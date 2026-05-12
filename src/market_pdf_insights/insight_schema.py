"""Pydantic models for structured market research insights."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MarketStance = Literal["bullish", "bearish", "neutral", "mixed", "unclear"]
RiskSeverity = Literal["low", "medium", "high", "unknown"]
AssetType = Literal[
    "company",
    "ticker",
    "index",
    "fund",
    "commodity",
    "currency",
    "crypto",
    "sector",
    "other",
]
MacroDirection = Literal["rising", "falling", "stable", "volatile", "unclear"]
VerificationPriority = Literal["low", "medium", "high"]


class StrictInsightModel(BaseModel):
    """Base model with strict output keys and assignment validation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class KeyClaim(StrictInsightModel):
    """A material claim made by the source document."""

    claim: NonEmptyStr = Field(description="Plain-English statement of the claim.")
    stance: MarketStance = Field(
        default="unclear",
        description="Directional market stance implied by this claim.",
    )
    supporting_evidence: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Short evidence snippets or observations supporting the claim.",
    )
    confidence_score: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Confidence that the claim is faithfully represented, from 0 to 1.",
    )

    @field_validator("supporting_evidence")
    @classmethod
    def _dedupe_supporting_evidence(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class Risk(StrictInsightModel):
    """A risk, uncertainty, or downside case raised by the document."""

    description: NonEmptyStr = Field(description="The risk in concise terms.")
    severity: RiskSeverity = Field(
        default="unknown",
        description="Estimated risk severity based only on the document language.",
    )
    evidence: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Source snippets or observations that support the risk.",
    )
    affected_assets: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Companies, tickers, sectors, or assets affected by the risk.",
    )

    @field_validator("evidence", "affected_assets")
    @classmethod
    def _dedupe_lists(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class MentionedAsset(StrictInsightModel):
    """A company, ticker, index, fund, commodity, currency, or other market asset."""

    name: NonEmptyStr | None = Field(default=None, description="Company or asset name.")
    ticker: str | None = Field(
        default=None,
        pattern=r"^[A-Z0-9.\-]{1,12}$",
        description="Uppercase ticker or market symbol when available.",
    )
    asset_type: AssetType = Field(default="company", description="Type of referenced asset.")
    exchange: str | None = Field(
        default=None,
        pattern=r"^[A-Z0-9.\-]{2,12}$",
        description="Exchange code when available.",
    )
    sector: NonEmptyStr | None = Field(default=None, description="Related sector when known.")
    sentiment: MarketStance = Field(
        default="unclear",
        description="Directional sentiment toward this asset in the document.",
    )
    rationale: NonEmptyStr | None = Field(
        default=None,
        description="Short reason the asset was mentioned.",
    )

    @field_validator("ticker", "exchange", mode="before")
    @classmethod
    def _normalize_market_codes(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return value

    @model_validator(mode="after")
    def _require_name_or_ticker(self) -> Self:
        if self.name is None and self.ticker is None:
            raise ValueError("MentionedAsset requires at least one of name or ticker.")
        return self


class MacroAssumption(StrictInsightModel):
    """A macroeconomic assumption that influences the report's market view."""

    assumption: NonEmptyStr = Field(description="The macro assumption or condition.")
    indicator: NonEmptyStr | None = Field(
        default=None,
        description="Related macro indicator, such as inflation, rates, GDP, or oil.",
    )
    direction: MacroDirection = Field(
        default="unclear",
        description="Direction implied for the macro indicator.",
    )
    evidence: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Source snippets or observations supporting the assumption.",
    )

    @field_validator("evidence")
    @classmethod
    def _dedupe_evidence(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)


class VerificationItem(StrictInsightModel):
    """A number, statistic, date, or factual item that should be checked."""

    number: NonEmptyStr = Field(description="The number or statistic to verify.")
    context: NonEmptyStr = Field(description="Where the number appears or what it describes.")
    source_excerpt: NonEmptyStr | None = Field(
        default=None,
        description="Short excerpt containing the number.",
    )
    reason: NonEmptyStr = Field(
        default="Verify against the source document or primary market data.",
        description="Why this item needs verification.",
    )
    priority: VerificationPriority = Field(
        default="medium",
        description="Verification priority before relying on the report.",
    )


class MarketInsightReport(StrictInsightModel):
    """Final structured output for a market research summary."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "document_title": "Small-Cap Market Outlook",
                "executive_summary": (
                    "The report presents a mixed outlook, balancing earnings resilience "
                    "against valuation and inflation risks."
                ),
                "market_stance": "mixed",
                "key_claims": [
                    {
                        "claim": "Quality small-cap companies may benefit if rate pressure eases.",
                        "stance": "bullish",
                        "supporting_evidence": [
                            "The report links lower bond yields with improving small-cap appetite."
                        ],
                        "confidence_score": 0.72,
                    }
                ],
                "supporting_evidence": [
                    "Lower yields and improving earnings breadth are cited as market supports."
                ],
                "risks": [
                    {
                        "description": "Inflation could keep policy restrictive.",
                        "severity": "medium",
                        "evidence": ["The report notes sticky inflation as a valuation headwind."],
                        "affected_assets": ["small-cap equities"],
                    }
                ],
                "sectors_mentioned": ["materials", "technology"],
                "companies_or_tickers_mentioned": [
                    {
                        "name": "Example Resources",
                        "ticker": "EXR",
                        "asset_type": "company",
                        "exchange": "ASX",
                        "sector": "materials",
                        "sentiment": "bullish",
                        "rationale": "Mentioned as a beneficiary of lithium demand.",
                    }
                ],
                "macro_assumptions": [
                    {
                        "assumption": "Interest rates are near a peak.",
                        "indicator": "interest rates",
                        "direction": "falling",
                        "evidence": ["The report discusses lower bond yields."],
                    }
                ],
                "numbers_to_verify": [
                    {
                        "number": "12%",
                        "context": "Projected revenue growth for the next financial year.",
                        "source_excerpt": "Management targets 12% revenue growth.",
                        "reason": "Forecast numbers should be checked against company guidance.",
                        "priority": "high",
                    }
                ],
                "unanswered_questions": [
                    "Which holdings have the strongest evidence behind the stated upside?"
                ],
                "confidence_score": 0.68,
            }
        },
    )

    source_file: NonEmptyStr | None = Field(
        default=None,
        description="Source PDF path when the report was generated from a local file.",
    )
    document_title: NonEmptyStr = Field(description="Title inferred from the source document.")
    executive_summary: NonEmptyStr = Field(
        description="Concise overview of the report's core market message."
    )
    market_stance: MarketStance = Field(description="Overall stance of the source document.")
    key_claims: list[KeyClaim] = Field(
        default_factory=list,
        description="Material claims made by the source document.",
    )
    supporting_evidence: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Cross-report evidence snippets supporting the summary.",
    )
    risks: list[Risk] = Field(default_factory=list, description="Downside risks and caveats.")
    sectors_mentioned: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Market sectors referenced in the document.",
    )
    companies_or_tickers_mentioned: list[MentionedAsset] = Field(
        default_factory=list,
        description="Companies, tickers, and assets referenced in the document.",
    )
    macro_assumptions: list[MacroAssumption] = Field(
        default_factory=list,
        description="Macro assumptions that shape the document's market view.",
    )
    numbers_to_verify: list[VerificationItem] = Field(
        default_factory=list,
        description="Numerical or factual claims requiring verification.",
    )
    unanswered_questions: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Important questions not resolved by the source document.",
    )
    confidence_score: float = Field(
        ge=0,
        le=1,
        description="Overall confidence in the structured summary, from 0 to 1.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Operational metadata, such as chunk count or model name.",
    )

    @field_validator("supporting_evidence", "sectors_mentioned", "unanswered_questions")
    @classmethod
    def _dedupe_text_lists(cls, values: list[str]) -> list[str]:
        return _dedupe_preserving_order(values)

    @model_validator(mode="after")
    def _require_claim_or_evidence(self) -> Self:
        if not self.key_claims and not self.supporting_evidence:
            raise ValueError(
                "MarketInsightReport requires at least one key claim or evidence item."
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""

        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the report to JSON."""

        separators = (",", ":") if indent is None else None
        return json.dumps(self.to_dict(), indent=indent, separators=separators, sort_keys=True)

    @classmethod
    def example(cls) -> MarketInsightReport:
        """Return a validated example report."""

        return cls.model_validate(cls.model_config["json_schema_extra"]["example"])

    @classmethod
    def example_json(cls, *, indent: int | None = 2) -> str:
        """Return the validated example report as JSON."""

        return cls.example().to_json(indent=indent)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    """Remove duplicate strings while preserving first-seen order."""

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


# Backwards-compatible names from the initial scaffold.
MarketInsightSummary = MarketInsightReport
CompanyMention = MentionedAsset
