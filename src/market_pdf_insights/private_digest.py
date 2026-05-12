"""Private single-user digest rendering and dry-run email helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from market_pdf_insights.daily_brief_rendering import DryRunEmailMode, EmailSendResult
from market_pdf_insights.private_research_storage import (
    PrivateRecommendationRecord,
    PrivateResearchStore,
    PrivateStructuredSummaryRecord,
)


PrivateDigestPeriod = Literal["daily", "weekly"]
PrivateDigestOutputFormat = Literal["json", "markdown", "html", "text"]
PRIVATE_DIGEST_DISCLAIMER = (
    "Private research summary for personal use only. It is not personal financial advice "
    "and must not be redistributed."
)


class PrivateDigestEmailSettings(BaseModel):
    """Configurable private digest email envelope without sender credentials."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sender: str = Field(min_length=1)
    recipients: list[str] = Field(min_length=1)
    subject_prefix: str = "Private Research Digest"
    reply_to: str | None = None

    @field_validator("recipients")
    @classmethod
    def _validate_recipients(cls, values: list[str]) -> list[str]:
        recipients = [value.strip() for value in values if value.strip()]
        if not recipients:
            raise ValueError("at least one recipient is required")
        return recipients

    def subject_for(self, digest: PrivateDigest) -> str:
        """Return the subject line for a private digest."""

        return (
            f"{self.subject_prefix}: {digest.date_from.isoformat()} to "
            f"{digest.date_to.isoformat()}"
        )


class PrivateDigestEmailSender(Protocol):
    """Protocol for future private digest email senders."""

    def send(
        self,
        digest: PrivateDigest,
        settings: PrivateDigestEmailSettings,
    ) -> EmailSendResult:
        """Send or write a rendered private digest."""


class PrivateDigestSourceReference(BaseModel):
    """Short source reference for a private digest without full source content."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str
    source_name: str
    document_title: str
    issue_date: date | None = None
    excerpt_id: str | None = None
    location: str | None = None
    excerpt: str | None = None


class PrivateDigestRecommendationSummary(BaseModel):
    """Digest row for one stock recommendation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str | None = None
    company_name: str
    exchange: str | None = None
    sector: str | None = None
    recommendation: str
    source_rating: str | None = None
    stated_target_price: float | None = None
    target_price_currency: str | None = None
    thesis: str | None = None
    risks: tuple[str, ...] = ()
    catalysts: tuple[str, ...] = ()
    numbers_to_verify: tuple[str, ...] = ()
    source_reference: PrivateDigestSourceReference | None = None


class PrivateDigestDocumentSummary(BaseModel):
    """Per-document summary included in a private digest."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str
    source_name: str
    document_title: str
    issue_date: date | None = None
    generated_at: datetime
    summary: str
    recommendations: tuple[PrivateDigestRecommendationSummary, ...] = ()
    source_references: tuple[PrivateDigestSourceReference, ...] = ()


class PrivateDigestTickerSummary(BaseModel):
    """Per-ticker digest summary across selected private recommendations."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str | None = None
    company_name: str
    exchange: str | None = None
    latest_document_id: str
    latest_issue_date: date | None = None
    latest_recommendation: str
    latest_target_price: float | None = None
    target_price_currency: str | None = None
    mentions: int = Field(ge=1)
    document_ids: tuple[str, ...] = ()
    thesis: str | None = None
    risks: tuple[str, ...] = ()
    catalysts: tuple[str, ...] = ()
    numbers_to_verify: tuple[str, ...] = ()
    source_references: tuple[PrivateDigestSourceReference, ...] = ()


class PrivateDigestRecommendationChange(BaseModel):
    """Recommendation or target-price change detected in local private history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str | None = None
    company_name: str
    from_document_id: str
    to_document_id: str
    from_issue_date: date | None = None
    to_issue_date: date | None = None
    from_recommendation: str
    to_recommendation: str
    from_target_price: float | None = None
    to_target_price: float | None = None
    target_price_currency: str | None = None
    summary: str
    source_reference: PrivateDigestSourceReference | None = None


class PrivateDigest(BaseModel):
    """Rendered private digest source model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str
    period: PrivateDigestPeriod
    date_from: date
    date_to: date
    generated_at: datetime
    document_summaries: tuple[PrivateDigestDocumentSummary, ...] = ()
    ticker_summaries: tuple[PrivateDigestTickerSummary, ...] = ()
    recommendation_change_log: tuple[PrivateDigestRecommendationChange, ...] = ()
    source_references: tuple[PrivateDigestSourceReference, ...] = ()
    disclaimer: str = PRIVATE_DIGEST_DISCLAIMER

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable digest dictionary."""

        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Render the digest as JSON."""

        return self.model_dump_json(indent=indent, exclude_none=True) + "\n"


class DryRunPrivateDigestEmailWriter:
    """Dry-run private digest writer that never sends email."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        mode: DryRunEmailMode = "eml",
        basename: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.basename = basename

    def send(
        self,
        digest: PrivateDigest,
        settings: PrivateDigestEmailSettings,
    ) -> EmailSendResult:
        """Write `.eml` or text/html parts locally and return their paths."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        basename = self.basename or _private_digest_basename(digest)
        output_paths: dict[str, Path] = {}

        if self.mode == "eml":
            message = build_private_digest_email_message(digest, settings)
            eml_path = self.output_dir / f"{basename}.eml"
            eml_path.write_bytes(message.as_bytes())
            output_paths["eml"] = eml_path
        else:
            text_path = self.output_dir / f"{basename}.txt"
            html_path = self.output_dir / f"{basename}.html"
            text_path.write_text(render_private_digest_plain_text(digest), encoding="utf-8")
            html_path.write_text(render_private_digest_html(digest), encoding="utf-8")
            output_paths["text"] = text_path
            output_paths["html"] = html_path

        return EmailSendResult(dry_run=True, output_paths=output_paths)


def build_private_digest(
    store: PrivateResearchStore,
    *,
    period: PrivateDigestPeriod = "daily",
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    tickers: Iterable[str] | None = None,
    generated_at: datetime | None = None,
) -> PrivateDigest:
    """Build a private digest from locally indexed structured summaries."""

    generated = generated_at or datetime.now(UTC)
    resolved_from, resolved_to = _resolve_digest_dates(
        period,
        as_of=as_of or generated.date(),
        date_from=date_from,
        date_to=date_to,
    )
    wanted_tickers = _normalize_tickers(tickers)
    structured_records = [
        record
        for record in store.list_structured_summaries()
        if _record_in_range(record, resolved_from, resolved_to)
        and _structured_record_matches_tickers(record, wanted_tickers)
    ]
    structured_records.sort(key=_structured_sort_key, reverse=True)
    document_summaries = tuple(
        _build_document_summary(record, wanted_tickers) for record in structured_records
    )
    selected_document_ids = {summary.document_id for summary in document_summaries}
    selected_recommendations = [
        record
        for record in store.list_recommendations()
        if record.document_id in selected_document_ids
        and _recommendation_matches_tickers(record, wanted_tickers)
    ]
    ticker_summaries = tuple(_build_ticker_summaries(selected_recommendations))
    recommendation_changes = tuple(
        _build_recommendation_change_log(
            store.list_recommendations(),
            selected_document_ids=selected_document_ids,
            wanted_tickers=wanted_tickers,
        )
    )
    source_references = _dedupe_source_references(
        reference
        for summary in document_summaries
        for reference in summary.source_references
    )
    title = f"Private {period.title()} Research Digest"
    return PrivateDigest(
        title=title,
        period=period,
        date_from=resolved_from,
        date_to=resolved_to,
        generated_at=generated,
        document_summaries=document_summaries,
        ticker_summaries=ticker_summaries,
        recommendation_change_log=recommendation_changes,
        source_references=source_references,
    )


def render_private_digest_json(digest: PrivateDigest, *, indent: int | None = 2) -> str:
    """Render a private digest as JSON."""

    return digest.to_json(indent=indent)


def render_private_digest_markdown(digest: PrivateDigest) -> str:
    """Render a private digest as Markdown."""

    lines = [
        f"# {digest.title}",
        "",
        f"**Period:** {digest.period}",
        f"**Date range:** {digest.date_from.isoformat()} to {digest.date_to.isoformat()}",
        f"**Generated:** {digest.generated_at.isoformat()}",
        "",
        "## Executive Summary",
        "",
        f"- Documents: {len(digest.document_summaries)}",
        f"- Tickers covered: {len(digest.ticker_summaries)}",
        f"- Recommendation changes: {len(digest.recommendation_change_log)}",
    ]
    _append_markdown_documents(lines, digest.document_summaries)
    _append_markdown_tickers(lines, digest.ticker_summaries)
    _append_markdown_changes(lines, digest.recommendation_change_log)
    _append_markdown_sources(lines, digest.source_references)
    lines.extend(["", "## Disclaimer", "", digest.disclaimer])
    return "\n".join(lines).strip() + "\n"


def render_private_digest_plain_text(digest: PrivateDigest) -> str:
    """Render a private digest as plain text for email bodies."""

    lines = [
        digest.title,
        "=" * len(digest.title),
        "",
        f"Period: {digest.period}",
        f"Date range: {digest.date_from.isoformat()} to {digest.date_to.isoformat()}",
        f"Generated: {digest.generated_at.isoformat()}",
        "",
        "EXECUTIVE SUMMARY",
        f"Documents: {len(digest.document_summaries)}",
        f"Tickers covered: {len(digest.ticker_summaries)}",
        f"Recommendation changes: {len(digest.recommendation_change_log)}",
    ]
    _append_text_documents(lines, digest.document_summaries)
    _append_text_tickers(lines, digest.ticker_summaries)
    _append_text_changes(lines, digest.recommendation_change_log)
    _append_text_sources(lines, digest.source_references)
    lines.extend(["", "DISCLAIMER", digest.disclaimer])
    return "\n".join(lines).strip() + "\n"


def render_private_digest_html(digest: PrivateDigest) -> str:
    """Render a private digest as standalone HTML suitable for email dry runs."""

    body = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(digest.title)}</title>",
        _PRIVATE_DIGEST_EMAIL_STYLE,
        "</head>",
        "<body>",
        '<main class="digest">',
        f"<h1>{escape(digest.title)}</h1>",
        '<p class="meta">'
        f"Period: {escape(digest.period)} | "
        f"Date range: {escape(digest.date_from.isoformat())} to "
        f"{escape(digest.date_to.isoformat())} | "
        f"Generated: {escape(digest.generated_at.isoformat())}"
        "</p>",
        "<h2>Executive Summary</h2>",
        "<ul>",
        f"<li>Documents: {len(digest.document_summaries)}</li>",
        f"<li>Tickers covered: {len(digest.ticker_summaries)}</li>",
        f"<li>Recommendation changes: {len(digest.recommendation_change_log)}</li>",
        "</ul>",
    ]
    _append_html_documents(body, digest.document_summaries)
    _append_html_tickers(body, digest.ticker_summaries)
    _append_html_changes(body, digest.recommendation_change_log)
    _append_html_sources(body, digest.source_references)
    body.extend(
        [
            "<h2>Disclaimer</h2>",
            f'<p class="disclaimer">{escape(digest.disclaimer)}</p>',
            "</main>",
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(body) + "\n"


def render_private_document_summary_markdown(
    summary: PrivateDigestDocumentSummary,
) -> str:
    """Render one per-document digest summary as Markdown."""

    lines: list[str] = []
    _append_one_markdown_document(lines, summary)
    return "\n".join(lines).strip() + "\n"


def render_private_ticker_summary_markdown(summary: PrivateDigestTickerSummary) -> str:
    """Render one per-ticker digest summary as Markdown."""

    lines: list[str] = []
    _append_one_markdown_ticker(lines, summary)
    return "\n".join(lines).strip() + "\n"


def save_private_digest_outputs(
    digest: PrivateDigest,
    output_dir: str | Path,
    *,
    basename: str | None = None,
    formats: Iterable[PrivateDigestOutputFormat] = ("json", "markdown", "html", "text"),
) -> dict[str, Path]:
    """Save selected private digest renderings to disk."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    resolved_basename = basename or _private_digest_basename(digest)
    renderers: Mapping[PrivateDigestOutputFormat, tuple[str, str]] = {
        "json": ("json", render_private_digest_json(digest)),
        "markdown": ("md", render_private_digest_markdown(digest)),
        "html": ("html", render_private_digest_html(digest)),
        "text": ("txt", render_private_digest_plain_text(digest)),
    }
    saved: dict[str, Path] = {}
    for output_format in formats:
        extension, content = renderers[output_format]
        path = output_path / f"{resolved_basename}.{extension}"
        path.write_text(content, encoding="utf-8")
        saved[output_format] = path
    return saved


def build_private_digest_email_message(
    digest: PrivateDigest,
    settings: PrivateDigestEmailSettings,
) -> EmailMessage:
    """Build a multipart private digest email message without sending it."""

    message = EmailMessage()
    message["Subject"] = settings.subject_for(digest)
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    if settings.reply_to:
        message["Reply-To"] = settings.reply_to
    message.set_content(render_private_digest_plain_text(digest))
    message.add_alternative(render_private_digest_html(digest), subtype="html")
    return message


def write_private_digest_dry_run_email(
    digest: PrivateDigest,
    settings: PrivateDigestEmailSettings,
    path: Path,
) -> EmailSendResult:
    """Write a private digest dry-run email file without sending."""

    suffix = path.suffix.lower()
    if suffix == ".eml":
        writer = DryRunPrivateDigestEmailWriter(path.parent, mode="eml", basename=path.stem)
    elif suffix in {".html", ".txt"}:
        writer = DryRunPrivateDigestEmailWriter(path.parent, mode="parts", basename=path.stem)
    else:
        raise ValueError("private digest email dry-run path must end in .eml, .html, or .txt")
    return writer.send(digest, settings)


def render_private_digest_terminal_summary(
    digest: PrivateDigest,
    *,
    saved_paths: Sequence[str] = (),
) -> str:
    """Render a concise terminal summary for a private digest."""

    lines = [
        f"Private digest: {digest.period}",
        f"Date range: {digest.date_from.isoformat()} to {digest.date_to.isoformat()}",
        f"Documents: {len(digest.document_summaries)}",
        f"Tickers: {len(digest.ticker_summaries)}",
        f"Recommendation changes: {len(digest.recommendation_change_log)}",
    ]
    if digest.ticker_summaries:
        lines.extend(["", "Tickers covered:"])
        lines.extend(
            f"- {summary.ticker or '-'} | {summary.company_name} | "
            f"{summary.latest_recommendation}"
            for summary in digest.ticker_summaries[:10]
        )
    if saved_paths:
        lines.extend(["", "Saved:"])
        lines.extend(f"- {path}" for path in saved_paths)
    return "\n".join(lines)


def _resolve_digest_dates(
    period: PrivateDigestPeriod,
    *,
    as_of: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    if date_from is not None or date_to is not None:
        resolved_to = date_to or as_of
        resolved_from = date_from or (resolved_to - timedelta(days=6))
    elif period == "weekly":
        resolved_to = as_of
        resolved_from = resolved_to - timedelta(days=6)
    else:
        resolved_from = as_of
        resolved_to = as_of
    if resolved_from > resolved_to:
        raise ValueError("date_from must be before or equal to date_to")
    return resolved_from, resolved_to


def _record_in_range(
    record: PrivateStructuredSummaryRecord,
    date_from: date,
    date_to: date,
) -> bool:
    record_date = record.summary.issue_date or record.generated_at.date()
    return date_from <= record_date <= date_to


def _structured_record_matches_tickers(
    record: PrivateStructuredSummaryRecord,
    wanted_tickers: set[str],
) -> bool:
    if not wanted_tickers:
        return True
    return any(
        recommendation.ticker in wanted_tickers
        for recommendation in record.summary.recommendations
        if recommendation.ticker
    )


def _build_document_summary(
    record: PrivateStructuredSummaryRecord,
    wanted_tickers: set[str],
) -> PrivateDigestDocumentSummary:
    summary = record.summary
    recommendations = tuple(
        PrivateDigestRecommendationSummary(
            ticker=recommendation.ticker,
            company_name=recommendation.company_name,
            exchange=recommendation.exchange,
            sector=recommendation.sector,
            recommendation=recommendation.recommendation,
            source_rating=recommendation.source_rating,
            stated_target_price=recommendation.stated_target_price,
            target_price_currency=recommendation.target_price_currency,
            thesis=recommendation.thesis,
            risks=tuple(risk.risk for risk in recommendation.risks),
            catalysts=tuple(catalyst.catalyst for catalyst in recommendation.catalysts),
            numbers_to_verify=tuple(
                f"{number.value}: {number.context}"
                for number in recommendation.numbers_to_verify
            ),
            source_reference=_source_reference_from_excerpt(recommendation.source_citation),
        )
        for recommendation in summary.recommendations
        if not wanted_tickers or recommendation.ticker in wanted_tickers
    )
    source_references = _dedupe_source_references(
        [
            *(_source_reference_from_excerpt(excerpt) for excerpt in summary.source_excerpts),
            *(
                recommendation.source_reference
                for recommendation in recommendations
                if recommendation.source_reference is not None
            ),
        ]
    )
    return PrivateDigestDocumentSummary(
        document_id=summary.document_id,
        source_name=summary.source_name,
        document_title=summary.document_title,
        issue_date=summary.issue_date,
        generated_at=record.generated_at,
        summary=summary.document_summary,
        recommendations=recommendations,
        source_references=source_references,
    )


def _build_ticker_summaries(
    records: Sequence[PrivateRecommendationRecord],
) -> list[PrivateDigestTickerSummary]:
    grouped: dict[str, list[PrivateRecommendationRecord]] = defaultdict(list)
    for record in records:
        grouped[_recommendation_key(record)].append(record)

    summaries: list[PrivateDigestTickerSummary] = []
    for group_records in grouped.values():
        ordered = sorted(group_records, key=_recommendation_sort_key)
        latest = ordered[-1]
        summaries.append(
            PrivateDigestTickerSummary(
                ticker=latest.ticker,
                company_name=latest.company_name,
                exchange=latest.exchange,
                latest_document_id=latest.document_id,
                latest_issue_date=latest.issue_date,
                latest_recommendation=latest.recommendation,
                latest_target_price=latest.stated_target_price,
                target_price_currency=latest.target_price_currency,
                mentions=len(ordered),
                document_ids=tuple(_dedupe(record.document_id for record in ordered)),
                thesis=latest.thesis,
                risks=tuple(_dedupe(risk for record in ordered for risk in record.risks)),
                catalysts=tuple(
                    _dedupe(catalyst for record in ordered for catalyst in record.catalysts)
                ),
                numbers_to_verify=tuple(
                    _dedupe(
                        question
                        for record in ordered
                        for question in record.verification_questions
                    )
                ),
                source_references=_dedupe_source_references(
                    _source_reference_from_excerpt(record.source_excerpt)
                    for record in ordered
                    if record.source_excerpt is not None
                ),
            )
        )
    return sorted(summaries, key=lambda item: (item.ticker or item.company_name))


def _build_recommendation_change_log(
    records: Sequence[PrivateRecommendationRecord],
    *,
    selected_document_ids: set[str],
    wanted_tickers: set[str],
) -> list[PrivateDigestRecommendationChange]:
    grouped: dict[str, list[PrivateRecommendationRecord]] = defaultdict(list)
    for record in records:
        if _recommendation_matches_tickers(record, wanted_tickers):
            grouped[_recommendation_key(record)].append(record)

    changes: list[PrivateDigestRecommendationChange] = []
    for group_records in grouped.values():
        ordered = sorted(group_records, key=_recommendation_sort_key)
        for index, current in enumerate(ordered):
            if current.document_id not in selected_document_ids or index == 0:
                continue
            previous = ordered[index - 1]
            if not _recommendation_changed(previous, current):
                continue
            changes.append(
                PrivateDigestRecommendationChange(
                    ticker=current.ticker,
                    company_name=current.company_name,
                    from_document_id=previous.document_id,
                    to_document_id=current.document_id,
                    from_issue_date=previous.issue_date,
                    to_issue_date=current.issue_date,
                    from_recommendation=previous.recommendation,
                    to_recommendation=current.recommendation,
                    from_target_price=previous.stated_target_price,
                    to_target_price=current.stated_target_price,
                    target_price_currency=(
                        current.target_price_currency or previous.target_price_currency
                    ),
                    summary=_change_summary(previous, current),
                    source_reference=_source_reference_from_excerpt(current.source_excerpt)
                    if current.source_excerpt
                    else None,
                )
            )
    return sorted(changes, key=lambda item: (item.to_issue_date or date.min, item.ticker or ""))


def _recommendation_changed(
    previous: PrivateRecommendationRecord,
    current: PrivateRecommendationRecord,
) -> bool:
    return (
        previous.recommendation != current.recommendation
        or previous.stated_target_price != current.stated_target_price
    )


def _change_summary(
    previous: PrivateRecommendationRecord,
    current: PrivateRecommendationRecord,
) -> str:
    parts = [
        f"{previous.recommendation} -> {current.recommendation}",
    ]
    if previous.stated_target_price != current.stated_target_price:
        parts.append(
            "target "
            f"{_format_target(previous.stated_target_price, previous.target_price_currency)} -> "
            f"{_format_target(current.stated_target_price, current.target_price_currency)}"
        )
    return "; ".join(parts)


def _source_reference_from_excerpt(excerpt) -> PrivateDigestSourceReference:
    location_parts = []
    if excerpt.page_number is not None:
        location_parts.append(f"page {excerpt.page_number}")
    if excerpt.section:
        location_parts.append(excerpt.section)
    if excerpt.location_label:
        location_parts.append(excerpt.location_label)
    return PrivateDigestSourceReference(
        document_id=excerpt.document_id,
        source_name=excerpt.source_name,
        document_title=excerpt.document_title,
        excerpt_id=excerpt.excerpt_id,
        location=", ".join(location_parts) or None,
        excerpt=excerpt.excerpt,
    )


def _dedupe_source_references(
    references: Iterable[PrivateDigestSourceReference | None],
) -> tuple[PrivateDigestSourceReference, ...]:
    deduped: dict[str, PrivateDigestSourceReference] = {}
    for reference in references:
        if reference is None:
            continue
        key = "|".join(
            [
                reference.excerpt_id or "",
                reference.document_id,
                reference.location or "",
                reference.excerpt or "",
            ]
        )
        deduped[key] = reference
    return tuple(deduped.values())


def _normalize_tickers(tickers: Iterable[str] | None) -> set[str]:
    if tickers is None:
        return set()
    return {ticker.strip().upper() for ticker in tickers if ticker.strip()}


def _recommendation_matches_tickers(
    record: PrivateRecommendationRecord,
    wanted_tickers: set[str],
) -> bool:
    if not wanted_tickers:
        return True
    return record.ticker in wanted_tickers


def _structured_sort_key(record: PrivateStructuredSummaryRecord) -> tuple[date, datetime, str]:
    return (record.summary.issue_date or record.generated_at.date(), record.generated_at, record.document_id)


def _recommendation_sort_key(record: PrivateRecommendationRecord) -> tuple[date, datetime, str]:
    return (record.issue_date or record.generated_at.date(), record.generated_at, record.document_id)


def _recommendation_key(record: PrivateRecommendationRecord) -> str:
    return (record.ticker or record.company_name).casefold()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _append_markdown_documents(
    lines: list[str],
    summaries: Sequence[PrivateDigestDocumentSummary],
) -> None:
    lines.extend(["", "## Per-Document Summaries"])
    if not summaries:
        lines.extend(["", "No private documents matched this digest range."])
        return
    for summary in summaries:
        _append_one_markdown_document(lines, summary)


def _append_one_markdown_document(
    lines: list[str],
    summary: PrivateDigestDocumentSummary,
) -> None:
    lines.extend(["", f"### {summary.document_title}", ""])
    lines.append(f"- Source: {summary.source_name}")
    lines.append(f"- Document ID: `{summary.document_id}`")
    if summary.issue_date:
        lines.append(f"- Issue date: {summary.issue_date.isoformat()}")
    lines.extend(["", summary.summary])
    if summary.recommendations:
        lines.extend(["", "Recommendations:"])
        for recommendation in summary.recommendations:
            target = _format_target(
                recommendation.stated_target_price,
                recommendation.target_price_currency,
            )
            target_text = f", target {target}" if target else ""
            lines.append(
                f"- **{recommendation.ticker or '-'} {recommendation.company_name}:** "
                f"{recommendation.recommendation}{target_text}"
            )
            if recommendation.thesis:
                lines.append(f"  Thesis: {recommendation.thesis}")
            _append_inline_list(lines, "Risks", recommendation.risks)
            _append_inline_list(lines, "Catalysts", recommendation.catalysts)
            _append_inline_list(lines, "Numbers to verify", recommendation.numbers_to_verify)


def _append_markdown_tickers(
    lines: list[str],
    summaries: Sequence[PrivateDigestTickerSummary],
) -> None:
    lines.extend(["", "## Per-Ticker Summaries"])
    if not summaries:
        lines.extend(["", "No tickers were indexed for this digest range."])
        return
    for summary in summaries:
        _append_one_markdown_ticker(lines, summary)


def _append_one_markdown_ticker(lines: list[str], summary: PrivateDigestTickerSummary) -> None:
    target = _format_target(summary.latest_target_price, summary.target_price_currency)
    target_text = f", target {target}" if target else ""
    lines.extend(["", f"### {summary.ticker or '-'} {summary.company_name}", ""])
    lines.append(f"- Latest rating: {summary.latest_recommendation}{target_text}")
    if summary.latest_issue_date:
        lines.append(f"- Latest issue date: {summary.latest_issue_date.isoformat()}")
    lines.append(f"- Documents: {', '.join(summary.document_ids)}")
    if summary.thesis:
        lines.append(f"- Thesis: {summary.thesis}")
    _append_inline_list(lines, "Risks", summary.risks)
    _append_inline_list(lines, "Catalysts", summary.catalysts)
    _append_inline_list(lines, "Numbers to verify", summary.numbers_to_verify)


def _append_markdown_changes(
    lines: list[str],
    changes: Sequence[PrivateDigestRecommendationChange],
) -> None:
    lines.extend(["", "## Recommendation Change Log"])
    if not changes:
        lines.extend(["", "No recommendation or target-price changes detected."])
        return
    for change in changes:
        lines.append(
            f"- **{change.ticker or '-'} {change.company_name}:** {change.summary} "
            f"(`{change.from_document_id}` -> `{change.to_document_id}`)"
        )


def _append_markdown_sources(
    lines: list[str],
    references: Sequence[PrivateDigestSourceReference],
) -> None:
    lines.extend(["", "## Source References"])
    if not references:
        lines.extend(["", "No source references captured."])
        return
    for reference in references:
        location = f", {reference.location}" if reference.location else ""
        excerpt = f" - {reference.excerpt}" if reference.excerpt else ""
        lines.append(
            f"- `{reference.excerpt_id or reference.document_id}`: "
            f"{reference.source_name}, {reference.document_title}{location}{excerpt}"
        )


def _append_text_documents(
    lines: list[str],
    summaries: Sequence[PrivateDigestDocumentSummary],
) -> None:
    lines.extend(["", "PER-DOCUMENT SUMMARIES"])
    if not summaries:
        lines.append("No private documents matched this digest range.")
        return
    for summary in summaries:
        lines.extend(["", summary.document_title])
        lines.append(f"Source: {summary.source_name}")
        lines.append(f"Document ID: {summary.document_id}")
        if summary.issue_date:
            lines.append(f"Issue date: {summary.issue_date.isoformat()}")
        lines.append(summary.summary)
        for recommendation in summary.recommendations:
            lines.append(
                f"- {recommendation.ticker or '-'} {recommendation.company_name}: "
                f"{recommendation.recommendation}"
            )


def _append_text_tickers(
    lines: list[str],
    summaries: Sequence[PrivateDigestTickerSummary],
) -> None:
    lines.extend(["", "PER-TICKER SUMMARIES"])
    if not summaries:
        lines.append("No tickers were indexed for this digest range.")
        return
    for summary in summaries:
        target = _format_target(summary.latest_target_price, summary.target_price_currency)
        target_text = f", target {target}" if target else ""
        lines.append(
            f"- {summary.ticker or '-'} {summary.company_name}: "
            f"{summary.latest_recommendation}{target_text}"
        )


def _append_text_changes(
    lines: list[str],
    changes: Sequence[PrivateDigestRecommendationChange],
) -> None:
    lines.extend(["", "RECOMMENDATION CHANGE LOG"])
    if not changes:
        lines.append("No recommendation or target-price changes detected.")
        return
    for change in changes:
        lines.append(
            f"- {change.ticker or '-'} {change.company_name}: {change.summary} "
            f"({change.from_document_id} -> {change.to_document_id})"
        )


def _append_text_sources(
    lines: list[str],
    references: Sequence[PrivateDigestSourceReference],
) -> None:
    lines.extend(["", "SOURCE REFERENCES"])
    if not references:
        lines.append("No source references captured.")
        return
    for reference in references:
        location = f", {reference.location}" if reference.location else ""
        excerpt = f" - {reference.excerpt}" if reference.excerpt else ""
        lines.append(
            f"- {reference.excerpt_id or reference.document_id}: "
            f"{reference.source_name}, {reference.document_title}{location}{excerpt}"
        )


def _append_html_documents(
    body: list[str],
    summaries: Sequence[PrivateDigestDocumentSummary],
) -> None:
    body.append("<h2>Per-Document Summaries</h2>")
    if not summaries:
        body.append("<p>No private documents matched this digest range.</p>")
        return
    for summary in summaries:
        body.append(f"<h3>{escape(summary.document_title)}</h3>")
        body.append(
            '<p class="meta">'
            f"Source: {escape(summary.source_name)} | "
            f"Document ID: {escape(summary.document_id)}"
            "</p>"
        )
        body.append(f"<p>{escape(summary.summary)}</p>")
        if summary.recommendations:
            body.append("<ul>")
            for recommendation in summary.recommendations:
                target = _format_target(
                    recommendation.stated_target_price,
                    recommendation.target_price_currency,
                )
                target_text = f", target {target}" if target else ""
                body.append(
                    "<li>"
                    f"<strong>{escape(recommendation.ticker or '-')} "
                    f"{escape(recommendation.company_name)}:</strong> "
                    f"{escape(recommendation.recommendation + target_text)}"
                    "</li>"
                )
            body.append("</ul>")


def _append_html_tickers(
    body: list[str],
    summaries: Sequence[PrivateDigestTickerSummary],
) -> None:
    body.append("<h2>Per-Ticker Summaries</h2>")
    if not summaries:
        body.append("<p>No tickers were indexed for this digest range.</p>")
        return
    body.append("<ul>")
    for summary in summaries:
        target = _format_target(summary.latest_target_price, summary.target_price_currency)
        target_text = f", target {target}" if target else ""
        body.append(
            "<li>"
            f"<strong>{escape(summary.ticker or '-')} {escape(summary.company_name)}:</strong> "
            f"{escape(summary.latest_recommendation + target_text)}"
            "</li>"
        )
    body.append("</ul>")


def _append_html_changes(
    body: list[str],
    changes: Sequence[PrivateDigestRecommendationChange],
) -> None:
    body.append("<h2>Recommendation Change Log</h2>")
    if not changes:
        body.append("<p>No recommendation or target-price changes detected.</p>")
        return
    body.append("<ul>")
    for change in changes:
        body.append(
            "<li>"
            f"<strong>{escape(change.ticker or '-')} {escape(change.company_name)}:</strong> "
            f"{escape(change.summary)}"
            "</li>"
        )
    body.append("</ul>")


def _append_html_sources(
    body: list[str],
    references: Sequence[PrivateDigestSourceReference],
) -> None:
    body.append("<h2>Source References</h2>")
    if not references:
        body.append("<p>No source references captured.</p>")
        return
    body.append("<ul>")
    for reference in references:
        location = f", {reference.location}" if reference.location else ""
        excerpt = f" - {reference.excerpt}" if reference.excerpt else ""
        body.append(
            "<li>"
            f"<code>{escape(reference.excerpt_id or reference.document_id)}</code>: "
            f"{escape(reference.source_name)}, {escape(reference.document_title)}"
            f"{escape(location + excerpt)}"
            "</li>"
        )
    body.append("</ul>")


def _append_inline_list(lines: list[str], label: str, values: Sequence[str]) -> None:
    if values:
        lines.append(f"  {label}: {', '.join(values)}")


def _format_target(value: float | None, currency: str | None) -> str:
    if value is None:
        return ""
    return f"{currency or ''} {value:g}".strip()


def _private_digest_basename(digest: PrivateDigest) -> str:
    raw = (
        f"private-{digest.period}-digest-"
        f"{digest.date_from.isoformat()}-to-{digest.date_to.isoformat()}"
    )
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-").lower()


_PRIVATE_DIGEST_EMAIL_STYLE = """
<style>
body {
  margin: 0;
  padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #1f2933;
  background: #f7f8fa;
}
.digest {
  max-width: 880px;
  margin: 0 auto;
  padding: 28px;
  background: #fff;
  border: 1px solid #d9dee7;
  border-radius: 8px;
}
h1, h2, h3 { color: #102033; }
.meta { color: #536170; font-size: 0.92rem; }
.disclaimer {
  color: #5b2b1f;
  background: #fff4ec;
  border-left: 4px solid #d97706;
  padding: 12px;
}
code { background: #eef2f6; padding: 1px 4px; border-radius: 4px; }
</style>
"""
