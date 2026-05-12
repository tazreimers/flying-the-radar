"""Boundaries for private, single-user subscribed research workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrivateResearchPolicyError(RuntimeError):
    """Raised when a private research workflow crosses product boundaries."""


class PrivateResearchAccessMethod(StrEnum):
    """Allowed or gated ways to bring private research into the app."""

    USER_UPLOAD = "user_upload"
    LOCAL_FILE = "local_file"
    EMAIL_FORWARD = "email_forward"
    MANUAL_ENTRY = "manual_entry"
    SUBSCRIPTION_EXPORT = "subscription_export"
    LOGGED_IN_AUTOMATION = "logged_in_automation"


class PrivateResearchModule(StrEnum):
    """Planned private research module boundaries."""

    PRIVATE_INGESTION = "private_ingestion"
    SECURE_SETTINGS = "secure_settings"
    DOCUMENT_LIBRARY = "document_library"
    RECOMMENDATION_EXTRACTION = "recommendation_extraction"
    PERSONAL_DIGEST = "personal_digest"
    SEARCH_QA = "search_qa"
    PASSWORD_PROTECTED_UI = "password_protected_ui"


class PrivateResearchBoundary(BaseModel):
    """Product boundary for private subscribed research."""

    model_config = ConfigDict(extra="forbid")

    single_user_private_use: bool = True
    redistribution_allowed: bool = False
    logged_in_automation_enabled: bool = False
    explicit_terms_confirmation: bool = False
    financial_advice_allowed: bool = False
    preserve_source_attribution: bool = True
    full_text_export_allowed: bool = False

    @model_validator(mode="after")
    def _validate_private_boundary(self) -> PrivateResearchBoundary:
        if not self.single_user_private_use:
            raise ValueError("private research workflows must remain single-user first")
        if self.redistribution_allowed:
            raise ValueError("redistribution of subscribed research is not allowed")
        if self.financial_advice_allowed:
            raise ValueError("private research workflows must not provide financial advice")
        if not self.preserve_source_attribution:
            raise ValueError("source attribution must be preserved")
        return self

    def assert_access_method_allowed(self, method: PrivateResearchAccessMethod) -> None:
        """Raise unless an access method is allowed by the current boundary."""

        if method == PrivateResearchAccessMethod.LOGGED_IN_AUTOMATION:
            if not self.logged_in_automation_enabled:
                raise PrivateResearchPolicyError(
                    "Logged-in automation is disabled by default. Prefer uploads, local files, "
                    "forwarded emails, manual entry, or subscriber exports."
                )
            if not self.explicit_terms_confirmation:
                raise PrivateResearchPolicyError(
                    "Logged-in automation requires explicit confirmation that subscription "
                    "terms permit this access pattern."
                )
        if method == PrivateResearchAccessMethod.SUBSCRIPTION_EXPORT:
            return
        if method not in _PREFERRED_PRIVATE_ACCESS_METHODS:
            raise PrivateResearchPolicyError(f"Unsupported private access method: {method.value}")


class PrivateSourceAttribution(BaseModel):
    """Attribution metadata for private subscribed research."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_name: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    access_method: PrivateResearchAccessMethod
    url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    subscription_notes: str | None = None
    licence_notes: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def _require_retrieved_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at must include timezone information")
        return value


class PrivateResearchModuleBoundary(BaseModel):
    """Design boundary for one future private research module."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    module: PrivateResearchModule
    responsibility: str = Field(min_length=1)
    allowed_inputs: tuple[str, ...] = Field(default_factory=tuple)
    prohibited_outputs: tuple[str, ...] = Field(default_factory=tuple)


def default_private_research_boundary() -> PrivateResearchBoundary:
    """Return the default private-use guardrail set."""

    return PrivateResearchBoundary()


def default_private_research_module_boundaries() -> tuple[PrivateResearchModuleBoundary, ...]:
    """Return planned module boundaries for the private research companion."""

    return (
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.PRIVATE_INGESTION,
            responsibility=(
                "Import user-provided PDFs, emails, local files, manual notes, and permitted "
                "subscription exports into normalized private research records."
            ),
            allowed_inputs=("PDF upload", "local file", "forwarded email", "manual note"),
            prohibited_outputs=("logged-in scraping", "redistributed paid content"),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.SECURE_SETTINGS,
            responsibility="Store local-only private settings and references to secrets.",
            allowed_inputs=("environment variables", "local config", "password hash"),
            prohibited_outputs=("hardcoded passwords", "committed credentials"),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.DOCUMENT_LIBRARY,
            responsibility="Index private documents with attribution and local metadata.",
            allowed_inputs=("normalized private research records",),
            prohibited_outputs=("public brief source items", "redistribution feeds"),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.RECOMMENDATION_EXTRACTION,
            responsibility=(
                "Extract general recommendation facts, risks, catalysts, valuation notes, and "
                "watch items from subscribed research without giving personal advice."
            ),
            allowed_inputs=("private document text", "source attribution"),
            prohibited_outputs=("personal buy/sell/hold instructions",),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.PERSONAL_DIGEST,
            responsibility="Render a private single-user digest from the local library.",
            allowed_inputs=("private summaries", "library metadata"),
            prohibited_outputs=("public redistribution", "bulk forwarded paid content"),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.SEARCH_QA,
            responsibility="Search and answer questions over local private records with citations.",
            allowed_inputs=("local index", "private summaries", "user questions"),
            prohibited_outputs=("uncited claims", "full report reproduction"),
        ),
        PrivateResearchModuleBoundary(
            module=PrivateResearchModule.PASSWORD_PROTECTED_UI,
            responsibility="Expose local private library screens behind a password gate.",
            allowed_inputs=("local session", "password verifier"),
            prohibited_outputs=("unauthenticated private content",),
        ),
    )


def private_research_scope_notes() -> tuple[str, ...]:
    """Return concise private-use notes for UI/docs/tests."""

    return (
        "Single-user private use only.",
        "Use material the subscriber is already entitled to access.",
        "Prefer uploads, local files, forwarded emails, manual notes, or permitted exports.",
        "Do not redistribute paid content.",
        "Do not provide personalized financial advice.",
        "Logged-in automation stays disabled unless terms explicitly permit it.",
    )


_PREFERRED_PRIVATE_ACCESS_METHODS = frozenset(
    {
        PrivateResearchAccessMethod.USER_UPLOAD,
        PrivateResearchAccessMethod.LOCAL_FILE,
        PrivateResearchAccessMethod.EMAIL_FORWARD,
        PrivateResearchAccessMethod.MANUAL_ENTRY,
    }
)
