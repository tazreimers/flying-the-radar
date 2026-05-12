"""Tests for report rendering helpers."""

from __future__ import annotations

import unittest

from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.report_rendering import render_markdown_report, render_terminal_summary


class ReportRenderingTests(unittest.TestCase):
    """Coverage for human-readable report renderers."""

    def test_terminal_summary_mentions_saved_outputs(self) -> None:
        report = MarketInsightReport.example()

        rendered = render_terminal_summary(report, saved_paths=["JSON: report.json"])

        self.assertIn("Summary: Small-Cap Market Outlook", rendered)
        self.assertIn("Stance: mixed", rendered)
        self.assertIn("JSON: report.json", rendered)
        self.assertIn("EXR", rendered)

    def test_markdown_report_contains_core_sections(self) -> None:
        report = MarketInsightReport.example()

        rendered = render_markdown_report(report)

        self.assertIn("# Small-Cap Market Outlook", rendered)
        self.assertIn("## Executive Summary", rendered)
        self.assertIn("## Bullish Arguments", rendered)
        self.assertIn("## Numbers To Verify", rendered)
        self.assertIn("12%", rendered)


if __name__ == "__main__":
    unittest.main()

