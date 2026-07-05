"""Generate the release-evaluation checklist table from the canonical JSON."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "evals" / "release_evaluation_set.json"
MARKDOWN_PATH = ROOT / "evals" / "release_evaluation_set.md"
BEGIN = "<!-- BEGIN GENERATED EVAL CHECKLIST -->"
END = "<!-- END GENERATED EVAL CHECKLIST -->"


def render(cases: list[dict[str, object]]) -> str:
    lines = [
        BEGIN,
        "| Case ID | Type | Result | Evidence | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(f"| {case['id']} | {case['type']} |  |  |  |" for case in cases)
    lines.append(END)
    return "\n".join(lines)


def generate(json_path: Path = JSON_PATH, markdown_path: Path = MARKDOWN_PATH) -> bool:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    content = markdown_path.read_text(encoding="utf-8")
    if content.count(BEGIN) != 1 or content.count(END) != 1:
        raise ValueError("release checklist must contain exactly one generated region")
    before, remainder = content.split(BEGIN, 1)
    _, after = remainder.split(END, 1)
    updated = before + render(payload["cases"]) + after
    if updated == content:
        return False
    markdown_path.write_text(updated, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = generate()
    print("generated evaluation checklist" if changed else "evaluation checklist already current")
