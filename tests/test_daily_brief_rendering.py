from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_pdf_insights.daily_brief_rendering import (
    DailyBriefEmailSettings,
    DryRunDailyBriefEmailWriter,
    build_daily_brief_email_message,
    render_daily_brief_html,
    render_daily_brief_json,
    render_daily_brief_markdown,
    render_daily_brief_plain_text,
    render_daily_brief_terminal_summary,
    save_daily_brief_outputs,
)
from market_pdf_insights.daily_brief_schema import DailyMarketBrief


EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "daily_market_brief.json"


def test_daily_brief_json_renderer_round_trips() -> None:
    brief = _brief()

    rendered = render_daily_brief_json(brief)
    parsed = DailyMarketBrief.model_validate_json(rendered)

    assert parsed.title == brief.title
    assert parsed.sources[0].citation_id == "rba-policy"


def test_daily_brief_markdown_contains_required_sections() -> None:
    rendered = render_daily_brief_markdown(_brief())

    for heading in [
        "# Daily Market Intelligence Brief",
        "## Executive Summary",
        "## Yesterday Recap",
        "## Day Ahead",
        "## Top Themes",
        "## Australia Market",
        "## Global Macro",
        "## Commodities",
        "## Currencies And Rates",
        "## Watchlist Impacts",
        "## Risks",
        "## Sources",
        "## Verification Flags",
        "## Disclaimer",
    ]:
        assert heading in rendered
    assert "`rba-policy`" in rendered
    assert "This briefing summarizes factual market information" in rendered


def test_daily_brief_plain_text_contains_email_sections() -> None:
    rendered = render_daily_brief_plain_text(_brief())

    assert "EXECUTIVE SUMMARY" in rendered
    assert "YESTERDAY RECAP" in rendered
    assert "DAY AHEAD" in rendered
    assert "WATCHLIST IMPACTS" in rendered
    assert "VERIFICATION FLAGS" in rendered
    assert "DISCLAIMER" in rendered
    assert "Citations: rba-policy" in rendered


def test_daily_brief_html_contains_sections_and_escapes_title() -> None:
    brief = _brief().model_copy(update={"title": "Daily <Market> & Rates"})

    rendered = render_daily_brief_html(brief)

    assert "<!doctype html>" in rendered
    assert "Daily &lt;Market&gt; &amp; Rates" in rendered
    assert "<h2>Executive Summary</h2>" in rendered
    assert "<h2>Sources</h2>" in rendered
    assert 'href="#rba-policy"' in rendered
    assert "full article text" in rendered


def test_daily_brief_terminal_summary_is_concise() -> None:
    rendered = render_daily_brief_terminal_summary(
        _brief(),
        saved_paths=["JSON: brief.json", "HTML: brief.html"],
    )

    assert "Daily brief: 2026-05-12" in rendered
    assert "Stance: mixed" in rendered
    assert "Sources: 3" in rendered
    assert "Verification flags: 1" in rendered
    assert "JSON: brief.json" in rendered


def test_save_daily_brief_outputs_writes_all_formats(tmp_path) -> None:
    brief = _brief()

    saved = save_daily_brief_outputs(brief, tmp_path)

    assert set(saved) == {"json", "markdown", "html", "text"}
    assert saved["json"].suffix == ".json"
    assert saved["markdown"].suffix == ".md"
    assert saved["html"].suffix == ".html"
    assert saved["text"].suffix == ".txt"
    assert DailyMarketBrief.model_validate_json(saved["json"].read_text(encoding="utf-8"))
    assert "## Executive Summary" in saved["markdown"].read_text(encoding="utf-8")
    assert "<h2>Sources</h2>" in saved["html"].read_text(encoding="utf-8")
    assert "SOURCES" in saved["text"].read_text(encoding="utf-8")


def test_build_daily_brief_email_message_has_text_and_html_parts() -> None:
    settings = DailyBriefEmailSettings(
        sender="briefs@example.test",
        recipients=["one@example.test", "two@example.test"],
        reply_to="reply@example.test",
    )

    message = build_daily_brief_email_message(_brief(), settings)

    assert message["From"] == "briefs@example.test"
    assert message["To"] == "one@example.test, two@example.test"
    assert message["Reply-To"] == "reply@example.test"
    assert message["Subject"].startswith("Daily Market Brief: 2026-05-12")
    assert message.is_multipart()
    parts = list(message.walk())
    assert any(part.get_content_type() == "text/plain" for part in parts)
    assert any(part.get_content_type() == "text/html" for part in parts)


def test_dry_run_email_writer_saves_eml_without_sending(tmp_path) -> None:
    settings = DailyBriefEmailSettings(
        sender="briefs@example.test",
        recipients=["recipient@example.test"],
    )
    writer = DryRunDailyBriefEmailWriter(tmp_path)

    result = writer.send(_brief(), settings)

    assert result.dry_run
    eml_path = result.output_paths["eml"]
    parsed = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
    assert parsed["Subject"].startswith("Daily Market Brief: 2026-05-12")
    assert parsed["To"] == "recipient@example.test"
    assert parsed.is_multipart()


def test_dry_run_email_writer_can_save_html_and_text_parts(tmp_path) -> None:
    settings = DailyBriefEmailSettings(
        sender="briefs@example.test",
        recipients=["recipient@example.test"],
    )
    writer = DryRunDailyBriefEmailWriter(tmp_path, mode="parts", basename="brief")

    result = writer.send(_brief(), settings)

    assert set(result.output_paths) == {"text", "html"}
    assert result.output_paths["text"].name == "brief.txt"
    assert result.output_paths["html"].name == "brief.html"
    assert "EXECUTIVE SUMMARY" in result.output_paths["text"].read_text(encoding="utf-8")
    assert "<h2>Executive Summary</h2>" in result.output_paths["html"].read_text(
        encoding="utf-8"
    )


def test_email_settings_require_recipient() -> None:
    with pytest.raises(ValidationError, match="at least one recipient"):
        DailyBriefEmailSettings(sender="briefs@example.test", recipients=[" "])


def _brief() -> DailyMarketBrief:
    return DailyMarketBrief.model_validate_json(EXAMPLE_PATH.read_text(encoding="utf-8"))
