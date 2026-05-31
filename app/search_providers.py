from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol

import httpx

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


class CodexSearchProvider(OpenClawCacheProvider):
    """Read search results prepared interactively by a Codex session."""

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.cache_path.exists():
            raise ProviderNotConfigured(
                f"Codex search bridge not found: {self.cache_path}. Run an interactive Codex search first."
            )
        return super().search(query)


class GdeltDocProvider:
    """Search the public GDELT DOC API without a browser session or API key."""

    ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        text = query.text
        if text == "provider health check":
            text = "(fintech OR payments OR banking) sourcelang:english"
        elif "sourcelang:" not in text:
            text = f"({text}) sourcelang:english"
        params = {
            "query": text,
            "mode": "artlist",
            "format": "json",
            "maxrecords": self.settings.max_results_per_query,
            "sort": "datedesc",
        }
        for attempt in range(2):
            response = httpx.get(
                self.ENDPOINT,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            if response.status_code != 429 or attempt == 1:
                response.raise_for_status()
                break
            time.sleep(8)
        articles = response.json().get("articles") or []
        return [
            SearchResult(
                title=str(article.get("title") or ""),
                url=str(article.get("url") or ""),
                source=str(article.get("domain") or ""),
                published_at=str(article.get("seendate") or ""),
            )
            for article in articles
            if article.get("title") and article.get("url")
        ]


class ExternalApiProvider:
    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.settings.api_key:
            raise ProviderNotConfigured(f"Missing API key for {self.settings.provider}")
        raise NotImplementedError(f"{self.settings.provider} adapter is configured but not implemented yet")


class SerpApiProvider:
    """Run unattended Google News searches through SerpApi."""

    ENDPOINT = "https://serpapi.com/search.json"

    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.settings.api_key:
            raise ProviderNotConfigured("Missing API key for serpapi")
        response = httpx.get(
            self.ENDPOINT,
            params={
                "engine": "google",
                "tbm": "nws",
                "q": query.text,
                "api_key": self.settings.api_key,
                "num": self.settings.max_results_per_query,
                "hl": "en",
                "gl": "us",
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        items = payload.get("news_results") or payload.get("organic_results") or []
        return [
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("link") or ""),
                source=str(item.get("source") or item.get("displayed_link") or ""),
                snippet=str(item.get("snippet") or ""),
                published_at=str(item.get("date") or ""),
            )
            for item in items
            if item.get("title") and item.get("link")
        ][: self.settings.max_results_per_query]


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
    if provider_name in {"chatgpt_web", "gemini_web"}:
        return BrowserProvider(settings)
    if provider_name == "serpapi":
        return SerpApiProvider(settings)
    if provider_name in {"bing_web_search", "serpstack"}:
        return ExternalApiProvider(settings)
    if provider_name == "openclaw_cache":
        return OpenClawCacheProvider(settings.openclaw_cache_path, settings.max_results_per_query)
    if provider_name == "manual_seed":
        return ManualSeedProvider(settings.manual_seed_path, settings.max_results_per_query)
    if provider_name == "codex_search":
        return CodexSearchProvider(settings.codex_search_cache_path, settings.max_results_per_query)
    if provider_name == "gdelt_doc":
        return GdeltDocProvider(settings)
    raise ProviderNotConfigured(f"Unknown provider: {provider_name}")


def provider_record_path(settings: SearchProviderSettings, provider_name: str) -> Path | None:
    paths = {
        "openclaw_cache": settings.openclaw_cache_path,
        "manual_seed": settings.manual_seed_path,
        "codex_search": settings.codex_search_cache_path,
    }
    value = paths.get(provider_name)
    return Path(value).expanduser() if value else None
