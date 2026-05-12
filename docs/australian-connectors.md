# Australian Connectors

`market_pdf_insights.australian_connectors` contains the first legal Australia-specific
ingestion connectors for the public daily market-intelligence branch.

## Enabled Connector Paths

- `RBAFeedConnector`: uses official RBA RSS feed presets for media releases and exchange
  rates.
- `ABSDataConnector`: uses an explicitly configured ABS Data API JSON endpoint.
- `ABSLocalReleaseConnector`: loads ABS release fixtures or user-provided exports from local
  JSON/JSONL files.
- `ASICMediaReleasesConnector`: only works when an explicit permitted API/feed/export endpoint
  is supplied. It does not scrape ASIC pages.

All connectors normalize into `NormalizedMarketItem` and preserve source terms metadata.

## Disabled Placeholders

- `ASXAnnouncementsConnector`: disabled until an official permitted endpoint, licensed ASX
  Information Services path, or documented user-provided export is configured.
- `MarketIndexConnector`: disabled until a permitted API/feed, written permission, or licensed
  path is configured.

Both placeholders raise `SourcePolicyError` immediately and include instructions in
`AustralianDisabledConnectorInstructions`.

## Source Notes

RBA:

- The RBA publishes RSS feeds for media releases, exchange rates, speeches, Bulletin,
  Financial Stability Review, Statement on Monetary Policy, and other updates.
- RBA material is subject to the RBA copyright and disclaimer notice, including attribution
  requirements and special conditions for financial data.

ABS:

- The ABS Data API base URL is `https://data.api.abs.gov.au/rest/`.
- ABS Data API responses can be requested as JSON, XML, or CSV.
- ABS says Data API keys were removed on 29 November 2024 and the Data API is freely
  accessible without an API key.
- The separate ABS Indicator API is live for headline statistics but requires an API key.

ASIC:

- ASIC media releases are public, but this project keeps automated ingestion disabled unless
  a permitted API/feed/export endpoint is configured.

ASX and Market Index:

- Do not automate public pages or bypass controls. Use licensed data paths, official permitted
  endpoints, written permission, or user-provided exports.

References:

- RBA RSS feeds: https://www.rba.gov.au/updates/rss-feeds.html
- RBA copyright notice: https://www.rba.gov.au/copyright/
- ABS Data API user guide: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
- ABS Indicator API: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/indicator-api
- ASIC media releases: https://www.asic.gov.au/newsroom/media-releases/
- ASX Information Services: https://www.asx.com.au/connectivity-and-data/information-services
