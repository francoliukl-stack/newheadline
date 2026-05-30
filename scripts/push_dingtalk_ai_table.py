"""Push the current news cache into DingTalk AI Table."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import add_news_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)

run_id = run_logs.start(
    "dingtalk_ai_table_push",
    provider=settings.search_provider.provider,
    fallback_provider=settings.search_provider.fallback_provider,
    metadata={"cache_path": settings.search_provider.openclaw_cache_path},
)

try:
    cache_path = Path(settings.search_provider.openclaw_cache_path).expanduser()
    if not cache_path.exists():
        raise FileNotFoundError(f"news cache not found: {cache_path}")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload.get("records", payload.get("items", []))
    result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, records)
    print(f"dingtalk_ai_table_push {result.status}: {result.message}")
    run_logs.finish(
        run_id,
        "success" if result.status == "sent" else result.status,
        result_count=len(result.record_ids),
        message=result.message,
        metadata={"record_ids": result.record_ids},
    )
except Exception as exc:
    print(f"dingtalk_ai_table_push failed: {exc}")
    run_logs.finish(run_id, "failed", message="DingTalk AI table push failed", error=str(exc))
    raise
