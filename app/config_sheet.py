from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Iterable, List, Optional

from .dingtalk_ai_table import add_records, create_sheet, ensure_fields, list_records, list_sheets, update_records
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


CONFIG_SHEET_NAME = "Config"
CONFIG_FIELDS = [
    {"name": "Config Key", "type": "text"},
    {"name": "Group", "type": "text"},
    {"name": "Name", "type": "text"},
    {"name": "Value", "type": "text"},
    {"name": "Value Type", "type": "text"},
    {"name": "Editable", "type": "text"},
    {"name": "Description", "type": "text"},
    {"name": "Updated At", "type": "text"},
]

SCHEDULE_PATTERN = re.compile(r"weekdays=\[(?P<weekdays>[0-6,\s]*)\];\s*time=(?P<hour>\d{1,2}):(?P<minute>\d{2})")


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _config_table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def ensure_config_sheet(settings: AppSettings, store: Optional[SettingsStore] = None) -> DingTalkAITableSettings:
    sheet_id = settings.dingtalk_ai_table.config_sheet_id.strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk AI table sheets"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, CONFIG_SHEET_NAME)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, CONFIG_SHEET_NAME, CONFIG_FIELDS)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or "failed to create Config sheet"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError("Config sheet id is missing")

    config_table = _config_table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, config_table, CONFIG_FIELDS)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or "failed to ensure Config fields"))

    if settings.dingtalk_ai_table.config_sheet_id != sheet_id:
        settings.dingtalk_ai_table.config_sheet_id = sheet_id
        if store:
            store.save(settings)
    return config_table


def _time_value(hour: int, minute: int, weekdays: Iterable[int]) -> str:
    return f"weekdays={list(weekdays)}; time={hour:02d}:{minute:02d}"


def _item(
    key: str,
    group: str,
    name: str,
    value: Any,
    value_type: str,
    description: str,
    editable: bool = True,
) -> Dict[str, Any]:
    return {
        "Config Key": key,
        "Group": group,
        "Name": name,
        "Value": str(value),
        "Value Type": value_type,
        "Editable": "yes" if editable else "no",
        "Description": description,
    }


def default_config_items(settings: AppSettings) -> List[Dict[str, Any]]:
    schedule = settings.schedule
    ai_table = settings.dingtalk_ai_table
    return [
        _item("sheets.news.sheet_id", "Sheets", "News Sheet ID", ai_table.sheet_id, "sheet_id", "Source headline table. Keep News and Insights separate.", False),
        _item("sheets.insights.sheet_id", "Sheets", "Insights Sheet ID", ai_table.insights_sheet_id, "sheet_id", "Weekly insight draft/final report storage.", False),
        _item("sheets.audit_trail.sheet_id", "Sheets", "Audit Trail Sheet ID", ai_table.audit_trail_sheet_id, "sheet_id", "Append-only workflow, step, artifact, result, and error audit records.", False),
        _item("sheets.config.sheet_id", "Sheets", "Config Sheet ID", ai_table.config_sheet_id, "sheet_id", "Central view of configurable workflow values.", False),
        _item("sheets.research_topics.sheet_id", "Sheets", "Research Topics Sheet ID", ai_table.research_topics_sheet_id, "sheet_id", "Rolling weekly research topic roadmap.", False),
        _item("sheets.research_queue.sheet_id", "Sheets", "Research Queue Sheet ID", ai_table.research_queue_sheet_id, "sheet_id", "Locked weekly research question, source plan and evidence freeze state.", False),
        _item("sheets.evidence_bank.sheet_id", "Sheets", "Evidence Bank Sheet ID", ai_table.evidence_bank_sheet_id, "sheet_id", "Atomic source evidence used to support or challenge weekly claims.", False),
        _item("sheets.claim_ledger.sheet_id", "Sheets", "Claim Ledger Sheet ID", ai_table.claim_ledger_sheet_id, "sheet_id", "Fact, inference and hypothesis approval ledger for management report statements.", False),
        _item("sheets.research_results.sheet_id", "Sheets", "Research Results Sheet ID", ai_table.research_results_sheet_id, "sheet_id", "Full external research outputs, provider metadata and document links.", False),
        _item("sheets.detect_sources.sheet_id", "Sheets", "Detect Sources Sheet ID", ai_table.detect_sources_sheet_id, "sheet_id", "Companies, competitor benchmarks, topics, and source domains used to build daily collection queries.", False),
        _item("sheets.event_cases.sheet_id", "Sheets", "Event Cases Sheet ID", ai_table.event_cases_sheet_id, "sheet_id", "Canonical event review and weekly input table.", False),
        _item("sheets.event_entities.sheet_id", "Sheets", "Event Entities Sheet ID", ai_table.event_entities_sheet_id, "sheet_id", "Event-to-entity relations.", False),
        _item("sheets.event_sources.sheet_id", "Sheets", "Event Sources Sheet ID", ai_table.event_sources_sheet_id, "sheet_id", "Event-to-News and source lineage.", False),
        _item("sheets.event_scores.sheet_id", "Sheets", "Event Scores Sheet ID", ai_table.event_scores_sheet_id, "sheet_id", "Explainable event score components.", False),
        _item("sheets.entity_catalog.sheet_id", "Sheets", "Entity Catalog Sheet ID", ai_table.entity_catalog_sheet_id, "sheet_id", "Human-maintained entity, alias, ticker and official-source catalog.", False),
        _item("sheets.alert_log.sheet_id", "Sheets", "Alert Log Sheet ID", ai_table.alert_log_sheet_id, "sheet_id", "Deduplicated strategic and P0 Candidate alerts.", False),
        _item("sheets.api_usage.sheet_id", "Sheets", "API Usage Sheet ID", ai_table.api_usage_sheet_id, "sheet_id", "Cost estimates, actual usage and budget skips.", False),
        _item("reports.daily_review.enabled", "Daily News Review", "Daily review reminder enabled", schedule.daily_remind.enabled, "boolean", "Whether reviewers receive the daily pending-review reminder."),
        _item("reports.daily_review.schedule", "Daily News Review", "Daily review reminder schedule", _time_value(schedule.daily_remind.hour, schedule.daily_remind.minute, schedule.daily_remind.weekdays), "schedule", "Every day at 09:00; launchd weekdays use Sunday=0."),
        _item("reports.daily_review.ai_suggest_schedule", "Daily News Review", "AI pre-review schedule", _time_value(schedule.ai_review_suggest.hour, schedule.ai_review_suggest.minute, schedule.ai_review_suggest.weekdays), "schedule", "Every day at 08:50, write AI Status before the human review reminder."),
        _item("reports.daily_review.ai_deadline_schedule", "Daily News Review", "AI deadline fallback schedule", _time_value(schedule.ai_review_deadline.hour, schedule.ai_review_deadline.minute, schedule.ai_review_deadline.weekdays), "schedule", "Every day at 11:50, auto-accept only high-confidence traceable pending News."),
        _item("reports.daily_review.source_sheet", "Daily News Review", "Daily review source sheet", "News", "sheet_name", "Reviewers process only previous-day pending News linked to an Event Case.", False),
        _item("reports.weekly_headlines.enabled", "Daily Report", "Daily report publish enabled", schedule.weekly_headlines.enabled, "boolean", "Whether management receives the daily accepted-news report. The legacy config key is retained for compatibility."),
        _item("reports.weekly_headlines.schedule", "Daily Report", "Daily report publish schedule", _time_value(schedule.weekly_headlines.hour, schedule.weekly_headlines.minute, schedule.weekly_headlines.weekdays), "schedule", "Daily management report schedule; target is 12:00 every day, leaving one hour for review before manual forwarding at 13:00."),
        _item("reports.weekly_headlines.lookback_days", "Daily Report", "Daily report recovery window", settings.rules.daily_report_lookback_days, "integer", "Publish-date recovery window; sent markers ensure each accepted Event is delivered once."),
        _item("reports.weekly_headlines.max_items", "Daily Report", "Daily report max items", settings.rules.max_items_per_category, "integer", "Maximum accepted events shown in the daily report."),
        _item("reports.weekly_headlines.source_sheet", "Daily Report", "Daily report source sheet", "News / Event Cases", "sheet_name", "Daily Report selects accepted News-backed Events and writes Daily Report Sent At.", False),
        _item("reports.weekly_intelligence.enabled", "Weekly Intelligence", "Weekly intelligence publish enabled", schedule.weekly_publish.enabled, "boolean", "Whether the final management analysis report is enabled."),
        _item("reports.weekly_intelligence.draft_schedule", "Weekly Intelligence", "Legacy image draft schedule", _time_value(schedule.weekly_draft.hour, schedule.weekly_draft.minute, schedule.weekly_draft.weekdays), "schedule", "Disabled: manual ChatGPT research link delivery replaces the generated image One Pager."),
        _item("reports.weekly_intelligence.final_schedule", "Weekly Intelligence", "Weekly report-link delivery schedule", _time_value(schedule.weekly_publish.hour, schedule.weekly_publish.minute, schedule.weekly_publish.weekdays), "schedule", "Sunday noon sends Research Document URL plus accepted Event/news digest."),
        _item("reports.weekly_intelligence.lookback_days", "Weekly Intelligence", "Weekly intelligence lookback days", settings.rules.weekly_report_lookback_days, "integer", "Number of publish-date days included in weekly analysis selection."),
        _item("reports.weekly_intelligence.max_items", "Weekly Intelligence", "Weekly intelligence max items", settings.rules.max_items_per_category, "integer", "Maximum source items used in the weekly analysis report."),
        _item("reports.weekly_intelligence.output_sheet", "Weekly Intelligence", "Weekly intelligence output sheet", "Insights", "sheet_name", "Draft and final analysis reports are stored in Insights.", False),
        _item("reports.weekly_intelligence.document_workspace_id", "Weekly Intelligence", "Weekly report document workspace id", ai_table.report_docs_workspace_id, "workspace_id", "DingTalk knowledge workspace used for full weekly report documents."),
        _item("reports.weekly_intelligence.document_folder_node_id", "Weekly Intelligence", "Weekly report document folder node id", ai_table.report_docs_folder_node_id, "node_id", "DingTalk folder node used for one full report document per week."),
        _item("reports.weekly_intelligence.document_folder_url", "Weekly Intelligence", "Weekly report document folder url", ai_table.report_docs_folder_url, "url", "DWS folder URL used as the parent directory for weekly report documents."),
        _item("reports.weekly_intelligence.document_folder_name", "Weekly Intelligence", "Weekly report document folder name", ai_table.report_docs_folder_name, "text", "Folder name to create or reuse when folder node id is blank."),
        _item("reports.weekly_intelligence.prompt", "Weekly Intelligence", "Weekly intelligence prompt", settings.prompts.weekly_publish, "text", "Report structure and analysis requirements."),
        _item("research.rhythm", "Research Topics", "Research rhythm", "one topic per week + next 4 topics preview", "text", "Weekly synchronization model for management mindshare.", False),
        _item("research.topic_scoring", "Research Topics", "Topic scoring logic", "strategic relevance + external momentum + competitor movement + decision urgency + evidence quality", "text", "How topics should be selected and prioritized.", False),
        _item("research.provider", "External Research", "External research provider", "OpenAI / ChatGPT", "text", "Provider currently wired for full external research generation. Gemini can use the same Research Results output contract.", False),
        _item("research.openai.enabled", "External Research", "Project OpenAI Deep Research enabled", settings.openai_research.enabled, "boolean", "Keep disabled: the owner runs ChatGPT Deep Research manually and pastes a DingTalk document link.", False),
        _item("research.openai.model", "External Research", "OpenAI Deep Research model", settings.openai_research.model, "text", "Configured model for the approved external research run.", False),
        _item("schema.event_intelligence.version", "Event Intelligence", "Event intelligence schema version", settings.event_intelligence.schema_version, "text", "Idempotent DingTalk schema version.", False),
        _item("event.enabled", "Event Intelligence", "Event intelligence enabled", settings.event_intelligence.enabled, "boolean", "Enable News-to-Event processing."),
        _item("event.critical_scan_enabled", "Event Intelligence", "Critical scan enabled", settings.event_intelligence.critical_scan_enabled, "boolean", "Enable the dual-mode critical event scan."),
        _item("event.critical_scan_lookback_days", "Event Intelligence", "Critical scan lookback days", settings.event_intelligence.critical_scan_lookback_days, "integer", "Ignore dated critical-source items older than this rolling window."),
        _item("event.weekly_input_mode", "Event Intelligence", "Weekly input mode", settings.event_intelligence.weekly_input_mode, "enum", "Use news for rollback or event_cases after release gate."),
        _item("event.review_view_url", "Event Intelligence", "Event review view URL", settings.event_intelligence.review_view_url, "url", "Direct reviewer link to the Event Cases view."),
        _item("event.openai.enabled", "Event Intelligence", "Event OpenAI enabled", settings.openai_service.enabled, "boolean", "Allow budget-gated structured event analysis."),
        _item("event.openai.classification_model", "Event Intelligence", "Classification model", settings.openai_service.classification_model, "text", "Low-cost structured classification model.", False),
        _item("event.openai.analysis_model", "Event Intelligence", "Analysis model", settings.openai_service.analysis_model, "text", "Structured event summary and review model.", False),
        _item("event.budget.monthly_usd", "Event Intelligence", "Monthly API hard cap", settings.openai_service.monthly_cap_usd, "float", "Application-side monthly API cap."),
        _item("system.timezone", "System", "Timezone", settings.system.timezone, "timezone", "Timezone used for schedules and generated timestamps."),
        _item("dingtalk.daily_webhook.configured", "DingTalk", "Daily webhook configured", bool(settings.dingtalk.daily_webhook_url), "boolean", "Configuration presence only; secret values are not stored here.", False),
        _item("dingtalk.weekly_webhook.configured", "DingTalk", "Weekly webhook configured", bool(settings.dingtalk.weekly_webhook_url), "boolean", "Configuration presence only; secret values are not stored here.", False),
    ]


def sync_config_items(
    settings: AppSettings,
    config_table: DingTalkAITableSettings,
    items: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> List[str]:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    desired = []
    for item in items or default_config_items(settings):
        row = dict(item)
        row["Updated At"] = timestamp
        desired.append(row)

    existing = list_records(settings.dingtalk, config_table)
    existing_by_key = {
        str((record.get("fields") or {}).get("Config Key") or ""): record
        for record in existing
        if (record.get("fields") or {}).get("Config Key")
    }

    created_or_updated: List[str] = []
    to_create = []
    to_update = []
    for row in desired:
        key = str(row["Config Key"])
        existing_record = existing_by_key.get(key)
        if existing_record:
            to_update.append({"id": existing_record["id"], "fields": row})
            created_or_updated.append(str(existing_record["id"]))
        else:
            to_create.append(row)

    if to_update:
        result = update_records(settings.dingtalk, config_table, to_update)
        if result.status != "sent":
            raise RuntimeError(result.message)
    if to_create:
        result = add_records(settings.dingtalk, config_table, to_create)
        if result.status != "sent":
            raise RuntimeError(result.message)
        created_or_updated.extend(result.record_ids)
    return created_or_updated


def _bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "启用"}


def _int_value(value: Any, minimum: int, maximum: int) -> int:
    parsed = int(str(value).strip())
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"integer value must be between {minimum} and {maximum}")
    return parsed


def _schedule_value(value: Any) -> Dict[str, Any]:
    match = SCHEDULE_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise ValueError("schedule must use format: weekdays=[0, 1]; time=12:00")
    weekdays_text = match.group("weekdays").strip()
    weekdays = [] if not weekdays_text else [int(item.strip()) for item in weekdays_text.split(",") if item.strip()]
    if any(weekday < 0 or weekday > 6 for weekday in weekdays):
        raise ValueError("weekdays must use launchd values from 0 to 6")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour > 23 or minute > 59:
        raise ValueError("schedule time is out of range")
    return {"weekdays": weekdays, "hour": hour, "minute": minute}


def apply_config_items(settings: AppSettings, records: List[Dict[str, Any]]) -> List[str]:
    applied: List[str] = []
    for record in records:
        fields = record.get("fields") or {}
        if str(fields.get("Editable") or "").lower() not in {"yes", "true", "1"}:
            continue
        key = str(fields.get("Config Key") or "")
        value = fields.get("Value")
        if key == "reports.daily_review.enabled":
            settings.schedule.daily_remind.enabled = _bool_value(value)
        elif key == "reports.daily_review.schedule":
            parsed = _schedule_value(value)
            settings.schedule.daily_remind.hour = parsed["hour"]
            settings.schedule.daily_remind.minute = parsed["minute"]
            settings.schedule.daily_remind.weekdays = parsed["weekdays"]
        elif key == "reports.daily_review.ai_suggest_schedule":
            parsed = _schedule_value(value)
            settings.schedule.ai_review_suggest.hour = parsed["hour"]
            settings.schedule.ai_review_suggest.minute = parsed["minute"]
            settings.schedule.ai_review_suggest.weekdays = parsed["weekdays"]
        elif key == "reports.daily_review.ai_deadline_schedule":
            parsed = _schedule_value(value)
            settings.schedule.ai_review_deadline.hour = parsed["hour"]
            settings.schedule.ai_review_deadline.minute = parsed["minute"]
            settings.schedule.ai_review_deadline.weekdays = parsed["weekdays"]
        elif key == "reports.weekly_headlines.enabled":
            settings.schedule.weekly_headlines.enabled = _bool_value(value)
        elif key == "reports.weekly_headlines.schedule":
            parsed = _schedule_value(value)
            settings.schedule.weekly_headlines.hour = parsed["hour"]
            settings.schedule.weekly_headlines.minute = parsed["minute"]
            settings.schedule.weekly_headlines.weekdays = parsed["weekdays"]
        elif key == "reports.weekly_headlines.lookback_days":
            settings.rules.daily_report_lookback_days = _int_value(value, 1, 30)
        elif key == "reports.weekly_headlines.max_items":
            settings.rules.max_items_per_category = _int_value(value, 1, 50)
        elif key == "reports.weekly_intelligence.enabled":
            settings.schedule.weekly_publish.enabled = _bool_value(value)
        elif key == "reports.weekly_intelligence.draft_schedule":
            parsed = _schedule_value(value)
            settings.schedule.weekly_draft.hour = parsed["hour"]
            settings.schedule.weekly_draft.minute = parsed["minute"]
            settings.schedule.weekly_draft.weekdays = parsed["weekdays"]
        elif key == "reports.weekly_intelligence.final_schedule":
            parsed = _schedule_value(value)
            settings.schedule.weekly_publish.hour = parsed["hour"]
            settings.schedule.weekly_publish.minute = parsed["minute"]
            settings.schedule.weekly_publish.weekdays = parsed["weekdays"]
        elif key == "event.enabled":
            settings.event_intelligence.enabled = _bool_value(value)
        elif key == "event.critical_scan_enabled":
            settings.event_intelligence.critical_scan_enabled = _bool_value(value)
        elif key == "event.critical_scan_lookback_days":
            settings.event_intelligence.critical_scan_lookback_days = _int_value(value, 1, 30)
        elif key == "event.weekly_input_mode":
            candidate = str(value).strip()
            if candidate not in {"news", "event_cases"}:
                raise ValueError("event.weekly_input_mode must be news or event_cases")
            settings.event_intelligence.weekly_input_mode = candidate
        elif key == "event.review_view_url":
            settings.event_intelligence.review_view_url = str(value or "").strip()
        elif key == "event.openai.enabled":
            settings.openai_service.enabled = _bool_value(value)
        elif key == "system.timezone":
            settings.system.timezone = str(value or "").strip()
        elif key == "reports.weekly_intelligence.lookback_days":
            settings.rules.weekly_report_lookback_days = _int_value(value, 1, 90)
        elif key == "reports.weekly_intelligence.max_items":
            settings.rules.max_items_per_category = _int_value(value, 1, 50)
        elif key == "reports.weekly_intelligence.document_workspace_id":
            settings.dingtalk_ai_table.report_docs_workspace_id = str(value or "").strip()
        elif key == "reports.weekly_intelligence.document_folder_node_id":
            settings.dingtalk_ai_table.report_docs_folder_node_id = str(value or "").strip()
        elif key == "reports.weekly_intelligence.document_folder_url":
            settings.dingtalk_ai_table.report_docs_folder_url = str(value or "").strip()
        elif key == "reports.weekly_intelligence.document_folder_name":
            settings.dingtalk_ai_table.report_docs_folder_name = str(value or "").strip() or "GBSS Research Reports"
        elif key == "reports.weekly_intelligence.prompt":
            settings.prompts.weekly_publish = str(value or "")
        elif key == "sheets.detect_sources.sheet_id":
            settings.dingtalk_ai_table.detect_sources_sheet_id = str(value or "").strip()
        else:
            continue
        applied.append(key)
    return applied
