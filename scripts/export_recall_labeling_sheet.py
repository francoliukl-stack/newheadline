"""Draw a stratified sample of swept candidates for independent labelling.

The exported sheet deliberately omits each row's sweep verdict and score, and
orders rows by a hash of their URL rather than by stratum, so a labeller cannot
read the sweep's answer off the sheet. Verdicts stay in the pool and are only
rejoined when scoring the labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.candidate_pool import CandidatePoolStore  # noqa: E402
from app.recall_sweep import stratified_sample, stratum_weights  # noqa: E402

DATA = ROOT / "data"
parser = argparse.ArgumentParser()
parser.add_argument("--per-stratum", type=int, default=20)
parser.add_argument("--out", default=str(DATA / "recall-labeling-sheet.json"))
parser.add_argument("--key-out", default=str(DATA / "recall-labeling-key.json"))
args = parser.parse_args()

pool = CandidatePoolStore(DATA / "settings.sqlite3")
scored = [row for row in pool.list_unselected() if row.get("sweep_verdict")]
sample = stratified_sample(scored, per_stratum=args.per_stratum)
weights = stratum_weights(scored)
stratum_of = {row["url"]: name for name, rows in sample.items() for row in rows}
drawn = [row for rows in sample.values() for row in rows]

if not drawn:
    raise SystemExit("no swept candidates available; run scripts/recall_sweep.py first")

# Blind ordering: stable, reproducible, and independent of stratum.
drawn.sort(key=lambda row: hashlib.sha256(str(row["url"]).encode("utf-8")).hexdigest())

sheet = [
    {
        "id": f"RC-{index:03d}",
        "title": row.get("title") or "",
        "url": row.get("url"),
        "source_domain": row.get("source_domain") or "",
        "publish_date": row.get("publish_date") or "",
        "source_lane": row.get("source_lane") or "",
        "search_group": row.get("search_group") or "",
        "label": None,
        "label_reason": "",
    }
    for index, row in enumerate(drawn, start=1)
]
key = {
    "stratum_population": weights,
    "sampled": {
        f"RC-{index:03d}": {
            "url": row.get("url"),
            "sweep_verdict": row.get("sweep_verdict"),
            "sweep_score": row.get("sweep_score"),
            "sweep_reason": row.get("sweep_reason") or "",
            "stratum": stratum_of.get(row.get("url")),
        }
        for index, row in enumerate(drawn, start=1)
    },
}

Path(args.out).write_text(json.dumps({"instructions": "label 为 true 表示这条本应进入 News 供人工审核；false 表示丢弃正确。", "cases": sheet}, ensure_ascii=False, indent=2), encoding="utf-8")
Path(args.key_out).write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
drawn_counts = {name: len(rows) for name, rows in sample.items()}
print(f"exported {len(sheet)} cases to {args.out}; drawn={drawn_counts}; population={weights}")
print(f"sweep answers withheld in {args.key_out}")
