"""Private importers for user-provided subscribed research."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from pydantic import BaseModel, ConfigDict, Field

from market_pdf_insights.pdf_loader import load_pdf_text
from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateResearchPolicyError,
    PrivateSourceAttribution,
    default_private_research_boundary,
)
from market_pdf_insights.private_research_storage import (
    PrivateCitationRecord,
    PrivateDocumentRecord,
    PrivateResearchStore,
    PrivateSummaryRecord,
)
from market_pdf_insights.private_settings import PrivateResearchSettings


class PrivateImportError(ValueError):
    """Raised when a private import cannot be completed."""


class PrivateDocumentImportPayload(BaseModel):
    """Normalized private document payload before storage."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    source_name: str = "Under the Radar"
    source_type: str = Field(min_length=1)
    access_method: PrivateResearchAccessMethod
    original_filename: str | None = None
    source_url: str | None = None
    author: str | None = None
    issue_date: date | None = None
    extracted_text: str = Field(min_length=1)
    section_headings: tuple[str, ...] = ()
    content_hash: str = Field(min_length=1)
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    subscription_notes: str | None = None
    licence_notes: str | None = "Private personal-use import. Do not redistribute."

    @property
    def deduplication_key(self) -> str:
        """Return a stable key from source/date/title/hash."""

        issue = self.issue_date.isoformat() if self.issue_date else "undated"
        title_key = _slug(self.title)
        return f"{_slug(self.source_name)}:{issue}:{title_key}:{self.content_hash[:16]}"

    @property
    def document_id(self) -> str:
        """Return a deterministic document id for deduplication."""

        digest = hashlib.sha256(self.deduplication_key.encode("utf-8")).hexdigest()
        return f"private-{digest[:24]}"


@dataclass(frozen=True)
class PrivateImportResult:
    """Result from importing one or more private documents."""

    documents: tuple[PrivateDocumentRecord, ...]
    imported_count: int
    skipped_count: int
    warnings: tuple[str, ...] = ()


def import_private_path(
    path: str | Path,
    *,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    source_name: str = "Under the Radar",
) -> PrivateImportResult:
    """Import a private file or directory without logged-in automation."""

    import_path = Path(path).expanduser()
    if not import_path.exists():
        raise FileNotFoundError(import_path)
    if import_path.is_dir():
        documents: list[PrivateDocumentRecord] = []
        imported_count = 0
        skipped = 0
        warnings: list[str] = []
        for child in _iter_importable_files(import_path):
            result = import_private_file(
                child,
                settings=settings,
                store=store,
                source_name=source_name,
            )
            documents.extend(result.documents)
            imported_count += result.imported_count
            skipped += result.skipped_count
            warnings.extend(result.warnings)
        return PrivateImportResult(
            documents=tuple(documents),
            imported_count=imported_count,
            skipped_count=skipped,
            warnings=tuple(warnings),
        )
    return import_private_file(
        import_path,
        settings=settings,
        store=store,
        source_name=source_name,
    )


def import_private_file(
    path: str | Path,
    *,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    source_name: str = "Under the Radar",
) -> PrivateImportResult:
    """Import one private PDF, HTML, text, or saved email file."""

    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if not file_path.is_file():
        raise PrivateImportError(f"Expected a file, got directory: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        payload = _payload_from_pdf(file_path, source_name=source_name)
    elif suffix in {".html", ".htm"}:
        payload = _payload_from_html_file(file_path, source_name=source_name)
    elif suffix in {".txt", ".md"}:
        payload = _payload_from_text_file(file_path, source_name=source_name)
    elif suffix == ".eml":
        payload = _payload_from_eml_file(file_path, source_name=source_name)
    else:
        raise PrivateImportError(
            f"Unsupported private import file type: {file_path.suffix or file_path.name}"
        )

    return store_private_import(payload, settings=settings, store=store, source_path=file_path)


def import_manual_private_text(
    text: str,
    *,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    title: str | None = None,
    source_name: str = "Under the Radar",
) -> PrivateImportResult:
    """Import manually pasted private text."""

    _assert_import_enabled(settings, PrivateResearchAccessMethod.MANUAL_ENTRY)
    normalized = _clean_text(text)
    if not normalized:
        raise PrivateImportError("Manual text import is empty.")
    payload = _payload_from_text(
        normalized,
        source_name=source_name,
        source_type="manual_text",
        access_method=PrivateResearchAccessMethod.MANUAL_ENTRY,
        original_filename=None,
        title=title,
    )
    return store_private_import(payload, settings=settings, store=store)


def import_uploaded_private_pdf(
    pdf_bytes: bytes,
    *,
    filename: str,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    source_name: str = "Under the Radar",
) -> PrivateImportResult:
    """Import uploaded PDF bytes without keeping a raw copy unless configured."""

    if not pdf_bytes:
        raise PrivateImportError("Uploaded private PDF is empty.")
    with tempfile.TemporaryDirectory() as tmp_dir:
        safe_filename = Path(filename).name or "uploaded.pdf"
        upload_path = Path(tmp_dir) / safe_filename
        if upload_path.suffix.lower() != ".pdf":
            upload_path = upload_path.with_suffix(".pdf")
            safe_filename = upload_path.name
        upload_path.write_bytes(pdf_bytes)
        payload = _payload_from_pdf(upload_path, source_name=source_name).model_copy(
            update={
                "source_type": "uploaded_pdf",
                "access_method": PrivateResearchAccessMethod.USER_UPLOAD,
                "original_filename": safe_filename,
            }
        )
        return store_private_import(
            payload,
            settings=settings,
            store=store,
            source_path=upload_path,
        )


def store_private_import(
    payload: PrivateDocumentImportPayload,
    *,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    source_path: Path | None = None,
) -> PrivateImportResult:
    """Store a normalized private import payload."""

    default_private_research_boundary().assert_access_method_allowed(payload.access_method)
    _assert_import_enabled(settings, payload.access_method)
    settings.ensure_local_directories()
    store.initialize()
    existing = store.get_document(payload.document_id)
    if existing is not None:
        return PrivateImportResult(
            documents=(existing,),
            imported_count=0,
            skipped_count=1,
            warnings=(f"Duplicate private document skipped: {existing.title}",),
        )

    text_path = _write_extracted_text(payload, settings)
    raw_path = _store_raw_document(source_path, payload, settings)
    attribution = PrivateSourceAttribution(
        source_name=payload.source_name,
        document_title=payload.title,
        access_method=payload.access_method,
        url=payload.source_url,
        author=payload.author,
        published_at=_date_to_datetime(payload.issue_date),
        retrieved_at=payload.imported_at,
        subscription_notes=payload.subscription_notes,
        licence_notes=payload.licence_notes,
    )
    document = PrivateDocumentRecord(
        document_id=payload.document_id,
        title=payload.title,
        source_name=payload.source_name,
        access_method=payload.access_method,
        imported_at=payload.imported_at,
        published_at=_date_to_datetime(payload.issue_date),
        source_url=payload.source_url,
        author=payload.author,
        raw_document_path=raw_path,
        extracted_text_path=text_path,
        raw_document_stored=raw_path is not None,
        attribution=attribution,
        metadata={
            "deduplication_key": payload.deduplication_key,
            "content_hash": payload.content_hash,
            "source_type": payload.source_type,
            "original_filename": payload.original_filename,
            "issue_date": payload.issue_date.isoformat() if payload.issue_date else None,
            "section_headings": list(payload.section_headings),
            "text_char_count": len(payload.extracted_text),
        },
    )
    store.add_document(document)
    return PrivateImportResult(
        documents=(document,),
        imported_count=1,
        skipped_count=0,
    )


def summarize_private_document(
    document_id: str,
    *,
    store: PrivateResearchStore,
    model: str = "private-local-placeholder",
) -> PrivateSummaryRecord:
    """Create a local deterministic private summary from extracted text."""

    document = store.get_document(document_id)
    if document is None:
        raise PrivateImportError(f"Unknown private document: {document_id}")
    if document.extracted_text_path is None or not document.extracted_text_path.exists():
        raise PrivateImportError(f"Extracted text is missing for document: {document_id}")

    text = document.extracted_text_path.read_text(encoding="utf-8")
    summary = _local_summary(text)
    record = PrivateSummaryRecord(
        document_id=document.document_id,
        summary_text=summary,
        recommendation_label=_find_recommendation_label(text),
        tickers=_extract_tickers(text),
        risks=_extract_prefixed_items(text, ("risk", "risks")),
        catalysts=_extract_prefixed_items(text, ("catalyst", "catalysts")),
        model=model,
    )
    store.add_summary(record)
    citation = PrivateCitationRecord(
        document_id=document.document_id,
        summary_id=record.summary_id,
        label=document.title,
        location="extracted text",
        snippet=_short_snippet(text, max_words=36, max_chars=220),
    )
    store.add_citation(citation)
    return record


def private_document_display_rows(
    documents: Sequence[PrivateDocumentRecord],
) -> list[dict[str, str]]:
    """Return rows suitable for CLI/UI document lists."""

    rows: list[dict[str, str]] = []
    for document in documents:
        issue_date = document.metadata.get("issue_date") or ""
        rows.append(
            {
                "document_id": document.document_id,
                "title": document.title,
                "source": document.source_name,
                "issue_date": str(issue_date),
                "source_type": str(document.metadata.get("source_type") or ""),
                "filename": str(document.metadata.get("original_filename") or ""),
            }
        )
    return rows


def _payload_from_pdf(path: Path, *, source_name: str) -> PrivateDocumentImportPayload:
    loaded_pdf = load_pdf_text(path)
    text = _clean_text(loaded_pdf.text)
    return _payload_from_text(
        text,
        source_name=source_name,
        source_type="pdf",
        access_method=PrivateResearchAccessMethod.LOCAL_FILE,
        original_filename=path.name,
        content_bytes=path.read_bytes(),
    )


def _payload_from_text_file(path: Path, *, source_name: str) -> PrivateDocumentImportPayload:
    text = _clean_text(path.read_text(encoding="utf-8"))
    is_email = _looks_like_email_text(text)
    return _payload_from_text(
        text,
        source_name=source_name,
        source_type="text_email" if is_email else "text",
        access_method=PrivateResearchAccessMethod.EMAIL_FORWARD
        if is_email
        else PrivateResearchAccessMethod.LOCAL_FILE,
        original_filename=path.name,
        title=_extract_email_header(text, "subject") if is_email else None,
        author=_extract_email_header(text, "from") if is_email else None,
        content_bytes=path.read_bytes(),
    )


def _payload_from_html_file(path: Path, *, source_name: str) -> PrivateDocumentImportPayload:
    raw_html = path.read_text(encoding="utf-8")
    text = _clean_text(_html_to_text(raw_html))
    return _payload_from_text(
        text,
        source_name=source_name,
        source_type="html_email",
        access_method=PrivateResearchAccessMethod.EMAIL_FORWARD,
        original_filename=path.name,
        content_bytes=path.read_bytes(),
    )


def _payload_from_eml_file(path: Path, *, source_name: str) -> PrivateDocumentImportPayload:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    subject = str(message.get("subject") or "").strip() or None
    author = str(message.get("from") or "").strip() or None
    text = _clean_text(_message_text(message))
    return _payload_from_text(
        text,
        source_name=source_name,
        source_type="saved_email",
        access_method=PrivateResearchAccessMethod.EMAIL_FORWARD,
        original_filename=path.name,
        title=subject,
        author=author,
        content_bytes=path.read_bytes(),
    )


def _payload_from_text(
    text: str,
    *,
    source_name: str,
    source_type: str,
    access_method: PrivateResearchAccessMethod,
    original_filename: str | None,
    title: str | None = None,
    author: str | None = None,
    content_bytes: bytes | None = None,
) -> PrivateDocumentImportPayload:
    if not text:
        raise PrivateImportError("Private import produced no extracted text.")
    issue_date = _extract_issue_date(text)
    resolved_title = title or _extract_title(text, fallback=original_filename)
    content_hash = hashlib.sha256(content_bytes or text.encode("utf-8")).hexdigest()
    return PrivateDocumentImportPayload(
        title=resolved_title,
        source_name=source_name,
        source_type=source_type,
        access_method=access_method,
        original_filename=original_filename,
        author=author,
        issue_date=issue_date,
        extracted_text=text,
        section_headings=tuple(_extract_section_headings(text)),
        content_hash=content_hash,
        subscription_notes="User-provided private research import.",
    )


def _iter_importable_files(path: Path) -> Iterable[Path]:
    suffixes = {".pdf", ".txt", ".md", ".html", ".htm", ".eml"}
    for child in sorted(path.rglob("*")):
        if child.is_file() and child.suffix.lower() in suffixes:
            yield child


def _assert_import_enabled(
    settings: PrivateResearchSettings,
    method: PrivateResearchAccessMethod,
) -> None:
    source_settings = settings.import_sources
    enabled = {
        PrivateResearchAccessMethod.USER_UPLOAD: source_settings.user_upload,
        PrivateResearchAccessMethod.LOCAL_FILE: source_settings.local_file,
        PrivateResearchAccessMethod.EMAIL_FORWARD: source_settings.email_forward,
        PrivateResearchAccessMethod.MANUAL_ENTRY: source_settings.manual_entry,
        PrivateResearchAccessMethod.SUBSCRIPTION_EXPORT: source_settings.subscription_export,
        PrivateResearchAccessMethod.LOGGED_IN_AUTOMATION: source_settings.logged_in_automation,
    }[method]
    if not enabled:
        raise PrivateResearchPolicyError(f"Private import source is disabled: {method.value}")


def _write_extracted_text(
    payload: PrivateDocumentImportPayload,
    settings: PrivateResearchSettings,
) -> Path:
    text_path = settings.extracted_text_dir / f"{payload.document_id}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(payload.extracted_text, encoding="utf-8")
    return text_path


def _store_raw_document(
    source_path: Path | None,
    payload: PrivateDocumentImportPayload,
    settings: PrivateResearchSettings,
) -> Path | None:
    if not settings.retention.store_raw_documents or source_path is None:
        return None
    raw_dir = settings.raw_documents_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix or ".bin"
    raw_path = raw_dir / f"{payload.document_id}{suffix}"
    shutil.copy2(source_path, raw_path)
    return raw_path


def _message_text(message) -> str:
    if message.is_multipart():
        html_part = ""
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                return str(part.get_content())
            if content_type == "text/html" and not html_part:
                html_part = _html_to_text(str(part.get_content()))
        return html_part
    content = str(message.get_content())
    if message.get_content_type() == "text/html":
        return _html_to_text(content)
    return content


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.text()


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r" *\n *", "\n", text)
        return _clean_text(text)


def _clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False
    return "\n".join(collapsed).strip()


def _looks_like_email_text(text: str) -> bool:
    lowered = text[:500].lower()
    return any(lowered.startswith(prefix) for prefix in ("subject:", "from:", "date:"))


def _extract_email_header(text: str, header: str) -> str | None:
    pattern = rf"^{re.escape(header)}\s*:\s*(.+)$"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip() or None


def _extract_title(text: str, *, fallback: str | None) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--- Page"):
            continue
        if _header_label(stripped):
            continue
        return stripped[:160]
    if fallback:
        return Path(fallback).stem.replace("_", " ").replace("-", " ").title()
    return "Private Research Note"


def _extract_issue_date(text: str) -> date | None:
    patterns = [
        r"\b(20\d{2}-\d{2}-\d{2})\b",
        r"\b(\d{1,2})\s+([A-Z][a-z]+)\s+(20\d{2})\b",
        r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s*(20\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if len(match.groups()) == 1:
                return date.fromisoformat(match.group(1))
            if match.group(1).isdigit():
                return datetime.strptime(match.group(0), "%d %B %Y").date()
            return datetime.strptime(match.group(0), "%B %d, %Y").date()
        except ValueError:
            continue
    return None


def _extract_section_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip(":")
        if len(stripped) < 3 or len(stripped) > 80:
            continue
        if stripped.startswith("--- Page"):
            continue
        if _header_label(stripped) or re.match(r"^[A-Z][A-Za-z0-9 &/,-]{2,}$", stripped):
            if stripped not in headings:
                headings.append(stripped)
    return headings[:20]


def _header_label(value: str) -> bool:
    return value.lower().split(":", maxsplit=1)[0] in {
        "subject",
        "from",
        "to",
        "date",
        "issue date",
        "published",
    }


def _local_summary(text: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    basis = paragraphs[0] if paragraphs else text
    return _short_snippet(basis, max_words=72, max_chars=480)


def _find_recommendation_label(text: str) -> str | None:
    match = re.search(
        r"\b(?:recommendation|rating)\s*:\s*([A-Za-z][A-Za-z ]{1,40})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return " ".join(match.group(1).split()).title()
    return None


def _extract_tickers(text: str) -> tuple[str, ...]:
    ignored = {"PDF", "HTML", "EMAIL", "THE", "AND", "FOR", "UNDER", "RADAR"}
    tickers = re.findall(r"\b[A-Z]{2,5}(?:\.[A-Z]{1,3})?\b", text)
    return tuple(dict.fromkeys(ticker for ticker in tickers if ticker not in ignored))


def _extract_prefixed_items(text: str, labels: tuple[str, ...]) -> tuple[str, ...]:
    items: list[str] = []
    label_pattern = "|".join(re.escape(label) for label in labels)
    for match in re.finditer(
        rf"^\s*(?:{label_pattern})\s*:\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        value = match.group(1).strip()
        if value and value not in items:
            items.append(value)
    return tuple(items[:10])


def _short_snippet(value: str, *, max_words: int, max_chars: int) -> str:
    words = " ".join(value.split()).split()
    snippet = " ".join(words[:max_words])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return snippet or "Private document imported."


def _date_to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or uuid.uuid4().hex[:12]
