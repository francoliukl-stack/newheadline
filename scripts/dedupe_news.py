"""Mark duplicate news records on the canonical News sheet."""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dedupe import find_duplicate_clusters, record_title  # noqa: E402
from app.dingtalk_ai_table import ensure_fields, list_records, status_name, update_field_schema, update_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def ensure_duplicate_status() -> None:
    fields = settings.dingtalk_ai_table
    from app.dingtalk_ai_table import list_fields

    status_field = fields.field_mapping.get("status", "Review Status")
    status = next(
        field
        for field in list_fields(settings.dingtalk, fields)["payload"]["value"]
        if field["name"] in {status_field, "Review Status", "Status"}
    )
    choices = list((status.get("property") or {}).get("choices") or [])
    if any(choice.get("name") == "已重复" for choice in choices):
        return
    choices.append({"name": "已重复"})
    update_field_schema(settings.dingtalk, fields, status["id"], {"name": status["name"], "property": {"choices": choices}})


def has_duplicate_remark(fields: Dict[str, object]) -> bool:
    duplicate_of = str(fields.get("Duplicate Of") or "").strip()
    duplicate_reason = str(fields.get("Duplicate Reason") or "").strip().lower()
    rejection_reason = str(fields.get("Rejection Reason") or "").strip().lower()
    return bool(duplicate_of or duplicate_reason or rejection_reason.startswith("duplicate of") or "重复" in rejection_reason)


run_id = run_logs.start(
    "dedupe_news",
    provider="event_aware_similarity",
    metadata={"sheet_id": CANONICAL_SHEET_ID, "threshold": 0.55},
)

try:
    ensured = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, [
        {"name": "No", "type": "text"},
        {"name": "Duplicate Of", "type": "text"},
        {"name": "Duplicate Reason", "type": "text"},
        {"name": "Rejection Reason", "type": "text"},
    ])
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured))
    ensure_duplicate_status()
    status_field = settings.dingtalk_ai_table.field_mapping.get("status", "Review Status")

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
    clusters = find_duplicate_clusters(records, threshold=0.55)
    updates: Dict[str, Dict[str, object]] = {}
    for record in records:
        if not (record.get("fields") or {}).get("No"):
            updates[str(record["id"])] = {"id": record["id"], "fields": {"No": no_by_id[str(record["id"])]}}
    for cluster in clusters:
        primary_id = str(cluster.primary["id"])
        primary_no = no_by_id[primary_id]
        primary = updates.setdefault(primary_id, {"id": cluster.primary["id"], "fields": {}})
        primary_status_name = status_name(cluster.primary.get("fields") or {}, settings.dingtalk_ai_table.field_mapping)
        if primary_status_name == "已重复":
            primary["fields"][status_field] = "待处理"
        if (cluster.primary.get("fields") or {}).get("Duplicate Of"):
            primary["fields"]["Duplicate Of"] = ""
        if (cluster.primary.get("fields") or {}).get("Duplicate Reason"):
            primary["fields"]["Duplicate Reason"] = ""
        primary_rejection_reason = str((cluster.primary.get("fields") or {}).get("Rejection Reason") or "")
        if primary_rejection_reason.lower().startswith("duplicate of") or "重复" in primary_rejection_reason:
            primary["fields"]["Rejection Reason"] = ""
        for duplicate in cluster.duplicates:
            duplicate_id = str(duplicate["id"])
            patch = updates.setdefault(duplicate_id, {"id": duplicate["id"], "fields": {}})
            duplicate_fields = duplicate.get("fields") or {}
            duplicate_status_name = status_name(duplicate_fields, settings.dingtalk_ai_table.field_mapping)
            if duplicate_status_name not in {"", "待处理", "已重复"}:
                continue
            reason = cluster.reasons.get(duplicate_id) or "Same event"
            reason_text = f"Duplicate of {primary_no}: {reason}"
            if duplicate_status_name != "已重复":
                patch["fields"][status_field] = "已重复"
            if duplicate_fields.get("Duplicate Of") != primary_no:
                patch["fields"]["Duplicate Of"] = primary_no
            if duplicate_fields.get("Duplicate Reason") != reason_text:
                patch["fields"]["Duplicate Reason"] = reason_text
            if duplicate_fields.get("Rejection Reason") != reason_text:
                patch["fields"]["Rejection Reason"] = reason_text

    # A duplicate remark is a terminal automated decision, never a pending-review state.
    for record in records:
        fields = record.get("fields") or {}
        current_status = status_name(fields, settings.dingtalk_ai_table.field_mapping)
        existing_patch = (updates.get(str(record["id"])) or {}).get("fields") or {}
        effective_fields = {**fields, **existing_patch}
        if current_status not in {"", "待处理"} or not has_duplicate_remark(effective_fields):
            continue
        patch = updates.setdefault(str(record["id"]), {"id": record["id"], "fields": {}})
        patch["fields"][status_field] = "已重复"

    payload = [update for update in updates.values() if update["fields"]]
    updated_ids: List[str] = []
    for chunk in batched(payload, 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
        print(f"updated {len(updated_ids)}/{len(payload)} records")

    duplicate_count = sum(
        1
        for update in payload
        if (update.get("fields") or {}).get(status_field) == "已重复"
    )
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
                    "duplicates": [
                        {
                            "no": no_by_id[str(record["id"])],
                            "reason": cluster.reasons.get(str(record.get("id") or ""), ""),
                        }
                        for record in cluster.duplicates
                    ],
                }
                for cluster in clusters
            ],
        },
    )
    settings.dingtalk_ai_table.field_mapping.update({
        "no": "No",
        "duplicate_of": "Duplicate Of",
        "duplicate_reason": "Duplicate Reason",
        "rejection_reason": "Rejection Reason",
    })
    store.save(settings)
    print(f"marked {duplicate_count} duplicates across {len(clusters)} clusters")
except Exception as exc:
    print(f"dedupe_news failed: {exc}")
    run_logs.finish(run_id, "failed", message="dedupe failed", error=str(exc))
    raise
