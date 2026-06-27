"""Send a DingTalk reminder for pending News review records."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, status_name  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.notifications import build_dingtalk_approval_url, send_dingtalk_action_card  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
audit = AuditTrailWriter(settings, store, run_logs)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
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
    pending_events = []
    p0_candidates = 0
    strategic_candidates = 0
    if settings.event_intelligence.enabled and settings.dingtalk_ai_table.event_cases_sheet_id:
        event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
        for record in list_records(settings.dingtalk, event_table):
            fields = record.get("fields") or {}
            if str(fields.get("Status") or "") == "待处理":
                pending_events.append(fields)
                p0_candidates += str(fields.get("Priority Candidate") or "") == "P0_Candidate"
                strategic_candidates += str(fields.get("Strategic Candidate") or "").lower() == "yes"
    total = len(pending) + len(pending_events)
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.pending_count", stage_name="Count pending News and Event reviews", status="success", output_summary=f"Pending News={len(pending)}; Events={len(pending_events)}; P0 Candidates={p0_candidates}", result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id)
    review_url = settings.event_intelligence.review_view_url or build_dingtalk_approval_url(settings.dingtalk_ai_table.base_id, settings.dingtalk_ai_table.approval_view_url)
    content = "\n\n".join([
        "### 📢 GBSS 外部事件待审提醒",
        f"News 待处理：**{len(pending)}**  ",
        f"Event Case 待处理：**{len(pending_events)}**  ",
        f"P0 Candidate：**{p0_candidates}**  ",
        f"Strategic Event：**{strategic_candidates}**  ",
        "请先完成 News 审核，再确认 Event Case、Evidence 与 Claim。",
    ])
    notification = send_dingtalk_action_card(
        settings.dingtalk.daily_webhook_url,
        settings.dingtalk.daily_signing_secret,
        "GBSS 外部事件待审提醒",
        content,
        "打开审核视图",
        review_url,
        settings.dingtalk.at_mobiles,
    )
    status = "success" if notification.status == "sent" else notification.status
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.notify", stage_name="Send review reminder", status=status, output_summary=notification.message, result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"notification": notification.__dict__, "pending_news": len(pending), "pending_events": len(pending_events)})
    run_logs.finish(run_id, status, result_count=total, message=notification.message)
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status=status, output_summary=notification.message, result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id)
    print(f"daily_remind {status}: pending_news={len(pending)}; pending_events={len(pending_events)}; {notification.message}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily reminder failed", error=str(exc))
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status="failed", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id)
    raise
