from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .base import AdapterRequest, ExtractedContent, ProviderHealth, SourceSignal
from ..publish_dates import date_from_html, parse_date


TITLE_LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")


def _feed_date(value: str) -> str:
    parsed = parse_date(value)
    if parsed:
        return parsed
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _excerpt(value: str, limit: int = 1800) -> str:
    text = unescape(TAG.sub(" ", str(value or "")))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


class OfficialSourceAdapter:
    name = "official"

    def __init__(self, timeout_seconds: int = 20, max_retries: int = 1) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _get(self, url: str) -> httpx.Response:
        last_error: Exception = RuntimeError("official source request failed")
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.get(url, timeout=self.timeout_seconds, follow_redirects=True, headers={"User-Agent": "GBSS-Event-Intelligence/3.1"})
                if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                    time.sleep(attempt + 1)
                    continue
                response.raise_for_status()
                return response
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(attempt + 1)
        raise last_error

    def collect(self, request: AdapterRequest) -> List[SourceSignal]:
        signals: List[SourceSignal] = []
        for url in request.urls:
            response = self._get(url)
            content_type = response.headers.get("content-type", "").lower()
            if "xml" in content_type or response.text.lstrip().startswith("<?xml"):
                signals.extend(self._rss(response.text, str(response.url), request))
            else:
                signals.extend(self._html(response.text, str(response.url), request))
        unique = {}
        for signal in signals:
            unique.setdefault(signal.source_url, signal)
        return list(unique.values())[: request.limit]

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(self.name, True, "configured; URL-specific health is checked during collect")

    def extract(self, url: str) -> ExtractedContent:
        response = self._get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup.select("script, style, nav, header, footer, form, noscript, svg"):
            node.decompose()
        target = soup.find("article") or soup.find("main") or soup.body or soup
        text = "\n".join(line.strip() for line in target.get_text("\n").splitlines() if line.strip())
        title_node = soup.find("meta", attrs={"property": "og:title"}) or soup.find("h1") or soup.find("title")
        if title_node and getattr(title_node, "attrs", {}).get("content"):
            title = str(title_node.attrs["content"]).strip()
        else:
            title = title_node.get_text(" ", strip=True) if title_node else ""
        return ExtractedContent(self.name, str(response.url), title=title, markdown=text[:12000], publish_date=date_from_html(response.text) or "", metadata={"source_grade": "T1"})

    def _rss(self, text: str, base_url: str, request: AdapterRequest) -> List[SourceSignal]:
        root = ElementTree.fromstring(text)
        rows = []
        for item in root.findall(".//item") + root.findall(".//{*}entry"):
            title = (item.findtext("title") or item.findtext("{*}title") or "").strip()
            link = item.findtext("link") or item.findtext("{*}link") or ""
            link_node = item.find("{*}link")
            if not link and link_node is not None:
                link = str(link_node.attrib.get("href") or "")
            date = item.findtext("pubDate") or item.findtext("{*}published") or item.findtext("{*}updated") or ""
            description = item.findtext("description") or item.findtext("{*}summary") or item.findtext("{*}content") or ""
            if title and link:
                final_url = urljoin(base_url, link.strip())
                rows.append(SourceSignal(self.name, title, final_url, urlparse(final_url).netloc.lower().removeprefix("www."), _feed_date(date.strip()), snippet=_excerpt(description), query=request.query, metadata={"entity_id": request.entity_id, "source_grade": "T1"}))
        return rows

    def _html(self, text: str, base_url: str, request: AdapterRequest) -> List[SourceSignal]:
        rows = []
        base_domain = urlparse(base_url).netloc.lower().removeprefix("www.")
        for href, raw_title in TITLE_LINK.findall(text):
            title = unescape(TAG.sub(" ", raw_title))
            title = " ".join(title.split())
            final_url = urljoin(base_url, href)
            if len(title) < 20 or urlparse(final_url).netloc.lower().removeprefix("www.") != base_domain:
                continue
            rows.append(SourceSignal(self.name, title, final_url, base_domain, query=request.query, metadata={"entity_id": request.entity_id, "source_grade": "T1"}))
        return rows
