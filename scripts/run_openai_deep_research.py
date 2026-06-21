"""Run OpenAI Deep Research for the accepted weekly News selection."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.dingtalk_docs import create_report_document  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.openai_deep_research import run_deep_research, save_result  # noqa: E402
from app.research_production import ensure_research_production_sheets, load_research_context, save_research_result, upsert_evidence_from_news, upsert_research_queue  # noqa: E402
from app.market_research_plan import build_market_led_research_plan  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.weekly_report import select_weekly_records  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=7)
parser.add_argument("--recent-count", type=int, default=0)
parser.add_argument("--include-sent", action="store_true")
parser.add_argument("--approve", action="store_true")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
store.save(settings)
run_id = run_logs.start("openai_deep_research", provider="openai_responses")
audit = AuditTrailWriter(settings, store)
research_tables = None
queue = None

try:
    now = datetime.now(ZoneInfo(settings.system.timezone))
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    accepted, period = select_weekly_records(
        records,
        settings.dingtalk_ai_table.field_mapping,
        now,
        days=args.days,
        recent_count=args.recent_count,
        include_sent=args.include_sent,
        max_items=settings.rules.max_items_per_category,
    )
    if not accepted:
        raise RuntimeError("No accepted News records are available for Deep Research")
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(accepted), message="OpenAI Deep Research dry-run selected records")
        print(f"openai_deep_research dry-run: selected={len(accepted)}; period={period}")
        raise SystemExit(0)
    market_plan = build_market_led_research_plan(accepted, period)
    topic = market_plan["topic_record"]
    topic_fields = topic["fields"]
    research_tables = ensure_research_production_sheets(settings, store)
    queue = upsert_research_queue(settings, research_tables.queue, topic)
    research_id = str((queue.get("fields") or {}).get("Research ID") or "")
    if not research_id:
        raise RuntimeError("Research ID is missing")
    queue_fields = queue.get("fields") or {}
    approval_status = str(queue_fields.get("Approval Status") or "").strip()
    if args.approve:
        approved_at = now.isoformat(timespec="seconds")
        approval_result = update_records(settings.dingtalk, research_tables.queue, [{
            "id": queue["id"],
            "fields": {
                "Approval Status": "Approved",
                "Approved At": approved_at,
                "Deep Research Status": "Approved - pending execution",
            },
        }])
        if approval_result.status != "sent":
            raise RuntimeError(approval_result.message)
        approval_status = "Approved"
    if approval_status != "Approved":
        run_logs.finish(run_id, "success", result_count=0, message="Deep Research skipped: approval is required", metadata={"research_id": research_id, "approval_status": approval_status or "Pending Approval"})
        print(f"openai_deep_research skipped: research_id={research_id}; approval_status={approval_status or 'Pending Approval'}")
        raise SystemExit(0)
    upsert_evidence_from_news(settings, research_tables.evidence, research_id, accepted)
    context = load_research_context(settings, research_tables, research_id)
    evidence_ids = [str((item.get("fields") or {}).get("Evidence ID") or "") for item in context["evidence"]]
    source_record_ids = [str(item.get("id") or "") for item in accepted]
    audit.record(
        run_id=run_id,
        workflow="openai_deep_research",
        stage_code="RESEARCH.generate",
        stage_name="Generate external research with OpenAI",
        status="running",
        input_summary=f"Research ID={research_id}; topic={topic_fields.get('Topic') or ''}",
        source_record_ids=", ".join(source_record_ids),
        report_id=research_id,
        related_sheet=research_tables.queue.sheet_id,
    )
    result = run_deep_research(
        settings.openai_research,
        str(topic_fields.get("Topic") or "GBSS Weekly Research"),
        str(topic_fields.get("Research Question") or "What changed, why does it matter, and what should GBSS do next?"),
        period,
        accepted,
    )
    path = save_result(DATA, research_id, result)
    research_doc = create_report_document(
        settings,
        store,
        f"{period} GBSS External Research - {topic_fields.get('Topic') or 'Weekly Research'}",
        "\n".join([
            "# GBSS External Research / 外部调研报告",
            "",
            f"Research ID: {research_id}",
            f"Provider: OpenAI / {result['model']}",
            f"Response ID: {result['response_id']}",
            "",
            result["content"],
        ]),
    )
    result_record_id = save_research_result(
        settings,
        research_tables.results,
        research_id=research_id,
        provider="OpenAI",
        model=result["model"],
        response_id=result["response_id"],
        status="Completed",
        topic=str(topic_fields.get("Topic") or "GBSS Weekly Research"),
        question=str(topic_fields.get("Research Question") or ""),
        source_record_ids=source_record_ids,
        evidence_ids=evidence_ids,
        content=result["content"],
        phrases=result["phrases"],
        document_url=research_doc.url,
        document_node_id=research_doc.node_id,
        document_key=research_doc.doc_key,
        local_artifact_path=str(path),
    )
    result_write = update_records(settings.dingtalk, research_tables.queue, [{
        "id": queue["id"],
        "fields": {
            "Deep Research Status": "Completed",
            "OpenAI Response ID": result["response_id"],
            "Deep Insight Phrases": " | ".join(result["phrases"]),
            "Research Result Record ID": result_record_id,
            "Research Document URL": research_doc.url,
        },
    }])
    if result_write.status != "sent":
        raise RuntimeError(result_write.message)
    audit.record(
        run_id=run_id,
        workflow="openai_deep_research",
        stage_code="RESEARCH.persist",
        stage_name="Persist external research result",
        status="success",
        output_summary=f"Research Results record={result_record_id}; document created.",
        result_count=1,
        source_record_ids=", ".join(source_record_ids),
        report_id=research_id,
        artifact_url=research_doc.url,
        artifact_path=str(path),
        related_sheet=research_tables.results.sheet_id,
        metadata={"response_id": result["response_id"], "model": result["model"]},
    )
    run_logs.finish(run_id, "success", result_count=len(accepted), message=f"OpenAI Deep Research completed: {research_id}", metadata={"research_id": research_id, "response_id": result["response_id"], "result_record_id": result_record_id, "document_url": research_doc.url, "phrases": result["phrases"]})
    print(f"openai_deep_research success: research_id={research_id}; result_record={result_record_id}; path={path}")
except Exception as exc:
    if research_tables and queue:
        update_records(settings.dingtalk, research_tables.queue, [{
            "id": queue["id"],
            "fields": {"Deep Research Status": "Failed - see RunLog"},
        }])
    run_logs.finish(run_id, "failed", message="OpenAI Deep Research failed", error=str(exc))
    raise
