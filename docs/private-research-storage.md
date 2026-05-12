# Private Research Settings And Storage

Pivot 3 private research stores local metadata for single-user subscribed research. It is
separate from the public daily brief cache.

## Settings

`market_pdf_insights.private_settings` defines `PrivateResearchSettings` with:

- `local_data_dir`: local private data directory, default `.private-research`;
- `database_name`: local SQLite filename;
- `secrets_strategy`: `environment`, `os_keyring`, or `external_secret_manager`;
- `import_sources`: enabled flags for upload, local file, email forward, manual entry,
  subscription export, and gated logged-in automation;
- `retention`: raw document, extracted text, summary, and metadata retention policy;
- `password_protection`: private UI password settings.

Settings files must not contain raw passwords, API tokens, or subscription credentials. Password
protection uses a hash reference such as `MARKET_PRIVATE_UI_PASSWORD_HASH`; the hash value should
come from an environment variable, OS keyring, or documented secret manager.

Generate a password hash in Python:

```python
from market_pdf_insights.private_settings import hash_private_password

print(hash_private_password("your local UI password"))
```

Store the resulting hash in your local environment, not in source control.

## Raw Document Storage

Raw subscribed documents are not stored by default. The default policy creates only the SQLite
database and an extracted-text directory. If raw document retention is explicitly enabled, raw
files belong under `.private-research/raw-documents/`, which is ignored by git.

## SQLite Store

`market_pdf_insights.private_research_storage` creates three tables:

- `private_documents`: document metadata, attribution JSON, optional raw/text path references;
- `private_summaries`: generated private summaries, labels, tickers, risks, and catalysts;
- `private_citations`: source-backed citation locations and short snippets.

The store supports:

- initialization from settings;
- document, summary, and citation insert/query;
- document deletion with cascaded summaries/citations;
- optional file deletion for local raw/text sidecars;
- retention cleanup for old summaries, metadata, raw paths, and extracted text paths.

## Boundary

The current private workflow can import user-provided PDFs, local files/directories, saved
HTML/text/email files, and manual pasted text into this store. It can also create a local
placeholder summary from extracted text.

It does not implement Under the Radar live login or scraping. The optional Under the Radar
connector is only a disabled safety stub for future design. The app also does not yet implement
password UI, search/Q&A, a private digest, or LLM-backed recommendation extraction. Later steps
should build on these models while preserving the no-redistribution and no-personal-advice
boundaries.
