from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from market_pdf_insights.ingestion import (
    IngestionRunner,
    JsonAPIConnector,
    JsonlMarketItemStore,
    LocalFixtureConnector,
    RSSFeedConnector,
    RawSourceItem,
    build_deduplication_key,
    deduplicate_items,
    normalize_source_item,
    parse_datetime,
)
from market_pdf_insights.source_policy import SourceAccessMethod, SourcePolicyError
from market_pdf_insights.source_registry import (
    SourceCapability,
    SourceCategory,
    SourceDefinition,
    SourceTerms,
    default_source_registry,
)


def test_rss_connector_parses_fixture_and_normalizes_items() -> None:
    connector = RSSFeedConnector(
        _source("fixture-rss", SourceAccessMethod.RSS, SourceCategory.AUSTRALIAN_MARKET),
        feed_url="https://example.test/feed.xml",
        http_get=lambda _: _rss_fixture(),
    )

    result = connector.fetch_since(datetime(2026, 5, 12, tzinfo=UTC))

    assert result.source_id == "fixture-rss"
    assert len(result.raw_items) == 1
    assert len(result.normalized_items) == 1
    item = result.normalized_items[0]
    assert item.title == "Market update BHP"
    assert item.url == "https://example.test/bhp"
    assert item.category == SourceCategory.AUSTRALIAN_MARKET
    assert item.tickers == ("BHP",)
    assert item.attribution.source_name == "Fixture fixture-rss"
    assert item.terms.terms_notes == "Fixture terms permit automated tests."


def test_json_api_connector_parses_fixture_response() -> None:
    source = _source("fixture-api", SourceAccessMethod.API, SourceCategory.GLOBAL_MACRO)
    connector = JsonAPIConnector(
        source,
        endpoint_url="https://example.test/api",
        http_get=lambda _: {
            "items": [
                {
                    "id": "cpi-1",
                    "headline": "CPI print cools",
                    "summary": "Inflation fell to 3.0%.",
                    "link": "https://example.test/cpi",
                    "date": "2026-05-12T01:30:00Z",
                    "tickers": ["AUD"],
                }
            ]
        },
    )

    result = connector.fetch_since()

    assert len(result.raw_items) == 1
    assert result.normalized_items[0].title == "CPI print cools"
    assert result.normalized_items[0].tickers == ("AUD",)
    assert result.normalized_items[0].published_at == datetime(2026, 5, 12, 1, 30, tzinfo=UTC)


def test_local_fixture_connector_loads_jsonl_manual_file(tmp_path) -> None:
    fixture_path = tmp_path / "manual.jsonl"
    fixture_path.write_text(
        json.dumps(
            {
                "id": "manual-1",
                "title": "Manual note",
                "body": "Portfolio watchlist note.",
                "url": "https://example.test/manual",
                "published_at": "2026-05-12",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    connector = LocalFixtureConnector(_manual_source(), fixture_path=fixture_path)

    result = connector.fetch_since()

    assert len(result.normalized_items) == 1
    assert result.normalized_items[0].title == "Manual note"
    assert result.normalized_items[0].source_id == "user-upload"


def test_disabled_source_cannot_create_network_connector() -> None:
    disabled_source = default_source_registry().get("market-index")

    with pytest.raises(SourcePolicyError, match="Source is disabled"):
        JsonAPIConnector(disabled_source, endpoint_url="https://example.test/api")


def test_dry_run_does_not_call_fetcher() -> None:
    def fail_fetch(_: str) -> str:
        raise AssertionError("dry run should not fetch")

    connector = RSSFeedConnector(
        _source("dry-rss", SourceAccessMethod.RSS, SourceCategory.NEWS_COMMENTARY),
        feed_url="https://example.test/feed.xml",
        http_get=fail_fetch,
        dry_run=True,
    )

    result = connector.fetch_since()

    assert result.dry_run
    assert not result.raw_items
    assert result.warnings == ["Dry run: no network or file fetch was performed."]


def test_retry_backoff_hook_runs_before_success() -> None:
    attempts = {"count": 0}
    backoff_calls: list[tuple[int, str]] = []

    def flaky_fetch(_: str) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        return _rss_fixture()

    connector = RSSFeedConnector(
        _source("retry-rss", SourceAccessMethod.RSS, SourceCategory.NEWS_COMMENTARY),
        feed_url="https://example.test/feed.xml",
        http_get=flaky_fetch,
        max_attempts=2,
        retry_backoff=lambda attempt, exc: backoff_calls.append((attempt, str(exc))),
    )

    result = connector.fetch_since()

    assert len(result.normalized_items) == 2
    assert backoff_calls == [(1, "temporary")]


def test_deduplication_key_prefers_url_then_id_then_title_date() -> None:
    source_id = "fixture-api"
    published_at = datetime(2026, 5, 12, tzinfo=UTC)

    from_url = build_deduplication_key(
        source_id=source_id,
        url="https://example.test/story",
        raw_id="first",
        title="First title",
        published_at=published_at,
    )
    from_same_url = build_deduplication_key(
        source_id=source_id,
        url="https://example.test/story",
        raw_id="second",
        title="Second title",
        published_at=published_at,
    )
    from_title_date = build_deduplication_key(
        source_id=source_id,
        url=None,
        raw_id=None,
        title="First title",
        published_at=published_at,
    )

    assert from_url == from_same_url
    assert from_url != from_title_date


def test_jsonl_store_and_runner_deduplicate_items(tmp_path) -> None:
    source = _source("fixture-api", SourceAccessMethod.API, SourceCategory.GLOBAL_MACRO)
    connector = JsonAPIConnector(
        source,
        endpoint_url="https://example.test/api",
        http_get=lambda _: {
            "items": [
                {
                    "id": "same-id",
                    "title": "Duplicate story",
                    "summary": "First copy.",
                    "url": "https://example.test/dupe",
                },
                {
                    "id": "same-id",
                    "title": "Duplicate story",
                    "summary": "Second copy.",
                    "url": "https://example.test/dupe",
                },
            ]
        },
    )
    store = JsonlMarketItemStore(tmp_path / "items.jsonl")
    runner = IngestionRunner([connector], store=store)

    first_run = runner.run()
    second_run = runner.run()

    assert first_run.total_fetched == 2
    assert first_run.total_new == 1
    assert second_run.total_new == 0
    assert len(store.load_items()) == 1


def test_normalize_source_item_preserves_terms_metadata() -> None:
    source = _source("fixture-api", SourceAccessMethod.API, SourceCategory.GLOBAL_MACRO)
    raw = RawSourceItem(
        source_id=source.source_id,
        raw_id="raw-1",
        title="GDP release",
        summary="GDP rose.",
        url="https://example.test/gdp",
    )

    item = normalize_source_item(raw, source)

    assert item.terms.terms_url == "https://example.test/terms"
    assert item.attribution.terms_url == "https://example.test/terms"
    assert item.attribution.licence_notes == "Fixture terms permit automated tests."


def test_parse_datetime_handles_iso_and_rss_dates() -> None:
    assert parse_datetime("2026-05-12T01:30:00Z") == datetime(
        2026, 5, 12, 1, 30, tzinfo=UTC
    )
    assert parse_datetime("Tue, 12 May 2026 01:30:00 GMT") == datetime(
        2026, 5, 12, 1, 30, tzinfo=UTC
    )


def test_deduplicate_items_preserves_first_seen_order() -> None:
    source = _source("fixture-api", SourceAccessMethod.API, SourceCategory.GLOBAL_MACRO)
    first = normalize_source_item(
        RawSourceItem(source_id=source.source_id, raw_id="1", title="First"),
        source,
    )
    duplicate = first.model_copy(update={"body": "later copy"})
    second = normalize_source_item(
        RawSourceItem(source_id=source.source_id, raw_id="2", title="Second"),
        source,
    )

    assert deduplicate_items([first, duplicate, second]) == [first, second]


def _source(
    source_id: str,
    access_method: SourceAccessMethod,
    category: SourceCategory,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=f"Fixture {source_id}",
        category=category,
        homepage_url="https://example.test/",
        capability=SourceCapability(
            access_method=access_method,
            fetch_strategy="fixture",
            automation_allowed=True,
            enabled=True,
        ),
        terms=SourceTerms(
            terms_notes="Fixture terms permit automated tests.",
            terms_url="https://example.test/terms",
            rate_limit_notes="No live network calls in tests.",
        ),
    )


def _manual_source() -> SourceDefinition:
    return SourceDefinition(
        source_id="user-upload",
        display_name="User Upload",
        category=SourceCategory.USER_PROVIDED,
        capability=SourceCapability(
            access_method=SourceAccessMethod.USER_UPLOAD,
            fetch_strategy="manual_upload",
            automation_allowed=False,
            enabled=True,
        ),
        terms=SourceTerms(terms_notes="User-provided fixture."),
    )


def _rss_fixture() -> str:
    return """
    <rss version="2.0">
      <channel>
        <title>Fixture feed</title>
        <item>
          <guid>old-1</guid>
          <title>Old market update</title>
          <description>Before the since window.</description>
          <link>https://example.test/old</link>
          <pubDate>Mon, 11 May 2026 00:00:00 GMT</pubDate>
        </item>
        <item>
          <guid>new-1</guid>
          <title>Market update BHP</title>
          <description>BHP rose after a production update.</description>
          <link>https://example.test/bhp</link>
          <pubDate>Tue, 12 May 2026 01:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
