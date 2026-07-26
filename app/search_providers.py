from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Protocol, Tuple

import httpx

from .adapters.base import AdapterRequest
from .adapters.marketaux import MarketauxAdapter
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
                results.append(
                    SearchResult(
                        title=title,
                        url=url,
                        source=source,
                        snippet=str(item.get("snippet") or ""),
                        published_at=str(item.get("published_at") or item.get("publishedAt") or item.get("releaseDate") or ""),
                    )
                )
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

    @staticmethod
    def _normalize_seendate(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return value

    def search(self, query: SearchQuery) -> List[SearchResult]:
        # GDELT DOC uses domain: where web search providers use site:.
        text = query.text.replace("site:", "domain:")
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
        for attempt in range(3):
            response = httpx.get(
                self.ENDPOINT,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            if response.status_code != 429 or attempt == 2:
                response.raise_for_status()
                break
            time.sleep(10)
        articles = response.json().get("articles") or []
        return [
            SearchResult(
                title=str(article.get("title") or ""),
                url=str(article.get("url") or ""),
                source=str(article.get("domain") or ""),
                published_at=self._normalize_seendate(str(article.get("seendate") or "")),
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
        api_key = self.settings.serpapi_api_key or self.settings.api_key
        if not api_key:
            raise ProviderNotConfigured("Missing API key for serpapi")
        response = httpx.get(
            self.ENDPOINT,
            params={
                "engine": "google",
                "tbm": "nws",
                "q": query.text,
                "api_key": api_key,
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


class BraveSearchProvider:
    """Run unattended news searches through the Brave Search API."""

    ENDPOINT = "https://api.search.brave.com/res/v1/news/search"

    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings

    def search(self, query: SearchQuery) -> List[SearchResult]:
        api_key = self.settings.brave_api_key or self.settings.api_key
        if not api_key:
            raise ProviderNotConfigured("Missing API key for brave_search")
        response = httpx.get(
            self.ENDPOINT,
            params={
                "q": query.text,
                "count": min(self.settings.max_results_per_query, 20),
                "freshness": "pw",
                "search_lang": "en",
                "country": "US",
            },
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results") or []
        return [
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                source=str(item.get("source") or item.get("meta_url", {}).get("hostname") or ""),
                snippet=str(item.get("description") or ""),
                published_at=str(item.get("age") or item.get("page_age") or ""),
            )
            for item in items
            if item.get("title") and item.get("url")
        ][: self.settings.max_results_per_query]


class MarketauxSearchProvider:
    """Run keyword news searches through the Marketaux news API.

    Wraps the event-intelligence MarketauxAdapter so the daily News fetch can use
    Marketaux as a supplemental recall provider alongside the primary web search.
    """

    def __init__(self, settings: SearchProviderSettings) -> None:
        self.settings = settings
        self._adapter = MarketauxAdapter(settings.marketaux_api_key, settings.request_timeout_seconds)

    @staticmethod
    def _to_marketaux_query(text: str) -> str:
        # Detect-source plans use Brave-style boolean `OR`, but Marketaux's `search`
        # param treats bare words as AND terms and uses `|` for OR — passing the raw
        # query makes it match the literal token "OR" and return nothing. Translate
        # ` OR ` -> ` | ` and drop any web-only `site:` operators.
        translated = text.replace(" OR ", " | ")
        return " ".join(part for part in translated.split() if not part.startswith("site:"))

    def search(self, query: SearchQuery) -> List[SearchResult]:
        if not self.settings.marketaux_api_key:
            raise ProviderNotConfigured("Missing API key for marketaux")
        text = "payments" if query.text == "provider health check" else self._to_marketaux_query(query.text)
        signals = self._adapter.collect(AdapterRequest(query=text, limit=self.settings.max_results_per_query))
        return [
            SearchResult(
                title=signal.title,
                url=signal.source_url,
                source=signal.source_domain,
                snippet=signal.snippet,
                published_at=signal.publish_date,
            )
            for signal in signals
            if signal.title and signal.source_url
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


def build_supplemental_providers(settings: SearchProviderSettings) -> List[Tuple[str, SearchProvider]]:
    """Build extra recall providers that run alongside the primary provider."""
    providers: List[Tuple[str, SearchProvider]] = []
    seen = {settings.provider, settings.fallback_provider, "none", ""}
    for name in settings.supplemental_providers:
        if name in seen:
            continue
        seen.add(name)
        providers.append((name, build_provider_for_name(settings, name)))
    return providers


def build_provider_for_name(settings: SearchProviderSettings, provider_name: str) -> SearchProvider:
    if provider_name in {"chatgpt_web", "gemini_web"}:
        return BrowserProvider(settings)
    if provider_name == "serpapi":
        return SerpApiProvider(settings)
    if provider_name == "brave_search":
        return BraveSearchProvider(settings)
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
    if provider_name == "marketaux":
        return MarketauxSearchProvider(settings)
    raise ProviderNotConfigured(f"Unknown provider: {provider_name}")


def select_provider_query_groups(query_groups: List[Any], limit: int, fetch_index: int) -> List[Any]:
    """Pick a rotating window of query groups for a rate-limited supplemental provider.

    ``limit`` <= 0 or >= the number of groups means run every group. Otherwise the
    window advances by ``limit`` each fetch (keyed on ``fetch_index``) so repeated
    runs cover all groups in ``ceil(total / limit)`` fetches without wasting quota.
    """
    groups = list(query_groups)
    total = len(groups)
    if limit <= 0 or limit >= total:
        return groups
    offset = (fetch_index * limit) % total
    return [groups[(offset + step) % total] for step in range(limit)]


def provider_record_path(settings: SearchProviderSettings, provider_name: str) -> Path | None:
    paths = {
        "openclaw_cache": settings.openclaw_cache_path,
        "manual_seed": settings.manual_seed_path,
        "codex_search": settings.codex_search_cache_path,
    }
    value = paths.get(provider_name)
    return Path(value).expanduser() if value else None
