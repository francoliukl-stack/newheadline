"""Send a DingTalk reminder for pending News review records."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, status_name  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.notifications import build_dingtalk_approval_url, send_dingtalk_webhook_text  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
audit = AuditTrailWriter(settings, store)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
store.save(settings)
run_id = run_logs.start("daily_remind", provider="dingtalk_ai_table")
audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.start", stage_name="Start review reminder", status="running", input_summary="Check providers, count pending News records and send review reminder.", related_sheet=settings.dingtalk_ai_table.sheet_id)

try:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "provider_health_check.py")], cwd=ROOT, check=True)
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.provider_check", stage_name="Check providers", status="success", output_summary="Provider health check completed.", related_sheet=settings.dingtalk_ai_table.sheet_id)
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    pending = []
    for record in records:
        fields = record.get("fields") or {}
        if status_name(fields, settings.dingtalk_ai_table.field_mapping) == "待处理":
            pending.append(fields)
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.pending_count", stage_name="Count pending News reviews", status="success", output_summary=f"Pending News reviews: {len(pending)}", result_count=len(pending), related_sheet=settings.dingtalk_ai_table.sheet_id)
    content = "\n".join([
        "【新闻待审核提醒】",
        f"待处理数量：{len(pending)}",
        "请打开钉钉 AI 表格 News 完成审核。",
        build_dingtalk_approval_url(
            settings.dingtalk_ai_table.base_id,
            settings.dingtalk_ai_table.approval_view_url,
        ),
    ])
    notification = send_dingtalk_webhook_text(
        settings.dingtalk.daily_webhook_url,
        settings.dingtalk.daily_signing_secret,
        content,
        settings.dingtalk.at_mobiles,
    )
    status = "success" if notification.status == "sent" else notification.status
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.notify", stage_name="Send review reminder", status=status, output_summary=notification.message, result_count=len(pending), related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"notification": notification.__dict__})
    run_logs.finish(run_id, status, result_count=len(pending), message=notification.message)
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status=status, output_summary=notification.message, result_count=len(pending), related_sheet=settings.dingtalk_ai_table.sheet_id)
    print(f"daily_remind {status}: pending={len(pending)}; {notification.message}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily reminder failed", error=str(exc))
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status="failed", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id)
    raise
