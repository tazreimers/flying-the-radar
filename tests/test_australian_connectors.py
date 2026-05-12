from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from market_pdf_insights.australian_connectors import (
    ABSDataConnector,
    ABSLocalReleaseConnector,
    ASICMediaReleasesConnector,
    ASXAnnouncementsConnector,
    MarketIndexConnector,
    RBAFeedConnector,
    RBAFeedKind,
    abs_data_source,
    abs_release_export_source,
    asic_media_source,
    asx_disabled_source,
    market_index_disabled_source,
    rba_source,
)
from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError
from market_pdf_insights.source_registry import default_source_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "australia"


def test_rba_media_feed_connector_ingests_fixture() -> None:
    fixture = (FIXTURE_DIR / "rba-media-releases.xml").read_text(encoding="utf-8")
    connector = RBAFeedConnector(http_get=lambda _: fixture)

    result = connector.fetch_since(datetime(2026, 5, 1, tzinfo=UTC))

    assert result.source_id == "rba-rss"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "Statement by the Monetary Policy Board: Monetary Policy Decision"
    assert item.source_name == "Reserve Bank of Australia RSS"
    assert item.attribution.terms_url == "https://www.rba.gov.au/copyright/"
    assert item.metadata["payload"]["format"] == "rss"


def test_rba_exchange_rate_feed_kind_declares_source_metadata() -> None:
    source = rba_source(enabled=True, feed_kind=RBAFeedKind.EXCHANGE_RATES)

    assert source.enabled
    assert source.access_method == SourceAccessMethod.RSS
    assert source.metadata["feed_url"].endswith("rss-cb-exchange-rates.xml")
    assert "financial data" in source.terms.terms_notes.lower()


def test_abs_data_connector_ingests_fixture_json() -> None:
    payload = json.loads((FIXTURE_DIR / "abs-data-api.json").read_text(encoding="utf-8"))
    connector = ABSDataConnector(
        endpoint_url="https://data.api.abs.gov.au/rest/data/fixture?format=jsondata",
        http_get=lambda _: payload,
    )

    result = connector.fetch_since(datetime(2026, 4, 20, tzinfo=UTC))

    assert result.source_id == "abs-api"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "Consumer Price Index, Australia"
    assert item.tickers == ("AUD",)
    assert item.attribution.source_name == "Australian Bureau of Statistics Data API"


def test_abs_data_connector_requires_concrete_endpoint() -> None:
    with pytest.raises(SourcePolicyError, match="requires a concrete ABS Data API"):
        ABSDataConnector(endpoint_url=None)


def test_abs_local_release_connector_ingests_export_fixture() -> None:
    connector = ABSLocalReleaseConnector(
        fixture_path=FIXTURE_DIR / "abs-release-export.jsonl",
    )

    result = connector.fetch_since()

    assert len(result.normalized_items) == 1
    assert result.normalized_items[0].source_id == "abs-release-export"
    assert result.normalized_items[0].title.startswith("Media Release - Transport costs")
    assert result.normalized_items[0].terms.terms_url is not None


def test_asic_media_connector_requires_permitted_endpoint() -> None:
    with pytest.raises(SourcePolicyError, match="requires an explicit permitted"):
        ASICMediaReleasesConnector(endpoint_url=None)


def test_asic_media_connector_ingests_permitted_fixture_endpoint() -> None:
    payload = json.loads((FIXTURE_DIR / "asic-media.json").read_text(encoding="utf-8"))
    connector = ASICMediaReleasesConnector(
        endpoint_url="https://example.test/permitted-asic-media-export.json",
        http_get=lambda _: payload,
    )

    result = connector.fetch_since()

    assert result.source_id == "asic-media"
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "ASIC acts on market disclosure failures"
    assert item.tickers == ("ASX",)
    assert "do not scrape" in item.terms.terms_notes.lower()


def test_asx_and_market_index_connectors_are_disabled_stubs() -> None:
    with pytest.raises(SourcePolicyError, match="Do not scrape ASX"):
        ASXAnnouncementsConnector()
    with pytest.raises(SourcePolicyError, match="Do not scrape Market Index"):
        MarketIndexConnector()


def test_disabled_stub_sources_are_not_fetchable() -> None:
    asx = asx_disabled_source()
    market_index = market_index_disabled_source()

    assert not asx.enabled
    assert not market_index.enabled
    assert asx.access_method == SourceAccessMethod.DISABLED
    assert market_index.access_method == SourceAccessMethod.DISABLED
    assert "Do not scrape pages" in asx.terms.terms_notes
    assert "Do not scrape pages" in market_index.terms.terms_notes


def test_default_registry_keeps_asic_asx_and_market_index_disabled() -> None:
    registry = default_source_registry()

    for source_id in ("asic-media", "asx-announcements", "market-index"):
        source = registry.get(source_id)
        assert not source.enabled
        assert source.access_method == SourceAccessMethod.DISABLED


def test_australian_sources_include_compliance_terms() -> None:
    sources = [
        rba_source(),
        abs_data_source(),
        abs_release_export_source(),
        asic_media_source(),
    ]

    for source in sources:
        assert source.terms.terms_notes
        assert source.terms.terms_url
        assert source.category.value == "australian_market"
