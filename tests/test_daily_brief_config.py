from __future__ import annotations

import pytest

from market_pdf_insights.daily_brief_config import (
    DailyBriefConfigError,
    describe_daily_brief_sources,
    load_daily_brief_config,
    source_definition_from_config,
    validate_daily_brief_config,
)
from market_pdf_insights.source_policy import SourceAccessMethod
from market_pdf_insights.source_registry import SourceCategory


def test_load_daily_brief_config_resolves_fixture_and_validates(tmp_path) -> None:
    fixture_path = tmp_path / "items.jsonl"
    fixture_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "daily-brief.toml"
    config_path.write_text(_config_toml("items.jsonl"), encoding="utf-8")

    config = load_daily_brief_config(config_path)
    source = config.sources[0]
    definition = source_definition_from_config(source)

    assert config.config_dir == tmp_path
    assert validate_daily_brief_config(config, environ={}) == []
    assert config.watchlist == ("AUD", "BHP")
    assert source.category == SourceCategory.AUSTRALIAN_MARKET
    assert definition.access_method == SourceAccessMethod.USER_UPLOAD


def test_validate_daily_brief_config_reports_missing_fixture(tmp_path) -> None:
    config_path = tmp_path / "daily-brief.toml"
    config_path.write_text(_config_toml("missing.jsonl"), encoding="utf-8")
    config = load_daily_brief_config(config_path)

    errors = validate_daily_brief_config(config, environ={})

    assert errors == [f"source fixture-market fixture does not exist: {tmp_path / 'missing.jsonl'}"]


def test_validate_daily_brief_config_reports_missing_env_var(tmp_path) -> None:
    fixture_path = tmp_path / "items.jsonl"
    fixture_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "daily-brief.toml"
    config_path.write_text(
        _config_toml("items.jsonl", extra_source='required_env_vars = ["NEWSAPI_KEY"]'),
        encoding="utf-8",
    )
    config = load_daily_brief_config(config_path)

    errors = validate_daily_brief_config(config, environ={})

    assert errors == [
        "source fixture-market requires environment variable(s): NEWSAPI_KEY",
    ]


def test_describe_daily_brief_sources_includes_status(tmp_path) -> None:
    fixture_path = tmp_path / "items.jsonl"
    fixture_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "daily-brief.toml"
    config_path.write_text(_config_toml("items.jsonl"), encoding="utf-8")
    config = load_daily_brief_config(config_path)

    lines = describe_daily_brief_sources(config, environ={})

    assert lines == [
        (
            "- fixture-market: Fixture Market "
            f"(local_fixture; australian_market; enabled; fixture: {fixture_path})"
        )
    ]


def test_load_daily_brief_config_rejects_yaml(tmp_path) -> None:
    config_path = tmp_path / "daily-brief.yaml"
    config_path.write_text("sources: []", encoding="utf-8")

    with pytest.raises(DailyBriefConfigError, match="YAML config is not supported"):
        load_daily_brief_config(config_path)


def _config_toml(fixture_path: str, *, extra_source: str = "") -> str:
    return f"""
watchlist = ["AUD", "BHP"]

[regions]
primary_region = "AU"
timezone = "Australia/Perth"
regions = ["AU", "US", "global"]

[llm]
backend = "placeholder"

[email]
sender = "briefs@example.test"
recipients = ["reader@example.test"]

[[sources]]
source_id = "fixture-market"
display_name = "Fixture Market"
kind = "local_fixture"
category = "australian_market"
fixture_path = "{fixture_path}"
terms_notes = "Fixture terms permit local tests."
terms_url = "https://example.test/terms"
{extra_source}
""".strip()
