"""Tests for private subscribed-research synthesis clients."""

from __future__ import annotations

from pathlib import Path
import json
import os
from unittest.mock import patch

import pytest

from market_pdf_insights.private_ingestion import import_manual_private_text
from market_pdf_insights.private_research_schema import PrivateResearchDocument, SourceExcerpt
from market_pdf_insights.private_research_storage import (
    initialize_private_research_store,
)
from market_pdf_insights.private_research_synthesis import (
    OpenAIPrivateResearchClient,
    PlaceholderPrivateResearchClient,
    PrivateResearchChunkNotes,
    PrivateResearchDocumentContext,
    PrivateResearchSummarizerConfig,
    summarize_imported_private_research,
)
from market_pdf_insights.private_settings import PrivateResearchSettings
from market_pdf_insights.llm_client import LLMConfigurationError


class FakeResponse:
    """Minimal Responses API response with output_text."""

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponsesResource:
    """Fake OpenAI responses resource returning queued outputs."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        if not self.outputs:
            raise AssertionError("No fake OpenAI outputs remain.")
        return FakeResponse(self.outputs.pop(0))


class FakeOpenAIClient:
    """Fake OpenAI SDK client exposing responses.create."""

    def __init__(self, outputs: list[str]) -> None:
        self.responses = FakeResponsesResource(outputs)


def test_placeholder_private_summarizer_produces_valid_source_summary(
    tmp_path: Path,
) -> None:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")
    store = initialize_private_research_store(settings)
    import_result = import_manual_private_text(
        """
        Example Resources (EXR.ASX)
        Issue Date: 2026-05-12
        Recommendation: Speculative Buy
        Previous Recommendation: Hold
        Target Price: AUD 1.35
        Time Horizon: 12 months
        Thesis: Project milestones may improve market confidence.
        Bullish: Quarterly updates could support sentiment.
        Bearish: Funding needs remain uncertain.
        Risks: Funding and execution risk.
        Catalysts: Quarterly project update.
        """,
        settings=settings,
        store=store,
        title="Under the Radar EXR Note",
    )
    document_id = import_result.documents[0].document_id

    summary = summarize_imported_private_research(
        document_id,
        store=store,
        client=PlaceholderPrivateResearchClient(),
        config=PrivateResearchSummarizerConfig(max_chunk_chars=500, chunk_overlap=50),
    )

    recommendation = summary.recommendations[0]
    assert isinstance(summary, PrivateResearchDocument)
    assert summary.document_id == document_id
    assert summary.source_name == "Under the Radar"
    assert "The source document" in summary.document_summary
    assert recommendation.company_name == "Example Resources"
    assert recommendation.ticker == "EXR"
    assert recommendation.exchange == "ASX"
    assert recommendation.recommendation == "speculative_buy"
    assert recommendation.stated_target_price == 1.35
    assert recommendation.recommendation_changes[0].previous_rating == "hold"
    assert summary.numbers_to_verify
    assert "not personal financial advice" in summary.disclaimer
    assert "buy" not in summary.personal_action_questions[0].question.lower()
    assert summary.metadata["chunk_count"] >= 1
    assert summary.metadata["model"] == "private-placeholder"


def test_openai_private_client_retries_malformed_json_and_uses_safety_prompts() -> None:
    context = PrivateResearchDocumentContext(
        document_id="private-example-2026-05-12",
        source_name="Under the Radar",
        document_title="Under the Radar Small-Cap Note",
        issue_date="2026-05-12",
        source_type="pdf",
    )
    chunk_notes = PrivateResearchChunkNotes(
        chunk_index=0,
        summary="The source reiterates a speculative buy rating for EXR.",
        recommendation_mentions=["EXR speculative buy"],
        company_mentions=["Example Resources"],
        rating_mentions=["Speculative Buy"],
        source_excerpts=[
            SourceExcerpt(
                excerpt_id="chunk-excerpt",
                document_id=context.document_id,
                source_name=context.source_name,
                document_title=context.document_title,
                page_number=1,
                section="Recommendation",
                excerpt="Speculative buy rating for EXR.",
            )
        ],
        confidence_score=0.7,
    )
    final_document = PrivateResearchDocument.example()
    fake_client = FakeOpenAIClient(
        [
            "not json",
            chunk_notes.model_dump_json(),
            final_document.to_json(indent=None),
        ]
    )
    client = OpenAIPrivateResearchClient(
        model="gpt-private-test",
        openai_client=fake_client,
        max_retries=1,
    )

    summary = client.summarize_chunks(["EXR source chunk"], context=context)

    assert summary.document_id == "private-example-2026-05-12"
    assert summary.metadata["model"] == "gpt-private-test"
    assert summary.metadata["llm_provider"] == "openai"
    assert summary.metadata["note_count"] == 1
    assert len(fake_client.responses.calls) == 3
    assert fake_client.responses.calls[0]["text"] == {"format": {"type": "json_object"}}

    chunk_system_prompt = fake_client.responses.calls[0]["input"][0]["content"]
    final_system_prompt = fake_client.responses.calls[2]["input"][0]["content"]
    for required_phrase in [
        "summarize what",
        "do not generate new buy/sell/hold advice",
        "do not tailor advice",
        "preserve source attribution",
        "general-advice",
        "flag uncertainty",
        "claims needing verification",
    ]:
        assert required_phrase in chunk_system_prompt.lower()
        assert required_phrase in final_system_prompt.lower()

    retry_messages = fake_client.responses.calls[1]["input"]
    assert "invalid JSON" in json.dumps(retry_messages)


def test_openai_private_client_requires_api_key_when_sdk_client_not_injected() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
            OpenAIPrivateResearchClient()
