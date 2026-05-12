# Market PDF Insights

`market-pdf-insights` accepts a PDF containing stock market commentary or financial
research and returns a structured JSON summary.

This first pass includes a PyMuPDF-backed PDF extraction layer, Pydantic output schema,
a deterministic placeholder summarizer, and an OpenAI-backed summarization client.

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

The command prints a concise terminal summary. Use `--output` to save the full
structured JSON report:

```bash
market-pdf-insights summarize path/to/file.pdf --output report.json
```

For optional Markdown output:

```bash
market-pdf-insights summarize path/to/file.pdf --output report.json --markdown report.md
```

The JSON report has this shape:

```json
{
  "document_title": "Research Note",
  "executive_summary": "...",
  "market_stance": "mixed",
  "investment_thesis": "...",
  "bullish_arguments": [],
  "bearish_arguments": [],
  "valuation_assumptions": [],
  "time_horizon": "medium term",
  "catalysts": [],
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

To change chunk size:

```bash
market-pdf-insights summarize path/to/file.pdf --max-chars 6000
```

To use the OpenAI-backed summarizer, set an API key and select the OpenAI backend:

```bash
export OPENAI_API_KEY="..."
market-pdf-insights summarize path/to/file.pdf --llm openai
```

The OpenAI client defaults to `MARKET_PDF_INSIGHTS_MODEL` or `gpt-4.1-mini`.
You can override it per run:

```bash
market-pdf-insights summarize path/to/file.pdf --llm openai --model gpt-4.1-mini
```

The OpenAI prompts are designed for document analysis only. They ask the model to extract
the investment thesis, bullish and bearish arguments, valuation assumptions, macro
assumptions, sector implications, named assets, time horizon, catalysts, risks, and claims
requiring external verification. They explicitly instruct the model not to provide
financial advice.

## Streamlit App

Run the web app locally:

```bash
streamlit run src/market_pdf_insights/streamlit_app.py
```

The app accepts a PDF upload, displays the executive summary, stance, claims, bullish
points, risks, assets, and numbers to verify, and provides JSON and Markdown downloads.

## Development

Run tests with either command:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python3 -m pytest
```

## Current Modules

- `pdf_loader.py` validates a PDF path and extracts ordered page text with PyMuPDF.
- `chunker.py` splits long research text into overlapping chunks.
- `llm_client.py` provides placeholder, mock, and OpenAI summarization clients.
- `insight_schema.py` defines the Pydantic structured output models.
- `streamlit_app.py` exposes the upload-and-summarize web app.
- `summarizer.py` orchestrates loading, chunking, and summarization.
- `cli.py` exposes the `market-pdf-insights` command.
