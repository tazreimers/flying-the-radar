"""Streamlit app for market PDF insights."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import tempfile

from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMSummarizationError,
    OpenAISummaryClient,
    PlaceholderLLMClient,
    SummaryClient,
)
from market_pdf_insights.report_rendering import render_markdown_report
from market_pdf_insights.summarizer import SummarizerConfig, summarize_pdf


def main() -> None:
    """Run the Streamlit app."""

    import streamlit as st

    st.set_page_config(page_title="Market PDF Insights", layout="wide")
    st.title("Market PDF Insights")

    with st.sidebar:
        uploaded_file = st.file_uploader("PDF", type=["pdf"])
        backend = st.selectbox("LLM", options=["placeholder", "openai"], index=0)
        model = st.text_input("Model", value="gpt-4.1-mini", disabled=backend != "openai")
        max_chars = st.number_input(
            "Max chars",
            min_value=1_000,
            max_value=30_000,
            value=6_000,
            step=500,
        )
        summarize_clicked = st.button("Summarize", type="primary", disabled=uploaded_file is None)

    if uploaded_file is None:
        st.info("No report loaded.")
        return

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
            st.session_state["summary"] = summary
        except (LLMConfigurationError, LLMSummarizationError, OSError, ValueError) as exc:
            st.error(str(exc))

    summary = st.session_state.get("summary")
    if isinstance(summary, MarketInsightReport):
        _render_summary(summary)


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
            [_format_asset(asset) for asset in summary.companies_or_tickers_mentioned],
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


def _render_bullets(title: str, items: Sequence[str]) -> None:
    """Render a heading and bullet list."""

    import streamlit as st

    st.subheader(title)
    if not items:
        st.caption("None found.")
        return
    for item in items:
        st.markdown(f"- {item}")


def _format_asset(asset: object) -> str:
    """Format an asset for display."""

    if asset.ticker and asset.name and asset.name != asset.ticker:
        return f"{asset.name} ({asset.ticker})"
    if asset.ticker:
        return asset.ticker
    return str(asset.name)


if __name__ == "__main__":
    main()
