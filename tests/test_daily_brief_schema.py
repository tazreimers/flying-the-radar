from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_pdf_insights.daily_brief_schema import (
    AssetMention,
    BriefSection,
    DailyMarketBrief,
    SourceCitation,
    VerificationFlag,
)


EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "daily_market_brief.json"


def test_daily_market_brief_example_validates_and_serializes() -> None:
    brief = DailyMarketBrief.model_validate_json(EXAMPLE_PATH.read_text(encoding="utf-8"))

    payload = brief.model_dump(mode="json")

    assert payload["briefing_date"] == "2026-05-12"
    assert payload["market_stance"] == "mixed"
    assert len(payload["sources"]) == 3
    assert payload["sources"][0]["citation_id"] == "rba-policy"
    assert "full article text" in payload["sources"][2]["licence_notes"]


def test_source_backed_section_requires_citation() -> None:
    with pytest.raises(ValidationError, match="requires at least one citation"):
        BriefSection(
            title="Rates",
            summary="Rates stayed in focus.",
            bullets=["Cash rate sensitivity remains high."],
        )


def test_non_source_backed_section_can_omit_citations() -> None:
    section = BriefSection(
        title="Editor Note",
        summary="This is a non-source-backed operational note.",
        source_backed=False,
    )

    assert section.citations == []


def test_source_citation_snippet_is_short() -> None:
    with pytest.raises(ValidationError, match="60 words or fewer"):
        SourceCitation(
            citation_id="long-snippet",
            source_id="fixture",
            source_name="Fixture",
            snippet=" ".join(["w"] * 61),
        )


def test_asset_mention_requires_name_or_ticker() -> None:
    with pytest.raises(ValidationError, match="requires at least one of name or ticker"):
        AssetMention(citations=[_citation()])


def test_ticker_is_normalized() -> None:
    asset = AssetMention(
        ticker=" aud ",
        asset_type="currency",
        rationale="Currency watch.",
        citations=[_citation()],
    )

    assert asset.ticker == "AUD"


def test_daily_market_brief_requires_timezone_aware_generation_time() -> None:
    payload = _brief_payload()
    payload["generated_at"] = "2026-05-12T06:30:00"

    with pytest.raises(ValidationError, match="timezone"):
        DailyMarketBrief.model_validate(payload)


def test_daily_market_brief_rejects_invalid_stance_and_confidence() -> None:
    payload = _brief_payload()
    payload["market_stance"] = "optimistic"
    payload["confidence_score"] = 1.2

    with pytest.raises(ValidationError):
        DailyMarketBrief.model_validate(payload)


def test_daily_market_brief_sources_must_catalogue_nested_citations() -> None:
    payload = _brief_payload()
    payload["australia_market"]["citations"] = [
        _citation("missing-id", source_id="fixture-source").model_dump(mode="json")
    ]

    with pytest.raises(ValidationError, match="missing from sources catalogue"):
        DailyMarketBrief.model_validate(payload)


def test_daily_market_brief_rejects_duplicate_source_catalogue_ids() -> None:
    payload = _brief_payload()
    payload["sources"].append(payload["sources"][0])

    with pytest.raises(ValidationError, match="duplicate citation_id"):
        DailyMarketBrief.model_validate(payload)


def test_verification_flag_requires_citation_by_default() -> None:
    with pytest.raises(ValidationError, match="requires at least one citation"):
        VerificationFlag(claim="4.33", reason="Verify macro datapoint.")


def _brief_payload() -> dict:
    citation = _citation()
    citation_payload = citation.model_dump(mode="json")
    section = {
        "title": "Section",
        "summary": "Source-backed market summary.",
        "bullets": ["First point", "First point"],
        "stance": "mixed",
        "citations": [citation_payload],
    }
    asset = {
        "name": "Australian Dollar",
        "ticker": "AUD",
        "asset_type": "currency",
        "stance": "unclear",
        "rationale": "Rate sensitivity.",
        "citations": [citation_payload],
    }
    return {
        "briefing_date": date(2026, 5, 12).isoformat(),
        "generated_at": datetime(2026, 5, 12, 6, 30, tzinfo=UTC).isoformat(),
        "title": "Daily Brief",
        "executive_summary": "Mixed market setup.",
        "yesterday_recap": section,
        "day_ahead": section,
        "market_stance": "mixed",
        "top_themes": [
            {
                "title": "Rates",
                "summary": "Rates remain important.",
                "stance": "mixed",
                "affected_assets": [asset],
                "citations": [citation_payload],
            }
        ],
        "australia_market": section,
        "global_macro": section,
        "commodities": section,
        "currencies_and_rates": section,
        "watchlist_impacts": [
            {
                "asset": asset,
                "impact_summary": "AUD remains rates-sensitive.",
                "stance": "unclear",
                "drivers": ["Rates", "Rates"],
                "citations": [citation_payload],
            }
        ],
        "calendar": [
            {
                "event_date": "2026-05-12",
                "title": "Inflation data",
                "event_type": "economic_release",
                "importance": "high",
                "citations": [citation_payload],
            }
        ],
        "macro_events": [
            {
                "event_name": "Yield observation",
                "indicator": "DGS10",
                "actual": "4.33",
                "importance": "medium",
                "citations": [citation_payload],
            }
        ],
        "risks": [
            {
                "description": "Yield volatility could pressure risk assets.",
                "severity": "medium",
                "affected_assets": [asset],
                "watch_items": ["Yields", "Yields"],
                "citations": [citation_payload],
            }
        ],
        "sources": [citation_payload],
        "verification_flags": [
            {
                "claim": "Yield was 4.33.",
                "reason": "Verify against FRED.",
                "priority": "medium",
                "citations": [citation_payload],
            }
        ],
        "confidence_score": 0.7,
    }


def _citation(
    citation_id: str = "fixture-citation",
    *,
    source_id: str = "fixture-source",
) -> SourceCitation:
    return SourceCitation(
        citation_id=citation_id,
        source_id=source_id,
        source_name="Fixture Source",
        title="Fixture title",
        url="https://example.test/source",
        published_at=datetime(2026, 5, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 5, 12, 6, 30, tzinfo=UTC),
        snippet="Short source snippet.",
        terms_url="https://example.test/terms",
        licence_notes="Fixture terms.",
    )
