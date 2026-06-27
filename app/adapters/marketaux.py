from __future__ import annotations

import time
from typing import List
from urllib.parse import urlparse

import httpx

from .base import AdapterRequest, ProviderHealth, SourceSignal


class MarketauxAdapter:
    name = "marketaux"
    endpoint = "https://api.marketaux.com/v1/news/all"

    def __init__(self, api_key: str, timeout_seconds: int = 30) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def collect(self, request: AdapterRequest) -> List[SourceSignal]:
        if not self.api_key:
            raise RuntimeError("Marketaux API key is not configured")
        response = httpx.get(self.endpoint, params={"api_token": self.api_key, "search": request.query or request.entity_id, "language": "en", "limit": request.limit}, timeout=self.timeout_seconds)
        response.raise_for_status()
        rows = []
        for item in response.json().get("data") or []:
            url = str(item.get("url") or "")
            title = str(item.get("title") or "")
            if title and url:
                rows.append(SourceSignal(self.name, title, url, urlparse(url).netloc.lower().removeprefix("www."), str(item.get("published_at") or ""), str(item.get("description") or ""), "en", request.query, {"entity_id": request.entity_id, "source": item.get("source")}))
        return rows

    def healthcheck(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(self.name, False, "API key missing")
        started = time.monotonic()
        try:
            self.collect(AdapterRequest(query="payments", limit=1))
            return ProviderHealth(self.name, True, "Marketaux responded", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return ProviderHealth(self.name, False, str(exc), int((time.monotonic() - started) * 1000))
