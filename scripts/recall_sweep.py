"""Score unselected candidate-pool rows so misses can be surfaced and ranked.

Proposes only. Never writes News, never changes any review status: `News=已采纳`
remains the sole publication gate (INV-03).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.candidate_pool import CandidatePoolStore  # noqa: E402
from app.llm_carrier import ALL_CARRIERS, CarrierUnavailable, run_prompt  # noqa: E402
from app.recall_sweep import batched, build_sweep_prompt, parse_sweep_response  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402

DATA = ROOT / "data"
parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=7, help="only sweep candidates last seen within this window")
parser.add_argument("--batch-size", type=int, default=40)
parser.add_argument("--limit", type=int, default=0, help="0 means sweep every eligible candidate")
parser.add_argument("--carriers", default=",".join(ALL_CARRIERS))
parser.add_argument("--dry-run", action="store_true", help="build prompts and report counts without calling a carrier")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
pool = CandidatePoolStore(DATA / "settings.sqlite3")

now = datetime.now(ZoneInfo(settings.system.timezone))
since = now.date() - timedelta(days=max(args.days - 1, 0))
candidates = pool.list_unselected(since=since, limit=args.limit or None)

run_id = run_logs.start("recall_sweep", provider="subscription_carrier", metadata={"since": since.isoformat(), "eligible": len(candidates)})
print(f"recall_sweep: {len(candidates)} unselected candidates last seen since {since}")

if args.dry_run:
    batches = list(batched(candidates, args.batch_size))
    run_logs.finish(run_id, "success", result_count=len(candidates), message=f"dry-run: {len(candidates)} candidates in {len(batches)} batches")
    print(f"recall_sweep dry-run: {len(batches)} batches; first prompt is {len(build_sweep_prompt(batches[0])) if batches else 0} chars")
    raise SystemExit(0)

carriers = tuple(name.strip() for name in args.carriers.split(",") if name.strip())
scored, attempts_log, failed_batches = [], [], 0
try:
    for index, batch in enumerate(batched(candidates, args.batch_size), start=1):
        try:
            response = run_prompt(build_sweep_prompt(batch), carriers=carriers)
        except CarrierUnavailable as exc:
            failed_batches += 1
            print(f"  batch {index}: no carrier available: {exc}")
            continue
        parsed = parse_sweep_response(response.text, batch)
        attempts_log.append({"batch": index, "size": len(batch), "parsed": len(parsed), **response.as_metadata()})
        if len(parsed) < len(batch):
            # Under-reporting is safe (unscored rows keep a null score) but must stay visible.
            print(f"  batch {index}: carrier returned {len(parsed)}/{len(batch)} verdicts via {response.carrier}")
        else:
            print(f"  batch {index}: {len(parsed)}/{len(batch)} via {response.carrier}")
        scored.extend(parsed)

    updated = pool.apply_sweep_results(scored, swept_at=now.isoformat(timespec="seconds"))
    verdict_counts = {}
    for row in scored:
        verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1
    message = f"scored {len(scored)}/{len(candidates)} candidates; written={updated}; verdicts={verdict_counts}; failed_batches={failed_batches}"
    run_logs.finish(
        run_id,
        "degraded" if failed_batches else "success",
        result_count=len(scored),
        message=message,
        metadata={"verdicts": verdict_counts, "carrier_attempts": attempts_log, "failed_batches": failed_batches},
    )
    print(f"recall_sweep success: {message}")
except Exception as exc:
    run_logs.finish(run_id, "failed", result_count=len(scored), message="recall sweep failed", error=str(exc))
    raise
