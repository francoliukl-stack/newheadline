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


def title_word_count(value: str) -> int:
    return len(clean_title(value).split())


def shorten_title(value: str, max_words: int = 20) -> str:
    title = clean_title(value)
    words = title.split()
    if len(words) <= max_words:
        return title
    return " ".join(words[:max_words]).rstrip(".,;:!?") + "..."


def title_from_html(body: str) -> Optional[str]:
    for pattern in TITLE_PATTERNS:
        match = pattern.search(body)
        if match:
            title = clean_title(match.group(1))
            if title:
                return title
    return None
