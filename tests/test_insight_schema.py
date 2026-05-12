"""Tests for the structured insight schema."""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from market_pdf_insights.insight_schema import (
    MarketInsightReport,
    MentionedAsset,
)


class InsightSchemaTests(unittest.TestCase):
    """Coverage for Pydantic validation and JSON helpers."""

    def test_example_report_validates_and_serializes(self) -> None:
        report = MarketInsightReport.example()
        payload = json.loads(report.to_json())

        self.assertEqual(payload["market_stance"], "mixed")
        self.assertIn("document_title", payload)
        self.assertIn("key_claims", payload)
        self.assertIn("numbers_to_verify", payload)

    def test_rejects_invalid_market_stance(self) -> None:
        with self.assertRaises(ValidationError):
            MarketInsightReport.model_validate(
                {
                    "document_title": "Market Note",
                    "executive_summary": "Summary text.",
                    "market_stance": "optimistic",
                    "key_claims": [],
                    "supporting_evidence": ["One source sentence."],
                    "risks": [],
                    "sectors_mentioned": [],
                    "companies_or_tickers_mentioned": [],
                    "macro_assumptions": [],
                    "numbers_to_verify": [],
                    "unanswered_questions": [],
                    "confidence_score": 0.5,
                }
            )

    def test_requires_claim_or_supporting_evidence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "key claim or evidence"):
            MarketInsightReport(
                document_title="Market Note",
                executive_summary="Summary text.",
                market_stance="neutral",
                confidence_score=0.5,
            )

    def test_confidence_score_must_be_between_zero_and_one(self) -> None:
        with self.assertRaises(ValidationError):
            MarketInsightReport(
                document_title="Market Note",
                executive_summary="Summary text.",
                market_stance="neutral",
                supporting_evidence=["Evidence."],
                confidence_score=1.5,
            )

    def test_mentioned_asset_normalizes_ticker_and_requires_identifier(self) -> None:
        asset = MentionedAsset(ticker="abc", asset_type="company", exchange="asx")

        self.assertEqual(asset.ticker, "ABC")
        self.assertEqual(asset.exchange, "ASX")

        with self.assertRaisesRegex(ValidationError, "name or ticker"):
            MentionedAsset()


if __name__ == "__main__":
    unittest.main()
