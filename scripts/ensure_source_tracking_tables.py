"""Ensure DingTalk AI Table has source tracking fields and provider registry."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import add_records, create_sheet, ensure_fields  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
NEWS_FIELDS = [
    {"name": "Search Provider", "type": "text"},
    {"name": "Search Query", "type": "text"},
    {"name": "Search Batch", "type": "text"},
    {"name": "Discovery Type", "type": "text"},
    {"name": "First Seen At", "type": "date"},
]
PROVIDER_FIELDS = [
    {"name": "Provider", "type": "text"},
    {"name": "Type", "type": "text"},
    {"name": "Priority", "type": "number"},
    {"name": "Enabled", "type": "text"},
    {"name": "Cost Model", "type": "text"},
    {"name": "Auth Mode", "type": "text"},
    {"name": "Fallback Eligible", "type": "text"},
    {"name": "Notes", "type": "text"},
    {"name": "Created At", "type": "date"},
]
PROVIDERS = [
    {"Provider": "chatgpt_web", "Type": "browser", "Priority": 1, "Enabled": "true", "Cost Model": "paid_account", "Auth Mode": "browser_profile", "Fallback Eligible": "false", "Notes": "Primary planned web search provider"},
    {"Provider": "gemini_web", "Type": "browser", "Priority": 2, "Enabled": "false", "Cost Model": "paid_or_free_account", "Auth Mode": "browser_profile", "Fallback Eligible": "true", "Notes": "Optional browser fallback"},
    {"Provider": "openclaw_cache", "Type": "cache", "Priority": 3, "Enabled": "true", "Cost Model": "local", "Auth Mode": "local_file", "Fallback Eligible": "true", "Notes": "Current working fallback source"},
    {"Provider": "manual_seed", "Type": "file", "Priority": 4, "Enabled": "false", "Cost Model": "local", "Auth Mode": "local_file", "Fallback Eligible": "true", "Notes": "Manual JSON seed file"},
    {"Provider": "serpapi", "Type": "api", "Priority": 5, "Enabled": "true", "Cost Model": "paid_api", "Auth Mode": "api_key", "Fallback Eligible": "true", "Notes": "Implemented unattended Google News search; requires API key"},
    {"Provider": "bing_web_search", "Type": "api", "Priority": 6, "Enabled": "false", "Cost Model": "retired", "Auth Mode": "none", "Fallback Eligible": "false", "Notes": "Retired by Microsoft on 2025-08-11"},
    {"Provider": "serpstack", "Type": "api", "Priority": 7, "Enabled": "false", "Cost Model": "paid_api", "Auth Mode": "api_key", "Fallback Eligible": "true", "Notes": "Future API provider"},
    {"Provider": "codex_search", "Type": "interactive_bridge", "Priority": 8, "Enabled": "true", "Cost Model": "codex_session", "Auth Mode": "interactive_session", "Fallback Eligible": "false", "Notes": "High-quality interactive supplement; requires Codex session to refresh bridge file"},
    {"Provider": "gdelt_doc", "Type": "public_api", "Priority": 9, "Enabled": "true", "Cost Model": "free_public_api", "Auth Mode": "none", "Fallback Eligible": "true", "Notes": "Unattended public news search through GDELT DOC API"},
    {"Provider": "brave_search", "Type": "api", "Priority": 10, "Enabled": "true", "Cost Model": "free_monthly_credit", "Auth Mode": "api_key", "Fallback Eligible": "true", "Notes": "Implemented unattended Brave News Search API; includes monthly free credits"},
]


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start(
    "ensure_source_tracking_tables",
    provider="dingtalk_ai_table",
    metadata={"news_sheet_id": settings.dingtalk_ai_table.sheet_id},
)

try:
    result = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, NEWS_FIELDS)
    if not result.get("ok"):
        raise RuntimeError(str(result))

    provider_sheet = settings.dingtalk_ai_table.model_copy(update={"sheet_id": ""})
    created = create_sheet(settings.dingtalk, provider_sheet, "Search Providers", PROVIDER_FIELDS)
    if not created.get("ok"):
        raise RuntimeError(str(created))
    provider_sheet_id = created["payload"]["id"]
    provider_sheet = settings.dingtalk_ai_table.model_copy(update={"sheet_id": provider_sheet_id})

    created_at = datetime.now(timezone.utc).date().isoformat()
    records = [{**record, "Created At": created_at} for record in PROVIDERS]
    created_ids: List[str] = []
    for chunk in batched(records, 100):
        write = add_records(settings.dingtalk, provider_sheet, chunk)
        if write.status != "sent":
            raise RuntimeError(write.message)
        created_ids.extend(write.record_ids)

    settings.dingtalk_ai_table.field_mapping.update({
        "search_provider": "Search Provider",
        "search_query": "Search Query",
        "search_batch": "Search Batch",
        "discovery_type": "Discovery Type",
        "first_seen_at": "First Seen At",
    })
    store.save(settings)

    run_logs.finish(
        run_id,
        "success",
        result_count=len(created_ids),
        message=f"created provider registry with {len(created_ids)} providers",
        metadata={"provider_sheet_id": provider_sheet_id, "provider_record_ids": created_ids},
    )
    print(f"provider registry sheet: {provider_sheet_id}")
except Exception as exc:
    print(f"ensure_source_tracking_tables failed: {exc}")
    run_logs.finish(run_id, "failed", message="source tracking setup failed", error=str(exc))
    raise
