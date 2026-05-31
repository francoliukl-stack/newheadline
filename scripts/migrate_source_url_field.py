"""Create a clickable Source URL field and migrate existing URL values."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import ensure_fields, list_records, normalize_url_cell, update_records  # noqa: E402
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
    "migrate_source_url_field",
    provider="dingtalk_ai_table",
    metadata={"sheet_id": settings.dingtalk_ai_table.sheet_id},
)

try:
    result = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, [{"name": "Source URL", "type": "url"}])
    if not result.get("ok"):
        raise RuntimeError(str(result))

    current = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = []
    for record in current:
        fields = record.get("fields") or {}
        value = fields.get("Source URL") or fields.get("URL")
        normalized = normalize_url_cell(value)
        if isinstance(normalized, dict) and normalized.get("link"):
            updates.append({"id": record["id"], "fields": {"Source URL": normalized}})

    updated_ids: List[str] = []
    for chunk in batched(updates, 100):
        write = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if write.status != "sent":
            raise RuntimeError(write.message)
        updated_ids.extend(write.record_ids)
        print(f"updated {len(updated_ids)}/{len(updates)} records")

    settings.dingtalk_ai_table.field_mapping["link"] = "Source URL"
    store.save(settings)
    run_logs.finish(
        run_id,
        "success",
        result_count=len(updated_ids),
        message=f"migrated {len(updated_ids)} clickable source URLs",
        metadata={"record_ids": updated_ids},
    )
    print(f"migrated {len(updated_ids)} clickable source URLs")
except Exception as exc:
    print(f"migrate_source_url_field failed: {exc}")
    run_logs.finish(run_id, "failed", message="source URL migration failed", error=str(exc))
    raise
