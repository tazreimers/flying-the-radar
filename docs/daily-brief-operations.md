# Daily Brief Operations

The daily brief CLI is configured with TOML and can run fully from local fixtures for
development and tests.

## Commands

```bash
market-pdf-insights brief validate-config --config examples/daily_brief_config.toml
market-pdf-insights brief sources --config examples/daily_brief_config.toml
market-pdf-insights brief run --config examples/daily_brief_config.toml --date 2026-05-12
market-pdf-insights brief send --dry-run --config examples/daily_brief_config.toml
```

`brief run` can also save direct outputs:

```bash
market-pdf-insights brief run \
  --config examples/daily_brief_config.toml \
  --date 2026-05-12 \
  --output outputs/brief.json \
  --markdown outputs/brief.md \
  --html outputs/brief.html \
  --llm placeholder
```

`brief send --dry-run` writes a local `.eml`, `.html`, or `.txt` output. It does not send real
email and does not contain SMTP or provider credentials.

## Config

Use TOML. YAML files are rejected until an optional YAML parser is deliberately added.

Key sections:

- `[[sources]]`: source enablement, connector kind, source category, fixture/API/RSS path, terms,
  and required environment variable names.
- `watchlist`: tickers, assets, macro indicators, or topics used by synthesis.
- `[regions]`: primary region, timezone label, and region list.
- `[ingestion]`: JSONL cache path and lookback window.
- `[llm]`: `placeholder` or `openai`, plus an optional model.
- `[output]`: JSON, Markdown, HTML, text, or email dry-run paths.
- `[email]`: sender, recipients, subject prefix, and reply-to. These are envelope settings only.

API keys are referenced by environment variable names, never stored in config. For example, a
source can set `required_env_vars = ["NEWSAPI_KEY"]`; validation then checks that the variable is
present before a run.

## Scheduling

No background daemon is required. Use the operating environment to call the CLI once each morning:

```cron
15 7 * * 1-5 cd /path/to/flying-the-radar && \
  market-pdf-insights brief run --config daily-brief.toml
```

For hosted operation, the same command can be run from GitHub Actions, systemd timers, launchd,
Windows Task Scheduler, or a container scheduler. Keep secrets in the scheduler's environment or
secret store, not in TOML.

Minimal GitHub Actions shape:

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
      - run: market-pdf-insights brief run --config daily-brief.toml
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
```

See [Deployment Guide](deployment.md) for a fuller checklist.
