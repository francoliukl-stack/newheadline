"""Refresh canonical News titles from source pages and keep them compact."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.article_titles import shorten_title, title_from_html  # noqa: E402
from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
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


def fetch_title(record: Dict[str, object]) -> Tuple[Dict[str, object], str]:
    fields = record.get("fields") or {}
    source_url = fields.get("Source URL") or {}
    url = source_url.get("link") if isinstance(source_url, dict) else source_url
    fallback = str(fields.get("Title") or fields.get("Title & URL") or "")
    if not isinstance(url, str) or not url:
        return record, shorten_title(fallback)
    try:
        with httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 WeeklyHeadlines/1.0"},
            timeout=8,
        ) as client:
            response = client.get(url)
            if response.is_success:
                extracted = title_from_html(response.text)
                if extracted:
                    return record, shorten_title(extracted)
    except httpx.HTTPError:
        pass
    return record, shorten_title(fallback)


run_id = run_logs.start("backfill_titles", provider="web_page_title", metadata={"sheet_id": CANONICAL_SHEET_ID})

try:
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    candidates = [
        record
        for record in records
        if not (record.get("fields") or {}).get("Title")
        or len(str((record.get("fields") or {}).get("Title") or "")) > 20
    ]
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(fetch_title, record) for record in candidates]
        for future in as_completed(futures):
            results.append(future.result())

    updates = []
    unresolved = []
    for record, title in results:
        fields = record.get("fields") or {}
        current = str(fields.get("Title") or fields.get("Title & URL") or "")
        if not title:
            unresolved.append(record.get("id"))
            continue
        if title != current:
            updates.append({"id": record["id"], "fields": {"Title": title}})

    updated_ids: List[str] = []
    for chunk in batched(updates, 50):
        write = update_records(settings.dingtalk, settings.dingtalk_ai_table, chunk)
        if write.status != "sent":
            raise RuntimeError(write.message)
        updated_ids.extend(write.record_ids)
        print(f"updated {len(updated_ids)}/{len(updates)} titles")

    run_logs.finish(
        run_id,
        "success",
        result_count=len(updated_ids),
        message=f"refreshed {len(updated_ids)} titles; unresolved {len(unresolved)}",
        metadata={"unresolved_record_ids": unresolved},
    )
    print(f"refreshed {len(updated_ids)} titles; unresolved {len(unresolved)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="title refresh failed", error=str(exc))
    raise
