"""Send a DingTalk reminder for pending News review records."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records  # noqa: E402
from app.notifications import send_dingtalk_webhook_text  # noqa: E402
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
run_id = run_logs.start("daily_remind", provider="dingtalk_ai_table")

try:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "provider_health_check.py")], cwd=ROOT, check=True)
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    pending = []
    for record in records:
        fields = record.get("fields") or {}
        status = fields.get("Status") or {}
        status_name = status.get("name") if isinstance(status, dict) else status
        if status_name == "待处理":
            pending.append(fields)
    content = "\n".join([
        "【新闻待审核提醒】",
        f"待处理数量：{len(pending)}",
        "请打开钉钉 AI 表格 News 完成审核。",
    ])
    notification = send_dingtalk_webhook_text(
        settings.dingtalk.daily_webhook_url,
        settings.dingtalk.daily_signing_secret,
        content,
    )
    status = "success" if notification.status == "sent" else notification.status
    run_logs.finish(run_id, status, result_count=len(pending), message=notification.message)
    print(f"daily_remind {status}: pending={len(pending)}; {notification.message}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="daily reminder failed", error=str(exc))
    raise
