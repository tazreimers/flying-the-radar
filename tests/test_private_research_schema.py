"""Tests for private stock recommendation schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_pdf_insights.private_research_schema import (
    MAX_SOURCE_EXCERPT_WORDS,
    PersonalActionQuestion,
    PrivateResearchDocument,
    SourceExcerpt,
    StockRecommendation,
    ThesisPoint,
    normalize_recommendation_rating,
)


EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "private_research_document.json"


def test_private_research_document_example_validates_and_serializes() -> None:
    document = PrivateResearchDocument.model_validate_json(
        EXAMPLE_PATH.read_text(encoding="utf-8")
    )
    payload = json.loads(document.to_json())

    assert payload["source_name"] == "Under the Radar"
    assert payload["recommendations"][0]["recommendation"] == "speculative_buy"
    assert payload["recommendations"][0]["ticker"] == "EXR"
    assert payload["recommendations"][0]["source_citation"]["page_number"] == 2
    assert payload["numbers_to_verify"][0]["value"] == "AUD 1.35"
    assert "not personal financial advice" in payload["disclaimer"]


def test_private_research_document_class_example_validates() -> None:
    document = PrivateResearchDocument.example()

    assert document.document_id == "private-example-2026-05-12"
    assert document.recommendations[0].recommendation == "speculative_buy"
    assert "recommendations" in json.loads(PrivateResearchDocument.example_json())


def test_recommendation_rating_normalizes_known_source_labels() -> None:
    assert normalize_recommendation_rating("Speculative Buy") == "speculative_buy"
    assert normalize_recommendation_rating("outperform") == "buy"

    recommendation = StockRecommendation(
        recommendation_id="rec-abc",
        company_name="ABC Holdings",
        ticker=" abc ",
        exchange=" asx ",
        recommendation="Speculative Buy",
        source_citation=_source_excerpt(),
    )

    assert recommendation.recommendation == "speculative_buy"
    assert recommendation.ticker == "ABC"
    assert recommendation.exchange == "ASX"


def test_rejects_malformed_rating_and_confidence_values() -> None:
    with pytest.raises(ValidationError, match="unsupported recommendation rating"):
        StockRecommendation(
            recommendation_id="rec-abc",
            company_name="ABC Holdings",
            recommendation="moonshot",
            source_citation=_source_excerpt(),
        )

    with pytest.raises(ValidationError):
        StockRecommendation(
            recommendation_id="rec-abc",
            company_name="ABC Holdings",
            recommendation="buy",
            source_citation=_source_excerpt(),
            confidence_score=1.2,
        )


def test_source_excerpt_rejects_long_copyrighted_snippets() -> None:
    with pytest.raises(ValidationError, match=f"{MAX_SOURCE_EXCERPT_WORDS} words or fewer"):
        SourceExcerpt(
            excerpt_id="long",
            document_id="private-example",
            source_name="Under the Radar",
            document_title="Synthetic Note",
            excerpt=" ".join(["word"] * (MAX_SOURCE_EXCERPT_WORDS + 1)),
        )


def test_private_document_rejects_source_excerpts_from_other_documents() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    payload["recommendations"][0]["source_citation"]["document_id"] = "other-document"

    with pytest.raises(ValidationError, match="parent document_id"):
        PrivateResearchDocument.model_validate(payload)


def test_bullish_and_bearish_argument_buckets_validate_stance() -> None:
    with pytest.raises(ValidationError, match="bullish_arguments"):
        StockRecommendation(
            recommendation_id="rec-abc",
            company_name="ABC Holdings",
            recommendation="buy",
            bullish_arguments=[
                ThesisPoint(point="Margin pressure is rising.", stance="bearish")
            ],
            source_citation=_source_excerpt(),
        )


def test_personal_action_question_must_remain_a_question_not_trade_instruction() -> None:
    question = PersonalActionQuestion(
        question_id="q-risk",
        question="What downside case would change my view?",
        related_ticker="abc",
    )

    assert question.related_ticker == "ABC"
    with pytest.raises(ValidationError, match="framed as questions"):
        PersonalActionQuestion(question_id="q-bad", question="Review position size")
    with pytest.raises(ValidationError, match="must not instruct"):
        PersonalActionQuestion(question_id="q-trade", question="Should I buy ABC?")


def _source_excerpt() -> SourceExcerpt:
    return SourceExcerpt(
        excerpt_id="excerpt-1",
        document_id="private-example",
        source_name="Under the Radar",
        document_title="Synthetic Note",
        page_number=1,
        section="Recommendation",
        excerpt="Short paraphrase of the source rating.",
    )
