"""Publish accepted unsent News records to DingTalk and mark them sent."""

from __future__ import annotations

import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.notifications import send_dingtalk_webhook_markdown  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
store.save(settings)
run_id = run_logs.start("weekly_publish", provider="dingtalk_ai_table")
parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()


def status_name(fields: Dict[str, object]) -> str:
    value = fields.get("Status") or {}
    return str(value.get("name") or "") if isinstance(value, dict) else str(value)


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


try:
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    accepted = [
        record for record in records
        if status_name(record.get("fields") or {}) == "已采纳"
        and (record.get("fields") or {}).get("Publish Status") != "已发送"
    ]
    if not accepted:
        run_logs.finish(run_id, "success", result_count=0, message="no accepted unsent records")
        print("weekly_publish success: nothing to publish")
        raise SystemExit(0)
    lines = ["# Weekly Headlines", ""]
    for section in ("Finance", "Contact Center"):
        section_records = [
            record for record in accepted
            if (record.get("fields") or {}).get("Section") == section
        ][: settings.rules.max_items_per_category]
        if not section_records:
            continue
        lines.extend([f"## {section}", ""])
        for record in section_records:
            fields = record.get("fields") or {}
            source_url = fields.get("Source URL") or {}
            url = source_url.get("link") if isinstance(source_url, dict) else source_url
            headline = fields.get("Title & URL") or "-"
            label = fields.get("Label") or fields.get("Tag") or "-"
            lines.append(f"- {label}: [{headline}]({url})")
        lines.append("")
    content = "\n".join(lines)
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(accepted), message=f"dry-run selected {len(accepted)} accepted records")
        print(f"weekly_publish dry-run: selected={len(accepted)}")
        raise SystemExit(0)
    target_url = settings.dingtalk.weekly_webhook_url or settings.dingtalk.daily_webhook_url
    target_secret = settings.dingtalk.weekly_signing_secret or settings.dingtalk.daily_signing_secret
    notification = send_dingtalk_webhook_markdown(target_url, target_secret, "Weekly Headlines", content)
    if notification.status != "sent":
        raise RuntimeError(notification.message)
    sent_at = datetime.now(ZoneInfo(settings.system.timezone)).date().isoformat()
    updates = [{"id": record["id"], "fields": {"Publish Status": "已发送", "Sent At": sent_at}} for record in accepted]
    updated_ids = []
    for chunk in batched(updates, 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
    run_logs.finish(run_id, "success", result_count=len(updated_ids), message=f"published {len(updated_ids)} accepted records")
    print(f"weekly_publish success: published={len(updated_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="weekly publish failed", error=str(exc))
    raise
