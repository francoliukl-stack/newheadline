"""Join labels back onto withheld sweep verdicts and estimate pool-wide miss rate.

Each stratum's labelled miss rate is weighted by that stratum's true population,
so the estimate covers the whole unselected pool rather than only the rows a
labeller happened to see.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
parser = argparse.ArgumentParser()
parser.add_argument("--sheet", default=str(DATA / "recall-labeling-sheet.json"))
parser.add_argument("--key", default=str(DATA / "recall-labeling-key.json"))
args = parser.parse_args()

sheet = json.loads(Path(args.sheet).read_text(encoding="utf-8"))
key = json.loads(Path(args.key).read_text(encoding="utf-8"))
sampled, population = key["sampled"], key["stratum_population"]

cases = {case["id"]: case for case in sheet["cases"]}
unlabelled = [cid for cid, case in cases.items() if case.get("label") is None]
if unlabelled:
    raise SystemExit(f"{len(unlabelled)} cases are still unlabelled: {', '.join(sorted(unlabelled)[:5])}...")

by_stratum: dict[str, dict[str, int]] = {}
for cid, case in cases.items():
    stratum = sampled[cid]["stratum"]
    bucket = by_stratum.setdefault(stratum, {"labelled": 0, "should_enter": 0})
    bucket["labelled"] += 1
    bucket["should_enter"] += 1 if case["label"] else 0

total_population = sum(population.values())
estimated_misses = 0.0
print(f"未选中候选总体：{total_population} 条\n")
print(f"{'层':8} {'总体':>6} {'抽样':>6} {'判为应入 News':>14} {'该层漏报率':>12} {'推算漏报条数':>14}")
for stratum in ("high", "middle", "low"):
    bucket = by_stratum.get(stratum, {"labelled": 0, "should_enter": 0})
    size, labelled, hits = population.get(stratum, 0), bucket["labelled"], bucket["should_enter"]
    rate = hits / labelled if labelled else 0.0
    projected = rate * size
    estimated_misses += projected
    print(f"{stratum:8} {size:>6} {labelled:>6} {hits:>14} {rate:>11.0%} {projected:>13.0f}")

overall = estimated_misses / total_population if total_population else 0.0
print(f"\n全池推算漏报：约 {estimated_misses:.0f} 条 / {total_population} 条未选中候选（{overall:.1%}）")

# Sweep precision on its own top stratum, and what it wrongly discarded.
high = by_stratum.get("high", {"labelled": 0, "should_enter": 0})
low = by_stratum.get("low", {"labelled": 0, "should_enter": 0})
if high["labelled"]:
    print(f"Sweep 在 likely_missed 层的精确率：{high['should_enter']}/{high['labelled']} = {high['should_enter']/high['labelled']:.0%}")
if low["labelled"]:
    print(f"Sweep 在 noise 层的误杀率：{low['should_enter']}/{low['labelled']} = {low['should_enter']/low['labelled']:.0%}")

agree = sum(
    1 for cid, case in cases.items()
    if bool(case["label"]) == (sampled[cid]["sweep_verdict"] == "likely_missed")
)
print(f"标注与 sweep 判定一致率：{agree}/{len(cases)} = {agree/len(cases):.0%}")
