"""Tests for private research library search, history, and comparison."""

from __future__ import annotations

from pathlib import Path

from market_pdf_insights.private_ingestion import import_manual_private_text
from market_pdf_insights.private_research_library import (
    PrivateResearchLibrary,
    PrivateResearchSearchFilters,
    compare_private_documents,
    latest_private_recommendation,
    private_recommendation_timeline,
    search_private_recommendations,
    unresolved_private_verification_questions,
)
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


def test_private_library_stores_and_searches_recommendations(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_id = _import_document(store, tmp_path, "Under the Radar EXR May Note", "2026-05-01")
    second_id = _import_document(store, tmp_path, "Under the Radar EXR June Note", "2026-06-01")
    library = PrivateResearchLibrary(store)

    library.index_summary(
        _summary(
            first_id,
            issue_date="2026-05-01",
            rating="hold",
            target=1.0,
            risk="Funding risk remains unresolved.",
            catalyst="Quarterly project update.",
        ),
        model="fixture",
    )
    library.index_summary(
        _summary(
            second_id,
            issue_date="2026-06-01",
            rating="speculative_buy",
            target=1.35,
            risk="Execution and licence timing risk.",
            catalyst="Licence approval decision.",
            extra_ticker="XYZ",
        ),
        model="fixture",
    )

    assert len(store.list_structured_summaries()) == 2
    assert len(store.list_recommendations()) == 3
    assert len(search_private_recommendations(store=store, filters=PrivateResearchSearchFilters(ticker="EXR"))) == 2
    assert len(library.search(PrivateResearchSearchFilters(company="example"))) == 2
    assert len(library.search(PrivateResearchSearchFilters(date_from="2026-06-01"))) == 2
    assert len(library.search(PrivateResearchSearchFilters(recommendation="Speculative Buy"))) == 2
    assert len(library.search(PrivateResearchSearchFilters(sector="materials"))) == 3
    assert len(library.search(PrivateResearchSearchFilters(keyword="licence"))) == 1

    latest = latest_private_recommendation("EXR", store=store)
    assert latest is not None
    assert latest.document_id == second_id
    assert latest.recommendation == "speculative_buy"

    timeline = private_recommendation_timeline("EXR", store=store)
    assert [item.document_id for item in timeline] == [first_id, second_id]

    questions = unresolved_private_verification_questions(store=store, ticker="EXR")
    assert any("target price" in question.question.lower() for question in questions)


def test_private_library_compares_documents(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_id = _import_document(store, tmp_path, "Under the Radar EXR May Note", "2026-05-01")
    second_id = _import_document(store, tmp_path, "Under the Radar EXR June Note", "2026-06-01")
    library = PrivateResearchLibrary(store)
    library.index_summary(
        _summary(
            first_id,
            issue_date="2026-05-01",
            rating="hold",
            target=1.0,
            risk="Funding risk remains unresolved.",
            catalyst="Quarterly project update.",
        )
    )
    library.index_summary(
        _summary(
            second_id,
            issue_date="2026-06-01",
            rating="speculative_buy",
            target=1.35,
            risk="Execution and licence timing risk.",
            catalyst="Licence approval decision.",
            extra_ticker="XYZ",
        )
    )

    comparison = compare_private_documents(first_id, second_id, store=store)

    assert comparison.document_a_id == first_id
    assert comparison.document_b_id == second_id
    assert comparison.only_in_a == ()
    assert comparison.only_in_b == ("XYZ",)
    assert len(comparison.changed) == 1
    change = comparison.changed[0]
    assert change.ticker == "EXR"
    assert change.from_recommendation == "hold"
    assert change.to_recommendation == "speculative_buy"
    assert change.from_target_price == 1.0
    assert change.to_target_price == 1.35
    assert comparison.unresolved_questions


def _store(tmp_path: Path) -> PrivateResearchStore:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")
    return initialize_private_research_store(settings)


def _import_document(
    store: PrivateResearchStore,
    tmp_path: Path,
    title: str,
    issue_date: str,
) -> str:
    settings = PrivateResearchSettings(local_data_dir=tmp_path / "private")
    result = import_manual_private_text(
        f"{title}\nIssue Date: {issue_date}\n\nRecommendation: Hold\nEXR update.",
        settings=settings,
        store=store,
        title=title,
    )
    return result.documents[0].document_id


def _summary(
    document_id: str,
    *,
    issue_date: str,
    rating: str,
    target: float,
    risk: str,
    catalyst: str,
    extra_ticker: str | None = None,
) -> PrivateResearchDocument:
    recommendations = [
        _recommendation(
            document_id,
            issue_date=issue_date,
            ticker="EXR",
            company_name="Example Resources",
            rating=rating,
            target=target,
            risk=risk,
            catalyst=catalyst,
        )
    ]
    if extra_ticker is not None:
        recommendations.append(
            _recommendation(
                document_id,
                issue_date=issue_date,
                ticker=extra_ticker,
                company_name="XYZ Holdings",
                rating="speculative_buy",
                target=0.42,
                risk="Customer concentration risk.",
                catalyst="Contract renewal.",
            )
        )
    return PrivateResearchDocument(
        document_id=document_id,
        source_name="Under the Radar",
        document_title=f"Under the Radar {issue_date}",
        issue_date=issue_date,
        source_type="manual_text",
        document_summary="Source summary for indexed private research.",
        recommendations=recommendations,
        source_excerpts=[recommendations[0].source_citation],
        numbers_to_verify=[
            NumberToVerify(
                value=f"AUD {target}",
                context="Source target price.",
                suggested_check="Verify against source PDF.",
                confidence_score=0.7,
            )
        ],
        personal_action_questions=[
            PersonalActionQuestion(
                question_id=f"q-{document_id}",
                question="What target price assumptions need checking?",
                related_ticker="EXR",
                related_recommendation_id=recommendations[0].recommendation_id,
            )
        ],
        confidence_score=0.7,
    )


def _recommendation(
    document_id: str,
    *,
    issue_date: str,
    ticker: str,
    company_name: str,
    rating: str,
    target: float,
    risk: str,
    catalyst: str,
) -> StockRecommendation:
    return StockRecommendation(
        recommendation_id=f"rec-{ticker.lower()}-{issue_date}",
        company_name=company_name,
        ticker=ticker,
        exchange="ASX",
        sector="materials",
        recommendation=rating,
        source_rating=rating.replace("_", " ").title(),
        stated_target_price=target,
        target_price_currency="AUD",
        recommendation_date=issue_date,
        thesis=f"{ticker} thesis from the source.",
        risks=[RiskPoint(risk=risk, severity="medium")],
        catalysts=[Catalyst(catalyst=catalyst, direction="positive")],
        numbers_to_verify=[
            NumberToVerify(
                value=f"AUD {target}",
                context="Recommendation target price.",
                suggested_check="Check source document.",
            )
        ],
        source_citation=SourceExcerpt(
            excerpt_id=f"excerpt-{ticker.lower()}-{issue_date}",
            document_id=document_id,
            source_name="Under the Radar",
            document_title=f"Under the Radar {issue_date}",
            section="Recommendation",
            excerpt=f"{ticker} source rating and target price.",
        ),
        confidence_score=0.7,
    )
