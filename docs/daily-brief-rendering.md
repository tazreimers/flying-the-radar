# Daily Brief Rendering

`market_pdf_insights.daily_brief_rendering` turns a validated `DailyMarketBrief` into output
formats for daily workflows.

## Renderers

- `render_daily_brief_json`: JSON payload for storage or integrations.
- `render_daily_brief_markdown`: Markdown report for files or app previews.
- `render_daily_brief_plain_text`: plain text email body.
- `render_daily_brief_html`: standalone HTML email body.
- `render_daily_brief_terminal_summary`: compact CLI/status summary.
- `save_daily_brief_outputs`: writes selected JSON, Markdown, HTML, and text files locally.

Rendered outputs include the executive summary, yesterday recap, day ahead, top themes,
Australia market, global macro, commodities, currencies/rates, watchlist impacts, calendar,
macro events, risks, sources, verification flags, and disclaimer.

## Email Abstraction

`DailyBriefEmailSender` is the sender protocol. It has no provider-specific credentials or SMTP
configuration.

`DailyBriefEmailSettings` stores only the envelope-level settings needed later:

- sender
- recipients
- subject prefix
- optional reply-to

`DryRunDailyBriefEmailWriter` implements the sender protocol but does not send email. It writes
either:

- a local `.eml` file containing multipart text and HTML; or
- separate `.txt` and `.html` files.

Tests use only the dry-run writer, so no real email is sent.
