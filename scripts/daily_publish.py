"""Publish the newest accepted unsent News record to DingTalk and mark it sent."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import ensure_fields, list_records, update_records  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.notifications import send_dingtalk_webhook_markdown  # noqa: E402
from app.publish_format import build_headlines_content, is_accepted_record, record_date, selected_date_range  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--limit", type=int, default=1)
parser.add_argument("--webhook-url", default="")
parser.add_argument("--signing-secret", default="")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
audit = AuditTrailWriter(settings, store)
run_id = run_logs.start("daily_publish", provider="dingtalk_ai_table")


def audit_event(stage_code: str, stage_name: str, status: str, **kwargs: object) -> None:
    audit.record(
        run_id=run_id,
        workflow="daily_publish",
        stage_code=stage_code,
        stage_name=stage_name,
        status=status,
        mode="dry-run" if args.dry_run else "live",
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        **kwargs,
    )


audit_event("PUBLISH.start", "Start daily headline publish", "running", input_summary=f"Select up to {max(args.limit, 1)} accepted News records not yet sent daily.")

try:
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    accepted = [
        record for record in records
        if is_accepted_record(record, settings.dingtalk_ai_table.field_mapping)
        and not (record.get("fields") or {}).get("Daily Sent At")
    ]
    selected = sorted(accepted, key=lambda record: (record_date(record), str(record.get("id") or "")), reverse=True)[: max(args.limit, 1)]
    selected_ids = ", ".join(str(record.get("id") or "") for record in selected if record.get("id"))
    audit_event(
        "PUBLISH.select", "Select accepted daily headlines", "success",
        output_summary=f"Selected {len(selected)} of {len(accepted)} accepted unsent News records.", result_count=len(selected), source_record_ids=selected_ids,
    )
    if not selected:
        run_logs.finish(run_id, "success", result_count=0, message="no accepted unsent records")
        audit_event("PUBLISH.complete", "Complete daily headline publish", "success", output_summary="No accepted unsent records.", result_count=0)
        print("daily_publish success: nothing to publish")
        raise SystemExit(0)

    now = datetime.now(ZoneInfo(settings.system.timezone))
    content = build_headlines_content(
        selected,
        "Daily",
        selected_date_range(selected, now),
        settings.dingtalk_ai_table.approval_view_url,
    )
    audit_event("PUBLISH.render", "Render daily headline content", "success", output_summary="Daily headline content rendered.", result_count=len(selected), source_record_ids=selected_ids, metadata={"period": selected_date_range(selected, now)})
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(selected), message=f"dry-run selected {len(selected)} accepted records")
        audit_event("PUBLISH.complete", "Complete daily headline publish", "success", output_summary="Dry-run completed without DingTalk send or News writeback.", result_count=len(selected), source_record_ids=selected_ids)
        print(f"daily_publish dry-run: selected={len(selected)}")
        print(content)
        raise SystemExit(0)

    target_url = args.webhook_url or settings.dingtalk.daily_webhook_url or settings.dingtalk.weekly_webhook_url
    target_secret = args.signing_secret or settings.dingtalk.daily_signing_secret or settings.dingtalk.weekly_signing_secret
    notification = send_dingtalk_webhook_markdown(
        target_url,
        target_secret,
        "Daily Headlines",
        content,
    )
    audit_event("PUBLISH.notify", "Send daily headline", notification.status, output_summary=notification.message, result_count=len(selected), source_record_ids=selected_ids, metadata={"notification": notification.__dict__})
    if notification.status != "sent":
        raise RuntimeError(notification.message)

    ensured = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, [{"name": "Daily Sent At", "type": "text"}])
    if not ensured.get("ok"):
        raise RuntimeError(ensured.get("message", "failed to ensure Daily Sent At field"))
    sent_at = datetime.now(ZoneInfo(settings.system.timezone)).date().isoformat()
    updates = [{"id": record["id"], "fields": {"Daily Sent At": sent_at}} for record in selected]
    updated_ids = []
    for chunk in batched(updates, 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
    audit_event("PUBLISH.writeback", "Write Daily Sent At", "success", output_summary=f"Updated Daily Sent At for {len(updated_ids)} News records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids))
    run_logs.finish(run_id, "success", result_count=len(updated_ids), message=f"published {len(updated_ids)} accepted records")
    audit_event("PUBLISH.complete", "Complete daily headline publish", "success", output_summary=f"Published {len(updated_ids)} accepted records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids))
    print(f"daily_publish success: published={len(updated_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily publish failed", error=str(exc))
    audit_event("PUBLISH.complete", "Complete daily headline publish", "failed", error=str(exc))
    raise
