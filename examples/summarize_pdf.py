"""Example usage of the market_pdf_insights Python API."""

from __future__ import annotations

import argparse
from pathlib import Path

from market_pdf_insights import summarize_pdf


def main() -> int:
    """Summarize a PDF path supplied on the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", type=Path)
    args = parser.parse_args()

    summary = summarize_pdf(args.pdf_path)
    print(summary.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

