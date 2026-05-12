# Market PDF Insights

`market-pdf-insights` accepts a PDF containing stock market commentary or financial research and returns a structured JSON summary.

This first pass includes a PyMuPDF-backed PDF extraction layer and a deterministic placeholder summarizer. Hosted LLM summarization is not implemented yet.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## PDF Extraction

Use `extract_pdf_text` to extract ordered page text with page markers:

```python
from pathlib import Path

from market_pdf_insights.pdf_loader import extract_pdf_text

text = extract_pdf_text(Path("reports/small-caps-report-issue-700.pdf"))
print(text[:1_000])
```

Output includes page markers:

```text
--- Page 1 ---
First page text...

--- Page 2 ---
Second page text...
```

## CLI

```bash
market-pdf-insights summarize path/to/file.pdf
```

The command currently writes placeholder JSON to stdout:

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

- `pdf_loader.py` validates a PDF path and extracts ordered page text with PyMuPDF.
- `chunker.py` splits long research text into overlapping chunks.
- `llm_client.py` provides a placeholder summarization client.
- `insight_schema.py` defines the structured summary dataclasses.
- `summarizer.py` orchestrates loading, chunking, and summarization.
- `cli.py` exposes the `market-pdf-insights` command.
