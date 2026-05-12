"""Structured schema for private stock recommendation research."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

RecommendationRating = Literal[
    "strong_buy",
    "buy",
    "speculative_buy",
    "accumulate",
    "hold",
    "neutral",
    "reduce",
    "sell",
    "avoid",
    "under_review",
    "not_rated",
]
RecommendationChangeType = Literal[
    "initiated",
    "upgraded",
    "downgraded",
    "reiterated",
    "suspended",
    "removed",
    "changed",
]
ThesisStance = Literal["bullish", "bearish", "balanced", "neutral", "unclear"]
RiskSeverity = Literal["low", "medium", "high", "unknown"]
CatalystDirection = Literal["positive", "negative", "mixed", "unclear"]
WatchItemStatus = Literal["watch", "monitor", "review", "resolved", "archived"]
ExcerptKind = Literal["quote", "paraphrase", "table", "chart", "metadata"]

MAX_SOURCE_EXCERPT_WORDS = 55
MAX_SOURCE_EXCERPT_CHARS = 360


class StrictPrivateResearchModel(BaseModel):
    """Base model with strict keys and assignment validation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class SourceExcerpt(StrictPrivateResearchModel):
    """Short source-backed reference without reproducing full subscribed content."""

    excerpt_id: NonEmptyStr = Field(description="Stable local excerpt id.")
    document_id: NonEmptyStr = Field(description="Private source document id.")
    source_name: NonEmptyStr = Field(description="Source publication or provider name.")
    document_title: NonEmptyStr = Field(description="Private source document title.")
    page_number: int | None = Field(default=None, ge=1, description="PDF page when available.")
    section: NonEmptyStr | None = Field(default=None, description="Source section when available.")
    location_label: NonEmptyStr | None = Field(
        default=None,
        description="Fallback location label, such as email subject or chart/table name.",
    )
    excerpt: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SOURCE_EXCERPT_CHARS,
        description="Short excerpt or paraphrase. Never store full subscribed content.",
    )
    kind: ExcerptKind = Field(default="paraphrase", description="Type of source reference.")

    @field_validator("excerpt")
    @classmethod
    def _keep_excerpt_short(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized.split()) > MAX_SOURCE_EXCERPT_WORDS:
            raise ValueError(
                f"source excerpts must be {MAX_SOURCE_EXCERPT_WORDS} words or fewer"
            )
        return normalized


class NumberToVerify(StrictPrivateResearchModel):
    """Numeric or factual item that should be checked against source/market data."""

    value: NonEmptyStr = Field(description="Number, date, multiple, price, or statistic.")
    context: NonEmptyStr = Field(description="What the number relates to.")
    suggested_check: NonEmptyStr | None = Field(
        default=None,
        description="Suggested source or check before relying on the number.",
    )
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class ThesisPoint(StrictPrivateResearchModel):
    """A thesis, upside argument, downside argument, or neutral observation."""

    point: NonEmptyStr = Field(description="Concise thesis point.")
    stance: ThesisStance = Field(default="unclear", description="Direction of the point.")
    evidence_summary: NonEmptyStr | None = Field(
        default=None,
        description="Short paraphrase of the supporting evidence.",
    )
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class RiskPoint(StrictPrivateResearchModel):
    """Risk or downside scenario raised by the source."""

    risk: NonEmptyStr = Field(description="Concise risk description.")
    severity: RiskSeverity = Field(default="unknown")
    affected_metric: NonEmptyStr | None = Field(default=None)
    mitigation_or_offset: NonEmptyStr | None = Field(default=None)
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class ValuationNote(StrictPrivateResearchModel):
    """Valuation method, target price, assumptions, and checks from the source."""

    valuation_summary: NonEmptyStr = Field(description="Concise valuation note.")
    method: NonEmptyStr | None = Field(default=None, description="DCF, PE, EV/EBITDA, NTA, etc.")
    stated_target_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="Currency code for target price or valuation when available.",
    )
    assumptions: list[NonEmptyStr] = Field(default_factory=list)
    numbers_to_verify: list[NumberToVerify] = Field(default_factory=list)
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value

    @field_validator("assumptions")
    @classmethod
    def _dedupe_assumptions(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class Catalyst(StrictPrivateResearchModel):
    """Event or condition that could affect the recommendation."""

    catalyst: NonEmptyStr = Field(description="Catalyst description.")
    expected_timing: NonEmptyStr | None = Field(default=None)
    direction: CatalystDirection = Field(default="unclear")
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class RecommendationChange(StrictPrivateResearchModel):
    """Change in source recommendation, rating, or target."""

    change_type: RecommendationChangeType = Field(default="changed")
    previous_rating: RecommendationRating | None = None
    new_rating: RecommendationRating
    previous_target_price: float | None = Field(default=None, ge=0)
    new_target_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    change_date: date | None = None
    reason: NonEmptyStr | None = None
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("previous_rating", "new_rating", mode="before")
    @classmethod
    def _normalize_rating_fields(cls, value: Any) -> Any:
        return normalize_recommendation_rating(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value


class PortfolioWatchItem(StrictPrivateResearchModel):
    """Personal watchlist item derived from source facts, not a trade instruction."""

    item_id: NonEmptyStr = Field(description="Stable local watch item id.")
    company_name: NonEmptyStr | None = None
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{1,16}$")
    exchange: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{2,12}$")
    watch_reason: NonEmptyStr = Field(description="Why this item should be monitored.")
    trigger_to_watch: NonEmptyStr | None = Field(default=None)
    status: WatchItemStatus = Field(default="watch")
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("ticker", "exchange", mode="before")
    @classmethod
    def _normalize_market_code(cls, value: Any) -> Any:
        return _normalize_market_code(value)

    @model_validator(mode="after")
    def _require_company_or_ticker(self) -> Self:
        if self.company_name is None and self.ticker is None:
            raise ValueError("PortfolioWatchItem requires company_name or ticker")
        return self


class PersonalActionQuestion(StrictPrivateResearchModel):
    """Question for the user to investigate without instructing a trade."""

    question_id: NonEmptyStr = Field(description="Stable local question id.")
    question: NonEmptyStr = Field(description="Research/checklist question for the user.")
    why_it_matters: NonEmptyStr | None = None
    related_ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{1,16}$")
    related_recommendation_id: NonEmptyStr | None = None
    source_excerpt: SourceExcerpt | None = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("question")
    @classmethod
    def _require_question_not_instruction(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized.endswith("?"):
            raise ValueError("personal action items must be framed as questions")
        if re.search(r"\b(should\s+i\s+)?(buy|sell|hold|trade)\b", normalized, re.I):
            raise ValueError("personal action questions must not instruct buy/sell/hold/trade")
        return normalized

    @field_validator("related_ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, value: Any) -> Any:
        return _normalize_market_code(value)


class StockRecommendation(StrictPrivateResearchModel):
    """Structured recommendation for one company or listed security."""

    recommendation_id: NonEmptyStr = Field(description="Stable local recommendation id.")
    company_name: NonEmptyStr = Field(description="Company name from the source.")
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{1,16}$")
    exchange: str | None = Field(default=None, pattern=r"^[A-Z0-9.\-]{2,12}$")
    recommendation: RecommendationRating = Field(description="Canonical source rating.")
    source_rating: NonEmptyStr | None = Field(
        default=None,
        description="Original source rating label if different from canonical value.",
    )
    stated_target_price: float | None = Field(default=None, ge=0)
    target_price_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    stated_valuation: NonEmptyStr | None = Field(default=None)
    recommendation_date: date | None = None
    time_horizon: NonEmptyStr | None = None
    thesis: NonEmptyStr | None = Field(default=None, description="Overall thesis.")
    thesis_points: list[ThesisPoint] = Field(default_factory=list)
    bullish_arguments: list[ThesisPoint] = Field(default_factory=list)
    bearish_arguments: list[ThesisPoint] = Field(default_factory=list)
    risks: list[RiskPoint] = Field(default_factory=list)
    catalysts: list[Catalyst] = Field(default_factory=list)
    valuation_notes: list[ValuationNote] = Field(default_factory=list)
    valuation_assumptions: list[NonEmptyStr] = Field(default_factory=list)
    recommendation_changes: list[RecommendationChange] = Field(default_factory=list)
    portfolio_watch_items: list[PortfolioWatchItem] = Field(default_factory=list)
    numbers_to_verify: list[NumberToVerify] = Field(default_factory=list)
    source_citation: SourceExcerpt = Field(description="Primary short source citation.")
    confidence_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("recommendation", mode="before")
    @classmethod
    def _normalize_recommendation(cls, value: Any) -> Any:
        return normalize_recommendation_rating(value)

    @field_validator("ticker", "exchange", mode="before")
    @classmethod
    def _normalize_market_codes(cls, value: Any) -> Any:
        return _normalize_market_code(value)

    @field_validator("target_price_currency", mode="before")
    @classmethod
    def _normalize_target_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value

    @field_validator("valuation_assumptions")
    @classmethod
    def _dedupe_valuation_assumptions(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)

    @model_validator(mode="after")
    def _validate_argument_stance(self) -> Self:
        for point in self.bullish_arguments:
            if point.stance == "bearish":
                raise ValueError("bullish_arguments cannot contain bearish thesis points")
        for point in self.bearish_arguments:
            if point.stance == "bullish":
                raise ValueError("bearish_arguments cannot contain bullish thesis points")
        return self


class PrivateResearchDocument(StrictPrivateResearchModel):
    """Source-light structured summary of a private subscribed research document."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "document_id": "private-example-2026-05-12",
                "source_name": "Under the Radar",
                "document_title": "Under the Radar Small-Cap Note",
                "issue_date": "2026-05-12",
                "source_type": "pdf",
                "original_filename": "under-the-radar-sample.pdf",
                "document_summary": (
                    "The note reiterates a speculative buy rating on Example Resources "
                    "while highlighting funding, execution, and quarterly update risks."
                ),
                "recommendations": [
                    {
                        "recommendation_id": "rec-exr-2026-05-12",
                        "company_name": "Example Resources",
                        "ticker": "EXR",
                        "exchange": "ASX",
                        "recommendation": "Speculative Buy",
                        "source_rating": "Speculative Buy",
                        "stated_target_price": 1.35,
                        "target_price_currency": "AUD",
                        "stated_valuation": "Target price based on staged project delivery.",
                        "recommendation_date": "2026-05-12",
                        "time_horizon": "12 months",
                        "thesis": (
                            "The source expects project milestones to improve market confidence."
                        ),
                        "thesis_points": [
                            {
                                "point": "Project delivery is the main thesis driver.",
                                "stance": "bullish",
                                "evidence_summary": "Milestones are framed as valuation support.",
                                "confidence_score": 0.72,
                            }
                        ],
                        "bullish_arguments": [
                            {
                                "point": "Upcoming project milestones could support sentiment.",
                                "stance": "bullish",
                                "confidence_score": 0.7,
                            }
                        ],
                        "bearish_arguments": [
                            {
                                "point": "Funding and execution remain key uncertainties.",
                                "stance": "bearish",
                                "confidence_score": 0.68,
                            }
                        ],
                        "risks": [
                            {
                                "risk": "Project delays could pressure the valuation case.",
                                "severity": "medium",
                                "affected_metric": "target price",
                                "confidence_score": 0.7,
                            }
                        ],
                        "catalysts": [
                            {
                                "catalyst": "Quarterly project update",
                                "expected_timing": "next quarter",
                                "direction": "positive",
                                "confidence_score": 0.64,
                            }
                        ],
                        "valuation_notes": [
                            {
                                "valuation_summary": "The source states a AUD 1.35 target price.",
                                "method": "project milestone valuation",
                                "stated_target_price": 1.35,
                                "currency": "AUD",
                                "assumptions": ["Milestones arrive on schedule."],
                                "numbers_to_verify": [
                                    {
                                        "value": "AUD 1.35",
                                        "context": "Stated source target price.",
                                        "suggested_check": "Check against the original report.",
                                        "confidence_score": 0.75,
                                    }
                                ],
                                "confidence_score": 0.72,
                            }
                        ],
                        "valuation_assumptions": ["Milestones arrive on schedule."],
                        "recommendation_changes": [
                            {
                                "change_type": "reiterated",
                                "new_rating": "Speculative Buy",
                                "new_target_price": 1.35,
                                "currency": "AUD",
                                "change_date": "2026-05-12",
                                "reason": "The rating was reiterated in the source note.",
                                "confidence_score": 0.7,
                            }
                        ],
                        "portfolio_watch_items": [
                            {
                                "item_id": "watch-exr-update",
                                "company_name": "Example Resources",
                                "ticker": "EXR",
                                "exchange": "ASX",
                                "watch_reason": "Track whether project milestones arrive.",
                                "trigger_to_watch": "Quarterly update",
                                "status": "watch",
                                "confidence_score": 0.7,
                            }
                        ],
                        "numbers_to_verify": [
                            {
                                "value": "AUD 1.35",
                                "context": "Target price.",
                                "suggested_check": "Check source PDF and current market data.",
                                "confidence_score": 0.75,
                            }
                        ],
                        "source_citation": {
                            "excerpt_id": "exr-rating-page-2",
                            "document_id": "private-example-2026-05-12",
                            "source_name": "Under the Radar",
                            "document_title": "Under the Radar Small-Cap Note",
                            "page_number": 2,
                            "section": "Recommendation",
                            "excerpt": "Speculative buy rating with a stated AUD 1.35 target.",
                            "kind": "paraphrase",
                        },
                        "confidence_score": 0.72,
                    }
                ],
                "portfolio_watch_items": [
                    {
                        "item_id": "watch-exr-position-risk",
                        "company_name": "Example Resources",
                        "ticker": "EXR",
                        "exchange": "ASX",
                        "watch_reason": "Review exposure if funding risk increases.",
                        "trigger_to_watch": "Capital raising update",
                        "status": "monitor",
                        "confidence_score": 0.65,
                    }
                ],
                "source_excerpts": [
                    {
                        "excerpt_id": "exr-rating-page-2",
                        "document_id": "private-example-2026-05-12",
                        "source_name": "Under the Radar",
                        "document_title": "Under the Radar Small-Cap Note",
                        "page_number": 2,
                        "section": "Recommendation",
                        "excerpt": "Speculative buy rating with a stated AUD 1.35 target.",
                        "kind": "paraphrase",
                    }
                ],
                "numbers_to_verify": [
                    {
                        "value": "AUD 1.35",
                        "context": "Target price cited in the source note.",
                        "suggested_check": "Verify against the original report and market price.",
                        "confidence_score": 0.75,
                    }
                ],
                "personal_action_questions": [
                    {
                        "question_id": "q-exr-risk-fit",
                        "question": "What portfolio risk would this position add?",
                        "why_it_matters": "The source highlights execution and funding risks.",
                        "related_ticker": "EXR",
                        "related_recommendation_id": "rec-exr-2026-05-12",
                        "confidence_score": 0.7,
                    }
                ],
                "confidence_score": 0.72,
                "disclaimer": (
                    "Private research summary for personal use only. It is not personal "
                    "financial advice and must not be redistributed."
                ),
            }
        },
    )

    document_id: NonEmptyStr = Field(description="Private document id from local storage.")
    source_name: NonEmptyStr = Field(description="Source publication or provider name.")
    document_title: NonEmptyStr = Field(description="Document title.")
    issue_date: date | None = Field(default=None)
    imported_at: datetime | None = Field(default=None)
    source_type: NonEmptyStr | None = Field(default=None)
    original_filename: NonEmptyStr | None = Field(default=None)
    document_summary: NonEmptyStr = Field(description="Brief summary without full source text.")
    recommendations: list[StockRecommendation] = Field(default_factory=list)
    portfolio_watch_items: list[PortfolioWatchItem] = Field(default_factory=list)
    source_excerpts: list[SourceExcerpt] = Field(default_factory=list)
    numbers_to_verify: list[NumberToVerify] = Field(default_factory=list)
    personal_action_questions: list[PersonalActionQuestion] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1)
    disclaimer: NonEmptyStr = Field(
        default=(
            "Private research summary for personal use only. It is not personal financial "
            "advice and must not be redistributed."
        )
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_private_document(self) -> Self:
        if self.imported_at is not None and self.imported_at.tzinfo is None:
            raise ValueError("imported_at must include timezone information")
        if not self.recommendations and not self.portfolio_watch_items:
            raise ValueError(
                "PrivateResearchDocument requires at least one recommendation or watch item"
            )
        for excerpt in _collect_source_excerpts(
            [
                self.recommendations,
                self.portfolio_watch_items,
                self.source_excerpts,
                self.numbers_to_verify,
                self.personal_action_questions,
            ]
        ):
            if excerpt.document_id != self.document_id:
                raise ValueError("source excerpts must reference the parent document_id")
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""

        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the private research document to JSON."""

        separators = (",", ":") if indent is None else None
        return json.dumps(self.to_dict(), indent=indent, separators=separators, sort_keys=True)

    @classmethod
    def example(cls) -> PrivateResearchDocument:
        """Return a validated example private research document."""

        return cls.model_validate(cls.model_config["json_schema_extra"]["example"])

    @classmethod
    def example_json(cls, *, indent: int | None = 2) -> str:
        """Return the validated example document as JSON."""

        return cls.example().to_json(indent=indent)


def normalize_recommendation_rating(value: Any) -> Any:
    """Normalize common source rating labels to canonical schema values."""

    if value is None:
        return None
    if not isinstance(value, str):
        return value
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")
    if not key:
        return value
    normalized = _RATING_ALIASES.get(key, key)
    if normalized not in _ALLOWED_RATINGS:
        raise ValueError(f"unsupported recommendation rating: {value}")
    return normalized


def _normalize_market_code(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped.upper() if stripped else None
    return value


def _collect_source_excerpts(value: Any) -> list[SourceExcerpt]:
    if isinstance(value, SourceExcerpt):
        return [value]
    if isinstance(value, BaseModel):
        excerpts: list[SourceExcerpt] = []
        for field_name in value.__class__.model_fields:
            excerpts.extend(_collect_source_excerpts(getattr(value, field_name)))
        return excerpts
    if isinstance(value, list | tuple | set):
        excerpts = []
        for item in value:
            excerpts.extend(_collect_source_excerpts(item))
        return excerpts
    if isinstance(value, dict):
        excerpts = []
        for item in value.values():
            excerpts.extend(_collect_source_excerpts(item))
        return excerpts
    return []


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


_ALLOWED_RATINGS = frozenset(
    {
        "strong_buy",
        "buy",
        "speculative_buy",
        "accumulate",
        "hold",
        "neutral",
        "reduce",
        "sell",
        "avoid",
        "under_review",
        "not_rated",
    }
)

_RATING_ALIASES = {
    "strong_buy": "strong_buy",
    "outperform": "buy",
    "add": "accumulate",
    "spec_buy": "speculative_buy",
    "speculative_buy": "speculative_buy",
    "speculative": "speculative_buy",
    "market_perform": "neutral",
    "equal_weight": "neutral",
    "underperform": "reduce",
    "take_profit": "reduce",
    "no_rating": "not_rated",
    "not_rated": "not_rated",
    "under_review": "under_review",
    "suspended": "under_review",
}
