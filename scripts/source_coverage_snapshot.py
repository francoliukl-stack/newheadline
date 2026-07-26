"""Build a weekly, read-only source coverage snapshot and persist one local artifact."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.detect_sources import default_detect_source_records  # noqa: E402
from app.dingtalk_ai_table import list_records  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.source_coverage_metrics import build_source_coverage_snapshot  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"


def _table(settings, sheet_id: str):
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--freshness-days", type=int, default=7)
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    runs = RunLogStore(DATA / "settings.sqlite3")
    run_id = "" if args.dry_run else runs.start("source_coverage_snapshot", provider="dingtalk_ai_table")
    try:
        news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        entity_id = settings.dingtalk_ai_table.entity_catalog_sheet_id
        if not entity_id:
            raise RuntimeError("Entity Catalog sheet is not configured")
        entities = list_records(settings.dingtalk, _table(settings, entity_id))
        detect_id = settings.dingtalk_ai_table.detect_sources_sheet_id
        detect = (
            list_records(settings.dingtalk, _table(settings, detect_id))
            if detect_id
            else default_detect_source_records(settings)
        )
        fixture = json.loads((ROOT / "evals" / "news_coverage_regression_set.json").read_text(encoding="utf-8"))
        snapshot = build_source_coverage_snapshot(
            news,
            entities,
            detect,
            fixture.get("cases") or [],
            now=datetime.now(ZoneInfo(settings.system.timezone)),
            freshness_days=max(1, args.freshness_days),
        )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        output_path = DATA / "source-coverage-latest.json"
        output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runs.finish(
            run_id,
            "success",
            result_count=snapshot["known_important_recall"]["found"],
            message="weekly source coverage snapshot completed",
            metadata=snapshot,
        )
        return 0
    except Exception as exc:
        if run_id:
            runs.finish(run_id, "failed", message="source coverage snapshot failed", error=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
