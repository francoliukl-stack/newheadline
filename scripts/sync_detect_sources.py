"""Create or update the Detect Sources sheet used by daily collection."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.detect_sources import ensure_detect_sources_sheet, sync_detect_sources  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("sync_detect_sources", provider="dingtalk_ai_table")


try:
    detect_table = ensure_detect_sources_sheet(settings, store)
    settings = store.load(masked=False)
    record_ids = sync_detect_sources(settings, detect_table)
    run_logs.finish(run_id, "success", result_count=len(record_ids), message=f"synced {len(record_ids)} detect source records")
    print(f"Detect Sources sheet id: {detect_table.sheet_id}")
    print(f"sync_detect_sources success: created={len(record_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="sync detect sources failed", error=str(exc))
    raise
