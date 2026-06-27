"""Prepare the evidence-backed research workspace for the current weekly topic."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.research_production import (  # noqa: E402
    ensure_research_production_sheets,
    load_research_context,
    upsert_claim_candidates,
    upsert_evidence_from_news,
    upsert_research_queue,
)
from app.research_topics import current_and_next_topics, ensure_research_topics_sheet, sync_research_topic_roadmap  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.weekly_report import select_weekly_records  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=7)
parser.add_argument("--recent-count", type=int, default=0)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
audit = AuditTrailWriter(settings, store)
run_id = run_logs.start("prepare_weekly_research", provider="dingtalk_ai_table")


def audit_event(stage_code: str, stage_name: str, status: str, **kwargs: object) -> None:
    related_sheet = str(kwargs.pop("related_sheet", settings.dingtalk_ai_table.sheet_id))
    audit.record(
        run_id=run_id,
        workflow="prepare_weekly_research",
        stage_code=stage_code,
        stage_name=stage_name,
        status=status,
        mode="dry-run" if args.dry_run else "live",
        related_sheet=related_sheet,
        **kwargs,
    )


try:
    now = datetime.now(ZoneInfo(settings.system.timezone))
    audit_event("RESEARCH.start", "Start weekly research preparation", "running", input_summary=f"Prepare current topic with days={args.days}, recent_count={args.recent_count}.")
    topic_table = ensure_research_topics_sheet(settings, store)
    settings = store.load(masked=False)
    sync_research_topic_roadmap(settings, topic_table, now.date())
    current_topic, _ = current_and_next_topics(list_records(settings.dingtalk, topic_table), now.date())
    if not current_topic:
        raise RuntimeError("no current research topic is available")
    source_records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    accepted, range_label = select_weekly_records(
        source_records,
        settings.dingtalk_ai_table.field_mapping,
        now,
        days=args.days,
        recent_count=args.recent_count,
        include_sent=False,
    )
    source_ids = ", ".join(str(record.get("id") or "") for record in accepted if record.get("id"))
    audit_event("RESEARCH.select", "Select accepted weekly signals", "success", output_summary=f"Selected {len(accepted)} accepted records for {range_label}.", result_count=len(accepted), source_record_ids=source_ids)
    if args.dry_run:
        topic_fields = current_topic.get("fields") or {}
        run_logs.finish(run_id, "success", result_count=len(accepted), message="research preparation dry-run", metadata={"topic": topic_fields.get("Topic"), "range": range_label})
        audit_event("RESEARCH.complete", "Complete weekly research preparation", "success", output_summary="Dry-run completed without creating research records.", result_count=len(accepted), source_record_ids=source_ids)
        print(f"prepare_weekly_research dry-run: topic={topic_fields.get('Topic')}; selected={len(accepted)}")
        raise SystemExit(0)

    tables = ensure_research_production_sheets(settings, store)
    queue_record = upsert_research_queue(settings, tables.queue, current_topic)
    research_id = str((queue_record.get("fields") or {}).get("Research ID") or "")
    audit_event("RESEARCH.queue", "Create or update Research Queue", "success", output_summary=f"Research Queue ready for {research_id}.", result_count=1, report_id=research_id, related_sheet=tables.queue.sheet_id)
    evidence = upsert_evidence_from_news(settings, tables.evidence, research_id, accepted)
    audit_event("RESEARCH.evidence", "Create or update Evidence Bank", "success", output_summary=f"Created or updated {len(evidence)} candidate evidence records. Reviewer verification is required before Deep Research.", result_count=len(evidence), source_record_ids=source_ids, report_id=research_id, related_sheet=tables.evidence.sheet_id)
    context = load_research_context(settings, tables, research_id)
    claims = upsert_claim_candidates(settings, tables.claims, research_id, context["evidence"])
    context = load_research_context(settings, tables, research_id)
    quality = context["quality"]
    audit_event("RESEARCH.claims", "Create claim candidates from verified evidence", "success", output_summary=f"Generated or updated {len(claims)} claim candidates; quality={quality['status']}.", result_count=len(claims), report_id=research_id, related_sheet=tables.claims.sheet_id, metadata=quality)
    run_logs.finish(run_id, "success", result_count=len(evidence), message=f"prepared {len(evidence)} evidence records", metadata={"research_id": research_id, "quality": quality})
    audit_event("RESEARCH.complete", "Complete weekly research preparation", "success", output_summary=f"Research workspace prepared; quality={quality['status']}.", result_count=len(evidence), source_record_ids=source_ids, report_id=research_id, metadata=quality)
    print(f"prepare_weekly_research success: research_id={research_id}; evidence={len(evidence)}; quality={quality['status']}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="research preparation failed", error=str(exc))
    audit_event("RESEARCH.complete", "Complete weekly research preparation", "failed", error=str(exc))
    raise
