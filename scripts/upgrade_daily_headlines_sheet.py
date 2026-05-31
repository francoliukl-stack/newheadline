"""Upgrade the canonical News DingTalk AI Table sheet in place."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import ensure_fields, list_records, normalize_url_cell, update_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
CANONICAL_SHEET_NAME = "News"
EXTRA_FIELDS = [
    {"name": "Operator", "type": "text"},
    {"name": "Publish Status", "type": "text"},
    {"name": "Sent At", "type": "date"},
    {"name": "Search Provider", "type": "text"},
    {"name": "Search Query", "type": "text"},
    {"name": "Search Batch", "type": "text"},
    {"name": "Discovery Type", "type": "text"},
    {"name": "First Seen At", "type": "date"},
]


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
store.save(settings)

run_id = run_logs.start(
    "upgrade_daily_headlines_sheet",
    provider="dingtalk_ai_table",
    metadata={"sheet_id": CANONICAL_SHEET_ID},
)

try:
    result = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, EXTRA_FIELDS)
    if not result.get("ok"):
        raise RuntimeError(str(result))

    provider = settings.search_provider.fallback_provider or settings.search_provider.provider
    first_seen = datetime.now(timezone.utc).date().isoformat()
    current = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = []
    for record in current:
        fields = record.get("fields") or {}
        patch: Dict[str, object] = {}
        source_url = normalize_url_cell(fields.get("Source URL"))
        if isinstance(source_url, dict) and source_url.get("link"):
            patch["Source URL"] = source_url
        if not fields.get("Operator"):
            patch["Operator"] = settings.dingtalk_ai_table.operator_user_id or settings.dingtalk_ai_table.operator_id
        if not fields.get("Publish Status"):
            patch["Publish Status"] = "未发送"
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
        write = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if write.status != "sent":
            raise RuntimeError(write.message)
        updated_ids.extend(write.record_ids)
        print(f"updated {len(updated_ids)}/{len(updates)} records")

    settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
    settings.dingtalk_ai_table.field_mapping = {
        "no": "ID",
        "category": "Section",
        "subject": "Title & URL",
        "tag": "Label",
        "link": "Source URL",
        "source": "Source Domain",
        "release_date": "Release Date",
        "status": "Status",
        "operator": "Operator",
        "publish_status": "Publish Status",
        "sent_at": "Sent At",
        "search_provider": "Search Provider",
        "search_query": "Search Query",
        "search_batch": "Search Batch",
        "discovery_type": "Discovery Type",
        "first_seen_at": "First Seen At",
    }
    store.save(settings)
    run_logs.finish(
        run_id,
        "success",
        result_count=len(updated_ids),
        message=f"upgraded canonical {CANONICAL_SHEET_NAME} sheet with {len(updated_ids)} records",
        metadata={"sheet_id": CANONICAL_SHEET_ID, "record_ids": updated_ids},
    )
    print(f"upgraded canonical {CANONICAL_SHEET_NAME} sheet: {CANONICAL_SHEET_ID}")
except Exception as exc:
    print(f"upgrade_daily_headlines_sheet failed: {exc}")
    run_logs.finish(run_id, "failed", message="canonical sheet upgrade failed", error=str(exc))
    raise
