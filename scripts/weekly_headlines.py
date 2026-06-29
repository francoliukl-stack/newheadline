"""Publish the daily management news report and record its delivery state."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import ensure_fields  # noqa: E402
from app.notifications import send_dingtalk_webhook_markdown  # noqa: E402
from app.publish_format import build_headlines_content  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.weekly_report import select_weekly_records  # noqa: E402
from app.event_weekly import load_weekly_input, write_sent_markers  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--days", type=int, default=None)
parser.add_argument("--recent-count", type=int, default=0)
parser.add_argument("--include-sent", action="store_true")
parser.add_argument("--webhook-url", default="")
parser.add_argument("--signing-secret", default="")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
audit = AuditTrailWriter(settings, store, run_logs)
run_id = run_logs.start("daily_report", provider="dingtalk_ai_table")


def audit_event(stage_code: str, stage_name: str, status: str, **kwargs: object) -> None:
    audit.record(
        run_id=run_id,
        workflow="daily_report",
        stage_code=stage_code,
        stage_name=stage_name,
        status=status,
        mode="dry-run" if args.dry_run else "live",
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        **kwargs,
    )


try:
    now = datetime.now(ZoneInfo(settings.system.timezone))
    days = args.days or settings.rules.daily_report_lookback_days
    audit_event(
        "HEADLINES.start",
        "Start Daily Report",
        "running",
        input_summary=f"Select accepted News records for the past {days} days.",
    )
    weekly_input = load_weekly_input(settings, now, days=days, recent_count=args.recent_count, include_sent=args.include_sent, max_items=settings.rules.max_items_per_category, sent_fields=("Daily Report Sent At", "Weekly Headlines Sent At"))
    selected, range_label = weekly_input.report_records, weekly_input.range_label
    selected_ids = ", ".join(str(record.get("id") or "") for record in selected if record.get("id"))
    audit_event(
        "HEADLINES.select",
        "Select Daily Report source records",
        "success",
        output_summary=f"Selected {len(selected)} accepted News records for {range_label}.",
        result_count=len(selected),
        source_record_ids=selected_ids,
        metadata={"range_label": range_label, "recent_count": args.recent_count, "input_mode": weekly_input.mode},
    )
    if not selected:
        run_logs.finish(run_id, "success", result_count=0, message="no accepted unsent daily report records")
        audit_event("HEADLINES.complete", "Complete Daily Report", "success", output_summary="No accepted unsent News records.", result_count=0)
        print("daily_report success: nothing to publish")
        raise SystemExit(0)

    content = build_headlines_content(
        selected,
        "Daily",
        range_label,
        settings.dingtalk_ai_table.approval_view_url,
        settings.rules.max_items_per_category,
    )
    audit_event("HEADLINES.render", "Render Daily Report", "success", output_summary="Daily Report rendered.", result_count=len(selected), source_record_ids=selected_ids, metadata={"period": range_label})
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(selected), message=f"dry-run selected {len(selected)} accepted records")
        audit_event("HEADLINES.complete", "Complete Daily Report", "success", output_summary="Dry-run completed without DingTalk send or News writeback.", result_count=len(selected), source_record_ids=selected_ids)
        print(f"daily_report dry-run: selected={len(selected)}")
        print(content)
        raise SystemExit(0)

    target_url = args.webhook_url or settings.dingtalk.weekly_webhook_url or settings.dingtalk.daily_webhook_url
    target_secret = args.signing_secret or settings.dingtalk.weekly_signing_secret or settings.dingtalk.daily_signing_secret
    notification = send_dingtalk_webhook_markdown(
        target_url,
        target_secret,
        "Daily Report",
        content,
        "",  # AI_Intelligence receives the report without mentioning anyone.
    )
    audit_event("HEADLINES.notify", "Send Daily Report", notification.status, output_summary=notification.message, result_count=len(selected), source_record_ids=selected_ids, metadata={"notification": notification.__dict__})
    if notification.status != "sent":
        raise RuntimeError(notification.message)

    field_name = "Daily Report Sent At"
    sent_at = now.date().isoformat()
    updated_ids = write_sent_markers(settings, weekly_input, field_name, sent_at)
    audit_event("HEADLINES.writeback", f"Write {field_name}", "success", output_summary=f"Updated {field_name} for {len(updated_ids)} News records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids))
    run_logs.finish(run_id, "success", result_count=len(updated_ids), message=f"published {len(updated_ids)} accepted records")
    audit_event("HEADLINES.complete", "Complete Daily Report", "success", output_summary=f"Published {len(updated_ids)} accepted records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids))
    print(f"daily_report success: published={len(updated_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily report failed", error=str(exc))
    audit_event("HEADLINES.complete", "Complete Daily Report", "failed", error=str(exc))
    raise
