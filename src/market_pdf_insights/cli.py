"""Command-line interface for market PDF insights."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import sys

from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMSummarizationError,
    OpenAISummaryClient,
    PlaceholderLLMClient,
    SummaryClient,
)
from market_pdf_insights.pdf_loader import PdfLoadError
from market_pdf_insights.report_rendering import render_markdown_report, render_terminal_summary
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
        help="Summarize a PDF and save optional JSON or Markdown reports.",
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


if __name__ == "__main__":
    raise SystemExit(main())
