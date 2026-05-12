# Private Research Library

`market_pdf_insights.private_research_library` indexes structured private summaries into a local
recommendation library so coverage can be searched and compared over time.

## Stored Index

The SQLite store now keeps:

- `private_structured_summaries`: validated `PrivateResearchDocument` JSON per imported document;
- `private_stock_recommendations`: denormalized recommendation rows for search, history, and
  comparison.

The index stores source-light fields: document id/title, issue date, company, ticker, exchange,
sector, source rating, target price, thesis, risks, catalysts, short source excerpt references,
and unresolved verification questions.

## Search

Search locally by ticker, company, date range, rating, sector, and keyword:

```bash
market-pdf-insights private search --ticker EXR
market-pdf-insights private search --rating "Speculative Buy" --sector materials
market-pdf-insights private search --keyword licence
```

Programmatic use:

```python
from market_pdf_insights.private_research_library import (
    PrivateResearchLibrary,
    PrivateResearchSearchFilters,
)

records = PrivateResearchLibrary(store).search(
    PrivateResearchSearchFilters(ticker="EXR", keyword="funding")
)
```

## History And Comparison

```bash
market-pdf-insights private history --ticker EXR
market-pdf-insights private compare private-doc-a private-doc-b
```

The library can return the latest recommendation for a ticker, a chronological recommendation
timeline, changed ratings/target prices between two documents, added/removed ticker coverage,
and unresolved verification questions.

## Indexing

`market-pdf-insights private summarize DOCUMENT_ID` now creates the older local placeholder
summary and indexes a structured `PrivateResearchDocument` using the offline placeholder private
research synthesizer.

Programmatically, index an existing structured summary with:

```python
from market_pdf_insights.private_research_library import index_private_research_summary

index_private_research_summary(summary, store=store, model="private-placeholder")
```

All library queries are local and use synthetic/offline fixtures in tests.
