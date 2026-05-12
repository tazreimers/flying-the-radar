"""Release safety checks for the private research companion."""

from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).parents[1]
PUBLIC_MODULES = [
    "src/market_pdf_insights/australian_connectors.py",
    "src/market_pdf_insights/daily_brief_config.py",
    "src/market_pdf_insights/daily_brief_rendering.py",
    "src/market_pdf_insights/daily_brief_runner.py",
    "src/market_pdf_insights/daily_brief_schema.py",
    "src/market_pdf_insights/daily_brief_synthesis.py",
    "src/market_pdf_insights/global_connectors.py",
    "src/market_pdf_insights/ingestion.py",
    "src/market_pdf_insights/source_policy.py",
    "src/market_pdf_insights/source_registry.py",
]


def test_gitignore_blocks_private_data_and_secret_files() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in [".env", ".env.*", ".private-research/", "outputs/", "*.eml"]:
        assert pattern in gitignore
    assert "!.env.example" in gitignore


def test_no_obvious_api_keys_or_private_passwords_are_committed() -> None:
    checked_suffixes = {".py", ".md", ".toml", ".txt", ".example", ".json", ".jsonl", ".xml"}
    secret_patterns = [
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"(?m)^(?![ \t]*#)[ \t]*OPENAI_API_KEY[ \t]*=[ \t]*['\"]?sk-", re.IGNORECASE),
        re.compile(
            r"(?m)^(?![ \t]*#)[ \t]*FRED_API_KEY[ \t]*=[ \t]*['\"]?[A-Za-z0-9]{12,}",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?m)^(?![ \t]*#)[ \t]*NEWSAPI_KEY[ \t]*=[ \t]*['\"]?[A-Za-z0-9]{12,}",
            re.IGNORECASE,
        ),
        re.compile(
            r"pbkdf2_sha256\$\d+\$[A-Za-z0-9+/=_-]+\$[A-Za-z0-9+/=_-]+",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?m)^(?![ \t]*#)[ \t]*UNDERTHERADAR_PASSWORD[ \t]*=[ \t]*['\"]?[^ \t\r\n'\"#]+",
            re.IGNORECASE,
        ),
    ]
    ignored_parts = {".git", ".pytest_cache", ".ruff_cache", "__pycache__"}

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        if path.suffix not in checked_suffixes and path.name != ".env.example":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in secret_patterns:
            assert not pattern.search(text), f"secret-like value matched in {path}"


def test_public_daily_brief_modules_do_not_import_private_research_modules() -> None:
    for relative_path in PUBLIC_MODULES:
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "market_pdf_insights.private_" not in source, relative_path
