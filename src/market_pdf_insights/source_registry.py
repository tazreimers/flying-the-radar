"""Source registry for public market-intelligence inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from market_pdf_insights.source_policy import (
    AUTOMATED_ACCESS_METHODS,
    SourceAccessMethod,
    SourceAttribution,
    SourcePolicyError,
)


class SourceCategory(StrEnum):
    """High-level market-intelligence source categories."""

    AUSTRALIAN_MARKET = "australian_market"
    GLOBAL_MACRO = "global_macro"
    NEWS_COMMENTARY = "news_commentary"
    CHARTS_WATCHLISTS = "charts_watchlists"
    USER_PROVIDED = "user_provided"


class SourceAuthType(StrEnum):
    """Credential strategy for a source."""

    NONE = "none"
    API_KEY = "api_key"
    TOKEN = "token"
    LICENSED_ACCOUNT = "licensed_account"
    USER_PROVIDED = "user_provided"


class SourceCapability(BaseModel):
    """Technical capabilities and fetch strategy for a source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    access_method: SourceAccessMethod
    fetch_strategy: str = Field(min_length=1)
    supports_historical_fetch: bool = False
    supports_incremental_fetch: bool = True
    automation_allowed: bool = False
    enabled: bool = False

    @model_validator(mode="after")
    def _validate_enabled_capability(self) -> SourceCapability:
        if self.enabled and self.access_method == SourceAccessMethod.DISABLED:
            raise ValueError("enabled capabilities cannot use disabled access_method")
        if (
            self.enabled
            and self.access_method in AUTOMATED_ACCESS_METHODS
            and not self.automation_allowed
        ):
            raise ValueError("enabled automated sources must set automation_allowed=True")
        return self


class SourceTerms(BaseModel):
    """Compliance metadata for source use."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    terms_notes: str = Field(min_length=1)
    terms_url: str | None = None
    rate_limit_notes: str | None = None
    redistribution_allowed: bool = False
    citation_required: bool = True


class SourceCredentialPolicy(BaseModel):
    """Credential requirements for a source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    auth_type: SourceAuthType = SourceAuthType.NONE
    required_env_vars: tuple[str, ...] = ()
    credential_notes: str | None = None

    @model_validator(mode="after")
    def _validate_required_env_vars(self) -> SourceCredentialPolicy:
        if self.auth_type != SourceAuthType.NONE and not self.required_env_vars:
            raise ValueError("credentialed sources must define required_env_vars")
        return self


class SourceDefinition(BaseModel):
    """Complete source definition used by the registry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: SourceCategory
    homepage_url: str | None = None
    api_docs_url: str | None = None
    capability: SourceCapability
    terms: SourceTerms
    credentials: SourceCredentialPolicy = Field(default_factory=SourceCredentialPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @property
    def enabled(self) -> bool:
        """Return whether this source is currently enabled."""

        return self.capability.enabled

    @property
    def access_method(self) -> SourceAccessMethod:
        """Return the source access method."""

        return self.capability.access_method

    @property
    def redistribution_allowed(self) -> bool:
        """Return whether source content can be redistributed."""

        return self.terms.redistribution_allowed

    def attribution(
        self,
        *,
        url: str | None = None,
        title: str | None = None,
        published_at: datetime | None = None,
        retrieved_at: datetime | None = None,
    ) -> SourceAttribution:
        """Create attribution metadata for a downstream item."""

        return SourceAttribution(
            source_id=self.source_id,
            source_name=self.display_name,
            url=url or self.homepage_url,
            title=title,
            published_at=published_at,
            retrieved_at=retrieved_at or datetime.now(UTC),
            terms_url=self.terms.terms_url,
            licence_notes=self.terms.terms_notes,
        )


class SourceFetchResult(BaseModel):
    """Metadata wrapper for a source fetch result."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    item_count: int = Field(ge=0)
    attribution: SourceAttribution
    terms: SourceTerms
    warnings: list[str] = Field(default_factory=list)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @model_validator(mode="after")
    def _validate_source_matches_attribution(self) -> SourceFetchResult:
        if self.source_id != self.attribution.source_id:
            raise ValueError("fetch result source_id must match attribution.source_id")
        return self


class SourceRegistry(BaseModel):
    """In-memory source registry with compliance checks."""

    model_config = ConfigDict(extra="forbid")

    sources: dict[str, SourceDefinition] = Field(default_factory=dict)

    @classmethod
    def from_definitions(cls, definitions: list[SourceDefinition]) -> SourceRegistry:
        """Build a registry from source definitions."""

        sources: dict[str, SourceDefinition] = {}
        for definition in definitions:
            if definition.source_id in sources:
                raise ValueError(f"Duplicate source id: {definition.source_id}")
            sources[definition.source_id] = definition
        return cls(sources=sources)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> SourceRegistry:
        """Build a registry from parsed YAML/TOML/env-style data."""

        definitions_data = config.get("sources")
        if not isinstance(definitions_data, list):
            raise ValueError("source registry config must contain a sources list")
        return cls.from_definitions(
            [SourceDefinition.model_validate(definition) for definition in definitions_data]
        )

    def get(self, source_id: str) -> SourceDefinition:
        """Return a source definition by id."""

        normalized_id = _normalize_source_id(source_id)
        try:
            return self.sources[normalized_id]
        except KeyError as exc:
            raise SourcePolicyError(f"Unknown source: {normalized_id}") from exc

    def enabled_sources(self) -> list[SourceDefinition]:
        """Return enabled source definitions."""

        return [source for source in self.sources.values() if source.enabled]

    def assert_fetch_allowed(self, source_id: str) -> SourceDefinition:
        """Return a source if automated fetching is allowed, otherwise raise."""

        source = self.get(source_id)
        if not source.enabled:
            raise SourcePolicyError(f"Source is disabled: {source.display_name}")
        if source.access_method == SourceAccessMethod.DISABLED:
            raise SourcePolicyError(f"Source has disabled access method: {source.display_name}")
        if source.access_method not in AUTOMATED_ACCESS_METHODS:
            raise SourcePolicyError(
                f"Source is not an automated fetch source: {source.display_name}"
            )
        if not source.capability.automation_allowed:
            raise SourcePolicyError(
                f"Automated access is not allowed for source: {source.display_name}"
            )
        return source


def default_source_registry() -> SourceRegistry:
    """Return the conservative built-in public source registry."""

    return SourceRegistry.from_definitions(
        [
            _source(
                source_id="rba-rss",
                display_name="Reserve Bank of Australia RSS",
                category=SourceCategory.AUSTRALIAN_MARKET,
                homepage_url="https://www.rba.gov.au/",
                access_method=SourceAccessMethod.RSS,
                fetch_strategy="rss",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official RBA public feed. Enable only after connector and "
                    "rate-limit settings are configured."
                ),
                terms_url="https://www.rba.gov.au/copyright/",
                rate_limit_notes="Use polite polling and preserve attribution.",
                metadata={
                    "feed_url": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml",
                    "exchange_rates_feed_url": (
                        "https://www.rba.gov.au/rss/rss-cb-exchange-rates.xml"
                    ),
                },
            ),
            _source(
                source_id="abs-api",
                display_name="Australian Bureau of Statistics API",
                category=SourceCategory.AUSTRALIAN_MARKET,
                homepage_url="https://www.abs.gov.au/",
                api_docs_url=(
                    "https://www.abs.gov.au/about/data-services/"
                    "application-programming-interfaces-apis"
                ),
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official ABS API. Enable only after connector and attribution "
                    "handling are configured."
                ),
                terms_url="https://www.abs.gov.au/about/legislation-and-policy/copyright",
                rate_limit_notes="Follow ABS API guidance and cache responsibly.",
                metadata={
                    "base_url": "https://data.api.abs.gov.au/rest/",
                    "format": "jsondata",
                },
            ),
            _source(
                source_id="asic-media",
                display_name="ASIC Media Releases",
                category=SourceCategory.AUSTRALIAN_MARKET,
                homepage_url="https://www.asic.gov.au/newsroom/media-releases/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="permitted_api_rss_or_manual_export_required",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled until a permitted API, RSS feed, licensed feed, or "
                    "documented user export is configured. Do not scrape ASIC pages."
                ),
                terms_url="https://asic.gov.au/copyright/",
                rate_limit_notes="Requires endpoint and terms review.",
            ),
            _source(
                source_id="asx-announcements",
                display_name="ASX Announcements",
                category=SourceCategory.AUSTRALIAN_MARKET,
                homepage_url="https://www.asx.com.au/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="licensed_or_official_api_required",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled until a permitted official endpoint, licensed provider, "
                    "or documented user export is configured. Do not scrape ASX pages."
                ),
                rate_limit_notes="Requires licence/API review.",
            ),
            _source(
                source_id="market-index",
                display_name="Market Index",
                category=SourceCategory.AUSTRALIAN_MARKET,
                homepage_url="https://www.marketindex.com.au/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="licensed_api_or_manual_export_required",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled until a permitted API/feed/licence is configured. "
                    "Do not scrape pages."
                ),
                rate_limit_notes="Requires written permission or licensed access.",
            ),
            _credentialed_source(
                source_id="fred-api",
                display_name="FRED API",
                category=SourceCategory.GLOBAL_MACRO,
                homepage_url="https://fred.stlouisfed.org/",
                api_docs_url="https://fred.stlouisfed.org/docs/api/fred/",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                auth_type=SourceAuthType.API_KEY,
                env_vars=("FRED_API_KEY",),
                terms_notes=(
                    "Official FRED API. Requires API key and attribution/rate-limit "
                    "compliance."
                ),
                terms_url="https://fred.stlouisfed.org/docs/api/terms_of_use.html",
                rate_limit_notes="Respect FRED API limits and cache responses.",
            ),
            _source(
                source_id="world-bank-api",
                display_name="World Bank API",
                category=SourceCategory.GLOBAL_MACRO,
                homepage_url="https://data.worldbank.org/",
                api_docs_url="https://datahelpdesk.worldbank.org/knowledgebase/topics/125589",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official World Bank data API. Enable only after connector and "
                    "attribution handling are configured."
                ),
                terms_url="https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
                rate_limit_notes="Cache and preserve source attribution.",
            ),
            _source(
                source_id="imf-api",
                display_name="IMF Data API",
                category=SourceCategory.GLOBAL_MACRO,
                homepage_url="https://www.imf.org/en/Data",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official IMF data access. Enable only after connector and terms "
                    "review."
                ),
                rate_limit_notes="Cache and preserve source attribution.",
            ),
            _source(
                source_id="oecd-api",
                display_name="OECD Data API",
                category=SourceCategory.GLOBAL_MACRO,
                homepage_url="https://data-explorer.oecd.org/",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official OECD data access. Enable only after connector and terms "
                    "review."
                ),
                rate_limit_notes="Cache and preserve source attribution.",
            ),
            _source(
                source_id="ecb-data-portal",
                display_name="European Central Bank Data Portal",
                category=SourceCategory.GLOBAL_MACRO,
                homepage_url="https://data.ecb.europa.eu/",
                api_docs_url="https://data.ecb.europa.eu/help/api/overview",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Official ECB data access. Enable only after connector and terms "
                    "review."
                ),
                rate_limit_notes="Cache and preserve source attribution.",
            ),
            _source(
                source_id="gdelt-api",
                display_name="GDELT API",
                category=SourceCategory.NEWS_COMMENTARY,
                homepage_url="https://www.gdeltproject.org/",
                api_docs_url="https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                automation_allowed=True,
                enabled=False,
                terms_notes=(
                    "Public API. Enable only after connector, query, and attribution "
                    "settings are configured."
                ),
                rate_limit_notes="Use narrow queries and cache responses.",
            ),
            _credentialed_source(
                source_id="newsapi",
                display_name="NewsAPI",
                category=SourceCategory.NEWS_COMMENTARY,
                homepage_url="https://newsapi.org/",
                api_docs_url="https://newsapi.org/docs",
                access_method=SourceAccessMethod.API,
                fetch_strategy="json_api",
                auth_type=SourceAuthType.API_KEY,
                env_vars=("NEWSAPI_KEY",),
                terms_notes="Credentialed news API. Use only within plan/licence terms.",
                terms_url="https://newsapi.org/terms",
                rate_limit_notes="Respect plan limits and usage restrictions.",
            ),
            _source(
                source_id="bloomberg",
                display_name="Bloomberg",
                category=SourceCategory.NEWS_COMMENTARY,
                homepage_url="https://www.bloomberg.com/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="licensed_api_or_user_export_required",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled unless licensed API/access or user-provided export permits "
                    "use. Do not scrape."
                ),
                rate_limit_notes="Requires licence review.",
            ),
            _source(
                source_id="reuters",
                display_name="Reuters",
                category=SourceCategory.NEWS_COMMENTARY,
                homepage_url="https://www.reuters.com/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="licensed_api_or_user_export_required",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled unless licensed API/access or user-provided export permits "
                    "use. Do not scrape."
                ),
                rate_limit_notes="Requires licence review.",
            ),
            _source(
                source_id="tradingview",
                display_name="TradingView",
                category=SourceCategory.CHARTS_WATCHLISTS,
                homepage_url="https://www.tradingview.com/",
                access_method=SourceAccessMethod.DISABLED,
                fetch_strategy="alerts_exports_embeds_or_licensed_api_only",
                automation_allowed=False,
                enabled=False,
                terms_notes=(
                    "Disabled for page automation. Use only user exports, "
                    "alerts/webhooks, embeds, or permitted API/licensed access."
                ),
                rate_limit_notes="Do not screen-scrape or automate chart pages.",
            ),
            _source(
                source_id="user-upload",
                display_name="User Upload",
                category=SourceCategory.USER_PROVIDED,
                access_method=SourceAccessMethod.USER_UPLOAD,
                fetch_strategy="manual_upload",
                automation_allowed=False,
                enabled=True,
                terms_notes=(
                    "User supplies files they are entitled to use. Preserve attribution "
                    "if source metadata is available."
                ),
                rate_limit_notes="Not an automated fetch source.",
            ),
        ]
    )


def _source(
    *,
    source_id: str,
    display_name: str,
    category: SourceCategory,
    access_method: SourceAccessMethod,
    fetch_strategy: str,
    terms_notes: str,
    homepage_url: str | None = None,
    api_docs_url: str | None = None,
    automation_allowed: bool,
    enabled: bool,
    terms_url: str | None = None,
    rate_limit_notes: str | None = None,
    redistribution_allowed: bool = False,
    metadata: dict[str, Any] | None = None,
) -> SourceDefinition:
    """Create a non-credentialed source definition."""

    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        category=category,
        homepage_url=homepage_url,
        api_docs_url=api_docs_url,
        capability=SourceCapability(
            access_method=access_method,
            fetch_strategy=fetch_strategy,
            automation_allowed=automation_allowed,
            enabled=enabled,
        ),
        terms=SourceTerms(
            terms_notes=terms_notes,
            terms_url=terms_url,
            rate_limit_notes=rate_limit_notes,
            redistribution_allowed=redistribution_allowed,
        ),
        metadata=metadata or {},
    )


def _credentialed_source(
    *,
    source_id: str,
    display_name: str,
    category: SourceCategory,
    access_method: SourceAccessMethod,
    fetch_strategy: str,
    auth_type: SourceAuthType,
    env_vars: tuple[str, ...],
    terms_notes: str,
    homepage_url: str | None = None,
    api_docs_url: str | None = None,
    terms_url: str | None = None,
    rate_limit_notes: str | None = None,
) -> SourceDefinition:
    """Create a disabled-by-default credentialed source definition."""

    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        category=category,
        homepage_url=homepage_url,
        api_docs_url=api_docs_url,
        capability=SourceCapability(
            access_method=access_method,
            fetch_strategy=fetch_strategy,
            automation_allowed=True,
            enabled=False,
        ),
        terms=SourceTerms(
            terms_notes=terms_notes,
            terms_url=terms_url,
            rate_limit_notes=rate_limit_notes,
            redistribution_allowed=False,
        ),
        credentials=SourceCredentialPolicy(
            auth_type=auth_type,
            required_env_vars=env_vars,
            credential_notes="Read credentials from environment variables only.",
        ),
    )


def _normalize_source_id(source_id: str) -> str:
    """Normalize source ids consistently."""

    return source_id.strip().lower().replace(" ", "-")
