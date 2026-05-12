"""Australian public market-intelligence connectors."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from market_pdf_insights.ingestion import HttpGet, JsonAPIConnector, LocalFixtureConnector
from market_pdf_insights.ingestion import RSSFeedConnector
from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError
from market_pdf_insights.source_registry import (
    SourceCapability,
    SourceCategory,
    SourceDefinition,
    SourceTerms,
)

RBA_RSS_PAGE_URL = "https://www.rba.gov.au/updates/rss-feeds.html"
RBA_MEDIA_RELEASES_FEED_URL = "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"
RBA_EXCHANGE_RATES_FEED_URL = "https://www.rba.gov.au/rss/rss-cb-exchange-rates.xml"
RBA_COPYRIGHT_URL = "https://www.rba.gov.au/copyright/"

ABS_DATA_API_BASE_URL = "https://data.api.abs.gov.au/rest/"
ABS_DATA_API_DOCS_URL = (
    "https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/"
    "data-api-user-guide"
)
ABS_INDICATOR_API_DOCS_URL = (
    "https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/"
    "indicator-api"
)
ABS_COPYRIGHT_URL = "https://www.abs.gov.au/about/legislation-and-policy/copyright"

ASIC_MEDIA_RELEASES_URL = "https://www.asic.gov.au/newsroom/media-releases/"
ASIC_COPYRIGHT_URL = "https://asic.gov.au/copyright/"

ASX_COMPANY_NEWS_URL = (
    "https://www.asx.com.au/connectivity-and-data/information-services/company-news"
)
MARKET_INDEX_URL = "https://www.marketindex.com.au/"


class RBAFeedKind(StrEnum):
    """Supported official RBA RSS feed presets."""

    MEDIA_RELEASES = "media_releases"
    EXCHANGE_RATES = "exchange_rates"


class AustralianDisabledConnectorInstructions(BaseModel):
    """Instructions for sources that must stay disabled until licensed or exported."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    permitted_paths: tuple[str, ...]


class RBAFeedConnector(RSSFeedConnector):
    """Connector for official RBA RSS feeds."""

    def __init__(
        self,
        *,
        feed_kind: RBAFeedKind = RBAFeedKind.MEDIA_RELEASES,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        feed_url = _rba_feed_url(feed_kind)
        super().__init__(
            source or rba_source(enabled=True, feed_kind=feed_kind),
            feed_url=feed_url,
            http_get=http_get,
            **kwargs,
        )
        self.feed_kind = feed_kind


class ABSDataConnector(JsonAPIConnector):
    """Connector for configured ABS Data API or permitted release JSON responses."""

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        items_path: tuple[str, ...] = ("items",),
        **kwargs: Any,
    ) -> None:
        if endpoint_url is None:
            raise SourcePolicyError(
                "ABSDataConnector requires a concrete ABS Data API query endpoint. "
                "Use the ABS Data API base URL plus an explicit dataflow/datakey query."
            )
        super().__init__(
            source or abs_data_source(enabled=True),
            endpoint_url=endpoint_url,
            http_get=http_get,
            items_path=items_path,
            **kwargs,
        )


class ABSLocalReleaseConnector(LocalFixtureConnector):
    """Load ABS release/news fixtures or user-provided exports."""

    def __init__(
        self,
        *,
        fixture_path: str | Path,
        source: SourceDefinition | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            source or abs_release_export_source(enabled=True),
            fixture_path=fixture_path,
            **kwargs,
        )


class ASICMediaReleasesConnector(JsonAPIConnector):
    """Connector for a permitted ASIC media-release feed or export endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        items_path: tuple[str, ...] = ("items",),
        **kwargs: Any,
    ) -> None:
        if endpoint_url is None:
            raise SourcePolicyError(
                "ASICMediaReleasesConnector requires an explicit permitted API, RSS-to-JSON "
                "feed, licensed feed, or documented export. Do not scrape ASIC pages."
            )
        super().__init__(
            source or asic_media_source(enabled=True),
            endpoint_url=endpoint_url,
            http_get=http_get,
            items_path=items_path,
            **kwargs,
        )


class ASXAnnouncementsConnector:
    """Disabled placeholder for ASX announcements."""

    instructions = AustralianDisabledConnectorInstructions(
        source_id="asx-announcements",
        display_name="ASX Announcements",
        reason=(
            "ASX announcement ingestion is disabled until an official permitted endpoint, "
            "licensed provider, or documented user-provided export is configured."
        ),
        permitted_paths=(
            "licensed ASX Information Services company-news product",
            "official endpoint with written permission",
            "documented user-provided export loaded through LocalFixtureConnector",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(
            f"{self.instructions.reason} Do not scrape ASX announcement pages."
        )


class MarketIndexConnector:
    """Disabled placeholder for Market Index."""

    instructions = AustralianDisabledConnectorInstructions(
        source_id="market-index",
        display_name="Market Index",
        reason=(
            "Market Index ingestion is disabled until a permitted API/feed, written "
            "permission, or licensed data path is configured."
        ),
        permitted_paths=(
            "licensed API or feed",
            "written permission for the intended automated access pattern",
            "documented user-provided export loaded through LocalFixtureConnector",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(
            f"{self.instructions.reason} Do not scrape Market Index pages."
        )


def rba_source(
    *,
    enabled: bool = False,
    feed_kind: RBAFeedKind = RBAFeedKind.MEDIA_RELEASES,
) -> SourceDefinition:
    """Return RBA RSS source metadata."""

    feed_url = _rba_feed_url(feed_kind)
    return SourceDefinition(
        source_id="rba-rss",
        display_name="Reserve Bank of Australia RSS",
        category=SourceCategory.AUSTRALIAN_MARKET,
        homepage_url=RBA_RSS_PAGE_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.RSS,
            fetch_strategy=f"official_rba_{feed_kind.value}_rss",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "Official RBA RSS material. Preserve attribution and comply with the "
                "RBA copyright/disclaimer notice, including special conditions for "
                "financial data."
            ),
            terms_url=RBA_COPYRIGHT_URL,
            rate_limit_notes="Use polite polling and cache responses.",
        ),
        metadata={"feed_url": feed_url, "feed_kind": feed_kind.value},
    )


def abs_data_source(*, enabled: bool = False) -> SourceDefinition:
    """Return ABS Data API source metadata."""

    return SourceDefinition(
        source_id="abs-api",
        display_name="Australian Bureau of Statistics Data API",
        category=SourceCategory.AUSTRALIAN_MARKET,
        homepage_url="https://www.abs.gov.au/",
        api_docs_url=ABS_DATA_API_DOCS_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="official_abs_data_api_json",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "Official ABS Data API. The Data API is freely accessible without an "
                "API key; preserve ABS attribution and source links."
            ),
            terms_url=ABS_COPYRIGHT_URL,
            rate_limit_notes="Use narrow queries and cache responses.",
        ),
        metadata={"base_url": ABS_DATA_API_BASE_URL, "format": "jsondata"},
    )


def abs_release_export_source(*, enabled: bool = False) -> SourceDefinition:
    """Return ABS release export source metadata for local fixtures or exports."""

    return SourceDefinition(
        source_id="abs-release-export",
        display_name="Australian Bureau of Statistics Release Export",
        category=SourceCategory.AUSTRALIAN_MARKET,
        homepage_url="https://www.abs.gov.au/release-calendar/latest-releases",
        capability=SourceCapability(
            access_method=SourceAccessMethod.USER_UPLOAD,
            fetch_strategy="abs_release_json_or_jsonl_export",
            automation_allowed=False,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes="User-provided ABS release fixture/export. Preserve ABS attribution.",
            terms_url=ABS_COPYRIGHT_URL,
            rate_limit_notes="Not an automated fetch source.",
        ),
    )


def asic_media_source(*, enabled: bool = False) -> SourceDefinition:
    """Return ASIC media-release metadata for a permitted endpoint/export."""

    return SourceDefinition(
        source_id="asic-media",
        display_name="ASIC Media Releases",
        category=SourceCategory.AUSTRALIAN_MARKET,
        homepage_url=ASIC_MEDIA_RELEASES_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="permitted_asic_media_feed_or_export",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "ASIC media-release ingestion requires a permitted API/feed, licensed "
                "feed, or documented export. Do not scrape ASIC pages."
            ),
            terms_url=ASIC_COPYRIGHT_URL,
            rate_limit_notes="Use only the explicitly configured permitted endpoint.",
        ),
    )


def asx_disabled_source() -> SourceDefinition:
    """Return disabled ASX announcements metadata."""

    return _disabled_source(
        source_id="asx-announcements",
        display_name="ASX Announcements",
        homepage_url=ASX_COMPANY_NEWS_URL,
        terms_notes=ASXAnnouncementsConnector.instructions.reason,
    )


def market_index_disabled_source() -> SourceDefinition:
    """Return disabled Market Index metadata."""

    return _disabled_source(
        source_id="market-index",
        display_name="Market Index",
        homepage_url=MARKET_INDEX_URL,
        terms_notes=MarketIndexConnector.instructions.reason,
    )


def _disabled_source(
    *,
    source_id: str,
    display_name: str,
    homepage_url: str,
    terms_notes: str,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        category=SourceCategory.AUSTRALIAN_MARKET,
        homepage_url=homepage_url,
        capability=SourceCapability(
            access_method=SourceAccessMethod.DISABLED,
            fetch_strategy="disabled_until_licensed_or_exported",
            automation_allowed=False,
            enabled=False,
        ),
        terms=SourceTerms(
            terms_notes=f"{terms_notes} Do not scrape pages.",
            rate_limit_notes="Requires licence, permission, or user-export review.",
        ),
    )


def _rba_feed_url(feed_kind: RBAFeedKind) -> str:
    if feed_kind == RBAFeedKind.MEDIA_RELEASES:
        return RBA_MEDIA_RELEASES_FEED_URL
    if feed_kind == RBAFeedKind.EXCHANGE_RATES:
        return RBA_EXCHANGE_RATES_FEED_URL
    raise ValueError(f"Unsupported RBA feed kind: {feed_kind}")
