"""Streamlit app for market PDF insights and daily market briefs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import os
from pathlib import Path
import tempfile
from typing import Any

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
from market_pdf_insights.private_ingestion import (
    PrivateImportResult,
    import_manual_private_text,
    import_private_file,
    import_uploaded_private_pdf,
    private_document_display_rows,
)
from market_pdf_insights.private_research_library import (
    PrivateResearchLibrary,
    PrivateResearchSearchFilters,
)
from market_pdf_insights.private_research_schema import PrivateResearchDocument
from market_pdf_insights.private_research_storage import (
    PrivateRecommendationRecord,
    PrivateResearchStore,
    initialize_private_research_store,
)
from market_pdf_insights.private_research_synthesis import summarize_imported_private_research
from market_pdf_insights.private_settings import (
    PrivateResearchSettings,
    PrivateSettingsError,
    load_private_research_settings,
    verify_private_password,
)
from market_pdf_insights.report_rendering import format_asset, render_markdown_report
from market_pdf_insights.source_policy import SourcePolicyError
from market_pdf_insights.source_registry import default_source_registry
from market_pdf_insights.summarizer import SummarizerConfig, summarize_pdf

PROJECT_ROOT = Path(__file__).parents[2]
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "examples" / "daily_brief_config.toml"
EXAMPLE_BRIEF_PATH = PROJECT_ROOT / "examples" / "daily_market_brief.json"
PRIVATE_RESEARCH_DISCLAIMER = (
    "Private research organization only. Not financial advice. Do not redistribute subscribed "
    "material or generated private summaries."
)


@dataclass(frozen=True)
class DailyBriefDownload:
    """Download payload for a rendered daily brief."""

    label: str
    file_name: str
    mime: str
    content: str


@dataclass(frozen=True)
class PrivateResearchDownload:
    """Download payload for a private structured research summary."""

    label: str
    file_name: str
    mime: str
    content: str


def main() -> None:
    """Run the Streamlit app."""

    import streamlit as st

    st.set_page_config(page_title="Market Intelligence", layout="wide")
    st.title("Market Intelligence")

    daily_tab, pdf_tab, private_tab = st.tabs(["Daily Brief", "PDF Report", "Private Research"])
    with daily_tab:
        _render_daily_brief_app()
    with pdf_tab:
        _render_pdf_app()
    with private_tab:
        _render_private_research_app()


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


def private_ui_authentication_required(settings: PrivateResearchSettings) -> bool:
    """Return whether the private Streamlit tab requires a password."""

    return settings.password_protection.enabled


def resolve_private_ui_password_hash(
    settings: PrivateResearchSettings,
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve the configured password hash without accepting plaintext secrets."""

    if not settings.password_protection.enabled:
        return None
    env = os.environ if environ is None else environ
    env_var = settings.password_protection.password_hash_env_var
    password_hash = env.get(env_var)
    if not password_hash and secrets is not None:
        secret_value = secrets.get(env_var)
        password_hash = str(secret_value) if secret_value else None
    if not password_hash:
        raise PrivateSettingsError(
            f"{env_var} is required when private UI password protection is enabled."
        )
    return password_hash


def verify_private_ui_password(
    password: str,
    settings: PrivateResearchSettings,
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> bool:
    """Verify a submitted private UI password against a configured hash."""

    if not settings.password_protection.enabled:
        return True
    password_hash = resolve_private_ui_password_hash(
        settings,
        environ=environ,
        secrets=secrets,
    )
    return verify_private_password(password, password_hash or "")


def private_ui_session_is_authenticated(
    session_state: Mapping[str, Any],
    settings: PrivateResearchSettings,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a private UI session is currently authenticated."""

    if not settings.password_protection.enabled:
        return True
    authenticated_until = session_state.get("private_authenticated_until")
    if not isinstance(authenticated_until, datetime):
        return False
    reference_time = now or datetime.now(UTC)
    return authenticated_until > reference_time


def mark_private_ui_authenticated(
    session_state: dict[str, Any],
    settings: PrivateResearchSettings,
    *,
    now: datetime | None = None,
) -> None:
    """Mark private UI session authentication until the configured timeout."""

    reference_time = now or datetime.now(UTC)
    session_state["private_authenticated_until"] = reference_time + timedelta(
        minutes=settings.password_protection.session_timeout_minutes
    )


def clear_private_ui_authentication(session_state: dict[str, Any]) -> None:
    """Clear private UI authentication state."""

    session_state.pop("private_authenticated_until", None)


def load_private_dashboard_settings(
    *,
    settings_path: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> PrivateResearchSettings:
    """Load private dashboard settings with an optional local data-dir override."""

    if settings_path:
        settings = load_private_research_settings(Path(settings_path).expanduser())
    else:
        settings = PrivateResearchSettings()
    if data_dir:
        settings = settings.model_copy(update={"local_data_dir": Path(data_dir).expanduser()})
    return settings


def import_private_upload_bytes(
    upload_bytes: bytes,
    *,
    filename: str,
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
    source_name: str = "Under the Radar",
) -> PrivateImportResult:
    """Import uploaded private PDF/email/text bytes through existing importers."""

    if not upload_bytes:
        raise ValueError("Uploaded private file is empty.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return import_uploaded_private_pdf(
            upload_bytes,
            filename=filename,
            settings=settings,
            store=store,
            source_name=source_name,
        )
    with tempfile.TemporaryDirectory() as tmp_dir:
        safe_name = Path(filename).name or "private-upload.txt"
        upload_path = Path(tmp_dir) / safe_name
        upload_path.write_bytes(upload_bytes)
        return import_private_file(
            upload_path,
            settings=settings,
            store=store,
            source_name=source_name,
        )


def summarize_and_index_private_document(
    document_id: str,
    *,
    store: PrivateResearchStore,
) -> PrivateResearchDocument:
    """Summarize an imported private document and index it for library search."""

    summary = summarize_imported_private_research(document_id, store=store)
    PrivateResearchLibrary(store).index_summary(
        summary,
        model=str(summary.metadata.get("model") or "private-placeholder"),
    )
    return summary


def build_private_research_downloads(
    summary: PrivateResearchDocument,
) -> list[PrivateResearchDownload]:
    """Build JSON and Markdown downloads for a private structured summary."""

    base_name = f"private-research-{summary.document_id}"
    return [
        PrivateResearchDownload(
            label="JSON",
            file_name=f"{base_name}.json",
            mime="application/json",
            content=summary.to_json(),
        ),
        PrivateResearchDownload(
            label="Markdown",
            file_name=f"{base_name}.md",
            mime="text/markdown",
            content=render_private_research_markdown(summary),
        ),
    ]


def render_private_research_markdown(summary: PrivateResearchDocument) -> str:
    """Render a source-light private research summary as Markdown."""

    lines = [
        f"# {summary.document_title}",
        "",
        f"Source: {summary.source_name}",
        f"Document ID: {summary.document_id}",
    ]
    if summary.issue_date:
        lines.append(f"Issue date: {summary.issue_date.isoformat()}")
    lines.extend(["", "## Summary", summary.document_summary, "", "## Recommendations"])
    for recommendation in summary.recommendations:
        lines.extend(
            [
                f"### {recommendation.ticker or '-'} {recommendation.company_name}",
                f"- Rating: {recommendation.recommendation}",
            ]
        )
        if recommendation.stated_target_price is not None:
            currency = recommendation.target_price_currency or ""
            lines.append(f"- Target: {currency} {recommendation.stated_target_price:g}".strip())
        if recommendation.thesis:
            lines.append(f"- Thesis: {recommendation.thesis}")
        for risk in recommendation.risks:
            lines.append(f"- Risk: {risk.risk}")
        for catalyst in recommendation.catalysts:
            lines.append(f"- Catalyst: {catalyst.catalyst}")
        lines.append("")
    verification = build_private_verification_rows(summary)
    if verification:
        lines.extend(["## Numbers And Questions To Verify"])
        for row in verification:
            lines.append(f"- {row['Item']}: {row['Context']}")
        lines.append("")
    lines.extend(["## Disclaimer", summary.disclaimer or PRIVATE_RESEARCH_DISCLAIMER])
    return "\n".join(lines).strip() + "\n"


def build_private_document_rows(store: PrivateResearchStore) -> list[dict[str, str]]:
    """Build private document rows for Streamlit display."""

    rows = private_document_display_rows(store.list_documents())
    return [
        {
            "Document ID": row["document_id"],
            "Issue Date": row["issue_date"],
            "Source": row["source"],
            "Title": row["title"],
            "Type": row["source_type"],
            "Filename": row["filename"],
        }
        for row in rows
    ]


def build_private_recommendation_rows(
    records: Sequence[PrivateRecommendationRecord],
) -> list[dict[str, str]]:
    """Build rows for indexed recommendation search results."""

    rows: list[dict[str, str]] = []
    for record in records:
        target = ""
        if record.stated_target_price is not None:
            currency = record.target_price_currency or ""
            target = f"{currency} {record.stated_target_price:g}".strip()
        rows.append(
            {
                "Document ID": record.document_id,
                "Issue Date": record.issue_date.isoformat() if record.issue_date else "",
                "Ticker": record.ticker or "",
                "Company": record.company_name,
                "Rating": record.recommendation,
                "Target": target,
                "Sector": record.sector or "",
                "Confidence": f"{record.confidence_score:.2f}",
            }
        )
    return rows


def build_private_risk_catalyst_rows(
    records: Sequence[PrivateRecommendationRecord],
) -> list[dict[str, str]]:
    """Build rows for risk/catalyst review."""

    rows: list[dict[str, str]] = []
    for record in records:
        for risk in record.risks:
            rows.append(
                {
                    "Ticker": record.ticker or "",
                    "Company": record.company_name,
                    "Type": "Risk",
                    "Item": risk,
                    "Document ID": record.document_id,
                }
            )
        for catalyst in record.catalysts:
            rows.append(
                {
                    "Ticker": record.ticker or "",
                    "Company": record.company_name,
                    "Type": "Catalyst",
                    "Item": catalyst,
                    "Document ID": record.document_id,
                }
            )
    return rows


def build_private_verification_rows(
    summary: PrivateResearchDocument,
) -> list[dict[str, str]]:
    """Build rows for numbers and questions to verify."""

    rows: list[dict[str, str]] = []
    for number in summary.numbers_to_verify:
        rows.append({"Item": number.value, "Context": number.context, "Type": "Number"})
    for recommendation in summary.recommendations:
        for number in recommendation.numbers_to_verify:
            rows.append(
                {
                    "Item": number.value,
                    "Context": f"{recommendation.ticker or recommendation.company_name}: "
                    f"{number.context}",
                    "Type": "Number",
                }
            )
    for question in summary.personal_action_questions:
        rows.append(
            {
                "Item": question.question,
                "Context": question.why_it_matters or "",
                "Type": "Question",
            }
        )
    return rows


def build_private_source_excerpt_rows(
    summary: PrivateResearchDocument,
) -> list[dict[str, str]]:
    """Build short source citation rows from structured private summaries."""

    rows: list[dict[str, str]] = []
    for excerpt in summary.source_excerpts:
        rows.append(
            {
                "Excerpt ID": excerpt.excerpt_id,
                "Document ID": excerpt.document_id,
                "Page": str(excerpt.page_number or ""),
                "Section": excerpt.section or excerpt.location_label or "",
                "Excerpt": excerpt.excerpt or "",
            }
        )
    for recommendation in summary.recommendations:
        excerpt = recommendation.source_citation
        rows.append(
            {
                "Excerpt ID": excerpt.excerpt_id,
                "Document ID": excerpt.document_id,
                "Page": str(excerpt.page_number or ""),
                "Section": excerpt.section or excerpt.location_label or "",
                "Excerpt": excerpt.excerpt or "",
            }
        )
    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[row["Excerpt ID"]] = row
    return list(deduped.values())


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


def _render_private_research_app() -> None:
    """Render private subscribed-research library UI."""

    import streamlit as st

    st.caption(PRIVATE_RESEARCH_DISCLAIMER)
    settings_col, status_col = st.columns([2, 1], gap="large")
    with settings_col:
        settings_path = st.text_input(
            "Private settings TOML",
            value="",
            key="private_settings_path",
            placeholder="Optional path/to/private-settings.toml",
        )
        data_dir = st.text_input(
            "Private data directory",
            value=".private-research",
            key="private_data_dir",
        )
    try:
        settings = load_private_dashboard_settings(
            settings_path=settings_path.strip() or None,
            data_dir=data_dir.strip() or None,
        )
        store = initialize_private_research_store(settings)
    except (OSError, ValueError, PrivateSettingsError) as exc:
        st.error(str(exc))
        return

    with status_col:
        st.metric("Documents", len(store.list_documents()))
        st.metric("Recommendations", len(store.list_recommendations()))

    if not _render_private_password_gate(settings):
        return

    import_tab, library_tab, summaries_tab, detail_tab, history_tab, risks_tab, citations_tab = (
        st.tabs(
            [
                "Import",
                "Library",
                "Summaries",
                "Recommendation",
                "History",
                "Risks",
                "Citations",
            ]
        )
    )
    with import_tab:
        _render_private_import_screen(settings, store)
    with library_tab:
        _render_private_library_screen(store)
    with summaries_tab:
        _render_private_summaries_screen(store)
    with detail_tab:
        _render_private_recommendation_detail_screen(store)
    with history_tab:
        _render_private_history_screen(store)
    with risks_tab:
        _render_private_risks_screen(store)
    with citations_tab:
        _render_private_citations_screen(store)


def _render_private_password_gate(settings: PrivateResearchSettings) -> bool:
    """Render and evaluate the private UI password gate."""

    import streamlit as st

    if not private_ui_authentication_required(settings):
        st.caption("Private password protection is disabled in local settings.")
        return True
    if private_ui_session_is_authenticated(st.session_state, settings):
        if st.button("Lock Private Research", key="private_lock"):
            clear_private_ui_authentication(st.session_state)
            st.rerun()
        return True

    st.subheader("Private Research Locked")
    st.caption("Password hash is read from environment variables or Streamlit secrets.")
    password = st.text_input("Password", type="password", key="private_password")
    if st.button("Unlock", type="primary", key="private_unlock"):
        try:
            if verify_private_ui_password(password, settings, secrets=st.secrets):
                mark_private_ui_authenticated(st.session_state, settings)
                st.rerun()
            else:
                st.error("Invalid password.")
        except PrivateSettingsError as exc:
            st.error(str(exc))
    return False


def _render_private_import_screen(
    settings: PrivateResearchSettings,
    store: PrivateResearchStore,
) -> None:
    """Render upload/manual import and summarization controls."""

    import streamlit as st

    upload_col, manual_col = st.columns(2, gap="large")
    with upload_col:
        st.subheader("Upload")
        source_name = st.text_input(
            "Source",
            value="Under the Radar",
            key="private_upload_source",
        )
        uploaded = st.file_uploader(
            "PDF, saved email, HTML, or text",
            type=["pdf", "txt", "md", "html", "htm", "eml"],
            key="private_upload",
        )
        if st.button("Import Upload", type="primary", disabled=uploaded is None):
            try:
                result = import_private_upload_bytes(
                    uploaded.getvalue(),
                    filename=uploaded.name,
                    settings=settings,
                    store=store,
                    source_name=source_name,
                )
                _show_private_import_result(result)
            except (OSError, ValueError) as exc:
                st.error(str(exc))

    with manual_col:
        st.subheader("Manual Text")
        manual_title = st.text_input("Title", key="private_manual_title")
        manual_text = st.text_area("Text", height=180, key="private_manual_text")
        if st.button("Import Text", disabled=not manual_text.strip()):
            try:
                result = import_manual_private_text(
                    manual_text,
                    settings=settings,
                    store=store,
                    title=manual_title or None,
                )
                _show_private_import_result(result)
            except (OSError, ValueError) as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("Summarize And Index")
    documents = store.list_documents()
    options = {f"{document.title} | {document.document_id}": document for document in documents}
    if not options:
        st.caption("No private documents imported.")
        return
    selected = st.selectbox("Document", options=list(options), key="private_summarize_doc")
    if st.button("Summarize And Index", type="primary"):
        try:
            with st.spinner("Summarizing private document..."):
                summary = summarize_and_index_private_document(
                    options[selected].document_id,
                    store=store,
                )
            st.session_state["private_structured_summary"] = summary
            st.success(f"Indexed {len(summary.recommendations)} recommendation(s).")
        except (OSError, ValueError, PrivateSettingsError) as exc:
            st.error(str(exc))


def _render_private_library_screen(store: PrivateResearchStore) -> None:
    """Render document library and recommendation search."""

    import streamlit as st

    st.subheader("Documents")
    _render_table("Document Library", build_private_document_rows(store))

    st.subheader("Search Recommendations")
    filter_cols = st.columns(6)
    ticker = filter_cols[0].text_input("Ticker", key="private_search_ticker")
    company = filter_cols[1].text_input("Company", key="private_search_company")
    rating = filter_cols[2].text_input("Rating", key="private_search_rating")
    sector = filter_cols[3].text_input("Sector", key="private_search_sector")
    keyword = filter_cols[4].text_input("Risk/catalyst", key="private_search_keyword")
    date_from = filter_cols[5].date_input("From", value=None, key="private_search_from")
    filters = PrivateResearchSearchFilters(
        ticker=ticker or None,
        company=company or None,
        recommendation=rating or None,
        sector=sector or None,
        keyword=keyword or None,
        date_from=date_from if isinstance(date_from, date) else None,
    )
    records = PrivateResearchLibrary(store).search(filters)
    _render_table("Search Results", build_private_recommendation_rows(records))


def _render_private_summaries_screen(store: PrivateResearchStore) -> None:
    """Render latest structured summaries and downloads."""

    import streamlit as st

    records = store.list_structured_summaries()
    if not records:
        st.info("No structured private summaries indexed.")
        return
    selected = st.selectbox(
        "Summary",
        options=[f"{record.summary.document_title} | {record.document_id}" for record in records],
        key="private_summary_select",
    )
    index = [f"{record.summary.document_title} | {record.document_id}" for record in records].index(
        selected
    )
    _render_private_summary(records[index].summary)


def _render_private_recommendation_detail_screen(store: PrivateResearchStore) -> None:
    """Render a focused stock recommendation detail view."""

    import streamlit as st

    records = store.list_recommendations()
    if not records:
        st.info("No indexed recommendations.")
        return
    labels = [_private_record_label(record) for record in records]
    selected = st.selectbox("Recommendation", options=labels, key="private_rec_detail")
    record = records[labels.index(selected)]
    recommendation = record.recommendation_payload
    st.metric("Rating", recommendation.recommendation)
    if recommendation.stated_target_price is not None:
        st.metric(
            "Target",
            f"{recommendation.target_price_currency or ''} "
            f"{recommendation.stated_target_price:g}",
        )
    st.subheader(recommendation.company_name)
    st.write(recommendation.thesis or record.thesis or "No thesis captured.")
    _render_bullets("Risks", [risk.risk for risk in recommendation.risks])
    _render_bullets("Catalysts", [catalyst.catalyst for catalyst in recommendation.catalysts])
    _render_table(
        "Numbers To Verify",
        [
            {
                "Item": item.value,
                "Context": item.context,
                "Suggested Check": item.suggested_check or "",
            }
            for item in recommendation.numbers_to_verify
        ],
    )


def _render_private_history_screen(store: PrivateResearchStore) -> None:
    """Render ticker recommendation history."""

    import streamlit as st

    ticker = st.text_input("Ticker", key="private_history_ticker")
    if not ticker:
        st.caption("Enter a ticker to view history.")
        return
    records = PrivateResearchLibrary(store).recommendation_timeline(ticker)
    _render_table("Ticker History", build_private_recommendation_rows(records))


def _render_private_risks_screen(store: PrivateResearchStore) -> None:
    """Render risk/catalyst and verification screens."""

    records = store.list_recommendations()
    _render_table("Risks And Catalysts", build_private_risk_catalyst_rows(records))
    questions = PrivateResearchLibrary(store).unresolved_verification_questions()
    _render_table(
        "Unresolved Verification Questions",
        [
            {
                "Ticker": question.ticker or "",
                "Company": question.company_name,
                "Question": question.question,
                "Document ID": question.document_id,
            }
            for question in questions
        ],
    )


def _render_private_citations_screen(store: PrivateResearchStore) -> None:
    """Render source excerpts/citations for structured summaries."""

    import streamlit as st

    records = store.list_structured_summaries()
    if not records:
        st.info("No structured summaries indexed.")
        return
    for record in records:
        with st.expander(record.summary.document_title):
            _render_table("Source Citations", build_private_source_excerpt_rows(record.summary))


def _render_private_summary(summary: PrivateResearchDocument) -> None:
    """Render a structured private research summary."""

    import streamlit as st

    st.subheader(summary.document_title)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Recommendations", len(summary.recommendations))
    metric_cols[1].metric("Confidence", f"{summary.confidence_score:.2f}")
    metric_cols[2].metric("Questions", len(summary.personal_action_questions))
    metric_cols[3].metric("Source", summary.source_name)
    st.write(summary.document_summary)
    _render_table(
        "Recommendations",
        build_private_recommendation_rows(
            [
                PrivateRecommendationRecord(
                    document_id=summary.document_id,
                    structured_summary_id="preview",
                    document_title=summary.document_title,
                    source_name=summary.source_name,
                    issue_date=summary.issue_date,
                    generated_at=datetime.now(UTC),
                    recommendation_id=recommendation.recommendation_id,
                    company_name=recommendation.company_name,
                    ticker=recommendation.ticker,
                    exchange=recommendation.exchange,
                    sector=recommendation.sector,
                    recommendation=recommendation.recommendation,
                    source_rating=recommendation.source_rating,
                    stated_target_price=recommendation.stated_target_price,
                    target_price_currency=recommendation.target_price_currency,
                    time_horizon=recommendation.time_horizon,
                    thesis=recommendation.thesis,
                    risks=tuple(risk.risk for risk in recommendation.risks),
                    catalysts=tuple(catalyst.catalyst for catalyst in recommendation.catalysts),
                    verification_questions=(),
                    source_excerpt=recommendation.source_citation,
                    confidence_score=recommendation.confidence_score,
                    recommendation_payload=recommendation,
                )
                for recommendation in summary.recommendations
            ]
        ),
    )
    _render_table("Numbers And Questions To Verify", build_private_verification_rows(summary))
    st.caption(summary.disclaimer or PRIVATE_RESEARCH_DISCLAIMER)
    cols = st.columns(2)
    for column, download in zip(cols, build_private_research_downloads(summary), strict=True):
        column.download_button(
            download.label,
            data=download.content,
            file_name=download.file_name,
            mime=download.mime,
        )


def _show_private_import_result(result: PrivateImportResult) -> None:
    """Show private import results in Streamlit."""

    import streamlit as st

    st.success(f"Imported {result.imported_count}; skipped {result.skipped_count}.")
    for warning in result.warnings:
        st.warning(warning)
    if result.documents:
        st.dataframe(
            private_document_display_rows(result.documents),
            use_container_width=True,
            hide_index=True,
        )


def _private_record_label(record: PrivateRecommendationRecord) -> str:
    issue_date = record.issue_date.isoformat() if record.issue_date else ""
    return (
        f"{record.ticker or '-'} | {record.company_name} | "
        f"{record.recommendation} | {issue_date}"
    )


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
