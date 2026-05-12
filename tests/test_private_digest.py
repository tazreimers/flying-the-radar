from __future__ import annotations

from datetime import UTC, date, datetime
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from market_pdf_insights.private_digest import (
    DryRunPrivateDigestEmailWriter,
    PrivateDigestEmailSettings,
    build_private_digest,
    build_private_digest_email_message,
    render_private_digest_html,
    render_private_digest_json,
    render_private_digest_markdown,
    render_private_digest_plain_text,
    save_private_digest_outputs,
    write_private_digest_dry_run_email,
)
from market_pdf_insights.private_ingestion import import_manual_private_text
from market_pdf_insights.private_research_schema import (
    Catalyst,
    NumberToVerify,
    PersonalActionQuestion,
    PrivateResearchDocument,
    RiskPoint,
    SourceExcerpt,
    StockRecommendation,
)
from market_pdf_insights.private_research_storage import (
    PrivateResearchStore,
    initialize_private_research_store,
)
from market_pdf_insights.private_settings import PrivateResearchSettings


def test_private_digest_renderers_include_documents_tickers_changes_and_disclaimer(
    tmp_path: Path,
) -> None:
    store, _, second_id = _seed_digest_library(tmp_path)

    digest = build_private_digest(
        store,
        period="daily",
        as_of=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 22, 0, tzinfo=UTC),
    )

    assert digest.period == "daily"
    assert [summary.document_id for summary in digest.document_summaries] == [second_id]
    assert digest.ticker_summaries[0].ticker == "EXR"
    assert digest.ticker_summaries[0].latest_recommendation == "speculative_buy"
    assert len(digest.recommendation_change_log) == 1
    assert digest.recommendation_change_log[0].summary == (
        "hold -> speculative_buy; target AUD 1 -> AUD 1.35"
    )

    payload = json.loads(render_private_digest_json(digest))
    markdown = render_private_digest_markdown(digest)
    html = render_private_digest_html(digest)
    plain_text = render_private_digest_plain_text(digest)

    assert payload["period"] == "daily"
    assert "# Private Daily Research Digest" in markdown
    assert "## Per-Document Summaries" in markdown
    assert "Under the Radar EXR June" in markdown
    assert "hold -> speculative_buy" in markdown
    assert "<h2>Per-Ticker Summaries</h2>" in html
    assert "not personal financial advice" in html
    assert "RECOMMENDATION CHANGE LOG" in plain_text


def test_private_digest_outputs_and_dry_run_email(tmp_path: Path) -> None:
    store, _, _ = _seed_digest_library(tmp_path)
    digest = build_private_digest(
        store,
        period="weekly",
        as_of=date(2026, 5, 12),
        generated_at=datetime(2026, 5, 12, 22, 0, tzinfo=UTC),
    )

    saved = save_private_digest_outputs(
        digest,
        tmp_path / "outputs",
        basename="private-digest",
        formats=("json", "markdown", "html"),
    )

    assert set(saved) == {"json", "markdown", "html"}
    assert saved["json"].suffix == ".json"
    assert "Private Weekly Research Digest" in saved["markdown"].read_text(encoding="utf-8")
    assert "<h1>Private Weekly Research Digest</h1>" in saved["html"].read_text(
        encoding="utf-8"
    )

    settings = PrivateDigestEmailSettings(
        sender="private@example.test",
        recipients=["reader@example.test"],
        reply_to="reply@example.test",
    )
    message = build_private_digest_email_message(digest, settings)
    assert message["From"] == "private@example.test"
    assert message["To"] == "reader@example.test"
    assert message["Reply-To"] == "reply@example.test"
    assert message["Subject"].startswith("Private Research Digest: 2026-05-06 to 2026-05-12")
    assert message.is_multipart()

    writer = DryRunPrivateDigestEmailWriter(tmp_path / "email")
    result = writer.send(digest, settings)

    assert result.dry_run
    parsed = BytesParser(policy=policy.default).parsebytes(
        result.output_paths["eml"].read_bytes()
    )
    assert parsed["To"] == "reader@example.test"
    assert parsed.is_multipart()


def test_private_digest_dry_run_email_parts_and_validation(tmp_path: Path) -> None:
    store, _, _ = _seed_digest_library(tmp_path)
    digest = build_private_digest(store, period="daily", as_of=date(2026, 5, 12))
    settings = PrivateDigestEmailSettings(
        sender="private@example.test",
        recipients=["reader@example.test"],
    )

    result = write_private_digest_dry_run_email(
        digest,
        settings,
        tmp_path / "email" / "digest.html",
    )

    assert set(result.output_paths) == {"text", "html"}
    assert "PER-DOCUMENT SUMMARIES" in result.output_paths["text"].read_text(
        encoding="utf-8"
    )
    assert "<h2>Per-Document Summaries</h2>" in result.output_paths["html"].read_text(
        encoding="utf-8"
    )

    with pytest.raises(ValidationError, match="at least one recipient"):
        PrivateDigestEmailSettings(sender="private@example.test", recipients=[" "])

    with pytest.raises(ValueError, match="must end in"):
        write_private_digest_dry_run_email(digest, settings, tmp_path / "digest.mail")


def _seed_digest_library(tmp_path: Path) -> tuple[PrivateResearchStore, str, str]:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")
    store = initialize_private_research_store(settings)
    first = import_manual_private_text(
        "Under the Radar EXR May\nIssue Date: 2026-05-10\n\nRecommendation: Hold\nEXR.",
        settings=settings,
        store=store,
        title="Under the Radar EXR May",
    ).documents[0]
    second = import_manual_private_text(
        (
            "Under the Radar EXR June\nIssue Date: 2026-05-12\n\n"
            "Recommendation: Speculative Buy\nEXR."
        ),
        settings=settings,
        store=store,
        title="Under the Radar EXR June",
    ).documents[0]
    store.add_structured_summary(
        _summary(first.document_id, "2026-05-10", "hold", 1.0, "Funding risk."),
        generated_at=datetime(2026, 5, 10, 22, 0, tzinfo=UTC),
    )
    store.add_structured_summary(
        _summary(
            second.document_id,
            "2026-05-12",
            "speculative_buy",
            1.35,
            "Execution risk.",
        ),
        generated_at=datetime(2026, 5, 12, 22, 0, tzinfo=UTC),
    )
    return store, first.document_id, second.document_id


def _summary(
    document_id: str,
    issue_date: str,
    rating: str,
    target: float,
    risk: str,
) -> PrivateResearchDocument:
    recommendation = StockRecommendation(
        recommendation_id=f"rec-exr-{issue_date}",
        company_name="Example Resources",
        ticker="EXR",
        exchange="ASX",
        sector="materials",
        recommendation=rating,
        source_rating=rating.replace("_", " ").title(),
        stated_target_price=target,
        target_price_currency="AUD",
        recommendation_date=issue_date,
        thesis="The source links project delivery to valuation support.",
        risks=[RiskPoint(risk=risk, severity="medium")],
        catalysts=[Catalyst(catalyst="Quarterly update.", direction="positive")],
        numbers_to_verify=[
            NumberToVerify(
                value=f"AUD {target}",
                context="Source target price.",
                suggested_check="Check the original report.",
            )
        ],
        source_citation=SourceExcerpt(
            excerpt_id=f"excerpt-exr-{issue_date}",
            document_id=document_id,
            source_name="Under the Radar",
            document_title=f"Under the Radar EXR {issue_date}",
            section="Recommendation",
            excerpt="Short source-backed rating and target note.",
        ),
        confidence_score=0.7,
    )
    return PrivateResearchDocument(
        document_id=document_id,
        source_name="Under the Radar",
        document_title="Under the Radar EXR June"
        if issue_date == "2026-05-12"
        else "Under the Radar EXR May",
        issue_date=issue_date,
        document_summary="Private source summary for Example Resources.",
        recommendations=[recommendation],
        source_excerpts=[recommendation.source_citation],
        personal_action_questions=[
            PersonalActionQuestion(
                question_id=f"q-{document_id}",
                question="What target price assumption needs checking?",
                related_ticker="EXR",
                related_recommendation_id=recommendation.recommendation_id,
            )
        ],
        confidence_score=0.7,
    )
