"""Cut over or roll back v3.1 using non-destructive feature flags."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.scheduler import install_critical_scan  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.event_weekly import load_weekly_input  # noqa: E402
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument("--apply", action="store_true")
mode.add_argument("--rollback", action="store_true")
mode.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

store = SettingsStore(ROOT / "data" / "settings.sqlite3", SecretStore(ROOT / "data" / "secrets.json"))
settings = store.load(masked=False)
target = {
    "event_intelligence_enabled": not args.rollback,
    "critical_scan_enabled": not args.rollback,
    "weekly_input_mode": "news" if args.rollback else "event_cases",
    "timezone": "Asia/Kuala_Lumpur",
}
if args.dry_run:
    print(json.dumps({"mode": "dry-run", "target": target}, indent=2))
    raise SystemExit(0)
if args.apply:
    for command in ([str(ROOT / ".venv" / "bin" / "python"), "-m", "unittest", "discover", "-s", "tests"], [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "run_v3_1_evaluation.py")]):
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "release gate failed")
    required = [settings.dingtalk_ai_table.event_cases_sheet_id, settings.dingtalk_ai_table.event_sources_sheet_id, settings.dingtalk_ai_table.evidence_bank_sheet_id, settings.dingtalk_ai_table.claim_ledger_sheet_id]
    if not all(required):
        raise RuntimeError("v3.1 schema and lineage sheets must be configured before cutover")
    settings.event_intelligence.weekly_input_mode = "event_cases"
    ready = load_weekly_input(settings, datetime.now(ZoneInfo("Asia/Kuala_Lumpur")), days=14, recent_count=1, include_sent=True, max_items=1, sent_fields=("Weekly Intelligence Sent At", "Weekly Sent At"))
    if not ready.report_records:
        raise RuntimeError("cutover blocked: no human-accepted Event Case has verified Evidence and approved Claim")
settings.system.timezone = target["timezone"]
settings.event_intelligence.enabled = target["event_intelligence_enabled"]
settings.event_intelligence.critical_scan_enabled = target["critical_scan_enabled"]
settings.event_intelligence.weekly_input_mode = target["weekly_input_mode"]
store.save(settings)
message = install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_hours, settings.event_intelligence.critical_scan_enabled, dry_run=False)
print(json.dumps({"mode": "rollback" if args.rollback else "apply", "target": target, "schedule": message}, indent=2))
