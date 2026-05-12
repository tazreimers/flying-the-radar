# Private Research UI

The private Streamlit tab is a local, single-user workspace for subscribed research that the
user already possesses. It is for organizing and summarizing private documents, not for
redistribution and not for personal financial advice.

## Run Locally

```bash
streamlit run src/market_pdf_insights/streamlit_app.py
```

Open the `Private Research` tab. By default it uses `.private-research` as the local data
directory and creates a SQLite database plus extracted-text sidecars there.

The UI does not call live market APIs, log in to Under the Radar, scrape websites, or download
subscription content. Synthetic PDFs and user-uploaded files are summarized through the local
placeholder path unless code is explicitly wired to an injected LLM client later.

## Password Gate

Password protection is controlled by private settings. Settings reference a hash environment
variable; they must not contain the raw password.

```toml
[password_protection]
enabled = true
password_hash_env_var = "MARKET_PRIVATE_UI_PASSWORD_HASH"
session_timeout_minutes = 60
```

Generate a hash locally:

```python
from getpass import getpass
from market_pdf_insights.private_settings import hash_private_password

print(hash_private_password(getpass("Private UI password: ")))
```

Then set the hash through the environment or Streamlit secrets:

```bash
export MARKET_PRIVATE_UI_PASSWORD_HASH='pbkdf2_sha256$...'
```

```toml
# .streamlit/secrets.toml
MARKET_PRIVATE_UI_PASSWORD_HASH = "pbkdf2_sha256$..."
```

When password protection is enabled, the tab reads only the configured hash and stores only a
session expiry timestamp in Streamlit session state.

## Screens

- `Import`: upload PDF, saved email, HTML/text/Markdown, or paste manual text, then summarize
  and index the selected document.
- `Library`: document table plus local recommendation search by ticker, company, rating,
  sector, keyword, and date.
- `Summaries`: latest structured private summaries with JSON and Markdown downloads.
- `Recommendation`: focused company/ticker rating, thesis, target, risks, catalysts, and
  numbers to verify.
- `History`: ticker recommendation timeline from locally indexed summaries.
- `Risks`: consolidated risk, catalyst, and unresolved verification-question views.
- `Citations`: source-light excerpts and page/section labels from structured summaries.
- `Digest`: daily or weekly private digest preview with JSON, Markdown, and HTML downloads.

Every private screen displays the private-use disclaimer: private research organization only,
not financial advice, and no redistribution of subscribed material or generated private
summaries.

## Current Limits

The UI is intentionally local and conservative. It does not implement live Under the Radar
automation, browser login, scraping, real email sending, or multi-user deployment security. Treat
the password gate as a local access guard, and use operating-system disk encryption or deployment
controls for stronger protection.
