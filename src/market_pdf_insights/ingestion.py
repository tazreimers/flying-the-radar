"""Ingestion framework for public market-intelligence source items."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator

from market_pdf_insights.source_policy import (
    AUTOMATED_ACCESS_METHODS,
    SourceAccessMethod,
    SourceAttribution,
    SourcePolicyError,
)
from market_pdf_insights.source_registry import SourceCategory, SourceDefinition, SourceTerms

HttpGet = Callable[[str], str | bytes | dict[str, Any] | list[Any]]
RetryBackoffHook = Callable[[int, Exception], None]


class RawSourceItem(BaseModel):
    """Connector-specific source item before normalization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    raw_id: str | None = None
    title: str = Field(min_length=1)
    body: str | None = None
    summary: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tickers: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return _normalize_source_id(value)


class NormalizedMarketItem(BaseModel):
    """Common item shape used by downstream brief synthesis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deduplication_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = ""
    url: str | None = None
    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: SourceCategory
    tickers: tuple[str, ...] = ()
    attribution: SourceAttribution
    terms: SourceTerms
    raw_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return _normalize_source_id(value)


class ConnectorResult(BaseModel):
    """Result returned by a source connector."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dry_run: bool = False
    raw_items: list[RawSourceItem] = Field(default_factory=list)
    normalized_items: list[NormalizedMarketItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("source_id")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        return _normalize_source_id(value)


class IngestionRun(BaseModel):
    """Summary of a complete ingestion run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    since: datetime | None = None
    dry_run: bool = False
    connector_results: list[ConnectorResult] = Field(default_factory=list)
    items: list[NormalizedMarketItem] = Field(default_factory=list)
    total_fetched: int = 0
    total_new: int = 0
    warnings: list[str] = Field(default_factory=list)


class MarketSourceConnector(ABC):
    """Base connector with dry-run, retry, normalization, and compliance checks."""

    def __init__(
        self,
        source: SourceDefinition,
        *,
        dry_run: bool = False,
        max_attempts: int = 1,
        retry_backoff: RetryBackoffHook | None = None,
        require_automated: bool = True,
    ) -> None:
        _assert_source_ready(source, require_automated=require_automated)
        self.source = source
        self.dry_run = dry_run
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff = retry_backoff

    @property
    def source_metadata(self) -> SourceDefinition:
        """Return source compliance and registry metadata."""

        return self.source

    def fetch_since(
        self,
        since: datetime | None = None,
        *,
        dry_run: bool | None = None,
    ) -> ConnectorResult:
        """Fetch and normalize items since a timestamp."""

        fetched_at = datetime.now(UTC)
        effective_dry_run = self.dry_run if dry_run is None else dry_run
        if effective_dry_run:
            return ConnectorResult(
                source_id=self.source.source_id,
                source_name=self.source.display_name,
                fetched_at=fetched_at,
                dry_run=True,
                warnings=["Dry run: no network or file fetch was performed."],
            )

        raw_items = self._fetch_with_retry(since)
        normalized_items = [
            normalize_source_item(raw_item, self.source)
            for raw_item in raw_items
            if _is_since(raw_item.published_at, since)
        ]
        return ConnectorResult(
            source_id=self.source.source_id,
            source_name=self.source.display_name,
            fetched_at=fetched_at,
            raw_items=raw_items,
            normalized_items=deduplicate_items(normalized_items),
        )

    def deduplication_key(self, item: RawSourceItem) -> str:
        """Return the normalized deduplication key for a raw item."""

        return build_deduplication_key(
            source_id=item.source_id,
            url=item.url,
            raw_id=item.raw_id,
            title=item.title,
            published_at=item.published_at,
        )

    def _fetch_with_retry(self, since: datetime | None) -> list[RawSourceItem]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.fetch_raw(since)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                if self.retry_backoff is not None:
                    self.retry_backoff(attempt, exc)
        assert last_error is not None
        raise last_error

    @abstractmethod
    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        """Fetch connector-specific raw source items."""


class RSSFeedConnector(MarketSourceConnector):
    """Fetch and parse RSS or Atom feeds."""

    def __init__(
        self,
        source: SourceDefinition,
        *,
        feed_url: str | None = None,
        http_get: HttpGet | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(source, **kwargs)
        self.feed_url = feed_url or source.metadata.get("feed_url") or source.homepage_url
        if not self.feed_url:
            raise ValueError("RSSFeedConnector requires a feed_url or source homepage_url")
        self.http_get = http_get or _default_http_get

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        payload = _coerce_text(self.http_get(self.feed_url))
        root = ElementTree.fromstring(payload)
        items = _parse_rss_items(root, self.source, since=since)
        if items:
            return items
        return _parse_atom_items(root, self.source, since=since)


class JsonAPIConnector(MarketSourceConnector):
    """Fetch and parse JSON API endpoint responses."""

    def __init__(
        self,
        source: SourceDefinition,
        *,
        endpoint_url: str | None = None,
        http_get: HttpGet | None = None,
        items_path: Sequence[str] = ("items",),
        **kwargs: Any,
    ) -> None:
        super().__init__(source, **kwargs)
        self.endpoint_url = (
            endpoint_url
            or source.metadata.get("endpoint_url")
            or source.api_docs_url
            or source.homepage_url
        )
        if not self.endpoint_url:
            raise ValueError("JsonAPIConnector requires an endpoint_url")
        self.http_get = http_get or _default_http_get
        self.items_path = tuple(items_path)

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        payload = self.http_get(self.endpoint_url)
        data = payload if isinstance(payload, dict | list) else json.loads(_coerce_text(payload))
        records = _extract_json_records(data, self.items_path)
        return [
            _raw_item_from_mapping(record, self.source)
            for record in records
            if _is_since(parse_datetime(_pick(record, "published_at", "published", "date")), since)
        ]


class LocalFixtureConnector(MarketSourceConnector):
    """Load fixture/manual source items from JSON, JSONL, or text files."""

    def __init__(
        self,
        source: SourceDefinition,
        *,
        fixture_path: str | Path,
        **kwargs: Any,
    ) -> None:
        super().__init__(source, require_automated=False, **kwargs)
        self.fixture_path = Path(fixture_path)

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        if not self.fixture_path.exists():
            raise FileNotFoundError(self.fixture_path)

        if self.fixture_path.suffix.lower() == ".jsonl":
            records = [
                json.loads(line)
                for line in self.fixture_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        elif self.fixture_path.suffix.lower() == ".json":
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            records = _extract_json_records(payload, ("items",))
        else:
            text = self.fixture_path.read_text(encoding="utf-8")
            records = [{"title": self.fixture_path.name, "body": text}]

        return [
            _raw_item_from_mapping(record, self.source)
            for record in records
            if _is_since(parse_datetime(_pick(record, "published_at", "published", "date")), since)
        ]


class MockConnector(MarketSourceConnector):
    """Offline connector for tests and local MVP wiring."""

    def __init__(
        self,
        source: SourceDefinition,
        *,
        raw_items: Sequence[RawSourceItem | dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        super().__init__(source, require_automated=False, **kwargs)
        self.raw_items = tuple(
            item if isinstance(item, RawSourceItem) else RawSourceItem.model_validate(item)
            for item in raw_items
        )
        self.fetch_count = 0

    def fetch_raw(self, since: datetime | None = None) -> list[RawSourceItem]:
        """Return configured raw items without network or filesystem access."""

        self.fetch_count += 1
        return list(self.raw_items)


class JsonlMarketItemStore:
    """Simple JSONL cache for normalized market items."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def seen_keys(self) -> set[str]:
        """Return deduplication keys already persisted."""

        if not self.path.exists():
            return set()

        keys: set[str] = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            key = data.get("deduplication_key")
            if isinstance(key, str):
                keys.add(key)
        return keys

    def save_new_items(self, items: Iterable[NormalizedMarketItem]) -> list[NormalizedMarketItem]:
        """Persist unseen items and return the newly written items."""

        seen = self.seen_keys()
        new_items: list[NormalizedMarketItem] = []
        for item in deduplicate_items(items):
            if item.deduplication_key in seen:
                continue
            seen.add(item.deduplication_key)
            new_items.append(item)

        if new_items:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for item in new_items:
                    handle.write(item.model_dump_json() + "\n")
        return new_items

    def load_items(self) -> list[NormalizedMarketItem]:
        """Load persisted normalized items."""

        if not self.path.exists():
            return []
        return [
            NormalizedMarketItem.model_validate(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class IngestionRunner:
    """Run connectors and optionally persist newly fetched items."""

    def __init__(
        self,
        connectors: Sequence[MarketSourceConnector],
        *,
        store: JsonlMarketItemStore | None = None,
    ) -> None:
        self.connectors = tuple(connectors)
        self.store = store

    def run(self, since: datetime | None = None, *, dry_run: bool = False) -> IngestionRun:
        """Run each connector and return a deduplicated ingestion summary."""

        started_at = datetime.now(UTC)
        results: list[ConnectorResult] = []
        warnings: list[str] = []
        all_items: list[NormalizedMarketItem] = []

        for connector in self.connectors:
            result = connector.fetch_since(since, dry_run=dry_run)
            results.append(result)
            warnings.extend(result.warnings)
            all_items.extend(result.normalized_items)

        unique_items = deduplicate_items(all_items)
        new_items = self.store.save_new_items(unique_items) if self.store else unique_items
        return IngestionRun(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            since=since,
            dry_run=dry_run,
            connector_results=results,
            items=new_items,
            total_fetched=sum(len(result.raw_items) for result in results),
            total_new=len(new_items),
            warnings=warnings,
        )


def normalize_source_item(
    item: RawSourceItem,
    source: SourceDefinition,
) -> NormalizedMarketItem:
    """Normalize a raw item into the common downstream item shape."""

    body = item.body or item.summary or ""
    attribution = source.attribution(
        url=item.url,
        title=item.title,
        published_at=item.published_at,
        retrieved_at=item.fetched_at,
    )
    return NormalizedMarketItem(
        deduplication_key=build_deduplication_key(
            source_id=item.source_id,
            url=item.url,
            raw_id=item.raw_id,
            title=item.title,
            published_at=item.published_at,
        ),
        title=item.title,
        body=body,
        url=item.url,
        source_id=source.source_id,
        source_name=source.display_name,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
        category=source.category,
        tickers=item.tickers,
        attribution=attribution,
        terms=source.terms,
        raw_id=item.raw_id,
        metadata={"payload": item.payload},
    )


def build_deduplication_key(
    *,
    source_id: str,
    url: str | None,
    raw_id: str | None,
    title: str,
    published_at: datetime | None,
) -> str:
    """Build a stable key from source id plus URL, id, or title/date."""

    normalized_source_id = _normalize_source_id(source_id)
    if url:
        basis = f"url:{url.strip().lower()}"
    elif raw_id:
        basis = f"id:{raw_id.strip().lower()}"
    else:
        published_key = published_at.date().isoformat() if published_at else "undated"
        basis = f"title:{_collapse_whitespace(title).lower()}:{published_key}"
    digest = hashlib.sha256(f"{normalized_source_id}|{basis}".encode("utf-8")).hexdigest()
    return f"{normalized_source_id}:{digest[:24]}"


def deduplicate_items(
    items: Iterable[NormalizedMarketItem],
) -> list[NormalizedMarketItem]:
    """Deduplicate normalized items while preserving first-seen order."""

    seen: set[str] = set()
    deduplicated: list[NormalizedMarketItem] = []
    for item in items:
        if item.deduplication_key in seen:
            continue
        seen.add(item.deduplication_key)
        deduplicated.append(item)
    return deduplicated


def parse_datetime(value: Any) -> datetime | None:
    """Parse common RSS/API timestamp values."""

    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    try:
        return _ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    try:
        return _ensure_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError):
        return None


def _assert_source_ready(source: SourceDefinition, *, require_automated: bool) -> None:
    if not source.enabled:
        raise SourcePolicyError(f"Source is disabled: {source.display_name}")
    if source.access_method == SourceAccessMethod.DISABLED:
        raise SourcePolicyError(f"Source has disabled access method: {source.display_name}")
    if require_automated and source.access_method not in AUTOMATED_ACCESS_METHODS:
        raise SourcePolicyError(f"Source is not an automated fetch source: {source.display_name}")
    if require_automated and not source.capability.automation_allowed:
        raise SourcePolicyError(
            f"Automated access is not allowed for source: {source.display_name}"
        )


def _default_http_get(url: str) -> bytes:
    with urlopen(url, timeout=20) as response:
        return response.read()


def _parse_rss_items(
    root: ElementTree.Element,
    source: SourceDefinition,
    *,
    since: datetime | None,
) -> list[RawSourceItem]:
    items: list[RawSourceItem] = []
    for element in root.findall(".//item"):
        published_at = parse_datetime(_child_text(element, "pubDate", "published", "date"))
        if not _is_since(published_at, since):
            continue
        title = _child_text(element, "title") or "Untitled RSS item"
        summary = _child_text(element, "description", "summary")
        items.append(
            RawSourceItem(
                source_id=source.source_id,
                raw_id=_child_text(element, "guid"),
                title=title,
                summary=summary,
                url=_child_text(element, "link"),
                published_at=published_at,
                tickers=_extract_tickers(" ".join([title, summary or ""])),
                payload={"format": "rss"},
            )
        )
    return items


def _parse_atom_items(
    root: ElementTree.Element,
    source: SourceDefinition,
    *,
    since: datetime | None,
) -> list[RawSourceItem]:
    items: list[RawSourceItem] = []
    for element in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        published_at = parse_datetime(
            _child_text(element, "published", "updated", namespaced=True)
        )
        if not _is_since(published_at, since):
            continue
        title = _child_text(element, "title", namespaced=True) or "Untitled Atom item"
        summary = _child_text(element, "summary", "content", namespaced=True)
        url = _atom_link(element)
        items.append(
            RawSourceItem(
                source_id=source.source_id,
                raw_id=_child_text(element, "id", namespaced=True),
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                tickers=_extract_tickers(" ".join([title, summary or ""])),
                payload={"format": "atom"},
            )
        )
    return items


def _raw_item_from_mapping(record: dict[str, Any], source: SourceDefinition) -> RawSourceItem:
    title = _pick(record, "title", "headline", "name") or "Untitled source item"
    body = _pick(record, "body", "content", "text")
    summary = _pick(record, "summary", "description", "abstract")
    published_at = parse_datetime(_pick(record, "published_at", "published", "date"))
    tickers = _coerce_string_tuple(record.get("tickers") or record.get("assets"))
    if not tickers:
        tickers = _extract_tickers(" ".join([str(title), str(body or ""), str(summary or "")]))
    return RawSourceItem(
        source_id=source.source_id,
        raw_id=_coerce_optional_str(_pick(record, "id", "guid", "slug")),
        title=str(title),
        body=_coerce_optional_str(body),
        summary=_coerce_optional_str(summary),
        url=_coerce_optional_str(_pick(record, "url", "link")),
        published_at=published_at,
        tickers=tickers,
        payload=record,
    )


def _extract_json_records(data: Any, items_path: Sequence[str]) -> list[dict[str, Any]]:
    current = data
    if isinstance(current, dict):
        for key in items_path:
            next_value = current.get(key)
            if next_value is None:
                break
            current = next_value
        else:
            return _coerce_record_list(current)
        for fallback_key in ("items", "data", "results", "articles"):
            if fallback_key in current:
                return _coerce_record_list(current[fallback_key])
        return [current]
    return _coerce_record_list(current)


def _coerce_record_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _child_text(
    element: ElementTree.Element,
    *names: str,
    namespaced: bool = False,
) -> str | None:
    for name in names:
        child = element.find(f"{{http://www.w3.org/2005/Atom}}{name}") if namespaced else None
        if child is None:
            child = element.find(name)
        if child is not None and child.text and child.text.strip():
            return child.text.strip()
    return None


def _atom_link(element: ElementTree.Element) -> str | None:
    for child in element.findall("{http://www.w3.org/2005/Atom}link"):
        href = child.attrib.get("href")
        if href:
            return href
    return None


def _is_since(published_at: datetime | None, since: datetime | None) -> bool:
    if since is None or published_at is None:
        return True
    return _ensure_utc(published_at) >= _ensure_utc(since)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_text(value: str | bytes | dict[str, Any] | list[Any]) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip().upper(),) if value.strip() else ()
    if isinstance(value, list | tuple | set):
        return tuple(str(item).strip().upper() for item in value if str(item).strip())
    return ()


def _extract_tickers(text: str) -> tuple[str, ...]:
    tickers = re.findall(r"\b[A-Z]{2,5}(?:\.[A-Z]{1,3})?\b", text)
    ignored = {"API", "RSS", "JSON", "HTTP", "ASX", "RBA", "ABS", "ASIC"}
    return tuple(dict.fromkeys(ticker for ticker in tickers if ticker not in ignored))


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_source_id(source_id: str) -> str:
    return source_id.strip().lower().replace(" ", "-")
