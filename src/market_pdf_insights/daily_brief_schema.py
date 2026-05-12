"""Structured schema for public daily market-intelligence briefs."""

from __future__ import annotations

from datetime import date, datetime
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

BriefMarketStance = Literal["bullish", "bearish", "neutral", "mixed", "unclear"]
BriefImportance = Literal["low", "medium", "high"]
BriefRiskSeverity = Literal["low", "medium", "high", "unknown"]
BriefVerificationPriority = Literal["low", "medium", "high"]
BriefAssetType = Literal[
    "company",
    "ticker",
    "index",
    "fund",
    "commodity",
    "currency",
    "rate",
    "sector",
    "macro_indicator",
    "other",
]
CalendarEventType = Literal[
    "economic_release",
    "central_bank",
    "earnings",
    "market_holiday",
    "dividend",
    "policy",
    "other",
]

DEFAULT_BRIEF_DISCLAIMER = (
    "This briefing summarizes factual market information and general market commentary from "
    "identified sources. It is not financial, investment, tax, legal, or accounting advice."
)


class StrictBriefModel(BaseModel):
    """Base model with strict output keys and assignment validation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class SourceCitation(StrictBriefModel):
    """Short source citation preserved with generated brief claims."""

    citation_id: NonEmptyStr = Field(description="Stable id used to reference this citation.")
    source_id: NonEmptyStr = Field(description="Source registry id.")
    source_name: NonEmptyStr = Field(description="Human-readable source name.")
    title: NonEmptyStr | None = Field(default=None, description="Source item title.")
    url: str | None = Field(default=None, description="Source item URL when available.")
    published_at: datetime | None = Field(
        default=None,
        description="Publication timestamp when available.",
    )
    retrieved_at: datetime | None = Field(
        default=None,
        description="Retrieval timestamp when available.",
    )
    snippet: str | None = Field(
        default=None,
        min_length=1,
        max_length=280,
        description="Short excerpt or paraphrased source note, not full copyrighted text.",
    )
    terms_url: str | None = Field(default=None, description="Terms/licence URL.")
    licence_notes: str | None = Field(default=None, description="Short licence/terms note.")

    @field_validator("source_id", "citation_id")
    @classmethod
    def _normalize_ids(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("snippet")
    @classmethod
    def _keep_snippet_short(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized.split()) > 60:
            raise ValueError("citation snippets must be 60 words or fewer")
        return normalized


class SourceBackedModel(StrictBriefModel):
    """Base for claims that normally require source citations."""

    source_backed: bool = Field(
        default=True,
        description="Whether this claim is backed by external source material.",
    )
    citations: list[SourceCitation] = Field(
        default_factory=list,
        description="Citations supporting this claim or section.",
    )

    @model_validator(mode="after")
    def _require_citations_when_source_backed(self) -> Self:
        if self.source_backed and not self.citations:
            raise ValueError("source-backed brief content requires at least one citation")
        return self


class AssetMention(SourceBackedModel):
    """An asset, market, sector, index, currency, commodity, or rate mentioned in the brief."""

    name: NonEmptyStr | None = Field(default=None, description="Asset or market name.")
    ticker: str | None = Field(
        default=None,
        pattern=r"^[A-Z0-9.\-]{1,16}$",
        description="Ticker or symbol when available.",
    )
    asset_type: BriefAssetType = Field(default="other", description="Type of asset.")
    region: NonEmptyStr | None = Field(default=None, description="Relevant region.")
    stance: BriefMarketStance = Field(default="unclear", description="Directional tone.")
    rationale: NonEmptyStr | None = Field(default=None, description="Why the asset matters.")

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value

    @model_validator(mode="after")
    def _require_name_or_ticker(self) -> Self:
        if self.name is None and self.ticker is None:
            raise ValueError("AssetMention requires at least one of name or ticker.")
        return self


class BriefSection(SourceBackedModel):
    """Reusable section for daily brief narrative."""

    title: NonEmptyStr = Field(description="Section heading.")
    summary: NonEmptyStr = Field(description="Concise section summary.")
    bullets: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Short supporting bullets for email/web display.",
    )
    stance: BriefMarketStance = Field(default="unclear", description="Section stance.")

    @field_validator("bullets")
    @classmethod
    def _dedupe_bullets(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class MarketTheme(SourceBackedModel):
    """A top market theme for the day."""

    title: NonEmptyStr = Field(description="Theme title.")
    summary: NonEmptyStr = Field(description="Why the theme matters.")
    stance: BriefMarketStance = Field(default="unclear", description="Theme stance.")
    affected_assets: list[AssetMention] = Field(
        default_factory=list,
        description="Assets, sectors, or indicators affected by the theme.",
    )


class MacroEvent(SourceBackedModel):
    """Macro release or event included in the brief."""

    event_name: NonEmptyStr = Field(description="Macro event or release name.")
    region: NonEmptyStr | None = Field(default=None, description="Country or region.")
    indicator: NonEmptyStr | None = Field(default=None, description="Macro indicator.")
    actual: NonEmptyStr | None = Field(default=None, description="Actual reported value.")
    forecast: NonEmptyStr | None = Field(default=None, description="Expected value.")
    previous: NonEmptyStr | None = Field(default=None, description="Previous value.")
    event_time: datetime | None = Field(default=None, description="Release timestamp.")
    importance: BriefImportance = Field(default="medium", description="Market relevance.")
    market_readthrough: NonEmptyStr | None = Field(
        default=None,
        description="General market readthrough, not personal advice.",
    )


class CalendarEvent(SourceBackedModel):
    """Forward-looking calendar item for the day ahead."""

    event_date: date = Field(description="Calendar date.")
    title: NonEmptyStr = Field(description="Event title.")
    event_type: CalendarEventType = Field(default="other", description="Event category.")
    region: NonEmptyStr | None = Field(default=None, description="Country or region.")
    time_label: NonEmptyStr | None = Field(
        default=None,
        description="Human-readable local time label when exact datetime is unavailable.",
    )
    importance: BriefImportance = Field(default="medium", description="Market relevance.")
    expected_readthrough: NonEmptyStr | None = Field(
        default=None,
        description="General expected market relevance.",
    )


class WatchlistImpact(SourceBackedModel):
    """General impact note for a watched asset or theme."""

    asset: AssetMention = Field(description="Watched asset, market, sector, or indicator.")
    impact_summary: NonEmptyStr = Field(description="General impact summary.")
    stance: BriefMarketStance = Field(default="unclear", description="Directional tone.")
    drivers: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Short source-backed drivers.",
    )

    @field_validator("drivers")
    @classmethod
    def _dedupe_drivers(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class BriefRisk(SourceBackedModel):
    """Risk or uncertainty highlighted in the daily brief."""

    description: NonEmptyStr = Field(description="Risk description.")
    severity: BriefRiskSeverity = Field(default="unknown", description="Risk severity.")
    affected_assets: list[AssetMention] = Field(default_factory=list)
    watch_items: list[NonEmptyStr] = Field(default_factory=list)

    @field_validator("watch_items")
    @classmethod
    def _dedupe_watch_items(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class VerificationFlag(SourceBackedModel):
    """Flag for data points or claims that need human verification."""

    claim: NonEmptyStr = Field(description="Claim, data point, or number to verify.")
    reason: NonEmptyStr = Field(description="Why verification is required.")
    priority: BriefVerificationPriority = Field(default="medium")
    suggested_source: NonEmptyStr | None = Field(
        default=None,
        description="Primary source or dataset to check.",
    )


class DailyMarketBrief(StrictBriefModel):
    """Structured daily public market-intelligence brief."""

    briefing_date: date = Field(description="Date the brief is for.")
    generated_at: datetime = Field(description="Generation timestamp.")
    title: NonEmptyStr = Field(description="Brief title.")
    executive_summary: NonEmptyStr = Field(description="Top-level concise summary.")
    yesterday_recap: BriefSection = Field(description="Prior-session recap.")
    day_ahead: BriefSection = Field(description="Forward-looking day-ahead summary.")
    market_stance: BriefMarketStance = Field(description="Overall market stance.")
    top_themes: list[MarketTheme] = Field(default_factory=list)
    australia_market: BriefSection = Field(description="Australian market section.")
    global_macro: BriefSection = Field(description="Global macro section.")
    commodities: BriefSection = Field(description="Commodities section.")
    currencies_and_rates: BriefSection = Field(description="Currencies and rates section.")
    watchlist_impacts: list[WatchlistImpact] = Field(default_factory=list)
    calendar: list[CalendarEvent] = Field(default_factory=list)
    macro_events: list[MacroEvent] = Field(default_factory=list)
    risks: list[BriefRisk] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(
        min_length=1,
        description="Source citation catalogue for the brief.",
    )
    verification_flags: list[VerificationFlag] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1, description="Overall confidence from 0 to 1.")
    disclaimer: NonEmptyStr = Field(default=DEFAULT_BRIEF_DISCLAIMER)

    @model_validator(mode="after")
    def _validate_daily_brief(self) -> Self:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must include timezone information")

        citation_ids = [source.citation_id for source in self.sources]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("sources must not contain duplicate citation_id values")

        catalog_ids = set(citation_ids)
        component_ids = set()
        for field_name in (
            "yesterday_recap",
            "day_ahead",
            "top_themes",
            "australia_market",
            "global_macro",
            "commodities",
            "currencies_and_rates",
            "watchlist_impacts",
            "calendar",
            "macro_events",
            "risks",
            "verification_flags",
        ):
            component_ids.update(_collect_citation_ids(getattr(self, field_name)))

        missing_ids = sorted(component_ids - catalog_ids)
        if missing_ids:
            raise ValueError(f"brief citations missing from sources catalogue: {missing_ids}")
        return self


def _collect_citation_ids(value: Any) -> set[str]:
    citation_ids: set[str] = set()
    if isinstance(value, SourceCitation):
        citation_ids.add(value.citation_id)
    elif isinstance(value, BaseModel):
        for field_name in value.__class__.model_fields:
            citation_ids.update(_collect_citation_ids(getattr(value, field_name)))
    elif isinstance(value, list | tuple | set):
        for item in value:
            citation_ids.update(_collect_citation_ids(item))
    elif isinstance(value, dict):
        for item in value.values():
            citation_ids.update(_collect_citation_ids(item))
    return citation_ids


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
