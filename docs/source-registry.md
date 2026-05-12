# Source Registry

`market_pdf_insights.source_registry` is the central catalogue for public
market-intelligence inputs. It records what each source is, how it may be accessed, what
credentials are required, and what compliance notes must travel with fetched content.

The default registry is conservative: sources that may require a licence, explicit API
permission, user export, or terms review are disabled until a connector is built and the
access pattern is approved.

## Models

- `SourceDefinition`: the complete source record.
- `SourceCapability`: access method, fetch strategy, automation flag, and enabled flag.
- `SourceTerms`: rate-limit notes, terms notes, terms URL, redistribution flag, and citation
  requirement.
- `SourceCredentialPolicy`: auth type and environment variable names for credentials.
- `SourceFetchResult`: downstream metadata wrapper for fetched source content.
- `SourceRegistry`: in-memory registry with `get`, `enabled_sources`, and
  `assert_fetch_allowed`.

Use `SourceRegistry.from_definitions(...)` for code-defined registries. Use
`SourceRegistry.from_config(...)` once YAML, TOML, or environment-derived config has been
parsed into dictionaries.

## Access Methods

Automated connectors may only fetch sources whose access method is an approved automated
method and whose `automation_allowed` and `enabled` flags are both true.

Approved automated methods:

- `api`
- `rss`
- `licensed_feed`

Non-fetch methods:

- `user_upload`
- `email_forward`
- `manual_entry`

Blocked method:

- `disabled`

## Initial Sources

Australian market sources:

- `rba-rss`: official RBA public feed, disabled until connector settings are configured.
- `abs-api`: official ABS API, disabled until connector settings are configured.
- `asic-media`: ASIC public releases, disabled until connector settings are configured.
- `asx-announcements`: disabled until an official endpoint, licensed provider, or documented
  user export is configured.
- `market-index`: disabled until a permitted API/feed/licence is configured.

Global macro sources:

- `fred-api`: credentialed FRED API source using `FRED_API_KEY`, disabled by default.
- `world-bank-api`: official World Bank API, disabled until connector settings are configured.
- `imf-api`: official IMF data access, disabled until connector settings are configured.
- `oecd-api`: official OECD data access, disabled until connector settings are configured.
- `ecb-data-portal`: official ECB data access, disabled until connector settings are
  configured.

News/commentary sources:

- `gdelt-api`: public GDELT API, disabled until query and attribution settings are configured.
- `newsapi`: credentialed NewsAPI source using `NEWSAPI_KEY`, disabled by default.
- `bloomberg`: disabled unless licensed API/access or a permitted user export is configured.
- `reuters`: disabled unless licensed API/access or a permitted user export is configured.

Charts/watchlists:

- `tradingview`: disabled for page automation. Use only user exports, alerts/webhooks,
  embeds, or permitted API/licensed access.

User-provided inputs:

- `user-upload`: enabled for manual uploads, but rejected by automated fetch checks.

## Connector Rule

Every connector should call:

```python
source = default_source_registry().assert_fetch_allowed("source-id")
```

before making network requests. Downstream artifacts should preserve the `SourceAttribution`
created by `source.attribution(...)` and the source `SourceTerms`.
