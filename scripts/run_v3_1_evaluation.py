"""Run static v3.1 event-intelligence golden evaluations without network or API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.event_intelligence import (  # noqa: E402
    catalog_from_records,
    infer_event_type,
    deterministic_impact_hypothesis,
    machine_priority,
    match_entities,
    publication_eligible,
    same_event,
)
from app.event_tables import ENTITY_SEEDS  # noqa: E402


def _seed_catalog():
    rows = []
    for entity_id, name, aliases, _entity_type, lines, ticker, official_url, tier in ENTITY_SEEDS:
        rows.append({"fields": {
            "Entity ID": entity_id,
            "Canonical Name": name,
            "Aliases": aliases,
            "Business Lines": lines,
            "Ticker": ticker,
            "Official URLs": official_url,
            "Watch Tier": tier,
            "Active": "Yes",
        }})
    return catalog_from_records(rows)


def evaluate(payload):
    cases = payload["cases"]
    catalog = _seed_catalog()
    clustering_tp = clustering_fp = clustering_fn = 0
    type_total = type_correct = line_total = line_correct = 0
    critical_total = critical_correct = p0_violations = 0
    impact_total = impact_correct = 0

    for case in cases:
        event_type = infer_event_type(case["title"])
        expected_type = case.get("expected_event_type")
        if expected_type:
            type_total += 1
            type_correct += event_type == expected_type
        expected_lines = set(case.get("expected_business_lines") or [])
        if expected_lines:
            matched = match_entities(case["title"], case.get("source_url", ""), catalog)
            actual_lines = {line for entity in matched for line in entity.business_lines}
            line_total += 1
            line_correct += actual_lines == expected_lines
        if "secondary_title" in case:
            actual_same = same_event(
                case["title"],
                case["secondary_title"],
                event_type,
                infer_event_type(case["secondary_title"]),
                bool(case.get("shared_entity", True)),
            )
            expected_same = bool(case["expected_same_event"])
            clustering_tp += actual_same and expected_same
            clustering_fp += actual_same and not expected_same
            clustering_fn += not actual_same and expected_same
        if case.get("expected_strategic_candidate"):
            critical_total += 1
            critical_correct += event_type in {"Earnings", "Regulatory", "Product_Launch", "Strategic_MA", "Ops_Incident"}
        expected_impact_keywords = case.get("expected_impact_keywords") or []
        if expected_impact_keywords:
            impact_total += 1
            hypothesis = deterministic_impact_hypothesis(event_type, sorted(expected_lines))
            impact_correct += all(keyword.lower() in hypothesis.lower() for keyword in expected_impact_keywords)
        if case.get("expected_machine_priority"):
            priority = machine_priority(0.86, event_type, True)
            p0_violations += priority == "P0"
            if priority != case["expected_machine_priority"]:
                raise ValueError(f"{case['id']}: expected {case['expected_machine_priority']}, got {priority}")

    lineage_cases = payload.get("lineage_cases") or []
    lineage_correct = sum(
        publication_eligible(case["fields"]) == bool(case["expected_publication_eligible"])
        for case in lineage_cases
    )
    precision_denominator = clustering_tp + clustering_fp
    recall_denominator = clustering_tp + clustering_fn
    metrics = {
        "clustering_precision": clustering_tp / precision_denominator if precision_denominator else 1.0,
        "clustering_recall": clustering_tp / recall_denominator if recall_denominator else 1.0,
        "business_line_accuracy": line_correct / line_total if line_total else 1.0,
        "event_type_accuracy": type_correct / type_total if type_total else 1.0,
        "impact_mapping_accuracy": impact_correct / impact_total if impact_total else 1.0,
        "critical_event_recall": critical_correct / critical_total if critical_total else 1.0,
        "automatic_final_p0_violations": p0_violations,
        "lineage_completeness": lineage_correct / len(lineage_cases) if lineage_cases else 0.0,
    }
    failures = []
    for name, threshold in payload["thresholds"].items():
        value = metrics[name]
        if name == "automatic_final_p0_violations":
            if value != threshold:
                failures.append(f"{name}={value} expected={threshold}")
        elif value < threshold:
            failures.append(f"{name}={value:.3f} threshold={threshold:.3f}")
    return {"status": "failed" if failures else "passed", "metrics": metrics, "failures": failures}


def main() -> int:
    payload = json.loads((ROOT / "evals" / "v3_1_event_cases.json").read_text(encoding="utf-8"))
    result = evaluate(payload)
    print(json.dumps(result, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
