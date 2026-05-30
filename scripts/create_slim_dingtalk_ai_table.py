"""Create a slim DingTalk AI Table sheet for review and publishing."""

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
SHEET_NAME = "Daily Headlines Review"
FIELDS = [
    {"name": "No", "type": "text"},
    {"name": "Section", "type": "text"},
    {"name": "Label", "type": "text"},
    {"name": "Headline", "type": "text"},
    {"name": "URL", "type": "text"},
    {"name": "Source", "type": "text"},
    {"name": "Published At", "type": "date"},
    {"name": "Search Provider", "type": "text"},
    {"name": "Search Query", "type": "text"},
    {"name": "Search Batch", "type": "text"},
    {"name": "Discovery Type", "type": "text"},
    {"name": "First Seen At", "type": "date"},
    {"name": "Review Status", "type": "text"},
    {"name": "Operator", "type": "text"},
    {"name": "Publish Status", "type": "text"},
    {"name": "Sent At", "type": "date"},
]


def load_pages() -> List[Dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(EXPORTS.glob("lark_records_page_*.json"))]


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list) and len(value) == 1:
        return scalar(value[0])
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def simplify_record(row: List[Any], fields: List[str], operator: str) -> Dict[str, Any]:
    item = dict(zip(fields, row))
    return {
        "No": scalar(item.get("ID")),
        "Section": scalar(item.get("Section") or item.get("Category")),
        "Label": scalar(item.get("Label") or item.get("Tag")),
        "Headline": scalar(item.get("Title & URL")),
        "URL": scalar(item.get("Source URL")),
        "Source": scalar(item.get("Source Domain")),
        "Published At": scalar(item.get("Publish Date") or item.get("Release Date")),
        "Search Provider": "",
        "Search Query": "",
        "Search Batch": "",
        "Discovery Type": "historical_import",
        "First Seen At": "",
        "Review Status": scalar(item.get("Status") or "待处理"),
        "Operator": operator,
        "Publish Status": "未发送",
        "Sent At": "",
    }


def build_records(pages: Iterable[Dict[str, Any]], operator: str) -> List[Dict[str, Any]]:
    records = []
    for page in pages:
        fields = page["data"]["fields"]
        for row in page["data"]["data"]:
            records.append(simplify_record(row, fields, operator))
    return records


def batched(items: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start(
    "create_slim_dingtalk_ai_table",
    provider="lark_base",
    fallback_provider="dingtalk_ai_table",
    metadata={"sheet_name": SHEET_NAME, "source_sheet_id": settings.dingtalk_ai_table.sheet_id},
)

try:
    pages = load_pages()
    if not pages:
        raise FileNotFoundError("no lark_records_page_*.json snapshots found")
    operator = settings.dingtalk_ai_table.operator_user_id or settings.dingtalk_ai_table.operator_id
    records = build_records(pages, operator)

    ai_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": ""})
    created = create_sheet(settings.dingtalk, ai_table, SHEET_NAME, FIELDS)
    if not created.get("ok"):
        raise RuntimeError(str(created))
    sheet_id = created["payload"]["id"]
    ai_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})

    created_ids: List[str] = []
    for chunk in batched(records, 100):
        result = add_records(settings.dingtalk, ai_table, chunk)
        if result.status != "sent":
            raise RuntimeError(result.message)
        created_ids.extend(result.record_ids)
        print(f"created {len(created_ids)}/{len(records)} slim records")

    settings.dingtalk_ai_table.sheet_id = sheet_id
    settings.dingtalk_ai_table.field_mapping = {
        "no": "No",
        "category": "Section",
        "subject": "Headline",
        "tag": "Label",
        "link": "URL",
        "source": "Source",
        "release_date": "Published At",
        "status": "Review Status",
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
        result_count=len(created_ids),
        message=f"created slim DingTalk AI Table sheet with {len(created_ids)} records",
        metadata={"sheet_id": sheet_id, "record_ids": created_ids},
    )
    print(f"created slim sheet: {sheet_id}")
except Exception as exc:
    print(f"create_slim_dingtalk_ai_table failed: {exc}")
    run_logs.finish(run_id, "failed", message="slim table creation failed", error=str(exc))
    raise
