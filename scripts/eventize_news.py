"""Aggregate recent News rows into auditable Event Cases."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.event_alerts import send_event_alerts  # noqa: E402
from app.event_intelligence import archive_stale_ai_rejected_events, archive_stale_pending_events, archive_superseded_events, catalog_from_records, enrich_events_with_llm, eventize_records, persist_event_candidates, reconcile_terminal_event_statuses  # noqa: E402
from app.cost_control import BudgetController, DingTalkUsageLedger  # noqa: E402
from app.llm_service import LLMService  # noqa: E402
from app.event_tables import EventIntelligenceTables  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.publish_dates import parse_date  # noqa: E402


parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=14)
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--send-alerts", action="store_true")
args = parser.parse_args()

data = ROOT / "data"
store = SettingsStore(data / "settings.sqlite3", SecretStore(data / "secrets.json"))
settings = store.load(masked=False)
runs = RunLogStore(data / "settings.sqlite3")
run_id = runs.start("eventize_news", provider="dingtalk_ai_table")
audit = AuditTrailWriter(settings, store, runs)


def tables_from_settings() -> EventIntelligenceTables:
    ai = settings.dingtalk_ai_table
    required = [ai.event_cases_sheet_id, ai.event_entities_sheet_id, ai.event_sources_sheet_id, ai.event_scores_sheet_id, ai.entity_catalog_sheet_id, ai.alert_log_sheet_id, ai.api_usage_sheet_id]
    if not all(required):
        raise RuntimeError("v3.1 event schema is not applied")
    table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
    return EventIntelligenceTables(table(ai.event_cases_sheet_id), table(ai.event_entities_sheet_id), table(ai.event_sources_sheet_id), table(ai.event_scores_sheet_id), table(ai.entity_catalog_sheet_id), table(ai.alert_log_sheet_id), table(ai.api_usage_sheet_id))


try:
    tables = tables_from_settings()
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    cutoff = datetime.now(ZoneInfo(settings.system.timezone)).date() - timedelta(days=max(args.days - 1, 0))
    recent_news = []
    for record in news:
        fields = record.get("fields") or {}
        observed = parse_date(fields.get("Publish Date") or fields.get("First Seen At"))
        if observed:
            try:
                if datetime.fromisoformat(observed).date() >= cutoff:
                    recent_news.append(record)
            except ValueError:
                pass
    news = recent_news
    events = eventize_records(news, catalog, settings)
    if settings.openai_service.enabled:
        ledger = DingTalkUsageLedger(settings, tables.api_usage)
        service = LLMService(settings.openai_service, BudgetController(settings.openai_service, ledger, settings.system.timezone), ledger, audit)
        events = enrich_events_with_llm(events, service, settings, run_id)
    summary = [{"event_id": event.event_id, "title": event.title, "type": event.event_type, "priority": event.priority_candidate, "strategic": event.strategic_candidate, "sources": len(event.sources)} for event in events]
    if args.dry_run or not args.apply:
        runs.finish(run_id, "success", result_count=len(events), message="eventize dry-run")
        print(json.dumps({"mode": "dry-run", "events": summary}, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    count = persist_event_candidates(settings, tables, events)
    merged = archive_superseded_events(settings, tables, [event.event_id for event in events])
    reconciled = reconcile_terminal_event_statuses(settings, tables)
    stale_ai_archived = archive_stale_ai_rejected_events(settings, tables, datetime.now(ZoneInfo(settings.system.timezone)).date() - timedelta(days=2))
    archived = archive_stale_pending_events(settings, tables, [event.event_id for event in events], cutoff)
    alerts = send_event_alerts(settings, tables, events) if args.send_alerts else 0
    runs.finish(run_id, "success", result_count=count, message=f"eventized={count}; merged={merged}; reconciled={reconciled}; stale_ai_archived={stale_ai_archived}; archived={archived}; alerts={alerts}")
    audit.record(run_id=run_id, workflow="eventize", stage_code="EVENTIZE.complete", stage_name="Aggregate News into Event Cases", status="success", result_count=count, output_summary=f"Event Cases={count}; merged={merged}; reconciled={reconciled}; stale_ai_archived={stale_ai_archived}; archived={archived}; alerts={alerts}")
    print(f"eventize success: events={count}; merged={merged}; reconciled={reconciled}; stale_ai_archived={stale_ai_archived}; archived={archived}; alerts={alerts}")
except Exception as exc:
    runs.finish(run_id, "failed", message="eventize failed", error=str(exc))
    audit.record(run_id=run_id, workflow="eventize", stage_code="EVENTIZE.complete", stage_name="Aggregate News into Event Cases", status="failed", error=str(exc))
    raise
