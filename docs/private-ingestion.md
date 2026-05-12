# Private Ingestion

Private ingestion imports subscribed research the user already possesses. It does not log in to
Under the Radar, scrape private websites, bypass paywalls, or redistribute paid content.

## Supported Inputs

`market_pdf_insights.private_ingestion` supports:

- downloaded PDF files;
- local directories containing `.pdf`, `.txt`, `.md`, `.html`, `.htm`, or `.eml` files;
- saved HTML/text email files;
- RFC 822 `.eml` email files;
- manually pasted text;
- uploaded PDF bytes from a future UI.

Each import is normalized into a private document record with:

- document title;
- issue date when detected;
- source name and source type;
- access method;
- original filename when applicable;
- author/from header when available;
- extracted text path;
- section/headings list;
- content hash and deduplication key;
- source attribution and licence notes.

Raw subscribed documents are not stored by default. Extracted text sidecars are stored under the
configured private data directory so summaries can be regenerated locally.

## Deduplication

Documents are deduplicated by source, issue date, title, and content hash. Importing the same
file or identical saved text twice returns the existing private document and reports it as
skipped instead of inserting a duplicate row.

## CLI

Import a downloaded report or a directory:

```bash
market-pdf-insights private import ~/Downloads/under-the-radar-report.pdf
market-pdf-insights private import ~/Documents/private-research-inbox
```

Import pasted text:

```bash
market-pdf-insights private import \
  --title "Under the Radar note" \
  --manual-text "Issue Date: 2026-05-12\n\nRecommendation: Buy\nABC update."
```

List and summarize private documents:

```bash
market-pdf-insights private list
market-pdf-insights private summarize private-abc123
```

Use `--settings path/to/private-settings.toml` to load a settings file, or `--data-dir` to point
the private store at a local directory for tests, experiments, or a separate personal library.

## Current Limits

The summary command is a local deterministic placeholder. It extracts a short summary,
recommendation label, ticker-like uppercase symbols, risks, catalysts, and a citation snippet.
It is useful for validating the ingestion/storage workflow, but it is not a replacement for a
source-grounded LLM summarizer or investment advice.
