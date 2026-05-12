from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from unittest.mock import patch

import pytest

from market_pdf_insights.australian_connectors import rba_source
from market_pdf_insights.daily_brief_schema import DailyMarketBrief
from market_pdf_insights.daily_brief_synthesis import (
    DAILY_BRIEF_SYNTHESIS_SYSTEM_PROMPT,
    SOURCE_GROUP_NOTES_SYSTEM_PROMPT,
    MockDailyBriefLLMClient,
    OpenAIDailyBriefClient,
    SourceGroupNotes,
    build_source_citations,
)
from market_pdf_insights.global_connectors import fred_source
from market_pdf_insights.ingestion import RawSourceItem, normalize_source_item
from market_pdf_insights.llm_client import LLMConfigurationError


class FakeResponse:
    """Minimal Responses API response with output_text."""

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponsesResource:
    """Fake OpenAI responses resource returning queued outputs."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        if not self.outputs:
            raise AssertionError("No fake OpenAI outputs remain.")
        return FakeResponse(self.outputs.pop(0))


class FakeOpenAIClient:
    """Fake OpenAI SDK client exposing responses.create."""

    def __init__(self, outputs: list[str]) -> None:
        self.responses = FakeResponsesResource(outputs)


def test_mock_daily_brief_client_synthesizes_valid_brief() -> None:
    items = _source_items()
    client = MockDailyBriefLLMClient()

    brief = client.synthesize_brief(
        items,
        briefing_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 6, 30, tzinfo=UTC),
        watchlist_terms=("AUD", "DGS10"),
    )

    assert isinstance(brief, DailyMarketBrief)
    assert brief.briefing_date == date(2026, 5, 12)
    assert brief.generated_at.tzinfo is not None
    assert brief.sources
    assert brief.watchlist_impacts
    assert brief.verification_flags
    assert "not financial" in brief.disclaimer.lower()
    assert client.calls == [[item.deduplication_key for item in items]]


def test_build_source_citations_preserves_metadata_and_short_snippets() -> None:
    item = _source_items()[0]
    long_item = item.model_copy(update={"body": " ".join(["word"] * 120)})

    citations = build_source_citations([long_item, long_item])

    assert len(citations) == 1
    citation = citations[0]
    assert citation.source_id == "rba-rss"
    assert citation.source_name == "Reserve Bank of Australia RSS"
    assert citation.terms_url == "https://www.rba.gov.au/copyright/"
    assert len(citation.snippet.split()) <= 60
    assert len(citation.snippet) <= 280


def test_openai_daily_brief_client_retries_group_notes_and_returns_brief() -> None:
    item = _source_items()[0]
    citations = build_source_citations([item])
    group_notes = SourceGroupNotes(
        group_id="australian_market:rba-rss",
        source_id=item.source_id,
        source_name=item.source_name,
        category=item.category,
        item_count=1,
        factual_points=["RBA left the cash rate target unchanged."],
        commentary_points=["Rates sensitivity remains relevant."],
        market_themes=["Rates remain in focus."],
        macro_events=["RBA monetary policy decision."],
        asset_mentions=["AUD"],
        verification_flags=["Verify the cash rate decision against the RBA source."],
        citations=citations,
        confidence_score=0.8,
    )
    final_brief = MockDailyBriefLLMClient().synthesize_brief(
        [item],
        briefing_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 6, 30, tzinfo=UTC),
        watchlist_terms=("AUD",),
    )
    fake_client = FakeOpenAIClient(
        [
            "not json",
            group_notes.model_dump_json(),
            final_brief.model_dump_json(),
        ]
    )
    client = OpenAIDailyBriefClient(
        model="gpt-test",
        openai_client=fake_client,
        max_retries=1,
    )

    brief = client.synthesize_brief(
        [item],
        briefing_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 6, 30, tzinfo=UTC),
        watchlist_terms=("AUD",),
    )

    assert brief.title == "Daily Market Intelligence Brief - 2026-05-12"
    assert brief.sources[0].source_id == "rba-rss"
    assert len(fake_client.responses.calls) == 3
    assert fake_client.responses.calls[0]["text"] == {"format": {"type": "json_object"}}
    retry_messages = fake_client.responses.calls[1]["input"]
    assert "invalid JSON" in json.dumps(retry_messages)


def test_openai_daily_brief_client_requires_api_key_when_client_not_injected() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
            OpenAIDailyBriefClient()


def test_daily_brief_synthesis_requires_source_items() -> None:
    client = MockDailyBriefLLMClient()

    with pytest.raises(ValueError, match="At least one normalized source item"):
        client.synthesize_brief([], briefing_date=date(2026, 5, 12))


def test_daily_brief_prompts_include_required_guardrails() -> None:
    combined = (
        SOURCE_GROUP_NOTES_SYSTEM_PROMPT.lower()
        + "\n"
        + DAILY_BRIEF_SYNTHESIS_SYSTEM_PROMPT.lower()
    )

    for phrase in [
        "distinguish factual",
        "flag unsupported",
        "do not copy long source text",
        "yesterday_recap",
        "day_ahead",
        "australia",
        "global macro",
        "rates",
        "currencies",
        "commodities",
        "watchlist",
        "do not provide financial advice",
        "buy, sell, hold",
    ]:
        assert phrase in combined


def _source_items():
    rba = rba_source(enabled=True)
    fred = fred_source(enabled=True)
    return [
        normalize_source_item(
            RawSourceItem(
                source_id=rba.source_id,
                raw_id="rba-2026-05",
                title="RBA leaves cash rate target unchanged",
                summary="The Board left the cash rate target unchanged and noted inflation risk.",
                url="https://www.rba.gov.au/media-releases/2026/mr-26-12.html",
                published_at=datetime(2026, 5, 5, 4, 30, tzinfo=UTC),
                fetched_at=datetime(2026, 5, 12, 6, 0, tzinfo=UTC),
                tickers=("AUD",),
            ),
            rba,
        ),
        normalize_source_item(
            RawSourceItem(
                source_id=fred.source_id,
                raw_id="DGS10:2026-05-01",
                title="US 10-year Treasury yield rises to 4.33",
                summary="FRED DGS10 observation rose to 4.33, keeping rates in focus.",
                url="https://fred.stlouisfed.org/series/DGS10",
                published_at=datetime(2026, 5, 1, tzinfo=UTC),
                fetched_at=datetime(2026, 5, 12, 6, 1, tzinfo=UTC),
                tickers=("DGS10", "USD"),
            ),
            fred,
        ),
    ]
