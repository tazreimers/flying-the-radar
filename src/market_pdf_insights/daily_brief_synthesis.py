"""LLM synthesis layer for public daily market-intelligence briefs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
import json
import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from market_pdf_insights.daily_brief_schema import (
    DEFAULT_BRIEF_DISCLAIMER,
    AssetMention,
    BriefRisk,
    BriefSection,
    DailyMarketBrief,
    MacroEvent,
    MarketTheme,
    SourceCitation,
    VerificationFlag,
    WatchlistImpact,
)
from market_pdf_insights.ingestion import NormalizedMarketItem
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
from market_pdf_insights.source_registry import SourceCategory

TModel = TypeVar("TModel", bound=BaseModel)


class SourceGroupNotes(BaseModel):
    """Structured notes extracted from source items before final brief synthesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    category: SourceCategory
    item_count: int = Field(ge=1)
    factual_points: list[str] = Field(default_factory=list)
    commentary_points: list[str] = Field(default_factory=list)
    market_themes: list[str] = Field(default_factory=list)
    macro_events: list[str] = Field(default_factory=list)
    asset_mentions: list[str] = Field(default_factory=list)
    calendar_items: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watchlist_impacts: list[str] = Field(default_factory=list)
    verification_flags: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(min_length=1)
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class DailyBriefSynthesisClient(Protocol):
    """Protocol for clients that synthesize source items into a daily brief."""

    def synthesize_brief(
        self,
        items: Sequence[NormalizedMarketItem],
        *,
        briefing_date: date,
        generated_at: datetime | None = None,
        watchlist_terms: Sequence[str] = (),
    ) -> DailyMarketBrief:
        """Synthesize source items into a validated daily market brief."""


class OpenAIDailyBriefClient:
    """Synthesize daily market briefs with the OpenAI Responses API."""

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

        self.model = model or os.environ.get(MARKET_MODEL_ENV) or DEFAULT_OPENAI_MODEL
        self.max_retries = max_retries
        self._client = openai_client or self._build_client(api_key)

    def synthesize_brief(
        self,
        items: Sequence[NormalizedMarketItem],
        *,
        briefing_date: date,
        generated_at: datetime | None = None,
        watchlist_terms: Sequence[str] = (),
    ) -> DailyMarketBrief:
        """Create grouped notes, then synthesize a validated `DailyMarketBrief`."""

        if not items:
            raise ValueError("At least one normalized source item is required.")

        resolved_generated_at = generated_at or datetime.now(UTC)
        grouped_items = _group_items(items)
        group_notes = [
            self._summarize_source_group(group, watchlist_terms=watchlist_terms)
            for group in grouped_items
        ]
        citations = build_source_citations(items)
        return self._synthesize_final_brief(
            group_notes,
            citations=citations,
            briefing_date=briefing_date,
            generated_at=resolved_generated_at,
            watchlist_terms=watchlist_terms,
        )

    def _build_client(self, api_key: str | None) -> Any:
        resolved_api_key = api_key or os.environ.get(OPENAI_API_KEY_ENV)
        if not resolved_api_key:
            raise LLMConfigurationError(
                f"{OPENAI_API_KEY_ENV} is required when using OpenAIDailyBriefClient."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The openai package is required for OpenAIDailyBriefClient."
            ) from exc

        return OpenAI(api_key=resolved_api_key)

    def _summarize_source_group(
        self,
        items: Sequence[NormalizedMarketItem],
        *,
        watchlist_terms: Sequence[str],
    ) -> SourceGroupNotes:
        citations = build_source_citations(items)
        source = items[0]
        payload = {
            "group_id": _group_id(source),
            "source_id": source.source_id,
            "source_name": source.source_name,
            "category": source.category.value,
            "watchlist_terms": list(watchlist_terms),
            "citations": [citation.model_dump(mode="json") for citation in citations],
            "items": [_source_item_payload(item) for item in items],
        }
        prompt = (
            "Summarize this group of public/legal market-intelligence source items into "
            "structured notes.\n\n"
            f"Source group JSON:\n{json.dumps(payload, indent=2)}"
        )
        return self._request_json_model(
            SourceGroupNotes,
            [
                {"role": "system", "content": SOURCE_GROUP_NOTES_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    def _synthesize_final_brief(
        self,
        notes: Sequence[SourceGroupNotes],
        *,
        citations: Sequence[SourceCitation],
        briefing_date: date,
        generated_at: datetime,
        watchlist_terms: Sequence[str],
    ) -> DailyMarketBrief:
        payload = {
            "briefing_date": briefing_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "watchlist_terms": list(watchlist_terms),
            "source_catalogue": [citation.model_dump(mode="json") for citation in citations],
            "group_notes": [note.model_dump(mode="json") for note in notes],
            "required_disclaimer": DEFAULT_BRIEF_DISCLAIMER,
        }
        prompt = (
            "Synthesize a final public daily market-intelligence brief from these grouped "
            "source notes.\n\n"
            f"Synthesis input JSON:\n{json.dumps(payload, indent=2)}"
        )
        return self._request_json_model(
            DailyMarketBrief,
            [
                {"role": "system", "content": DAILY_BRIEF_SYNTHESIS_SYSTEM_PROMPT},
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
                model=self.model,
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


class MockDailyBriefLLMClient:
    """Deterministic daily brief synthesizer for tests and local wiring."""

    model_name = "mock-daily-brief"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def synthesize_brief(
        self,
        items: Sequence[NormalizedMarketItem],
        *,
        briefing_date: date,
        generated_at: datetime | None = None,
        watchlist_terms: Sequence[str] = (),
    ) -> DailyMarketBrief:
        if not items:
            raise ValueError("At least one normalized source item is required.")

        self.calls.append([item.deduplication_key for item in items])
        generated = generated_at or datetime.now(UTC)
        citations = build_source_citations(items)
        first_citation = citations[0]
        summary = _compose_mock_summary(items)
        stance = _infer_brief_stance(items)

        yesterday_recap = _section(
            "Yesterday Recap",
            summary,
            items,
            citations,
            stance=stance,
        )
        day_ahead = _section(
            "Day Ahead",
            "Watch macro data, source-backed market headlines, and rates-sensitive assets.",
            items,
            citations,
            stance="unclear",
        )
        australia_items = [
            item for item in items if item.category == SourceCategory.AUSTRALIAN_MARKET
        ]
        macro_items = [item for item in items if item.category == SourceCategory.GLOBAL_MACRO]
        commodity_items = [
            item for item in items if _contains_any(item.title + " " + item.body, _COMMODITY_TERMS)
        ]
        rates_items = [
            item for item in items if _contains_any(item.title + " " + item.body, _RATES_TERMS)
        ]
        watchlist_assets = _mock_asset_mentions(items, citations)

        return DailyMarketBrief(
            briefing_date=briefing_date,
            generated_at=generated,
            title=f"Daily Market Intelligence Brief - {briefing_date.isoformat()}",
            executive_summary=summary,
            yesterday_recap=yesterday_recap,
            day_ahead=day_ahead,
            market_stance=stance,
            top_themes=[
                MarketTheme(
                    title="Source-Backed Market Signals",
                    summary=summary,
                    stance=stance,
                    affected_assets=watchlist_assets[:3],
                    citations=[first_citation],
                )
            ],
            australia_market=_section(
                "Australia Market",
                _compose_mock_summary(australia_items or items),
                australia_items or items,
                citations,
                stance=stance,
            ),
            global_macro=_section(
                "Global Macro",
                _compose_mock_summary(macro_items or items),
                macro_items or items,
                citations,
                stance=stance,
            ),
            commodities=_section(
                "Commodities",
                _compose_mock_summary(commodity_items or items),
                commodity_items or items,
                citations,
                stance="mixed",
            ),
            currencies_and_rates=_section(
                "Currencies And Rates",
                _compose_mock_summary(rates_items or items),
                rates_items or items,
                citations,
                stance="unclear",
            ),
            watchlist_impacts=[
                WatchlistImpact(
                    asset=asset,
                    impact_summary=(
                        f"{asset.name or asset.ticker} may be affected by today's "
                        "source-backed market themes."
                    ),
                    stance=asset.stance,
                    drivers=list(watchlist_terms)[:3] or ["source-backed market update"],
                    citations=asset.citations,
                )
                for asset in watchlist_assets[:5]
            ],
            calendar=[],
            macro_events=_mock_macro_events(macro_items, citations),
            risks=_mock_risks(items, citations),
            sources=citations,
            verification_flags=[
                VerificationFlag(
                    claim="Verify numeric market datapoints against primary sources.",
                    reason=(
                        "Daily briefs may contain stale or externally verifiable market data."
                    ),
                    priority="medium",
                    suggested_source="Primary data providers and source URLs",
                    citations=[first_citation],
                )
            ],
            confidence_score=0.65,
            disclaimer=DEFAULT_BRIEF_DISCLAIMER,
        )


class MockBriefLLMClient(MockDailyBriefLLMClient):
    """Short alias for the deterministic daily brief synthesizer."""


def build_source_citations(items: Sequence[NormalizedMarketItem]) -> list[SourceCitation]:
    """Build deduplicated source citations from normalized source items."""

    citations: list[SourceCitation] = []
    seen: set[str] = set()
    for item in items:
        citation = SourceCitation(
            citation_id=_citation_id(item),
            source_id=item.source_id,
            source_name=item.source_name,
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            retrieved_at=item.fetched_at,
            snippet=_short_snippet(item.body or item.title),
            terms_url=item.terms.terms_url or item.attribution.terms_url,
            licence_notes=item.terms.terms_notes or item.attribution.licence_notes,
        )
        if citation.citation_id in seen:
            continue
        seen.add(citation.citation_id)
        citations.append(citation)
    return citations


def _group_items(items: Sequence[NormalizedMarketItem]) -> list[list[NormalizedMarketItem]]:
    groups: dict[tuple[str, str], list[NormalizedMarketItem]] = defaultdict(list)
    for item in items:
        groups[(item.category.value, item.source_id)].append(item)
    return list(groups.values())


def _source_item_payload(item: NormalizedMarketItem) -> dict[str, Any]:
    return {
        "deduplication_key": item.deduplication_key,
        "title": item.title,
        "body_summary": _short_snippet(item.body),
        "url": item.url,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "fetched_at": item.fetched_at.isoformat(),
        "category": item.category.value,
        "tickers": list(item.tickers),
        "citation_id": _citation_id(item),
        "terms_url": item.terms.terms_url,
        "licence_notes": item.terms.terms_notes,
    }


def _section(
    title: str,
    summary: str,
    items: Sequence[NormalizedMarketItem],
    all_citations: Sequence[SourceCitation],
    *,
    stance: str,
) -> BriefSection:
    citations = _citations_for_items(items, all_citations)
    return BriefSection(
        title=title,
        summary=summary,
        bullets=[_short_snippet(item.title, max_words=14) for item in items[:4]],
        stance=stance,
        citations=citations or list(all_citations[:1]),
    )


def _mock_asset_mentions(
    items: Sequence[NormalizedMarketItem],
    citations: Sequence[SourceCitation],
) -> list[AssetMention]:
    mentions: list[AssetMention] = []
    seen: set[str] = set()
    for item in items:
        item_citations = _citations_for_items([item], citations)
        for ticker in item.tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            mentions.append(
                AssetMention(
                    ticker=ticker,
                    asset_type=_asset_type_from_ticker(ticker),
                    stance=_infer_item_stance(item),
                    rationale=_short_snippet(item.title, max_words=16),
                    citations=item_citations,
                )
            )
    if not mentions and items:
        mentions.append(
            AssetMention(
                name=items[0].source_name,
                asset_type="other",
                stance="unclear",
                rationale=_short_snippet(items[0].title, max_words=16),
                citations=list(citations[:1]),
            )
        )
    return mentions


def _mock_macro_events(
    items: Sequence[NormalizedMarketItem],
    citations: Sequence[SourceCitation],
) -> list[MacroEvent]:
    events: list[MacroEvent] = []
    for item in items[:3]:
        events.append(
            MacroEvent(
                event_name=item.title,
                region=None,
                indicator=item.tickers[0] if item.tickers else None,
                actual=None,
                event_time=item.published_at,
                importance="medium",
                market_readthrough=_short_snippet(item.body or item.title),
                citations=_citations_for_items([item], citations),
            )
        )
    return events


def _mock_risks(
    items: Sequence[NormalizedMarketItem],
    citations: Sequence[SourceCitation],
) -> list[BriefRisk]:
    risk_items = [
        item for item in items if _contains_any(item.title + " " + item.body, _RISK_TERMS)
    ]
    if not risk_items and items:
        risk_items = [items[0]]
    return [
        BriefRisk(
            description=(
                "Market conditions may change quickly; verify source-backed datapoints "
                "before relying on the brief."
            ),
            severity="medium",
            affected_assets=_mock_asset_mentions(risk_items[:1], citations)[:2],
            watch_items=["primary source updates", "market data revisions"],
            citations=_citations_for_items(risk_items[:1], citations) or list(citations[:1]),
        )
    ]


def _citations_for_items(
    items: Sequence[NormalizedMarketItem],
    citations: Sequence[SourceCitation],
) -> list[SourceCitation]:
    wanted_ids = {_citation_id(item) for item in items}
    return [citation for citation in citations if citation.citation_id in wanted_ids]


def _compose_mock_summary(items: Sequence[NormalizedMarketItem]) -> str:
    if not items:
        return "No source-backed items were available for this section."
    fragments = [_short_snippet(item.title, max_words=16) for item in items[:3]]
    return " ".join(fragments)


def _infer_brief_stance(items: Sequence[NormalizedMarketItem]) -> str:
    stances = {_infer_item_stance(item) for item in items}
    directional = stances - {"unclear", "neutral"}
    if len(directional) > 1:
        return "mixed"
    if directional:
        return next(iter(directional))
    if "neutral" in stances:
        return "neutral"
    return "unclear"


def _infer_item_stance(item: NormalizedMarketItem) -> str:
    text = f"{item.title} {item.body}".lower()
    bullish = _contains_any(text, _BULLISH_TERMS)
    bearish = _contains_any(text, _BEARISH_TERMS)
    if bullish and bearish:
        return "mixed"
    if bullish:
        return "bullish"
    if bearish:
        return "bearish"
    return "unclear"


def _asset_type_from_ticker(ticker: str) -> str:
    if ticker in {"AUD", "USD", "EUR", "JPY", "GBP", "CAD", "NZD"}:
        return "currency"
    if ticker in {"DGS10", "CASH", "FEDFUNDS"}:
        return "rate"
    return "ticker"


def _citation_id(item: NormalizedMarketItem) -> str:
    return f"{item.source_id}-{item.deduplication_key.rsplit(':', maxsplit=1)[-1][:8]}"


def _group_id(item: NormalizedMarketItem) -> str:
    return f"{item.category.value}:{item.source_id}"


def _short_snippet(value: str, *, max_words: int = 40, max_chars: int = 240) -> str:
    words = " ".join(value.split()).split()
    snippet = " ".join(words[:max_words])
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return snippet or "Source item available."


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


_BULLISH_TERMS = ("rise", "rises", "rose", "higher", "growth", "improves", "support")
_BEARISH_TERMS = ("fall", "falls", "fell", "lower", "risk", "pressure", "weak")
_RISK_TERMS = ("risk", "pressure", "volatility", "uncertain", "shock", "downside")
_COMMODITY_TERMS = ("commodity", "oil", "gold", "copper", "lithium", "iron ore")
_RATES_TERMS = ("rate", "rates", "yield", "bond", "currency", "aud", "usd")


SOURCE_GROUP_NOTES_SYSTEM_PROMPT = f"""
You summarize public/legal market-intelligence source items into structured notes.
Return only valid JSON matching this JSON Schema:

{json.dumps(SourceGroupNotes.model_json_schema(), indent=2)}

Rules:
- Use only the supplied source items and citation catalogue.
- Distinguish factual observations from commentary or market readthrough.
- Preserve citation ids, source names, source URLs, retrieval timestamps, and terms metadata.
- Keep snippets short. Do not copy long source text or reproduce full articles.
- Flag unsupported, stale, numerical, or externally verifiable claims in verification_flags.
- Call out Australia, global macro, rates, currencies, commodities, sectors, and watchlist
  impacts when the source items support them.
- Do not provide financial advice or instructions to buy, sell, hold, rebalance, or trade.
""".strip()


DAILY_BRIEF_SYNTHESIS_SYSTEM_PROMPT = f"""
You synthesize grouped notes into a public daily market-intelligence brief.
Return only valid JSON matching this JSON Schema:

{json.dumps(DailyMarketBrief.model_json_schema(), indent=2)}

Rules:
- Use only the grouped notes and source catalogue.
- Preserve first-class citations and include every nested citation in top-level sources.
- Distinguish facts from commentary and market readthrough.
- Keep source snippets short. Never reproduce full copyrighted articles or paid reports.
- Summarize yesterday_recap and day_ahead separately.
- Include Australia, global macro, rates, currencies, commodities, sectors, watchlist impacts,
  calendar events, risks, and verification flags when supported.
- Put unsupported, stale, numerical, or externally verifiable claims in verification_flags.
- Keep output factual/general. Do not personalize to the reader's circumstances.
- Do not give financial advice or instructions to buy, sell, hold, rebalance, or trade.
- Use this disclaimer exactly when possible: {DEFAULT_BRIEF_DISCLAIMER}
""".strip()
