# Market PDF Insights

`market-pdf-insights` is a public market-intelligence briefing app plus a PDF research
summarizer. The Pivot 2 MVP builds a daily market brief from permitted inputs, preserves
source citations, flags claims for verification, renders JSON/Markdown/HTML/text outputs, and
can write dry-run email files without sending real email.

The daily brief is scoped to factual information and general market commentary. It does not
personalize output to a user's objectives, financial situation, or needs, and it must not
provide buy/sell/hold recommendations.

Pivot 3 starts a separate private, single-user research companion for subscribed material. It is
for user-provided documents and permitted exports first; logged-in automation remains disabled
unless subscription terms explicitly permit the exact access pattern.

## Documentation

- [Market intelligence architecture](docs/market-intelligence-architecture.md)
- [Source policy](docs/source-policy.md)
- [Source registry](docs/source-registry.md)
- [Ingestion framework](docs/ingestion-framework.md)
- [Australian connectors](docs/australian-connectors.md)
- [Global connectors](docs/global-connectors.md)
- [Daily brief schema](docs/daily-brief-schema.md)
- [Daily brief synthesis](docs/daily-brief-synthesis.md)
- [Daily brief rendering](docs/daily-brief-rendering.md)
- [Daily brief operations](docs/daily-brief-operations.md)
- [Deployment guide](docs/deployment.md)
- [Private research architecture](docs/private-research-architecture.md)
- [Private research policy](docs/private-research-policy.md)
- [Private ingestion](docs/private-ingestion.md)
- [Private research schema](docs/private-research-schema.md)
- [Private research summarizer](docs/private-research-summarizer.md)
- [Private research library](docs/private-research-library.md)
- [Private digest](docs/private-digest.md)
- [Private research UI](docs/private-research-ui.md)
- [Optional Under the Radar connector stub](docs/private-undertheradar-connector.md)
- [Private research settings and storage](docs/private-research-storage.md)
- [Private release checklist](docs/private-release-checklist.md)

## Product Overview

The daily market-intelligence workflow:

1. Loads source items from legal APIs, RSS feeds, licensed feeds, user-provided files, or local
   fixtures.
2. Normalizes each item with attribution, terms metadata, timestamps, URLs, and tickers.
3. Deduplicates items and optionally stores them in a JSONL cache.
4. Synthesizes a validated `DailyMarketBrief` with a placeholder/mock client or OpenAI.
5. Renders dashboard, terminal, JSON, Markdown, HTML, plain text, and dry-run email output.

The original PDF workflow remains available for summarizing individual research PDFs into
structured `MarketInsightReport` output.

The private research workflow can import user-provided subscribed PDFs, local files/directories,
saved HTML/text/email files, and manual pasted text into a separate local SQLite store. It can
list those documents and produce a local placeholder summary for one imported document without
scraping a logged-in website.

The private recommendation schema captures company/ticker ratings, thesis points, risks,
catalysts, valuation notes, numbers to verify, and short source excerpts without storing full
subscribed articles or reports.

The private summarizer can turn an imported private document into that schema using the existing
chunking pipeline, an offline placeholder client, or an injected/OpenAI client with retrying
JSON validation. Its prompts frame output as a source summary, not personal financial advice.

The private library indexes structured summaries so local recommendations can be searched by
ticker, company, date range, rating, sector, and risk/catalyst keyword, with timeline and
document comparison helpers.

The private Streamlit tab provides a local password-gated workspace for importing files or
manual text, running the offline private summarizer, reviewing recommendations, checking
risks/catalysts/numbers to verify, viewing source citations, and downloading private
JSON/Markdown summaries.

The private digest renderer can produce daily or weekly single-user digests from indexed
subscribed research, including per-document summaries, per-ticker summaries, a recommendation
change log, short source references, JSON/Markdown/HTML outputs, and local `.eml` dry runs.

An optional Under the Radar connector stub exists for future personal automation design. It is
disabled by default, requires explicit environment and terms gates, and still refuses to perform
a live login or scrape.

## Source Policy

Allowed input patterns:

- official APIs;
- RSS feeds where automated access is permitted;
- paid or licensed feeds where the licence permits this use;
- user-provided files, exports, forwarded emails, or manual notes.

Do not scrape Bloomberg, Reuters, TradingView, Market Index, ASX pages, or similar sites unless
the specific access pattern is permitted by licence, API terms, written permission, or a
documented user export. Do not bypass logins, paywalls, bot controls, rate limits, or technical
access restrictions. Do not store or redistribute full copyrighted articles or paid reports.

## Supported Sources

The registry is conservative. Many sources are disabled until credentials, endpoint scope,
licence terms, and rate limits are configured.

| Source | Status | Access path |
| --- | --- | --- |
| Local fixtures/user files | Enabled for mock mode | `LocalFixtureConnector`, `MockConnector` |
| RBA RSS | Connector available | Official RSS feed |
| ABS | Connector available | Official ABS API or user export |
| ASIC media | Gated | Permitted API/feed/export only |
| FRED | Connector available | Official API with `FRED_API_KEY` |
| World Bank | Connector available | Official API |
| GDELT | Connector available | Public API metadata/links |
| NewsAPI | Connector available | API with `NEWSAPI_KEY` |
| ASX, Market Index | Disabled by default | Licensed API/feed or user export only |
| Bloomberg, Reuters | Disabled by default | Licensed feed/export only |
| TradingView | Disabled by default | Alerts, exports, embeds, or permitted API only |

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy the environment example if you plan to use hosted LLMs or credentialed connectors:

```bash
cp .env.example .env
```

The app does not auto-load `.env`; export variables in your shell or load them with your own
environment tooling.

## Environment Variables

| Variable | Required for | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | `--llm openai` | Billed to the OpenAI account/project that owns the key. |
| `MARKET_PDF_INSIGHTS_MODEL` | Optional | Overrides the default OpenAI model. |
| `FRED_API_KEY` | FRED connector | Keep in the environment or scheduler secret store. |
| `NEWSAPI_KEY` | NewsAPI connector | Keep in the environment or scheduler secret store. |
| `MARKET_PRIVATE_UI_PASSWORD_HASH` | Private Streamlit tab when password protection is enabled | Store a hash from `hash_private_password`, not a plaintext password. |
| `UNDERTHERADAR_CONNECTOR_ENABLED` | Future Under the Radar stub | Defaults to disabled; set only after terms confirmation. |
| `UNDERTHERADAR_USERNAME` | Future Under the Radar stub | Keep in environment/keyring/secret store; never commit. |
| `UNDERTHERADAR_PASSWORD` | Future Under the Radar stub | Keep in environment/keyring/secret store; never commit. |

No API key is hardcoded. Tests clear these environment variables and use fake clients,
fixtures, and mocks.

## CLI Examples

Run the fixture-backed public daily brief with no live APIs:

```bash
market-pdf-insights brief validate-config --config examples/daily_brief_config.toml
market-pdf-insights brief sources --config examples/daily_brief_config.toml
market-pdf-insights brief run \
  --config examples/daily_brief_config.toml \
  --date 2026-05-12 \
  --output outputs/daily-brief.json \
  --markdown outputs/daily-brief.md \
  --html outputs/daily-brief.html
```

Write a dry-run email file without sending:

```bash
market-pdf-insights brief send \
  --dry-run \
  --config examples/daily_brief_config.toml \
  --email-dry-run outputs/daily-brief.eml
```

Use OpenAI for daily brief synthesis:

```bash
export OPENAI_API_KEY="..."
market-pdf-insights brief run \
  --config examples/daily_brief_config.toml \
  --llm openai \
  --model gpt-4.1-mini
```

Summarize a PDF report:

```bash
market-pdf-insights summarize reports/small-caps-report-issue-700.pdf \
  --output report.json \
  --markdown report.md
```

Import and summarize private subscribed research you already possess:

```bash
market-pdf-insights private import ~/Downloads/under-the-radar-report.pdf
market-pdf-insights private list
market-pdf-insights private summarize private-abc123
market-pdf-insights private search --ticker EXR
market-pdf-insights private history --ticker EXR
market-pdf-insights private compare private-doc-a private-doc-b
market-pdf-insights private digest \
  --period weekly \
  --markdown outputs/private-digest.md \
  --html outputs/private-digest.html
```

## Streamlit Dashboard

Run the web app locally:

```bash
streamlit run src/market_pdf_insights/streamlit_app.py
```

The dashboard opens with the daily brief workflow backed by
`examples/daily_brief_config.toml` and `examples/daily_market_brief.json`, so it can render a
fixture brief without live APIs. It shows source status, disabled-source compliance notes,
executive summary, recap/day-ahead, themes, risks, watchlist impacts, citations, verification
flags, and JSON/Markdown/HTML downloads. A second tab keeps the PDF upload workflow.

The `Private Research` tab uses the local private store, `.private-research` by default. It can
import subscribed PDFs, saved emails, HTML/text files, or pasted notes; summarize and index them
with the offline placeholder path; show latest summaries, ticker history, recommendation detail,
risks, catalysts, numbers to verify, citations, and private digests; and download private
JSON/Markdown/HTML outputs. If
`[password_protection].enabled = true`, set `MARKET_PRIVATE_UI_PASSWORD_HASH` in the environment
or Streamlit secrets. Generate the hash with `hash_private_password`; do not store plaintext
passwords in settings.

## Email

Current email support is intentionally dry-run only. `DailyBriefEmailSettings` and
`PrivateDigestEmailSettings` store sender, recipient, subject prefix, and reply-to envelope
settings. `DryRunDailyBriefEmailWriter` and `DryRunPrivateDigestEmailWriter` write `.eml` or
text/HTML files locally. Future senders can implement the sender protocols for SMTP or a
provider API, with credentials supplied by environment variables or a secret store.

## Scheduling

Use an external scheduler; the app does not run a background daemon.

Cron example:

```cron
15 7 * * 1-5 cd /path/to/flying-the-radar && \
  MARKET_PDF_INSIGHTS_MODEL=gpt-4.1-mini \
  market-pdf-insights brief run --config daily-brief.toml
```

GitHub Actions example:

```yaml
name: Daily market brief
on:
  schedule:
    - cron: "15 21 * * 0-4"
  workflow_dispatch:
jobs:
  brief:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: market-pdf-insights brief run --config examples/daily_brief_config.toml
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
```

Store credentials in the scheduler's secret manager, not in TOML, fixtures, docs, or source
control.

## Citations And Verification

Daily brief citations live in `DailyMarketBrief.sources`. Nested sections reference those
records by `citation_id`, and each citation preserves source name, title, URL, publication time,
retrieval time, terms URL, licence notes, and a short snippet. The schema rejects nested
citations that are missing from the top-level catalogue.

Claims that need human review are stored in `DailyMarketBrief.verification_flags`. Numbers,
dates, prices, forecasts, yields, legal/regulatory claims, and stale source items should be
checked against primary sources before use.

## Architecture

```mermaid
flowchart TD
    A[Permitted APIs RSS licensed feeds fixtures] --> B[Source policy and config]
    B --> C[Connectors]
    C --> D[NormalizedMarketItem]
    D --> E[Deduplication and JSONL cache]
    E --> F{Daily brief client}
    F --> G[MockBriefLLMClient]
    F --> H[OpenAIDailyBriefClient]
    G --> I[DailyMarketBrief]
    H --> I
    I --> J[Renderers]
    J --> K[CLI terminal]
    J --> L[JSON Markdown HTML text]
    J --> M[Dry-run email]
    J --> N[Streamlit dashboard]
    O[PDF upload or file] --> P[pdf_loader and chunker]
    P --> Q[PDF summary client]
    Q --> R[MarketInsightReport]
    R --> N
```

Core modules:

- `source_policy.py`: source-use and advice-boundary guardrails.
- `source_registry.py`: source metadata, credentials, capabilities, and compliance checks.
- `ingestion.py`: connectors, normalization, deduplication, JSONL cache, and test mocks.
- `australian_connectors.py`: RBA, ABS, ASIC scaffolding and disabled ASX/Market Index guards.
- `global_connectors.py`: FRED, World Bank, GDELT, NewsAPI, and licensed-source placeholders.
- `daily_brief_schema.py`: validated daily brief output contract.
- `daily_brief_synthesis.py`: mock/OpenAI daily brief synthesis.
- `daily_brief_rendering.py`: JSON, Markdown, HTML, text, terminal, and dry-run email rendering.
- `daily_brief_config.py`: TOML configuration and validation.
- `daily_brief_runner.py`: configured ingestion, synthesis, output writing, and dry-run email.
- `private_ingestion.py`: private PDFs, local files, saved emails, and manual text imports.
- `private_research_library.py`: private recommendation search, history, and comparison.
- `private_research_schema.py`: structured private stock recommendation schema.
- `private_research_synthesis.py`: private chunk notes and structured recommendation synthesis.
- `private_research_storage.py`: local SQLite store for private documents, summaries, citations.
- `private_digest.py`: private daily/weekly digest rendering and dry-run email output.
- `private_settings.py`: local-only private settings, retention, and password hash references.
- `private_undertheradar_connector.py`: disabled connector stub and safety gates.
- `cli.py`: `market-pdf-insights summarize`, `market-pdf-insights brief ...`, and private commands.
- `streamlit_app.py`: daily brief dashboard, PDF report tab, and private research tab.

## Development

Run tests and lint:

```bash
PYTHONPATH=src python3 -m pytest
PYTHONPATH=src python3 -m unittest discover -s tests
ruff check .
```

The test suite is offline. It blocks live network calls, clears real API key environment
variables, and uses fixture payloads plus mock clients.

Before using the private companion, review the [private release checklist](docs/private-release-checklist.md).

## Limitations

- Placeholder and mock clients are deterministic and useful for tests/local plumbing, not
  high-quality market analysis.
- OpenAI output is schema-validated, but factual correctness still depends on source quality and
  human verification.
- Live source connectors require source-specific endpoint scope, credentials, rate limits, and
  terms review before being enabled.
- The app does not send real email yet; only dry-run email files are written.
- The app does not include a background scheduler.
- Extracted PDF text quality depends on the source document; scanned PDFs without OCR may
  produce little useful text.
- Generated outputs can be incomplete, stale, or misleading.

## Financial Disclaimer

This project summarizes source documents and public market information. It is not financial,
investment, tax, legal, or accounting advice. Outputs may be incomplete, inaccurate, stale, or
misleading. Do not make investment decisions based only on this tool. Always verify claims
against primary sources and consult qualified professionals where appropriate.

## Contributing

Keep changes small, tested, and consistent with the current module boundaries.

Before opening a pull request:

- Run `python3 -m pytest`.
- Run `ruff check .`.
- Avoid committing generated outputs, cache directories, local PDFs, or secrets.
- Do not include real API keys in tests, fixtures, examples, docs, or screenshots.
- Prefer mock clients and fixture payloads so CI does not make live API calls.
