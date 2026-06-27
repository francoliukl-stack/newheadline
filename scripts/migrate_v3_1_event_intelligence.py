"""Idempotently create or inspect the GBSS v3.1 DingTalk event schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.config_sheet import ensure_config_sheet, sync_config_items  # noqa: E402
from app.event_tables import ensure_event_intelligence_sheets, ensure_lineage_fields, schema_plan, seed_entity_catalog  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group()
mode.add_argument("--dry-run", action="store_true")
mode.add_argument("--apply", action="store_true")
args = parser.parse_args()

data = ROOT / "data"
store = SettingsStore(data / "settings.sqlite3", SecretStore(data / "secrets.json"))
settings = store.load(masked=False)

if not args.apply:
    print(json.dumps({"mode": "dry-run", "schema_version": settings.event_intelligence.schema_version, "plan": schema_plan(settings)}, ensure_ascii=False, indent=2))
    raise SystemExit(0)

runs = RunLogStore(data / "settings.sqlite3")
run_id = runs.start("migrate_v3_1_event_intelligence", provider="dingtalk_ai_table")
audit = AuditTrailWriter(settings, store, run_logs=runs)
try:
    tables = ensure_event_intelligence_sheets(settings, store)
    settings = store.load(masked=False)
    ensure_lineage_fields(settings, tables)
    seeded = seed_entity_catalog(settings, tables.entity_catalog)
    config = ensure_config_sheet(settings, store)
    sync_config_items(settings, config)
    runs.finish(run_id, "success", result_count=7, message=f"v3.1 schema ready; seeded={seeded}")
    audit.record(run_id=run_id, workflow="migration", stage_code="MIGRATE.v3_1", stage_name="Apply v3.1 event schema", status="success", result_count=7, output_summary=f"Event schema ready; seeded entities={seeded}", metadata={"schema_version": settings.event_intelligence.schema_version})
    print(f"migration success: sheets=7; seeded_entities={seeded}")
except Exception as exc:
    runs.finish(run_id, "failed", message="v3.1 migration failed", error=str(exc))
    audit.record(run_id=run_id, workflow="migration", stage_code="MIGRATE.v3_1", stage_name="Apply v3.1 event schema", status="failed", error=str(exc))
    raise
