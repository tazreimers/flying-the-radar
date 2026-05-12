"""Human-readable rendering helpers for market insight reports."""

from __future__ import annotations

from collections.abc import Sequence

from market_pdf_insights.insight_schema import MarketInsightReport


def render_terminal_summary(
    summary: MarketInsightReport,
    *,
    saved_paths: Sequence[str] = (),
) -> str:
    """Render a concise terminal summary."""

    lines = [
        f"Summary: {summary.document_title}",
        f"Stance: {summary.market_stance}",
        f"Confidence: {summary.confidence_score:.2f}",
        "",
        _wrap_value("Executive summary", summary.executive_summary),
    ]

    if summary.investment_thesis:
        lines.extend(["", _wrap_value("Investment thesis", summary.investment_thesis)])

    _append_section(lines, "Key claims", [claim.claim for claim in summary.key_claims[:3]])
    _append_section(lines, "Risks", [risk.description for risk in summary.risks[:3]])
    _append_section(
        lines,
        "Assets",
        [_format_asset(asset) for asset in summary.companies_or_tickers_mentioned[:8]],
    )
    _append_section(lines, "Saved", list(saved_paths))

    if not saved_paths:
        lines.extend(["", "Saved: not requested. Use --output report.json to save full JSON."])

    return "\n".join(lines)


def render_markdown_report(summary: MarketInsightReport) -> str:
    """Render a Markdown report from a structured summary."""

    lines = [
        f"# {summary.document_title}",
        "",
        f"**Market stance:** {summary.market_stance}",
        f"**Confidence:** {summary.confidence_score:.2f}",
        "",
        "## Executive Summary",
        "",
        summary.executive_summary,
    ]

    if summary.investment_thesis:
        lines.extend(["", "## Investment Thesis", "", summary.investment_thesis])

    _append_markdown_list(lines, "Bullish Arguments", summary.bullish_arguments)
    _append_markdown_list(lines, "Bearish Arguments", summary.bearish_arguments)
    _append_markdown_list(lines, "Valuation Assumptions", summary.valuation_assumptions)
    if summary.time_horizon:
        lines.extend(["", "## Time Horizon", "", summary.time_horizon])
    _append_markdown_list(lines, "Catalysts", summary.catalysts)
    _append_markdown_list(lines, "Key Claims", [claim.claim for claim in summary.key_claims])
    _append_markdown_list(lines, "Risks", [risk.description for risk in summary.risks])
    _append_markdown_list(
        lines,
        "Sectors Mentioned",
        summary.sectors_mentioned,
    )
    _append_markdown_list(
        lines,
        "Assets Mentioned",
        [_format_asset(asset) for asset in summary.companies_or_tickers_mentioned],
    )
    _append_markdown_list(
        lines,
        "Macro Assumptions",
        [assumption.assumption for assumption in summary.macro_assumptions],
    )
    _append_markdown_list(
        lines,
        "Numbers To Verify",
        [f"{item.number}: {item.context}" for item in summary.numbers_to_verify],
    )
    _append_markdown_list(lines, "Unanswered Questions", summary.unanswered_questions)

    return "\n".join(lines).strip() + "\n"


def _append_section(lines: list[str], title: str, items: Sequence[str]) -> None:
    """Append a compact terminal section."""

    if not items:
        return
    lines.extend(["", f"{title}:"])
    lines.extend(f"- {item}" for item in items)


def _append_markdown_list(lines: list[str], title: str, items: Sequence[str]) -> None:
    """Append a Markdown heading and bullet list when items are present."""

    if not items:
        return
    lines.extend(["", f"## {title}", ""])
    lines.extend(f"- {item}" for item in items)


def _wrap_value(label: str, value: str) -> str:
    """Format a labelled value for terminal output."""

    return f"{label}: {value}"


def _format_asset(asset: object) -> str:
    """Format an asset for human-readable output."""

    if asset.ticker and asset.name and asset.name != asset.ticker:
        return f"{asset.name} ({asset.ticker})"
    if asset.ticker:
        return asset.ticker
    return str(asset.name)

