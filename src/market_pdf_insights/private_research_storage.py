"""SQLite storage for private subscribed research metadata and summaries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateSourceAttribution,
)
from market_pdf_insights.private_settings import PrivateResearchSettings, PrivateRetentionPolicy


class PrivateDocumentRecord(BaseModel):
    """Stored private document metadata."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    title: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    access_method: PrivateResearchAccessMethod
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None
    source_url: str | None = None
    author: str | None = None
    raw_document_path: Path | None = None
    extracted_text_path: Path | None = None
    raw_document_stored: bool = False
    attribution: PrivateSourceAttribution
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("imported_at")
    @classmethod
    def _require_imported_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("imported_at must include timezone information")
        return value


class PrivateSummaryRecord(BaseModel):
    """Stored private document summary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    document_id: str = Field(min_length=1)
    summary_text: str = Field(min_length=1)
    recommendation_label: str | None = None
    tickers: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    catalysts: tuple[str, ...] = ()
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str | None = None

    @field_validator("generated_at")
    @classmethod
    def _require_generated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must include timezone information")
        return value


class PrivateCitationRecord(BaseModel):
    """Stored citation or source-backed location for private summaries."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    citation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1)
    document_id: str = Field(min_length=1)
    summary_id: str | None = None
    label: str = Field(min_length=1)
    location: str | None = None
    snippet: str | None = Field(default=None, max_length=280)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at")
    @classmethod
    def _require_created_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include timezone information")
        return value


class PrivateResearchStore:
    """Local SQLite store for private research records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        """Create database tables if needed."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def add_document(self, document: PrivateDocumentRecord) -> PrivateDocumentRecord:
        """Insert or replace a private document record."""

        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO private_documents (
                    document_id, title, source_name, access_method, imported_at,
                    published_at, source_url, author, raw_document_path,
                    extracted_text_path, raw_document_stored, attribution_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _document_values(document),
            )
        return document

    def get_document(self, document_id: str) -> PrivateDocumentRecord | None:
        """Return one document by id."""

        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM private_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return _document_from_row(row) if row else None

    def list_documents(self) -> list[PrivateDocumentRecord]:
        """Return all documents ordered by import time."""

        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM private_documents ORDER BY imported_at DESC, title"
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def add_summary(self, summary: PrivateSummaryRecord) -> PrivateSummaryRecord:
        """Insert or replace a summary."""

        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO private_summaries (
                    summary_id, document_id, summary_text, recommendation_label,
                    tickers_json, risks_json, catalysts_json, generated_at, model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _summary_values(summary),
            )
        return summary

    def get_latest_summary(self, document_id: str) -> PrivateSummaryRecord | None:
        """Return the latest summary for a document."""

        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM private_summaries
                WHERE document_id = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        return _summary_from_row(row) if row else None

    def list_summaries(self, document_id: str | None = None) -> list[PrivateSummaryRecord]:
        """Return summaries, optionally filtered by document."""

        self.initialize()
        query = "SELECT * FROM private_summaries"
        params: tuple[str, ...] = ()
        if document_id is not None:
            query += " WHERE document_id = ?"
            params = (document_id,)
        query += " ORDER BY generated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_summary_from_row(row) for row in rows]

    def add_citation(self, citation: PrivateCitationRecord) -> PrivateCitationRecord:
        """Insert or replace a private citation."""

        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO private_citations (
                    citation_id, document_id, summary_id, label, location, snippet, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                _citation_values(citation),
            )
        return citation

    def list_citations(self, document_id: str | None = None) -> list[PrivateCitationRecord]:
        """Return citations, optionally filtered by document."""

        self.initialize()
        query = "SELECT * FROM private_citations"
        params: tuple[str, ...] = ()
        if document_id is not None:
            query += " WHERE document_id = ?"
            params = (document_id,)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_citation_from_row(row) for row in rows]

    def delete_document(self, document_id: str, *, delete_files: bool = False) -> bool:
        """Delete a document and cascaded summaries/citations."""

        self.initialize()
        document = self.get_document(document_id)
        if document is None:
            return False
        if delete_files:
            _delete_paths([document.raw_document_path, document.extracted_text_path])
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM private_documents WHERE document_id = ?",
                (document_id,),
            ).rowcount
        return deleted > 0

    def cleanup_retention(
        self,
        policy: PrivateRetentionPolicy,
        *,
        now: datetime | None = None,
        delete_files: bool = False,
    ) -> dict[str, int]:
        """Apply retention policy and return deletion counts."""

        self.initialize()
        reference_time = now or datetime.now(UTC)
        counts = {"documents": 0, "summaries": 0, "raw_files": 0, "text_files": 0}
        if policy.summary_retention_days is not None:
            counts["summaries"] = self._delete_summaries_before(
                reference_time - timedelta(days=policy.summary_retention_days)
            )
        if policy.metadata_retention_days is not None:
            cutoff = reference_time - timedelta(days=policy.metadata_retention_days)
            for document in self._documents_before(cutoff):
                if self.delete_document(document.document_id, delete_files=delete_files):
                    counts["documents"] += 1
        if policy.raw_document_retention_days is not None:
            cutoff = reference_time - timedelta(days=policy.raw_document_retention_days)
            counts["raw_files"] = self._clear_raw_paths_before(cutoff, delete_files=delete_files)
        if policy.extracted_text_retention_days is not None:
            cutoff = reference_time - timedelta(days=policy.extracted_text_retention_days)
            counts["text_files"] = self._clear_text_paths_before(cutoff, delete_files=delete_files)
        return counts

    def _delete_summaries_before(self, cutoff: datetime) -> int:
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM private_summaries WHERE generated_at < ?",
                (_to_iso(cutoff),),
            ).rowcount

    def _documents_before(self, cutoff: datetime) -> list[PrivateDocumentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM private_documents WHERE imported_at < ?",
                (_to_iso(cutoff),),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def _clear_raw_paths_before(self, cutoff: datetime, *, delete_files: bool) -> int:
        return self._clear_document_paths_before(
            cutoff,
            path_column="raw_document_path",
            stored_column="raw_document_stored",
            delete_files=delete_files,
        )

    def _clear_text_paths_before(self, cutoff: datetime, *, delete_files: bool) -> int:
        return self._clear_document_paths_before(
            cutoff,
            path_column="extracted_text_path",
            stored_column=None,
            delete_files=delete_files,
        )

    def _clear_document_paths_before(
        self,
        cutoff: datetime,
        *,
        path_column: str,
        stored_column: str | None,
        delete_files: bool,
    ) -> int:
        documents = self._documents_before(cutoff)
        paths = [getattr(document, path_column) for document in documents]
        if delete_files:
            _delete_paths(paths)
        set_clause = f"{path_column} = NULL"
        if stored_column is not None:
            set_clause += f", {stored_column} = 0"
        with self._connect() as conn:
            return conn.execute(
                f"UPDATE private_documents SET {set_clause} WHERE imported_at < ?",
                (_to_iso(cutoff),),
            ).rowcount

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def initialize_private_research_store(settings: PrivateResearchSettings) -> PrivateResearchStore:
    """Ensure directories and return an initialized private store."""

    settings.ensure_local_directories()
    store = PrivateResearchStore(settings.database_path)
    store.initialize()
    return store


def _document_values(document: PrivateDocumentRecord) -> tuple[Any, ...]:
    return (
        document.document_id,
        document.title,
        document.source_name,
        document.access_method.value,
        _to_iso(document.imported_at),
        _to_iso(document.published_at),
        document.source_url,
        document.author,
        _path_to_str(document.raw_document_path),
        _path_to_str(document.extracted_text_path),
        int(document.raw_document_stored),
        document.attribution.model_dump_json(),
        json.dumps(document.metadata),
    )


def _summary_values(summary: PrivateSummaryRecord) -> tuple[Any, ...]:
    return (
        summary.summary_id,
        summary.document_id,
        summary.summary_text,
        summary.recommendation_label,
        json.dumps(list(summary.tickers)),
        json.dumps(list(summary.risks)),
        json.dumps(list(summary.catalysts)),
        _to_iso(summary.generated_at),
        summary.model,
    )


def _citation_values(citation: PrivateCitationRecord) -> tuple[Any, ...]:
    return (
        citation.citation_id,
        citation.document_id,
        citation.summary_id,
        citation.label,
        citation.location,
        citation.snippet,
        _to_iso(citation.created_at),
    )


def _document_from_row(row: sqlite3.Row) -> PrivateDocumentRecord:
    return PrivateDocumentRecord(
        document_id=row["document_id"],
        title=row["title"],
        source_name=row["source_name"],
        access_method=PrivateResearchAccessMethod(row["access_method"]),
        imported_at=_parse_datetime(row["imported_at"]),
        published_at=_parse_optional_datetime(row["published_at"]),
        source_url=row["source_url"],
        author=row["author"],
        raw_document_path=_optional_path(row["raw_document_path"]),
        extracted_text_path=_optional_path(row["extracted_text_path"]),
        raw_document_stored=bool(row["raw_document_stored"]),
        attribution=PrivateSourceAttribution.model_validate_json(row["attribution_json"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def _summary_from_row(row: sqlite3.Row) -> PrivateSummaryRecord:
    return PrivateSummaryRecord(
        summary_id=row["summary_id"],
        document_id=row["document_id"],
        summary_text=row["summary_text"],
        recommendation_label=row["recommendation_label"],
        tickers=tuple(json.loads(row["tickers_json"] or "[]")),
        risks=tuple(json.loads(row["risks_json"] or "[]")),
        catalysts=tuple(json.loads(row["catalysts_json"] or "[]")),
        generated_at=_parse_datetime(row["generated_at"]),
        model=row["model"],
    )


def _citation_from_row(row: sqlite3.Row) -> PrivateCitationRecord:
    return PrivateCitationRecord(
        citation_id=row["citation_id"],
        document_id=row["document_id"],
        summary_id=row["summary_id"],
        label=row["label"],
        location=row["location"],
        snippet=row["snippet"],
        created_at=_parse_datetime(row["created_at"]),
    )


def _delete_paths(paths: Iterable[Path | None]) -> None:
    for path in paths:
        if path is not None and path.exists() and path.is_file():
            path.unlink()


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_optional_datetime(value: str | None) -> datetime | None:
    return _parse_datetime(value) if value else None


def _path_to_str(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS private_documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    access_method TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    published_at TEXT,
    source_url TEXT,
    author TEXT,
    raw_document_path TEXT,
    extracted_text_path TEXT,
    raw_document_stored INTEGER NOT NULL DEFAULT 0,
    attribution_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS private_summaries (
    summary_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    recommendation_label TEXT,
    tickers_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    catalysts_json TEXT NOT NULL DEFAULT '[]',
    generated_at TEXT NOT NULL,
    model TEXT,
    FOREIGN KEY (document_id)
        REFERENCES private_documents(document_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS private_citations (
    citation_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    summary_id TEXT,
    label TEXT NOT NULL,
    location TEXT,
    snippet TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id)
        REFERENCES private_documents(document_id)
        ON DELETE CASCADE,
    FOREIGN KEY (summary_id)
        REFERENCES private_summaries(summary_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_private_documents_imported_at
    ON private_documents(imported_at);
CREATE INDEX IF NOT EXISTS idx_private_summaries_document_id
    ON private_summaries(document_id);
CREATE INDEX IF NOT EXISTS idx_private_citations_document_id
    ON private_citations(document_id);
"""
