import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOURCE = (ROOT / "scripts" / "weekly_publish.py").read_text(encoding="utf-8")


class InsightGenerationWiringTests(unittest.TestCase):
    """The article and the report that links it must not come apart."""

    def test_the_article_is_generated_inside_the_publish_run(self):
        self.assertIn("generate_weekly_insight.py", SOURCE)

    def test_generation_runs_before_the_research_queue_is_read(self):
        # Reading the queue first would link last week's document.
        generated_at = SOURCE.index("generate_weekly_insight.py")
        queue_read_at = SOURCE.index("select_manual_research_queue(queue_records")
        self.assertLess(generated_at, queue_read_at)

    def test_a_failed_generation_does_not_block_publication(self):
        # The report degrades to its verified-fact layer rather than failing.
        block = SOURCE[SOURCE.index("insight_step = subprocess.run") : SOURCE.index("if not settings.dingtalk_ai_table.research_queue_sheet_id")]
        self.assertNotIn("raise", block)
        self.assertIn('"success" if insight_ok else "failed"', block)

    def test_the_failure_is_recorded_rather_than_swallowed(self):
        self.assertIn("PUBLISH.insight_article", SOURCE)

    def test_a_dry_run_never_creates_a_document(self):
        self.assertIn("if not args.skip_insight and not args.dry_run:", SOURCE)

    def test_generation_can_be_skipped_explicitly(self):
        self.assertIn('"--skip-insight"', SOURCE)


GEN_SOURCE = (ROOT / "scripts" / "generate_weekly_insight.py").read_text(encoding="utf-8")


class InputFingerprintStampTests(unittest.TestCase):
    """A generated article must not be discarded by the drift check."""

    def test_generation_stamps_the_event_set_it_analysed(self):
        # Without this the report clears the link it just created, because the
        # queue row still carries an older event set.
        self.assertIn("build_research_input_fields(records", GEN_SOURCE)

    def test_the_stamp_is_written_in_the_same_patch_as_the_url(self):
        patch_block = GEN_SOURCE[GEN_SOURCE.index("patch = {") : GEN_SOURCE.index("result = update_records")]
        self.assertIn("Research Document URL", patch_block)
        self.assertIn("build_research_input_fields", patch_block)

    def test_a_stamped_row_passes_the_drift_check(self):
        from app.research_production import build_research_input_fields, research_input_preflight

        records = [{"id": "e1", "fields": {"Event ID": "event-1"}}, {"id": "e2", "fields": {"Event ID": "event-2"}}]
        stamped = build_research_input_fields(records, "2026-08-09T12:00:00+08:00")
        self.assertTrue(research_input_preflight(stamped, records)["matched"])

    def test_a_stale_stamp_still_fails_the_drift_check(self):
        from app.research_production import build_research_input_fields, research_input_preflight

        old = [{"id": "e1", "fields": {"Event ID": "event-1"}}]
        new = [{"id": "e2", "fields": {"Event ID": "event-2"}}]
        stamped = build_research_input_fields(old, "2026-08-09T12:00:00+08:00")
        self.assertFalse(research_input_preflight(stamped, new)["matched"])


if __name__ == "__main__":
    unittest.main()
