from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .dingtalk_ai_table import add_records, create_sheet, ensure_fields, list_records, list_sheets, update_records
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


INSIGHTS_SHEET_NAME = "Insights"
INSIGHT_FIELDS = [
    {"name": "Report ID", "type": "text"},
    {"name": "Report Type", "type": "text"},
    {"name": "Status", "type": "text"},
    {"name": "Period", "type": "text"},
    {"name": "Generated At", "type": "text"},
    {"name": "Feedback Deadline", "type": "text"},
    {"name": "Published At", "type": "text"},
    {"name": "Source Sheet", "type": "text"},
    {"name": "Source Record Count", "type": "text"},
    {"name": "Source Record IDs", "type": "text"},
    {"name": "Research ID", "type": "text"},
    {"name": "Evidence IDs", "type": "text"},
    {"name": "Claim IDs", "type": "text"},
    {"name": "Research Quality Status", "type": "text"},
    {"name": "Research Quality Gate", "type": "text"},
    {"name": "Title", "type": "text"},
    {"name": "Report Content", "type": "text"},
    {"name": "Report Doc URL", "type": "text"},
    {"name": "Report Doc Node ID", "type": "text"},
    {"name": "Report Doc Key", "type": "text"},
    {"name": "Report Doc Workspace ID", "type": "text"},
    {"name": "Image Report URL", "type": "text"},
    {"name": "Image Report Node ID", "type": "text"},
    {"name": "Image Report Key", "type": "text"},
    {"name": "Text Report URL", "type": "text"},
    {"name": "Text Report Node ID", "type": "text"},
    {"name": "Text Report Key", "type": "text"},
    {"name": "Image File Path", "type": "text"},
    {"name": "Image Permission Status", "type": "text"},
    {"name": "Image Permission Message", "type": "text"},
    {"name": "Text Permission Status", "type": "text"},
    {"name": "Text Permission Message", "type": "text"},
    {"name": "Image DingTalk Status", "type": "text"},
    {"name": "Image DingTalk Message", "type": "text"},
    {"name": "Text DingTalk Status", "type": "text"},
    {"name": "Text DingTalk Message", "type": "text"},
    {"name": "DingTalk Status", "type": "text"},
    {"name": "DingTalk Message", "type": "text"},
]


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _insights_table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def ensure_insights_sheet(settings: AppSettings, store: Optional[SettingsStore] = None) -> DingTalkAITableSettings:
    sheet_id = settings.dingtalk_ai_table.insights_sheet_id.strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk AI table sheets"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, INSIGHTS_SHEET_NAME)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, INSIGHTS_SHEET_NAME, INSIGHT_FIELDS)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or "failed to create Insights sheet"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError("Insights sheet id is missing")

    insights_table = _insights_table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, insights_table, INSIGHT_FIELDS)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or "failed to ensure Insights fields"))

    if settings.dingtalk_ai_table.insights_sheet_id != sheet_id:
        settings.dingtalk_ai_table.insights_sheet_id = sheet_id
        if store:
            store.save(settings)
    return insights_table


def save_insight_report(
    settings: AppSettings,
    insights_table: DingTalkAITableSettings,
    report_id: str,
    report_type: str,
    status: str,
    period: str,
    content: str,
    source_records: List[Dict[str, Any]],
    generated_at: datetime,
    feedback_deadline: str = "",
    published_at: str = "",
    report_content_excerpt: str = "",
    report_doc_url: str = "",
    report_doc_node_id: str = "",
    report_doc_key: str = "",
    report_doc_workspace_id: str = "",
    image_report_url: str = "",
    image_report_node_id: str = "",
    image_report_key: str = "",
    text_report_url: str = "",
    text_report_node_id: str = "",
    text_report_key: str = "",
    image_file_path: str = "",
    image_permission_status: str = "",
    image_permission_message: str = "",
    text_permission_status: str = "",
    text_permission_message: str = "",
    image_dingtalk_status: str = "",
    image_dingtalk_message: str = "",
    text_dingtalk_status: str = "",
    text_dingtalk_message: str = "",
    dingtalk_status: str = "",
    dingtalk_message: str = "",
    research_id: str = "",
    evidence_ids: str = "",
    claim_ids: str = "",
    research_quality_status: str = "",
    research_quality_gate: str = "",
) -> str:
    source_ids = [str(record.get("id") or "") for record in source_records if record.get("id")]
    fields = {
        "Report ID": report_id,
        "Report Type": report_type,
        "Status": status,
        "Period": period,
        "Generated At": generated_at.isoformat(timespec="seconds"),
        "Feedback Deadline": feedback_deadline,
        "Published At": published_at,
        "Source Sheet": settings.dingtalk_ai_table.sheet_id,
        "Source Record Count": str(len(source_records)),
        "Source Record IDs": ", ".join(source_ids),
        "Research ID": research_id,
        "Evidence IDs": evidence_ids,
        "Claim IDs": claim_ids,
        "Research Quality Status": research_quality_status,
        "Research Quality Gate": research_quality_gate,
        "Title": content.splitlines()[0] if content else "",
        "Report Content": report_content_excerpt or content,
        "Report Doc URL": report_doc_url,
        "Report Doc Node ID": report_doc_node_id,
        "Report Doc Key": report_doc_key,
        "Report Doc Workspace ID": report_doc_workspace_id,
        "Image Report URL": image_report_url,
        "Image Report Node ID": image_report_node_id,
        "Image Report Key": image_report_key,
        "Text Report URL": text_report_url,
        "Text Report Node ID": text_report_node_id,
        "Text Report Key": text_report_key,
        "Image File Path": image_file_path,
        "Image Permission Status": image_permission_status,
        "Image Permission Message": image_permission_message,
        "Text Permission Status": text_permission_status,
        "Text Permission Message": text_permission_message,
        "Image DingTalk Status": image_dingtalk_status,
        "Image DingTalk Message": image_dingtalk_message,
        "Text DingTalk Status": text_dingtalk_status,
        "Text DingTalk Message": text_dingtalk_message,
        "DingTalk Status": dingtalk_status,
        "DingTalk Message": dingtalk_message,
    }
    existing = list_records(settings.dingtalk, insights_table)
    for record in existing:
        record_fields = record.get("fields") or {}
        if str(record_fields.get("Report ID") or "") == report_id:
            updated = update_records(settings.dingtalk, insights_table, [{"id": record["id"], "fields": fields}])
            if updated.status != "sent":
                raise RuntimeError(updated.message)
            return str(record["id"])
    created = add_records(settings.dingtalk, insights_table, [fields])
    if created.status != "sent" or not created.record_ids:
        raise RuntimeError(created.message)
    return created.record_ids[0]
