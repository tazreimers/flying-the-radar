from __future__ import annotations

from datetime import UTC, datetime

from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateSourceAttribution,
)
from market_pdf_insights.private_research_storage import (
    PrivateCitationRecord,
    PrivateDocumentRecord,
    PrivateResearchStore,
    PrivateSummaryRecord,
    initialize_private_research_store,
)
from market_pdf_insights.private_settings import PrivateResearchSettings, PrivateRetentionPolicy


def test_private_store_initializes_and_round_trips_records(tmp_path) -> None:
    store = PrivateResearchStore(tmp_path / "private.sqlite3")
    document = _document(tmp_path)
    summary = PrivateSummaryRecord(
        summary_id="summary-1",
        document_id=document.document_id,
        summary_text="Synthetic private research summary.",
        recommendation_label="Speculative Buy",
        tickers=("ABC",),
        risks=("Execution risk",),
        catalysts=("Quarterly update",),
        generated_at=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        model="mock",
    )
    citation = PrivateCitationRecord(
        citation_id="citation-1",
        document_id=document.document_id,
        summary_id=summary.summary_id,
        label="Page 1",
        location="p. 1",
        snippet="Synthetic source-backed note.",
        created_at=datetime(2026, 5, 12, 9, 1, tzinfo=UTC),
    )

    store.add_document(document)
    store.add_summary(summary)
    store.add_citation(citation)

    loaded_document = store.get_document(document.document_id)
    assert loaded_document is not None
    assert loaded_document.title == "Synthetic Under the Radar Note"
    assert loaded_document.metadata == {"sector": "technology"}
    assert store.list_documents()[0].document_id == document.document_id
    assert store.get_latest_summary(document.document_id) == summary
    assert store.list_citations(document.document_id) == [citation]


def test_initialize_private_research_store_uses_settings(tmp_path) -> None:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")

    store = initialize_private_research_store(settings)

    assert store.path == settings.database_path
    assert settings.database_path.exists()
    assert settings.extracted_text_dir.exists()


def test_private_store_delete_document_cascades_and_removes_files(tmp_path) -> None:
    raw_path = tmp_path / "raw.pdf"
    text_path = tmp_path / "text.txt"
    raw_path.write_text("raw", encoding="utf-8")
    text_path.write_text("text", encoding="utf-8")
    store = PrivateResearchStore(tmp_path / "private.sqlite3")
    document = _document(
        tmp_path,
        raw_document_path=raw_path,
        extracted_text_path=text_path,
        raw_document_stored=True,
    )
    summary = PrivateSummaryRecord(
        summary_id="summary-1",
        document_id=document.document_id,
        summary_text="Summary",
    )
    citation = PrivateCitationRecord(
        citation_id="citation-1",
        document_id=document.document_id,
        summary_id=summary.summary_id,
        label="Page 1",
    )
    store.add_document(document)
    store.add_summary(summary)
    store.add_citation(citation)

    deleted = store.delete_document(document.document_id, delete_files=True)

    assert deleted
    assert store.get_document(document.document_id) is None
    assert store.list_summaries(document.document_id) == []
    assert store.list_citations(document.document_id) == []
    assert not raw_path.exists()
    assert not text_path.exists()


def test_private_store_cleanup_retention_deletes_old_summaries(tmp_path) -> None:
    store = PrivateResearchStore(tmp_path / "private.sqlite3")
    document = _document(tmp_path)
    old_summary = PrivateSummaryRecord(
        summary_id="old-summary",
        document_id=document.document_id,
        summary_text="Old summary",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    new_summary = PrivateSummaryRecord(
        summary_id="new-summary",
        document_id=document.document_id,
        summary_text="New summary",
        generated_at=datetime(2026, 5, 12, tzinfo=UTC),
    )
    store.add_document(document)
    store.add_summary(old_summary)
    store.add_summary(new_summary)

    counts = store.cleanup_retention(
        PrivateRetentionPolicy(summary_retention_days=30),
        now=datetime(2026, 5, 12, tzinfo=UTC),
    )

    assert counts["summaries"] == 1
    assert [summary.summary_id for summary in store.list_summaries()] == ["new-summary"]


def test_private_store_cleanup_can_clear_raw_paths_without_metadata_delete(tmp_path) -> None:
    raw_path = tmp_path / "raw.pdf"
    raw_path.write_text("raw", encoding="utf-8")
    store = PrivateResearchStore(tmp_path / "private.sqlite3")
    document = _document(
        tmp_path,
        raw_document_path=raw_path,
        raw_document_stored=True,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.add_document(document)

    counts = store.cleanup_retention(
        PrivateRetentionPolicy(
            store_raw_documents=True,
            raw_document_retention_days=30,
        ),
        now=datetime(2026, 5, 12, tzinfo=UTC),
        delete_files=True,
    )

    loaded = store.get_document(document.document_id)
    assert counts["raw_files"] == 1
    assert loaded is not None
    assert loaded.raw_document_path is None
    assert not loaded.raw_document_stored
    assert not raw_path.exists()


def _document(
    tmp_path,
    *,
    raw_document_path=None,
    extracted_text_path=None,
    raw_document_stored=False,
    imported_at=datetime(2026, 5, 12, 8, 0, tzinfo=UTC),
) -> PrivateDocumentRecord:
    attribution = PrivateSourceAttribution(
        source_name="Under the Radar",
        document_title="Synthetic Under the Radar Note",
        access_method=PrivateResearchAccessMethod.USER_UPLOAD,
        url="https://example.test/private-note",
        author="Fixture Author",
        published_at=datetime(2026, 5, 11, tzinfo=UTC),
        retrieved_at=imported_at,
        subscription_notes="Subscriber-provided fixture.",
        licence_notes="Do not redistribute.",
    )
    return PrivateDocumentRecord(
        document_id="document-1",
        title="Synthetic Under the Radar Note",
        source_name="Under the Radar",
        access_method=PrivateResearchAccessMethod.USER_UPLOAD,
        imported_at=imported_at,
        published_at=datetime(2026, 5, 11, tzinfo=UTC),
        source_url="https://example.test/private-note",
        author="Fixture Author",
        raw_document_path=raw_document_path,
        extracted_text_path=extracted_text_path or tmp_path / "text.txt",
        raw_document_stored=raw_document_stored,
        attribution=attribution,
        metadata={"sector": "technology"},
    )
