from __future__ import annotations

import time
from typing import Any, Dict

import httpx

from .base import ExtractedContent, ProviderHealth


class FirecrawlAdapter:
    name = "firecrawl"
    endpoint = "https://api.firecrawl.dev/v1/scrape"

    def __init__(self, api_key: str, timeout_seconds: int = 60) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def extract(self, url: str) -> ExtractedContent:
        if not self.api_key:
            raise RuntimeError("Firecrawl API key is not configured")
        response = httpx.post(self.endpoint, headers={"Authorization": f"Bearer {self.api_key}"}, json={"url": url, "formats": ["markdown"], "onlyMainContent": True}, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload: Dict[str, Any] = response.json()
        data = payload.get("data") or {}
        metadata = data.get("metadata") or {}
        return ExtractedContent(self.name, url, str(metadata.get("title") or ""), str(data.get("markdown") or ""), str(metadata.get("publishedTime") or metadata.get("publishedDate") or ""), metadata)

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(self.name, bool(self.api_key), "configured" if self.api_key else "API key missing")
