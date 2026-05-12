# Pivot 1 Prompts

These prompts build the original `market-pdf-insights` MVP: a PDF-to-structured-market-report
tool with CLI and Streamlit interfaces.

## Assumptions

- Codex is running from the repository root.
- The prompts are intended to be executed in numeric order.
- Each prompt should inspect the current codebase before editing.
- Keep tests offline and use mocked LLM calls.
- Do not hardcode API keys or secrets.

## Execution Order

Run `01-repo-scaffold.txt` through `10-full-mvp-build.txt` sequentially. Later prompts assume
the earlier repository scaffold, PDF extraction, chunking, schema, LLM client, CLI, Streamlit,
and README work already exists.

## Outcome

After this sequence, the app should extract PDF text, chunk long documents, summarize with a
placeholder or OpenAI-backed client, validate a structured `MarketInsightReport`, and provide
JSON/Markdown output through CLI and Streamlit.

