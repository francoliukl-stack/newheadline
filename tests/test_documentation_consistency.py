from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from scripts.generate_eval_checklist import BEGIN, END, render


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "v3_1_event_intelligence_spec.md"
EVAL_JSON = ROOT / "evals" / "release_evaluation_set.json"
EVAL_MD = ROOT / "evals" / "release_evaluation_set.md"
METADATA_FIELDS = ("Version", "Last-Updated", "Status", "Supersedes")


class DocumentationConsistencyTests(unittest.TestCase):
    def test_eval_requirement_references_exist_in_spec(self):
        spec = SPEC.read_text(encoding="utf-8")
        known = set(re.findall(r"(?:REQ-\d{3}|INV-\d{2})", spec))
        payload = json.loads(EVAL_JSON.read_text(encoding="utf-8"))
        self.assertTrue(known)
        for case in payload["cases"]:
            requirements = case.get("requirements") or []
            self.assertTrue(requirements, case["id"])
            self.assertEqual(set(requirements) - known, set(), case["id"])

    def test_generated_checklist_matches_json_cases_and_types(self):
        payload = json.loads(EVAL_JSON.read_text(encoding="utf-8"))
        content = EVAL_MD.read_text(encoding="utf-8")
        generated = BEGIN + content.split(BEGIN, 1)[1].split(END, 1)[0] + END
        self.assertEqual(generated, render(payload["cases"]))

    def test_project_documents_have_complete_metadata(self):
        documents = sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "evals").glob("*.md"))
        self.assertTrue(documents)
        for path in documents:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:15])
            for field in METADATA_FIELDS:
                self.assertRegex(head, rf"(?m)^> {field}:\s*\S+", f"{path}: missing {field}")
            self.assertRegex(head, r"(?m)^> Status: (?:active|superseded)$", str(path))

    def test_root_markdown_is_readme_only(self):
        markdown = sorted(path.name for path in ROOT.glob("*.md"))
        self.assertEqual(markdown, ["AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md"])

    def test_retired_document_paths_are_not_referenced(self):
        retired = (
            "GBSS_Intelligence_PRD_v3_1_Codex_" + "OpenAI.md",
            "prd" + ".md",
            "prd" + ".html",
        )
        paths = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "evals").glob("*"))]
        for path in paths:
            if not path.is_file() or path.suffix not in {".md", ".json"}:
                continue
            text = path.read_text(encoding="utf-8")
            for value in retired:
                self.assertNotIn(value, text, f"{path}: stale reference {value}")


if __name__ == "__main__":
    unittest.main()
