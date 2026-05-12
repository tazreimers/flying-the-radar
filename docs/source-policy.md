# Source Policy

The daily market-intelligence brief must use sources in a way that is consistent with their
terms, copyright, and data-licensing requirements. A page being publicly viewable does not
mean it can be scraped, stored, summarized at scale, or redistributed.

## Allowed Input Patterns

- Official APIs.
- RSS feeds where automated access is permitted.
- Paid or licensed feeds where the licence permits the intended use.
- User-provided uploads.
- Forwarded emails or saved files that the user is entitled to use.
- Manual entry.

## Prohibited or Disabled by Default

- Scraping websites whose terms prohibit automated access.
- Bypassing login, paywall, rate-limit, bot-detection, or technical controls.
- Storing or redistributing full copyrighted articles or paid reports.
- Using Bloomberg, Reuters, TradingView, Market Index, ASX pages, or similar sources through
  scraping unless a permitted API, feed, export, or written licence is configured.
- Hardcoding credentials or API keys.

## Metadata Requirements

Every source item should preserve:

- source id and display name;
- URL when available;
- title;
- published timestamp when available;
- retrieval timestamp;
- access method;
- terms/licence notes;
- short citations used in generated summaries.

## Advice Boundary

The app should summarize factual information and general market commentary. It should not
personalize output to a user's financial objectives, situation, or needs, and should not tell
users to buy, sell, hold, or rebalance.

References for future maintainers:

- ASIC financial advice obligations:
  https://asic.gov.au/regulatory-resources/financial-services/financial-advice/running-a-financial-advice-business/obligations-when-giving-financial-advice/
- ASIC financial product advice overview:
  https://asic.gov.au/regulatory-resources/financial-services/giving-financial-product-advice/
- Australian copyright basics:
  https://www.ag.gov.au/rights-and-protections/copyright/copyright-basics

