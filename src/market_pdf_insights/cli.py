"""Command-line interface for market PDF insights."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from market_pdf_insights.pdf_loader import PdfLoadError
from market_pdf_insights.summarizer import summarize_pdf


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
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of pretty-printed JSON.",
    )
    summarize_parser.set_defaults(func=_handle_summarize)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, PdfLoadError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _handle_summarize(args: argparse.Namespace) -> int:
    """Handle the `summarize` subcommand."""

    summary = summarize_pdf(args.pdf_path)
    print(summary.to_json(indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

