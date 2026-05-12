# Global Macro And News Connectors

`market_pdf_insights.global_connectors` adds legal global macro and news ingestion for the
public daily market-intelligence branch.

## Configuration

Use `GlobalMacroNewsConfig` to keep credentials and query scope out of code:

- `fred_api_key`: read from `FRED_API_KEY` or runtime config.
- `newsapi_key`: read from `NEWSAPI_KEY` or runtime config.
- `fred_series`: explicit FRED series IDs and optional observation date ranges.
- `world_bank_indicators`: explicit country/indicator/year ranges.
- `news_search`: query, watchlist terms, language, date range, result limit, and sort.
- `regions`: optional downstream grouping metadata.

API keys are optional at config time but required when credentialed connectors are created.
No connector hardcodes credentials.

## Implemented Connectors

- `FREDAPIConnector`: fetches FRED series observations using `FRED_API_KEY`.
- `WorldBankIndicatorConnector`: fetches World Bank Indicators API responses.
- `GDELTDocConnector`: fetches GDELT DOC 2.0 ArticleList JSON results.
- `NewsAPIConnector`: fetches NewsAPI Everything results using `NEWSAPI_KEY`.

All four normalize into `NormalizedMarketItem` and preserve terms metadata.

## Disabled Or Scope-Gated Stubs

- `IMFConnector`: disabled until an explicit IMF SDMX/DataMapper dataset, dimension, version,
  and period scope is configured.
- `OECDConnector`: disabled until an explicit Data Explorer API query and rate-limit budget
  is configured.
- `BloombergConnector`: disabled unless Bloomberg Data License or permitted subscription export
  access is configured.
- `ReutersConnector`: disabled unless Reuters Connect or equivalent licensed feed/export
  access is configured.

These stubs raise `SourcePolicyError` and must not scrape public pages.

## Source Notes

FRED:

- FRED API requests require a registered API key.
- Series observations support JSON output and observation start/end parameters.
- FRED terms require the FRED API notice and preservation of proprietary notices.

World Bank:

- Use the V2 Indicators API, for example `/v2/country/{country}/indicator/{indicator}`.
- Dataset terms generally permit API use with attribution, subject to indicator metadata and
  third-party restrictions.

GDELT:

- The DOC 2.0 API supports JSON ArticleList results.
- Use narrow watchlist queries, bounded date windows, and modest result counts.
- Store article metadata and links; do not republish third-party article text.

NewsAPI:

- The Everything endpoint requires an API key and supports date, language, query, and sort
  parameters.
- Respect plan limits and restrictions. Developer plans are for development/testing only.
- Do not reproduce or republish copyrighted material beyond the applicable licence.

References:

- FRED series observations: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- FRED API keys: https://fred.stlouisfed.org/docs/api/api_key.html
- FRED API terms: https://fred.stlouisfed.org/docs/api/terms_of_use.html
- World Bank Indicators API: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
- World Bank dataset terms: https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets
- GDELT DOC 2.0 API: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- NewsAPI Everything: https://newsapi.org/docs/endpoints/everything
- NewsAPI terms: https://newsapi.org/terms
- IMF APIs: https://data.imf.org/en/Resource-Pages/IMF-API
- OECD API: https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html
- Bloomberg Data License:
  https://professional.bloomberg.com/products/data/data-management/data-license/
- Reuters Connect: https://www.reutersconnect.com/
