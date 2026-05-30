"""Push the current news cache into DingTalk AI Table."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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

def enrich_record(record: dict, provider: str, query: str, batch: str, discovery_type: str) -> dict:
    enriched = dict(record)
    first_seen = datetime.now(timezone.utc).date().isoformat()
    enriched.setdefault("Search Provider", provider)
    enriched.setdefault("search_provider", provider)
    enriched.setdefault("Search Query", query)
    enriched.setdefault("search_query", query)
    enriched.setdefault("Search Batch", batch)
    enriched.setdefault("search_batch", batch)
    enriched.setdefault("Discovery Type", discovery_type)
    enriched.setdefault("discovery_type", discovery_type)
    enriched.setdefault("First Seen At", first_seen)
    enriched.setdefault("first_seen_at", first_seen)
    return enriched


try:
    cache_path = Path(settings.search_provider.openclaw_cache_path).expanduser()
    if not cache_path.exists():
        raise FileNotFoundError(f"news cache not found: {cache_path}")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload.get("records", payload.get("items", []))
    used_provider = (
        settings.search_provider.fallback_provider
        if settings.search_provider.provider in {"chatgpt_web", "gemini_web"}
        else settings.search_provider.provider
    )
    default_query = payload.get("query", "configured daily fetch") if isinstance(payload, dict) else "configured daily fetch"
    discovery_type = "fallback" if used_provider == settings.search_provider.fallback_provider else "primary"
    records = [enrich_record(record, used_provider, default_query, run_id, discovery_type) for record in records]
    result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, records)
    print(f"dingtalk_ai_table_push {result.status}: {result.message}")
    run_logs.finish(
        run_id,
        "success" if result.status == "sent" else result.status,
        result_count=len(result.record_ids),
        message=result.message,
        metadata={
            "record_ids": result.record_ids,
            "used_provider": used_provider,
            "search_query": default_query,
            "discovery_type": discovery_type,
        },
    )
except Exception as exc:
    print(f"dingtalk_ai_table_push failed: {exc}")
    run_logs.finish(run_id, "failed", message="DingTalk AI table push failed", error=str(exc))
    raise
