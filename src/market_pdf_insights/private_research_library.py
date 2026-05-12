"""Private research library search, history, and comparison helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from market_pdf_insights.private_research_schema import (
    PrivateResearchDocument,
    normalize_recommendation_rating,
)
from market_pdf_insights.private_research_storage import (
    PrivateRecommendationRecord,
    PrivateResearchStore,
    PrivateStructuredSummaryRecord,
)


class PrivateResearchSearchFilters(BaseModel):
    """Filters for local private recommendation search."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str | None = None
    company: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    recommendation: str | None = None
    sector: str | None = None
    keyword: str | None = Field(
        default=None,
        description="Keyword searched across thesis, risk, and catalyst fields.",
    )

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value

    @field_validator("recommendation", mode="before")
    @classmethod
    def _normalize_recommendation(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str) or not value.strip():
            return None
        return normalize_recommendation_rating(value)

    @model_validator(mode="after")
    def _validate_date_range(self) -> Self:
        if self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be before or equal to date_to")
        return self


class PrivateVerificationQuestion(BaseModel):
    """Unresolved source-backed verification question from the private library."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str
    document_title: str
    issue_date: date | None = None
    ticker: str | None = None
    company_name: str
    question: str


class PrivateRecommendationDifference(BaseModel):
    """Difference between two recommendation records."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str | None = None
    company_name: str
    from_document_id: str
    to_document_id: str
    from_recommendation: str
    to_recommendation: str
    from_target_price: float | None = None
    to_target_price: float | None = None
    from_risks: tuple[str, ...] = ()
    to_risks: tuple[str, ...] = ()
    from_catalysts: tuple[str, ...] = ()
    to_catalysts: tuple[str, ...] = ()


class PrivateDocumentComparison(BaseModel):
    """Comparison result for two private structured documents."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_a_id: str
    document_b_id: str
    only_in_a: tuple[str, ...] = ()
    only_in_b: tuple[str, ...] = ()
    changed: tuple[PrivateRecommendationDifference, ...] = ()
    unchanged: tuple[str, ...] = ()
    unresolved_questions: tuple[PrivateVerificationQuestion, ...] = ()


class PrivateResearchLibrary:
    """Local private research library over structured summaries and recommendations."""

    def __init__(self, store: PrivateResearchStore) -> None:
        self.store = store

    def index_summary(
        self,
        summary: PrivateResearchDocument,
        *,
        model: str | None = None,
    ) -> PrivateStructuredSummaryRecord:
        """Store a structured summary and refresh recommendation rows for its document."""

        return self.store.add_structured_summary(summary, model=model)

    def search(
        self,
        filters: PrivateResearchSearchFilters | None = None,
    ) -> list[PrivateRecommendationRecord]:
        """Search locally indexed private recommendations."""

        resolved = filters or PrivateResearchSearchFilters()
        records = self.store.list_recommendations()
        return [record for record in records if _matches_filters(record, resolved)]

    def latest_recommendation(self, ticker: str) -> PrivateRecommendationRecord | None:
        """Return the latest recommendation for a ticker."""

        timeline = self.recommendation_timeline(ticker)
        return timeline[-1] if timeline else None

    def recommendation_timeline(self, ticker: str) -> list[PrivateRecommendationRecord]:
        """Return ticker recommendation history in chronological order."""

        filters = PrivateResearchSearchFilters(ticker=ticker)
        records = self.search(filters)
        return sorted(records, key=_timeline_sort_key)

    def compare_documents(
        self,
        document_a_id: str,
        document_b_id: str,
    ) -> PrivateDocumentComparison:
        """Compare recommendation coverage between two private documents."""

        records_a = self.store.list_recommendations(document_id=document_a_id)
        records_b = self.store.list_recommendations(document_id=document_b_id)
        by_key_a = {_record_key(record): record for record in records_a}
        by_key_b = {_record_key(record): record for record in records_b}
        keys_a = set(by_key_a)
        keys_b = set(by_key_b)
        changed = []
        unchanged = []
        for key in sorted(keys_a & keys_b):
            previous = by_key_a[key]
            current = by_key_b[key]
            if _records_differ(previous, current):
                changed.append(_difference(previous, current))
            else:
                unchanged.append(_display_key(current))
        unresolved = [
            *self.unresolved_verification_questions(document_id=document_a_id),
            *self.unresolved_verification_questions(document_id=document_b_id),
        ]
        return PrivateDocumentComparison(
            document_a_id=document_a_id,
            document_b_id=document_b_id,
            only_in_a=tuple(_display_key(by_key_a[key]) for key in sorted(keys_a - keys_b)),
            only_in_b=tuple(_display_key(by_key_b[key]) for key in sorted(keys_b - keys_a)),
            changed=tuple(changed),
            unchanged=tuple(unchanged),
            unresolved_questions=tuple(unresolved),
        )

    def unresolved_verification_questions(
        self,
        *,
        ticker: str | None = None,
        document_id: str | None = None,
    ) -> list[PrivateVerificationQuestion]:
        """Return verification prompts from indexed private recommendations."""

        records = self.store.list_recommendations(document_id=document_id)
        if ticker:
            wanted = ticker.strip().upper()
            records = [record for record in records if record.ticker == wanted]
        questions: list[PrivateVerificationQuestion] = []
        for record in records:
            for question in record.verification_questions:
                questions.append(
                    PrivateVerificationQuestion(
                        document_id=record.document_id,
                        document_title=record.document_title,
                        issue_date=record.issue_date,
                        ticker=record.ticker,
                        company_name=record.company_name,
                        question=question,
                    )
                )
        return questions


def index_private_research_summary(
    summary: PrivateResearchDocument,
    *,
    store: PrivateResearchStore,
    model: str | None = None,
) -> PrivateStructuredSummaryRecord:
    """Store a structured summary in the private library."""

    return PrivateResearchLibrary(store).index_summary(summary, model=model)


def search_private_recommendations(
    *,
    store: PrivateResearchStore,
    filters: PrivateResearchSearchFilters | None = None,
) -> list[PrivateRecommendationRecord]:
    """Search indexed private recommendations."""

    return PrivateResearchLibrary(store).search(filters)


def latest_private_recommendation(
    ticker: str,
    *,
    store: PrivateResearchStore,
) -> PrivateRecommendationRecord | None:
    """Return the latest private recommendation for a ticker."""

    return PrivateResearchLibrary(store).latest_recommendation(ticker)


def private_recommendation_timeline(
    ticker: str,
    *,
    store: PrivateResearchStore,
) -> list[PrivateRecommendationRecord]:
    """Return a private recommendation timeline for a ticker."""

    return PrivateResearchLibrary(store).recommendation_timeline(ticker)


def compare_private_documents(
    document_a_id: str,
    document_b_id: str,
    *,
    store: PrivateResearchStore,
) -> PrivateDocumentComparison:
    """Compare indexed private recommendations between two documents."""

    return PrivateResearchLibrary(store).compare_documents(document_a_id, document_b_id)


def unresolved_private_verification_questions(
    *,
    store: PrivateResearchStore,
    ticker: str | None = None,
    document_id: str | None = None,
) -> list[PrivateVerificationQuestion]:
    """Return unresolved verification questions from indexed recommendations."""

    return PrivateResearchLibrary(store).unresolved_verification_questions(
        ticker=ticker,
        document_id=document_id,
    )


def _matches_filters(
    record: PrivateRecommendationRecord,
    filters: PrivateResearchSearchFilters,
) -> bool:
    if filters.ticker and record.ticker != filters.ticker:
        return False
    if filters.company and filters.company.casefold() not in record.company_name.casefold():
        return False
    if filters.recommendation and record.recommendation != filters.recommendation:
        return False
    if filters.sector:
        if record.sector is None or filters.sector.casefold() not in record.sector.casefold():
            return False
    if filters.date_from is not None:
        if record.issue_date is None or record.issue_date < filters.date_from:
            return False
    if filters.date_to is not None:
        if record.issue_date is None or record.issue_date > filters.date_to:
            return False
    if filters.keyword and filters.keyword.casefold() not in _keyword_blob(record):
        return False
    return True


def _keyword_blob(record: PrivateRecommendationRecord) -> str:
    parts = [
        record.document_title,
        record.company_name,
        record.thesis or "",
        " ".join(record.risks),
        " ".join(record.catalysts),
    ]
    return " ".join(parts).casefold()


def _timeline_sort_key(record: PrivateRecommendationRecord) -> tuple[date, str]:
    return (record.issue_date or record.generated_at.date(), record.document_id)


def _record_key(record: PrivateRecommendationRecord) -> str:
    return (record.ticker or record.company_name).casefold()


def _display_key(record: PrivateRecommendationRecord) -> str:
    return record.ticker or record.company_name


def _records_differ(
    previous: PrivateRecommendationRecord,
    current: PrivateRecommendationRecord,
) -> bool:
    return any(
        (
            previous.recommendation != current.recommendation,
            previous.stated_target_price != current.stated_target_price,
            previous.risks != current.risks,
            previous.catalysts != current.catalysts,
        )
    )


def _difference(
    previous: PrivateRecommendationRecord,
    current: PrivateRecommendationRecord,
) -> PrivateRecommendationDifference:
    return PrivateRecommendationDifference(
        ticker=current.ticker or previous.ticker,
        company_name=current.company_name,
        from_document_id=previous.document_id,
        to_document_id=current.document_id,
        from_recommendation=previous.recommendation,
        to_recommendation=current.recommendation,
        from_target_price=previous.stated_target_price,
        to_target_price=current.stated_target_price,
        from_risks=previous.risks,
        to_risks=current.risks,
        from_catalysts=previous.catalysts,
        to_catalysts=current.catalysts,
    )
