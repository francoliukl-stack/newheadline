"""Create or update the Research Topics sheet with the rolling topic roadmap."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.research_topics import ensure_research_topics_sheet, sync_research_topic_roadmap  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("sync_research_topics", provider="dingtalk_ai_table")


try:
    topic_table = ensure_research_topics_sheet(settings, store)
    settings = store.load(masked=False)
    record_ids = sync_research_topic_roadmap(settings, topic_table, date.today())
    run_logs.finish(run_id, "success", result_count=len(record_ids), message=f"synced {len(record_ids)} research topic records")
    print(f"Research Topics sheet id: {topic_table.sheet_id}")
    print(f"sync_research_topics success: synced={len(record_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="sync research topics failed", error=str(exc))
    raise
