"""Daily search-provider entrypoint.

This script is intentionally independent from Codex. It reads local settings
and instantiates the configured search provider. Full extraction, ranking,
dedupe, and Lark writes are implemented in later workflow modules.
"""

from pathlib import Path
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.search_providers import (  # noqa: E402
    ProviderNotConfigured,
    SearchQuery,
    build_fallback_provider,
    build_provider,
    build_supplemental_providers,
    select_provider_query_groups,
)
from app.detect_sources import (  # noqa: E402
    build_detect_query_plan,
    default_detect_source_records,
    dedupe_candidates,
    ensure_detect_sources_sheet,
    is_trusted_source,
    select_balanced_candidates,
    trusted_source_domains,
    validate_candidate_lanes,
)
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.notifications import build_dingtalk_approval_url, send_ingest_completion_notification  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.publish_dates import resolve_provider_publish_date  # noqa: E402


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
detect_source_records = default_detect_source_records(settings)
query_source = "local_settings"
if settings.dingtalk_ai_table.enabled and settings.dingtalk_ai_table.base_id:
    try:
        detect_table = ensure_detect_sources_sheet(settings, store)
        settings = store.load(masked=False)
        detect_records = list_records(settings.dingtalk, detect_table)
        table_plan = build_detect_query_plan(detect_records)
        if table_plan:
            query_plan = table_plan
            detect_source_records = detect_records
            query_source = "detect_sources_sheet"
    except Exception as exc:
        print(f"daily_fetch detect source table unavailable, using local fallback: {exc}")


def result_payload(item: object, query_key: str, query_text: str, section: str, lane: str, observed_at: datetime, provider_name: str = "") -> dict:
    published = resolve_provider_publish_date(item.published_at, observed_at, settings.system.timezone)
    payload = {
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": published.value,
        "Date Confidence": published.method,
        "source_excerpt": item.snippet,
        "search_query": query_text,
        "Search Query": query_text,
        "search_group": query_key,
        "Search Group": query_key,
        "source_lane": lane,
        "Source Lane": lane,
        "section": section,
    }
    if provider_name:
        payload.update({
            "search_provider": provider_name,
            "Search Provider": provider_name,
            "discovery_type": "supplemental",
            "Discovery Type": "supplemental",
        })
    return payload


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
    collected_at = datetime.now(ZoneInfo(settings.system.timezone))
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
        raw_records.extend(result_payload(item, planned.key, planned.text, planned.section, planned.lane, collected_at) for item in results)

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
        raw_records.extend(result_payload(item, "fallback_cache", fallback_query.text, "All", "broad_market", collected_at) for item in fallback_results)
        message = f"all primary query groups failed; fallback returned {len(fallback_results)} cached results"

    try:
        supplemental_providers = build_supplemental_providers(settings.search_provider)
    except ProviderNotConfigured as exc:
        supplemental_providers = []
        print(f"daily_fetch supplemental providers unavailable: {exc}")
    # Rotate the query-group window each fetch so rate-limited supplemental
    # providers (e.g. marketaux) cover every group over successive runs.
    fetch_index = max(0, run_logs.count("daily_fetch") - 1)
    for provider_name, extra_provider in supplemental_providers:
        group_limit = settings.search_provider.supplemental_query_group_limits.get(provider_name, 0)
        provider_groups = select_provider_query_groups(query_plan, group_limit, fetch_index)
        extra_successes = 0
        for planned in provider_groups:
            time.sleep(5)  # free APIs such as GDELT throttle back-to-back requests
            query = SearchQuery(text=planned.text, section=planned.section, domains=planned.domains)
            try:
                results = extra_provider.search(query)
            except Exception as exc:
                query_runs.append({
                    "key": f"{planned.key}@{provider_name}",
                    "section": planned.section,
                    "query": planned.text,
                    "status": "failed",
                    "result_count": 0,
                    "error": str(exc),
                })
                print(f"daily_fetch supplemental query failed [{planned.key}@{provider_name}]: {exc}")
                continue
            extra_successes += 1
            query_runs.append({
                "key": f"{planned.key}@{provider_name}",
                "section": planned.section,
                "query": planned.text,
                "status": "success",
                "result_count": len(results),
            })
            raw_records.extend(
                result_payload(item, planned.key, planned.text, planned.section, planned.lane, collected_at, provider_name)
                for item in results
            )
        message = f"{message}; supplemental {provider_name} completed {extra_successes}/{len(provider_groups)} query groups"

    unique_records = dedupe_candidates(raw_records)
    trusted_domains = trusted_source_domains(detect_source_records)
    unique_records = validate_candidate_lanes(unique_records, trusted_domains)
    records = select_balanced_candidates(
        unique_records,
        trusted_domains,
        settings.search_provider.max_candidates_per_query,
        settings.search_provider.max_candidates_per_daily_fetch,
        target_publish_date=collected_at.date() - timedelta(days=1),
    )
    status = "success"
    result_count = len(records)
    message = (
        f"{message}; {len(raw_records)} raw candidates -> {len(unique_records)} unique URLs "
        f"-> {result_count} balanced review candidates"
    )
    print(f"daily_fetch {message}")
    raw_lane_counts = {
        lane: sum(str(record.get("source_lane") or "") == lane for record in unique_records)
        for lane in ("core_entity", "strategic_theme", "trusted_media", "specialist_media", "broad_market", "editorial")
    }
    selected_lane_counts = {
        lane: sum(str(record.get("source_lane") or "") == lane for record in records)
        for lane in ("core_entity", "strategic_theme", "trusted_media", "broad_market", "editorial")
    }
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
                "raw_lane_counts": raw_lane_counts,
                "selected_lane_counts": selected_lane_counts,
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
        metadata={
            "provider": used_provider,
            "query_source": query_source,
            "query_runs": query_runs,
            "raw_lane_counts": raw_lane_counts,
            "selected_lane_counts": selected_lane_counts,
        },
    )
    run_step("写入 News", "INGEST.write_news", "push_dingtalk_ai_table.py")
    run_step("整理标题", "INGEST.refresh_titles", "backfill_titles.py")
    run_step("补齐发布时间", "INGEST.backfill_publish_date", "backfill_publish_dates.py")
    run_step("语义去重", "INGEST.semantic_dedupe", "dedupe_news.py")
    message = f"{message}; automated News pipeline completed"
    if settings.event_intelligence.enabled:
        try:
            run_step("聚合 Event Cases", "INGEST.eventize", "eventize_news.py", "--apply")
        except Exception as exc:
            status = "degraded"
            error = str(exc)
            message = f"{message}; optional Event Cases sync deferred: {exc}"
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
