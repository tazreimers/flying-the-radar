"""Tests for private, user-provided research ingestion."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from market_pdf_insights.private_ingestion import (
    import_manual_private_text,
    import_private_file,
    import_private_path,
    import_uploaded_private_pdf,
    summarize_private_document,
)
from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateResearchPolicyError,
)
from market_pdf_insights.private_research_storage import (
    PrivateResearchStore,
    initialize_private_research_store,
)
from market_pdf_insights.private_settings import (
    PrivateImportSourceSettings,
    PrivateResearchSettings,
)
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


def test_manual_text_import_stores_normalized_document_and_summary(tmp_path: Path) -> None:
    settings, store = _private_store(tmp_path)

    result = import_manual_private_text(
        """
        Under the Radar Research Note
        Issue Date: 2026-05-12

        Portfolio Review
        Recommendation: Speculative Buy
        ABC remains on watch after the trading update.

        Risks: Execution risk
        Catalysts: Quarterly update
        """,
        title=None,
        settings=settings,
        store=store,
    )

    assert result.imported_count == 1
    assert result.skipped_count == 0
    document = result.documents[0]
    assert document.title == "Under the Radar Research Note"
    assert document.access_method == PrivateResearchAccessMethod.MANUAL_ENTRY
    assert document.metadata["source_type"] == "manual_text"
    assert document.metadata["issue_date"] == "2026-05-12"
    assert "Portfolio Review" in document.metadata["section_headings"]
    assert document.extracted_text_path is not None
    assert document.extracted_text_path.exists()
    assert not document.raw_document_stored
    assert document.raw_document_path is None

    summary = summarize_private_document(document.document_id, store=store)
    assert summary.recommendation_label == "Speculative Buy"
    assert "ABC" in summary.tickers
    assert summary.risks == ("Execution risk",)
    assert summary.catalysts == ("Quarterly update",)
    assert store.list_citations(document.document_id)


def test_file_imports_normalize_saved_email_text_html_and_eml(tmp_path: Path) -> None:
    settings, store = _private_store(tmp_path)
    text_email = tmp_path / "morning-note.txt"
    text_email.write_text(
        """
Subject: Under the Radar Morning Note
From: Research Desk <research@example.test>
Date: 12 May 2026

Recommendation: Hold
XYZ remains on watch into results.
        """.strip(),
        encoding="utf-8",
    )
    html_email = tmp_path / "html-note.html"
    html_email.write_text(
        """
<html><body>
<h1>Under the Radar HTML Note</h1>
<p>Issue Date: 2026-05-12</p>
<h2>Risks</h2>
<p>Risks: Liquidity risk</p>
<h2>Catalysts</h2>
<p>Catalysts: Contract award</p>
</body></html>
        """.strip(),
        encoding="utf-8",
    )
    eml_path = tmp_path / "saved-note.eml"
    message = EmailMessage()
    message["Subject"] = "Under the Radar Saved Email"
    message["From"] = "Research Desk <research@example.test>"
    message["Date"] = "Tue, 12 May 2026 08:00:00 +0800"
    message.set_content("Issue Date: 2026-05-12\n\nRecommendation: Buy\nDEF update.")
    eml_path.write_bytes(message.as_bytes())

    text_result = import_private_file(text_email, settings=settings, store=store)
    html_result = import_private_file(html_email, settings=settings, store=store)
    eml_result = import_private_file(eml_path, settings=settings, store=store)

    text_document = text_result.documents[0]
    assert text_document.title == "Under the Radar Morning Note"
    assert text_document.author == "Research Desk <research@example.test>"
    assert text_document.metadata["source_type"] == "text_email"
    assert text_document.metadata["original_filename"] == text_email.name

    html_document = html_result.documents[0]
    assert html_document.title == "Under the Radar HTML Note"
    assert html_document.metadata["source_type"] == "html_email"
    assert "Risks" in html_document.metadata["section_headings"]

    eml_document = eml_result.documents[0]
    assert eml_document.title == "Under the Radar Saved Email"
    assert eml_document.author == "Research Desk <research@example.test>"
    assert eml_document.metadata["source_type"] == "saved_email"


def test_directory_import_deduplicates_by_source_date_title_and_hash(tmp_path: Path) -> None:
    settings, store = _private_store(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    text = """
Under the Radar Duplicate Note
Issue Date: 2026-05-12

Recommendation: Buy
DUP update.
    """.strip()
    (inbox / "first.txt").write_text(text, encoding="utf-8")
    (inbox / "second.txt").write_text(text, encoding="utf-8")

    result = import_private_path(inbox, settings=settings, store=store)

    assert result.imported_count == 1
    assert result.skipped_count == 1
    assert len(store.list_documents()) == 1
    assert result.warnings == ("Duplicate private document skipped: Under the Radar Duplicate Note",)


def test_disabled_local_file_import_source_blocks_path_import(tmp_path: Path) -> None:
    settings, store = _private_store(
        tmp_path,
        import_sources=PrivateImportSourceSettings(local_file=False),
    )
    note_path = tmp_path / "note.txt"
    note_path.write_text(
        "Under the Radar Local Note\nIssue Date: 2026-05-12\n\nABC update.",
        encoding="utf-8",
    )

    with pytest.raises(PrivateResearchPolicyError, match="local_file"):
        import_private_file(note_path, settings=settings, store=store)


@pytest.mark.skipif(not has_pymupdf(), reason="PyMuPDF is not installed")
def test_pdf_path_and_uploaded_pdf_imports(tmp_path: Path) -> None:
    settings, store = _private_store(tmp_path)
    pdf_path = tmp_path / "local-note.pdf"
    write_sample_pdf(
        pdf_path,
        [
            (
                "Under the Radar PDF Note\nIssue Date: 2026-05-12\n"
                "Recommendation: Buy\nPDFX update."
            )
        ],
    )
    uploaded_path = tmp_path / "uploaded-note.pdf"
    write_sample_pdf(
        uploaded_path,
        [
            (
                "Under the Radar Uploaded PDF\nIssue Date: 2026-05-13\n"
                "Recommendation: Hold\nUPLD update."
            )
        ],
    )

    local_result = import_private_file(pdf_path, settings=settings, store=store)
    uploaded_result = import_uploaded_private_pdf(
        uploaded_path.read_bytes(),
        filename="uploaded-note.pdf",
        settings=settings,
        store=store,
    )

    local_document = local_result.documents[0]
    assert local_document.access_method == PrivateResearchAccessMethod.LOCAL_FILE
    assert local_document.metadata["source_type"] == "pdf"
    assert local_document.metadata["original_filename"] == "local-note.pdf"
    assert local_document.extracted_text_path is not None
    assert "PDFX" in local_document.extracted_text_path.read_text(encoding="utf-8")

    uploaded_document = uploaded_result.documents[0]
    assert uploaded_document.access_method == PrivateResearchAccessMethod.USER_UPLOAD
    assert uploaded_document.metadata["source_type"] == "uploaded_pdf"
    assert uploaded_document.metadata["original_filename"] == "uploaded-note.pdf"


def _private_store(
    tmp_path: Path,
    *,
    import_sources: PrivateImportSourceSettings | None = None,
) -> tuple[PrivateResearchSettings, PrivateResearchStore]:
    settings = PrivateResearchSettings(
        local_data_dir=tmp_path / "private",
        import_sources=import_sources or PrivateImportSourceSettings(),
    )
    return settings, initialize_private_research_store(settings)
