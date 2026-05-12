"""Disabled-by-default Under the Radar connector stub."""

from __future__ import annotations

from collections.abc import Mapping
import os

from pydantic import BaseModel, ConfigDict, Field

from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateResearchBoundary,
    PrivateResearchPolicyError,
)
from market_pdf_insights.private_settings import PrivateResearchSettings


UNDERTHERADAR_CONNECTOR_ENABLED_ENV = "UNDERTHERADAR_CONNECTOR_ENABLED"
UNDERTHERADAR_USERNAME_ENV = "UNDERTHERADAR_USERNAME"
UNDERTHERADAR_PASSWORD_ENV = "UNDERTHERADAR_PASSWORD"


class UnderTheRadarConnectorError(PrivateResearchPolicyError):
    """Base error for blocked Under the Radar connector actions."""


class UnderTheRadarConnectorNotEnabledError(UnderTheRadarConnectorError):
    """Raised when the connector has not been explicitly enabled."""


class UnderTheRadarConnectorPermissionError(UnderTheRadarConnectorError):
    """Raised when subscription permission has not been explicitly confirmed."""


class UnderTheRadarConnectorCredentialError(UnderTheRadarConnectorError):
    """Raised when credential references are missing."""


class UnderTheRadarConnectorNotImplementedError(UnderTheRadarConnectorError):
    """Raised after gating because no live automation is implemented."""


class UnderTheRadarConnectorConfig(BaseModel):
    """Non-secret connector gate configuration."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    connector_enabled_env_var: str = UNDERTHERADAR_CONNECTOR_ENABLED_ENV
    username_env_var: str = UNDERTHERADAR_USERNAME_ENV
    password_env_var: str = UNDERTHERADAR_PASSWORD_ENV
    terms_permission_confirmed: bool = False
    credential_storage_notes: str = (
        "Provide credentials through environment variables, an OS keyring, or an external "
        "secret manager. Do not commit subscription credentials."
    )
    preferred_access_paths: tuple[str, ...] = (
        "download PDFs manually and import them",
        "forward or save subscriber emails",
        "use an official export, feed, or API if Under the Radar offers one",
        "consider browser automation only after explicit terms confirmation",
    )

    def is_enabled(self, environ: Mapping[str, str]) -> bool:
        """Return whether the connector flag is explicitly truthy."""

        return _truthy(environ.get(self.connector_enabled_env_var))

    def credentials_present(self, environ: Mapping[str, str]) -> bool:
        """Return whether configured credential environment variables are populated."""

        return bool(
            environ.get(self.username_env_var, "").strip()
            and environ.get(self.password_env_var, "").strip()
        )


class UnderTheRadarConnectorStatus(BaseModel):
    """Safe status for diagnostics without exposing credential values."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = "Under the Radar"
    enabled_env_var: str
    enabled: bool
    logged_in_automation_enabled: bool
    settings_terms_confirmed: bool
    connector_terms_confirmed: bool
    username_supplied: bool
    password_supplied: bool
    ready: bool
    message: str
    preferred_access_paths: tuple[str, ...] = Field(default_factory=tuple)


class UnderTheRadarConnector:
    """Safe future connector stub with explicit gates and no live scraping."""

    def __init__(
        self,
        *,
        settings: PrivateResearchSettings | None = None,
        config: UnderTheRadarConnectorConfig | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings or PrivateResearchSettings()
        self.config = config or UnderTheRadarConnectorConfig()
        self._environ = environ

    def status(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> UnderTheRadarConnectorStatus:
        """Return a non-secret readiness snapshot."""

        resolved_environ = self._resolve_environ(environ)
        enabled = self.config.is_enabled(resolved_environ)
        username_supplied = bool(resolved_environ.get(self.config.username_env_var, "").strip())
        password_supplied = bool(resolved_environ.get(self.config.password_env_var, "").strip())
        import_sources = self.settings.import_sources
        logged_in_enabled = import_sources.logged_in_automation
        settings_terms_confirmed = import_sources.logged_in_automation_terms_confirmed
        connector_terms_confirmed = self.config.terms_permission_confirmed
        ready = all(
            (
                enabled,
                logged_in_enabled,
                settings_terms_confirmed,
                connector_terms_confirmed,
                username_supplied,
                password_supplied,
            )
        )
        return UnderTheRadarConnectorStatus(
            enabled_env_var=self.config.connector_enabled_env_var,
            enabled=enabled,
            logged_in_automation_enabled=logged_in_enabled,
            settings_terms_confirmed=settings_terms_confirmed,
            connector_terms_confirmed=connector_terms_confirmed,
            username_supplied=username_supplied,
            password_supplied=password_supplied,
            ready=ready,
            message=_status_message(
                enabled=enabled,
                logged_in_enabled=logged_in_enabled,
                settings_terms_confirmed=settings_terms_confirmed,
                connector_terms_confirmed=connector_terms_confirmed,
                username_supplied=username_supplied,
                password_supplied=password_supplied,
                config=self.config,
            ),
            preferred_access_paths=self.config.preferred_access_paths,
        )

    def assert_ready(self, environ: Mapping[str, str] | None = None) -> None:
        """Raise unless every explicit gate required for future automation is satisfied."""

        status = self.status(environ)
        if not status.enabled:
            raise UnderTheRadarConnectorNotEnabledError(
                f"Under the Radar connector is disabled. Set "
                f"{self.config.connector_enabled_env_var}=true only after confirming this "
                "access pattern is permitted. Prefer manual PDF downloads, forwarded emails, "
                "or official exports."
            )
        if not status.logged_in_automation_enabled:
            raise UnderTheRadarConnectorPermissionError(
                "Logged-in automation is disabled in private research settings. Keep using "
                "uploads, local files, forwarded emails, manual notes, or permitted exports "
                "unless the subscription terms allow automation."
            )
        if not status.settings_terms_confirmed or not status.connector_terms_confirmed:
            raise UnderTheRadarConnectorPermissionError(
                "Under the Radar automation requires explicit confirmation that the "
                "subscription terms permit this exact personal-use access pattern."
            )
        if not status.username_supplied or not status.password_supplied:
            raise UnderTheRadarConnectorCredentialError(
                "Under the Radar credentials are not supplied. Set non-empty values through "
                f"{self.config.username_env_var} and {self.config.password_env_var}, or adapt "
                "this stub to a keyring/secret-manager resolver before enabling automation."
            )
        boundary = PrivateResearchBoundary(
            logged_in_automation_enabled=True,
            explicit_terms_confirmation=True,
        )
        boundary.assert_access_method_allowed(PrivateResearchAccessMethod.LOGGED_IN_AUTOMATION)

    def import_reports(self, environ: Mapping[str, str] | None = None) -> None:
        """Validate gates, then refuse because live automation is intentionally absent."""

        self.assert_ready(environ)
        raise UnderTheRadarConnectorNotImplementedError(
            "No live Under the Radar login, scraping, browser automation, or PDF download "
            "is implemented. Build a connector only after reviewing subscription terms and "
            "choosing a stable permitted export/API/browser-automation path."
        )

    def _resolve_environ(self, environ: Mapping[str, str] | None) -> Mapping[str, str]:
        if environ is not None:
            return environ
        if self._environ is not None:
            return self._environ
        return os.environ


def undertheradar_preferred_access_paths() -> tuple[str, ...]:
    """Return safer alternatives to logged-in automation."""

    return UnderTheRadarConnectorConfig().preferred_access_paths


def _status_message(
    *,
    enabled: bool,
    logged_in_enabled: bool,
    settings_terms_confirmed: bool,
    connector_terms_confirmed: bool,
    username_supplied: bool,
    password_supplied: bool,
    config: UnderTheRadarConnectorConfig,
) -> str:
    if not enabled:
        return f"Disabled until {config.connector_enabled_env_var}=true is set."
    if not logged_in_enabled:
        return "Disabled by private research settings."
    if not settings_terms_confirmed or not connector_terms_confirmed:
        return "Waiting for explicit subscription terms confirmation."
    if not username_supplied or not password_supplied:
        return "Waiting for secure credential references."
    return "All gates are satisfied, but live automation is still not implemented."


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
