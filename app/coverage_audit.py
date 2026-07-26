from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Set

from .dingtalk_ai_table import cell_text, status_name
from .editorial_intake import normalize_editorial_url
from .publish_dates import parse_date


COVERAGE_REASONS = {
    "not_discovered",
    "candidate_quota_excluded",
    "duplicate_existing",
    "missing_publish_date",
    "missing_entity",
    "general_event_type",
    "pending_human_review",
    "research_input_stale",
    "research_document_missing",
    "eligible",
}


def _source_url(fields: Dict[str, Any]) -> str:
    value = fields.get("Source URL") or fields.get("Link") or ""
    if isinstance(value, dict):
        value = value.get("link") or value.get("text") or ""
    return normalize_editorial_url(value)


def _normalized_urls(values: Iterable[str]) -> Set[str]:
    return {normalized for value in values for normalized in [normalize_editorial_url(value)] if normalized}


def build_coverage_audit(
    targets: Iterable[Dict[str, Any]],
    news_records: Iterable[Dict[str, Any]],
    event_records: Iterable[Dict[str, Any]],
    *,
    discovered_urls: Iterable[str] = (),
    selected_urls: Iterable[str] = (),
    research_event_ids: Optional[Iterable[str]] = None,
    generated_at: str = "",
) -> Dict[str, Any]:
    discovered = _normalized_urls(discovered_urls)
    selected = _normalized_urls(selected_urls)
    news_by_url = {
        url: record
        for record in news_records
        for url in [_source_url(record.get("fields") or {})]
        if url
    }
    events_by_id = {
        cell_text((record.get("fields") or {}).get("Event ID")): record
        for record in event_records
        if cell_text((record.get("fields") or {}).get("Event ID"))
    }
    research_ids = None if research_event_ids is None else {str(value) for value in research_event_ids if value}
    items = []

    for target in targets:
        url = normalize_editorial_url(target.get("url") or target.get("URL") or "")
        news = news_by_url.get(url)
        news_fields = (news or {}).get("fields") or {}
        event_id = cell_text(news_fields.get("Event Case ID") or news_fields.get("Event ID"))
        event_fields = (events_by_id.get(event_id) or {}).get("fields") or {}
        manual_status = status_name(news_fields)
        ai_status = cell_text(news_fields.get("AI Status"))
        event_type = cell_text(event_fields.get("Event Type"))
        event_status = status_name(event_fields)
        has_date = bool(parse_date(news_fields.get("Publish Date")))
        accepted = manual_status == "已采纳"
        active_event = bool(event_id and event_fields and event_status not in {"已归档", "已拒绝", "已重复"})
        typed_event = active_event and event_type not in {"", "General"}
        daily_eligible = bool(news and has_date and accepted and typed_event)
        weekly_eligible = daily_eligible
        research_input = bool(daily_eligible and (research_ids is None or event_id in research_ids))
        was_discovered = url in discovered or bool(news)
        was_selected = url in selected or bool(news)

        if not was_discovered:
            reason, blocked_stage = "not_discovered", "discovery"
        elif not was_selected and not news:
            reason, blocked_stage = "candidate_quota_excluded", "candidate_selection"
        elif news and not has_date:
            reason, blocked_stage = "missing_publish_date", "news"
        elif news and not event_id:
            reason, blocked_stage = "missing_entity", "eventization"
        elif event_type == "General":
            reason, blocked_stage = "general_event_type", "eventization"
        elif news and not accepted:
            reason, blocked_stage = "pending_human_review", "human_review"
        elif daily_eligible and research_ids is not None and event_id not in research_ids:
            reason, blocked_stage = "research_input_stale", "research_queue"
        elif daily_eligible:
            reason, blocked_stage = "eligible", ""
        else:
            reason, blocked_stage = "missing_entity", "eventization"

        items.append({
            "url": url,
            "discovered": was_discovered,
            "candidate_selected": was_selected,
            "news_record_id": str((news or {}).get("id") or ""),
            "event_id": event_id,
            "manual_status": manual_status,
            "ai_status": ai_status,
            "daily_eligible": daily_eligible,
            "weekly_eligible": weekly_eligible,
            "research_input": research_input,
            "blocked_stage": blocked_stage,
            "reason": reason,
        })

    counts: Dict[str, int] = {}
    for item in items:
        counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
        "counts": counts,
    }

