# Market PDF Insights

`market-pdf-insights` accepts a PDF containing stock market commentary or financial research and returns a structured JSON summary.

This first pass is a typed scaffold with deterministic placeholder summarization. PDF text extraction uses `pypdf`, with a limited plain-text fallback for fixtures and early development.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI

```bash
market-pdf-insights summarize path/to/file.pdf
```

The command writes JSON to stdout:

```json
{
  "source_file": "path/to/file.pdf",
  "executive_summary": "...",
  "key_themes": ["earnings", "interest rates"],
  "company_mentions": [],
  "risks": [],
  "opportunities": [],
  "disclaimers": [],
  "sections": [],
  "metadata": {}
}
```

For compact output:

```bash
market-pdf-insights summarize path/to/file.pdf --compact
```

## Development

Run tests with either command:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m pytest
```

## Current Modules

- `pdf_loader.py` validates a PDF path and extracts text.
- `chunker.py` splits long research text into overlapping chunks.
- `llm_client.py` provides a placeholder summarization client.
- `insight_schema.py` defines the structured summary dataclasses.
- `summarizer.py` orchestrates loading, chunking, and summarization.
- `cli.py` exposes the `market-pdf-insights` command.
