# Optional Under The Radar Connector Stub

The app includes a disabled-by-default Under the Radar connector stub for possible future
personal automation. It does not log in, scrape, download reports, or perform browser
automation.

## Gates

The stub refuses to proceed unless all of these are true:

- `UNDERTHERADAR_CONNECTOR_ENABLED=true`;
- private settings enable `import_sources.logged_in_automation`;
- private settings confirm logged-in automation terms;
- connector-specific terms permission is confirmed in code/config;
- username and password references are supplied through environment variables or an equivalent
  secret resolver.

Even when every gate is satisfied, `UnderTheRadarConnector.import_reports()` raises a clear
not-implemented error. This is intentional: a real connector should only be built after the
subscription terms and a stable permitted access path are confirmed.

## Safer Alternatives

Prefer user-driven inputs:

- download PDFs manually and import them with `market-pdf-insights private import`;
- forward or save subscriber emails and import the saved files;
- use an official Under the Radar export, feed, or API if available;
- consider browser automation only after explicit legal/terms confirmation.

## Environment Variables

The default variable names are:

```bash
UNDERTHERADAR_CONNECTOR_ENABLED=false
UNDERTHERADAR_USERNAME=
UNDERTHERADAR_PASSWORD=
```

Do not store subscription credentials in TOML, fixtures, source code, docs, or committed `.env`
files. Tests inject fake environment mappings and clear these variables so no real credential is
used.
