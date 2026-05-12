"""LLM client interfaces and summarization implementations."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
from typing import Any, Protocol, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from market_pdf_insights.insight_schema import (
    AssetType,
    KeyClaim,
    MacroAssumption,
    MarketInsightReport,
    MentionedAsset,
    Risk,
    VerificationItem,
)


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
MARKET_MODEL_ENV = "MARKET_PDF_INSIGHTS_MODEL"

TModel = TypeVar("TModel", bound=BaseModel)


class LLMSummarizationError(RuntimeError):
    """Base error for hosted LLM summarization failures."""


class LLMConfigurationError(LLMSummarizationError):
    """Raised when a hosted LLM client is missing required configuration."""


class LLMResponseValidationError(LLMSummarizationError):
    """Raised when an LLM response cannot be parsed into the expected schema."""


class SummaryClient(Protocol):
    """Protocol implemented by clients that can summarize document chunks."""

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        source_file: str | None = None,
    ) -> MarketInsightReport:
        """Summarize text chunks from a source document."""


class ChunkInsightNotes(BaseModel):
    """Structured notes extracted from one source chunk before final synthesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_index: int = Field(ge=0)
    summary: str = Field(min_length=1)
    investment_thesis: str | None = Field(default=None)
    bullish_arguments: list[str] = Field(default_factory=list)
    bearish_arguments: list[str] = Field(default_factory=list)
    valuation_assumptions: list[str] = Field(default_factory=list)
    time_horizon: str | None = Field(default=None)
    catalysts: list[str] = Field(default_factory=list)
    key_claims: list[KeyClaim] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    sectors_mentioned: list[str] = Field(default_factory=list)
    companies_or_tickers_mentioned: list[MentionedAsset] = Field(default_factory=list)
    macro_assumptions: list[MacroAssumption] = Field(default_factory=list)
    numbers_to_verify: list[VerificationItem] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)


class OpenAISummaryClient:
    """Summarize market research chunks using the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        openai_client: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to zero.")

        self.model = model or os.environ.get(MARKET_MODEL_ENV) or DEFAULT_OPENAI_MODEL
        self.max_retries = max_retries
        self._client = openai_client or self._build_client(api_key)

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        source_file: str | None = None,
    ) -> MarketInsightReport:
        """Summarize chunks into notes, then synthesize one validated report."""

        if not chunks:
            raise ValueError("At least one text chunk is required for summarization.")

        notes = [
            self._summarize_chunk(chunk, chunk_index=index)
            for index, chunk in enumerate(chunks)
        ]
        report = self._synthesize_report(notes, source_file=source_file)
        metadata = {
            **report.metadata,
            "chunk_count": len(chunks),
            "note_count": len(notes),
            "model": self.model,
            "llm_provider": "openai",
        }
        return report.model_copy(
            update={
                "source_file": report.source_file or source_file,
                "metadata": metadata,
            }
        )

    def _build_client(self, api_key: str | None) -> Any:
        """Build the OpenAI SDK client, loading the API key from the environment."""

        resolved_api_key = api_key or os.environ.get(OPENAI_API_KEY_ENV)
        if not resolved_api_key:
            raise LLMConfigurationError(
                f"{OPENAI_API_KEY_ENV} is required when using OpenAISummaryClient."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The openai package is required for OpenAISummaryClient."
            ) from exc

        return OpenAI(api_key=resolved_api_key)

    def _summarize_chunk(self, chunk: str, *, chunk_index: int) -> ChunkInsightNotes:
        """Create structured notes for a single chunk."""

        prompt = (
            "Summarize this market research PDF chunk into structured notes.\n\n"
            f"Chunk index: {chunk_index}\n\n"
            f"{chunk}"
        )
        return self._request_json_model(
            ChunkInsightNotes,
            [
                {"role": "system", "content": _CHUNK_NOTES_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    def _synthesize_report(
        self,
        notes: Sequence[ChunkInsightNotes],
        *,
        source_file: str | None,
    ) -> MarketInsightReport:
        """Synthesize chunk notes into the final report schema."""

        notes_json = json.dumps(
            [note.model_dump(mode="json", exclude_none=True) for note in notes],
            indent=2,
        )
        prompt = (
            "Synthesize these chunk-level notes into one final market insight report.\n"
            "Preserve uncertainty, avoid unsupported claims, and deduplicate repeated items.\n\n"
            f"Source file: {source_file or 'unknown'}\n\n"
            f"Chunk notes JSON:\n{notes_json}"
        )
        return self._request_json_model(
            MarketInsightReport,
            [
                {"role": "system", "content": _FINAL_REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    def _request_json_model(
        self,
        response_model: type[TModel],
        input_messages: list[dict[str, str]],
    ) -> TModel:
        """Request JSON from the model and retry if parsing or validation fails."""

        messages = list(input_messages)
        last_error: Exception | None = None
        last_text = ""

        for attempt in range(self.max_retries + 1):
            response = self._client.responses.create(
                model=self.model,
                input=messages,
                text={"format": {"type": "json_object"}},
            )
            last_text = _response_output_text(response)
            try:
                payload = _load_json_object(last_text)
                return response_model.model_validate(payload)
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = [
                    *input_messages,
                    {
                        "role": "user",
                        "content": (
                            "The previous response was invalid JSON or failed schema "
                            f"validation: {_truncate(str(exc), 700)}\n\n"
                            "Return only one corrected JSON object for the requested schema. "
                            "Do not include markdown fences or commentary."
                        ),
                    },
                ]

        raise LLMResponseValidationError(
            "OpenAI response could not be parsed into "
            f"{response_model.__name__} after {self.max_retries + 1} attempt(s). "
            f"Last error: {last_error}. Last response: {_truncate(last_text, 700)}"
        )


class MockLLMClient:
    """Small mock summary client for tests and local integration wiring."""

    def __init__(self, report: MarketInsightReport | None = None) -> None:
        self.report = report or MarketInsightReport.example()
        self.calls: list[list[str]] = []

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        source_file: str | None = None,
    ) -> MarketInsightReport:
        """Return a predefined report and record the provided chunks."""

        self.calls.append(list(chunks))
        metadata = {
            **self.report.metadata,
            "chunk_count": len(chunks),
            "model": "mock",
        }
        return self.report.model_copy(
            update={
                "source_file": self.report.source_file or source_file,
                "metadata": metadata,
            }
        )


class PlaceholderLLMClient:
    """Deterministic summarizer used until a hosted LLM implementation exists."""

    model_name = "placeholder"

    def summarize_chunks(
        self,
        chunks: Sequence[str],
        *,
        source_file: str | None = None,
    ) -> MarketInsightReport:
        """Build a structured summary from chunks using simple text heuristics."""

        combined_text = _remove_page_markers(" ".join(chunks))
        sentences = _split_sentences(combined_text)
        executive_summary = " ".join(_first_sentences(sentences, limit=3))
        supporting_evidence = _first_sentences(sentences, limit=5)
        risk_sentences = _sentences_matching(sentences, _RISK_TERMS, limit=5)
        macro_sentences = _sentences_matching(sentences, _MACRO_TERMS, limit=5)
        key_claims = _extract_key_claims(sentences)
        if not key_claims and supporting_evidence:
            key_claims = [
                KeyClaim(
                    claim=supporting_evidence[0],
                    stance=_infer_sentence_stance(supporting_evidence[0]),
                    supporting_evidence=[supporting_evidence[0]],
                    confidence_score=0.45,
                )
            ]

        return MarketInsightReport(
            source_file=source_file,
            document_title=_infer_document_title(source_file, sentences),
            executive_summary=executive_summary
            or "No summary could be generated from the extracted document text.",
            market_stance=_infer_market_stance(combined_text),
            investment_thesis=_infer_investment_thesis(key_claims, supporting_evidence),
            bullish_arguments=_extract_bullish_arguments(sentences),
            bearish_arguments=risk_sentences,
            valuation_assumptions=_extract_valuation_assumptions(sentences),
            time_horizon=_extract_time_horizon(combined_text),
            catalysts=_extract_catalysts(sentences),
            key_claims=key_claims,
            supporting_evidence=supporting_evidence,
            risks=[
                Risk(
                    description=sentence,
                    severity=_infer_risk_severity(sentence),
                    evidence=[sentence],
                    affected_assets=_extract_affected_assets(sentence),
                )
                for sentence in risk_sentences
            ],
            sectors_mentioned=_extract_sectors(combined_text),
            companies_or_tickers_mentioned=_extract_asset_mentions(combined_text),
            macro_assumptions=[
                MacroAssumption(
                    assumption=sentence,
                    indicator=_infer_macro_indicator(sentence),
                    direction=_infer_macro_direction(sentence),
                    evidence=[sentence],
                )
                for sentence in macro_sentences
            ],
            numbers_to_verify=_extract_numbers_to_verify(sentences),
            unanswered_questions=_infer_unanswered_questions(combined_text),
            confidence_score=0.35,
            metadata={
                "chunk_count": len(chunks),
                "model": self.model_name,
                "summary_warning": (
                    "Generated by a placeholder summarizer; review against the source document."
                ),
            },
        )


_FINANCE_EXTRACTION_REQUIREMENTS = """
- Extract the main investment thesis when the document states or implies one.
- Separate bullish arguments from bearish arguments.
- Capture valuation assumptions, including multiples, fair value, discount, premium, price target,
  margin of safety, or valuation sensitivity claims.
- Capture macroeconomic assumptions, including inflation, rates, yields, GDP, employment,
  commodities, currencies, and policy assumptions.
- Capture sector implications and the sectors affected.
- Capture named companies, tickers, indices, commodities, currencies, and rates.
- Capture the stated or implied time horizon.
- Capture catalysts such as earnings, guidance, policy decisions, transactions, product launches,
  commodity price moves, rate changes, or regulatory events.
- Capture risks and downside cases.
- Flag claims that need external verification, especially numbers, forecasts, valuation claims,
  dates, and market data.
""".strip()

_CHUNK_NOTES_SYSTEM_PROMPT = f"""
You extract structured finance notes from one chunk of market research text.
Return only valid JSON matching this JSON Schema:

{json.dumps(ChunkInsightNotes.model_json_schema(), indent=2)}

Finance extraction requirements:
{_FINANCE_EXTRACTION_REQUIREMENTS}

Rules:
- Base every field only on the provided chunk.
- Keep evidence snippets short and source-grounded.
- Use empty arrays when the chunk does not support a field.
- Use "unclear" for stance or direction when the chunk is ambiguous.
- Do not give financial advice, recommendations, or instructions to buy, sell, or hold.
""".strip()

_FINAL_REPORT_SYSTEM_PROMPT = f"""
You synthesize chunk-level market research notes into one final analytical report.
Return only valid JSON matching this JSON Schema:

{json.dumps(MarketInsightReport.model_json_schema(), indent=2)}

Finance synthesis requirements:
{_FINANCE_EXTRACTION_REQUIREMENTS}

Rules:
- Use only the provided notes.
- Deduplicate repeated claims, evidence, risks, assets, assumptions, and questions.
- Do not invent tickers, companies, numbers, or macro assumptions.
- Put uncertain or externally checkable numeric claims in numbers_to_verify.
- Set confidence_score lower when the notes are thin, conflicting, or ambiguous.
- Do not give financial advice, recommendations, or instructions to buy, sell, or hold.
- Summarize and analyze the document only.
""".strip()

_SECTOR_TERMS = {
    "communication services": ["telecom", "media", "advertising", "communication services"],
    "consumer discretionary": ["retail", "consumer discretionary", "auto", "travel"],
    "consumer staples": ["consumer staples", "supermarket", "food", "beverage"],
    "energy": ["energy", "oil", "gas", "lng", "coal"],
    "financials": ["bank", "banks", "insurance", "financials", "lender"],
    "health care": ["health care", "healthcare", "biotech", "pharmaceutical", "medical"],
    "industrials": ["industrial", "infrastructure", "transport", "logistics"],
    "information technology": ["software", "semiconductor", "technology", "tech", "ai"],
    "materials": ["materials", "gold", "copper", "lithium", "uranium", "mining"],
    "real estate": ["real estate", "reit", "property"],
    "utilities": ["utilities", "utility", "electricity", "grid"],
}

_MARKET_THEME_TERMS = {
    "earnings": ["earnings", "profit", "revenue", "margin", "guidance"],
    "interest rates": ["interest rate", "rates", "bond yield", "yield"],
    "inflation": ["inflation", "cpi", "prices"],
    "commodities": ["gold", "oil", "copper", "lithium", "uranium", "commodity"],
    "valuation": ["valuation", "multiple", "discount", "premium"],
    "growth": ["growth", "expansion", "market share"],
    "capital management": ["buyback", "dividend", "capital raise", "balance sheet"],
}

_VALUATION_TERMS = [
    "discount",
    "fair value",
    "margin of safety",
    "multiple",
    "premium",
    "price target",
    "valuation",
]

_CATALYST_TERMS = [
    "catalyst",
    "catalysts",
    "commodity price",
    "earnings",
    "guidance",
    "launch",
    "merger",
    "policy",
    "rate cut",
    "rate hike",
    "regulatory",
    "takeover",
    "transaction",
]

_NAMED_ASSET_TERMS: dict[str, AssetType] = {
    "ASX 200": "index",
    "S&P 500": "index",
    "NASDAQ": "index",
    "gold": "commodity",
    "oil": "commodity",
    "copper": "commodity",
    "lithium": "commodity",
    "uranium": "commodity",
    "USD": "currency",
    "AUD": "currency",
    "EUR": "currency",
    "JPY": "currency",
    "interest rates": "other",
    "bond yields": "other",
}

_BULLISH_TERMS = [
    "attractive",
    "benefit",
    "growth",
    "improvement",
    "opportunity",
    "outperform",
    "recovery",
    "resilient",
    "tailwind",
    "upgrade",
    "upside",
]

_BEARISH_TERMS = [
    "decline",
    "downgrade",
    "downside",
    "headwind",
    "pressure",
    "restrictive",
    "risk",
    "risks",
    "uncertain",
    "volatility",
    "weakness",
]

_RISK_TERMS = [
    "risk",
    "risks",
    "headwind",
    "pressure",
    "decline",
    "downgrade",
    "uncertain",
    "volatility",
]

_MACRO_TERMS = [
    "bond yield",
    "cpi",
    "employment",
    "gdp",
    "inflation",
    "interest rate",
    "oil",
    "rates",
    "unemployment",
    "wage",
    "yield",
]

_RISING_TERMS = ["higher", "increase", "increasing", "rising", "rose", "up"]
_FALLING_TERMS = ["cut", "decline", "decrease", "fall", "falling", "lower", "reduced"]
_STABLE_TERMS = ["flat", "steady", "stable", "unchanged"]
_VOLATILE_TERMS = ["uncertain", "volatile", "volatility", "swing"]

_TICKER_PATTERN = re.compile(r"\b[A-Z]{2,5}\b")
_NUMBER_PATTERN = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s?(?:%|bps|bp|million|billion|bn|m|x))",
    re.IGNORECASE,
)
_PAGE_MARKER_PATTERN = re.compile(r"---\s*Page\s+\d+\s*---", re.IGNORECASE)
_TIME_HORIZON_PATTERN = re.compile(
    r"\b(?:(?:next|over|within|during|by)\s+(?:the\s+)?(?:\d+\s+)?"
    r"(?:days?|weeks?|months?|quarters?|years?|financial year|fiscal year)|"
    r"(?:near|medium|long)[-\s]term|FY\d{2,4}|CY\d{2,4})\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Split text into readable sentence-like fragments."""

    fragments = re.split(r"(?<=[.!?])\s+", text.strip())
    return [fragment.strip() for fragment in fragments if fragment.strip()]


def _response_output_text(response: Any) -> str:
    """Extract text from an OpenAI Responses API response object."""

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        output_text = response.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = response.get("output", [])
    else:
        output = getattr(response, "output", [])

    text_parts: list[str] = []
    for item in output or []:
        content = (
            item.get("content", []) if isinstance(item, dict) else getattr(item, "content", [])
        )
        for part in content or []:
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if isinstance(text, str):
                text_parts.append(text)
    return "".join(text_parts)


def _load_json_object(text: str) -> dict[str, Any]:
    """Load one JSON object from model text, tolerating code fences around it."""

    cleaned = _strip_markdown_json_fence(text.strip())
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        object_start = cleaned.find("{")
        object_end = cleaned.rfind("}")
        if object_start == -1 or object_end == -1 or object_end <= object_start:
            raise
        payload = json.loads(cleaned[object_start : object_end + 1])

    if not isinstance(payload, dict):
        raise TypeError("Expected a JSON object.")
    return payload


def _strip_markdown_json_fence(text: str) -> str:
    """Remove a single markdown JSON fence if the model included one."""

    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _truncate(text: str, max_chars: int) -> str:
    """Truncate long model text for errors and retry prompts."""

    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def _remove_page_markers(text: str) -> str:
    """Remove extraction page markers before summarization heuristics run."""

    return _PAGE_MARKER_PATTERN.sub(" ", text)


def _first_sentences(sentences: Sequence[str], *, limit: int) -> list[str]:
    """Return the first sentence fragments up to a given limit."""

    return list(sentences[:limit])


def _infer_document_title(source_file: str | None, sentences: Sequence[str]) -> str:
    """Infer a readable document title from the first heading or file name."""

    for sentence in sentences[:3]:
        title = sentence.strip("- \n\t")
        if 4 <= len(title) <= 120 and len(title.split()) <= 14:
            return title
    if source_file:
        return Path(source_file).stem.replace("-", " ").replace("_", " ").title()
    return "Untitled Market Research"


def _extract_sectors(text: str) -> list[str]:
    """Find known market sectors present in the source text."""

    lowered = text.lower()
    sectors = [
        sector
        for sector, terms in _SECTOR_TERMS.items()
        if any(term in lowered for term in terms)
    ]
    return sectors[:8]


def _extract_asset_mentions(text: str) -> list[MentionedAsset]:
    """Extract likely tickers and commonly named market assets from the source text."""

    ignored = {
        "ASX",
        "AUD",
        "CEO",
        "CFO",
        "ETF",
        "EUR",
        "GDP",
        "JPY",
        "LLM",
        "NASDAQ",
        "PDF",
        "USD",
    }
    counts = Counter(
        match.group(0)
        for match in _TICKER_PATTERN.finditer(text)
        if match.group(0) not in ignored
    )
    mentions = [
        MentionedAsset(name=ticker, ticker=ticker, asset_type="company", sentiment="unclear")
        for ticker, _count in counts.most_common(10)
    ]
    existing_names = {
        (mention.name or mention.ticker or "").casefold()
        for mention in mentions
    }
    lowered = text.lower()
    for asset_name, asset_type in _NAMED_ASSET_TERMS.items():
        if asset_name.lower() not in lowered or asset_name.casefold() in existing_names:
            continue
        mentions.append(
            MentionedAsset(
                name=asset_name,
                asset_type=asset_type,
                sentiment="unclear",
            )
        )
        existing_names.add(asset_name.casefold())
    return mentions


def _extract_key_claims(sentences: Sequence[str]) -> list[KeyClaim]:
    """Convert the most informative early sentences into key claims."""

    claims: list[KeyClaim] = []
    candidate_terms = _BULLISH_TERMS + _BEARISH_TERMS + list(_flatten_terms(_MARKET_THEME_TERMS))
    for sentence in sentences:
        if not _contains_any(sentence, candidate_terms):
            continue
        stance = _infer_sentence_stance(sentence)
        claims.append(
            KeyClaim(
                claim=sentence,
                stance=stance,
                supporting_evidence=[sentence],
                confidence_score=0.5 if stance == "unclear" else 0.55,
            )
        )
        if len(claims) >= 5:
            break
    return claims


def _infer_investment_thesis(
    key_claims: Sequence[KeyClaim],
    supporting_evidence: Sequence[str],
) -> str | None:
    """Infer a short investment thesis from the strongest available claim."""

    for claim in key_claims:
        if claim.stance in {"bullish", "mixed"}:
            return claim.claim
    if key_claims:
        return key_claims[0].claim
    if supporting_evidence:
        return supporting_evidence[0]
    return None


def _extract_bullish_arguments(sentences: Sequence[str]) -> list[str]:
    """Extract sentences containing upside-oriented language."""

    return _sentences_matching(sentences, _BULLISH_TERMS, limit=5)


def _extract_valuation_assumptions(sentences: Sequence[str]) -> list[str]:
    """Extract sentences containing valuation-related assumptions."""

    return _sentences_matching(sentences, _VALUATION_TERMS, limit=5)


def _extract_time_horizon(text: str) -> str | None:
    """Extract a stated or implied time horizon from the text."""

    match = _TIME_HORIZON_PATTERN.search(text)
    return match.group(0) if match else None


def _extract_catalysts(sentences: Sequence[str]) -> list[str]:
    """Extract sentences naming possible catalysts."""

    return _sentences_matching(sentences, _CATALYST_TERMS, limit=5)


def _infer_market_stance(text: str) -> str:
    """Infer a coarse market stance from bullish and bearish language."""

    lowered = text.lower()
    bullish_count = sum(lowered.count(term) for term in _BULLISH_TERMS)
    bearish_count = sum(lowered.count(term) for term in _BEARISH_TERMS)
    if bullish_count and bearish_count:
        return "mixed"
    if bullish_count:
        return "bullish"
    if bearish_count:
        return "bearish"
    return "neutral" if lowered.strip() else "unclear"


def _infer_sentence_stance(sentence: str) -> str:
    """Infer a coarse stance for one sentence."""

    has_bullish = _contains_any(sentence, _BULLISH_TERMS)
    has_bearish = _contains_any(sentence, _BEARISH_TERMS)
    if has_bullish and has_bearish:
        return "mixed"
    if has_bullish:
        return "bullish"
    if has_bearish:
        return "bearish"
    return "unclear"


def _infer_risk_severity(sentence: str) -> str:
    """Infer risk severity from wording."""

    lowered = sentence.lower()
    if any(term in lowered for term in ["material", "significant", "severe", "major"]):
        return "high"
    if any(term in lowered for term in ["minor", "limited", "modest"]):
        return "low"
    return "medium"


def _extract_affected_assets(sentence: str) -> list[str]:
    """Extract likely affected tickers from a risk sentence."""

    return [
        match.group(0)
        for match in _TICKER_PATTERN.finditer(sentence)
        if match.group(0) not in {"ASX", "CEO", "CFO", "ETF", "GDP", "LLM", "PDF", "USD"}
    ][:5]


def _infer_macro_indicator(sentence: str) -> str | None:
    """Infer the primary macro indicator in a sentence."""

    lowered = sentence.lower()
    for theme, terms in _MARKET_THEME_TERMS.items():
        if theme in {"interest rates", "inflation", "commodities"} and any(
            term in lowered for term in terms
        ):
            return theme
    if "gdp" in lowered:
        return "GDP"
    if "employment" in lowered or "unemployment" in lowered:
        return "employment"
    return None


def _infer_macro_direction(sentence: str) -> str:
    """Infer macro direction from wording."""

    lowered = sentence.lower()
    if any(term in lowered for term in _VOLATILE_TERMS):
        return "volatile"
    if any(term in lowered for term in _RISING_TERMS):
        return "rising"
    if any(term in lowered for term in _FALLING_TERMS):
        return "falling"
    if any(term in lowered for term in _STABLE_TERMS):
        return "stable"
    return "unclear"


def _extract_numbers_to_verify(sentences: Sequence[str]) -> list[VerificationItem]:
    """Extract notable numbers that should be checked against source data."""

    items: list[VerificationItem] = []
    seen: set[tuple[str, str]] = set()
    for sentence in sentences:
        for match in _NUMBER_PATTERN.finditer(sentence):
            number = match.group(0)
            key = (number.casefold(), sentence.casefold())
            if key in seen:
                continue
            seen.add(key)
            items.append(
                VerificationItem(
                    number=number,
                    context=sentence,
                    source_excerpt=sentence,
                    priority="high" if "%" in number or "$" in number else "medium",
                )
            )
            if len(items) >= 10:
                return items
    return items


def _infer_unanswered_questions(text: str) -> list[str]:
    """Flag follow-up checks implied by the extracted content."""

    questions: list[str] = []
    if _NUMBER_PATTERN.search(text):
        questions.append("Which source tables or filings confirm the extracted numerical claims?")
    if _contains_any(text, _RISK_TERMS):
        questions.append("Which risks are most material to the report's overall stance?")
    return questions[:4]


def _sentences_matching(
    sentences: Sequence[str],
    terms: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    """Return sentences containing any of the requested lower-case terms."""

    matches: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(term in lowered for term in terms):
            matches.append(sentence)
        if len(matches) >= limit:
            break
    return matches


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    """Return whether text contains any lower-case search term."""

    lowered = text.lower()
    return any(term in lowered for term in terms)


def _flatten_terms(term_groups: dict[str, list[str]]) -> list[str]:
    """Flatten term groups into one list."""

    return [term for terms in term_groups.values() for term in terms]
