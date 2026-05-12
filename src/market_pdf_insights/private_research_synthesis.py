"""Summarization clients for private subscribed research documents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from market_pdf_insights.chunker import chunk_text
from market_pdf_insights.llm_client import (
    DEFAULT_OPENAI_MODEL,
    LLMConfigurationError,
    LLMResponseValidationError,
    MARKET_MODEL_ENV,
    OPENAI_API_KEY_ENV,
    _load_json_object,
    _response_output_text,
    _truncate,
)
from market_pdf_insights.private_research_schema import (
    Catalyst,
    NumberToVerify,
    PersonalActionQuestion,
    PortfolioWatchItem,
    PrivateResearchDocument,
    RecommendationChange,
    RiskPoint,
    SourceExcerpt,
    StockRecommendation,
    ThesisPoint,
    ValuationNote,
    normalize_recommendation_rating,
)
from market_pdf_insights.private_research_storage import PrivateDocumentRecord, PrivateResearchStore


TModel = TypeVar("TModel", bound=BaseModel)


class PrivateResearchSynthesisError(RuntimeError):
    """Raised when private research synthesis cannot be completed."""


class PrivateResearchDocumentContext(BaseModel):
    """Safe source metadata passed to private research summarizers."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    issue_date: date | None = None
    imported_at: datetime | None = None
    source_type: str | None = None
    original_filename: str | None = None
    section_headings: tuple[str, ...] = ()

    @classmethod
    def from_document_record(
        cls,
        document: PrivateDocumentRecord,
    ) -> PrivateResearchDocumentContext:
        """Build private summarizer context from a stored document record."""

        issue_date_value = document.metadata.get("issue_date")
        section_headings = document.metadata.get("section_headings") or ()
        return cls(
            document_id=document.document_id,
            source_name=document.source_name,
            document_title=document.title,
            issue_date=date.fromisoformat(issue_date_value) if issue_date_value else None,
            imported_at=document.imported_at,
            source_type=document.metadata.get("source_type"),
            original_filename=document.metadata.get("original_filename"),
            section_headings=tuple(str(heading) for heading in section_headings),
        )

    def prompt_payload(self) -> dict[str, Any]:
        """Return a JSON-safe context payload for model prompts."""

        return self.model_dump(mode="json", exclude_none=True)


class PrivateResearchChunkNotes(BaseModel):
    """Source-grounded notes extracted from one private document chunk."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_index: int = Field(ge=0)
    summary: str = Field(min_length=1)
    recommendation_mentions: list[str] = Field(default_factory=list)
    company_mentions: list[str] = Field(default_factory=list)
    rating_mentions: list[str] = Field(default_factory=list)
    recommendation_changes: list[str] = Field(default_factory=list)
    thesis_points: list[str] = Field(default_factory=list)
    bullish_arguments: list[str] = Field(default_factory=list)
    bearish_arguments: list[str] = Field(default_factory=list)
    valuation_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    catalyst_notes: list[str] = Field(default_factory=list)
    numbers_to_verify: list[str] = Field(default_factory=list)
    questions_to_verify: list[str] = Field(default_factory=list)
    source_excerpts: list[SourceExcerpt] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class PrivateResearchSynthesisClient(Protocol):
    """Protocol implemented by private subscribed-research summarizers."""

    model_name: str

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchDocument:
        """Summarize private source text chunks into a validated research document."""


@dataclass(frozen=True)
class PrivateResearchSummarizerConfig:
    """Chunking configuration for private research synthesis."""

    max_chunk_chars: int = 6_000
    chunk_overlap: int = 500


class PrivateResearchSummarizer:
    """Read imported private text, chunk it, and synthesize structured research."""

    def __init__(
        self,
        *,
        client: PrivateResearchSynthesisClient | None = None,
        config: PrivateResearchSummarizerConfig | None = None,
    ) -> None:
        self.client = client or PlaceholderPrivateResearchClient()
        self.config = config or PrivateResearchSummarizerConfig()

    def summarize_record(self, document: PrivateDocumentRecord) -> PrivateResearchDocument:
        """Summarize a stored private document record."""

        if document.extracted_text_path is None or not document.extracted_text_path.exists():
            raise PrivateResearchSynthesisError(
                f"Extracted text is missing for private document: {document.document_id}"
            )
        text = document.extracted_text_path.read_text(encoding="utf-8")
        chunks = chunk_text(
            text,
            max_chars=self.config.max_chunk_chars,
            overlap=self.config.chunk_overlap,
        )
        if not chunks:
            raise PrivateResearchSynthesisError(
                f"No text chunks could be produced for private document: {document.document_id}"
            )
        context = PrivateResearchDocumentContext.from_document_record(document)
        summary = self.client.summarize_chunks(chunks, context=context)
        metadata = {
            **summary.metadata,
            "chunk_count": len(chunks),
            "source_char_count": len(text),
            "model": self.client.model_name,
        }
        return summary.model_copy(update={"metadata": metadata})


class OpenAIPrivateResearchClient:
    """Synthesize private subscribed research with the OpenAI Responses API."""

    model_name: str

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        openai_client: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to zero.")

        self.model_name = model or os.environ.get(MARKET_MODEL_ENV) or DEFAULT_OPENAI_MODEL
        self.max_retries = max_retries
        self._client = openai_client or self._build_client(api_key)

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchDocument:
        """Summarize chunks into notes, then synthesize one private research document."""

        if not chunks:
            raise ValueError("At least one text chunk is required for private summarization.")
        notes = [
            self._summarize_chunk(chunk, chunk_index=index, context=context)
            for index, chunk in enumerate(chunks)
        ]
        document = self._synthesize_document(notes, context=context)
        metadata = {
            **document.metadata,
            "chunk_count": len(chunks),
            "note_count": len(notes),
            "model": self.model_name,
            "llm_provider": "openai",
        }
        return document.model_copy(update={"metadata": metadata})

    def _build_client(self, api_key: str | None) -> Any:
        resolved_api_key = api_key or os.environ.get(OPENAI_API_KEY_ENV)
        if not resolved_api_key:
            raise LLMConfigurationError(
                f"{OPENAI_API_KEY_ENV} is required when using OpenAIPrivateResearchClient."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The openai package is required for OpenAIPrivateResearchClient."
            ) from exc

        return OpenAI(api_key=resolved_api_key)

    def _summarize_chunk(
        self,
        chunk: str,
        *,
        chunk_index: int,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchChunkNotes:
        prompt = (
            "Summarize this private subscribed-research chunk into source-grounded notes.\n\n"
            f"Document context JSON:\n{json.dumps(context.prompt_payload(), indent=2)}\n\n"
            f"Chunk index: {chunk_index}\n\n"
            f"Chunk text:\n{chunk}"
        )
        return self._request_json_model(
            PrivateResearchChunkNotes,
            [
                {"role": "system", "content": PRIVATE_RESEARCH_CHUNK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    def _synthesize_document(
        self,
        notes: Sequence[PrivateResearchChunkNotes],
        *,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchDocument:
        payload = {
            "document_context": context.prompt_payload(),
            "chunk_notes": [note.model_dump(mode="json", exclude_none=True) for note in notes],
            "required_disclaimer": PrivateResearchDocument.model_fields[
                "disclaimer"
            ].default,
        }
        prompt = (
            "Synthesize one private structured research summary from these chunk notes.\n\n"
            f"Synthesis input JSON:\n{json.dumps(payload, indent=2)}"
        )
        return self._request_json_model(
            PrivateResearchDocument,
            [
                {"role": "system", "content": PRIVATE_RESEARCH_SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    def _request_json_model(
        self,
        response_model: type[TModel],
        input_messages: list[dict[str, str]],
    ) -> TModel:
        messages = list(input_messages)
        last_error: Exception | None = None
        last_text = ""

        for attempt in range(self.max_retries + 1):
            response = self._client.responses.create(
                model=self.model_name,
                input=messages,
                text={"format": {"type": "json_object"}},
            )
            last_text = _response_output_text(response)
            try:
                payload = _load_json_object(last_text)
                return response_model.model_validate(payload)
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = [
                    *input_messages,
                    {
                        "role": "user",
                        "content": (
                            "The previous response was invalid JSON or failed schema "
                            f"validation: {_truncate(str(exc), 900)}\n\n"
                            "Return only one corrected JSON object for the requested schema. "
                            "Do not include markdown fences or commentary."
                        ),
                    },
                ]

        raise LLMResponseValidationError(
            "OpenAI response could not be parsed into "
            f"{response_model.__name__} after {self.max_retries + 1} attempt(s). "
            f"Last error: {last_error}. Last response: {_truncate(last_text, 900)}"
        )


class MockPrivateResearchLLMClient:
    """Mock private research client for tests and local wiring."""

    model_name = "mock-private-research"

    def __init__(self, document: PrivateResearchDocument | None = None) -> None:
        self.document = document or PrivateResearchDocument.example()
        self.calls: list[dict[str, object]] = []

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchDocument:
        """Return a predefined private research document and record the call."""

        self.calls.append(
            {
                "chunks": list(chunks),
                "context": context.model_dump(mode="json", exclude_none=True),
            }
        )
        metadata = {
            **self.document.metadata,
            "chunk_count": len(chunks),
            "model": self.model_name,
        }
        return self.document.model_copy(update={"metadata": metadata})


class PlaceholderPrivateResearchClient:
    """Deterministic source-summary client for private research fixtures."""

    model_name = "private-placeholder"

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        context: PrivateResearchDocumentContext,
    ) -> PrivateResearchDocument:
        """Build a validated private research summary using simple source-text heuristics."""

        if not chunks:
            raise ValueError("At least one text chunk is required for private summarization.")
        text = _strip_page_markers("\n\n".join(chunks))
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = _source_summary(lines, context)
        company_name, ticker, exchange = _infer_company_identity(text, context)
        rating_label = _extract_prefixed_value(text, ("recommendation", "rating"))
        recommendation_value = _safe_rating(rating_label)
        target_price, currency = _extract_target_price(text)
        citation = _source_excerpt(context, text, label="Recommendation", excerpt_id="excerpt-1")
        thesis = _extract_prefixed_value(text, ("thesis", "investment thesis"))
        risks = [
            RiskPoint(
                risk=value,
                severity=_risk_severity(value),
                source_excerpt=_source_excerpt(
                    context,
                    value,
                    label="Risks",
                    excerpt_id=f"risk-{index + 1}",
                ),
                confidence_score=0.55,
            )
            for index, value in enumerate(_extract_prefixed_items(text, ("risk", "risks")))
        ]
        catalysts = [
            Catalyst(
                catalyst=value,
                expected_timing=_extract_time_horizon(value) or None,
                direction="positive",
                source_excerpt=_source_excerpt(
                    context,
                    value,
                    label="Catalysts",
                    excerpt_id=f"catalyst-{index + 1}",
                ),
                confidence_score=0.55,
            )
            for index, value in enumerate(_extract_prefixed_items(text, ("catalyst", "catalysts")))
        ]
        numbers_to_verify = _numbers_to_verify(text, context)
        valuation_note = None
        if target_price is not None or _extract_prefixed_value(text, ("valuation",)):
            valuation_note = ValuationNote(
                valuation_summary=_extract_prefixed_value(text, ("valuation",))
                or f"The source states a target price of {currency or ''} {target_price}.",
                stated_target_price=target_price,
                currency=currency,
                assumptions=_extract_prefixed_items(text, ("assumption", "assumptions")),
                numbers_to_verify=numbers_to_verify,
                source_excerpt=_source_excerpt(
                    context,
                    text,
                    label="Valuation",
                    excerpt_id="valuation-1",
                ),
                confidence_score=0.55,
            )
        recommendation_change = _recommendation_change(text, recommendation_value, target_price, currency)
        source_rating = rating_label or recommendation_value.replace("_", " ").title()
        recommendation = StockRecommendation(
            recommendation_id=f"rec-{(ticker or company_name).lower().replace('.', '-')}",
            company_name=company_name,
            ticker=ticker,
            exchange=exchange,
            recommendation=recommendation_value,
            source_rating=source_rating,
            stated_target_price=target_price,
            target_price_currency=currency,
            stated_valuation=_extract_prefixed_value(text, ("valuation",)),
            recommendation_date=context.issue_date,
            time_horizon=_extract_prefixed_value(text, ("time horizon", "horizon"))
            or _extract_time_horizon(text),
            thesis=thesis,
            thesis_points=[
                ThesisPoint(
                    point=thesis,
                    stance="bullish" if recommendation_value in _POSITIVE_RATINGS else "unclear",
                    source_excerpt=citation,
                    confidence_score=0.55,
                )
            ]
            if thesis
            else [],
            bullish_arguments=[
                ThesisPoint(point=value, stance="bullish", confidence_score=0.5)
                for value in _extract_prefixed_items(text, ("bullish", "bullish argument"))
            ],
            bearish_arguments=[
                ThesisPoint(point=value, stance="bearish", confidence_score=0.5)
                for value in _extract_prefixed_items(text, ("bearish", "bearish argument"))
            ],
            risks=risks,
            catalysts=catalysts,
            valuation_notes=[valuation_note] if valuation_note else [],
            valuation_assumptions=_extract_prefixed_items(text, ("assumption", "assumptions")),
            recommendation_changes=[recommendation_change] if recommendation_change else [],
            portfolio_watch_items=[
                PortfolioWatchItem(
                    item_id=f"watch-{(ticker or company_name).lower().replace('.', '-')}",
                    company_name=company_name,
                    ticker=ticker,
                    exchange=exchange,
                    watch_reason="Monitor source-stated risks, catalysts, and verification items.",
                    trigger_to_watch=catalysts[0].catalyst if catalysts else None,
                    status="watch",
                    source_excerpt=citation,
                    confidence_score=0.5,
                )
            ],
            numbers_to_verify=numbers_to_verify,
            source_citation=citation,
            confidence_score=0.55,
        )
        return PrivateResearchDocument(
            document_id=context.document_id,
            source_name=context.source_name,
            document_title=context.document_title,
            issue_date=context.issue_date,
            imported_at=context.imported_at,
            source_type=context.source_type,
            original_filename=context.original_filename,
            document_summary=summary,
            recommendations=[recommendation],
            portfolio_watch_items=recommendation.portfolio_watch_items,
            source_excerpts=[citation],
            numbers_to_verify=numbers_to_verify,
            personal_action_questions=[
                PersonalActionQuestion(
                    question_id=f"q-{(ticker or company_name).lower().replace('.', '-')}-verify",
                    question="What source-stated assumptions need checking before relying on this note?",
                    why_it_matters="The source summary may include forecasts, valuation claims, or risks.",
                    related_ticker=ticker,
                    related_recommendation_id=recommendation.recommendation_id,
                    confidence_score=0.5,
                )
            ],
            confidence_score=0.55,
            metadata={"placeholder_warning": "Review against the original private source."},
        )


def summarize_imported_private_research(
    document_id: str,
    *,
    store: PrivateResearchStore,
    client: PrivateResearchSynthesisClient | None = None,
    config: PrivateResearchSummarizerConfig | None = None,
) -> PrivateResearchDocument:
    """Summarize an imported private document from the local store."""

    document = store.get_document(document_id)
    if document is None:
        raise PrivateResearchSynthesisError(f"Unknown private document: {document_id}")
    return PrivateResearchSummarizer(client=client, config=config).summarize_record(document)


def _source_summary(lines: Sequence[str], context: PrivateResearchDocumentContext) -> str:
    if not lines:
        return f"The source document {context.document_title} contains no extracted text."
    first_points = " ".join(lines[:3])
    return _short_snippet(
        f"The source document {context.document_title} says: {first_points}",
        max_words=72,
        max_chars=520,
    )


def _infer_company_identity(
    text: str,
    context: PrivateResearchDocumentContext,
) -> tuple[str, str | None, str | None]:
    import re

    match = re.search(
        r"\b([A-Z][A-Za-z0-9 &.'-]{2,80})\s+\(([A-Z0-9]{2,6})(?:\.([A-Z]{2,4}))?\)",
        text,
    )
    if match:
        return match.group(1).strip(), match.group(2).upper(), (match.group(3) or "ASX").upper()
    ticker_match = re.search(r"\b([A-Z]{2,5})(?:\.([A-Z]{2,4}))?\b", text)
    if ticker_match:
        ticker = ticker_match.group(1).upper()
        exchange = (ticker_match.group(2) or "ASX").upper()
        return f"{ticker} company", ticker, exchange
    return context.document_title, None, None


def _extract_prefixed_value(text: str, labels: tuple[str, ...]) -> str | None:
    values = _extract_prefixed_items(text, labels)
    return values[0] if values else None


def _extract_prefixed_items(text: str, labels: tuple[str, ...]) -> list[str]:
    import re

    items: list[str] = []
    label_pattern = "|".join(re.escape(label) for label in labels)
    for match in re.finditer(
        rf"^\s*(?:{label_pattern})\s*:\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        value = match.group(1).strip()
        if value and value not in items:
            items.append(_short_snippet(value, max_words=32, max_chars=220))
    return items[:8]


def _safe_rating(value: str | None) -> str:
    try:
        return normalize_recommendation_rating(value or "not_rated")
    except ValueError:
        return "not_rated"


def _extract_target_price(text: str) -> tuple[float | None, str | None]:
    import re

    match = re.search(
        r"\b(?:target price|price target|valuation)\s*:\s*(?:(A\$|AUD|USD|NZD)\s*)?\$?(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    currency_token = (match.group(1) or "").upper()
    currency = "AUD" if currency_token in {"A$", "AUD", ""} else currency_token
    return float(match.group(2)), currency


def _numbers_to_verify(
    text: str,
    context: PrivateResearchDocumentContext,
) -> list[NumberToVerify]:
    import re

    numbers: list[NumberToVerify] = []
    patterns = [
        r"\b(?:AUD|USD|NZD|A\$|\$)\s*\d+(?:\.\d+)?\b",
        r"\b\d+(?:\.\d+)?%\b",
        r"\b\d+(?:\.\d+)?x\b",
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = " ".join(match.group(0).split())
            if value in seen:
                continue
            seen.add(value)
            numbers.append(
                NumberToVerify(
                    value=value,
                    context="Numeric claim found in the private source document.",
                    suggested_check="Verify against the original report and current market data.",
                    source_excerpt=_source_excerpt(
                        context,
                        _sentence_around(text, match.start()),
                        label="Number to verify",
                        excerpt_id=f"number-{len(numbers) + 1}",
                    ),
                    confidence_score=0.55,
                )
            )
            if len(numbers) >= 8:
                return numbers
    return numbers


def _recommendation_change(
    text: str,
    new_rating: str,
    target_price: float | None,
    currency: str | None,
) -> RecommendationChange | None:
    previous = _extract_prefixed_value(
        text,
        ("previous recommendation", "previous rating", "prior recommendation", "prior rating"),
    )
    if previous:
        return RecommendationChange(
            change_type="changed" if _safe_rating(previous) != new_rating else "reiterated",
            previous_rating=_safe_rating(previous),
            new_rating=new_rating,
            new_target_price=target_price,
            currency=currency,
            reason="The source references a previous recommendation or rating.",
            confidence_score=0.55,
        )
    lowered = text.lower()
    if "reiterate" in lowered or "reiterated" in lowered:
        return RecommendationChange(
            change_type="reiterated",
            new_rating=new_rating,
            new_target_price=target_price,
            currency=currency,
            reason="The source appears to reiterate the rating.",
            confidence_score=0.5,
        )
    return None


def _source_excerpt(
    context: PrivateResearchDocumentContext,
    text: str,
    *,
    label: str,
    excerpt_id: str,
) -> SourceExcerpt:
    page_number = _first_page_number(text)
    return SourceExcerpt(
        excerpt_id=excerpt_id,
        document_id=context.document_id,
        source_name=context.source_name,
        document_title=context.document_title,
        page_number=page_number,
        section=label,
        excerpt=_short_snippet(_strip_page_markers(text), max_words=32, max_chars=220),
        kind="paraphrase",
    )


def _sentence_around(text: str, position: int) -> str:
    start = max(text.rfind(".", 0, position), text.rfind("\n", 0, position))
    end = text.find(".", position)
    if end == -1:
        end = min(len(text), position + 180)
    return text[start + 1 : end + 1].strip()


def _first_page_number(text: str) -> int | None:
    import re

    match = re.search(r"---\s*Page\s+(\d+)\s*---", text)
    return int(match.group(1)) if match else None


def _strip_page_markers(text: str) -> str:
    import re

    return re.sub(r"---\s*Page\s+\d+\s*---", " ", text)


def _risk_severity(value: str) -> str:
    lowered = value.lower()
    if any(term in lowered for term in ("material", "major", "high", "significant")):
        return "high"
    if any(term in lowered for term in ("limited", "minor", "low")):
        return "low"
    return "medium"


def _extract_time_horizon(text: str) -> str | None:
    import re

    match = re.search(r"\b(\d+\s*(?:month|months|year|years))\b", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _short_snippet(value: str, *, max_words: int, max_chars: int) -> str:
    words = " ".join(value.split()).split()
    snippet = " ".join(words[:max_words])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return snippet or "Source-backed private note."


_POSITIVE_RATINGS = {"strong_buy", "buy", "speculative_buy", "accumulate"}


_PRIVATE_SUMMARY_REQUIREMENTS = """
- Summarize what the private source says; do not create new recommendations.
- Capture all company names, tickers, exchanges, source ratings, target prices, valuation notes,
  time horizons, thesis points, bullish arguments, bearish arguments, risks, and catalysts.
- Detect source-stated recommendation changes from previous ratings or targets when supported.
- Preserve source document id, source name, document title, page number, and section when known.
- Keep source excerpts short and use paraphrase where possible.
- Flag uncertain claims, forecasts, valuation numbers, target prices, percentages, multiples,
  dates, market data, and claims needing verification in numbers_to_verify or
  questions_to_verify.
- Frame output as a source summary for private personal use only.
""".strip()


PRIVATE_RESEARCH_CHUNK_SYSTEM_PROMPT = f"""
You extract source-grounded notes from one chunk of a private subscribed research document.
Return only valid JSON matching this JSON Schema:

{json.dumps(PrivateResearchChunkNotes.model_json_schema(), indent=2)}

Private research extraction requirements:
{_PRIVATE_SUMMARY_REQUIREMENTS}

Safety rules:
- Use only the supplied chunk and document context.
- Do not generate new buy/sell/hold advice.
- Do not tailor advice to the user's circumstances, portfolio, risk tolerance, or goals.
- Preserve source attribution and the private-use/general-advice boundary.
- Keep snippets short; do not reproduce full paid reports or long source passages.
- Flag uncertainty and use uncertainty_flags when the chunk is ambiguous or incomplete.
""".strip()


PRIVATE_RESEARCH_SYNTHESIS_SYSTEM_PROMPT = f"""
You synthesize private subscribed-research chunk notes into one structured source summary.
Return only valid JSON matching this JSON Schema:

{json.dumps(PrivateResearchDocument.model_json_schema(), indent=2)}

Private research synthesis requirements:
{_PRIVATE_SUMMARY_REQUIREMENTS}

Safety rules:
- Summarize what the source says; do not add new investment recommendations.
- Do not generate new buy/sell/hold advice, trade instructions, or portfolio allocations.
- Do not tailor advice or personalize output to the user's circumstances, objectives, or
  financial situation.
- Preserve source attribution, document ids, page/section references, and short excerpts.
- Include the general-advice/private-use disclaimer.
- Flag uncertainty and claims needing verification.
- Personal action items must be research questions, not instructions.
""".strip()
