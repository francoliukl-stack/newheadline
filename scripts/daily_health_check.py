"""Run a daily operational health check for the headlines workflow."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.notifications import send_dingtalk_webhook_text  # noqa: E402
from app.provider_health import check_configured_providers  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.v3_1_metrics import build_v3_1_metrics  # noqa: E402


DATA = ROOT / "data"
LOOKBACK_HOURS = 24
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
audit = AuditTrailWriter(settings, store, run_logs)
parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
run_id = run_logs.start("daily_health_check", provider=settings.search_provider.provider)
audit.record(
    run_id=run_id,
    workflow="daily_health_check",
    stage_code="HEALTH.start",
    stage_name="Start daily health check",
    status="running",
    mode="dry-run" if args.dry_run else "live",
    input_summary=f"Validate providers, News table and failed runs within {LOOKBACK_HOURS} hours.",
    related_sheet=settings.dingtalk_ai_table.sheet_id,
)


def recent_failed_runs() -> List[Dict[str, object]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    failed = []
    recovered_workflows = set()
    for run in run_logs.list_recent(limit=100):
        if run["job_name"] == "daily_health_check":
            continue
        started_at = datetime.fromisoformat(run["started_at"])
        if started_at < cutoff:
            continue
        # list_recent is newest-first. A later success proves the same workflow
        # recovered; retain its historical failure in RunLog/Audit Trail but do
        # not keep the operational health check red.
        if run["status"] == "success":
            recovered_workflows.add(str(run["job_name"]))
            continue
        if run["status"] == "running":
            failed.append(run)
            continue
        if run["status"] == "failed" and str(run["job_name"]) not in recovered_workflows:
            failed.append(run)
    return failed


def format_run(run: Dict[str, object]) -> str:
    message = str(run.get("error") or run.get("message") or "-").splitlines()[0]
    return f"- {run['job_name']} {run['status']}: {message}"


try:
    checks = []
    recovered_stale = 0 if args.dry_run else run_logs.recover_stale_runs()
    flushed_audit = 0 if args.dry_run else audit.flush_pending()
    checks.append(("RunLog stale recovery", True))
    checks.append(("Audit pending flush", True))

    provider_results = check_configured_providers(settings.search_provider)
    provider_ok = any(result.ok for result in provider_results)
    checks.append(("搜索源", provider_ok))
    audit.record(
        run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.providers", stage_name="Check providers",
        status="success" if provider_ok else "failed", output_summary="; ".join(f"{item.provider}: {item.message}" for item in provider_results),
        mode="dry-run" if args.dry_run else "live", result_count=sum(item.result_count for item in provider_results if item.ok), related_sheet=settings.dingtalk_ai_table.sheet_id,
        metadata={"providers": [item.__dict__ for item in provider_results]},
    )

    table_count = 0
    news_records = []
    table_error = ""
    try:
        news_records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        table_count = len(news_records)
        table_ok = True
    except Exception as exc:
        table_ok = False
        table_error = str(exc)
    checks.append(("News 表连通", table_ok))
    audit.record(
        run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.news_table", stage_name="Check News table connectivity",
        status="success" if table_ok else "failed", output_summary=f"News record count: {table_count}" if table_ok else table_error,
        mode="dry-run" if args.dry_run else "live", result_count=table_count, related_sheet=settings.dingtalk_ai_table.sheet_id, error=table_error,
    )

    kpi_snapshot: Dict[str, object] = {}
    kpi_error = ""
    if settings.event_intelligence.enabled:
        try:
            ai = settings.dingtalk_ai_table
            required = [ai.event_cases_sheet_id, ai.evidence_bank_sheet_id, ai.claim_ledger_sheet_id, ai.api_usage_sheet_id]
            if not all(required):
                raise RuntimeError("v3.1 Event/Evidence/Claim/API Usage sheets must be configured")
            event_table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
            first_scan = run_logs.first_success_started_at("critical_event_scan")
            kpi_snapshot = build_v3_1_metrics(
                news=news_records,
                events=list_records(settings.dingtalk, event_table(ai.event_cases_sheet_id)),
                evidence=list_records(settings.dingtalk, event_table(ai.evidence_bank_sheet_id)),
                claims=list_records(settings.dingtalk, event_table(ai.claim_ledger_sheet_id)),
                usage=list_records(settings.dingtalk, event_table(ai.api_usage_sheet_id)),
                observation_started_at=datetime.fromisoformat(first_scan) if first_scan else None,
            )
            kpi_ok = True
        except Exception as exc:
            kpi_ok = False
            kpi_error = str(exc)
        checks.append(("v3.1 KPI 快照", kpi_ok))
        audit.record(
            run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.v3_1_kpi", stage_name="Record v3.1 KPI snapshot",
            status="success" if kpi_ok else "failed", output_summary=(
                f"Observation day {((kpi_snapshot.get('window') or {}).get('observation_days'))}; "
                f"four-week status {kpi_snapshot.get('four_week_success_status')}"
                if kpi_ok else kpi_error
            ),
            mode="dry-run" if args.dry_run else "live", related_sheet=ai.event_cases_sheet_id,
            error=kpi_error, metadata={"kpi_snapshot": kpi_snapshot},
        )

    failed_runs = recent_failed_runs()
    runs_ok = not failed_runs
    checks.append((f"最近 {LOOKBACK_HOURS} 小时任务", runs_ok))
    audit.record(
        run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.recent_runs", stage_name="Check recent workflow failures",
        status="success" if runs_ok else "failed", output_summary=f"Recent failed/running jobs: {len(failed_runs)}",
        mode="dry-run" if args.dry_run else "live", result_count=len(failed_runs), related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"failed_runs": failed_runs[:10]},
    )

    ok = all(item[1] for item in checks)
    status = "success" if ok else "failed"
    lines = [
        f"【每日健康检查{'正常' if ok else '异常'}】",
        f"状态：{status}",
        "",
        "检查项：",
    ]
    lines.extend(f"- {name}: {'OK' if item_ok else 'FAIL'}" for name, item_ok in checks)
    lines.extend(["", "搜索源："])
    lines.extend(
        f"- {result.provider}: {'OK' if result.ok else 'FAIL'} ({result.message})"
        for result in provider_results
    )
    lines.extend(["", f"News 表记录数：{table_count if table_ok else '-'}"])
    if settings.event_intelligence.enabled:
        if kpi_snapshot:
            window = kpi_snapshot.get("window") or {}
            lines.extend([
                "",
                "v3.1 运营观察：",
                f"- 观察天数：{window.get('observation_days')}",
                f"- 四周状态：{kpi_snapshot.get('four_week_success_status')}",
                f"- 关键事件上线前回填：{(kpi_snapshot.get('metrics') or {}).get('critical_backfill_events_7d')}",
            ])
        elif kpi_error:
            lines.extend(["", f"v3.1 KPI 错误：{kpi_error}"])
    if table_error:
        lines.extend(["", f"News 表错误：{table_error}"])
    if failed_runs:
        lines.extend(["", "最近失败/未完成任务："])
        lines.extend(format_run(run) for run in failed_runs[:10])

    content = "\n".join(lines)
    if not ok and not args.dry_run:
        notification = send_dingtalk_webhook_text(
            settings.dingtalk.daily_webhook_url,
            settings.dingtalk.daily_signing_secret,
            content,
            settings.dingtalk.at_mobiles,
        )
    else:
        notification = None

    run_logs.finish(
        run_id,
        status,
        result_count=table_count,
        message="; ".join(f"{name}={'OK' if item_ok else 'FAIL'}" for name, item_ok in checks),
        metadata={
            "providers": [result.__dict__ for result in provider_results],
            "table_count": table_count,
            "failed_runs": failed_runs[:10],
            "notification": notification.__dict__ if notification else {"status": "skipped", "message": "dry-run or healthy"},
            "recovered_stale_runs": recovered_stale,
            "flushed_audit_events": flushed_audit,
            "kpi_snapshot": kpi_snapshot,
        },
    )
    audit.record(
        run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.complete", stage_name="Complete daily health check",
        status=status, output_summary="; ".join(f"{name}={'OK' if item_ok else 'FAIL'}" for name, item_ok in checks),
        mode="dry-run" if args.dry_run else "live", result_count=table_count, related_sheet=settings.dingtalk_ai_table.sheet_id,
        metadata={"notification": notification.__dict__ if notification else {"status": "skipped"}},
    )
    print(content)
    if not ok and not args.dry_run:
        raise SystemExit(1)
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily health check failed", error=str(exc))
    audit.record(run_id=run_id, workflow="daily_health_check", stage_code="HEALTH.complete", stage_name="Complete daily health check", status="failed", mode="dry-run" if args.dry_run else "live", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id)
    raise
