"""Configuration helpers for the daily public market brief."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from market_pdf_insights.daily_brief_rendering import DailyBriefEmailSettings
from market_pdf_insights.source_policy import SourceAccessMethod
from market_pdf_insights.source_registry import (
    SourceAuthType,
    SourceCapability,
    SourceCategory,
    SourceCredentialPolicy,
    SourceDefinition,
    SourceTerms,
)

DailyBriefSourceKind = Literal["local_fixture", "rss", "json_api"]
DailyBriefLLMBackend = Literal["placeholder", "openai"]


class DailyBriefConfigError(ValueError):
    """Raised when daily brief configuration is invalid."""


class DailyBriefSourceConfig(BaseModel):
    """Configuration for one enabled or disabled brief source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    display_name: str | None = None
    enabled: bool = True
    kind: DailyBriefSourceKind = "local_fixture"
    category: SourceCategory = SourceCategory.USER_PROVIDED
    fixture_path: Path | None = None
    feed_url: str | None = None
    endpoint_url: str | None = None
    items_path: tuple[str, ...] = ("items",)
    homepage_url: str | None = None
    api_docs_url: str | None = None
    terms_notes: str = "Configured source. Preserve attribution and comply with source terms."
    terms_url: str | None = None
    rate_limit_notes: str | None = None
    redistribution_allowed: bool = False
    required_env_vars: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("items_path", "required_env_vars", mode="before")
    @classmethod
    def _coerce_string_tuple(cls, value: Any) -> tuple[str, ...]:
        return _string_tuple(value)

    @model_validator(mode="after")
    def _validate_kind_settings(self) -> DailyBriefSourceConfig:
        if not self.enabled:
            return self
        if self.kind == "local_fixture" and self.fixture_path is None:
            raise ValueError("local_fixture sources require fixture_path when enabled")
        if self.kind == "rss" and not self.feed_url:
            raise ValueError("rss sources require feed_url when enabled")
        if self.kind == "json_api" and not self.endpoint_url:
            raise ValueError("json_api sources require endpoint_url when enabled")
        return self

    @property
    def resolved_display_name(self) -> str:
        """Return a display name for status output and citations."""

        return self.display_name or self.source_id.replace("-", " ").title()


class DailyBriefIngestionConfig(BaseModel):
    """Ingestion-wide settings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cache_path: Path | None = None
    lookback_hours: int = Field(default=36, ge=1, le=24 * 14)


class DailyBriefLLMConfig(BaseModel):
    """LLM settings for brief synthesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backend: DailyBriefLLMBackend = "placeholder"
    model: str | None = None


class DailyBriefRegionConfig(BaseModel):
    """Region and timezone settings for daily operations."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    primary_region: str = "AU"
    timezone: str = "Australia/Perth"
    regions: tuple[str, ...] = ("AU", "US", "global")

    @field_validator("regions", mode="before")
    @classmethod
    def _coerce_regions(cls, value: Any) -> tuple[str, ...]:
        return _string_tuple(value)


class DailyBriefOutputConfig(BaseModel):
    """Configured output paths."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    json_path: Path | None = Field(default=None, alias="json")
    markdown: Path | None = None
    html: Path | None = None
    text: Path | None = None
    email_dry_run: Path | None = None


class DailyBriefEmailConfig(BaseModel):
    """Email envelope settings without provider credentials."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sender: str | None = None
    recipients: list[str] = Field(default_factory=list)
    subject_prefix: str = "Daily Market Brief"
    reply_to: str | None = None

    @field_validator("recipients", mode="before")
    @classmethod
    def _coerce_recipients(cls, value: Any) -> list[str]:
        return list(_string_tuple(value))

    @property
    def is_partially_configured(self) -> bool:
        """Return whether any email envelope field was set."""

        return bool(self.sender or self.recipients or self.reply_to)

    def to_settings(self) -> DailyBriefEmailSettings:
        """Return validated rendering-layer email settings."""

        if not self.sender:
            raise DailyBriefConfigError("email.sender is required for dry-run email output")
        if not self.recipients:
            raise DailyBriefConfigError("email.recipients is required for dry-run email output")
        return DailyBriefEmailSettings(
            sender=self.sender,
            recipients=self.recipients,
            subject_prefix=self.subject_prefix,
            reply_to=self.reply_to,
        )


class DailyBriefConfig(BaseModel):
    """Top-level daily brief configuration."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sources: list[DailyBriefSourceConfig] = Field(default_factory=list)
    watchlist: tuple[str, ...] = ()
    ingestion: DailyBriefIngestionConfig = Field(default_factory=DailyBriefIngestionConfig)
    llm: DailyBriefLLMConfig = Field(default_factory=DailyBriefLLMConfig)
    regions: DailyBriefRegionConfig = Field(default_factory=DailyBriefRegionConfig)
    output: DailyBriefOutputConfig = Field(default_factory=DailyBriefOutputConfig)
    email: DailyBriefEmailConfig = Field(default_factory=DailyBriefEmailConfig)

    _config_dir: Path = PrivateAttr(default=Path("."))

    @field_validator("watchlist", mode="before")
    @classmethod
    def _coerce_watchlist(cls, value: Any) -> tuple[str, ...]:
        return _string_tuple(value)

    @property
    def config_dir(self) -> Path:
        """Return the directory used for resolving config-relative paths."""

        return self._config_dir

    @property
    def enabled_sources(self) -> list[DailyBriefSourceConfig]:
        """Return enabled source configs."""

        return [source for source in self.sources if source.enabled]


def load_daily_brief_config(path: str | Path) -> DailyBriefConfig:
    """Load a daily brief config from TOML."""

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Daily brief config does not exist: {config_path}")
    if config_path.suffix.lower() in {".yaml", ".yml"}:
        raise DailyBriefConfigError(
            "YAML config is not supported without an optional parser; use TOML instead."
        )
    if config_path.suffix.lower() != ".toml":
        raise DailyBriefConfigError("Daily brief config must be a .toml file.")

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DailyBriefConfigError(f"Could not parse TOML config: {exc}") from exc

    config = DailyBriefConfig.model_validate(data)
    config._config_dir = config_path.parent
    return config


def validate_daily_brief_config(
    config: DailyBriefConfig,
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
    require_enabled_sources: bool = True,
    require_email: bool = False,
) -> list[str]:
    """Return human-readable validation errors for runtime config checks."""

    env = os.environ if environ is None else environ
    base_dir = Path(config_dir) if config_dir is not None else config.config_dir
    errors: list[str] = []

    if require_enabled_sources and not config.enabled_sources:
        errors.append("at least one source must be enabled")

    for source in config.enabled_sources:
        missing_env = [name for name in source.required_env_vars if not env.get(name)]
        if missing_env:
            errors.append(
                f"source {source.source_id} requires environment variable(s): "
                f"{', '.join(missing_env)}"
            )
        if source.kind == "local_fixture" and source.fixture_path is not None:
            fixture_path = resolve_config_path(source.fixture_path, base_dir)
            if not fixture_path.exists():
                errors.append(f"source {source.source_id} fixture does not exist: {fixture_path}")

    if require_email or config.email.is_partially_configured:
        if not config.email.sender:
            errors.append("email.sender is required when email output is configured")
        if not config.email.recipients:
            errors.append("email.recipients is required when email output is configured")

    return errors


def assert_daily_brief_config_valid(
    config: DailyBriefConfig,
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
    require_email: bool = False,
) -> None:
    """Raise when the config has runtime validation errors."""

    errors = validate_daily_brief_config(
        config,
        environ=environ,
        config_dir=config_dir,
        require_email=require_email,
    )
    if errors:
        raise DailyBriefConfigError(_format_errors("Daily brief config is invalid", errors))


def source_definition_from_config(source: DailyBriefSourceConfig) -> SourceDefinition:
    """Build source registry metadata from source config."""

    access_method = _access_method_for_kind(source.kind)
    credentials = SourceCredentialPolicy()
    if source.required_env_vars:
        credentials = SourceCredentialPolicy(
            auth_type=SourceAuthType.API_KEY,
            required_env_vars=source.required_env_vars,
            credential_notes="Read credentials from environment variables only.",
        )
    return SourceDefinition(
        source_id=source.source_id,
        display_name=source.resolved_display_name,
        category=source.category,
        homepage_url=source.homepage_url,
        api_docs_url=source.api_docs_url,
        capability=SourceCapability(
            access_method=access_method,
            fetch_strategy=f"configured_{source.kind}",
            automation_allowed=source.kind in {"rss", "json_api"},
            enabled=source.enabled,
        ),
        terms=SourceTerms(
            terms_notes=source.terms_notes,
            terms_url=source.terms_url,
            rate_limit_notes=source.rate_limit_notes,
            redistribution_allowed=source.redistribution_allowed,
        ),
        credentials=credentials,
        metadata=source.metadata,
    )


def describe_daily_brief_sources(
    config: DailyBriefConfig,
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
) -> list[str]:
    """Return concise source status lines for CLI output."""

    env = os.environ if environ is None else environ
    base_dir = Path(config_dir) if config_dir is not None else config.config_dir
    lines: list[str] = []
    for source in config.sources:
        status = "enabled" if source.enabled else "disabled"
        details = [source.kind, source.category.value, status]
        if source.required_env_vars:
            missing = [name for name in source.required_env_vars if not env.get(name)]
            details.append("env ok" if not missing else f"missing env: {', '.join(missing)}")
        if source.kind == "local_fixture" and source.fixture_path is not None:
            path = resolve_config_path(source.fixture_path, base_dir)
            details.append(f"fixture: {path}")
        lines.append(f"- {source.source_id}: {source.resolved_display_name} ({'; '.join(details)})")
    if not lines:
        lines.append("- no sources configured")
    return lines


def resolve_config_path(path: str | Path, config_dir: str | Path) -> Path:
    """Resolve relative config paths against the config directory."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(config_dir) / candidate


def _access_method_for_kind(kind: DailyBriefSourceKind) -> SourceAccessMethod:
    if kind == "local_fixture":
        return SourceAccessMethod.USER_UPLOAD
    if kind == "rss":
        return SourceAccessMethod.RSS
    if kind == "json_api":
        return SourceAccessMethod.API
    raise DailyBriefConfigError(f"Unsupported source kind: {kind}")


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise TypeError("expected a string or sequence of strings")


def _format_errors(title: str, errors: Sequence[str]) -> str:
    return f"{title}:\n" + "\n".join(f"- {error}" for error in errors)
