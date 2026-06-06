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
from app.notifications import send_dingtalk_webhook_text  # noqa: E402
from app.provider_health import check_configured_providers  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
LOOKBACK_HOURS = 24
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
run_id = run_logs.start("daily_health_check", provider=settings.search_provider.provider)


def recent_failed_runs() -> List[Dict[str, object]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    failed = []
    for run in run_logs.list_recent(limit=100):
        if run["job_name"] == "daily_health_check":
            continue
        started_at = datetime.fromisoformat(run["started_at"])
        if started_at < cutoff:
            continue
        if run["status"] in {"failed", "running"}:
            failed.append(run)
    return failed


def format_run(run: Dict[str, object]) -> str:
    message = str(run.get("error") or run.get("message") or "-").splitlines()[0]
    return f"- {run['job_name']} {run['status']}: {message}"


try:
    checks = []

    provider_results = check_configured_providers(settings.search_provider)
    provider_ok = any(result.ok for result in provider_results)
    checks.append(("搜索源", provider_ok))

    table_count = 0
    table_error = ""
    try:
        table_count = len(list_records(settings.dingtalk, settings.dingtalk_ai_table))
        table_ok = True
    except Exception as exc:
        table_ok = False
        table_error = str(exc)
    checks.append(("News 表连通", table_ok))

    failed_runs = recent_failed_runs()
    runs_ok = not failed_runs
    checks.append((f"最近 {LOOKBACK_HOURS} 小时任务", runs_ok))

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
        },
    )
    print(content)
    if not ok and not args.dry_run:
        raise SystemExit(1)
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily health check failed", error=str(exc))
    raise
