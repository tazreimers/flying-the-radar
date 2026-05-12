"""Tests for hosted and mock LLM clients."""

from __future__ import annotations

import json
import os
from unittest.mock import patch
import unittest

from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.llm_client import (
    ChunkInsightNotes,
    LLMConfigurationError,
    MockLLMClient,
    OpenAISummaryClient,
)


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


class LLMClientTests(unittest.TestCase):
    """Coverage for retry and mock client behavior."""

    def test_openai_client_retries_malformed_json_and_returns_report(self) -> None:
        notes = ChunkInsightNotes(
            chunk_index=0,
            summary="ABC delivered earnings growth while inflation remained a risk.",
            key_claims=[
                {
                    "claim": "ABC delivered earnings growth.",
                    "stance": "bullish",
                    "supporting_evidence": ["ABC delivered earnings growth."],
                    "confidence_score": 0.7,
                }
            ],
            supporting_evidence=["ABC delivered earnings growth."],
            risks=[
                {
                    "description": "Inflation remained a risk.",
                    "severity": "medium",
                    "evidence": ["Inflation remained a risk."],
                    "affected_assets": ["ABC"],
                }
            ],
            companies_or_tickers_mentioned=[{"ticker": "ABC"}],
        )
        report = MarketInsightReport.example().model_copy(
            update={"document_title": "Mock Report", "source_file": "source.pdf"}
        )
        fake_client = FakeOpenAIClient(
            [
                "not json",
                notes.model_dump_json(),
                report.to_json(indent=None),
            ]
        )

        client = OpenAISummaryClient(
            model="gpt-test",
            openai_client=fake_client,
            max_retries=1,
        )

        summary = client.summarize_chunks(
            ["ABC earnings growth. Inflation risk."],
            source_file=None,
        )

        self.assertEqual(summary.document_title, "Mock Report")
        self.assertEqual(summary.metadata["model"], "gpt-test")
        self.assertEqual(summary.metadata["llm_provider"], "openai")
        self.assertEqual(summary.metadata["chunk_count"], 1)
        self.assertEqual(len(fake_client.responses.calls), 3)
        self.assertEqual(
            fake_client.responses.calls[0]["text"],
            {"format": {"type": "json_object"}},
        )
        retry_messages = fake_client.responses.calls[1]["input"]
        self.assertIn("invalid JSON", json.dumps(retry_messages))

    def test_openai_client_requires_api_key_when_sdk_client_not_injected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMConfigurationError, "OPENAI_API_KEY"):
                OpenAISummaryClient()

    def test_mock_llm_client_records_chunks(self) -> None:
        client = MockLLMClient()

        report = client.summarize_chunks(["one", "two"], source_file="mock.pdf")

        self.assertEqual(client.calls, [["one", "two"]])
        self.assertEqual(report.source_file, "mock.pdf")
        self.assertEqual(report.metadata["model"], "mock")
        self.assertEqual(report.metadata["chunk_count"], 2)


if __name__ == "__main__":
    unittest.main()
