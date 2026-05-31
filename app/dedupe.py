from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


WORD_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is",
    "of", "on", "or", "the", "to", "with",
}


@dataclass
class DuplicateCluster:
    primary: Dict[str, Any]
    duplicates: List[Dict[str, Any]]


def normalize_title(value: str) -> str:
    words = [word for word in WORD_PATTERN.findall(value.lower()) if word not in STOP_WORDS]
    return " ".join(words)


def title_similarity(left: str, right: str) -> float:
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    left_words = set(normalized_left.split())
    right_words = set(normalized_right.split())
    overlap = len(left_words & right_words) / max(1, len(left_words | right_words))
    sequence = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return max(overlap, sequence)


def record_title(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    return str(fields.get("Title & URL") or fields.get("Headline") or "")


def record_url(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    source_url = fields.get("Source URL") or {}
    return str(source_url.get("link") or "") if isinstance(source_url, dict) else str(source_url)


def is_article_url(url: str) -> bool:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return False
    final = parts[-1].lower()
    return len(parts) >= 2 and (len(final) >= 20 or "-" in final or "." in final)


def record_dates(record: Dict[str, Any]) -> tuple[int, int]:
    fields = record.get("fields") or {}
    first_seen = fields.get("First Seen At") or 0
    publish_date = fields.get("Publish Date") or 0
    return (
        int(first_seen) if isinstance(first_seen, (int, float)) else 0,
        int(publish_date) if isinstance(publish_date, (int, float)) else 0,
    )


def find_duplicate_clusters(records: Iterable[Dict[str, Any]], threshold: float = 0.86) -> List[DuplicateCluster]:
    groups: List[List[Dict[str, Any]]] = []
    for record in records:
        url = record_url(record)
        title = record_title(record)
        target = None
        for group in groups:
            primary = group[0]
            if url and is_article_url(url) and url == record_url(primary):
                target = group
                break
            if title_similarity(title, record_title(primary)) >= threshold:
                target = group
                break
        if target is None:
            groups.append([record])
        else:
            target.append(record)

    clusters = []
    for group in groups:
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda record: (*record_dates(record), str(record.get("id") or "")))
        clusters.append(DuplicateCluster(primary=ordered[0], duplicates=ordered[1:]))
    return clusters
