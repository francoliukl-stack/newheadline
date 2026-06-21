"""Create or validate the DingTalk AI Table Audit Trail sheet."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter, ensure_audit_trail_sheet  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("ensure_audit_trail", provider="dingtalk_ai_table")

try:
    table = ensure_audit_trail_sheet(settings, store)
    audit = AuditTrailWriter(settings, store)
    audit_result = audit.record(
        run_id=run_id,
        workflow="audit_trail",
        stage_code="AUDIT.setup",
        stage_name="Ensure Audit Trail sheet",
        status="success",
        input_summary="Ensure the append-only workflow audit sheet and its required fields.",
        output_summary=f"Audit Trail sheet ready: {table.sheet_id}",
        related_sheet=table.sheet_id,
        metadata={"audit_sheet_id": table.sheet_id},
    )
    run_logs.finish(run_id, "success", result_count=1, message=f"audit sheet ready: {table.sheet_id}", metadata={"audit_write": audit_result.__dict__})
    print(f"Audit Trail ready: {table.sheet_id}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="ensure audit trail failed", error=str(exc))
    raise
