"""Store interactive Codex search results for the normal INGEST pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)

parser = argparse.ArgumentParser()
parser.add_argument("input", nargs="?", help="JSON file; reads stdin when omitted")
args = parser.parse_args()

raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
payload = json.loads(raw)
records = payload if isinstance(payload, list) else payload.get("records", payload.get("items", []))
if not isinstance(records, list):
    raise ValueError("Codex search payload must be a JSON list or contain records/items")
for record in records:
    if not isinstance(record, dict) or not (record.get("url") or record.get("Link") or record.get("link")):
        raise ValueError("Each Codex search result must include a URL")

target = Path(settings.search_provider.codex_search_cache_path).expanduser()
if not target.is_absolute():
    target = ROOT / target
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(
        {
            "provider": "codex_search",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query": payload.get("query", "interactive Codex search") if isinstance(payload, dict) else "interactive Codex search",
            "records": records,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"stored {len(records)} Codex search results at {target}")
