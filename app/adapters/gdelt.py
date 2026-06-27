from __future__ import annotations

import time
from typing import List

import httpx

from .base import AdapterRequest, ProviderHealth, SourceSignal


class GdeltAdapter:
    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, timeout_seconds: int = 45) -> None:
        self.timeout_seconds = timeout_seconds

    def collect(self, request: AdapterRequest) -> List[SourceSignal]:
        query = request.query or request.entity_id
        if "sourcelang:" not in query:
            query = f"({query}) sourcelang:english"
        response = httpx.get(self.endpoint, params={"query": query, "mode": "artlist", "format": "json", "maxrecords": request.limit, "sort": "datedesc"}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return [SourceSignal(self.name, str(item.get("title") or ""), str(item.get("url") or ""), str(item.get("domain") or ""), str(item.get("seendate") or ""), language=str(item.get("language") or ""), query=request.query, metadata={"entity_id": request.entity_id}) for item in response.json().get("articles") or [] if item.get("title") and item.get("url")]

    def healthcheck(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            self.collect(AdapterRequest(query="payments", limit=1))
            return ProviderHealth(self.name, True, "GDELT responded", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return ProviderHealth(self.name, False, str(exc), int((time.monotonic() - started) * 1000))
