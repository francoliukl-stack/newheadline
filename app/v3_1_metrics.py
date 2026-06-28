from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

from .dingtalk_ai_table import cell_text
from .event_intelligence import CRITICAL_EVENT_TYPES, validate_final_p0
from .publish_dates import parse_date


def _fields(record: Dict[str, Any]) -> Dict[str, Any]:
    return record.get("fields") or record


def _date(value: Any) -> Optional[date]:
    parsed = parse_date(value)
    if not parsed:
        return None
    try:
        return date.fromisoformat(parsed)
    except ValueError:
        return None


def _url(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    return str(value or "").strip()


def _latest_usage_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    without_id = []
    for record in records:
        fields = _fields(record)
        call_id = cell_text(fields.get("Call ID")).strip()
        if not call_id:
            without_id.append(fields)
            continue
        current = latest.get(call_id)
        if current is None or cell_text(fields.get("Finished At")).strip() or not cell_text(current.get("Finished At")).strip():
            latest[call_id] = fields
    return without_id + list(latest.values())


def _cost(records: Sequence[Dict[str, Any]], cutoff: date) -> float:
    total = 0.0
    for fields in _latest_usage_rows(records):
        observed = _date(fields.get("Started At"))
        if not observed or observed < cutoff:
            continue
        status = cell_text(fields.get("Status")).lower()
        value = fields.get("Estimated Cost USD") if status == "reserved" else fields.get("Actual Cost USD")
        try:
            total += float(cell_text(value) or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 8)


def build_v3_1_metrics(
    *,
    news: Sequence[Dict[str, Any]],
    events: Sequence[Dict[str, Any]],
    evidence: Sequence[Dict[str, Any]],
    claims: Sequence[Dict[str, Any]],
    usage: Sequence[Dict[str, Any]],
    now: Optional[datetime] = None,
    observation_started_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    current = now or datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))
    today = current.date()
    week_cutoff = today - timedelta(days=6)
    month_cutoff = today - timedelta(days=27)
    active_events = [record for record in events if cell_text(_fields(record).get("Status")) not in {"已归档", "已拒绝", "已重复"}]
    linked_signals = [
        record for record in news
        if (_date(_fields(record).get("First Seen At")) or date.min) >= week_cutoff
        and cell_text(_fields(record).get("Event Case ID"))
        and cell_text(_fields(record).get("Status") or _fields(record).get("Review Status")) not in {"已拒绝", "已重复"}
    ]
    recent_event_ids = {cell_text(_fields(record).get("Event Case ID")) for record in linked_signals}
    accepted_event_ids = {
        cell_text(_fields(record).get("Event Case ID"))
        for record in news
        if cell_text(_fields(record).get("Event Case ID"))
        and cell_text(_fields(record).get("Review Status") or _fields(record).get("Status")) == "已采纳"
    }
    recent_events = [record for record in active_events if cell_text(_fields(record).get("Event ID")) in recent_event_ids]
    raw_signals = [record for record in news if (_date(_fields(record).get("First Seen At")) or date.min) >= week_cutoff]
    evidence_by_event: Dict[str, List[Dict[str, Any]]] = {}
    claims_by_event: Dict[str, List[Dict[str, Any]]] = {}
    for record in evidence:
        event_id = cell_text(_fields(record).get("Event ID"))
        if event_id:
            evidence_by_event.setdefault(event_id, []).append(_fields(record))
    for record in claims:
        event_id = cell_text(_fields(record).get("Event ID"))
        if event_id:
            claims_by_event.setdefault(event_id, []).append(_fields(record))

    candidate_traceable = accepted_traceable = accepted_count = deep_research_ready_count = 0
    critical_event_ids = set()
    business_mapped = event_typed = critical_active = critical_recent = automatic_p0_violations = 0
    for record in active_events:
        fields = _fields(record)
        event_id = cell_text(fields.get("Event ID"))
        event_evidence = evidence_by_event.get(event_id, [])
        event_claims = claims_by_event.get(event_id, [])
        event_has_lineage = bool(_url(fields.get("Primary Source URL")) and _date(fields.get("Publish Date")))
        evidence_has_lineage = any(cell_text(item.get("Evidence ID")) and _url(item.get("Source URL")) and _date(item.get("Published Date")) for item in event_evidence)
        claim_has_lineage = any(cell_text(item.get("Claim ID")) and cell_text(item.get("Evidence IDs")) for item in event_claims)
        candidate_traceable += int(event_has_lineage and evidence_has_lineage and claim_has_lineage)
        if event_id in accepted_event_ids:
            accepted_count += 1
            verified = any(cell_text(item.get("Reviewer Status")).lower() == "verified" for item in event_evidence)
            approved = any(cell_text(item.get("Reviewer Status")).lower() == "approved" for item in event_claims)
            accepted_traceable += int(event_has_lineage and evidence_has_lineage and claim_has_lineage)
            deep_research_ready_count += int(verified and approved)
        business_mapped += int(bool(cell_text(fields.get("Business Lines"))))
        event_typed += int(cell_text(fields.get("Event Type")) not in {"", "General"})
        event_type = cell_text(fields.get("Event Type"))
        is_critical = event_type in CRITICAL_EVENT_TYPES or cell_text(fields.get("Strategic Candidate")).lower() == "yes"
        critical_active += int(is_critical)
        critical_recent += int(is_critical and record in recent_events)
        if is_critical:
            critical_event_ids.add(event_id)
        automatic_p0_violations += int(cell_text(fields.get("Final Priority")) == "P0" and not validate_final_p0(fields))

    lag_by_event: Dict[str, int] = {}
    publish_date_by_event: Dict[str, date] = {}
    for record in linked_signals:
        fields = _fields(record)
        event_id = cell_text(fields.get("Event Case ID"))
        published, first_seen = _date(fields.get("Publish Date")), _date(fields.get("First Seen At"))
        if not event_id or not published or not first_seen:
            continue
        lag = max(0, (first_seen - published).days)
        lag_by_event[event_id] = min(lag, lag_by_event.get(event_id, lag))
        publish_date_by_event[event_id] = min(published, publish_date_by_event.get(event_id, published))
    observation_date = observation_started_at.astimezone(current.tzinfo).date() if observation_started_at else None
    latencies = list(lag_by_event.values())
    critical_latency_rows = [
        (event_id, lag, publish_date_by_event.get(event_id))
        for event_id, lag in lag_by_event.items() if event_id in critical_event_ids
    ]
    critical_latencies = [lag for _, lag, published in critical_latency_rows if not observation_date or (published and published >= observation_date)]
    critical_backfills = sum(1 for _, _, published in critical_latency_rows if observation_date and published and published < observation_date)
    critical_within_1d_rate = (
        round(sum(lag <= 1 for lag in critical_latencies) / len(critical_latencies), 4)
        if critical_latencies else None
    )

    observed_dates = [_date(_fields(record).get("First Seen At")) for record in active_events]
    observed_dates = [item for item in observed_dates if item]
    effective_observation_date = observation_date or (min(observed_dates) if observed_dates else None)
    observation_days = max(0, (today - effective_observation_date).days + 1) if effective_observation_date else 0
    signal_count, event_count = len(linked_signals), len(recent_events)
    rolling_cost = _cost(usage, month_cutoff)
    return {
        "as_of": current.isoformat(timespec="seconds"),
        "window": {
            "weekly_start": week_cutoff.isoformat(), "rolling_28d_start": month_cutoff.isoformat(),
            "observation_started_at": observation_started_at.isoformat(timespec="seconds") if observation_started_at else None,
            "observation_days": observation_days,
        },
        "metrics": {
            "raw_news_discovered_7d": len(raw_signals),
            "high_relevance_signals_7d": signal_count,
            "event_cases_created_7d": event_count,
            "active_event_cases": len(active_events),
            "critical_event_cases_7d": critical_recent,
            "critical_event_cases_active": critical_active,
            "accepted_event_cases": accepted_count,
            "deep_research_ready_event_cases": deep_research_ready_count,
            "event_cases_awaiting_news_review": sum(cell_text(_fields(record).get("Status")) == "待处理" for record in active_events),
            "business_mapping_completeness": round(business_mapped / len(active_events), 4) if active_events else None,
            "specific_event_type_completeness": round(event_typed / len(active_events), 4) if active_events else None,
            "candidate_lineage_completeness": round(candidate_traceable / len(active_events), 4) if active_events else None,
            "accepted_lineage_completeness": round(accepted_traceable / accepted_count, 4) if accepted_count else None,
            "median_publish_to_event_lag_days": median(latencies) if latencies else None,
            "critical_detection_within_1d_rate_7d": critical_within_1d_rate,
            "critical_backfill_events_7d": critical_backfills,
            "publish_to_event_lag_resolution": "date_only",
            "automatic_final_p0_violations": automatic_p0_violations,
            "api_cost_usd_28d": rolling_cost,
        },
        "targets": {
            "high_relevance_signals_7d": {"target": "10-30", "status": "met" if 10 <= signal_count <= 30 else "below" if signal_count < 10 else "above"},
            "event_cases_created_7d": {"target": "5-10", "status": "met" if 5 <= event_count <= 10 else "below" if event_count < 5 else "above"},
            "candidate_lineage_completeness": {"target": 1.0, "status": "met" if active_events and candidate_traceable == len(active_events) else "not_met"},
            "automatic_final_p0_violations": {"target": 0, "status": "met" if automatic_p0_violations == 0 else "not_met"},
            "critical_detection_within_1d_rate_7d": {"target": 1.0, "status": "no_data" if critical_within_1d_rate is None else "met" if critical_within_1d_rate == 1.0 else "not_met"},
            "api_cost_usd_28d": {"target_max": 25.0, "status": "met" if rolling_cost <= 25 else "not_met"},
        },
        "four_week_success_status": "observation_incomplete" if observation_days < 28 else "requires_weekly_snapshot_review",
    }
