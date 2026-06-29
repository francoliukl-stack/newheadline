"""Backfill Publish Date on the canonical News DingTalk AI Table sheet."""

from __future__ import annotations

import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.publish_dates import PublishedDateResult, discover_published_date, needs_publish_date_resolution, publish_date_update  # noqa: E402
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


def fetch_date(record: Dict[str, object]) -> Tuple[Dict[str, object], PublishedDateResult]:
    fields = record.get("fields") or {}
    source_url = fields.get("Source URL") or {}
    url = source_url.get("link") if isinstance(source_url, dict) else source_url
    if not isinstance(url, str) or not url:
        return record, PublishedDateResult("", "unresolved")
    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 WeeklyHeadlines/1.0"},
        timeout=8,
    ) as client:
        fallback_date = fields.get("Publish Date") if fields.get("Date Confidence") == "provider_relative" else fields.get("Release Date")
        return record, discover_published_date(client, url, fallback_date)


run_id = run_logs.start(
    "backfill_publish_dates",
    provider="web_page_metadata",
    metadata={"sheet_id": CANONICAL_SHEET_ID},
)

try:
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    candidates = [record for record in records if needs_publish_date_resolution(record.get("fields") or {})]
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(fetch_date, record) for record in candidates]
        for future in as_completed(futures):
            results.append(future.result())

    updates = []
    methods = Counter()
    unresolved = []
    for record, result in results:
        methods[result.method] += 1
        fields = record.get("fields") or {}
        update = publish_date_update(fields, result)
        if not update:
            unresolved.append(record.get("id"))
            continue
        updates.append({"id": record["id"], "fields": update})

    updated_ids: List[str] = []
    for chunk in batched(updates, 100):
        write = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if write.status != "sent":
            raise RuntimeError(write.message)
        updated_ids.extend(write.record_ids)
        print(f"updated {len(updated_ids)}/{len(updates)} publish dates")

    run_logs.finish(
        run_id,
        "success",
        result_count=len(updated_ids),
        message=f"backfilled {len(updated_ids)} publish dates; unresolved {len(unresolved)}",
        metadata={"candidate_count": len(candidates), "methods": dict(methods), "unresolved_record_ids": unresolved},
    )
    print(f"backfilled {len(updated_ids)} publish dates; unresolved {len(unresolved)}")
    print(f"methods: {dict(methods)}")
except Exception as exc:
    print(f"backfill_publish_dates failed: {exc}")
    run_logs.finish(run_id, "failed", message="publish date backfill failed", error=str(exc))
    raise
