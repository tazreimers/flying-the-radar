from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from market_pdf_insights.private_research_policy import (
    PrivateResearchAccessMethod,
    PrivateResearchBoundary,
    PrivateResearchModule,
    PrivateResearchPolicyError,
    PrivateSourceAttribution,
    default_private_research_boundary,
    default_private_research_module_boundaries,
    private_research_scope_notes,
)


def test_default_private_boundary_allows_user_provided_paths() -> None:
    boundary = default_private_research_boundary()

    for method in [
        PrivateResearchAccessMethod.USER_UPLOAD,
        PrivateResearchAccessMethod.LOCAL_FILE,
        PrivateResearchAccessMethod.EMAIL_FORWARD,
        PrivateResearchAccessMethod.MANUAL_ENTRY,
        PrivateResearchAccessMethod.SUBSCRIPTION_EXPORT,
    ]:
        boundary.assert_access_method_allowed(method)


def test_logged_in_automation_is_disabled_by_default() -> None:
    boundary = default_private_research_boundary()

    with pytest.raises(PrivateResearchPolicyError, match="disabled by default"):
        boundary.assert_access_method_allowed(PrivateResearchAccessMethod.LOGGED_IN_AUTOMATION)


def test_logged_in_automation_requires_explicit_terms_confirmation() -> None:
    boundary = PrivateResearchBoundary(logged_in_automation_enabled=True)

    with pytest.raises(PrivateResearchPolicyError, match="explicit confirmation"):
        boundary.assert_access_method_allowed(PrivateResearchAccessMethod.LOGGED_IN_AUTOMATION)


def test_private_boundary_rejects_redistribution_and_financial_advice() -> None:
    with pytest.raises(ValidationError, match="redistribution"):
        PrivateResearchBoundary(redistribution_allowed=True)

    with pytest.raises(ValidationError, match="financial advice"):
        PrivateResearchBoundary(financial_advice_allowed=True)


def test_private_source_attribution_preserves_subscription_metadata() -> None:
    attribution = PrivateSourceAttribution(
        source_name="Under the Radar",
        document_title="Synthetic Research Note",
        access_method=PrivateResearchAccessMethod.USER_UPLOAD,
        url="https://example.test/private-note",
        author="Fixture Author",
        published_at=datetime(2026, 5, 12, tzinfo=UTC),
        retrieved_at=datetime(2026, 5, 12, 8, 0, tzinfo=UTC),
        subscription_notes="Subscriber-provided fixture.",
        licence_notes="Do not redistribute.",
    )

    assert attribution.source_name == "Under the Radar"
    assert attribution.access_method == PrivateResearchAccessMethod.USER_UPLOAD
    assert attribution.licence_notes == "Do not redistribute."


def test_private_source_attribution_requires_retrieved_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        PrivateSourceAttribution(
            source_name="Under the Radar",
            document_title="Synthetic Research Note",
            access_method=PrivateResearchAccessMethod.LOCAL_FILE,
            retrieved_at=datetime(2026, 5, 12, 8, 0),
        )


def test_private_module_boundaries_cover_required_design_areas() -> None:
    modules = {boundary.module for boundary in default_private_research_module_boundaries()}

    assert modules == {
        PrivateResearchModule.PRIVATE_INGESTION,
        PrivateResearchModule.SECURE_SETTINGS,
        PrivateResearchModule.DOCUMENT_LIBRARY,
        PrivateResearchModule.RECOMMENDATION_EXTRACTION,
        PrivateResearchModule.PERSONAL_DIGEST,
        PrivateResearchModule.SEARCH_QA,
        PrivateResearchModule.PASSWORD_PROTECTED_UI,
    }


def test_private_scope_notes_include_core_boundaries() -> None:
    notes = " ".join(private_research_scope_notes()).lower()

    assert "single-user" in notes
    assert "do not redistribute" in notes
    assert "financial advice" in notes
    assert "logged-in automation" in notes
