from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from .dingtalk_ai_table import cell_text
from .publish_dates import date_from_url, parse_date
from .url_identity import canonical_article_url


EDITORIAL_NEWS_FIELDS = [
    {"name": "Source Lane", "type": "text"},
    {"name": "Editorial Reason", "type": "text"},
    {"name": "Editorial Approved At", "type": "text"},
]

def editorial_field_definitions(plan: Dict[str, Any]) -> List[Dict[str, str]]:
    field_names = {
        str(name)
        for fields in [
            *(plan.get("creates") or []),
            *((row.get("fields") or {}) for row in (plan.get("updates") or [])),
        ]
        for name in fields
        if name
    }
    field_names.update(field["name"] for field in EDITORIAL_NEWS_FIELDS)
    return [
        {"name": name, "type": "url" if name == "Source URL" else "text"}
        for name in sorted(field_names)
    ]


def normalize_editorial_url(value: Any) -> str:
    return canonical_article_url(value)


def _record_url(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    value = fields.get("Source URL") or fields.get("Link") or ""
    if isinstance(value, dict):
        value = value.get("link") or value.get("text") or ""
    return normalize_editorial_url(value)


def _item_value(item: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = cell_text(item.get(name)).strip()
        if value:
            return value
    return ""


def _existing_value(fields: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = cell_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def plan_editorial_intake(
    items: Iterable[Dict[str, Any]],
    existing_records: Iterable[Dict[str, Any]],
    *,
    approve: bool,
    reason: str,
    now: str,
    status_field: str = "Review Status",
) -> Dict[str, Any]:
    existing_by_url = {
        normalized: record
        for record in existing_records
        for normalized in [_record_url(record)]
        if normalized
    }
    creates: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    seen_input_urls = set()
    counts = {"created": 0, "updated": 0, "duplicate": 0, "blocked": 0}
    first_seen = now[:10] if now else datetime.now().date().isoformat()

    for item in items:
        url = normalize_editorial_url(_item_value(item, "url", "URL", "Source URL", "Link"))
        if not url:
            counts["blocked"] += 1
            results.append({"url": _item_value(item, "url", "URL", "Source URL", "Link"), "action": "blocked", "reason": "invalid_url"})
            continue
        if url in seen_input_urls:
            counts["duplicate"] += 1
            results.append({"url": url, "action": "duplicate", "reason": "duplicate_input"})
            continue
        seen_input_urls.add(url)

        existing = existing_by_url.get(url)
        existing_fields = (existing or {}).get("fields") or {}
        title = _item_value(item, "title", "Title", "Subject") or _existing_value(existing_fields, "Title", "Subject")
        publish_date = (
            parse_date(_item_value(item, "publish_date", "Publish Date", "published_at"))
            or parse_date(_existing_value(existing_fields, "Publish Date", "Published At"))
            or date_from_url(url)
            or ""
        )
        if not publish_date:
            counts["blocked"] += 1
            results.append({"url": url, "action": "blocked", "reason": "missing_publish_date"})
            continue
        if not title:
            counts["blocked"] += 1
            results.append({"url": url, "action": "blocked", "reason": "missing_title"})
            continue

        section = _item_value(item, "section", "Section", "Category")
        excerpt = _item_value(item, "source_excerpt", "Source Excerpt", "snippet")
        domain = urlparse(url).netloc.removeprefix("www.")
        editorial_fields: Dict[str, Any] = {
            "Search Provider": "editorial_input",
            "Discovery Type": "editorial_must_include",
            "Source Lane": "editorial",
            "Search Query": reason,
            "Editorial Reason": reason,
        }
        if approve:
            editorial_fields.update({
                status_field: "已采纳",
                "Review Decision Source": "Human",
                "Editorial Approved At": now,
            })

        if existing:
            patch = dict(editorial_fields)
            for field_name, value in (
                ("Title", title),
                ("Publish Date", publish_date),
                ("Section", section),
                ("Source", domain),
                ("Source Excerpt", excerpt),
                ("Date Confidence", "editorial_verified"),
            ):
                if value and not _existing_value(existing_fields, field_name):
                    patch[field_name] = value
            updates.append({"id": str(existing.get("id") or ""), "fields": patch})
            counts["updated"] += 1
            counts["duplicate"] += 1
            results.append({"url": url, "record_id": str(existing.get("id") or ""), "action": "updated", "reason": "duplicate_existing"})
            continue

        fields: Dict[str, Any] = {
            "Title": title,
            "Source URL": {"text": domain, "link": url},
            "Publish Date": publish_date,
            "Source": domain,
            "Date Confidence": "editorial_verified",
            "First Seen At": first_seen,
            status_field: "已采纳" if approve else "待处理",
            "Publish Status": "未发送",
            **editorial_fields,
        }
        if section:
            fields["Section"] = section
        if excerpt:
            fields["Source Excerpt"] = excerpt
        creates.append(fields)
        counts["created"] += 1
        results.append({"url": url, "action": "created", "reason": "editorial_approved" if approve else "editorial_pending"})

    return {"creates": creates, "updates": updates, "results": results, "counts": counts}
