from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_pdf_insights.private_settings import (
    PrivateImportSourceSettings,
    PrivatePasswordProtectionSettings,
    PrivateResearchSettings,
    PrivateRetentionPolicy,
    PrivateSettingsError,
    hash_private_password,
    load_private_research_settings,
    private_settings_template,
    verify_private_password,
)


def test_private_settings_default_to_local_metadata_only(tmp_path) -> None:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")

    settings.ensure_local_directories()

    assert settings.database_path == tmp_path / "private" / "private-research.sqlite3"
    assert settings.import_sources.user_upload
    assert not settings.import_sources.logged_in_automation
    assert not settings.retention.store_raw_documents
    assert settings.extracted_text_dir.exists()
    assert not settings.raw_documents_dir.exists()


def test_private_settings_can_enable_raw_document_directory(tmp_path) -> None:
    settings = PrivateResearchSettings(
        local_data_dir=tmp_path / "private",
        retention=PrivateRetentionPolicy(store_raw_documents=True),
    )

    settings.ensure_local_directories()

    assert settings.raw_documents_dir.exists()


def test_import_settings_reject_logged_in_automation_without_terms_confirmation() -> None:
    with pytest.raises(ValidationError, match="terms confirmation"):
        PrivateImportSourceSettings(logged_in_automation=True)


def test_retention_rejects_raw_retention_when_raw_storage_is_disabled() -> None:
    with pytest.raises(ValidationError, match="store_raw_documents=True"):
        PrivateRetentionPolicy(raw_document_retention_days=30)


def test_password_hash_round_trip_and_env_resolution() -> None:
    password_hash = hash_private_password(
        "correct horse battery staple",
        salt=b"0123456789abcdef",
        iterations=100_000,
    )
    settings = PrivatePasswordProtectionSettings(enabled=True)

    resolved = settings.resolve_password_hash(
        {"MARKET_PRIVATE_UI_PASSWORD_HASH": password_hash}
    )

    assert resolved == password_hash
    assert verify_private_password("correct horse battery staple", password_hash)
    assert not verify_private_password("wrong password", password_hash)
    assert "correct horse" not in password_hash


def test_password_protection_requires_hash_env_when_enabled() -> None:
    settings = PrivatePasswordProtectionSettings(enabled=True)

    with pytest.raises(PrivateSettingsError, match="MARKET_PRIVATE_UI_PASSWORD_HASH"):
        settings.resolve_password_hash({})


def test_load_private_research_settings_from_toml(tmp_path) -> None:
    settings_path = tmp_path / "private.toml"
    settings_path.write_text(
        """
local_data_dir = "private-data"
database_name = "research.sqlite3"

[import_sources]
user_upload = true
local_file = true
email_forward = true
manual_entry = true
subscription_export = true
logged_in_automation = false

[retention]
store_raw_documents = false
summary_retention_days = 365

[password_protection]
enabled = false
session_timeout_minutes = 30
""".strip(),
        encoding="utf-8",
    )

    settings = load_private_research_settings(settings_path)

    assert settings.local_data_dir.name == "private-data"
    assert settings.database_name == "research.sqlite3"
    assert settings.retention.summary_retention_days == 365
    assert settings.password_protection.session_timeout_minutes == 30


def test_private_settings_template_contains_no_secret_values() -> None:
    template = private_settings_template()

    assert "password =" not in template.lower()
    assert "token =" not in template.lower()
    assert "MARKET_PRIVATE_UI_PASSWORD_HASH" in template
