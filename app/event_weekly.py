from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .dingtalk_ai_table import cell_text, ensure_fields, list_records, update_records
from .event_intelligence import publication_eligible
from .models import AppSettings, DingTalkAITableSettings
from .publish_dates import parse_date
from .weekly_report import select_weekly_records


@dataclass
class WeeklyInput:
    mode: str
    report_records: List[Dict[str, Any]]
    range_label: str
    event_records: List[Dict[str, Any]]
    linked_news_ids: List[str]
    source_table: DingTalkAITableSettings


def _table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def _date_in_range(value: Any, start: datetime, end: datetime) -> bool:
    parsed = parse_date(value)
    if not parsed:
        return False
    try:
        observed = datetime.fromisoformat(parsed).date()
    except ValueError:
        return False
    return start.date() <= observed <= end.date()


def _lineage_by_event(settings: AppSettings) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    evidence: Dict[str, List[Dict[str, Any]]] = {}
    claims: Dict[str, List[Dict[str, Any]]] = {}
    if settings.dingtalk_ai_table.evidence_bank_sheet_id:
        for row in list_records(settings.dingtalk, _table(settings, settings.dingtalk_ai_table.evidence_bank_sheet_id)):
            event_id = cell_text((row.get("fields") or {}).get("Event ID"))
            if event_id:
                evidence.setdefault(event_id, []).append(row)
    if settings.dingtalk_ai_table.claim_ledger_sheet_id:
        for row in list_records(settings.dingtalk, _table(settings, settings.dingtalk_ai_table.claim_ledger_sheet_id)):
            event_id = cell_text((row.get("fields") or {}).get("Event ID"))
            if event_id:
                claims.setdefault(event_id, []).append(row)
    return evidence, claims


def _lineage_ready(event_id: str, evidence: Dict[str, List[Dict[str, Any]]], claims: Dict[str, List[Dict[str, Any]]]) -> bool:
    verified = [row for row in evidence.get(event_id, []) if cell_text((row.get("fields") or {}).get("Reviewer Status")).lower() == "verified"]
    approved = [row for row in claims.get(event_id, []) if cell_text((row.get("fields") or {}).get("Reviewer Status")).lower() == "approved"]
    return bool(verified and approved)


def _event_report_record(event: Dict[str, Any], sources: Sequence[Dict[str, Any]], evidence: Sequence[Dict[str, Any]], claims: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    fields = event.get("fields") or {}
    event_id = cell_text(fields.get("Event ID"))
    primary_url = fields.get("Primary Source URL")
    source_rows = [row for row in sources if cell_text((row.get("fields") or {}).get("Event ID")) == event_id]
    news_ids = [cell_text((row.get("fields") or {}).get("News Record ID")) for row in source_rows]
    event_source_ids = [cell_text((row.get("fields") or {}).get("Event Source ID")) for row in source_rows]
    evidence_ids = [cell_text((row.get("fields") or {}).get("Evidence ID")) for row in evidence]
    claim_ids = [cell_text((row.get("fields") or {}).get("Claim ID")) for row in claims]
    return {
        "id": str(event.get("id") or event_id),
        "fields": {
            "Event ID": event_id,
            "Title": cell_text(fields.get("Event Title")),
            "Label": cell_text(fields.get("Event Type")),
            "Section": cell_text(fields.get("Business Lines")) or "Event Intelligence",
            "Source URL": primary_url,
            "Publish Date": cell_text(fields.get("Publish Date")),
            "Status": "已采纳",
            "Review Status": "已采纳",
            "Priority Candidate": cell_text(fields.get("Priority Candidate")),
            "Final Priority": cell_text(fields.get("Final Priority")),
            "Summary": cell_text(fields.get("Summary")),
            "GBSS Impact Hypothesis": cell_text(fields.get("GBSS Impact Hypothesis")),
            "Limitations": cell_text(fields.get("Limitations")),
            "Source News Record IDs": ", ".join(item for item in news_ids if item),
            "Event Source IDs": ", ".join(item for item in event_source_ids if item),
            "Evidence IDs": ", ".join(item for item in evidence_ids if item),
            "Claim IDs": ", ".join(item for item in claim_ids if item),
        },
    }


def load_weekly_input(settings: AppSettings, now: datetime, *, days: int, recent_count: int, include_sent: bool, max_items: int, sent_fields: Sequence[str]) -> WeeklyInput:
    if settings.event_intelligence.weekly_input_mode == "news":
        records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        selected, label = select_weekly_records(records, settings.dingtalk_ai_table.field_mapping, now, days=days, recent_count=recent_count, include_sent=include_sent, max_items=max_items, sent_fields=sent_fields)
        return WeeklyInput("news", selected, label, [], [], settings.dingtalk_ai_table)
    sheet_id = settings.dingtalk_ai_table.event_cases_sheet_id
    source_sheet_id = settings.dingtalk_ai_table.event_sources_sheet_id
    if not sheet_id or not source_sheet_id:
        raise RuntimeError("Event Cases/Event Sources sheet is not configured; event mode fails closed")
    event_table, source_table = _table(settings, sheet_id), _table(settings, source_sheet_id)
    events = list_records(settings.dingtalk, event_table)
    sources = list_records(settings.dingtalk, source_table)
    evidence_by_event, claims_by_event = _lineage_by_event(settings)
    end = now
    start = now - timedelta(days=max(days - 1, 0))
    selected = []
    for event in events:
        fields = event.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        if not publication_eligible(fields) or not _lineage_ready(event_id, evidence_by_event, claims_by_event):
            continue
        if not include_sent and any(cell_text(fields.get(name)) for name in sent_fields):
            continue
        if not _date_in_range(fields.get("Publish Date"), start, end):
            continue
        selected.append(event)
    selected.sort(key=lambda row: float(cell_text((row.get("fields") or {}).get("Relevance Score")) or 0), reverse=True)
    if recent_count > 0:
        selected = selected[:recent_count]
    else:
        selected = selected[:max_items]
    report_records = []
    linked_news_ids: List[str] = []
    for event in selected:
        event_id = cell_text((event.get("fields") or {}).get("Event ID"))
        report = _event_report_record(event, sources, evidence_by_event.get(event_id, []), claims_by_event.get(event_id, []))
        report_records.append(report)
        linked_news_ids.extend(item.strip() for item in cell_text(report["fields"].get("Source News Record IDs")).split(",") if item.strip())
    return WeeklyInput("event_cases", report_records, f"{start:%b %d} - {end:%b %d}".upper(), selected, list(dict.fromkeys(linked_news_ids)), event_table)


def write_sent_markers(settings: AppSettings, weekly_input: WeeklyInput, field_name: str, sent_at: str) -> List[str]:
    updated = []
    if weekly_input.mode == "news":
        ensured = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, [{"name": field_name, "type": "text"}])
        if not ensured.get("ok"):
            raise RuntimeError(str(ensured.get("message") or f"failed to ensure {field_name}"))
        rows = [{"id": row["id"], "fields": {field_name: sent_at}} for row in weekly_input.report_records]
        if rows:
            result = update_records(settings.dingtalk, settings.dingtalk_ai_table, rows)
            if result.status != "sent":
                raise RuntimeError(result.message)
            updated.extend(result.record_ids)
        return updated
    ensured = ensure_fields(settings.dingtalk, weekly_input.source_table, [{"name": field_name, "type": "text"}])
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or f"failed to ensure {field_name}"))
    event_rows = [{"id": row["id"], "fields": {field_name: sent_at}} for row in weekly_input.event_records]
    if event_rows:
        result = update_records(settings.dingtalk, weekly_input.source_table, event_rows)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated.extend(result.record_ids)
    if weekly_input.linked_news_ids:
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, [{"id": row_id, "fields": {field_name: sent_at}} for row_id in weekly_input.linked_news_ids])
        if result.status != "sent":
            raise RuntimeError(result.message)
    return updated
