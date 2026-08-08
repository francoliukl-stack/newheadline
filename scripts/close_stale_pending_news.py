"""Close News still pending past the retention window.

External event intelligence has a short shelf life, so unreviewed items older
than the window are closed in bulk as an operator policy. Every run writes a
rollback snapshot before touching anything, and the closure is recorded as a
bulk policy action rather than as an individual human review.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.stale_review import DEFAULT_MAX_AGE_DAYS, snapshot_rows, stale_close_patch, stale_pending_news  # noqa: E402
from app.storage import SettingsStore  # noqa: E402

DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"

parser = argparse.ArgumentParser(description="Close News left pending beyond the retention window.")
parser.add_argument("--days", type=int, default=DEFAULT_MAX_AGE_DAYS)
parser.add_argument("--batch-size", type=int, default=20)
parser.add_argument("--apply", action="store_true", help="write; otherwise report only")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
now = datetime.now(ZoneInfo(settings.system.timezone))
status_field = settings.dingtalk_ai_table.field_mapping.get("status", "Status")

records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
stale = stale_pending_news(records, now.date(), args.days, settings.dingtalk_ai_table.field_mapping)
snapshot = snapshot_rows(stale, settings.dingtalk_ai_table.field_mapping)
oldest = min((row["publish_date"] for row in snapshot if row["publish_date"]), default="-")
newest = max((row["publish_date"] for row in snapshot if row["publish_date"]), default="-")

print(f"待处理总数 {sum(1 for r in records if (r.get('fields') or {}))}; 超过 {args.days} 天仍待处理: {len(stale)} 条 (发布日 {oldest} .. {newest})")
if not stale:
    raise SystemExit(0)

if not args.apply:
    print("dry-run：未写入。样例：")
    for row in snapshot[:10]:
        print(f"  {row['publish_date']} · {row['title'][:70]}")
    raise SystemExit(0)

snapshot_path = DATA / f"stale-close-snapshot-{now:%Y%m%dT%H%M%S}.json"
snapshot_path.write_text(
    json.dumps({"closed_at": now.isoformat(timespec="seconds"), "max_age_days": args.days, "rows": snapshot}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"回滚快照已写入 {snapshot_path}")

run_logs = RunLogStore(DATA / "settings.sqlite3")
audit = AuditTrailWriter(settings, store, run_logs)
run_id = run_logs.start("close_stale_pending_news", provider="dingtalk_ai_table", metadata={"max_age_days": args.days, "candidates": len(stale)})
patch = stale_close_patch(args.days, now.isoformat(timespec="seconds"), status_field)
updates = [{"id": record["id"], "fields": dict(patch)} for record in stale]
written = 0
try:
    for start in range(0, len(updates), max(1, args.batch_size)):
        batch = updates[start : start + max(1, args.batch_size)]
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, batch)
        if result.status != "sent":
            raise RuntimeError(result.message)
        written += len(batch)
        print(f"  已写入 {written}/{len(updates)}")
    message = f"closed {written} News pending beyond {args.days} days ({oldest}..{newest})"
    run_logs.finish(run_id, "success", result_count=written, message=message, metadata={"snapshot": str(snapshot_path)})
    audit.record(
        run_id=run_id, workflow="close_stale_pending_news", stage_code="REVIEW.bulk_close",
        stage_name="Close stale pending News by policy", status="success",
        input_summary=f"Pending News older than {args.days} days.", output_summary=message,
        result_count=written, related_sheet=settings.dingtalk_ai_table.sheet_id,
        metadata={"max_age_days": args.days, "oldest": oldest, "newest": newest, "snapshot": str(snapshot_path)},
    )
    print(f"close_stale_pending_news success: {message}")
except Exception as exc:
    run_logs.finish(run_id, "failed", result_count=written, message=f"closed {written}/{len(updates)} before failing", error=str(exc))
    audit.record(
        run_id=run_id, workflow="close_stale_pending_news", stage_code="REVIEW.bulk_close",
        stage_name="Close stale pending News by policy", status="failed",
        output_summary=f"closed {written}/{len(updates)} before failing", error=str(exc),
        related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"snapshot": str(snapshot_path)},
    )
    raise
