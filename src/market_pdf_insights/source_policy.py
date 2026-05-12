"""Guardrails for compliant market-intelligence source use."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourcePolicyError(RuntimeError):
    """Raised when a source is not permitted for the requested access pattern."""


class AdviceBoundary(StrEnum):
    """Supported output boundaries for market-intelligence content."""

    FACTUAL_INFORMATION = "factual_information"
    GENERAL_MARKET_COMMENTARY = "general_market_commentary"
    PERSONAL_ADVICE = "personal_advice"


class SourceAccessMethod(StrEnum):
    """Allowed ways the app may receive source material."""

    API = "api"
    RSS = "rss"
    LICENSED_FEED = "licensed_feed"
    USER_UPLOAD = "user_upload"
    EMAIL_FORWARD = "email_forward"
    MANUAL_ENTRY = "manual_entry"
    DISABLED = "disabled"


AUTOMATED_ACCESS_METHODS = frozenset(
    {
        SourceAccessMethod.API,
        SourceAccessMethod.RSS,
        SourceAccessMethod.LICENSED_FEED,
    }
)


class SourceAttribution(BaseModel):
    """Metadata that should travel with fetched or user-provided source content."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    url: str | None = None
    title: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    terms_url: str | None = None
    licence_notes: str | None = None


class SourceUsePolicy(BaseModel):
    """Policy for whether and how a source may be used by connectors."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    source_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    access_method: SourceAccessMethod
    enabled: bool = False
    automation_allowed: bool = False
    redistribution_allowed: bool = False
    requires_credentials: bool = False
    homepage_url: str | None = None
    terms_url: str | None = None
    terms_notes: str = Field(min_length=1)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @model_validator(mode="after")
    def _validate_enabled_source(self) -> SourceUsePolicy:
        if self.enabled and self.access_method == SourceAccessMethod.DISABLED:
            raise ValueError("enabled sources cannot use disabled access_method")
        if (
            self.enabled
            and self.access_method in AUTOMATED_ACCESS_METHODS
            and not self.automation_allowed
        ):
            raise ValueError("enabled automated sources must set automation_allowed=True")
        return self

    @property
    def is_user_supplied(self) -> bool:
        """Return whether the content comes from an explicit user-provided action."""

        return self.access_method in {
            SourceAccessMethod.USER_UPLOAD,
            SourceAccessMethod.EMAIL_FORWARD,
            SourceAccessMethod.MANUAL_ENTRY,
        }

    def assert_fetch_allowed(self) -> None:
        """Raise if a connector is not allowed to fetch this source automatically."""

        if not self.enabled:
            raise SourcePolicyError(f"Source is disabled: {self.display_name}")
        if self.access_method == SourceAccessMethod.DISABLED:
            raise SourcePolicyError(f"Source has disabled access method: {self.display_name}")
        if self.access_method not in AUTOMATED_ACCESS_METHODS:
            raise SourcePolicyError(
                f"Source is not an automated fetch source: {self.display_name}"
            )
        if not self.automation_allowed:
            raise SourcePolicyError(
                f"Automated access is not allowed for source: {self.display_name}"
            )


class MarketIntelligenceGuardrails(BaseModel):
    """High-level product guardrails for public market-intelligence briefs."""

    model_config = ConfigDict(extra="forbid")

    allowed_boundaries: tuple[AdviceBoundary, ...] = (
        AdviceBoundary.FACTUAL_INFORMATION,
        AdviceBoundary.GENERAL_MARKET_COMMENTARY,
    )
    prohibited_boundary: AdviceBoundary = AdviceBoundary.PERSONAL_ADVICE
    require_source_attribution: bool = True
    require_terms_metadata: bool = True
    allow_scraping_without_permission: bool = False
    allow_hardcoded_api_keys: bool = False
    default_disclaimer: str = (
        "This briefing summarizes factual market information and general market commentary. "
        "It is not financial, investment, tax, legal, or accounting advice."
    )

    def assert_output_boundary_allowed(self, boundary: AdviceBoundary) -> None:
        """Raise if a requested output boundary is outside product scope."""

        if boundary == self.prohibited_boundary or boundary not in self.allowed_boundaries:
            raise SourcePolicyError(f"Output boundary is not allowed: {boundary.value}")


DEFAULT_GUARDRAILS = MarketIntelligenceGuardrails()

