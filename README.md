# Market PDF Insights

`market-pdf-insights` accepts a PDF containing stock market commentary or financial
research and returns a structured JSON summary.

This first pass includes a PyMuPDF-backed PDF extraction layer, Pydantic output schema,
and a deterministic placeholder summarizer. Hosted LLM summarization is not implemented yet.

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
  "document_title": "Research Note",
  "executive_summary": "...",
  "market_stance": "mixed",
  "key_claims": [],
  "supporting_evidence": [],
  "risks": [],
  "sectors_mentioned": [],
  "companies_or_tickers_mentioned": [],
  "macro_assumptions": [],
  "numbers_to_verify": [],
  "unanswered_questions": [],
  "confidence_score": 0.35,
  "source_file": "path/to/file.pdf",
  "metadata": {}
}
```

For a fuller validated example, see `examples/market_insight_report.json`.

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
- `insight_schema.py` defines the Pydantic structured output models.
- `summarizer.py` orchestrates loading, chunking, and summarization.
- `cli.py` exposes the `market-pdf-insights` command.
