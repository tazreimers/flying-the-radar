# Private Digest

`market_pdf_insights.private_digest` renders daily or weekly single-user digests from the local
private research library. It uses only indexed private summaries already stored locally.

## Outputs

The digest includes:

- per-document summaries for new private research in the selected date range;
- per-ticker summaries from indexed recommendation rows;
- recommendation and target-price changes compared with earlier local history;
- short source references and citations;
- the private-use, not-advice, no-redistribution disclaimer.

Supported output formats are JSON, Markdown, HTML, plain text, and dry-run `.eml` email files.
No real email is sent.

## CLI

Generate Markdown and HTML:

```bash
market-pdf-insights private digest \
  --period weekly \
  --date 2026-05-12 \
  --markdown outputs/private-digest.md \
  --html outputs/private-digest.html
```

Write a local `.eml` dry run:

```bash
market-pdf-insights private digest \
  --period daily \
  --date 2026-05-12 \
  --email-dry-run outputs/private-digest.eml \
  --sender private@example.test \
  --recipient you@example.test
```

`--sender`, `--recipient`, `--reply-to`, and `--subject-prefix` are envelope settings only.
They are not SMTP credentials and the command does not send the message.

Use `--from-date` and `--to-date` for a custom date range, and repeat `--ticker` to limit the
digest to selected tickers.

## Streamlit

The `Private Research` tab includes a `Digest` screen. It builds a local daily or weekly digest
from indexed summaries and exposes JSON, Markdown, and HTML download buttons.

## Boundaries

Private digests are for personal organization of subscribed material. They must not be
distributed, published, or mixed into the public daily market brief. The renderer includes only
short source references and source-light summaries, not full subscribed reports.
