# Daily Brief Schema

`market_pdf_insights.daily_brief_schema` defines the structured output contract for the
public daily market-intelligence brief.

## Primary Model

`DailyMarketBrief` represents the email/web-ready daily brief. It includes:

- `briefing_date`, `generated_at`, `title`, and `executive_summary`
- `yesterday_recap` and `day_ahead`
- overall `market_stance`
- `top_themes`
- sections for Australia, global macro, commodities, and currencies/rates
- `watchlist_impacts`
- `calendar` and `macro_events`
- `risks`
- `sources`
- `verification_flags`
- `confidence_score`
- `disclaimer`

## Supporting Models

- `BriefSection`: reusable source-backed section.
- `MarketTheme`: top market theme with affected assets.
- `AssetMention`: asset, sector, currency, rate, or macro indicator mention.
- `MacroEvent`: macro release or data observation.
- `CalendarEvent`: forward-looking event.
- `WatchlistImpact`: general watchlist readthrough.
- `BriefRisk`: highlighted risk or uncertainty.
- `SourceCitation`: first-class citation metadata.
- `VerificationFlag`: claim or datapoint needing human verification.

## Validation Rules

- `market_stance` and section stances are limited to `bullish`, `bearish`, `neutral`, `mixed`,
  or `unclear`.
- `confidence_score` must be between `0` and `1`.
- `generated_at` must include timezone information.
- Source-backed content must include at least one citation.
- Nested citations must appear in the top-level `sources` catalogue.
- Top-level `sources` cannot contain duplicate `citation_id` values.
- Citation snippets are limited to short excerpts: max 280 characters and 60 words.

These limits are intentional: the brief should summarize and attribute sources, not store full
copyrighted articles or reports.

See [examples/daily_market_brief.json](../examples/daily_market_brief.json) for a validated
example payload.
