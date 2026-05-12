# Private Research Summarizer

`market_pdf_insights.private_research_synthesis` turns an imported private document into a
validated `PrivateResearchDocument`.

## Flow

1. Load extracted text from a stored `PrivateDocumentRecord`.
2. Split the text with the existing `chunk_text` utility.
3. Summarize each chunk into `PrivateResearchChunkNotes`.
4. Synthesize the chunk notes into the private recommendation schema.

The main helper is:

```python
from market_pdf_insights.private_research_synthesis import summarize_imported_private_research

summary = summarize_imported_private_research(document_id, store=store)
```

To make the result searchable in the private library, index it:

```python
from market_pdf_insights.private_research_library import index_private_research_summary

index_private_research_summary(summary, store=store, model="private-placeholder")
```

By default this uses `PlaceholderPrivateResearchClient`, which is deterministic and offline.
`OpenAIPrivateResearchClient` is available for hosted synthesis when an injected SDK client or
`OPENAI_API_KEY` is supplied.

## Safety Prompts

The OpenAI client uses two prompt constants:

- `PRIVATE_RESEARCH_CHUNK_SYSTEM_PROMPT`
- `PRIVATE_RESEARCH_SYNTHESIS_SYSTEM_PROMPT`

Both prompts require the model to:

- summarize what the source says;
- avoid generating new buy/sell/hold advice;
- avoid tailoring output to user circumstances;
- preserve source attribution, page/section references, and disclaimers;
- keep excerpts short;
- flag uncertainty and claims needing verification.

## Output Boundary

The output is framed as a source summary for private personal use. It may include source-stated
ratings, target prices, risks, catalysts, valuation assumptions, and personal research questions,
but it must not tell the user what to buy, sell, hold, rebalance, or trade.

Tests use synthetic fixtures, `PlaceholderPrivateResearchClient`, and injected fake OpenAI
clients. No live OpenAI calls or real subscription credentials are used in tests.
