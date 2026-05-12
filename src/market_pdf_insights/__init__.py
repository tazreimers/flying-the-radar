"""Tools for summarizing market research PDFs into structured insights."""

from market_pdf_insights.insight_schema import (
    KeyClaim,
    MacroAssumption,
    MarketInsightReport,
    MentionedAsset,
    Risk,
    VerificationItem,
)
from market_pdf_insights.llm_client import (
    LLMConfigurationError,
    LLMResponseValidationError,
    LLMSummarizationError,
    MockLLMClient,
    OpenAISummaryClient,
    PlaceholderLLMClient,
)
from market_pdf_insights.pdf_loader import extract_pdf_text
from market_pdf_insights.summarizer import MarketPdfSummarizer, summarize_pdf

__all__ = [
    "KeyClaim",
    "LLMConfigurationError",
    "LLMResponseValidationError",
    "LLMSummarizationError",
    "MacroAssumption",
    "MarketInsightReport",
    "MarketPdfSummarizer",
    "MentionedAsset",
    "MockLLMClient",
    "OpenAISummaryClient",
    "PlaceholderLLMClient",
    "Risk",
    "VerificationItem",
    "extract_pdf_text",
    "summarize_pdf",
]

__version__ = "0.1.0"
