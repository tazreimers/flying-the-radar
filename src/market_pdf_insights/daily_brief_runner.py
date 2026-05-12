"""Operational runner for configured daily market briefs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from market_pdf_insights.daily_brief_config import (
    DailyBriefConfig,
    DailyBriefConfigError,
    assert_daily_brief_config_valid,
    resolve_config_path,
    source_definition_from_config,
)
from market_pdf_insights.daily_brief_rendering import (
    DryRunDailyBriefEmailWriter,
    EmailSendResult,
    render_daily_brief_html,
    render_daily_brief_json,
    render_daily_brief_markdown,
    render_daily_brief_plain_text,
)
from market_pdf_insights.daily_brief_schema import DailyMarketBrief
from market_pdf_insights.daily_brief_synthesis import (
    DailyBriefSynthesisClient,
    MockDailyBriefLLMClient,
    OpenAIDailyBriefClient,
)
from market_pdf_insights.ingestion import (
    IngestionRun,
    IngestionRunner,
    JsonAPIConnector,
    JsonlMarketItemStore,
    LocalFixtureConnector,
    MarketSourceConnector,
    NormalizedMarketItem,
    RSSFeedConnector,
    deduplicate_items,
)

DailyBriefOutputKey = Literal["json", "markdown", "html", "text"]


@dataclass(frozen=True)
class DailyBriefOutputPaths:
    """Optional direct output paths for rendered daily briefs."""

    json: Path | None = None
    markdown: Path | None = None
    html: Path | None = None
    text: Path | None = None


@dataclass(frozen=True)
class DailyBriefRunResult:
    """Result of a configured daily brief run."""

    ingestion_run: IngestionRun
    brief: DailyMarketBrief
    output_paths: dict[str, Path] = field(default_factory=dict)
    email_result: EmailSendResult | None = None


def run_daily_brief(
    config: DailyBriefConfig,
    *,
    briefing_date: date,
    output_paths: DailyBriefOutputPaths | None = None,
    email_dry_run_path: Path | None = None,
    llm_backend: Literal["placeholder", "openai"] | None = None,
    model: str | None = None,
) -> DailyBriefRunResult:
    """Run ingestion, synthesize a brief, save outputs, and optionally write dry-run email."""

    assert_daily_brief_config_valid(
        config,
        require_email=email_dry_run_path is not None,
    )
    connectors = build_daily_brief_connectors(config)
    store = _build_store(config)
    since = _since_for_briefing_date(briefing_date, lookback_hours=config.ingestion.lookback_hours)
    ingestion_run = IngestionRunner(connectors, store=store).run(since=since)
    synthesis_items = ingestion_run.items or _fetched_items(ingestion_run)
    if not synthesis_items:
        raise ValueError("No source items were available for daily brief synthesis.")

    client = build_daily_brief_client(config, llm_backend=llm_backend, model=model)
    brief = client.synthesize_brief(
        synthesis_items,
        briefing_date=briefing_date,
        watchlist_terms=config.watchlist,
    )
    saved_outputs = save_daily_brief_configured_outputs(
        brief,
        config,
        output_paths=output_paths or DailyBriefOutputPaths(),
    )
    email_result = None
    resolved_email_path = email_dry_run_path or _resolve_output_path(
        config.output.email_dry_run,
        config,
    )
    if resolved_email_path is not None:
        email_result = write_daily_brief_dry_run_email(brief, config, resolved_email_path)

    return DailyBriefRunResult(
        ingestion_run=ingestion_run,
        brief=brief,
        output_paths=saved_outputs,
        email_result=email_result,
    )


def build_daily_brief_connectors(config: DailyBriefConfig) -> list[MarketSourceConnector]:
    """Build enabled source connectors from daily brief config."""

    connectors: list[MarketSourceConnector] = []
    for source_config in config.enabled_sources:
        source = source_definition_from_config(source_config)
        if source_config.kind == "local_fixture":
            assert source_config.fixture_path is not None
            connectors.append(
                LocalFixtureConnector(
                    source,
                    fixture_path=resolve_config_path(
                        source_config.fixture_path,
                        config.config_dir,
                    ),
                )
            )
        elif source_config.kind == "rss":
            connectors.append(
                RSSFeedConnector(
                    source,
                    feed_url=source_config.feed_url,
                )
            )
        elif source_config.kind == "json_api":
            connectors.append(
                JsonAPIConnector(
                    source,
                    endpoint_url=source_config.endpoint_url,
                    items_path=source_config.items_path,
                )
            )
        else:
            raise DailyBriefConfigError(f"Unsupported source kind: {source_config.kind}")
    return connectors


def build_daily_brief_client(
    config: DailyBriefConfig,
    *,
    llm_backend: Literal["placeholder", "openai"] | None = None,
    model: str | None = None,
) -> DailyBriefSynthesisClient:
    """Build the configured daily brief synthesis client."""

    backend = llm_backend or config.llm.backend
    resolved_model = model or config.llm.model
    if backend == "placeholder":
        return MockDailyBriefLLMClient()
    if backend == "openai":
        return OpenAIDailyBriefClient(model=resolved_model)
    raise DailyBriefConfigError(f"Unsupported daily brief LLM backend: {backend}")


def save_daily_brief_configured_outputs(
    brief: DailyMarketBrief,
    config: DailyBriefConfig,
    *,
    output_paths: DailyBriefOutputPaths,
) -> dict[str, Path]:
    """Save direct file outputs from config and CLI overrides."""

    targets: dict[DailyBriefOutputKey, Path | None] = {
        "json": output_paths.json or _resolve_output_path(config.output.json_path, config),
        "markdown": output_paths.markdown or _resolve_output_path(config.output.markdown, config),
        "html": output_paths.html or _resolve_output_path(config.output.html, config),
        "text": output_paths.text or _resolve_output_path(config.output.text, config),
    }
    renderers = {
        "json": render_daily_brief_json,
        "markdown": render_daily_brief_markdown,
        "html": render_daily_brief_html,
        "text": render_daily_brief_plain_text,
    }
    saved: dict[str, Path] = {}
    for key, path in targets.items():
        if path is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(renderers[key](brief), encoding="utf-8")
        saved[key] = path
    return saved


def write_daily_brief_dry_run_email(
    brief: DailyMarketBrief,
    config: DailyBriefConfig,
    path: Path,
) -> EmailSendResult:
    """Write a dry-run email file without sending."""

    settings = config.email.to_settings()
    suffix = path.suffix.lower()
    if suffix == ".eml":
        writer = DryRunDailyBriefEmailWriter(path.parent, mode="eml", basename=path.stem)
    elif suffix in {".html", ".txt"}:
        writer = DryRunDailyBriefEmailWriter(path.parent, mode="parts", basename=path.stem)
    else:
        raise DailyBriefConfigError(
            "email dry-run path must end in .eml, .html, or .txt"
        )
    return writer.send(brief, settings)


def _build_store(config: DailyBriefConfig) -> JsonlMarketItemStore | None:
    if config.ingestion.cache_path is None:
        return None
    return JsonlMarketItemStore(resolve_config_path(config.ingestion.cache_path, config.config_dir))


def _fetched_items(ingestion_run: IngestionRun) -> list[NormalizedMarketItem]:
    return deduplicate_items(
        item
        for result in ingestion_run.connector_results
        for item in result.normalized_items
    )


def _resolve_output_path(path: Path | None, config: DailyBriefConfig) -> Path | None:
    if path is None:
        return None
    return resolve_config_path(path, config.config_dir)


def _since_for_briefing_date(briefing_date: date, *, lookback_hours: int) -> datetime:
    start = datetime.combine(briefing_date, time.min, tzinfo=UTC)
    return start - timedelta(hours=lookback_hours)
