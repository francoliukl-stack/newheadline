from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_article_url(value: Any, *, strip_www: bool = True) -> str:
    if isinstance(value, dict):
        value = value.get("link") or value.get("text") or ""
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    hostname = parsed.hostname.lower()
    if strip_www:
        hostname = hostname.removeprefix("www.")
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    query = urlencode([
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ])
    clean = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=parsed.path.rstrip("/") or "/",
        query=query,
        fragment="",
    )
    return urlunparse(clean).rstrip("/")


def article_url_identity(value: Any) -> str:
    return canonical_article_url(value, strip_www=True)
