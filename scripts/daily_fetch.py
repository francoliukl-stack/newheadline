"""Daily search-provider entrypoint.

This script is intentionally independent from Codex. It reads local settings
and instantiates the configured search provider. Full extraction, ranking,
dedupe, and Lark writes are implemented in later workflow modules.
"""

from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.search_providers import (  # noqa: E402
    ProviderNotConfigured,
    SearchQuery,
    build_fallback_provider,
    build_provider,
)
from app.detect_sources import (  # noqa: E402
    build_detect_query_plan,
    default_detect_source_records,
    ensure_detect_sources_sheet,
    is_trusted_source,
    select_balanced_candidates,
)
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.notifications import build_dingtalk_approval_url, send_ingest_completion_notification  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
audit = AuditTrailWriter(settings, store, run_logs)
run_id = run_logs.start(
    "daily_fetch",
    provider=settings.search_provider.provider,
    fallback_provider=settings.search_provider.fallback_provider,
    metadata={"max_results_per_query": settings.search_provider.max_results_per_query},
)
audit.record(
    run_id=run_id,
    workflow="daily_fetch",
    stage_code="INGEST.start",
    stage_name="Start daily ingest",
    status="running",
    input_summary="Start provider health, source discovery, News write, title refresh, publish-date backfill and semantic dedupe.",
    related_sheet=settings.dingtalk_ai_table.sheet_id,
    metadata={"provider": settings.search_provider.provider, "fallback_provider": settings.search_provider.fallback_provider},
)

status = "failed"
result_count = 0
message = ""
error = ""
used_provider = ""
pipeline_steps = []
query_plan = build_detect_query_plan(default_detect_source_records(settings))
query_source = "local_settings"
if settings.dingtalk_ai_table.enabled and settings.dingtalk_ai_table.base_id:
    try:
        detect_table = ensure_detect_sources_sheet(settings, store)
        settings = store.load(masked=False)
        detect_records = list_records(settings.dingtalk, detect_table)
        table_plan = build_detect_query_plan(detect_records)
        if table_plan:
            query_plan = table_plan
            query_source = "detect_sources_sheet"
    except Exception as exc:
        print(f"daily_fetch detect source table unavailable, using local fallback: {exc}")


def result_payload(item: object, query_key: str, query_text: str, section: str) -> dict:
    return {
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "source_excerpt": item.snippet,
        "search_query": query_text,
        "Search Query": query_text,
        "search_group": query_key,
        "Search Group": query_key,
        "section": section,
    }


def dedupe_candidates(records: list) -> list:
    unique = []
    seen_urls = set()
    for record in records:
        url = str(record.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(record)
    return unique


def run_step(stage_name: str, stage_code: str, script_name: str, *extra_args: str) -> None:
    script = ROOT / "scripts" / script_name
    completed = subprocess.run([sys.executable, str(script), *extra_args], cwd=ROOT, text=True, capture_output=True)
    pipeline_steps.append({
        "stage": stage_name,
        "stage_code": stage_code,
        "script": script_name,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    })
    audit.record(
        run_id=run_id,
        workflow="daily_fetch",
        stage_code=stage_code,
        stage_name=stage_name,
        status="success" if completed.returncode == 0 else "failed",
        input_summary=f"Execute {script_name} as an INGEST sub-step.",
        output_summary=completed.stdout.strip() or completed.stderr.strip(),
        result_count=completed.returncode,
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        error=completed.stderr.strip() if completed.returncode != 0 else "",
        metadata={"script": script_name, "returncode": completed.returncode},
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{script_name} failed: {completed.stderr.strip() or completed.stdout.strip()}")

try:
    run_step("来源检查", "INGEST.provider_check", "provider_health_check.py")

    if not query_plan:
        raise RuntimeError("Detect Sources produced no active search queries")

    provider = build_provider(settings.search_provider)
    raw_records = []
    query_runs = []
    primary_successes = 0
    for planned in query_plan:
        query = SearchQuery(text=planned.text, section=planned.section, domains=planned.domains)
        try:
            results = provider.search(query)
        except Exception as exc:
            query_runs.append({
                "key": planned.key,
                "section": planned.section,
                "query": planned.text,
                "status": "failed",
                "result_count": 0,
                "error": str(exc),
            })
            print(f"daily_fetch query failed [{planned.key}]: {exc}")
            continue
        primary_successes += 1
        query_runs.append({
            "key": planned.key,
            "section": planned.section,
            "query": planned.text,
            "status": "success",
            "result_count": len(results),
        })
        raw_records.extend(result_payload(item, planned.key, planned.text, planned.section) for item in results)

    if primary_successes:
        used_provider = settings.search_provider.provider
        message = f"primary provider completed {primary_successes}/{len(query_plan)} query groups"
    else:
        fallback = build_fallback_provider(settings.search_provider)
        fallback_query = SearchQuery(text="fallback cache", section="All", domains=[])
        fallback_results = fallback.search(fallback_query)
        used_provider = settings.search_provider.fallback_provider
        query_runs.append({
            "key": "fallback_cache",
            "section": "All",
            "query": fallback_query.text,
            "status": "success",
            "result_count": len(fallback_results),
        })
        raw_records.extend(result_payload(item, "fallback_cache", fallback_query.text, "All") for item in fallback_results)
        message = f"all primary query groups failed; fallback returned {len(fallback_results)} cached results"

    unique_records = dedupe_candidates(raw_records)
    trusted_domains = {domain for planned in query_plan for domain in planned.domains}
    records = select_balanced_candidates(
        unique_records,
        trusted_domains,
        settings.search_provider.max_candidates_per_query,
        settings.search_provider.max_candidates_per_daily_fetch,
    )
    status = "success"
    result_count = len(records)
    message = (
        f"{message}; {len(raw_records)} raw candidates -> {len(unique_records)} unique URLs "
        f"-> {result_count} balanced review candidates"
    )
    print(f"daily_fetch {message}")
    (DATA / "latest-provider-results.json").write_text(
        json.dumps(
            {
                "provider": used_provider,
                "query": "multi-query detect sources collection",
                "query_source": query_source,
                "query_runs": query_runs,
                "raw_candidate_count": len(raw_records),
                "unique_candidate_count": len(unique_records),
                "selected_candidate_count": result_count,
                "trusted_source_candidate_count": sum(is_trusted_source(record, trusted_domains) for record in records),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    audit.record(
        run_id=run_id,
        workflow="daily_fetch",
        stage_code="INGEST.search",
        stage_name="Collect provider results",
        status="success",
        input_summary=f"Executed {len(query_runs)} grouped queries from {query_source}.",
        output_summary=(
            f"Collected {len(raw_records)} raw candidates, {len(unique_records)} unique URLs, "
            f"and selected {result_count} review candidates using {used_provider}."
        ),
        result_count=result_count,
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        artifact_path=str(DATA / "latest-provider-results.json"),
        metadata={"provider": used_provider, "query_source": query_source, "query_runs": query_runs},
    )
    run_step("写入 News", "INGEST.write_news", "push_dingtalk_ai_table.py")
    run_step("整理标题", "INGEST.refresh_titles", "backfill_titles.py")
    run_step("补齐发布时间", "INGEST.backfill_publish_date", "backfill_publish_dates.py")
    run_step("语义去重", "INGEST.semantic_dedupe", "dedupe_news.py")
    if settings.event_intelligence.enabled:
        run_step("聚合 Event Cases", "INGEST.eventize", "eventize_news.py", "--apply")
    message = f"{message}; automated News pipeline completed"
except (NotImplementedError, ProviderNotConfigured) as exc:
    status = "failed"
    message = f"provider unavailable: {exc}"
    error = str(exc)
    print(f"daily_fetch {message}")
except Exception as exc:
    status = "failed"
    message = f"unexpected error: {exc}"
    error = str(exc)
    print(f"daily_fetch {message}")

notification = send_ingest_completion_notification(
    settings.dingtalk,
    status=status,
    result_count=result_count,
    provider=used_provider or settings.search_provider.provider,
    message=message,
    approval_url=build_dingtalk_approval_url(
        settings.dingtalk_ai_table.base_id,
        settings.dingtalk_ai_table.approval_view_url,
    ),
)
print(f"daily_fetch notification {notification.status}: {notification.message}")
run_logs.finish(
    run_id,
    status,
    result_count=result_count,
    message=message,
    error=error,
    metadata={
        "used_provider": used_provider,
        "query_source": query_source,
        "query_runs": query_runs if "query_runs" in locals() else [],
        "raw_candidate_count": len(raw_records) if "raw_records" in locals() else 0,
        "unique_candidate_count": len(unique_records) if "unique_records" in locals() else 0,
        "selected_candidate_count": result_count,
        "trusted_source_candidate_count": sum(
            is_trusted_source(record, trusted_domains) for record in records
        ) if "trusted_domains" in locals() else 0,
        "notification_status": notification.status,
        "notification_message": notification.message,
        "pipeline_steps": pipeline_steps,
    },
)
audit.record(
    run_id=run_id,
    workflow="daily_fetch",
    stage_code="INGEST.complete",
    stage_name="Complete daily ingest",
    status=status,
    input_summary=f"Executed {len(query_runs) if 'query_runs' in locals() else 0} grouped queries from {query_source}.",
    output_summary=message,
    result_count=result_count,
    related_sheet=settings.dingtalk_ai_table.sheet_id,
    error=error,
    metadata={
        "used_provider": used_provider,
        "query_runs": query_runs if "query_runs" in locals() else [],
        "pipeline_steps": pipeline_steps,
        "notification": notification.__dict__,
    },
)
