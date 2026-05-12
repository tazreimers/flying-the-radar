# Private Release Checklist

Use this checklist before running or sharing the Pivot 3 private research companion.

## Scope

- Personal use only for subscribed research the user is already entitled to access.
- Do not redistribute subscribed reports, full article text, or generated private summaries.
- Do not use private subscribed text in the public daily market brief workflow.
- Outputs are summaries and research organization aids, not personal financial advice.

## Inputs

Supported input paths are user-driven:

- PDF upload or local downloaded PDF;
- saved text, HTML, Markdown, or `.eml` email files;
- manually pasted notes;
- explicitly permitted subscription exports.

Logged-in Under the Radar automation remains disabled. The connector stub validates safety gates
and still refuses live login, scraping, browser automation, or report download.

## Local Data

- Default private data directory: `.private-research/`.
- Raw subscribed documents are not stored unless retention settings explicitly allow it.
- Extracted text and SQLite sidecars are local files and are ignored by git.
- Password protection uses `MARKET_PRIVATE_UI_PASSWORD_HASH`; do not store plaintext passwords
  in settings, docs, tests, screenshots, or committed `.env` files.

## Verification

Run before release:

```bash
ruff check .
PYTHONPATH=src python3 -m pytest -q
```

The tests are offline. They clear real API key environment variables, block live network access,
use fixtures/fakes, and include safety checks for private/public separation and committed
credential patterns.

## Current Limits

- No real email sending; only dry-run `.eml`, `.html`, or `.txt` files are written.
- No production multi-user access control.
- No natural-language private Q&A.
- Placeholder and mock summarizers are useful for plumbing but not final investment research.
