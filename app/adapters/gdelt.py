from __future__ import annotations

import time
from typing import Callable, List

import httpx

from .base import AdapterRequest, ProviderHealth, SourceSignal


class GdeltAdapter:
    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, timeout_seconds: int = 45, max_retries: int = 2, retry_delay_seconds: float = 5.0, sleep_fn: Callable[[float], None] = time.sleep) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.sleep_fn = sleep_fn

    def collect(self, request: AdapterRequest) -> List[SourceSignal]:
        query = request.query or request.entity_id
        if "sourcelang:" not in query:
            query = f"({query}) sourcelang:english"
        params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": request.limit, "sort": "datedesc"}
        last_error: Exception = RuntimeError("GDELT request failed")
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.get(self.endpoint, params=params, timeout=self.timeout_seconds)
                if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else self.retry_delay_seconds * (attempt + 1)
                    self.sleep_fn(delay)
                    continue
                response.raise_for_status()
                payload = response.json()
                return [SourceSignal(self.name, str(item.get("title") or ""), str(item.get("url") or ""), str(item.get("domain") or ""), str(item.get("seendate") or ""), language=str(item.get("language") or ""), query=request.query, metadata={"entity_id": request.entity_id}) for item in payload.get("articles") or [] if item.get("title") and item.get("url")]
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                self.sleep_fn(self.retry_delay_seconds * (attempt + 1))
        raise last_error

    def healthcheck(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            self.collect(AdapterRequest(query="payments", limit=1))
            return ProviderHealth(self.name, True, "GDELT responded", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return ProviderHealth(self.name, False, str(exc), int((time.monotonic() - started) * 1000))
