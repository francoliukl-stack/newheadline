"""Import explicitly curated URLs into canonical News with an auditable human gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.article_titles import title_from_html  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.coverage_audit import build_coverage_audit  # noqa: E402
from app.dingtalk_ai_table import add_records, ensure_fields, list_fields, list_records, resolve_news_field_mapping, update_records  # noqa: E402
from app.editorial_intake import EDITORIAL_NEWS_FIELDS, plan_editorial_intake  # noqa: E402
from app.publish_dates import date_from_html, date_from_url, parse_date  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_NEWS_SHEET_ID = "oMbefcK"


def load_items(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("cases") or []
        return [item for item in rows if isinstance(item, dict)]
    raise ValueError("editorial input must be a JSON list or object with items/cases")


def hydrate_metadata(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hydrated = [dict(item) for item in items]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GBSS-News-Coverage/1.0)"}
    with httpx.Client(follow_redirects=True, timeout=15, headers=headers) as client:
        for item in hydrated:
            url = str(item.get("url") or item.get("URL") or "").strip()
            has_title = bool(str(item.get("title") or item.get("Title") or "").strip())
            has_date = bool(parse_date(item.get("publish_date") or item.get("Publish Date"))) or bool(date_from_url(url))
            if has_title and has_date:
                continue
            try:
                response = client.get(url)
                if response.is_success:
                    if not has_title:
                        item["title"] = title_from_html(response.text) or ""
                    if not has_date:
                        item["publish_date"] = date_from_html(response.text) or date_from_url(str(response.url)) or ""
                else:
                    item["_metadata_fetch_error"] = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                item["_metadata_fetch_error"] = str(exc)
    return hydrated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reason", default="Editorial URL intake")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-eventize", action="store_true")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    settings.dingtalk_ai_table.sheet_id = CANONICAL_NEWS_SHEET_ID
    runs = RunLogStore(DATA / "settings.sqlite3")
    run_id = runs.start("editorial_url_intake", provider="editorial_input", metadata={"approve": args.approve, "input": str(args.input)})
    audit = AuditTrailWriter(settings, store, runs)
    artifact_path = DATA / "coverage-audit-latest.json"

    try:
        items = hydrate_metadata(load_items(args.input))
        existing = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        fields_result = list_fields(settings.dingtalk, settings.dingtalk_ai_table)
        if not fields_result.get("ok"):
            raise RuntimeError(str(fields_result.get("message") or "failed to list News fields"))
        field_names = {
            str(field.get("name") or "")
            for field in (fields_result.get("payload") or {}).get("value") or []
        }
        mapping = resolve_news_field_mapping(settings.dingtalk_ai_table.field_mapping, field_names)
        status_field = mapping.get("status") or "Review Status"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        plan = plan_editorial_intake(
            items,
            existing,
            approve=args.approve,
            reason=args.reason,
            now=now,
            status_field=status_field,
        )

        if not args.dry_run:
            ensured = ensure_fields(settings.dingtalk, settings.dingtalk_ai_table, EDITORIAL_NEWS_FIELDS)
            if not ensured.get("ok"):
                raise RuntimeError(str(ensured.get("message") or "failed to ensure editorial News fields"))
            if plan["creates"]:
                created = add_records(settings.dingtalk, settings.dingtalk_ai_table, plan["creates"])
                if created.status != "sent":
                    raise RuntimeError(created.message)
            if plan["updates"]:
                updated = update_records(settings.dingtalk, settings.dingtalk_ai_table, plan["updates"])
                if updated.status != "sent":
                    raise RuntimeError(updated.message)
            if (plan["creates"] or plan["updates"]) and not args.skip_eventize:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "eventize_news.py"), "--apply"],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "eventize_news failed")

        current_news = existing if args.dry_run else list_records(settings.dingtalk, settings.dingtalk_ai_table)
        event_records = []
        if settings.dingtalk_ai_table.event_cases_sheet_id:
            event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
            event_records = list_records(settings.dingtalk, event_table)
        target_urls = [{"url": item.get("url") or item.get("URL") or ""} for item in items]
        urls = [str(item["url"]) for item in target_urls]
        coverage = build_coverage_audit(
            target_urls,
            current_news,
            event_records,
            discovered_urls=urls,
            selected_urls=urls,
            generated_at=now,
        )
        coverage["intake"] = {"run_id": run_id, "approve": args.approve, **plan["counts"], "results": plan["results"]}
        if not args.dry_run:
            artifact_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")

        status = "success" if plan["counts"]["blocked"] == 0 else "degraded"
        runs.finish(run_id, status, result_count=plan["counts"]["created"] + plan["counts"]["updated"], message=json.dumps(plan["counts"], ensure_ascii=False), metadata={"artifact_path": str(artifact_path), "results": plan["results"]})
        audit.record(
            run_id=run_id,
            workflow="editorial_url_intake",
            stage_code="EDITORIAL.complete",
            stage_name="Import editorial URLs",
            status=status,
            mode="dry-run" if args.dry_run else "live",
            input_summary=f"Input URLs={len(items)}; approve={args.approve}.",
            output_summary=json.dumps(plan["counts"], ensure_ascii=False),
            result_count=plan["counts"]["created"] + plan["counts"]["updated"],
            related_sheet=settings.dingtalk_ai_table.sheet_id,
            artifact_path=str(artifact_path),
            metadata={"results": plan["results"]},
        )
        print(json.dumps({"mode": "dry-run" if args.dry_run else "live", **plan, "coverage": coverage}, ensure_ascii=False, indent=2))
        return 0 if plan["counts"]["blocked"] == 0 else 2
    except Exception as exc:
        runs.finish(run_id, "failed", message="editorial URL intake failed", error=str(exc))
        audit.record(
            run_id=run_id,
            workflow="editorial_url_intake",
            stage_code="EDITORIAL.complete",
            stage_name="Import editorial URLs",
            status="failed",
            mode="dry-run" if args.dry_run else "live",
            error=str(exc),
            related_sheet=settings.dingtalk_ai_table.sheet_id,
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
