# Deployment Guide

This app is safest to run as a scheduled CLI job plus an optional local Streamlit dashboard.
There is no background daemon in the MVP.

## Pre-Flight Checklist

- Confirm every enabled source uses an allowed access path: official API, RSS, licensed feed,
  user-provided export, email/manual ingestion, or local fixture.
- Keep Bloomberg, Reuters, TradingView, Market Index, and ASX page automation disabled unless a
  permitted API, feed, licence, or export path is documented.
- Store credentials in environment variables or the scheduler's secret store.
- Run `market-pdf-insights brief validate-config --config daily-brief.toml`.
- Review `DailyMarketBrief.verification_flags` before relying on generated claims.
- Preserve `DailyMarketBrief.sources` in stored JSON and downstream outputs.

## Local Fixture Run

```bash
market-pdf-insights brief run \
  --config examples/daily_brief_config.toml \
  --date 2026-05-12 \
  --output outputs/daily-brief.json \
  --markdown outputs/daily-brief.md \
  --html outputs/daily-brief.html
```

This uses fixture/mock mode and does not need live APIs or credentials.

## Cron

Run once each weekday morning in your local timezone. Put secrets in the crontab environment or a
separate environment file with appropriate filesystem permissions.

```cron
OPENAI_API_KEY=...
FRED_API_KEY=...
NEWSAPI_KEY=...
15 7 * * 1-5 cd /path/to/flying-the-radar && \
  market-pdf-insights brief run --config daily-brief.toml
```

## GitHub Actions

Store keys in repository or organization secrets, not in TOML.

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
      - run: market-pdf-insights brief validate-config --config daily-brief.toml
      - run: |
          market-pdf-insights brief run \
            --config daily-brief.toml \
            --output outputs/daily-brief.json \
            --markdown outputs/daily-brief.md \
            --html outputs/daily-brief.html
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
      - uses: actions/upload-artifact@v4
        with:
          name: daily-brief
          path: outputs/
```

## Email

`brief send --dry-run` writes a local `.eml`, `.html`, or `.txt` output. It does not send real
email.

Future SMTP or provider senders should implement `DailyBriefEmailSender` and read credentials
from environment variables or a secret manager. Do not add SMTP usernames, passwords, tokens, or
provider API keys to config files, fixtures, tests, screenshots, or documentation.

## Operational Review

Generated JSON should be retained when possible because it contains:

- `sources`: source catalogue with citation ids, URLs, retrieval timestamps, terms URLs, and
  licence notes;
- `verification_flags`: claims and datapoints requiring primary-source checks;
- `confidence_score`: synthesis confidence, not a guarantee of factual accuracy.

Before distribution, verify numerical market data, forecasts, prices, legal/regulatory claims,
and stale source items against primary sources.
