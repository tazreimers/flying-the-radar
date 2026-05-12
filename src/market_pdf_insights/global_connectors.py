"""Global macro and news connectors for market-intelligence ingestion."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from market_pdf_insights.ingestion import HttpGet, JsonAPIConnector, RawSourceItem, parse_datetime
from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError
from market_pdf_insights.source_registry import (
    SourceAuthType,
    SourceCapability,
    SourceCategory,
    SourceCredentialPolicy,
    SourceDefinition,
    SourceTerms,
)

FRED_API_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{series_id}"
FRED_API_DOCS_URL = "https://fred.stlouisfed.org/docs/api/fred/series_observations.html"
FRED_TERMS_URL = "https://fred.stlouisfed.org/docs/api/terms_of_use.html"

WORLD_BANK_API_BASE_URL = "https://api.worldbank.org/v2"
WORLD_BANK_API_DOCS_URL = (
    "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392"
)
WORLD_BANK_TERMS_URL = (
    "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets"
)

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_DOC_API_DOCS_URL = "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/"

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
NEWSAPI_DOCS_URL = "https://newsapi.org/docs/endpoints/everything"
NEWSAPI_TERMS_URL = "https://newsapi.org/terms"

IMF_API_DOCS_URL = "https://data.imf.org/en/Resource-Pages/IMF-API"
OECD_API_DOCS_URL = "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html"
OECD_BEST_PRACTICES_URL = (
    "https://www.oecd.org/en/data/insights/data-explainers/2024/11/"
    "Api-best-practices-and-recommendations.html"
)

BLOOMBERG_DATA_LICENSE_URL = (
    "https://professional.bloomberg.com/products/data/data-management/data-license/"
)
REUTERS_CONNECT_URL = "https://www.reutersconnect.com/"


class NewsSort(StrEnum):
    """Supported news sort presets."""

    PUBLISHED_AT = "publishedAt"
    RELEVANCY = "relevancy"
    POPULARITY = "popularity"


class FREDSeriesConfig(BaseModel):
    """Configuration for one FRED macro series."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    series_id: str = Field(min_length=1)
    label: str | None = None
    units: str | None = None
    observation_start: date | None = None
    observation_end: date | None = None
    limit: int = Field(default=100, ge=1, le=100000)


class WorldBankIndicatorConfig(BaseModel):
    """Configuration for one World Bank indicator query."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    indicator: str = Field(min_length=1)
    country: str = Field(default="all", min_length=1)
    label: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    per_page: int = Field(default=100, ge=1, le=20000)


class GlobalNewsSearchConfig(BaseModel):
    """Configuration for GDELT and NewsAPI news search."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str | None = None
    watchlist_terms: tuple[str, ...] = ()
    language: str = "en"
    from_datetime: datetime | None = None
    to_datetime: datetime | None = None
    max_records: int = Field(default=50, ge=1, le=250)
    sort: NewsSort = NewsSort.PUBLISHED_AT

    def resolved_query(self) -> str:
        """Return an explicit query or OR-joined watchlist terms."""

        if self.query:
            return self.query
        if self.watchlist_terms:
            return "(" + " OR ".join(self.watchlist_terms) + ")"
        raise SourcePolicyError("A news query or at least one watchlist term is required.")


class GlobalMacroNewsConfig(BaseModel):
    """Configuration surface for global macro/news ingestion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fred_api_key: str | None = None
    newsapi_key: str | None = None
    fred_series: tuple[FREDSeriesConfig, ...] = ()
    world_bank_indicators: tuple[WorldBankIndicatorConfig, ...] = ()
    news_search: GlobalNewsSearchConfig = Field(default_factory=GlobalNewsSearchConfig)
    regions: tuple[str, ...] = ()

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        **overrides: Any,
    ) -> GlobalMacroNewsConfig:
        """Build config from environment variables without hardcoding credentials."""

        env = os.environ if environ is None else environ
        return cls(
            fred_api_key=env.get("FRED_API_KEY"),
            newsapi_key=env.get("NEWSAPI_KEY"),
            **overrides,
        )


class LicensedSourceInstructions(BaseModel):
    """Instructions for licensed sources and broad APIs not yet wired."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    permitted_paths: tuple[str, ...]


class FREDAPIConnector(JsonAPIConnector):
    """Connector for FRED series observations."""

    def __init__(
        self,
        *,
        series: tuple[FREDSeriesConfig, ...],
        api_key: str | None = None,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        if not series:
            raise SourcePolicyError("FREDAPIConnector requires at least one series config.")
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise SourcePolicyError(
                "FREDAPIConnector requires FRED_API_KEY. Set the environment variable "
                "or pass api_key explicitly; API keys must not be hardcoded."
            )
        self.series = series
        super().__init__(
            source or fred_source(enabled=True),
            endpoint_url=FRED_API_BASE_URL,
            http_get=http_get,
            **kwargs,
        )

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        items: list[RawSourceItem] = []
        for series_config in self.series:
            payload = self.http_get(_fred_observations_url(series_config, self.api_key))
            data = _expect_mapping(payload)
            for observation in data.get("observations", []):
                if not isinstance(observation, dict):
                    continue
                item = _fred_observation_to_item(observation, series_config, self.source)
                if _published_since(item.published_at, since):
                    items.append(item)
        return items


class WorldBankIndicatorConnector(JsonAPIConnector):
    """Connector for World Bank V2 indicator responses."""

    def __init__(
        self,
        *,
        indicators: tuple[WorldBankIndicatorConfig, ...],
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        if not indicators:
            raise SourcePolicyError(
                "WorldBankIndicatorConnector requires at least one indicator config."
            )
        self.indicators = indicators
        super().__init__(
            source or world_bank_source(enabled=True),
            endpoint_url=WORLD_BANK_API_BASE_URL,
            http_get=http_get,
            **kwargs,
        )

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        items: list[RawSourceItem] = []
        for indicator_config in self.indicators:
            payload = self.http_get(_world_bank_indicator_url(indicator_config))
            for record in _world_bank_records(payload):
                item = _world_bank_record_to_item(record, indicator_config, self.source)
                if _published_since(item.published_at, since):
                    items.append(item)
        return items


class GDELTDocConnector(JsonAPIConnector):
    """Connector for GDELT DOC 2.0 ArticleList JSON responses."""

    def __init__(
        self,
        *,
        search: GlobalNewsSearchConfig,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        self.search = search
        super().__init__(
            source or gdelt_source(enabled=True),
            endpoint_url=_gdelt_doc_url(search),
            http_get=http_get,
            **kwargs,
        )

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        data = _expect_mapping(self.http_get(self.endpoint_url))
        items: list[RawSourceItem] = []
        for article in data.get("articles", []):
            if not isinstance(article, dict):
                continue
            item = _gdelt_article_to_item(article, self.source, self.search.watchlist_terms)
            if _published_since(item.published_at, since):
                items.append(item)
        return items


class NewsAPIConnector(JsonAPIConnector):
    """Connector for NewsAPI Everything responses."""

    def __init__(
        self,
        *,
        search: GlobalNewsSearchConfig,
        api_key: str | None = None,
        source: SourceDefinition | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key or os.getenv("NEWSAPI_KEY")
        if not self.api_key:
            raise SourcePolicyError(
                "NewsAPIConnector requires NEWSAPI_KEY. Set the environment variable "
                "or pass api_key explicitly; API keys must not be hardcoded."
            )
        self.search = search
        super().__init__(
            source or newsapi_source(enabled=True),
            endpoint_url=_newsapi_url(search, self.api_key),
            http_get=http_get,
            **kwargs,
        )

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        data = _expect_mapping(self.http_get(self.endpoint_url))
        if data.get("status") == "error":
            raise SourcePolicyError(str(data.get("message") or "NewsAPI returned an error."))
        items: list[RawSourceItem] = []
        for article in data.get("articles", []):
            if not isinstance(article, dict):
                continue
            item = _newsapi_article_to_item(article, self.source, self.search.watchlist_terms)
            if _published_since(item.published_at, since):
                items.append(item)
        return items


class IMFConnector:
    """Disabled stub until an explicit IMF SDMX query scope is configured."""

    instructions = LicensedSourceInstructions(
        source_id="imf-api",
        display_name="IMF Data API",
        reason=(
            "IMF ingestion is disabled in this step because IMF SDMX scope depends on "
            "dataset, dimensions, version, and time-period choices."
        ),
        permitted_paths=(
            "explicit IMF SDMX 2.1 or 3.0 query URL reviewed for the brief",
            "DataMapper API query for a known indicator/country set",
            "fixture or user-provided export loaded through the local fixture connector",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(self.instructions.reason)


class OECDConnector:
    """Disabled stub until an explicit OECD SDMX query scope is configured."""

    instructions = LicensedSourceInstructions(
        source_id="oecd-api",
        display_name="OECD Data Explorer API",
        reason=(
            "OECD ingestion is disabled in this step because each Data Explorer query "
            "must be scoped to a dataset, dimension selection, and rate-limit budget."
        ),
        permitted_paths=(
            "specific OECD Data Explorer API URL generated by the Developer API builder",
            "fixture or user-provided export loaded through the local fixture connector",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(self.instructions.reason)


class BloombergConnector:
    """Disabled licensed-source placeholder for Bloomberg."""

    instructions = LicensedSourceInstructions(
        source_id="bloomberg",
        display_name="Bloomberg",
        reason="Bloomberg ingestion requires licensed Bloomberg Data License access.",
        permitted_paths=(
            "Bloomberg Data License REST API, SFTP, or cloud delivery",
            "user-provided subscription export permitted by the applicable licence",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(f"{self.instructions.reason} Do not scrape Bloomberg pages.")


class ReutersConnector:
    """Disabled licensed-source placeholder for Reuters."""

    instructions = LicensedSourceInstructions(
        source_id="reuters",
        display_name="Reuters",
        reason="Reuters ingestion requires licensed Reuters Connect or equivalent access.",
        permitted_paths=(
            "Reuters Connect licensed content subscription/export",
            "licensed API/feed whose terms permit the intended use",
        ),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SourcePolicyError(f"{self.instructions.reason} Do not scrape Reuters pages.")


def fred_source(*, enabled: bool = False) -> SourceDefinition:
    """Return FRED API source metadata."""

    return SourceDefinition(
        source_id="fred-api",
        display_name="FRED API",
        category=SourceCategory.GLOBAL_MACRO,
        homepage_url="https://fred.stlouisfed.org/",
        api_docs_url=FRED_API_DOCS_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="fred_series_observations_json",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "FRED API requires a registered API key. Display the FRED API notice "
                "and preserve proprietary notices and attribution."
            ),
            terms_url=FRED_TERMS_URL,
            rate_limit_notes="Use narrow series lists and cache responses.",
        ),
        credentials=SourceCredentialPolicy(
            auth_type=SourceAuthType.API_KEY,
            required_env_vars=("FRED_API_KEY",),
            credential_notes="Read from environment or runtime configuration only.",
        ),
        metadata={"base_url": FRED_API_BASE_URL},
    )


def world_bank_source(*, enabled: bool = False) -> SourceDefinition:
    """Return World Bank Indicators API source metadata."""

    return SourceDefinition(
        source_id="world-bank-api",
        display_name="World Bank Indicators API",
        category=SourceCategory.GLOBAL_MACRO,
        homepage_url="https://data.worldbank.org/",
        api_docs_url=WORLD_BANK_API_DOCS_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="world_bank_v2_indicator_json",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "World Bank dataset terms generally permit API use with attribution, "
                "subject to dataset/indicator metadata and third-party restrictions."
            ),
            terms_url=WORLD_BANK_TERMS_URL,
            rate_limit_notes="Use narrow country/indicator queries and cache responses.",
            redistribution_allowed=True,
        ),
        metadata={"base_url": WORLD_BANK_API_BASE_URL},
    )


def gdelt_source(*, enabled: bool = False) -> SourceDefinition:
    """Return GDELT DOC API source metadata."""

    return SourceDefinition(
        source_id="gdelt-api",
        display_name="GDELT DOC 2.0 API",
        category=SourceCategory.NEWS_COMMENTARY,
        homepage_url="https://www.gdeltproject.org/",
        api_docs_url=GDELT_DOC_API_DOCS_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="gdelt_doc_2_article_list_json",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "GDELT DOC API returns article metadata and links. Preserve source URLs "
                "and do not republish third-party article text."
            ),
            rate_limit_notes="Use narrow queries, modest maxrecords, and cache responses.",
        ),
        metadata={"base_url": GDELT_DOC_API_URL},
    )


def newsapi_source(*, enabled: bool = False) -> SourceDefinition:
    """Return NewsAPI source metadata."""

    return SourceDefinition(
        source_id="newsapi",
        display_name="NewsAPI",
        category=SourceCategory.NEWS_COMMENTARY,
        homepage_url="https://newsapi.org/",
        api_docs_url=NEWSAPI_DOCS_URL,
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="newsapi_everything_json",
            automation_allowed=True,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=(
                "Credentialed NewsAPI access. Respect plan limits and do not reproduce "
                "or republish copyrighted material beyond the licence."
            ),
            terms_url=NEWSAPI_TERMS_URL,
            rate_limit_notes="Respect plan request limits and environment restrictions.",
        ),
        credentials=SourceCredentialPolicy(
            auth_type=SourceAuthType.API_KEY,
            required_env_vars=("NEWSAPI_KEY",),
            credential_notes="Read from environment or runtime configuration only.",
        ),
        metadata={"base_url": NEWSAPI_EVERYTHING_URL},
    )


def imf_disabled_source() -> SourceDefinition:
    """Return disabled IMF source metadata."""

    return _disabled_global_source(
        source_id="imf-api",
        display_name="IMF Data API",
        homepage_url="https://www.imf.org/en/Data",
        api_docs_url=IMF_API_DOCS_URL,
        terms_notes=IMFConnector.instructions.reason,
    )


def oecd_disabled_source() -> SourceDefinition:
    """Return disabled OECD source metadata."""

    return _disabled_global_source(
        source_id="oecd-api",
        display_name="OECD Data Explorer API",
        homepage_url="https://data-explorer.oecd.org/",
        api_docs_url=OECD_API_DOCS_URL,
        terms_notes=OECDConnector.instructions.reason,
        rate_limit_notes=(
            "OECD API users should respect rate limiting and efficient-query guidance."
        ),
    )


def bloomberg_disabled_source() -> SourceDefinition:
    """Return disabled Bloomberg metadata."""

    return _disabled_news_source(
        source_id="bloomberg",
        display_name="Bloomberg",
        homepage_url=BLOOMBERG_DATA_LICENSE_URL,
        terms_notes=BloombergConnector.instructions.reason,
    )


def reuters_disabled_source() -> SourceDefinition:
    """Return disabled Reuters metadata."""

    return _disabled_news_source(
        source_id="reuters",
        display_name="Reuters",
        homepage_url=REUTERS_CONNECT_URL,
        terms_notes=ReutersConnector.instructions.reason,
    )


def _fred_observations_url(config: FREDSeriesConfig, api_key: str) -> str:
    params: dict[str, str | int] = {
        "series_id": config.series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": config.limit,
    }
    if config.units:
        params["units"] = config.units
    if config.observation_start:
        params["observation_start"] = config.observation_start.isoformat()
    if config.observation_end:
        params["observation_end"] = config.observation_end.isoformat()
    return f"{FRED_API_BASE_URL}/series/observations?{urlencode(params)}"


def _world_bank_indicator_url(config: WorldBankIndicatorConfig) -> str:
    params: dict[str, str | int] = {"format": "json", "per_page": config.per_page}
    if config.start_year is not None and config.end_year is not None:
        params["date"] = f"{config.start_year}:{config.end_year}"
    elif config.start_year is not None:
        params["date"] = str(config.start_year)
    elif config.end_year is not None:
        params["date"] = str(config.end_year)
    return (
        f"{WORLD_BANK_API_BASE_URL}/country/{config.country}/indicator/{config.indicator}"
        f"?{urlencode(params)}"
    )


def _gdelt_doc_url(search: GlobalNewsSearchConfig) -> str:
    params: dict[str, str | int] = {
        "query": search.resolved_query(),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": search.max_records,
        "sort": "DateDesc",
    }
    if search.from_datetime:
        params["startdatetime"] = _gdelt_datetime(search.from_datetime)
    if search.to_datetime:
        params["enddatetime"] = _gdelt_datetime(search.to_datetime)
    return f"{GDELT_DOC_API_URL}?{urlencode(params)}"


def _newsapi_url(search: GlobalNewsSearchConfig, api_key: str) -> str:
    params: dict[str, str | int] = {
        "q": search.resolved_query(),
        "apiKey": api_key,
        "language": search.language,
        "sortBy": search.sort.value,
        "pageSize": min(search.max_records, 100),
    }
    if search.from_datetime:
        params["from"] = search.from_datetime.isoformat()
    if search.to_datetime:
        params["to"] = search.to_datetime.isoformat()
    return f"{NEWSAPI_EVERYTHING_URL}?{urlencode(params)}"


def _fred_observation_to_item(
    observation: dict[str, Any],
    config: FREDSeriesConfig,
    source: SourceDefinition,
) -> RawSourceItem:
    observation_date = _period_to_datetime(observation.get("date"))
    series_label = config.label or config.series_id
    value = observation.get("value")
    title = f"{series_label}: {value} on {observation.get('date')}"
    return RawSourceItem(
        source_id=source.source_id,
        raw_id=f"{config.series_id}:{observation.get('date')}",
        title=title,
        summary=(
            f"FRED series {config.series_id} observation for {observation.get('date')}: "
            f"{value}."
        ),
        url=FRED_SERIES_URL.format(series_id=config.series_id),
        published_at=observation_date,
        tickers=_assets_from_text(series_label),
        payload={"series_id": config.series_id, "observation": observation},
    )


def _world_bank_record_to_item(
    record: dict[str, Any],
    config: WorldBankIndicatorConfig,
    source: SourceDefinition,
) -> RawSourceItem:
    indicator = record.get("indicator") if isinstance(record.get("indicator"), dict) else {}
    country = record.get("country") if isinstance(record.get("country"), dict) else {}
    indicator_label = config.label or str(indicator.get("value") or config.indicator)
    country_label = str(country.get("value") or record.get("countryiso3code") or config.country)
    period = str(record.get("date") or "")
    value = record.get("value")
    title = f"{country_label} {indicator_label}: {value} ({period})"
    return RawSourceItem(
        source_id=source.source_id,
        raw_id=f"{config.country}:{config.indicator}:{period}",
        title=title,
        summary=f"World Bank indicator {config.indicator} for {country_label}: {value}.",
        url=(
            "https://data.worldbank.org/indicator/"
            f"{config.indicator}?locations={config.country.upper()}"
        ),
        published_at=_period_to_datetime(period),
        tickers=_assets_from_text(" ".join([indicator_label, country_label])),
        payload=record,
    )


def _gdelt_article_to_item(
    article: dict[str, Any],
    source: SourceDefinition,
    watchlist_terms: tuple[str, ...],
) -> RawSourceItem:
    title = str(article.get("title") or "Untitled GDELT article")
    domain = article.get("domain")
    country = article.get("sourcecountry")
    seen_at = _parse_gdelt_datetime(article.get("seendate"))
    summary = " | ".join(
        part
        for part in [
            f"Domain: {domain}" if domain else "",
            f"Country: {country}" if country else "",
        ]
        if part
    )
    return RawSourceItem(
        source_id=source.source_id,
        raw_id=str(article.get("url") or title),
        title=title,
        summary=summary or None,
        url=str(article.get("url")) if article.get("url") else None,
        published_at=seen_at,
        tickers=_assets_from_text(" ".join([title, *watchlist_terms])),
        payload=article,
    )


def _newsapi_article_to_item(
    article: dict[str, Any],
    source: SourceDefinition,
    watchlist_terms: tuple[str, ...],
) -> RawSourceItem:
    title = str(article.get("title") or "Untitled NewsAPI article")
    article_source = article.get("source") if isinstance(article.get("source"), dict) else {}
    source_name = article_source.get("name")
    description = article.get("description")
    content = article.get("content")
    summary = " ".join(str(part) for part in [description, content] if part)
    return RawSourceItem(
        source_id=source.source_id,
        raw_id=str(article.get("url") or title),
        title=title,
        summary=summary or None,
        url=str(article.get("url")) if article.get("url") else None,
        published_at=parse_datetime(article.get("publishedAt")),
        tickers=_assets_from_text(" ".join([title, summary, *watchlist_terms])),
        payload={"provider_source": source_name, "article": article},
    )


def _world_bank_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list):
        return [record for record in payload[1] if isinstance(record, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [record for record in payload["items"] if isinstance(record, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [record for record in payload["data"] if isinstance(record, dict)]
    return []


def _expect_mapping(payload: str | bytes | dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"items": payload}
    import json

    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object response")
    return data


def _disabled_global_source(
    *,
    source_id: str,
    display_name: str,
    homepage_url: str,
    api_docs_url: str,
    terms_notes: str,
    rate_limit_notes: str = "Requires explicit query design and source review.",
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        category=SourceCategory.GLOBAL_MACRO,
        homepage_url=homepage_url,
        api_docs_url=api_docs_url,
        capability=SourceCapability(
            access_method=SourceAccessMethod.DISABLED,
            fetch_strategy="disabled_until_explicit_query_scope",
            automation_allowed=False,
            enabled=False,
        ),
        terms=SourceTerms(
            terms_notes=terms_notes,
            rate_limit_notes=rate_limit_notes,
        ),
    )


def _disabled_news_source(
    *,
    source_id: str,
    display_name: str,
    homepage_url: str,
    terms_notes: str,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        category=SourceCategory.NEWS_COMMENTARY,
        homepage_url=homepage_url,
        capability=SourceCapability(
            access_method=SourceAccessMethod.DISABLED,
            fetch_strategy="disabled_until_licensed",
            automation_allowed=False,
            enabled=False,
        ),
        terms=SourceTerms(
            terms_notes=f"{terms_notes} Do not scrape pages.",
            rate_limit_notes="Requires licence or documented user-export review.",
        ),
    )


def _period_to_datetime(value: Any) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str) and len(value) == 4 and value.isdigit():
        return datetime(int(value), 1, 1, tzinfo=UTC)
    return None


def _parse_gdelt_datetime(value: Any) -> datetime | None:
    if isinstance(value, str) and len(value) == 14 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return parse_datetime(value)


def _gdelt_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _published_since(published_at: datetime | None, since: datetime | None) -> bool:
    if since is None or published_at is None:
        return True
    comparison = since if since.tzinfo else since.replace(tzinfo=UTC)
    return published_at >= comparison.astimezone(UTC)


def _assets_from_text(text: str) -> tuple[str, ...]:
    candidates = [candidate.strip().upper() for candidate in text.replace(",", " ").split()]
    return tuple(
        dict.fromkeys(
            candidate
            for candidate in candidates
            if 2 <= len(candidate) <= 6 and candidate.replace(".", "").isalpha()
        )
    )
