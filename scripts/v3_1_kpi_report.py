"""Print a read-only v3.1 operating KPI snapshot from live DingTalk tables."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.v3_1_metrics import build_v3_1_metrics  # noqa: E402


def main() -> int:
    store = SettingsStore(ROOT / "data" / "settings.sqlite3", SecretStore(ROOT / "data" / "secrets.json"))
    settings = store.load(masked=False)
    ai = settings.dingtalk_ai_table
    required = [ai.event_cases_sheet_id, ai.evidence_bank_sheet_id, ai.claim_ledger_sheet_id, ai.api_usage_sheet_id]
    if not all(required):
        raise RuntimeError("v3.1 Event/Evidence/Claim/API Usage sheets must be configured")
    table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
    report = build_v3_1_metrics(
        news=list_records(settings.dingtalk, ai),
        events=list_records(settings.dingtalk, table(ai.event_cases_sheet_id)),
        evidence=list_records(settings.dingtalk, table(ai.evidence_bank_sheet_id)),
        claims=list_records(settings.dingtalk, table(ai.claim_ledger_sheet_id)),
        usage=list_records(settings.dingtalk, table(ai.api_usage_sheet_id)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
