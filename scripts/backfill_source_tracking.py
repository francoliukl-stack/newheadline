"""Backfill source tracking fields on DingTalk AI Table records."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


run_id = run_logs.start(
    "backfill_source_tracking",
    provider="dingtalk_ai_table",
    metadata={"sheet_id": settings.dingtalk_ai_table.sheet_id},
)

try:
    provider = settings.search_provider.fallback_provider or settings.search_provider.provider
    first_seen = datetime.now(timezone.utc).date().isoformat()
    current = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = []
    for record in current:
        fields = record.get("fields") or {}
        patch = {}
        if not fields.get("Search Provider"):
            patch["Search Provider"] = provider
        if not fields.get("Search Query"):
            patch["Search Query"] = "historical import"
        if not fields.get("Search Batch"):
            patch["Search Batch"] = "historical_import"
        if not fields.get("Discovery Type"):
            patch["Discovery Type"] = "historical_import"
        if not fields.get("First Seen At"):
            patch["First Seen At"] = first_seen
        if patch:
            updates.append({"id": record["id"], "fields": patch})

    updated_ids: List[str] = []
    for chunk in batched(updates, 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
        print(f"updated {len(updated_ids)}/{len(updates)} records")

    run_logs.finish(
        run_id,
        "success",
        result_count=len(updated_ids),
        message=f"backfilled source tracking on {len(updated_ids)} records",
        metadata={"record_ids": updated_ids},
    )
    print(f"backfilled source tracking on {len(updated_ids)} records")
except Exception as exc:
    print(f"backfill_source_tracking failed: {exc}")
    run_logs.finish(run_id, "failed", message="source tracking backfill failed", error=str(exc))
    raise
