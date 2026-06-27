from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AdapterRequest:
    query: str = ""
    entity_id: str = ""
    urls: List[str] = field(default_factory=list)
    ticker: str = ""
    limit: int = 20


@dataclass
class SourceSignal:
    provider: str
    title: str
    source_url: str
    source_domain: str = ""
    publish_date: str = ""
    snippet: str = ""
    language: str = ""
    query: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedContent:
    provider: str
    url: str
    title: str = ""
    markdown: str = ""
    publish_date: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSignal:
    provider: str
    ticker: str
    observed_at: str
    price: float
    previous_close: float
    change_pct: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    provider: str
    ok: bool
    message: str
    latency_ms: int = 0
