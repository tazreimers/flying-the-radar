from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest

from market_pdf_insights.daily_brief_schema import DailyMarketBrief
from market_pdf_insights.daily_brief_synthesis import MockBriefLLMClient
from market_pdf_insights.daily_brief_rendering import save_daily_brief_outputs
from market_pdf_insights.ingestion import (
    IngestionRunner,
    JsonAPIConnector,
    MockConnector,
    RSSFeedConnector,
    RawSourceItem,
)
from market_pdf_insights.source_policy import SourceAccessMethod
from market_pdf_insights.source_registry import (
    SourceCapability,
    SourceCategory,
    SourceDefinition,
    SourceTerms,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mvp"


def test_mvp_path_from_fixture_sources_to_saved_daily_brief(tmp_path) -> None:
    connectors = [
        RSSFeedConnector(
            _source(
                "mvp-market-rss",
                SourceAccessMethod.RSS,
                SourceCategory.AUSTRALIAN_MARKET,
            ),
            feed_url="https://example.test/market/rss.xml",
            http_get=lambda _: (FIXTURE_DIR / "market-rss.xml").read_text(encoding="utf-8"),
        ),
        JsonAPIConnector(
            _source("mvp-json-api", SourceAccessMethod.API, SourceCategory.AUSTRALIAN_MARKET),
            endpoint_url="https://example.test/market/items.json",
            http_get=lambda _: _json_fixture("json-api-items.json"),
        ),
        JsonAPIConnector(
            _source("mvp-macro-api", SourceAccessMethod.API, SourceCategory.GLOBAL_MACRO),
            endpoint_url="https://example.test/macro/items.json",
            http_get=lambda _: _json_fixture("macro-data.json"),
        ),
        JsonAPIConnector(
            _source("mvp-news-api", SourceAccessMethod.API, SourceCategory.NEWS_COMMENTARY),
            endpoint_url="https://example.test/news/items.json",
            http_get=lambda _: _json_fixture("news-items.json"),
        ),
    ]

    ingestion_run = IngestionRunner(connectors).run(
        since=datetime(2026, 5, 12, tzinfo=UTC)
    )
    brief = MockBriefLLMClient().synthesize_brief(
        ingestion_run.items,
        briefing_date=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 6, 30, tzinfo=UTC),
        watchlist_terms=("BHP", "AUD", "DGS10", "USD"),
    )
    saved = save_daily_brief_outputs(brief, tmp_path)

    assert ingestion_run.total_fetched == 5
    assert ingestion_run.total_new == 4
    assert {item.source_id for item in ingestion_run.items} == {
        "mvp-market-rss",
        "mvp-json-api",
        "mvp-macro-api",
        "mvp-news-api",
    }
    assert brief.watchlist_impacts
    assert brief.verification_flags
    assert DailyMarketBrief.model_validate_json(saved["json"].read_text(encoding="utf-8"))
    assert "## Executive Summary" in saved["markdown"].read_text(encoding="utf-8")
    assert "<h2>Sources</h2>" in saved["html"].read_text(encoding="utf-8")
    assert "EXECUTIVE SUMMARY" in saved["text"].read_text(encoding="utf-8")


def test_mock_connector_normalizes_configured_raw_items_without_network() -> None:
    source = _source(
        "mock-manual",
        SourceAccessMethod.MANUAL_ENTRY,
        SourceCategory.USER_PROVIDED,
        automation_allowed=False,
    )
    connector = MockConnector(
        source,
        raw_items=[
            RawSourceItem(
                source_id=source.source_id,
                raw_id="mock-1",
                title="Manual market note",
                summary="AUD and BHP stayed on the watchlist.",
                url="https://example.test/manual",
                published_at=datetime(2026, 5, 12, tzinfo=UTC),
                tickers=("AUD", "BHP"),
            )
        ],
    )

    result = connector.fetch_since()

    assert connector.fetch_count == 1
    assert len(result.normalized_items) == 1
    assert result.normalized_items[0].source_id == "mock-manual"
    assert result.normalized_items[0].tickers == ("AUD", "BHP")


def test_default_network_fetch_is_blocked_by_test_guard() -> None:
    connector = RSSFeedConnector(
        _source("blocked-rss", SourceAccessMethod.RSS, SourceCategory.NEWS_COMMENTARY),
        feed_url="https://example.test/should-not-fetch.xml",
    )

    with pytest.raises(AssertionError, match="Live network access is disabled"):
        connector.fetch_since()


def _json_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _source(
    source_id: str,
    access_method: SourceAccessMethod,
    category: SourceCategory,
    *,
    automation_allowed: bool = True,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=source_id.replace("-", " ").title(),
        category=category,
        homepage_url="https://example.test/",
        capability=SourceCapability(
            access_method=access_method,
            fetch_strategy="fixture",
            automation_allowed=automation_allowed,
            enabled=True,
        ),
        terms=SourceTerms(
            terms_notes="Synthetic fixture terms. No copyrighted source text.",
            terms_url="https://example.test/terms",
            rate_limit_notes="No live network calls in tests.",
        ),
    )
