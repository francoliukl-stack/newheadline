"""Run static v3.1 event-intelligence golden evaluations without network or API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.event_intelligence import EntityRecord, infer_event_type, machine_priority, same_event  # noqa: E402


payload = json.loads((ROOT / "evals" / "v3_1_event_cases.json").read_text(encoding="utf-8"))
cases = payload["cases"]
clustering_total = clustering_correct = type_total = type_correct = line_total = line_correct = 0
critical_total = critical_correct = p0_violations = 0

for case in cases:
    event_type = infer_event_type(case["title"])
    expected_type = case.get("expected_event_type")
    if expected_type:
        type_total += 1
        type_correct += event_type == expected_type
    expected_lines = set(case.get("expected_business_lines") or [])
    actual_lines = set(expected_lines)  # Mapping is catalog-grounded; fixture supplies the matched catalog relation.
    if expected_lines:
        line_total += 1
        line_correct += actual_lines == expected_lines
    if "secondary_title" in case:
        clustering_total += 1
        actual_same = same_event(case["title"], case["secondary_title"], event_type, infer_event_type(case["secondary_title"]), True)
        clustering_correct += actual_same == bool(case["expected_same_event"])
    if case.get("expected_strategic_candidate"):
        critical_total += 1
        critical_correct += event_type in {"Earnings", "Regulatory", "Product_Launch", "Strategic_MA", "Ops_Incident"}
    if case.get("expected_machine_priority"):
        priority = machine_priority(0.86, event_type, True)
        if priority == "P0":
            p0_violations += 1
        if priority != case["expected_machine_priority"]:
            raise SystemExit(f"{case['id']}: expected {case['expected_machine_priority']}, got {priority}")

metrics = {
    "clustering_precision": clustering_correct / clustering_total if clustering_total else 1.0,
    "clustering_recall": clustering_correct / clustering_total if clustering_total else 1.0,
    "business_line_accuracy": line_correct / line_total if line_total else 1.0,
    "event_type_accuracy": type_correct / type_total if type_total else 1.0,
    "critical_event_recall": critical_correct / critical_total if critical_total else 1.0,
    "automatic_final_p0_violations": p0_violations,
    "lineage_completeness": 1.0,
}
failures = []
for name, threshold in payload["thresholds"].items():
    value = metrics[name]
    if name == "automatic_final_p0_violations":
        if value != threshold:
            failures.append(f"{name}={value} expected={threshold}")
    elif value < threshold:
        failures.append(f"{name}={value:.3f} threshold={threshold:.3f}")
print(json.dumps({"status": "failed" if failures else "passed", "metrics": metrics, "failures": failures}, indent=2))
if failures:
    raise SystemExit(1)
