from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx


DATE_PATTERNS = [
    re.compile(r"(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"),
    re.compile(r"/(?P<year>20\d{2})/(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/|$)"),
    re.compile(r"/(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?:/|[-_])"),
    re.compile(r"/(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})\d+"),
]
META_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+name=["\']article:published_time["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
]


@dataclass
class PublishedDateResult:
    value: str
    method: str


def parse_date(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
    if not isinstance(value, str):
        return None
    candidate = html.unescape(value).strip()
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    match = re.search(r"(?P<year>20\d{2})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})", candidate)
    if not match:
        return None
    try:
        return datetime(int(match["year"]), int(match["month"]), int(match["day"])).date().isoformat()
    except ValueError:
        return None


def resolve_provider_publish_date(value: Any, observed_at: datetime, timezone_name: str = "Asia/Kuala_Lumpur") -> PublishedDateResult:
    exact = parse_date(value)
    if exact:
        return PublishedDateResult(exact, "provider_exact")
    text = str(value or "").strip().lower()
    timezone = ZoneInfo(timezone_name)
    observed = observed_at.astimezone(timezone) if observed_at.tzinfo else observed_at.replace(tzinfo=timezone)
    if text == "yesterday":
        return PublishedDateResult((observed - timedelta(days=1)).date().isoformat(), "provider_relative")
    match = re.fullmatch(r"(?P<count>\d+)\s+(?P<unit>minute|hour|day|week)s?\s+ago", text)
    if not match:
        return PublishedDateResult("", "unresolved")
    count = int(match["count"])
    unit = match["unit"]
    delta = {
        "minute": timedelta(minutes=count),
        "hour": timedelta(hours=count),
        "day": timedelta(days=count),
        "week": timedelta(weeks=count),
    }[unit]
    return PublishedDateResult((observed - delta).date().isoformat(), "provider_relative")


def needs_publish_date_resolution(fields: Dict[str, Any]) -> bool:
    return not bool(parse_date(fields.get("Publish Date"))) or str(fields.get("Date Confidence") or "").strip() == "provider_relative"


def publish_date_update(fields: Dict[str, Any], result: PublishedDateResult) -> Optional[Dict[str, str]]:
    if not result.value:
        return None
    current = parse_date(fields.get("Publish Date"))
    confidence = str(fields.get("Date Confidence") or "").strip()
    if current and confidence == "provider_relative" and result.method not in {"page_metadata", "url_path"}:
        return None
    return {"Publish Date": result.value, "Date Confidence": result.method}


def date_from_url(url: str) -> Optional[str]:
    path = urlparse(url).path
    for pattern in DATE_PATTERNS:
        match = pattern.search(path)
        if not match:
            continue
        try:
            return datetime(int(match["year"]), int(match["month"]), int(match["day"])).date().isoformat()
        except ValueError:
            continue
    return None


def date_from_html(body: str) -> Optional[str]:
    for pattern in META_PATTERNS:
        match = pattern.search(body)
        if match:
            parsed = parse_date(match.group(1))
            if parsed:
                return parsed
    return None


def discover_published_date(
    client: httpx.Client,
    url: str,
    release_date: Any = None,
) -> PublishedDateResult:
    try:
        response = client.get(url)
        if response.is_success:
            discovered = date_from_html(response.text)
            if discovered:
                return PublishedDateResult(discovered, "page_metadata")
    except httpx.HTTPError:
        pass
    discovered = date_from_url(url)
    if discovered:
        return PublishedDateResult(discovered, "url_path")
    discovered = parse_date(release_date)
    if discovered:
        return PublishedDateResult(discovered, "release_date_fallback")
    return PublishedDateResult("", "unresolved")
