from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol

from .models import SearchProviderSettings


@dataclass
class SearchQuery:
    text: str
    section: str
    domains: List[str]


@dataclass
class SearchResult:
    title: str
    url: str
    source: str
    snippet: str = ""
    published_at: str = ""


class SearchProvider(Protocol):
    def search(self, query: SearchQuery) -> List[SearchResult]:
        ...


class ProviderNotConfigured(RuntimeError):
    pass


class OpenClawCacheProvider:
    def __init__(self, cache_path: str, max_results: int) -> None:
        self.cache_path = Path(cache_path).expanduser()
        self.max_results = max_results

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.cache_path.exists():
            raise ProviderNotConfigured(f"OpenClaw cache not found: {self.cache_path}")
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else payload.get("records", payload.get("items", []))
        results = []
        for item in records:
            title = str(item.get("title") or item.get("Subject") or item.get("subject") or "")
            url = str(item.get("url") or item.get("Link") or item.get("link") or "")
            source = str(item.get("source") or item.get("Source") or item.get("domain") or "")
            if title or url:
                results.append(SearchResult(title=title, url=url, source=source))
        return results[: self.max_results]


class ManualSeedProvider(OpenClawCacheProvider):
    pass


class ExternalApiProvider:
    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.settings.api_key:
            raise ProviderNotConfigured(f"Missing API key for {self.settings.provider}")
        raise NotImplementedError(f"{self.settings.provider} adapter is configured but not implemented yet")


class BrowserProvider:
    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        profile = self.settings.browser_profile_path
        if not profile or not Path(profile).expanduser().exists():
            raise ProviderNotConfigured(f"Missing browser profile for {self.settings.provider}")
        raise NotImplementedError(f"{self.settings.provider} browser automation adapter is not implemented yet")


def build_provider(settings: SearchProviderSettings) -> SearchProvider:
    return build_provider_for_name(settings, settings.provider)


def build_fallback_provider(settings: SearchProviderSettings) -> SearchProvider:
    if settings.fallback_provider == "none":
        raise ProviderNotConfigured("No fallback provider configured")
    return build_provider_for_name(settings, settings.fallback_provider)


def build_provider_for_name(settings: SearchProviderSettings, provider_name: str) -> SearchProvider:
    if settings.use_codex_search:
        raise ProviderNotConfigured("Codex search is disabled for unattended provider execution")
    if provider_name in {"chatgpt_web", "gemini_web"}:
        return BrowserProvider(settings)
    if provider_name in {"serpapi", "bing_web_search", "serpstack"}:
        return ExternalApiProvider(settings)
    if provider_name == "openclaw_cache":
        return OpenClawCacheProvider(settings.openclaw_cache_path, settings.max_results_per_query)
    if provider_name == "manual_seed":
        return ManualSeedProvider(settings.manual_seed_path, settings.max_results_per_query)
    raise ProviderNotConfigured(f"Unknown provider: {provider_name}")
