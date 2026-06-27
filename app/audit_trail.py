from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
from uuid import uuid4

from .dingtalk_ai_table import add_records, create_sheet, ensure_fields, list_sheets
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore
from .run_logs import RunLogStore


AUDIT_TRAIL_SHEET_NAME = "Audit Trail"
AUDIT_TRAIL_FIELDS = [
    {"name": "Audit Event ID", "type": "text"},
    {"name": "Run ID", "type": "text"},
    {"name": "Workflow", "type": "text"},
    {"name": "Stage Code", "type": "text"},
    {"name": "Stage Name", "type": "text"},
    {"name": "Status", "type": "text"},
    {"name": "Mode", "type": "text"},
    {"name": "Started At", "type": "text"},
    {"name": "Finished At", "type": "text"},
    {"name": "Duration Ms", "type": "text"},
    {"name": "Input Summary", "type": "text"},
    {"name": "Output Summary", "type": "text"},
    {"name": "Result Count", "type": "text"},
    {"name": "Related Sheet", "type": "text"},
    {"name": "Source Record IDs", "type": "text"},
    {"name": "Report ID", "type": "text"},
    {"name": "Artifact URL", "type": "text"},
    {"name": "Artifact Path", "type": "text"},
    {"name": "Error", "type": "text"},
    {"name": "Metadata JSON", "type": "text"},
    {"name": "Recorded At", "type": "text"},
]


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _audit_table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def ensure_audit_trail_sheet(settings: AppSettings, store: Optional[SettingsStore] = None) -> DingTalkAITableSettings:
    sheet_id = settings.dingtalk_ai_table.audit_trail_sheet_id.strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk AI table sheets"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, AUDIT_TRAIL_SHEET_NAME)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, AUDIT_TRAIL_SHEET_NAME, AUDIT_TRAIL_FIELDS)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or "failed to create Audit Trail sheet"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError("Audit Trail sheet id is missing")

    audit_table = _audit_table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, audit_table, AUDIT_TRAIL_FIELDS)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or "failed to ensure Audit Trail fields"))

    if settings.dingtalk_ai_table.audit_trail_sheet_id != sheet_id:
        settings.dingtalk_ai_table.audit_trail_sheet_id = sheet_id
        if store:
            store.save(settings)
    return audit_table


def _text(value: Any, limit: int = 1800) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _json(value: Dict[str, Any], limit: int = 5000) -> str:
    try:
        text = json.dumps(value or {}, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        text = json.dumps({"unserializable_metadata": str(value)}, ensure_ascii=False)
    return _text(text, limit)


def build_audit_fields(
    *,
    run_id: str,
    workflow: str,
    stage_code: str,
    stage_name: str,
    status: str,
    mode: str = "live",
    started_at: str = "",
    finished_at: str = "",
    duration_ms: Optional[int] = None,
    input_summary: str = "",
    output_summary: str = "",
    result_count: Optional[int] = None,
    related_sheet: str = "",
    source_record_ids: str = "",
    report_id: str = "",
    artifact_url: str = "",
    artifact_path: str = "",
    error: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    event_id: str = "",
    recorded_at: str = "",
) -> Dict[str, str]:
    now = recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "Audit Event ID": event_id or uuid4().hex,
        "Run ID": run_id,
        "Workflow": workflow,
        "Stage Code": stage_code,
        "Stage Name": stage_name,
        "Status": status,
        "Mode": mode,
        "Started At": started_at,
        "Finished At": finished_at,
        "Duration Ms": "" if duration_ms is None else str(duration_ms),
        "Input Summary": _text(input_summary),
        "Output Summary": _text(output_summary),
        "Result Count": "" if result_count is None else str(result_count),
        "Related Sheet": related_sheet,
        "Source Record IDs": _text(source_record_ids, 3000),
        "Report ID": report_id,
        "Artifact URL": artifact_url,
        "Artifact Path": artifact_path,
        "Error": _text(error),
        "Metadata JSON": _json(metadata or {}),
        "Recorded At": now,
    }


@dataclass
class AuditWriteResult:
    status: str
    message: str
    record_id: str = ""


class AuditTrailWriter:
    """Best-effort append-only writer; operational work must not fail only because audit storage is unavailable."""

    def __init__(self, settings: AppSettings, store: Optional[SettingsStore] = None, run_logs: Optional[RunLogStore] = None) -> None:
        self.settings = settings
        self.store = store
        self.run_logs = run_logs
        self._table: Optional[DingTalkAITableSettings] = None

    def record(self, **kwargs: Any) -> AuditWriteResult:
        try:
            if self._table is None:
                self._table = ensure_audit_trail_sheet(self.settings, self.store)
            fields = build_audit_fields(**kwargs)
            result = add_records(self.settings.dingtalk, self._table, [fields])
            record_id = result.record_ids[0] if result.record_ids else ""
            return AuditWriteResult(result.status, result.message, record_id)
        except Exception as exc:
            run_id = str(kwargs.get("run_id") or "")
            if self.run_logs and run_id:
                self.run_logs.append_pending_audit(run_id, dict(kwargs))
            return AuditWriteResult("failed", str(exc))

    def flush_pending(self, limit: int = 100) -> int:
        if not self.run_logs:
            return 0
        flushed = 0
        direct_writer = AuditTrailWriter(self.settings, self.store, None)
        for item in self.run_logs.list_pending_audit(limit=limit):
            all_sent = True
            for event in item["events"]:
                result = direct_writer.record(**event)
                if result.status != "sent":
                    all_sent = False
                    break
                flushed += 1
            if all_sent:
                self.run_logs.clear_pending_audit(item["run_id"])
        return flushed
