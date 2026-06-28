from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from .base import AdapterRequest, ProviderHealth, SourceSignal
from ..publish_dates import parse_date


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


class OfficialSourceAdapter:
    name = "official"

    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def collect(self, request: AdapterRequest) -> List[SourceSignal]:
        signals: List[SourceSignal] = []
        for url in request.urls:
            response = httpx.get(url, timeout=self.timeout_seconds, follow_redirects=True, headers={"User-Agent": "GBSS-Event-Intelligence/3.1"})
            response.raise_for_status()
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
            if title and link:
                final_url = urljoin(base_url, link.strip())
                rows.append(SourceSignal(self.name, title, final_url, urlparse(final_url).netloc.lower().removeprefix("www."), _feed_date(date.strip()), query=request.query, metadata={"entity_id": request.entity_id, "source_grade": "T1"}))
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
