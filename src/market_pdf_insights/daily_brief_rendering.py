"""Rendering and dry-run email helpers for daily market briefs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from email.message import EmailMessage
from html import escape
from pathlib import Path
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from market_pdf_insights.daily_brief_schema import (
    AssetMention,
    BriefRisk,
    BriefSection,
    CalendarEvent,
    DailyMarketBrief,
    MacroEvent,
    MarketTheme,
    SourceCitation,
    VerificationFlag,
    WatchlistImpact,
)


DailyBriefOutputFormat = Literal["json", "markdown", "html", "text"]
DryRunEmailMode = Literal["eml", "parts"]


class DailyBriefEmailSettings(BaseModel):
    """Configurable email envelope without provider credentials."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sender: str = Field(min_length=1)
    recipients: list[str] = Field(min_length=1)
    subject_prefix: str = "Daily Market Brief"
    reply_to: str | None = None

    @field_validator("recipients")
    @classmethod
    def _validate_recipients(cls, values: list[str]) -> list[str]:
        recipients = [value.strip() for value in values if value.strip()]
        if not recipients:
            raise ValueError("at least one recipient is required")
        return recipients

    def subject_for(self, brief: DailyMarketBrief) -> str:
        """Return the subject for a brief."""

        return f"{self.subject_prefix}: {brief.briefing_date.isoformat()} - {brief.market_stance}"


class EmailSendResult(BaseModel):
    """Result returned by an email sender."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    message_id: str | None = None
    output_paths: dict[str, Path] = Field(default_factory=dict)


class DailyBriefEmailSender(Protocol):
    """Protocol for email senders."""

    def send(self, brief: DailyMarketBrief, settings: DailyBriefEmailSettings) -> EmailSendResult:
        """Send or write a rendered brief."""


class DryRunDailyBriefEmailWriter:
    """Dry-run sender that writes email output locally instead of sending."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        mode: DryRunEmailMode = "eml",
        basename: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.basename = basename

    def send(self, brief: DailyMarketBrief, settings: DailyBriefEmailSettings) -> EmailSendResult:
        """Write `.eml` or text/html parts locally and return their paths."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        basename = self.basename or _brief_basename(brief)
        output_paths: dict[str, Path] = {}

        if self.mode == "eml":
            message = build_daily_brief_email_message(brief, settings)
            eml_path = self.output_dir / f"{basename}.eml"
            eml_path.write_bytes(message.as_bytes())
            output_paths["eml"] = eml_path
        else:
            text_path = self.output_dir / f"{basename}.txt"
            html_path = self.output_dir / f"{basename}.html"
            text_path.write_text(render_daily_brief_plain_text(brief), encoding="utf-8")
            html_path.write_text(render_daily_brief_html(brief), encoding="utf-8")
            output_paths["text"] = text_path
            output_paths["html"] = html_path

        return EmailSendResult(dry_run=True, output_paths=output_paths)


def render_daily_brief_json(brief: DailyMarketBrief, *, indent: int | None = 2) -> str:
    """Render a brief as JSON."""

    return brief.model_dump_json(indent=indent) + "\n"


def render_daily_brief_markdown(brief: DailyMarketBrief) -> str:
    """Render a brief as Markdown."""

    lines = [
        f"# {brief.title}",
        "",
        f"**Briefing date:** {brief.briefing_date.isoformat()}",
        f"**Generated:** {brief.generated_at.isoformat()}",
        f"**Market stance:** {brief.market_stance}",
        f"**Confidence:** {brief.confidence_score:.2f}",
        "",
        "## Executive Summary",
        "",
        brief.executive_summary,
    ]

    _append_markdown_section(lines, "Yesterday Recap", brief.yesterday_recap)
    _append_markdown_section(lines, "Day Ahead", brief.day_ahead)
    _append_markdown_themes(lines, brief.top_themes)
    _append_markdown_section(lines, "Australia Market", brief.australia_market)
    _append_markdown_section(lines, "Global Macro", brief.global_macro)
    _append_markdown_section(lines, "Commodities", brief.commodities)
    _append_markdown_section(lines, "Currencies And Rates", brief.currencies_and_rates)
    _append_markdown_watchlist(lines, brief.watchlist_impacts)
    _append_markdown_calendar(lines, brief.calendar)
    _append_markdown_macro_events(lines, brief.macro_events)
    _append_markdown_risks(lines, brief.risks)
    _append_markdown_verification(lines, brief.verification_flags)
    _append_markdown_sources(lines, brief.sources)
    lines.extend(["", "## Disclaimer", "", brief.disclaimer])

    return "\n".join(lines).strip() + "\n"


def render_daily_brief_plain_text(brief: DailyMarketBrief) -> str:
    """Render a brief as a plain text email body."""

    lines = [
        brief.title,
        "=" * len(brief.title),
        "",
        f"Briefing date: {brief.briefing_date.isoformat()}",
        f"Generated: {brief.generated_at.isoformat()}",
        f"Market stance: {brief.market_stance}",
        f"Confidence: {brief.confidence_score:.2f}",
        "",
        "EXECUTIVE SUMMARY",
        brief.executive_summary,
    ]

    _append_text_section(lines, "YESTERDAY RECAP", brief.yesterday_recap)
    _append_text_section(lines, "DAY AHEAD", brief.day_ahead)
    _append_text_themes(lines, brief.top_themes)
    _append_text_section(lines, "AUSTRALIA MARKET", brief.australia_market)
    _append_text_section(lines, "GLOBAL MACRO", brief.global_macro)
    _append_text_section(lines, "COMMODITIES", brief.commodities)
    _append_text_section(lines, "CURRENCIES AND RATES", brief.currencies_and_rates)
    _append_text_watchlist(lines, brief.watchlist_impacts)
    _append_text_calendar(lines, brief.calendar)
    _append_text_macro_events(lines, brief.macro_events)
    _append_text_risks(lines, brief.risks)
    _append_text_verification(lines, brief.verification_flags)
    _append_text_sources(lines, brief.sources)
    lines.extend(["", "DISCLAIMER", brief.disclaimer])

    return "\n".join(lines).strip() + "\n"


def render_daily_brief_html(brief: DailyMarketBrief) -> str:
    """Render a brief as a standalone HTML email body."""

    body = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(brief.title)}</title>",
        _EMAIL_STYLE,
        "</head>",
        "<body>",
        '<main class="brief">',
        f"<h1>{escape(brief.title)}</h1>",
        '<p class="meta">'
        f"Briefing date: {escape(brief.briefing_date.isoformat())} | "
        f"Generated: {escape(brief.generated_at.isoformat())} | "
        f"Stance: <strong>{escape(brief.market_stance)}</strong> | "
        f"Confidence: <strong>{brief.confidence_score:.2f}</strong>"
        "</p>",
        "<h2>Executive Summary</h2>",
        f"<p>{escape(brief.executive_summary)}</p>",
    ]

    _append_html_section(body, "Yesterday Recap", brief.yesterday_recap)
    _append_html_section(body, "Day Ahead", brief.day_ahead)
    _append_html_themes(body, brief.top_themes)
    _append_html_section(body, "Australia Market", brief.australia_market)
    _append_html_section(body, "Global Macro", brief.global_macro)
    _append_html_section(body, "Commodities", brief.commodities)
    _append_html_section(body, "Currencies And Rates", brief.currencies_and_rates)
    _append_html_watchlist(body, brief.watchlist_impacts)
    _append_html_calendar(body, brief.calendar)
    _append_html_macro_events(body, brief.macro_events)
    _append_html_risks(body, brief.risks)
    _append_html_verification(body, brief.verification_flags)
    _append_html_sources(body, brief.sources)
    body.extend(
        [
            "<h2>Disclaimer</h2>",
            f'<p class="disclaimer">{escape(brief.disclaimer)}</p>',
            "</main>",
            "</body>",
            "</html>",
        ]
    )

    return "\n".join(body) + "\n"


def render_daily_brief_terminal_summary(
    brief: DailyMarketBrief,
    *,
    saved_paths: Sequence[str] = (),
) -> str:
    """Render a concise terminal summary."""

    lines = [
        f"Daily brief: {brief.briefing_date.isoformat()}",
        f"Title: {brief.title}",
        f"Stance: {brief.market_stance}",
        f"Confidence: {brief.confidence_score:.2f}",
        f"Sources: {len(brief.sources)}",
        f"Verification flags: {len(brief.verification_flags)}",
        "",
        f"Executive summary: {brief.executive_summary}",
    ]
    if brief.top_themes:
        lines.extend(["", "Top themes:"])
        lines.extend(f"- {theme.title}" for theme in brief.top_themes[:3])
    if brief.risks:
        lines.extend(["", "Risks:"])
        lines.extend(f"- {risk.description}" for risk in brief.risks[:3])
    if saved_paths:
        lines.extend(["", "Saved:"])
        lines.extend(f"- {path}" for path in saved_paths)
    return "\n".join(lines)


def save_daily_brief_outputs(
    brief: DailyMarketBrief,
    output_dir: str | Path,
    *,
    basename: str | None = None,
    formats: Iterable[DailyBriefOutputFormat] = ("json", "markdown", "html", "text"),
) -> dict[str, Path]:
    """Save selected brief renderings to disk."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    resolved_basename = basename or _brief_basename(brief)
    renderers: Mapping[DailyBriefOutputFormat, tuple[str, str]] = {
        "json": ("json", render_daily_brief_json(brief)),
        "markdown": ("md", render_daily_brief_markdown(brief)),
        "html": ("html", render_daily_brief_html(brief)),
        "text": ("txt", render_daily_brief_plain_text(brief)),
    }

    saved: dict[str, Path] = {}
    for output_format in formats:
        extension, content = renderers[output_format]
        path = output_path / f"{resolved_basename}.{extension}"
        path.write_text(content, encoding="utf-8")
        saved[output_format] = path
    return saved


def build_daily_brief_email_message(
    brief: DailyMarketBrief,
    settings: DailyBriefEmailSettings,
) -> EmailMessage:
    """Build a multipart email message without sending it."""

    message = EmailMessage()
    message["Subject"] = settings.subject_for(brief)
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    if settings.reply_to:
        message["Reply-To"] = settings.reply_to
    message.set_content(render_daily_brief_plain_text(brief))
    message.add_alternative(render_daily_brief_html(brief), subtype="html")
    return message


def _append_markdown_section(lines: list[str], title: str, section: BriefSection) -> None:
    lines.extend(["", f"## {title}", "", section.summary])
    if section.bullets:
        lines.extend([""])
        lines.extend(f"- {bullet}" for bullet in section.bullets)
    _append_markdown_citation_refs(lines, section.citations)


def _append_markdown_themes(lines: list[str], themes: Sequence[MarketTheme]) -> None:
    if not themes:
        return
    lines.extend(["", "## Top Themes", ""])
    for theme in themes:
        lines.append(f"- **{theme.title}:** {theme.summary} _(stance: {theme.stance})_")
        if theme.affected_assets:
            assets = ", ".join(_format_daily_asset(asset) for asset in theme.affected_assets)
            lines.append(f"  Affected: {assets}")
        lines.append(f"  Citations: {_citation_ref_list(theme.citations)}")


def _append_markdown_watchlist(lines: list[str], impacts: Sequence[WatchlistImpact]) -> None:
    if not impacts:
        return
    lines.extend(["", "## Watchlist Impacts", ""])
    for impact in impacts:
        lines.append(
            f"- **{_format_daily_asset(impact.asset)}:** {impact.impact_summary} "
            f"_(stance: {impact.stance})_"
        )
        if impact.drivers:
            lines.append(f"  Drivers: {', '.join(impact.drivers)}")
        lines.append(f"  Citations: {_citation_ref_list(impact.citations)}")


def _append_markdown_calendar(lines: list[str], events: Sequence[CalendarEvent]) -> None:
    if not events:
        return
    lines.extend(["", "## Calendar", ""])
    for event in events:
        detail = f"{event.event_date.isoformat()} - {event.title}"
        if event.region:
            detail += f" ({event.region})"
        if event.time_label:
            detail += f", {event.time_label}"
        lines.append(f"- {detail} [{event.importance}]")
        if event.expected_readthrough:
            lines.append(f"  {event.expected_readthrough}")
        lines.append(f"  Citations: {_citation_ref_list(event.citations)}")


def _append_markdown_macro_events(lines: list[str], events: Sequence[MacroEvent]) -> None:
    if not events:
        return
    lines.extend(["", "## Macro Events", ""])
    for event in events:
        values = _join_present([event.actual, event.forecast, event.previous])
        suffix = f": {values}" if values else ""
        lines.append(f"- **{event.event_name}**{suffix} [{event.importance}]")
        if event.market_readthrough:
            lines.append(f"  {event.market_readthrough}")
        lines.append(f"  Citations: {_citation_ref_list(event.citations)}")


def _append_markdown_risks(lines: list[str], risks: Sequence[BriefRisk]) -> None:
    if not risks:
        return
    lines.extend(["", "## Risks", ""])
    for risk in risks:
        lines.append(f"- **{risk.severity}:** {risk.description}")
        if risk.watch_items:
            lines.append(f"  Watch: {', '.join(risk.watch_items)}")
        lines.append(f"  Citations: {_citation_ref_list(risk.citations)}")


def _append_markdown_verification(
    lines: list[str],
    flags: Sequence[VerificationFlag],
) -> None:
    if not flags:
        return
    lines.extend(["", "## Verification Flags", ""])
    for flag in flags:
        lines.append(f"- **{flag.priority}:** {flag.claim} - {flag.reason}")
        if flag.suggested_source:
            lines.append(f"  Suggested source: {flag.suggested_source}")
        lines.append(f"  Citations: {_citation_ref_list(flag.citations)}")


def _append_markdown_sources(lines: list[str], sources: Sequence[SourceCitation]) -> None:
    lines.extend(["", "## Sources", ""])
    for source in sources:
        lines.append(f"- `{source.citation_id}` {source.source_name}: {_citation_title(source)}")
        if source.url:
            lines.append(f"  {source.url}")
        if source.snippet:
            lines.append(f"  Snippet: {source.snippet}")
        if source.terms_url:
            lines.append(f"  Terms: {source.terms_url}")
        if source.licence_notes:
            lines.append(f"  Licence notes: {source.licence_notes}")


def _append_markdown_citation_refs(
    lines: list[str],
    citations: Sequence[SourceCitation],
) -> None:
    if citations:
        lines.extend(["", f"Citations: {_citation_ref_list(citations)}"])


def _append_text_section(lines: list[str], title: str, section: BriefSection) -> None:
    lines.extend(["", title, section.summary])
    lines.extend(f"- {bullet}" for bullet in section.bullets)
    if section.citations:
        lines.append(f"Citations: {_citation_ref_list(section.citations)}")


def _append_text_themes(lines: list[str], themes: Sequence[MarketTheme]) -> None:
    if not themes:
        return
    lines.extend(["", "TOP THEMES"])
    for theme in themes:
        lines.append(f"- {theme.title}: {theme.summary} (stance: {theme.stance})")
        lines.append(f"  Citations: {_citation_ref_list(theme.citations)}")


def _append_text_watchlist(lines: list[str], impacts: Sequence[WatchlistImpact]) -> None:
    if not impacts:
        return
    lines.extend(["", "WATCHLIST IMPACTS"])
    for impact in impacts:
        lines.append(f"- {_format_daily_asset(impact.asset)}: {impact.impact_summary}")
        if impact.drivers:
            lines.append(f"  Drivers: {', '.join(impact.drivers)}")
        lines.append(f"  Citations: {_citation_ref_list(impact.citations)}")


def _append_text_calendar(lines: list[str], events: Sequence[CalendarEvent]) -> None:
    if not events:
        return
    lines.extend(["", "CALENDAR"])
    for event in events:
        lines.append(f"- {event.event_date.isoformat()} {event.title} [{event.importance}]")
        if event.expected_readthrough:
            lines.append(f"  {event.expected_readthrough}")
        lines.append(f"  Citations: {_citation_ref_list(event.citations)}")


def _append_text_macro_events(lines: list[str], events: Sequence[MacroEvent]) -> None:
    if not events:
        return
    lines.extend(["", "MACRO EVENTS"])
    for event in events:
        lines.append(f"- {event.event_name} [{event.importance}]")
        if event.market_readthrough:
            lines.append(f"  {event.market_readthrough}")
        lines.append(f"  Citations: {_citation_ref_list(event.citations)}")


def _append_text_risks(lines: list[str], risks: Sequence[BriefRisk]) -> None:
    if not risks:
        return
    lines.extend(["", "RISKS"])
    for risk in risks:
        lines.append(f"- {risk.description} [{risk.severity}]")
        if risk.watch_items:
            lines.append(f"  Watch: {', '.join(risk.watch_items)}")
        lines.append(f"  Citations: {_citation_ref_list(risk.citations)}")


def _append_text_verification(lines: list[str], flags: Sequence[VerificationFlag]) -> None:
    if not flags:
        return
    lines.extend(["", "VERIFICATION FLAGS"])
    for flag in flags:
        lines.append(f"- {flag.claim} [{flag.priority}]")
        lines.append(f"  Reason: {flag.reason}")
        if flag.suggested_source:
            lines.append(f"  Suggested source: {flag.suggested_source}")
        lines.append(f"  Citations: {_citation_ref_list(flag.citations)}")


def _append_text_sources(lines: list[str], sources: Sequence[SourceCitation]) -> None:
    lines.extend(["", "SOURCES"])
    for source in sources:
        lines.append(f"- {source.citation_id}: {source.source_name} - {_citation_title(source)}")
        if source.url:
            lines.append(f"  {source.url}")
        if source.terms_url:
            lines.append(f"  Terms: {source.terms_url}")
        if source.licence_notes:
            lines.append(f"  Licence notes: {source.licence_notes}")


def _append_html_section(body: list[str], title: str, section: BriefSection) -> None:
    body.extend([f"<h2>{escape(title)}</h2>", f"<p>{escape(section.summary)}</p>"])
    if section.bullets:
        body.append("<ul>")
        body.extend(f"<li>{escape(bullet)}</li>" for bullet in section.bullets)
        body.append("</ul>")
    _append_html_citation_refs(body, section.citations)


def _append_html_themes(body: list[str], themes: Sequence[MarketTheme]) -> None:
    if not themes:
        return
    body.extend(["<h2>Top Themes</h2>", "<ul>"])
    for theme in themes:
        body.append(
            f"<li><strong>{escape(theme.title)}</strong>: {escape(theme.summary)} "
            f"<span class=\"muted\">({escape(theme.stance)})</span>"
        )
        _append_html_citation_refs(body, theme.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_watchlist(body: list[str], impacts: Sequence[WatchlistImpact]) -> None:
    if not impacts:
        return
    body.extend(["<h2>Watchlist Impacts</h2>", "<ul>"])
    for impact in impacts:
        body.append(
            f"<li><strong>{escape(_format_daily_asset(impact.asset))}</strong>: "
            f"{escape(impact.impact_summary)}"
        )
        if impact.drivers:
            body.append(f'<div class="muted">Drivers: {escape(", ".join(impact.drivers))}</div>')
        _append_html_citation_refs(body, impact.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_calendar(body: list[str], events: Sequence[CalendarEvent]) -> None:
    if not events:
        return
    body.extend(["<h2>Calendar</h2>", "<ul>"])
    for event in events:
        body.append(
            f"<li>{escape(event.event_date.isoformat())} - {escape(event.title)} "
            f"<span class=\"muted\">[{escape(event.importance)}]</span>"
        )
        if event.expected_readthrough:
            body.append(f"<div>{escape(event.expected_readthrough)}</div>")
        _append_html_citation_refs(body, event.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_macro_events(body: list[str], events: Sequence[MacroEvent]) -> None:
    if not events:
        return
    body.extend(["<h2>Macro Events</h2>", "<ul>"])
    for event in events:
        body.append(f"<li><strong>{escape(event.event_name)}</strong>")
        if event.market_readthrough:
            body.append(f"<div>{escape(event.market_readthrough)}</div>")
        _append_html_citation_refs(body, event.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_risks(body: list[str], risks: Sequence[BriefRisk]) -> None:
    if not risks:
        return
    body.extend(["<h2>Risks</h2>", "<ul>"])
    for risk in risks:
        body.append(
            f"<li><strong>{escape(risk.severity)}</strong>: {escape(risk.description)}"
        )
        if risk.watch_items:
            body.append(f'<div class="muted">Watch: {escape(", ".join(risk.watch_items))}</div>')
        _append_html_citation_refs(body, risk.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_verification(body: list[str], flags: Sequence[VerificationFlag]) -> None:
    if not flags:
        return
    body.extend(["<h2>Verification Flags</h2>", "<ul>"])
    for flag in flags:
        body.append(
            f"<li><strong>{escape(flag.priority)}</strong>: {escape(flag.claim)}"
            f"<div>{escape(flag.reason)}</div>"
        )
        _append_html_citation_refs(body, flag.citations)
        body.append("</li>")
    body.append("</ul>")


def _append_html_sources(body: list[str], sources: Sequence[SourceCitation]) -> None:
    body.extend(["<h2>Sources</h2>", "<ol>"])
    for source in sources:
        title = escape(_citation_title(source))
        if source.url:
            title = f'<a href="{escape(source.url, quote=True)}">{title}</a>'
        body.append(
            f'<li id="{escape(source.citation_id)}">'
            f"<code>{escape(source.citation_id)}</code> "
            f"{escape(source.source_name)}: {title}"
        )
        if source.snippet:
            body.append(f'<div class="snippet">{escape(source.snippet)}</div>')
        if source.terms_url:
            body.append(
                f'<div class="muted">Terms: '
                f'<a href="{escape(source.terms_url, quote=True)}">'
                f"{escape(source.terms_url)}</a></div>"
            )
        if source.licence_notes:
            body.append(f'<div class="muted">Licence: {escape(source.licence_notes)}</div>')
        body.append("</li>")
    body.append("</ol>")


def _append_html_citation_refs(body: list[str], citations: Sequence[SourceCitation]) -> None:
    if not citations:
        return
    refs = ", ".join(
        f'<a href="#{escape(citation.citation_id)}">{escape(citation.citation_id)}</a>'
        for citation in citations
    )
    body.append(f'<div class="citations">Citations: {refs}</div>')


def _citation_ref_list(citations: Sequence[SourceCitation]) -> str:
    return ", ".join(citation.citation_id for citation in citations) or "none"


def _citation_title(citation: SourceCitation) -> str:
    return citation.title or citation.url or citation.source_name


def _format_daily_asset(asset: AssetMention) -> str:
    if asset.ticker and asset.name and asset.name != asset.ticker:
        return f"{asset.name} ({asset.ticker})"
    if asset.ticker:
        return asset.ticker
    return str(asset.name)


def _join_present(values: Sequence[str | None]) -> str:
    return ", ".join(value for value in values if value)


def _brief_basename(brief: DailyMarketBrief) -> str:
    raw = f"daily-market-brief-{brief.briefing_date.isoformat()}"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-").lower()


_EMAIL_STYLE = """
<style>
body {
  margin: 0;
  padding: 0;
  background: #f7f7f5;
  color: #202124;
  font-family: Arial, sans-serif;
  line-height: 1.5;
}
.brief {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px;
  background: #ffffff;
}
h1, h2 {
  color: #17202a;
}
.meta, .muted, .citations, .snippet, .disclaimer {
  color: #555f6d;
  font-size: 14px;
}
.snippet {
  margin-top: 4px;
}
a {
  color: #0b57d0;
}
</style>
""".strip()
