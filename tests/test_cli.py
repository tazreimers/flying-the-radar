"""Tests for the command-line interface."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from email import policy
from email.parser import BytesParser
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from market_pdf_insights.cli import main
from market_pdf_insights.private_ingestion import import_manual_private_text
from market_pdf_insights.private_research_library import PrivateResearchLibrary
from market_pdf_insights.private_research_schema import (
    NumberToVerify,
    PersonalActionQuestion,
    PrivateResearchDocument,
    SourceExcerpt,
    StockRecommendation,
)
from market_pdf_insights.private_research_storage import initialize_private_research_store
from market_pdf_insights.private_settings import PrivateResearchSettings
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


class CliTests(unittest.TestCase):
    """Coverage for the summarize command."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_summarize_prints_summary_and_writes_requested_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "research.pdf"
            json_path = Path(tmp_dir) / "reports" / "research.json"
            markdown_path = Path(tmp_dir) / "reports" / "research.md"
            write_sample_pdf(
                pdf_path,
                ["ABC reports earnings growth. Risks include inflation and rate pressure."],
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "summarize",
                        str(pdf_path),
                        "--output",
                        str(json_path),
                        "--markdown",
                        str(markdown_path),
                        "--max-chars",
                        "1000",
                    ]
                )

            terminal_output = stdout.getvalue()
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(exit_code, 0)
            self.assertIn("Summary:", terminal_output)
            self.assertIn("Stance: mixed", terminal_output)
            self.assertIn(f"JSON: {json_path}", terminal_output)
            self.assertIn(f"Markdown: {markdown_path}", terminal_output)
            self.assertEqual(payload["metadata"]["model"], "placeholder")
            self.assertEqual(payload["market_stance"], "mixed")
            self.assertTrue(payload["key_claims"])
            self.assertEqual(payload["companies_or_tickers_mentioned"][0]["ticker"], "ABC")
            self.assertIn("#", markdown)
            self.assertIn("## Executive Summary", markdown)
            self.assertIn("ABC", markdown)

    def test_missing_pdf_returns_helpful_error(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main(["summarize", "missing.pdf", "--output", "unused.json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("error:", stderr.getvalue())
        self.assertIn("PDF file does not exist", stderr.getvalue())

    def test_brief_run_from_fixture_config_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = _write_brief_fixture_config(tmp_path)
            json_path = tmp_path / "out" / "brief.json"
            markdown_path = tmp_path / "out" / "brief.md"
            html_path = tmp_path / "out" / "brief.html"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "brief",
                        "run",
                        "--config",
                        str(config_path),
                        "--date",
                        "2026-05-12",
                        "--output",
                        str(json_path),
                        "--markdown",
                        str(markdown_path),
                        "--html",
                        str(html_path),
                        "--llm",
                        "placeholder",
                    ]
                )

            terminal_output = stdout.getvalue()
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertIn("Daily brief: 2026-05-12", terminal_output)
            self.assertIn(f"JSON: {json_path}", terminal_output)
            self.assertEqual(payload["briefing_date"], "2026-05-12")
            self.assertEqual(payload["market_stance"], "mixed")
            self.assertIn("## Executive Summary", markdown_path.read_text(encoding="utf-8"))
            self.assertIn("<h2>Executive Summary</h2>", html_path.read_text(encoding="utf-8"))

    def test_brief_validate_config_and_sources_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = _write_brief_fixture_config(tmp_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                validate_exit = main(
                    ["brief", "validate-config", "--config", str(config_path)]
                )
            with redirect_stdout(stdout):
                sources_exit = main(["brief", "sources", "--config", str(config_path)])

            output = stdout.getvalue()
            self.assertEqual(validate_exit, 0)
            self.assertEqual(sources_exit, 0)
            self.assertIn("Config valid", output)
            self.assertIn("fixture-market: Fixture Market", output)

    def test_brief_run_with_cache_can_repeat_from_fetched_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = _write_brief_fixture_config(tmp_path, cache=True)
            first_json_path = tmp_path / "out" / "first.json"
            second_json_path = tmp_path / "out" / "second.json"

            with redirect_stdout(io.StringIO()):
                first_exit = main(
                    [
                        "brief",
                        "run",
                        "--config",
                        str(config_path),
                        "--date",
                        "2026-05-12",
                        "--output",
                        str(first_json_path),
                    ]
                )
            with redirect_stdout(io.StringIO()):
                second_exit = main(
                    [
                        "brief",
                        "run",
                        "--config",
                        str(config_path),
                        "--date",
                        "2026-05-12",
                        "--output",
                        str(second_json_path),
                    ]
                )

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertTrue(first_json_path.exists())
            self.assertTrue(second_json_path.exists())

    def test_brief_send_dry_run_writes_eml_without_sending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = _write_brief_fixture_config(tmp_path)
            eml_path = tmp_path / "email" / "brief.eml"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "brief",
                        "send",
                        "--dry-run",
                        "--config",
                        str(config_path),
                        "--date",
                        "2026-05-12",
                        "--email-dry-run",
                        str(eml_path),
                    ]
                )

            parsed = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
            self.assertEqual(exit_code, 0)
            self.assertIn("Email dry-run", stdout.getvalue())
            self.assertTrue(parsed.is_multipart())
            self.assertEqual(parsed["To"], "reader@example.test")
            self.assertTrue(parsed["Subject"].startswith("Daily Market Brief: 2026-05-12"))

    def test_private_import_list_and_summarize_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            data_dir = tmp_path / "private-data"
            note_path = tmp_path / "private-note.txt"
            note_path.write_text(
                """
Under the Radar CLI Note
Issue Date: 2026-05-12

Recommendation: Buy
ABC update.
Risks: Liquidity risk
                """.strip(),
                encoding="utf-8",
            )
            import_stdout = io.StringIO()

            with redirect_stdout(import_stdout):
                import_exit = main(
                    ["private", "import", str(note_path), "--data-dir", str(data_dir)]
                )

            import_output = import_stdout.getvalue()
            document_id_match = re.search(r"- (private-[a-f0-9]+) \|", import_output)
            self.assertEqual(import_exit, 0)
            self.assertIn("Imported: 1; skipped: 0", import_output)
            self.assertIsNotNone(document_id_match)
            document_id = document_id_match.group(1) if document_id_match else ""

            list_stdout = io.StringIO()
            with redirect_stdout(list_stdout):
                list_exit = main(["private", "list", "--data-dir", str(data_dir)])

            summary_stdout = io.StringIO()
            with redirect_stdout(summary_stdout):
                summary_exit = main(
                    ["private", "summarize", document_id, "--data-dir", str(data_dir)]
                )

            self.assertEqual(list_exit, 0)
            self.assertEqual(summary_exit, 0)
            self.assertIn("Under the Radar CLI Note", list_stdout.getvalue())
            summary_output = summary_stdout.getvalue()
            self.assertIn("Recommendation label: Buy", summary_output)
            self.assertIn("ABC", summary_output)

    def test_private_search_history_and_compare_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            data_dir = tmp_path / "private-data"
            first_id, second_id = _seed_private_cli_library(data_dir)

            search_stdout = io.StringIO()
            with redirect_stdout(search_stdout):
                search_exit = main(
                    ["private", "search", "--ticker", "EXR", "--data-dir", str(data_dir)]
                )

            history_stdout = io.StringIO()
            with redirect_stdout(history_stdout):
                history_exit = main(
                    ["private", "history", "--ticker", "EXR", "--data-dir", str(data_dir)]
                )

            compare_stdout = io.StringIO()
            with redirect_stdout(compare_stdout):
                compare_exit = main(
                    [
                        "private",
                        "compare",
                        first_id,
                        second_id,
                        "--data-dir",
                        str(data_dir),
                    ]
                )

            self.assertEqual(search_exit, 0)
            self.assertEqual(history_exit, 0)
            self.assertEqual(compare_exit, 0)
            self.assertIn("EXR", search_stdout.getvalue())
            self.assertIn("speculative_buy", history_stdout.getvalue())
            self.assertIn("hold -> speculative_buy", compare_stdout.getvalue())


def _seed_private_cli_library(data_dir: Path) -> tuple[str, str]:
    settings = PrivateResearchSettings(local_data_dir=data_dir)
    store = initialize_private_research_store(settings)
    first = import_manual_private_text(
        "Under the Radar EXR May\nIssue Date: 2026-05-01\n\nRecommendation: Hold\nEXR.",
        settings=settings,
        store=store,
        title="Under the Radar EXR May",
    ).documents[0]
    second = import_manual_private_text(
        (
            "Under the Radar EXR June\nIssue Date: 2026-06-01\n\n"
            "Recommendation: Speculative Buy\nEXR."
        ),
        settings=settings,
        store=store,
        title="Under the Radar EXR June",
    ).documents[0]
    library = PrivateResearchLibrary(store)
    library.index_summary(_cli_private_summary(first.document_id, "2026-05-01", "hold", 1.0))
    library.index_summary(
        _cli_private_summary(second.document_id, "2026-06-01", "speculative_buy", 1.35)
    )
    return first.document_id, second.document_id


def _cli_private_summary(
    document_id: str,
    issue_date: str,
    rating: str,
    target: float,
) -> PrivateResearchDocument:
    recommendation = StockRecommendation(
        recommendation_id=f"rec-exr-{issue_date}",
        company_name="Example Resources",
        ticker="EXR",
        exchange="ASX",
        sector="materials",
        recommendation=rating,
        source_rating=rating.replace("_", " ").title(),
        stated_target_price=target,
        target_price_currency="AUD",
        recommendation_date=issue_date,
        risks=[],
        catalysts=[],
        numbers_to_verify=[
            NumberToVerify(value=f"AUD {target}", context="Source target price.")
        ],
        source_citation=SourceExcerpt(
            excerpt_id=f"excerpt-exr-{issue_date}",
            document_id=document_id,
            source_name="Under the Radar",
            document_title=f"Under the Radar EXR {issue_date}",
            section="Recommendation",
            excerpt="Short source-backed rating note.",
        ),
        confidence_score=0.7,
    )
    return PrivateResearchDocument(
        document_id=document_id,
        source_name="Under the Radar",
        document_title=f"Under the Radar EXR {issue_date}",
        issue_date=issue_date,
        document_summary="Private source summary.",
        recommendations=[recommendation],
        personal_action_questions=[
            PersonalActionQuestion(
                question_id=f"q-{document_id}",
                question="What target price assumption needs checking?",
                related_ticker="EXR",
                related_recommendation_id=recommendation.recommendation_id,
            )
        ],
        confidence_score=0.7,
    )


def _write_brief_fixture_config(tmp_path: Path, *, cache: bool = False) -> Path:
    fixture_path = tmp_path / "items.jsonl"
    fixture_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "market-1",
                        "title": "BHP rises as iron ore supports the ASX",
                        "body": "BHP and AUD rose while investors watched rates.",
                        "url": "https://example.test/bhp",
                        "published_at": "2026-05-12T01:00:00Z",
                        "tickers": ["BHP", "AUD"],
                    }
                ),
                json.dumps(
                    {
                        "id": "macro-1",
                        "title": "US yields pressure growth equities",
                        "body": "Treasury yields moved higher and created downside risk.",
                        "url": "https://example.test/yields",
                        "published_at": "2026-05-12T02:00:00Z",
                        "tickers": ["DGS10", "USD"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "daily-brief.toml"
    ingestion_section = (
        """

[ingestion]
cache_path = "cache/items.jsonl"
"""
        if cache
        else ""
    )
    config_path.write_text(
        f"""
watchlist = ["BHP", "AUD", "DGS10"]
{ingestion_section}

[llm]
backend = "placeholder"

[email]
sender = "briefs@example.test"
recipients = ["reader@example.test"]

[[sources]]
source_id = "fixture-market"
display_name = "Fixture Market"
kind = "local_fixture"
category = "australian_market"
fixture_path = "{fixture_path.name}"
terms_notes = "Fixture terms permit local test use."
terms_url = "https://example.test/terms"
""".strip(),
        encoding="utf-8",
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
