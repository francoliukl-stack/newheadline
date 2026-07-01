"""Shared runner for AI-assisted News pre-review and deadline fallback."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

from app.ai_news_review import AI_REVIEW_VERSION, learning_snapshot, plan_review_updates
from app.audit_trail import AuditTrailWriter
from app.dingtalk_ai_table import list_records, update_records
from app.run_logs import RunLogStore
from app.secrets import SecretStore
from app.storage import SettingsStore


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _batched(rows: List[Dict[str, object]], size: int = 100):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def run(mode: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run AI News review mode={mode}.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
    news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    events = list_records(settings.dingtalk, event_table)
    now = datetime.now(ZoneInfo(settings.system.timezone))
    updates, stats = plan_review_updates(news, events, mode, now, settings.system.timezone)
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

    runs = RunLogStore(DATA / "settings.sqlite3")
    job_name = f"ai_review_{mode}"
    run_id = runs.start(job_name, provider="deterministic_event_rules", metadata={"review_version": AI_REVIEW_VERSION})
    audit = AuditTrailWriter(settings, store, runs)
    try:
        updated_ids: List[str] = []
        for batch in _batched(updates):
            result = update_records(settings.dingtalk, settings.dingtalk_ai_table, batch)
            if result.status != "sent" and batch:
                raise RuntimeError(result.message)
            updated_ids.extend(result.record_ids)
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
        runs.finish(run_id, "failed", message=f"AI review {mode} failed", error=str(exc), metadata=stats)
        audit.record(run_id=run_id, workflow="ai_news_review", stage_code=f"AI_REVIEW.{mode}", stage_name="AI News review", status="failed", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id, metadata=stats)
        raise
