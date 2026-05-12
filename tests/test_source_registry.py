from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError
from market_pdf_insights.source_registry import (
    SourceAuthType,
    SourceCapability,
    SourceCategory,
    SourceCredentialPolicy,
    SourceDefinition,
    SourceFetchResult,
    SourceRegistry,
    SourceTerms,
    default_source_registry,
)


def test_default_registry_contains_disabled_unapproved_sources() -> None:
    registry = default_source_registry()

    for source_id in {
        "asx-announcements",
        "market-index",
        "bloomberg",
        "reuters",
        "tradingview",
    }:
        source = registry.get(source_id)
        assert not source.enabled
        assert source.access_method == SourceAccessMethod.DISABLED
        compliance_notes = " ".join(
            note
            for note in [source.terms.terms_notes, source.terms.rate_limit_notes]
            if note is not None
        ).lower()
        assert "scrape" in compliance_notes


def test_disabled_source_cannot_be_fetched() -> None:
    registry = default_source_registry()

    with pytest.raises(SourcePolicyError, match="Source is disabled"):
        registry.assert_fetch_allowed("market-index")


def test_user_upload_is_enabled_but_not_automated_fetchable() -> None:
    registry = default_source_registry()

    source = registry.get("user-upload")

    assert source.enabled
    assert source.access_method == SourceAccessMethod.USER_UPLOAD
    with pytest.raises(SourcePolicyError, match="not an automated fetch source"):
        registry.assert_fetch_allowed("user-upload")


def test_enabled_api_source_is_fetchable_from_code_registry() -> None:
    source = SourceDefinition(
        source_id="Fixture API",
        display_name="Fixture API",
        category=SourceCategory.GLOBAL_MACRO,
        homepage_url="https://example.test/",
        api_docs_url="https://example.test/docs",
        capability=SourceCapability(
            access_method=SourceAccessMethod.API,
            fetch_strategy="json_api",
            automation_allowed=True,
            enabled=True,
        ),
        terms=SourceTerms(
            terms_notes="Permitted test API.",
            rate_limit_notes="No network calls in tests.",
            redistribution_allowed=False,
        ),
    )
    registry = SourceRegistry.from_definitions([source])

    allowed = registry.assert_fetch_allowed("fixture api")

    assert allowed.source_id == "fixture-api"
    assert registry.enabled_sources() == [allowed]


def test_registry_loads_from_config_mapping() -> None:
    registry = SourceRegistry.from_config(
        {
            "sources": [
                {
                    "source_id": "Config API",
                    "display_name": "Config API",
                    "category": "global_macro",
                    "homepage_url": "https://example.test/",
                    "api_docs_url": "https://example.test/docs",
                    "capability": {
                        "access_method": "api",
                        "fetch_strategy": "json_api",
                        "automation_allowed": True,
                        "enabled": True,
                    },
                    "terms": {
                        "terms_notes": "Permitted config fixture.",
                        "rate_limit_notes": "No network calls in tests.",
                        "redistribution_allowed": False,
                    },
                    "credentials": {
                        "auth_type": "none",
                    },
                }
            ]
        }
    )

    source = registry.assert_fetch_allowed("config-api")

    assert source.display_name == "Config API"
    assert source.category == SourceCategory.GLOBAL_MACRO


def test_registry_config_requires_sources_list() -> None:
    with pytest.raises(ValueError, match="sources list"):
        SourceRegistry.from_config({"sources": {}})


def test_enabled_automated_source_must_be_explicitly_allowed() -> None:
    with pytest.raises(ValidationError, match="automation_allowed=True"):
        SourceCapability(
            access_method=SourceAccessMethod.RSS,
            fetch_strategy="rss",
            automation_allowed=False,
            enabled=True,
        )


def test_duplicate_source_ids_are_rejected_after_normalization() -> None:
    source_a = _definition("fixture")
    source_b = _definition("Fixture")

    with pytest.raises(ValueError, match="Duplicate source id"):
        SourceRegistry.from_definitions([source_a, source_b])


def test_credentialed_source_metadata_is_preserved() -> None:
    registry = default_source_registry()

    fred = registry.get("fred-api")

    assert fred.credentials.auth_type == SourceAuthType.API_KEY
    assert fred.credentials.required_env_vars == ("FRED_API_KEY",)
    assert not fred.enabled
    assert fred.terms.terms_url == "https://fred.stlouisfed.org/docs/api/terms_of_use.html"


def test_credentialed_source_requires_environment_variable_names() -> None:
    with pytest.raises(ValidationError, match="required_env_vars"):
        SourceCredentialPolicy(auth_type=SourceAuthType.API_KEY)


def test_fetch_result_carries_attribution_and_terms_metadata() -> None:
    source = default_source_registry().get("rba-rss")
    attribution = source.attribution(
        title="RBA statement",
        published_at=datetime(2026, 5, 12, tzinfo=UTC),
    )

    result = SourceFetchResult(
        source_id=source.source_id,
        item_count=2,
        attribution=attribution,
        terms=source.terms,
        warnings=["fixture warning"],
    )

    assert result.attribution.source_name == "Reserve Bank of Australia RSS"
    assert result.terms.terms_url == "https://www.rba.gov.au/copyright/"
    assert result.warnings == ["fixture warning"]


def test_fetch_result_source_must_match_attribution() -> None:
    source = default_source_registry().get("rba-rss")

    with pytest.raises(ValidationError, match="source_id must match"):
        SourceFetchResult(
            source_id="abs-api",
            item_count=1,
            attribution=source.attribution(),
            terms=source.terms,
        )


def _definition(source_id: str) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=source_id,
        category=SourceCategory.USER_PROVIDED,
        capability=SourceCapability(
            access_method=SourceAccessMethod.MANUAL_ENTRY,
            fetch_strategy="manual",
            enabled=False,
        ),
        terms=SourceTerms(terms_notes="Fixture definition."),
    )
