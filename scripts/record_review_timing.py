"""Record one manually timed News review sample in RunLog and Audit Trail."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"


def validate_review_timing(review_date: str, minutes: float, reviewed_count: int, today: date) -> dict:
    try:
        observed_date = date.fromisoformat(review_date)
    except ValueError as exc:
        raise ValueError("review date must be YYYY-MM-DD") from exc
    if observed_date > today:
        raise ValueError("review date cannot be in the future")
    if not 0 < minutes <= 120:
        raise ValueError("minutes must be greater than 0 and at most 120")
    if reviewed_count < 0:
        raise ValueError("reviewed count cannot be negative")
    return {
        "review_date": observed_date.isoformat(),
        "actual_review_minutes": round(float(minutes), 2),
        "reviewed_count": reviewed_count,
        "target_minutes": 10.0,
        "target_status": "met" if minutes <= 10 else "not_met",
        "measurement_mode": "manual_timed_sample",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an actual manually timed News review sample.")
    parser.add_argument("--date", required=True, help="Review date in YYYY-MM-DD.")
    parser.add_argument("--minutes", required=True, type=float, help="Actual elapsed review minutes.")
    parser.add_argument("--reviewed-count", required=True, type=int, help="Number of News rows reviewed.")
    parser.add_argument("--notes", default="", help="Optional short context for the sample.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print without writing evidence.")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    now = datetime.now(ZoneInfo(settings.system.timezone))
    sample = validate_review_timing(args.date, args.minutes, args.reviewed_count, now.date())
    sample["notes"] = args.notes.strip()
    sample["recorded_at"] = now.isoformat(timespec="seconds")
    if args.dry_run:
        print(f"review timing dry-run: {sample}")
        return 0

    runs = RunLogStore(DATA / "settings.sqlite3")
    run_id = runs.start("review_timing_sample", provider="manual")
    audit = AuditTrailWriter(settings, store, runs)
    try:
        message = (
            f"review_date={sample['review_date']}; actual_minutes={sample['actual_review_minutes']}; "
            f"reviewed_count={sample['reviewed_count']}; target_status={sample['target_status']}"
        )
        audit.record(
            run_id=run_id,
            workflow="review_timing_sample",
            stage_code="REVIEW.timing_sample",
            stage_name="Record manually timed News review sample",
            status="success",
            mode="live",
            output_summary=message,
            result_count=args.reviewed_count,
            related_sheet=settings.dingtalk_ai_table.sheet_id,
            metadata=sample,
        )
        runs.finish(run_id, "success", result_count=args.reviewed_count, message=message, metadata=sample)
        print(f"review timing recorded: {message}")
        return 0
    except Exception as exc:
        runs.finish(run_id, "failed", message="review timing sample failed", error=str(exc), metadata=sample)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
