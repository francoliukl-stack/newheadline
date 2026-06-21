"""Apply editable Config sheet values to local settings and reinstall launchd."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_sheet import apply_config_items, ensure_config_sheet, sync_config_items  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.scheduler import install_launchd  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("apply_config_sheet", provider="dingtalk_ai_table")


try:
    config_table = ensure_config_sheet(settings, store)
    records = list_records(settings.dingtalk, config_table)
    applied = apply_config_items(settings, records)
    store.save(settings)
    settings = store.load(masked=False)
    install_launchd(settings.schedule, ROOT, str(ROOT / ".venv" / "bin" / "python"), dry_run=False)
    config_table = ensure_config_sheet(settings, store)
    sync_config_items(settings, config_table)
    run_logs.finish(run_id, "success", result_count=len(applied), message=f"applied {len(applied)} config records")
    print(f"apply_config_sheet success: applied={len(applied)}")
    for key in applied:
        print(key)
except Exception as exc:
    run_logs.finish(run_id, "failed", message="apply config sheet failed", error=str(exc))
    raise
