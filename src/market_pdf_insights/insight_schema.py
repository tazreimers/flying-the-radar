"""Dataclasses representing structured market PDF insights."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Literal


Sentiment = Literal["positive", "negative", "mixed", "neutral", "unknown"]


@dataclass(frozen=True)
class CompanyMention:
    """A company or ticker mentioned in the source document."""

    name: str
    ticker: str | None = None
    sentiment: Sentiment = "unknown"
    rationale: str | None = None


@dataclass(frozen=True)
class SummarySection:
    """A titled group of summary bullets."""

    title: str
    bullets: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketInsightSummary:
    """Structured summary for a stock market commentary or research PDF."""

    source_file: str
    executive_summary: str
    key_themes: list[str] = field(default_factory=list)
    company_mentions: list[CompanyMention] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=list)
    sections: list[SummarySection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""

        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the summary to JSON."""

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

