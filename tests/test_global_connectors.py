from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from market_pdf_insights.global_connectors import (
    BloombergConnector,
    FREDAPIConnector,
    FREDSeriesConfig,
    GDELTDocConnector,
    GlobalMacroNewsConfig,
    GlobalNewsSearchConfig,
    IMFConnector,
    NewsAPIConnector,
    OECDConnector,
    ReutersConnector,
    WorldBankIndicatorConfig,
    WorldBankIndicatorConnector,
    bloomberg_disabled_source,
    fred_source,
    gdelt_source,
    imf_disabled_source,
    newsapi_source,
    oecd_disabled_source,
    reuters_disabled_source,
    world_bank_source,
)
from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "global"


def test_fred_connector_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(SourcePolicyError, match="requires FRED_API_KEY"):
        FREDAPIConnector(series=(FREDSeriesConfig(series_id="DGS10"),))


def test_fred_connector_ingests_macro_fixture() -> None:
    payload = json.loads((FIXTURE_DIR / "fred-observations.json").read_text(encoding="utf-8"))
    connector = FREDAPIConnector(
        series=(FREDSeriesConfig(series_id="DGS10", label="US 10 Year Treasury Yield"),),
        api_key="fixture-key",
        http_get=lambda _: payload,
    )

    result = connector.fetch_since(datetime(2026, 4, 15, tzinfo=UTC))

    assert result.source_id == "fred-api"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "US 10 Year Treasury Yield: 4.33 on 2026-05-01"
    assert item.url == "https://fred.stlouisfed.org/series/DGS10"
    assert item.attribution.terms_url == "https://fred.stlouisfed.org/docs/api/terms_of_use.html"


def test_world_bank_connector_ingests_indicator_fixture() -> None:
    payload = json.loads(
        (FIXTURE_DIR / "world-bank-indicator.json").read_text(encoding="utf-8")
    )
    connector = WorldBankIndicatorConnector(
        indicators=(
            WorldBankIndicatorConfig(
                country="AUS",
                indicator="NY.GDP.MKTP.KD.ZG",
                start_year=2025,
                end_year=2025,
            ),
        ),
        http_get=lambda _: payload,
    )

    result = connector.fetch_since(datetime(2025, 1, 1, tzinfo=UTC))

    assert result.source_id == "world-bank-api"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "Australia GDP growth (annual %): 1.8 (2025)"
    assert item.terms.redistribution_allowed
    assert item.attribution.terms_url.endswith("terms-of-use-for-datasets")


def test_gdelt_connector_ingests_news_fixture() -> None:
    payload = json.loads((FIXTURE_DIR / "gdelt-doc.json").read_text(encoding="utf-8"))
    connector = GDELTDocConnector(
        search=GlobalNewsSearchConfig(watchlist_terms=("Fed", "China")),
        http_get=lambda _: payload,
    )

    result = connector.fetch_since(datetime(2026, 5, 12, tzinfo=UTC))

    assert result.source_id == "gdelt-api"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "Global markets steady before Fed decision"
    assert item.url == "https://example.test/global-markets-fed"
    assert item.published_at == datetime(2026, 5, 12, 8, 30, tzinfo=UTC)
    assert "Domain: example.test" in item.body


def test_newsapi_connector_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)

    with pytest.raises(SourcePolicyError, match="requires NEWSAPI_KEY"):
        NewsAPIConnector(search=GlobalNewsSearchConfig(query="markets"))


def test_newsapi_connector_ingests_fixture() -> None:
    payload = json.loads((FIXTURE_DIR / "newsapi-everything.json").read_text(encoding="utf-8"))
    connector = NewsAPIConnector(
        search=GlobalNewsSearchConfig(query="dollar OR oil", watchlist_terms=("USD", "OIL")),
        api_key="fixture-key",
        http_get=lambda _: payload,
    )

    result = connector.fetch_since(datetime(2026, 5, 12, tzinfo=UTC))

    assert result.source_id == "newsapi"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "US dollar slips as traders assess rate outlook"
    assert item.attribution.source_name == "NewsAPI"
    assert item.terms.terms_url == "https://newsapi.org/terms"
    assert "US dollar eased" in item.body


def test_newsapi_error_response_is_helpful() -> None:
    connector = NewsAPIConnector(
        search=GlobalNewsSearchConfig(query="markets"),
        api_key="fixture-key",
        http_get=lambda _: {"status": "error", "message": "rateLimited"},
    )

    with pytest.raises(SourcePolicyError, match="rateLimited"):
        connector.fetch_since()


def test_config_loads_optional_credentials_from_environment() -> None:
    config = GlobalMacroNewsConfig.from_env(
        {"FRED_API_KEY": "fred-key", "NEWSAPI_KEY": "news-key"},
        fred_series=(FREDSeriesConfig(series_id="DGS10"),),
        news_search=GlobalNewsSearchConfig(watchlist_terms=("rates", "dollar")),
        regions=("US", "AU"),
    )

    assert config.fred_api_key == "fred-key"
    assert config.newsapi_key == "news-key"
    assert config.news_search.resolved_query() == "(rates OR dollar)"
    assert config.regions == ("US", "AU")


def test_news_search_requires_query_or_watchlist() -> None:
    with pytest.raises(SourcePolicyError, match="watchlist term"):
        GlobalNewsSearchConfig().resolved_query()


def test_imf_and_oecd_connectors_are_scope_gated_stubs() -> None:
    with pytest.raises(SourcePolicyError, match="IMF ingestion is disabled"):
        IMFConnector()
    with pytest.raises(SourcePolicyError, match="OECD ingestion is disabled"):
        OECDConnector()


def test_bloomberg_and_reuters_are_licensed_disabled_placeholders() -> None:
    with pytest.raises(SourcePolicyError, match="Do not scrape Bloomberg"):
        BloombergConnector()
    with pytest.raises(SourcePolicyError, match="Do not scrape Reuters"):
        ReutersConnector()


def test_global_source_metadata_declares_terms_and_access() -> None:
    enabled_sources = [
        fred_source(enabled=True),
        world_bank_source(enabled=True),
        gdelt_source(enabled=True),
        newsapi_source(enabled=True),
    ]
    disabled_sources = [
        imf_disabled_source(),
        oecd_disabled_source(),
        bloomberg_disabled_source(),
        reuters_disabled_source(),
    ]

    for source in enabled_sources:
        assert source.enabled
        assert source.access_method == SourceAccessMethod.API
        assert source.terms.terms_notes

    for source in disabled_sources:
        assert not source.enabled
        assert source.access_method == SourceAccessMethod.DISABLED
        assert source.terms.terms_notes
