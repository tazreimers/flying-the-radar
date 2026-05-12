"""Streamlit app for market PDF insights and daily market briefs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tempfile

from market_pdf_insights.daily_brief_config import (
    DailyBriefConfig,
    describe_daily_brief_sources,
    load_daily_brief_config,
    source_definition_from_config,
    validate_daily_brief_config,
)
from market_pdf_insights.daily_brief_rendering import (
    render_daily_brief_html,
    render_daily_brief_json,
    render_daily_brief_markdown,
)
from market_pdf_insights.daily_brief_runner import DailyBriefOutputPaths, run_daily_brief
from market_pdf_insights.daily_brief_schema import (
    AssetMention,
    BriefSection,
    DailyMarketBrief,
)
from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMSummarizationError,
    OpenAISummaryClient,
    PlaceholderLLMClient,
    SummaryClient,
)
from market_pdf_insights.report_rendering import format_asset, render_markdown_report
from market_pdf_insights.source_policy import SourcePolicyError
from market_pdf_insights.source_registry import default_source_registry
from market_pdf_insights.summarizer import SummarizerConfig, summarize_pdf

PROJECT_ROOT = Path(__file__).parents[2]
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "examples" / "daily_brief_config.toml"
EXAMPLE_BRIEF_PATH = PROJECT_ROOT / "examples" / "daily_market_brief.json"


@dataclass(frozen=True)
class DailyBriefDownload:
    """Download payload for a rendered daily brief."""

    label: str
    file_name: str
    mime: str
    content: str


def main() -> None:
    """Run the Streamlit app."""

    import streamlit as st

    st.set_page_config(page_title="Market Intelligence", layout="wide")
    st.title("Market Intelligence")

    daily_tab, pdf_tab = st.tabs(["Daily Brief", "PDF Report"])
    with daily_tab:
        _render_daily_brief_app()
    with pdf_tab:
        _render_pdf_app()


def load_daily_brief_fixture(path: str | Path = EXAMPLE_BRIEF_PATH) -> DailyMarketBrief:
    """Load a fixture brief for dashboard previews and tests."""

    fixture_path = Path(path)
    return DailyMarketBrief.model_validate_json(fixture_path.read_text(encoding="utf-8"))


def build_daily_brief_downloads(brief: DailyMarketBrief) -> list[DailyBriefDownload]:
    """Build JSON, Markdown, and HTML download payloads."""

    base_name = f"daily-market-brief-{brief.briefing_date.isoformat()}"
    return [
        DailyBriefDownload(
            label="JSON",
            file_name=f"{base_name}.json",
            mime="application/json",
            content=render_daily_brief_json(brief),
        ),
        DailyBriefDownload(
            label="Markdown",
            file_name=f"{base_name}.md",
            mime="text/markdown",
            content=render_daily_brief_markdown(brief),
        ),
        DailyBriefDownload(
            label="HTML",
            file_name=f"{base_name}.html",
            mime="text/html",
            content=render_daily_brief_html(brief),
        ),
    ]


def build_daily_brief_source_rows(config: DailyBriefConfig) -> list[dict[str, str]]:
    """Build source status rows for the dashboard."""

    rows: list[dict[str, str]] = []
    configured_ids: set[str] = set()
    for source in config.sources:
        configured_ids.add(source.source_id)
        definition = source_definition_from_config(source)
        credential_status = (
            ", ".join(source.required_env_vars) if source.required_env_vars else "None"
        )
        rows.append(
            {
                "Source": definition.display_name,
                "Source ID": definition.source_id,
                "Status": "Enabled" if source.enabled else "Disabled",
                "Type": source.kind,
                "Category": definition.category.value,
                "Credentials": credential_status,
                "Compliance Notes": source.terms_notes,
            }
        )

    for source in default_source_registry().sources.values():
        if source.source_id in configured_ids or source.enabled:
            continue
        if source.access_method.value != "disabled":
            continue
        rows.append(
            {
                "Source": source.display_name,
                "Source ID": source.source_id,
                "Status": "Disabled",
                "Type": source.capability.fetch_strategy,
                "Category": source.category.value,
                "Credentials": _credential_label(source.credentials.required_env_vars),
                "Compliance Notes": (
                    "Requires permission, licence, or documented export. "
                    f"{source.terms.terms_notes}"
                ),
            }
        )
    return rows


def build_daily_brief_theme_rows(brief: DailyMarketBrief) -> list[dict[str, str]]:
    """Build table rows for top themes."""

    return [
        {
            "Theme": theme.title,
            "Stance": theme.stance,
            "Summary": theme.summary,
            "Assets": ", ".join(_format_daily_asset(asset) for asset in theme.affected_assets),
            "Citations": ", ".join(citation.citation_id for citation in theme.citations),
        }
        for theme in brief.top_themes
    ]


def build_daily_brief_risk_rows(brief: DailyMarketBrief) -> list[dict[str, str]]:
    """Build table rows for brief risks."""

    return [
        {
            "Severity": risk.severity,
            "Risk": risk.description,
            "Watch": ", ".join(risk.watch_items),
            "Citations": ", ".join(citation.citation_id for citation in risk.citations),
        }
        for risk in brief.risks
    ]


def build_daily_brief_watchlist_rows(brief: DailyMarketBrief) -> list[dict[str, str]]:
    """Build table rows for watchlist impacts."""

    return [
        {
            "Asset": _format_daily_asset(impact.asset),
            "Type": impact.asset.asset_type,
            "Stance": impact.stance,
            "Impact": impact.impact_summary,
            "Drivers": ", ".join(impact.drivers),
            "Citations": ", ".join(citation.citation_id for citation in impact.citations),
        }
        for impact in brief.watchlist_impacts
    ]


def build_daily_brief_citation_rows(brief: DailyMarketBrief) -> list[dict[str, str]]:
    """Build table rows for source citations."""

    return [
        {
            "Citation ID": source.citation_id,
            "Source": source.source_name,
            "Title": source.title or "",
            "URL": source.url or "",
            "Published": source.published_at.isoformat() if source.published_at else "",
            "Terms": source.terms_url or "",
            "Licence Notes": source.licence_notes or "",
        }
        for source in brief.sources
    ]


def build_daily_brief_verification_rows(brief: DailyMarketBrief) -> list[dict[str, str]]:
    """Build table rows for verification flags."""

    return [
        {
            "Priority": flag.priority,
            "Claim": flag.claim,
            "Reason": flag.reason,
            "Suggested Source": flag.suggested_source or "",
            "Citations": ", ".join(citation.citation_id for citation in flag.citations),
        }
        for flag in brief.verification_flags
    ]


def _render_daily_brief_app() -> None:
    """Render the daily public market brief dashboard."""

    import streamlit as st

    control_col, brief_col = st.columns([1, 3], gap="large")

    with control_col:
        st.subheader("Run")
        config_text = st.text_input(
            "Config",
            value=str(EXAMPLE_CONFIG_PATH),
            key="daily_config_path",
        )
        briefing_date = st.date_input("Date", value=date.today(), key="daily_brief_date")
        backend = st.selectbox(
            "LLM",
            options=["placeholder", "openai"],
            index=0,
            key="daily_llm",
        )
        model = st.text_input(
            "Model",
            value="gpt-4.1-mini",
            disabled=backend != "openai",
            key="daily_model",
        )
        run_clicked = st.button("Run Brief", type="primary", key="daily_run")
        fixture_clicked = st.button("Load Fixture", key="daily_fixture")

        config = _load_config_for_dashboard(config_text)
        if config is not None:
            errors = validate_daily_brief_config(config)
            if errors:
                st.error("\n".join(errors))
            st.subheader("Source Status")
            st.dataframe(
                build_daily_brief_source_rows(config),
                use_container_width=True,
                hide_index=True,
            )
            for line in describe_daily_brief_sources(config):
                st.caption(line)

    if fixture_clicked:
        try:
            st.session_state["daily_brief"] = load_daily_brief_fixture()
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    if run_clicked and config is not None:
        try:
            with st.spinner("Running daily brief..."):
                result = run_daily_brief(
                    config,
                    briefing_date=briefing_date,
                    output_paths=DailyBriefOutputPaths(),
                    llm_backend=backend,
                    model=model or None,
                )
            st.session_state["daily_brief"] = result.brief
            st.session_state["daily_brief_run"] = result
        except (
            LLMConfigurationError,
            LLMSummarizationError,
            OSError,
            SourcePolicyError,
            ValueError,
        ) as exc:
            st.error(str(exc))

    brief = st.session_state.get("daily_brief")
    if not isinstance(brief, DailyMarketBrief) and EXAMPLE_BRIEF_PATH.exists():
        brief = load_daily_brief_fixture()

    with brief_col:
        if isinstance(brief, DailyMarketBrief):
            _render_daily_brief(brief)
        else:
            st.info("No daily brief loaded.")


def _render_pdf_app() -> None:
    """Render the existing PDF report workflow."""

    import streamlit as st

    control_col, report_col = st.columns([1, 3], gap="large")
    with control_col:
        st.subheader("Run")
        uploaded_file = st.file_uploader("PDF", type=["pdf"], key="pdf_upload")
        backend = st.selectbox(
            "LLM",
            options=["placeholder", "openai"],
            index=0,
            key="pdf_llm",
        )
        model = st.text_input(
            "Model",
            value="gpt-4.1-mini",
            disabled=backend != "openai",
            key="pdf_model",
        )
        max_chars = st.number_input(
            "Max chars",
            min_value=1_000,
            max_value=30_000,
            value=6_000,
            step=500,
            key="pdf_max_chars",
        )
        summarize_clicked = st.button(
            "Summarize",
            type="primary",
            disabled=uploaded_file is None,
            key="pdf_summarize",
        )

    if summarize_clicked:
        try:
            with st.spinner("Summarizing PDF..."):
                client = _build_summary_client(backend=backend, model=model)
                summary = summarize_uploaded_pdf(
                    uploaded_file.getvalue(),
                    filename=uploaded_file.name,
                    client=client,
                    config=SummarizerConfig(max_chunk_chars=int(max_chars)),
                )
            st.session_state["pdf_summary"] = summary
        except (LLMConfigurationError, LLMSummarizationError, OSError, ValueError) as exc:
            st.error(str(exc))

    with report_col:
        summary = st.session_state.get("pdf_summary")
        if isinstance(summary, MarketInsightReport):
            _render_summary(summary)
        else:
            st.info("No report loaded.")


def summarize_uploaded_pdf(
    pdf_bytes: bytes,
    *,
    filename: str,
    client: SummaryClient,
    config: SummarizerConfig,
) -> MarketInsightReport:
    """Write uploaded bytes to a temporary PDF and summarize it."""

    if not pdf_bytes:
        raise ValueError("Uploaded PDF is empty.")

    suffix = Path(filename).suffix
    if suffix.lower() != ".pdf":
        suffix = ".pdf"

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / f"uploaded{suffix}"
        pdf_path.write_bytes(pdf_bytes)
        return summarize_pdf(pdf_path, client=client, config=config)


def _build_summary_client(*, backend: str, model: str) -> SummaryClient:
    """Build the selected summary client."""

    if backend == "placeholder":
        return PlaceholderLLMClient()
    if backend == "openai":
        return OpenAISummaryClient(model=model or None)
    raise ValueError(f"Unsupported LLM backend: {backend}")


def _render_summary(summary: MarketInsightReport) -> None:
    """Render a completed summary in Streamlit."""

    import streamlit as st

    st.divider()
    stance_col, confidence_col, model_col = st.columns(3)
    stance_col.metric("Market stance", summary.market_stance)
    confidence_col.metric("Confidence", f"{summary.confidence_score:.2f}")
    model_col.metric("Model", str(summary.metadata.get("model", "unknown")))

    st.subheader("Executive Summary")
    st.write(summary.executive_summary)

    if summary.investment_thesis:
        st.subheader("Investment Thesis")
        st.write(summary.investment_thesis)

    left_col, right_col = st.columns(2)
    with left_col:
        _render_bullets("Key Claims", [claim.claim for claim in summary.key_claims])
        _render_bullets("Bullish Points", summary.bullish_arguments)
        _render_bullets(
            "Mentioned Assets",
            [format_asset(asset) for asset in summary.companies_or_tickers_mentioned],
        )
    with right_col:
        _render_bullets("Bearish Risks", [risk.description for risk in summary.risks])
        _render_bullets(
            "Numbers To Verify",
            [f"{item.number}: {item.context}" for item in summary.numbers_to_verify],
        )

    markdown_report = render_markdown_report(summary)
    download_col, markdown_col = st.columns(2)
    download_col.download_button(
        "JSON",
        data=summary.to_json(),
        file_name="market-insight-report.json",
        mime="application/json",
    )
    markdown_col.download_button(
        "Markdown",
        data=markdown_report,
        file_name="market-insight-report.md",
        mime="text/markdown",
    )


def _render_daily_brief(brief: DailyMarketBrief) -> None:
    """Render a completed daily market brief in Streamlit."""

    import streamlit as st

    stance_col, confidence_col, source_col, flag_col = st.columns(4)
    stance_col.metric("Market stance", brief.market_stance)
    confidence_col.metric("Confidence", f"{brief.confidence_score:.2f}")
    source_col.metric("Sources", len(brief.sources))
    flag_col.metric("Verification flags", len(brief.verification_flags))

    st.subheader("Executive Summary")
    st.write(brief.executive_summary)

    recap_col, ahead_col = st.columns(2)
    with recap_col:
        _render_brief_section("Yesterday Recap", brief.yesterday_recap)
    with ahead_col:
        _render_brief_section("Day Ahead", brief.day_ahead)

    market_col, macro_col = st.columns(2)
    with market_col:
        _render_brief_section("Australia Market", brief.australia_market)
        _render_brief_section("Commodities", brief.commodities)
    with macro_col:
        _render_brief_section("Global Macro", brief.global_macro)
        _render_brief_section("Currencies And Rates", brief.currencies_and_rates)

    _render_table("Top Themes", build_daily_brief_theme_rows(brief))
    _render_table("Risks", build_daily_brief_risk_rows(brief))
    _render_table("Watchlist Impacts", build_daily_brief_watchlist_rows(brief))
    _render_table("Source Citations", build_daily_brief_citation_rows(brief))
    _render_table("Verification Flags", build_daily_brief_verification_rows(brief))

    st.subheader("Disclaimer")
    st.caption(brief.disclaimer)

    download_cols = st.columns(3)
    for column, download in zip(download_cols, build_daily_brief_downloads(brief), strict=True):
        column.download_button(
            download.label,
            data=download.content,
            file_name=download.file_name,
            mime=download.mime,
        )


def _render_brief_section(title: str, section: BriefSection) -> None:
    """Render a brief section."""

    import streamlit as st

    st.subheader(title)
    st.write(section.summary)
    for bullet in section.bullets:
        st.markdown(f"- {bullet}")
    if section.citations:
        citation_ids = ", ".join(citation.citation_id for citation in section.citations)
        st.caption(f"Citations: {citation_ids}")


def _render_table(title: str, rows: list[dict[str, str]]) -> None:
    """Render a data table with a fallback empty state."""

    import streamlit as st

    st.subheader(title)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("None found.")


def _render_bullets(title: str, items: Sequence[str]) -> None:
    """Render a heading and bullet list."""

    import streamlit as st

    st.subheader(title)
    if not items:
        st.caption("None found.")
        return
    for item in items:
        st.markdown(f"- {item}")


def _load_config_for_dashboard(config_text: str) -> DailyBriefConfig | None:
    """Load dashboard config, returning None when no path is supplied."""

    import streamlit as st

    if not config_text.strip():
        return None
    try:
        return load_daily_brief_config(Path(config_text).expanduser())
    except (OSError, ValueError) as exc:
        st.error(str(exc))
        return None


def _format_daily_asset(asset: AssetMention) -> str:
    if asset.ticker and asset.name:
        return f"{asset.ticker} ({asset.name})"
    if asset.ticker:
        return asset.ticker
    return asset.name or "Unknown"


def _credential_label(env_vars: Sequence[str]) -> str:
    return ", ".join(env_vars) if env_vars else "None"


if __name__ == "__main__":
    main()
