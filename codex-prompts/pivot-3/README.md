# Pivot 3 Prompts

These prompts add a private, personal-use companion for subscribed Under the Radar research.
The intent is to help one subscriber ingest and understand material they already have access
to, not to redistribute paid content or automate access without permission.

## Assumptions

- Codex is running from the repository root.
- Pivot 1 functionality exists and can be reused for PDF extraction and summarization.
- Pivot 2 may exist, but the private workflow must remain clearly separated from public briefs.
- The prompts are intended to be executed in numeric order.
- Prefer upload, local files, forwarded emails, or manual import over logged-in scraping.
- Any logged-in connector must stay disabled by default unless explicit permission is confirmed.
- Tests must use synthetic fixtures and mocked LLM calls only.

## Execution Order

Run `01-private-use-boundaries-and-architecture.txt` through
`10-tests-docs-and-release-polish.txt` sequentially. Establish private-use boundaries and
storage before adding importers, schemas, summarization, search/history, UI, digest output,
and release documentation.

## Outcome

After this sequence, the app should provide a private local research library for subscribed
materials, summarize Under the Radar-style recommendations from user-provided documents,
support search/history/comparison, and offer password-protected UI and private digest outputs.

