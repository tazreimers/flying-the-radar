"""Command-line interface for market PDF insights."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import os
from pathlib import Path
import sys

from market_pdf_insights.daily_brief_config import (
    DailyBriefConfigError,
    describe_daily_brief_sources,
    load_daily_brief_config,
    validate_daily_brief_config,
)
from market_pdf_insights.daily_brief_rendering import render_daily_brief_terminal_summary
from market_pdf_insights.daily_brief_runner import DailyBriefOutputPaths, run_daily_brief
from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMSummarizationError,
    OpenAISummaryClient,
    PlaceholderLLMClient,
    SummaryClient,
)
from market_pdf_insights.pdf_loader import PdfLoadError
from market_pdf_insights.report_rendering import render_markdown_report, render_terminal_summary
from market_pdf_insights.source_policy import SourcePolicyError
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

    brief_parser = subparsers.add_parser(
        "brief",
        help="Run daily public market brief workflows.",
    )
    brief_subparsers = brief_parser.add_subparsers(dest="brief_command", required=True)

    brief_config_parent = argparse.ArgumentParser(add_help=False)
    brief_config_parent.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a daily brief TOML config.",
    )

    brief_run_parent = argparse.ArgumentParser(add_help=False)
    _add_brief_run_common_args(brief_run_parent)

    brief_run_parser = brief_subparsers.add_parser(
        "run",
        parents=[brief_run_parent],
        help="Ingest configured sources, synthesize a brief, and save outputs.",
    )
    _add_brief_output_args(brief_run_parser)
    brief_run_parser.set_defaults(func=_handle_brief_run)

    brief_sources_parser = brief_subparsers.add_parser(
        "sources",
        parents=[brief_config_parent],
        help="List configured daily brief sources and credential status.",
    )
    brief_sources_parser.set_defaults(func=_handle_brief_sources)

    brief_validate_parser = brief_subparsers.add_parser(
        "validate-config",
        parents=[brief_config_parent],
        help="Validate daily brief configuration.",
    )
    brief_validate_parser.set_defaults(func=_handle_brief_validate_config)

    brief_send_parser = brief_subparsers.add_parser(
        "send",
        parents=[brief_run_parent],
        help="Generate a brief and write dry-run email output.",
    )
    brief_send_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Required. Write email output locally without sending.",
    )
    brief_send_parser.add_argument(
        "--email-dry-run",
        type=Path,
        default=None,
        help="Path for local .eml, .html, or .txt dry-run output.",
    )
    brief_send_parser.set_defaults(func=_handle_brief_send)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        FileNotFoundError,
        PdfLoadError,
        ValueError,
        OSError,
        LLMSummarizationError,
        SourcePolicyError,
    ) as exc:
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


def _handle_brief_run(args: argparse.Namespace) -> int:
    """Handle `brief run`."""

    config = _load_daily_brief_config_from_args(args)
    result = run_daily_brief(
        config,
        briefing_date=_briefing_date(args),
        output_paths=DailyBriefOutputPaths(
            json=args.output,
            markdown=args.markdown,
            html=args.html,
        ),
        email_dry_run_path=args.email_dry_run,
        llm_backend=args.llm,
        model=args.model,
    )
    print(render_daily_brief_terminal_summary(result.brief, saved_paths=_brief_saved_paths(result)))
    return 0


def _handle_brief_sources(args: argparse.Namespace) -> int:
    """Handle `brief sources`."""

    config = _load_daily_brief_config_from_args(args)
    print("Configured daily brief sources:")
    print("\n".join(describe_daily_brief_sources(config)))
    return 0


def _handle_brief_validate_config(args: argparse.Namespace) -> int:
    """Handle `brief validate-config`."""

    config = _load_daily_brief_config_from_args(args)
    errors = validate_daily_brief_config(config)
    if errors:
        print("error: Daily brief config is invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Config valid: {args.config}")
    return 0


def _handle_brief_send(args: argparse.Namespace) -> int:
    """Handle `brief send`."""

    if not args.dry_run:
        raise DailyBriefConfigError("brief send currently supports --dry-run only")
    config = _load_daily_brief_config_from_args(args)
    if args.email_dry_run is None and config.output.email_dry_run is None:
        raise DailyBriefConfigError("provide --email-dry-run or configure output.email_dry_run")
    result = run_daily_brief(
        config,
        briefing_date=_briefing_date(args),
        output_paths=DailyBriefOutputPaths(),
        email_dry_run_path=args.email_dry_run,
        llm_backend=args.llm,
        model=args.model,
    )
    print(render_daily_brief_terminal_summary(result.brief, saved_paths=_brief_saved_paths(result)))
    return 0


def _build_summary_client(args: argparse.Namespace) -> SummaryClient:
    """Build the requested summary client."""

    if args.llm == "placeholder":
        return PlaceholderLLMClient()
    if args.llm == "openai":
        return OpenAISummaryClient(model=args.model)
    raise LLMConfigurationError(f"Unsupported LLM backend: {args.llm}")


def _add_brief_run_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a daily brief TOML config.",
    )
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="Briefing date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--llm",
        choices=("placeholder", "openai"),
        default=None,
        help="Daily brief synthesis backend. Defaults to config llm.backend.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model to use when --llm openai is selected.",
    )


def _add_brief_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to save the full daily brief JSON.",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Path to save a Markdown daily brief.",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="Path to save an HTML daily brief.",
    )
    parser.add_argument(
        "--email-dry-run",
        type=Path,
        default=None,
        help="Path for local .eml, .html, or .txt dry-run output.",
    )


def _load_daily_brief_config_from_args(args: argparse.Namespace):
    config_path = args.config or Path("daily-brief.toml")
    if args.config is None and not config_path.exists():
        raise FileNotFoundError(
            "Daily brief config does not exist: daily-brief.toml. "
            "Pass --config path/to/config.toml."
        )
    return load_daily_brief_config(config_path)


def _briefing_date(args: argparse.Namespace) -> date:
    return args.date or date.today()


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a date in YYYY-MM-DD format") from exc


def _brief_saved_paths(result) -> list[str]:
    labels = {
        "json": "JSON",
        "markdown": "Markdown",
        "html": "HTML",
        "text": "Text",
        "eml": "Email dry-run",
    }
    saved = [f"{labels.get(key, key)}: {path}" for key, path in result.output_paths.items()]
    if result.email_result is not None:
        saved.extend(
            f"{labels.get(key, f'Email {key}')}: {path}"
            for key, path in result.email_result.output_paths.items()
        )
    return saved


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
