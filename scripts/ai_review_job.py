"""Shared runner for AI-assisted News pre-review and deadline fallback."""

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

from app.ai_news_review import AI_REVIEW_VERSION, accepted_event_status_updates, learning_snapshot, plan_review_updates
from app.audit_trail import AuditTrailWriter
from app.dingtalk_ai_table import list_records, update_records
from app.run_logs import RunLogStore
from app.secrets import SecretStore
from app.storage import SettingsStore


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _batched(rows: List[Dict[str, object]], size: int = 20):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def prepare_review_updates(
    rows: List[Dict[str, object]],
    *,
    max_updates: int = 0,
    batch_size: int = 20,
):
    selected = rows[:max_updates] if max_updates > 0 else list(rows)
    batches = list(_batched(selected, max(1, batch_size)))
    return selected, batches, {
        "updates_planned": len(rows),
        "updates_selected": len(selected),
        "updates_deferred": max(len(rows) - len(selected), 0),
        "write_batch_size": max(1, batch_size),
        "write_batch_count": len(batches),
    }


def run(mode: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run AI News review mode={mode}.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-updates", type=int, default=0, help="Maximum News rows to update; 0 means all planned rows.")
    parser.add_argument("--batch-size", type=int, default=20, help="Rows per DingTalk update call.")
    parser.add_argument("--batch-delay-seconds", type=float, default=1.0, help="Pause between DingTalk update calls.")
    args = parser.parse_args()
    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    runs = RunLogStore(DATA / "settings.sqlite3")
    job_name = f"ai_review_{mode}"
    audit = AuditTrailWriter(settings, store, runs)
    run_id = "" if args.dry_run else runs.start(job_name, provider="deterministic_event_rules", metadata={"review_version": AI_REVIEW_VERSION})
    stats: Dict[str, object] = {}
    try:
        event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
        news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        events = list_records(settings.dingtalk, event_table)
        now = datetime.now(ZoneInfo(settings.system.timezone))
        status_field = settings.dingtalk_ai_table.field_mapping.get("status", "Review Status")
        updates, stats = plan_review_updates(news, events, mode, now, settings.system.timezone, status_field=status_field)
        updates, update_batches, batch_stats = prepare_review_updates(
            updates,
            max_updates=max(0, args.max_updates),
            batch_size=max(1, args.batch_size),
        )
        stats.update(batch_stats)
        event_status_updates = accepted_event_status_updates(news, events, updates) if mode == "deadline" else []
        stats["events_accepted"] = len(event_status_updates)
        update_index = {str(row.get("id") or ""): row.get("fields") or {} for row in updates}
        effective_news = [
            {**row, "fields": {**(row.get("fields") or {}), **update_index.get(str(row.get("id") or ""), {})}}
            for row in news
        ]
        stats.update(learning_snapshot(effective_news, events, now.date().isoformat()))
        distribution = Counter(str((row.get("fields") or {}).get("AI Status") or "") for row in updates)
        distribution.pop("", None)
        stats.update({f"ai_status_{status}": count for status, count in distribution.items()})
        if args.dry_run:
            print({"mode": mode, "updates": len(updates), **stats, "sample": updates[:5]})
            return 0

        updated_ids: List[str] = []
        for index, batch in enumerate(update_batches):
            result = update_records(settings.dingtalk, settings.dingtalk_ai_table, batch)
            if result.status != "sent" and batch:
                raise RuntimeError(result.message)
            updated_ids.extend(result.record_ids)
            if index < len(update_batches) - 1 and args.batch_delay_seconds > 0:
                time.sleep(args.batch_delay_seconds)
        if event_status_updates:
            result = update_records(settings.dingtalk, event_table, event_status_updates)
            if result.status != "sent":
                raise RuntimeError(result.message)
        message = f"mode={mode}; updated={len(updated_ids)}; stats={stats}"
        runs.finish(run_id, "success", result_count=len(updated_ids), message=message, metadata=stats)
        audit.record(
            run_id=run_id,
            workflow="ai_news_review",
            stage_code=f"AI_REVIEW.{mode}",
            stage_name="AI News pre-review" if mode == "suggest" else "AI News deadline fallback",
            status="success",
            result_count=len(updated_ids),
            output_summary=message,
            related_sheet=settings.dingtalk_ai_table.sheet_id,
            metadata=stats,
        )
        print(message)
        return 0
    except Exception as exc:
        if run_id:
            runs.finish(run_id, "failed", message=f"AI review {mode} failed", error=str(exc), metadata=stats)
            audit.record(run_id=run_id, workflow="ai_news_review", stage_code=f"AI_REVIEW.{mode}", stage_name="AI News review", status="failed", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id, metadata=stats)
        raise
