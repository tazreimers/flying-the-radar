# Ingestion Framework

`market_pdf_insights.ingestion` loads permitted public market-intelligence source items
without coupling ingestion to the LLM summarizer.

## Core Flow

1. A connector receives an enabled `SourceDefinition`.
2. The connector fetches raw items since an optional timestamp.
3. Raw items are normalized into `NormalizedMarketItem`.
4. Items are deduplicated by source id plus URL, source item id, or title/date.
5. Optional JSONL persistence stores only unseen normalized items.

Connectors must not fetch disabled sources. Network connectors require an enabled source with
an automated access method: `api`, `rss`, or `licensed_feed`.

## Models

- `RawSourceItem`: connector-specific item data before normalization.
- `NormalizedMarketItem`: common downstream shape with title, body, URL, source, category,
  tickers, attribution, and terms metadata.
- `ConnectorResult`: connector output containing raw items, normalized items, warnings, and
  dry-run status.
- `IngestionRun`: summary of a multi-connector run.

## Connectors

- `RSSFeedConnector`: parses RSS and Atom feed fixtures or responses.
- `JsonAPIConnector`: parses JSON responses with configurable item paths.
- `LocalFixtureConnector`: loads JSON, JSONL, or text files for manual/fixture ingestion.

All network access is isolated behind an injectable `http_get` callable, so tests and future
connectors can run without live network access.

## Persistence

`JsonlMarketItemStore` writes normalized items as newline-delimited JSON. It checks existing
deduplication keys before appending, so repeated runs only return newly stored items.

## Example

```python
from market_pdf_insights.ingestion import IngestionRunner, JsonAPIConnector

source = registry.assert_fetch_allowed("fred-api")
connector = JsonAPIConnector(source, endpoint_url="https://example.test/api")
run = IngestionRunner([connector]).run()
```

The default registry still keeps public sources disabled until connector-specific access,
terms, and rate-limit settings are configured.
