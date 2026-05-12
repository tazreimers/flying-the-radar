# Pivot 2 Prompts

These prompts evolve the app into a public/legal daily market-intelligence briefing system.
This branch should use permitted sources only: official APIs, RSS feeds, licensed providers,
user-provided files, or email/manual ingestion.

## Assumptions

- Codex is running from the repository root.
- Pivot 1 functionality exists and should be preserved.
- The prompts are intended to be executed in numeric order.
- Tests must not make live network or OpenAI calls.
- Do not scrape sources whose terms prohibit automated access.
- Keep all source attribution, retrieval metadata, and compliance notes first-class.

## Execution Order

Run `01-product-guardrails-and-architecture.txt` through
`12-documentation-and-deployment-polish.txt` sequentially. Start with guardrails and source
registry work before implementing connectors, then add schemas, synthesis, outputs, CLI,
dashboard, tests, and documentation.

## Outcome

After this sequence, the app should generate a daily morning market brief covering Australian
and global market intelligence, save JSON/Markdown/HTML/email-dry-run outputs, and provide a
clean CLI and Streamlit dashboard without bypassing paywalls or source terms.

