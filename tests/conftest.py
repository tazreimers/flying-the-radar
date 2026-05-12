"""Global pytest safeguards for offline tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def block_live_network_and_real_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests on fixtures, fake clients, and explicit in-test credentials."""

    for env_var in (
        "OPENAI_API_KEY",
        "FRED_API_KEY",
        "NEWSAPI_KEY",
        "UNDERTHERADAR_CONNECTOR_ENABLED",
        "UNDERTHERADAR_USERNAME",
        "UNDERTHERADAR_PASSWORD",
    ):
        monkeypatch.delenv(env_var, raising=False)

    def blocked_urlopen(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Live network access is disabled in tests; use fixtures.")

    monkeypatch.setattr("market_pdf_insights.ingestion.urlopen", blocked_urlopen)
