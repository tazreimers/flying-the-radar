# Private Research Schema

`market_pdf_insights.private_research_schema` defines the structured output contract for
Under the Radar-style stock recommendation summaries. The schema is designed to preserve source
references while avoiding full-text redistribution of subscribed material.

## Core Models

- `PrivateResearchDocument`: source-light structured summary for one imported private document.
- `StockRecommendation`: one company/security recommendation from the source.
- `RecommendationChange`: initiated, upgraded, downgraded, reiterated, or removed ratings.
- `ThesisPoint`: concise thesis, bullish, bearish, balanced, or neutral point.
- `RiskPoint`: risk, severity, affected metric, and optional mitigation/offset.
- `ValuationNote`: valuation method, target price, assumptions, and numbers to verify.
- `Catalyst`: event or condition that could affect the recommendation.
- `PortfolioWatchItem`: monitoring item derived from source facts, not a trade instruction.
- `SourceExcerpt`: short page/section-backed reference.
- `PersonalActionQuestion`: personal research/checklist question, not advice.

The schema also includes `NumberToVerify` for prices, dates, multiples, forecasts, and other
facts that should be checked before use.

## Validation Rules

- Ratings are normalized to canonical values such as `buy`, `speculative_buy`, `hold`,
  `reduce`, `sell`, `under_review`, and `not_rated`.
- Unknown ratings are rejected.
- Confidence scores must be between `0` and `1`.
- Tickers, exchanges, and currency codes are normalized to uppercase.
- Source excerpts are capped at 55 words and 360 characters.
- Nested source excerpts must reference the parent private `document_id`.
- Personal action items must be framed as questions and must not instruct buy/sell/hold/trade.

## Example JSON

A validated example is available at:

```text
examples/private_research_document.json
```

You can also generate the built-in example:

```python
from market_pdf_insights.private_research_schema import PrivateResearchDocument

print(PrivateResearchDocument.example_json())
```

## Boundary

This schema stores facts, short paraphrases/excerpts, source references, recommendation labels,
risks, catalysts, valuation assumptions, and verification prompts. It does not store full report
text and does not produce personal financial advice.

`market_pdf_insights.private_research_synthesis` produces this schema from imported private
documents through a chunk-notes-then-synthesis flow.
