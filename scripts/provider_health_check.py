"""Check configured search providers and alert when any provider is invalid."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.notifications import send_dingtalk_webhook_text  # noqa: E402
from app.provider_health import check_configured_providers  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start("provider_health_check", provider=settings.search_provider.provider)

results = check_configured_providers(settings.search_provider)
# Supplemental recall providers (e.g. gdelt_doc) are flaky by nature; their
# outages go to RunLog only and must not page the ops group or fail ingest.
invalid = [result for result in results if not result.ok and result.role != "supplemental"]
lines = [
    f"{'OK' if result.ok else 'INVALID'}: {result.provider} ({result.role}) - {result.message}"
    for result in results
]
status = "success" if any(result.ok for result in results if result.role != "supplemental") else "failed"
message = "; ".join(lines)

if invalid:
    send_dingtalk_webhook_text(
        settings.dingtalk.daily_webhook_url,
        settings.dingtalk.daily_signing_secret,
        "【Search Provider 告警】\n" + "\n".join(lines),
        settings.dingtalk.at_mobiles,
    )

run_logs.finish(
    run_id,
    status,
    result_count=sum(result.result_count for result in results if result.ok),
    message=message,
    metadata={"providers": [result.__dict__ for result in results]},
)
print(message)
if status == "failed":
    raise SystemExit(1)
