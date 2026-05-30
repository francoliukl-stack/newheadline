"""Clone the configured Lark Base table into DingTalk AI Table.

The script reads the Lark export snapshots produced by lark-cli and writes a
same-column DingTalk AI Table sheet. It avoids guessing unsupported DingTalk
field semantics: date/datetime fields become date fields, numeric fields become
number fields, and all other values are stored as text with structured values
JSON-encoded to preserve data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import add_records, create_sheet  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
EXPORTS = DATA / "exports"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dingtalk_field_type(lark_type: str) -> str:
    if lark_type in {"number", "currency", "percent", "rating"}:
        return "number"
    if lark_type in {"date", "datetime", "created_time", "modified_time"}:
        return "date"
    return "text"


def stringify_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return json.dumps(value, ensure_ascii=False)


def build_fields(lark_fields: Iterable[Dict[str, Any]], ordered_names: List[str]) -> List[Dict[str, str]]:
    by_name = {field["name"]: field for field in lark_fields}
    fields = []
    for name in ordered_names:
        field = by_name.get(name, {"type": "text"})
        fields.append({"name": name, "type": dingtalk_field_type(str(field.get("type", "text")))})
    return fields


def build_records(record_pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output = []
    for page in record_pages:
        field_names = page["data"]["fields"]
        for row in page["data"]["data"]:
            output.append({name: stringify_cell(value) for name, value in zip(field_names, row)})
    return output


def batched(items: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


settings = store.load(masked=False)
run_id = run_logs.start(
    "clone_lark_to_dingtalk_ai_table",
    provider="lark_base",
    fallback_provider="dingtalk_ai_table",
    metadata={
        "lark_base_token": settings.lark.app_token,
        "lark_table_id": settings.lark.table_id,
        "dingtalk_base_id": settings.dingtalk_ai_table.base_id,
    },
)

try:
    fields_payload = load_json(EXPORTS / "lark_fields.json")
    page_paths = sorted(EXPORTS.glob("lark_records_page_*.json"))
    pages = [load_json(path) for path in page_paths]
    if not pages:
        raise FileNotFoundError("no lark_records_page_*.json snapshots found")

    ordered_names = pages[0]["data"]["fields"]
    dingtalk_fields = build_fields(fields_payload["data"]["fields"], ordered_names)
    records = build_records(pages)

    ai_table = settings.dingtalk_ai_table
    if not ai_table.sheet_id:
        created = create_sheet(settings.dingtalk, ai_table, "Daily Headlines", dingtalk_fields)
        if not created.get("ok"):
            raise RuntimeError(str(created))
        ai_table.sheet_id = created["payload"]["id"]
        settings.dingtalk_ai_table = ai_table
        store.save(settings)
        print(f"created DingTalk AI Table sheet: {ai_table.sheet_id}")

    created_ids: List[str] = []
    for chunk in batched(records, 100):
        result = add_records(settings.dingtalk, ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        created_ids.extend(result.record_ids)
        print(f"created {len(created_ids)}/{len(records)} records")

    run_logs.finish(
        run_id,
        "success",
        result_count=len(created_ids),
        message=f"cloned {len(created_ids)} records from Lark Base to DingTalk AI Table",
        metadata={"sheet_id": ai_table.sheet_id, "record_ids": created_ids},
    )
except Exception as exc:
    print(f"clone_lark_to_dingtalk_ai_table failed: {exc}")
    run_logs.finish(run_id, "failed", message="clone failed", error=str(exc))
    raise
