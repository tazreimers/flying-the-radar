"""Tests for market-intelligence source policy guardrails."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from market_pdf_insights.source_policy import (
    DEFAULT_GUARDRAILS,
    AdviceBoundary,
    SourceAccessMethod,
    SourceAttribution,
    SourcePolicyError,
    SourceUsePolicy,
)


class SourcePolicyTests(unittest.TestCase):
    """Coverage for compliant source-use guardrails."""

    def test_enabled_api_source_can_be_fetched_when_automation_is_allowed(self) -> None:
        policy = SourceUsePolicy(
            source_id="RBA API",
            display_name="Reserve Bank of Australia API",
            access_method=SourceAccessMethod.API,
            enabled=True,
            automation_allowed=True,
            homepage_url="https://www.rba.gov.au/",
            terms_notes="Official API or feed access configured for factual macro data.",
        )

        policy.assert_fetch_allowed()
        self.assertEqual(policy.source_id, "rba-api")

    def test_disabled_source_cannot_be_fetched(self) -> None:
        policy = SourceUsePolicy(
            source_id="tradingview",
            display_name="TradingView",
            access_method=SourceAccessMethod.DISABLED,
            enabled=False,
            terms_notes="Disabled until permitted API, export, or licence is configured.",
        )

        with self.assertRaisesRegex(SourcePolicyError, "disabled"):
            policy.assert_fetch_allowed()

    def test_enabled_automated_source_requires_explicit_automation_permission(self) -> None:
        with self.assertRaisesRegex(ValidationError, "automation_allowed"):
            SourceUsePolicy(
                source_id="example-rss",
                display_name="Example RSS",
                access_method=SourceAccessMethod.RSS,
                enabled=True,
                automation_allowed=False,
                terms_notes="RSS terms have not been reviewed yet.",
            )

    def test_user_supplied_source_is_not_automatic_fetch_source(self) -> None:
        policy = SourceUsePolicy(
            source_id="manual-upload",
            display_name="Manual Upload",
            access_method=SourceAccessMethod.USER_UPLOAD,
            enabled=True,
            automation_allowed=False,
            terms_notes="User supplies files they are entitled to use.",
        )

        self.assertTrue(policy.is_user_supplied)
        with self.assertRaisesRegex(SourcePolicyError, "not an automated fetch"):
            policy.assert_fetch_allowed()

    def test_guardrails_reject_personal_advice_boundary(self) -> None:
        DEFAULT_GUARDRAILS.assert_output_boundary_allowed(AdviceBoundary.FACTUAL_INFORMATION)

        with self.assertRaisesRegex(SourcePolicyError, "not allowed"):
            DEFAULT_GUARDRAILS.assert_output_boundary_allowed(AdviceBoundary.PERSONAL_ADVICE)

    def test_source_attribution_preserves_retrieval_and_terms_metadata(self) -> None:
        attribution = SourceAttribution(
            source_id="rba",
            source_name="Reserve Bank of Australia",
            url="https://www.rba.gov.au/",
            title="Statement on Monetary Policy",
            terms_url="https://www.rba.gov.au/copyright/",
            licence_notes="Preserve attribution and source URL.",
        )

        payload = attribution.model_dump(mode="json")

        self.assertEqual(payload["source_id"], "rba")
        self.assertIn("retrieved_at", payload)
        self.assertEqual(payload["licence_notes"], "Preserve attribution and source URL.")


if __name__ == "__main__":
    unittest.main()

