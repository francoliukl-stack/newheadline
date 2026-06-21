"""Create or update the Config sheet with workflow configuration values."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_sheet import ensure_config_sheet, sync_config_items  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("sync_config_sheet", provider="dingtalk_ai_table")


try:
    config_table = ensure_config_sheet(settings, store)
    settings = store.load(masked=False)
    record_ids = sync_config_items(settings, config_table)
    run_logs.finish(run_id, "success", result_count=len(record_ids), message=f"synced {len(record_ids)} config records")
    print(f"Config sheet id: {config_table.sheet_id}")
    print(f"sync_config_sheet success: synced={len(record_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="sync config sheet failed", error=str(exc))
    raise
