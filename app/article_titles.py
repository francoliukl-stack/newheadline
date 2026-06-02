from __future__ import annotations

import html
import re
from typing import Optional


TITLE_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S),
]


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def shorten_title(value: str, max_chars: int = 20) -> str:
    title = clean_title(value)
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


def title_from_html(body: str) -> Optional[str]:
    for pattern in TITLE_PATTERNS:
        match = pattern.search(body)
        if match:
            title = clean_title(match.group(1))
            if title:
                return title
    return None
