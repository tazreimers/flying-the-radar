"""Command-line interface for market PDF insights."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import sys

from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMSummarizationError,
    OpenAISummaryClient,
    PlaceholderLLMClient,
    SummaryClient,
)
from market_pdf_insights.pdf_loader import PdfLoadError
from market_pdf_insights.summarizer import SummarizerConfig, summarize_pdf


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="market-pdf-insights",
        description="Summarize stock market commentary and financial research PDFs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize_parser = subparsers.add_parser(
        "summarize",
        help="Summarize a PDF and emit structured JSON.",
    )
    summarize_parser.add_argument("pdf_path", type=Path, help="Path to a PDF file.")
    summarize_parser.add_argument(
        "--output",
        type=Path,
        help="Path to save the full structured JSON report.",
    )
    summarize_parser.add_argument(
        "--markdown",
        type=Path,
        help="Path to save a Markdown report.",
    )
    summarize_parser.add_argument(
        "--llm",
        choices=("placeholder", "openai"),
        default=os.environ.get("MARKET_PDF_INSIGHTS_CLIENT", "placeholder"),
        help="LLM backend to use. Defaults to MARKET_PDF_INSIGHTS_CLIENT or placeholder.",
    )
    summarize_parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model to use when --llm openai is selected.",
    )
    summarize_parser.add_argument(
        "--max-chars",
        type=_positive_int,
        default=SummarizerConfig.max_chunk_chars,
        help="Maximum characters per text chunk. Defaults to 6000.",
    )
    summarize_parser.set_defaults(func=_handle_summarize)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, PdfLoadError, ValueError, OSError, LLMSummarizationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _handle_summarize(args: argparse.Namespace) -> int:
    """Handle the `summarize` subcommand."""

    config = SummarizerConfig(max_chunk_chars=args.max_chars)
    summary = summarize_pdf(args.pdf_path, client=_build_summary_client(args), config=config)

    saved_paths: list[str] = []
    if args.output:
        _write_text(args.output, summary.to_json())
        saved_paths.append(f"JSON: {args.output}")
    if args.markdown:
        _write_text(args.markdown, render_markdown_report(summary))
        saved_paths.append(f"Markdown: {args.markdown}")

    print(render_terminal_summary(summary, saved_paths=saved_paths))
    return 0


def _build_summary_client(args: argparse.Namespace) -> SummaryClient:
    """Build the requested summary client."""

    if args.llm == "placeholder":
        return PlaceholderLLMClient()
    if args.llm == "openai":
        return OpenAISummaryClient(model=args.model)
    raise LLMConfigurationError(f"Unsupported LLM backend: {args.llm}")


def render_terminal_summary(
    summary: MarketInsightReport,
    *,
    saved_paths: Sequence[str] = (),
) -> str:
    """Render a concise terminal summary."""

    report = summary
    lines = [
        f"Summary: {report.document_title}",
        f"Stance: {report.market_stance}",
        f"Confidence: {report.confidence_score:.2f}",
        "",
        _wrap_value("Executive summary", report.executive_summary),
    ]

    if report.investment_thesis:
        lines.extend(["", _wrap_value("Investment thesis", report.investment_thesis)])

    _append_section(lines, "Key claims", [claim.claim for claim in report.key_claims[:3]])
    _append_section(lines, "Risks", [risk.description for risk in report.risks[:3]])
    _append_section(
        lines,
        "Assets",
        [_format_asset(asset) for asset in report.companies_or_tickers_mentioned[:8]],
    )
    _append_section(lines, "Saved", list(saved_paths))

    if not saved_paths:
        lines.extend(["", "Saved: not requested. Use --output report.json to save full JSON."])

    return "\n".join(lines)


def render_markdown_report(summary: MarketInsightReport) -> str:
    """Render a Markdown report from a structured summary."""

    report = summary
    lines = [
        f"# {report.document_title}",
        "",
        f"**Market stance:** {report.market_stance}",
        f"**Confidence:** {report.confidence_score:.2f}",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
    ]

    if report.investment_thesis:
        lines.extend(["", "## Investment Thesis", "", report.investment_thesis])

    _append_markdown_list(lines, "Bullish Arguments", report.bullish_arguments)
    _append_markdown_list(lines, "Bearish Arguments", report.bearish_arguments)
    _append_markdown_list(lines, "Valuation Assumptions", report.valuation_assumptions)
    if report.time_horizon:
        lines.extend(["", "## Time Horizon", "", report.time_horizon])
    _append_markdown_list(lines, "Catalysts", report.catalysts)
    _append_markdown_list(lines, "Key Claims", [claim.claim for claim in report.key_claims])
    _append_markdown_list(lines, "Risks", [risk.description for risk in report.risks])
    _append_markdown_list(
        lines,
        "Sectors Mentioned",
        report.sectors_mentioned,
    )
    _append_markdown_list(
        lines,
        "Assets Mentioned",
        [_format_asset(asset) for asset in report.companies_or_tickers_mentioned],
    )
    _append_markdown_list(
        lines,
        "Macro Assumptions",
        [assumption.assumption for assumption in report.macro_assumptions],
    )
    _append_markdown_list(
        lines,
        "Numbers To Verify",
        [f"{item.number}: {item.context}" for item in report.numbers_to_verify],
    )
    _append_markdown_list(lines, "Unanswered Questions", report.unanswered_questions)

    return "\n".join(lines).strip() + "\n"


def _positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _write_text(path: Path, content: str) -> None:
    """Write text to a path, creating parent directories when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


if __name__ == "__main__":
    raise SystemExit(main())
