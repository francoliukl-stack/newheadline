from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .publish_format import is_accepted_record, numeric_date, section_name, selected_date_range


def publish_date(record: Dict[str, Any]) -> int:
    return numeric_date((record.get("fields") or {}).get("Publish Date"))


def period_label(start: datetime, end_exclusive: datetime) -> str:
    start_label = start.strftime("%b %d").upper()
    end_label = (end_exclusive - timedelta(days=1)).strftime("%b %d").upper()
    return start_label if start_label == end_label else f"{start_label} - {end_label}"


def weekly_window(now: datetime, days: int) -> Tuple[datetime, datetime]:
    period_start = datetime.combine(
        now.date() - timedelta(days=max(days, 1)),
        datetime.min.time(),
        tzinfo=now.tzinfo,
    )
    period_end_exclusive = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
    return period_start, period_end_exclusive


def balance_weekly_records(records: List[Dict[str, Any]], max_items: int) -> List[Dict[str, Any]]:
    ordered = sorted(records, key=lambda record: (publish_date(record), str(record.get("id") or "")), reverse=True)
    if max_items <= 0 or len(ordered) <= max_items:
        return ordered

    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    per_section_target = max_items // 2
    for section in ("Finance", "Contact Center"):
        for record in [item for item in ordered if section_name(item) == section][:per_section_target]:
            selected.append(record)
            selected_ids.add(str(record.get("id") or ""))
    for record in ordered:
        if len(selected) >= max_items:
            break
        if str(record.get("id") or "") not in selected_ids:
            selected.append(record)
            selected_ids.add(str(record.get("id") or ""))
    return sorted(selected, key=lambda record: (publish_date(record), str(record.get("id") or "")), reverse=True)


def select_weekly_records(
    records: List[Dict[str, Any]],
    field_mapping: Dict[str, str],
    now: datetime,
    days: int = 7,
    recent_count: int = 0,
    include_sent: bool = False,
    max_items: int = 0,
) -> Tuple[List[Dict[str, Any]], str]:
    if recent_count > 0:
        accepted = [
            record for record in records
            if is_accepted_record(record, field_mapping)
            and publish_date(record)
        ]
        selected = sorted(
            accepted,
            key=lambda record: (publish_date(record), str(record.get("id") or "")),
            reverse=True,
        )[:recent_count]
        return balance_weekly_records(selected, max_items), selected_date_range(selected, now)

    period_start, period_end_exclusive = weekly_window(now, days)
    start_ms = int(period_start.timestamp() * 1000)
    end_ms = int(period_end_exclusive.timestamp() * 1000)
    selected = [
        record for record in records
        if is_accepted_record(record, field_mapping)
        and (include_sent or not (record.get("fields") or {}).get("Weekly Sent At"))
        and start_ms <= publish_date(record) < end_ms
    ]
    return balance_weekly_records(selected, max_items), period_label(period_start, period_end_exclusive)
