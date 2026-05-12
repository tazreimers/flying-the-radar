"""Tests for the disabled Under the Radar connector stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_pdf_insights.private_settings import (
    PrivateImportSourceSettings,
    PrivateResearchSettings,
)
from market_pdf_insights.private_undertheradar_connector import (
    UnderTheRadarConnector,
    UnderTheRadarConnectorConfig,
    UnderTheRadarConnectorCredentialError,
    UnderTheRadarConnectorNotEnabledError,
    UnderTheRadarConnectorNotImplementedError,
    UnderTheRadarConnectorPermissionError,
    undertheradar_preferred_access_paths,
)


def test_undertheradar_connector_is_disabled_by_default(tmp_path: Path) -> None:
    connector = UnderTheRadarConnector(
        settings=PrivateResearchSettings(local_data_dir=tmp_path / "private"),
        environ={},
    )

    status = connector.status()

    assert not status.enabled
    assert not status.ready
    assert status.message == "Disabled until UNDERTHERADAR_CONNECTOR_ENABLED=true is set."
    with pytest.raises(
        UnderTheRadarConnectorNotEnabledError,
        match="UNDERTHERADAR_CONNECTOR_ENABLED=true",
    ):
        connector.assert_ready()


def test_undertheradar_connector_requires_private_settings_automation_gate(
    tmp_path: Path,
) -> None:
    connector = UnderTheRadarConnector(
        settings=PrivateResearchSettings(local_data_dir=tmp_path / "private"),
        config=UnderTheRadarConnectorConfig(terms_permission_confirmed=True),
        environ=_fake_enabled_environ(),
    )

    with pytest.raises(UnderTheRadarConnectorPermissionError, match="settings"):
        connector.assert_ready()


def test_undertheradar_connector_requires_connector_terms_confirmation(
    tmp_path: Path,
) -> None:
    connector = UnderTheRadarConnector(
        settings=_automation_enabled_settings(tmp_path),
        environ=_fake_enabled_environ(),
    )

    with pytest.raises(UnderTheRadarConnectorPermissionError, match="terms"):
        connector.assert_ready()


def test_undertheradar_connector_requires_credentials_without_exposing_values(
    tmp_path: Path,
) -> None:
    connector = UnderTheRadarConnector(
        settings=_automation_enabled_settings(tmp_path),
        config=UnderTheRadarConnectorConfig(terms_permission_confirmed=True),
        environ={"UNDERTHERADAR_CONNECTOR_ENABLED": "true"},
    )

    status = connector.status()
    status_json = status.model_dump_json()

    assert not status.ready
    assert "UNDERTHERADAR_USERNAME" not in status_json
    assert "secret-password" not in status_json
    with pytest.raises(UnderTheRadarConnectorCredentialError, match="credentials"):
        connector.assert_ready()


def test_undertheradar_connector_never_performs_live_login_even_when_gated(
    tmp_path: Path,
) -> None:
    connector = UnderTheRadarConnector(
        settings=_automation_enabled_settings(tmp_path),
        config=UnderTheRadarConnectorConfig(terms_permission_confirmed=True),
        environ=_fake_enabled_environ(),
    )

    status = connector.status()

    assert status.ready
    assert "reader@example.test" not in status.model_dump_json()
    assert "secret-password" not in status.model_dump_json()
    with pytest.raises(UnderTheRadarConnectorNotImplementedError, match="No live"):
        connector.import_reports()


def test_undertheradar_preferred_access_paths_favour_user_driven_imports() -> None:
    paths = undertheradar_preferred_access_paths()

    assert any("download PDFs manually" in path for path in paths)
    assert any("forward or save subscriber emails" in path for path in paths)
    assert any("official export" in path for path in paths)


def _automation_enabled_settings(tmp_path: Path) -> PrivateResearchSettings:
    return PrivateResearchSettings(
        local_data_dir=tmp_path / "private",
        import_sources=PrivateImportSourceSettings(
            logged_in_automation=True,
            logged_in_automation_terms_confirmed=True,
        ),
    )


def _fake_enabled_environ() -> dict[str, str]:
    return {
        "UNDERTHERADAR_CONNECTOR_ENABLED": "true",
        "UNDERTHERADAR_USERNAME": "reader@example.test",
        "UNDERTHERADAR_PASSWORD": "secret-password",
    }
