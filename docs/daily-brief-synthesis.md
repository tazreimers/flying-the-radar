# Daily Brief Synthesis

`market_pdf_insights.daily_brief_synthesis` turns normalized public/legal source items into a
validated `DailyMarketBrief`.

## Flow

1. `NormalizedMarketItem` objects are grouped by source and category.
2. Each group is summarized into `SourceGroupNotes`.
3. Group notes and the source citation catalogue are synthesized into a final
   `DailyMarketBrief`.
4. Pydantic validates both stages. Malformed JSON or schema failures are retried.

## Clients

- `OpenAIDailyBriefClient`: hosted LLM implementation using the same Responses API pattern as
  the PDF summarizer.
- `MockDailyBriefLLMClient`: deterministic local/test implementation that produces a valid
  brief without network calls.
- `MockBriefLLMClient`: short alias for the same deterministic daily brief test client.

## Guardrails

The prompts require the model to:

- distinguish facts from commentary;
- preserve citation ids, URLs, retrieved timestamps, and terms metadata;
- avoid copying long source text or full copyrighted articles;
- summarize `yesterday_recap` and `day_ahead` separately;
- call out Australia, global macro, rates, currencies, commodities, sectors, risks, and
  watchlist impacts when supported;
- flag unsupported, stale, numerical, or externally verifiable claims;
- avoid financial advice and buy/sell/hold recommendations.

Credentials are loaded from `OPENAI_API_KEY` or runtime configuration. Tests use fake clients
and never call live OpenAI.
