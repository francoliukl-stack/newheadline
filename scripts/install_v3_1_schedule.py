"""Install or inspect the v3.1 critical event launchd schedule."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.scheduler import install_critical_scan  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
settings = SettingsStore(ROOT / "data" / "settings.sqlite3", SecretStore(ROOT / "data" / "secrets.json")).load(masked=False)
print(install_critical_scan(
    ROOT,
    str(ROOT / ".venv" / "bin" / "python"),
    settings.event_intelligence.critical_scan_hours,
    settings.event_intelligence.critical_scan_enabled,
    mode="anchor",
    dry_run=not args.apply,
))
print(install_critical_scan(
    ROOT,
    str(ROOT / ".venv" / "bin" / "python"),
    settings.event_intelligence.critical_scan_fast_hours,
    settings.event_intelligence.critical_scan_enabled,
    mode="fast",
    dry_run=not args.apply,
))
