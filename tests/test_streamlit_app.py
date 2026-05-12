"""Tests for Streamlit app helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from market_pdf_insights.daily_brief_config import load_daily_brief_config
from market_pdf_insights.daily_brief_schema import DailyMarketBrief
from market_pdf_insights.llm_client import MockLLMClient
from market_pdf_insights.private_research_library import PrivateResearchLibrary
from market_pdf_insights.private_research_storage import initialize_private_research_store
from market_pdf_insights.private_settings import (
    PrivatePasswordProtectionSettings,
    PrivateResearchSettings,
    PrivateSettingsError,
    hash_private_password,
)
from market_pdf_insights.streamlit_app import (
    EXAMPLE_BRIEF_PATH,
    EXAMPLE_CONFIG_PATH,
    build_private_document_rows,
    build_private_recommendation_rows,
    build_private_research_downloads,
    clear_private_ui_authentication,
    import_private_upload_bytes,
    build_daily_brief_citation_rows,
    build_daily_brief_downloads,
    build_daily_brief_source_rows,
    build_daily_brief_verification_rows,
    build_daily_brief_watchlist_rows,
    load_daily_brief_fixture,
    mark_private_ui_authenticated,
    private_ui_session_is_authenticated,
    resolve_private_ui_password_hash,
    summarize_and_index_private_document,
    summarize_uploaded_pdf,
    verify_private_ui_password,
)
from market_pdf_insights.summarizer import SummarizerConfig
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


class StreamlitAppTests(unittest.TestCase):
    """Coverage for upload-to-summary plumbing without importing Streamlit."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_summarize_uploaded_pdf_uses_uploaded_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "uploaded.pdf"
            write_sample_pdf(pdf_path, ["ABC reports earnings growth."])

            client = MockLLMClient()
            report = summarize_uploaded_pdf(
                pdf_path.read_bytes(),
                filename="uploaded.pdf",
                client=client,
                config=SummarizerConfig(max_chunk_chars=1_000),
            )

        self.assertEqual(report.metadata["model"], "mock")
        self.assertEqual(report.metadata["chunk_count"], 1)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("ABC reports earnings growth", client.calls[0][0])

    def test_summarize_uploaded_pdf_rejects_empty_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            summarize_uploaded_pdf(
                b"",
                filename="empty.pdf",
                client=MockLLMClient(),
                config=SummarizerConfig(),
            )

    def test_load_daily_brief_fixture_returns_valid_brief(self) -> None:
        brief = load_daily_brief_fixture(EXAMPLE_BRIEF_PATH)

        self.assertIsInstance(brief, DailyMarketBrief)
        self.assertEqual(brief.briefing_date.isoformat(), "2026-05-12")
        self.assertTrue(brief.sources)

    def test_daily_brief_downloads_include_json_markdown_and_html(self) -> None:
        brief = load_daily_brief_fixture(EXAMPLE_BRIEF_PATH)

        downloads = build_daily_brief_downloads(brief)

        self.assertEqual([download.label for download in downloads], ["JSON", "Markdown", "HTML"])
        self.assertIn('"briefing_date"', downloads[0].content)
        self.assertIn("## Executive Summary", downloads[1].content)
        self.assertIn("<h2>Executive Summary</h2>", downloads[2].content)

    def test_daily_brief_source_rows_include_disabled_compliance_notices(self) -> None:
        config = load_daily_brief_config(EXAMPLE_CONFIG_PATH)

        rows = build_daily_brief_source_rows(config)

        local_fixture = next(row for row in rows if row["Source ID"] == "local-market-fixture")
        market_index = next(row for row in rows if row["Source ID"] == "market-index")
        self.assertEqual(local_fixture["Status"], "Enabled")
        self.assertEqual(market_index["Status"], "Disabled")
        self.assertIn("permission", market_index["Compliance Notes"].lower())
        self.assertIn("licence", market_index["Compliance Notes"].lower())

    def test_daily_brief_table_helpers_build_review_rows(self) -> None:
        brief = load_daily_brief_fixture(EXAMPLE_BRIEF_PATH)

        watchlist_rows = build_daily_brief_watchlist_rows(brief)
        citation_rows = build_daily_brief_citation_rows(brief)
        verification_rows = build_daily_brief_verification_rows(brief)

        self.assertTrue(watchlist_rows)
        self.assertEqual(citation_rows[0]["Citation ID"], "rba-policy")
        self.assertEqual(verification_rows[0]["Priority"], "medium")

    def test_private_ui_password_hash_resolution_and_session_helpers(self) -> None:
        password_hash = hash_private_password(
            "local private password",
            salt=b"0123456789abcdef",
            iterations=100_000,
        )
        settings = PrivateResearchSettings(
            password_protection=PrivatePasswordProtectionSettings(enabled=True)
        )
        now = datetime(2026, 5, 12, tzinfo=UTC)
        session_state: dict[str, object] = {}

        resolved = resolve_private_ui_password_hash(
            settings,
            environ={},
            secrets={"MARKET_PRIVATE_UI_PASSWORD_HASH": password_hash},
        )

        self.assertEqual(resolved, password_hash)
        self.assertTrue(
            verify_private_ui_password(
                "local private password",
                settings,
                environ={},
                secrets={"MARKET_PRIVATE_UI_PASSWORD_HASH": password_hash},
            )
        )
        self.assertFalse(
            verify_private_ui_password(
                "wrong password",
                settings,
                environ={},
                secrets={"MARKET_PRIVATE_UI_PASSWORD_HASH": password_hash},
            )
        )
        self.assertFalse(private_ui_session_is_authenticated(session_state, settings, now=now))
        mark_private_ui_authenticated(session_state, settings, now=now)
        self.assertTrue(private_ui_session_is_authenticated(session_state, settings, now=now))
        self.assertFalse(
            private_ui_session_is_authenticated(
                session_state,
                settings,
                now=now + timedelta(minutes=61),
            )
        )
        clear_private_ui_authentication(session_state)
        self.assertNotIn("private_authenticated_until", session_state)

    def test_private_ui_password_hash_missing_raises(self) -> None:
        settings = PrivateResearchSettings(
            password_protection=PrivatePasswordProtectionSettings(enabled=True)
        )

        with self.assertRaisesRegex(PrivateSettingsError, "MARKET_PRIVATE_UI_PASSWORD_HASH"):
            resolve_private_ui_password_hash(settings, environ={}, secrets={})

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_private_upload_pdf_can_summarize_and_index_with_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            pdf_path = tmp_path / "private.pdf"
            write_sample_pdf(
                pdf_path,
                [
                    (
                        "Example Resources (EXR.ASX)\n"
                        "Issue Date: 2026-05-12\n"
                        "Recommendation: Speculative Buy\n"
                        "Target Price: AUD 1.35\n"
                        "Risks: Funding risk.\n"
                        "Catalysts: Quarterly update."
                    )
                ],
            )
            settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")
            store = initialize_private_research_store(settings)

            result = import_private_upload_bytes(
                pdf_path.read_bytes(),
                filename="private.pdf",
                settings=settings,
                store=store,
            )
            document_id = result.documents[0].document_id
            summary = summarize_and_index_private_document(document_id, store=store)
            library = PrivateResearchLibrary(store)

            self.assertEqual(result.imported_count, 1)
            self.assertEqual(summary.recommendations[0].ticker, "EXR")
            self.assertEqual(summary.recommendations[0].recommendation, "speculative_buy")
            self.assertTrue(library.search())
            self.assertTrue(build_private_document_rows(store))
            self.assertTrue(build_private_recommendation_rows(store.list_recommendations()))

            downloads = build_private_research_downloads(summary)
            self.assertEqual([download.label for download in downloads], ["JSON", "Markdown"])
            self.assertIn('"recommendations"', downloads[0].content)
            self.assertIn("not personal financial advice", downloads[1].content)


if __name__ == "__main__":
    unittest.main()
