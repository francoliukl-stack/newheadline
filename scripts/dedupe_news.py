"""Mark duplicate news records on the canonical News sheet."""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dedupe import find_duplicate_clusters, record_title  # noqa: E402
from app.dingtalk_ai_table import ensure_fields, list_records, update_field_schema, update_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
store.save(settings)


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def ensure_duplicate_status() -> None:
    fields = settings.dingtalk_ai_table
    from app.dingtalk_ai_table import list_fields

    status = next(field for field in list_fields(settings.dingtalk, fields)["payload"]["value"] if field["name"] == "Status")
    choices = list((status.get("property") or {}).get("choices") or [])
    if any(choice.get("name") == "已重复" for choice in choices):
        return
    choices.append({"name": "已重复"})
    update_field_schema(settings.dingtalk, fields, status["id"], {"name": "Status", "property": {"choices": choices}})


run_id = run_logs.start(
    "dedupe_news",
    provider="title_similarity",
    metadata={"sheet_id": CANONICAL_SHEET_ID, "threshold": 0.86},
)

try:
    ensured = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, [
        {"name": "No", "type": "text"},
        {"name": "Duplicate Of", "type": "text"},
    ])
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured))
    ensure_duplicate_status()

    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    ordered = sorted(records, key=lambda record: str(record.get("id") or ""))
    existing_numbers = []
    for record in ordered:
        value = str((record.get("fields") or {}).get("No") or "")
        match = re.fullmatch(r"NEWS_(\d+)", value)
        if match:
            existing_numbers.append(int(match.group(1)))
    next_number = max(existing_numbers, default=0) + 1
    no_by_id = {}
    for record in ordered:
        record_id = str(record["id"])
        value = (record.get("fields") or {}).get("No")
        if not value:
            value = f"NEWS_{next_number:06d}"
            next_number += 1
        no_by_id[record_id] = value
    clusters = find_duplicate_clusters(records)
    updates: Dict[str, Dict[str, object]] = {}
    for record in records:
        if not (record.get("fields") or {}).get("No"):
            updates[str(record["id"])] = {"id": record["id"], "fields": {"No": no_by_id[str(record["id"])]}}
    for cluster in clusters:
        primary_id = str(cluster.primary["id"])
        primary_no = no_by_id[primary_id]
        primary = updates.setdefault(primary_id, {"id": cluster.primary["id"], "fields": {}})
        primary_status = (cluster.primary.get("fields") or {}).get("Status") or {}
        primary_status_name = primary_status.get("name") if isinstance(primary_status, dict) else primary_status
        if primary_status_name in {"", "已重复"}:
            primary["fields"]["Status"] = "待处理"
        primary["fields"]["Duplicate Of"] = ""
        for duplicate in cluster.duplicates:
            duplicate_id = str(duplicate["id"])
            patch = updates.setdefault(duplicate_id, {"id": duplicate["id"], "fields": {}})
            patch["fields"].update({"Status": "已重复", "Duplicate Of": primary_no})

    payload = list(updates.values())
    updated_ids: List[str] = []
    for chunk in batched(payload, 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
        print(f"updated {len(updated_ids)}/{len(payload)} records")

    duplicate_count = sum(len(cluster.duplicates) for cluster in clusters)
    run_logs.finish(
        run_id,
        "success",
        result_count=duplicate_count,
        message=f"marked {duplicate_count} duplicates across {len(clusters)} clusters",
        metadata={
            "cluster_count": len(clusters),
            "duplicate_count": duplicate_count,
            "clusters": [
                {
                    "primary_no": no_by_id[str(cluster.primary["id"])],
                    "primary_title": record_title(cluster.primary),
                    "duplicate_nos": [no_by_id[str(record["id"])] for record in cluster.duplicates],
                }
                for cluster in clusters
            ],
        },
    )
    settings.dingtalk_ai_table.field_mapping.update({"no": "No", "duplicate_of": "Duplicate Of"})
    store.save(settings)
    print(f"marked {duplicate_count} duplicates across {len(clusters)} clusters")
except Exception as exc:
    print(f"dedupe_news failed: {exc}")
    run_logs.finish(run_id, "failed", message="dedupe failed", error=str(exc))
    raise
