"""Secure local settings for private subscribed research."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
import secrets
import tomllib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrivateSettingsError(ValueError):
    """Raised when private settings are missing or unsafe."""


class PrivateSecretsStrategy(StrEnum):
    """Documented strategies for private secrets."""

    ENVIRONMENT = "environment"
    OS_KEYRING = "os_keyring"
    EXTERNAL_SECRET_MANAGER = "external_secret_manager"


class PrivateImportSourceSettings(BaseModel):
    """Enabled private import paths."""

    model_config = ConfigDict(extra="forbid")

    user_upload: bool = True
    local_file: bool = True
    email_forward: bool = True
    manual_entry: bool = True
    subscription_export: bool = True
    logged_in_automation: bool = False
    logged_in_automation_terms_confirmed: bool = False

    @model_validator(mode="after")
    def _validate_logged_in_automation(self) -> PrivateImportSourceSettings:
        if self.logged_in_automation and not self.logged_in_automation_terms_confirmed:
            raise ValueError(
                "logged_in_automation requires explicit subscription terms confirmation"
            )
        return self


class PrivateRetentionPolicy(BaseModel):
    """Retention settings for private local storage."""

    model_config = ConfigDict(extra="forbid")

    store_raw_documents: bool = False
    raw_document_retention_days: int | None = Field(default=None, ge=1)
    extracted_text_retention_days: int | None = Field(default=None, ge=1)
    summary_retention_days: int | None = Field(default=None, ge=1)
    metadata_retention_days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_raw_retention(self) -> PrivateRetentionPolicy:
        if not self.store_raw_documents and self.raw_document_retention_days is not None:
            raise ValueError(
                "raw_document_retention_days requires store_raw_documents=True"
            )
        return self


class PrivatePasswordProtectionSettings(BaseModel):
    """Password protection settings without storing raw passwords."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = False
    password_hash_env_var: str = "MARKET_PRIVATE_UI_PASSWORD_HASH"
    session_timeout_minutes: int = Field(default=60, ge=5, le=24 * 60)

    def resolve_password_hash(self, environ: Mapping[str, str] | None = None) -> str | None:
        """Read the configured password hash from the environment."""

        if not self.enabled:
            return None
        env = os.environ if environ is None else environ
        password_hash = env.get(self.password_hash_env_var)
        if not password_hash:
            raise PrivateSettingsError(
                f"{self.password_hash_env_var} is required when private UI password "
                "protection is enabled."
            )
        return password_hash


class PrivateResearchSettings(BaseModel):
    """Top-level local-only settings for private research."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    local_data_dir: Path = Path(".private-research")
    database_name: str = "private-research.sqlite3"
    secrets_strategy: PrivateSecretsStrategy = PrivateSecretsStrategy.ENVIRONMENT
    secrets_strategy_notes: str = (
        "Use environment variables, OS keyring, or a documented external secret manager. "
        "Do not commit credentials or raw passwords."
    )
    import_sources: PrivateImportSourceSettings = Field(
        default_factory=PrivateImportSourceSettings
    )
    retention: PrivateRetentionPolicy = Field(default_factory=PrivateRetentionPolicy)
    password_protection: PrivatePasswordProtectionSettings = Field(
        default_factory=PrivatePasswordProtectionSettings
    )

    @field_validator("database_name")
    @classmethod
    def _validate_database_name(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("database_name must be a filename, not a path")
        if not value.endswith((".sqlite", ".sqlite3", ".db")):
            raise ValueError("database_name must end in .sqlite, .sqlite3, or .db")
        return value

    @property
    def database_path(self) -> Path:
        """Return the configured local SQLite database path."""

        return self.local_data_dir / self.database_name

    @property
    def raw_documents_dir(self) -> Path:
        """Return the directory reserved for explicitly stored raw documents."""

        return self.local_data_dir / "raw-documents"

    @property
    def extracted_text_dir(self) -> Path:
        """Return the directory reserved for extracted text sidecar files."""

        return self.local_data_dir / "extracted-text"

    def ensure_local_directories(self) -> None:
        """Create local private data directories."""

        self.local_data_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_text_dir.mkdir(parents=True, exist_ok=True)
        if self.retention.store_raw_documents:
            self.raw_documents_dir.mkdir(parents=True, exist_ok=True)


def load_private_research_settings(path: str | Path) -> PrivateResearchSettings:
    """Load private settings from TOML."""

    settings_path = Path(path)
    if not settings_path.exists():
        raise FileNotFoundError(f"Private settings file does not exist: {settings_path}")
    if settings_path.suffix.lower() != ".toml":
        raise PrivateSettingsError("Private settings must be stored in TOML.")
    try:
        data = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PrivateSettingsError(f"Could not parse private settings TOML: {exc}") from exc
    return PrivateResearchSettings.model_validate(data)


def hash_private_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = 260_000,
) -> str:
    """Return a PBKDF2 password hash for environment-variable storage."""

    if not password:
        raise PrivateSettingsError("Password must not be empty.")
    if iterations < 100_000:
        raise PrivateSettingsError("Password hash iterations must be at least 100000.")
    resolved_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt,
        iterations,
    )
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        _b64(resolved_salt),
        _b64(digest),
    )


def verify_private_password(password: str, password_hash: str) -> bool:
    """Verify a password against `hash_private_password` output."""

    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = _unb64(salt_text)
        expected_digest = _unb64(digest_text)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected_digest)


def private_settings_template() -> str:
    """Return a safe TOML template without secrets."""

    return "\n".join(
        [
            'local_data_dir = ".private-research"',
            'database_name = "private-research.sqlite3"',
            'secrets_strategy = "environment"',
            "",
            "[import_sources]",
            "user_upload = true",
            "local_file = true",
            "email_forward = true",
            "manual_entry = true",
            "subscription_export = true",
            "logged_in_automation = false",
            "logged_in_automation_terms_confirmed = false",
            "",
            "[retention]",
            "store_raw_documents = false",
            "",
            "[password_protection]",
            "enabled = false",
            'password_hash_env_var = "MARKET_PRIVATE_UI_PASSWORD_HASH"',
            "session_timeout_minutes = 60",
            "",
        ]
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
