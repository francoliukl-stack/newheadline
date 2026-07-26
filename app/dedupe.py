from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from .url_identity import article_url_identity

WORD_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is",
    "of", "on", "or", "the", "to", "with",
}
EVENT_STOP_WORDS = STOP_WORDS | {
    "ai", "news", "new", "company", "companies", "startup", "tech", "technology",
    "platform", "agent", "agents", "service", "services", "global", "business",
    "million", "billion", "fund", "funding", "invest", "investment", "stake", "acquisition",
    "shares", "share", "launches", "launch", "expands", "build", "builds",
}
EVENT_ACTIONS = {
    "funding": ("fund", "invest", "raise", "stake", "udzia", "inwest", "kupuje"),
    "acquisition": ("acquir", "buyout", "merger", "merges"),
}


@dataclass
class DuplicateCluster:
    primary: Dict[str, Any]
    duplicates: List[Dict[str, Any]]
    reasons: Dict[str, str]


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
    return str(fields.get("Title") or fields.get("Title & URL") or fields.get("Headline") or "")


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


def _record_day(record: Dict[str, Any]) -> int:
    fields = record.get("fields") or {}
    value = fields.get("Publish Date") or fields.get("First Seen At") or ""
    if isinstance(value, (int, float)):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return timestamp // 86_400
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except ValueError:
        return 0


def _event_action(title: str) -> str:
    normalized = normalize_title(title)
    for action, stems in EVENT_ACTIONS.items():
        if any(stem in normalized for stem in stems):
            return action
    return ""


def _event_tokens(title: str) -> set[str]:
    return {
        word for word in WORD_PATTERN.findall(title.lower())
        if len(word) >= 6 and word not in EVENT_STOP_WORDS
    }


def duplicate_reason(left: Dict[str, Any], right: Dict[str, Any], threshold: float) -> str:
    left_url = record_url(left)
    right_url = record_url(right)
    left_identity = article_url_identity(left_url)
    right_identity = article_url_identity(right_url)
    if left_identity and is_article_url(left_identity) and left_identity == right_identity:
        return "Same canonical article URL"
    score = title_similarity(record_title(left), record_title(right))
    if score >= threshold:
        return f"Near-identical title (similarity {score:.2f})"
    left_action = _event_action(record_title(left))
    right_action = _event_action(record_title(right))
    day_gap = abs(_record_day(left) - _record_day(right))
    shared_entities = _event_tokens(record_title(left)) & _event_tokens(record_title(right))
    if left_action and left_action == right_action and day_gap <= 2 and shared_entities:
        entity = sorted(shared_entities, key=lambda item: (-len(item), item))[0]
        return f"Same {left_action} event for {entity} within {day_gap} day(s)"
    return ""


def find_duplicate_clusters(records: Iterable[Dict[str, Any]], threshold: float = 0.55) -> List[DuplicateCluster]:
    groups: List[List[Dict[str, Any]]] = []
    for record in records:
        target = None
        for group in groups:
            primary = group[0]
            if duplicate_reason(record, primary, threshold):
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
        primary = ordered[0]
        clusters.append(DuplicateCluster(
            primary=primary,
            duplicates=ordered[1:],
            reasons={
                str(record.get("id") or ""): duplicate_reason(record, primary, threshold)
                for record in ordered[1:]
            },
        ))
    return clusters
