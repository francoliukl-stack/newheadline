"""Replay candidate selection over a swept pool and measure what it surfaces.

The pool records every deduplicated candidate from an ingest run and the Recall
Sweep scores them, so a selection policy can be replayed offline against the
same day's real candidates and judged on how many genuinely relevant items it
would have put in front of review. Read-only: touches no DingTalk table, writes
no News.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.candidate_ranking import domain_relevance_priors  # noqa: E402
from app.detect_sources import (  # noqa: E402
    default_detect_source_records,
    select_balanced_candidates,
    trusted_source_domains,
)
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402

DATA = ROOT / "data"
parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=30, help="daily write cap being simulated")
parser.add_argument("--max-per-group", type=int, default=5)
parser.add_argument("--day", default="", help="first_seen_date to replay; defaults to every scored candidate")
parser.add_argument("--priors-from", default="", help="learn domain priors from verdicts on or before this first_seen_date")
parser.add_argument("--backlog-slots", type=int, default=0)
parser.add_argument("--backlog-age", type=int, default=7)
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)
trusted = trusted_source_domains(default_detect_source_records(settings))

conn = sqlite3.connect(DATA / "settings.sqlite3")
query = (
    "select url, title, source_domain, publish_date, source_lane, search_group, sweep_verdict, sweep_score, first_seen_date "
    "from candidate_pool where sweep_verdict is not null"
)
params: list[str] = []
if args.day:
    query += " and first_seen_date = ?"
    params.append(args.day)
rows = list(conn.execute(query, params))
if not rows:
    raise SystemExit(f"no swept candidates for {args.day or 'any day'}; run scripts/recall_sweep.py first")
day = args.day or max(row[8] for row in rows)

candidates = [
    {
        "url": url, "title": title, "source": domain, "published_at": publish_date,
        "source_lane": lane, "search_group": group,
        "_verdict": verdict, "_score": score or 0.0,
    }
    for url, title, domain, publish_date, lane, group, verdict, score, _first_seen in rows
]
relevant_total = sum(1 for c in candidates if c["_verdict"] == "likely_missed")
target = date.fromisoformat(day) - timedelta(days=1)

priors = {}
if args.priors_from:
    prior_rows = list(conn.execute(
        "select source_domain, sweep_verdict from candidate_pool where sweep_verdict is not null and first_seen_date <= ?",
        (args.priors_from,),
    ))
    priors = domain_relevance_priors([{"source_domain": d, "sweep_verdict": v} for d, v in prior_rows])
    print(f"域名先验：来自 first_seen_date <= {args.priors_from} 的判定，覆盖 {len(priors)} 个域名")

selected = select_balanced_candidates(
    candidates, trusted, args.max_per_group, args.limit,
    target_publish_date=target, domain_priors=priors or None,
    backlog_slots=args.backlog_slots, backlog_max_age_days=args.backlog_age,
)
hits = [c for c in selected if c["_verdict"] == "likely_missed"]
lanes: dict[str, int] = {}
for c in selected:
    lanes[c["source_lane"] or "(none)"] = lanes.get(c["source_lane"] or "(none)", 0) + 1

print(f"回放日期: {day}   候选总数: {len(candidates)}   其中判定相关: {relevant_total}")
print(f"选中 {len(selected)} 条，命中相关 {len(hits)} 条 —— 选中项相关率 {len(hits)/max(len(selected),1):.0%}，事件级召回 {len(hits)/max(relevant_total,1):.0%}")
print(f"选中项车道分布: {lanes}")
print("\n命中的相关条目:")
for c in sorted(hits, key=lambda x: -x["_score"]):
    print(f"  [{c['_score']:.2f}] {(c['title'] or '')[:70]}")
missed = sorted([c for c in candidates if c["_verdict"] == "likely_missed" and c not in selected], key=lambda x: -x["_score"])
print(f"\n漏掉的相关条目（前 10 / 共 {len(missed)}）:")
for c in missed[:10]:
    print(f"  [{c['_score']:.2f}] [{c['source_lane']:15}] {(c['title'] or '')[:60]}")
