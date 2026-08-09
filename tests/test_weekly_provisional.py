import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.event_weekly import PROVISIONAL_DECISION_SOURCE, operator_reviewed_window, provisional_news_by_id  # noqa: E402
from app.publish_format import (  # noqa: E402
    AI_DEADLINE_NOTE,
    AI_MIXED_UNCONFIRMED_NOTE,
    AI_PROVISIONAL_NOTE,
    NOTE,
    build_headlines_content,
    unconfirmed_disclosure_note,
)


def news(record_id, manual_status, ai_status):
    return {"id": record_id, "fields": {"Manual Status": manual_status, "AI Status": ai_status, "Title": f"t-{record_id}"}}


class ProvisionalSelectionTests(unittest.TestCase):
    def test_selects_ai_accepted_news_a_human_has_not_ruled_on(self):
        rows = [news("a", "待处理", "已采纳")]
        self.assertEqual(list(provisional_news_by_id(rows, True)), ["a"])

    def test_ai_rejected_items_are_never_promoted_into_the_report(self):
        # "Everything unreviewed" would refill the report with filtered-out noise.
        rows = [news("r", "待处理", "已拒绝"), news("d", "待处理", "已重复")]
        self.assertEqual(provisional_news_by_id(rows, True), {})

    def test_items_a_human_already_decided_are_not_provisional(self):
        rows = [news("acc", "已采纳", "已采纳"), news("rej", "已拒绝", "已采纳")]
        self.assertEqual(provisional_news_by_id(rows, True), {})

    def test_the_flag_switches_the_whole_behaviour_off(self):
        rows = [news("a", "待处理", "已采纳")]
        self.assertEqual(provisional_news_by_id(rows, False), {})

    def test_selection_reads_but_never_writes_the_news_row(self):
        rows = [news("a", "待处理", "已采纳")]
        before = {k: dict(v) for k, v in [(r["id"], r["fields"]) for r in rows]}
        provisional_news_by_id(rows, True)
        self.assertEqual({r["id"]: r["fields"] for r in rows}, before)
        self.assertEqual(rows[0]["fields"]["Manual Status"], "待处理")


class DisclosureTests(unittest.TestCase):
    def record(self, sources):
        return {"id": "e", "fields": {
            "Title": "Event", "Section": "Antom", "Label": "Regulatory",
            "Source URL": {"link": "https://example.com"}, "Publish Date": "2026-08-04",
            "Review Decision Sources": sources,
        }}

    def test_a_fully_approved_report_keeps_the_ordinary_note(self):
        self.assertEqual(unconfirmed_disclosure_note([self.record("Human")]), NOTE)

    def test_a_provisional_item_is_disclosed_as_awaiting_review(self):
        note = unconfirmed_disclosure_note([self.record(PROVISIONAL_DECISION_SOURCE)])
        self.assertEqual(note, AI_PROVISIONAL_NOTE)
        self.assertIn("not individually approved", note)
        self.assertIn("awaiting individual review", note)

    def test_the_existing_deadline_wording_is_not_weakened(self):
        note = unconfirmed_disclosure_note([self.record("AI_Deadline_Recovery")])
        self.assertEqual(note, AI_DEADLINE_NOTE)
        self.assertIn("deadline-fallback", note)

    def test_a_report_carrying_both_kinds_names_both(self):
        note = unconfirmed_disclosure_note([self.record("AI_Deadline_Recovery"), self.record(PROVISIONAL_DECISION_SOURCE)])
        self.assertEqual(note, AI_MIXED_UNCONFIRMED_NOTE)
        self.assertIn("deadline-fallback", note)
        self.assertIn("awaiting individual review", note)

    def test_the_rendered_report_never_claims_manual_verification_for_provisional_items(self):
        content = build_headlines_content([self.record(PROVISIONAL_DECISION_SOURCE)], "Weekly", "AUG 02 - AUG 08")
        self.assertIn("not individually approved", content)
        self.assertNotIn("merged with manual verification", content)


class OperatorInterventionTests(unittest.TestCase):
    """"Defaults through if I did not intervene" -- so intervention switches it off."""

    START = datetime(2026, 8, 3, tzinfo=timezone.utc)
    END = datetime(2026, 8, 9, tzinfo=timezone.utc)

    def row(self, source, publish_date="2026-08-05"):
        return {"id": "n", "fields": {"Review Decision Source": source, "Publish Date": publish_date}}

    def test_a_week_the_operator_never_touched_counts_as_no_intervention(self):
        rows = [self.row(""), self.row("AI_Deadline")]
        self.assertFalse(operator_reviewed_window(rows, self.START, self.END))

    def test_one_human_decision_in_the_window_counts_as_intervention(self):
        self.assertTrue(operator_reviewed_window([self.row("Human")], self.START, self.END))
        self.assertTrue(operator_reviewed_window([self.row("Human_Override")], self.START, self.END))

    def test_a_human_decision_outside_the_window_does_not_count(self):
        rows = [self.row("Human", publish_date="2026-06-01")]
        self.assertFalse(operator_reviewed_window(rows, self.START, self.END))

    def test_a_bulk_stale_closure_is_not_intervention_on_this_week(self):
        rows = [self.row("Human_Bulk_Stale_Close")]
        self.assertFalse(operator_reviewed_window(rows, self.START, self.END))


if __name__ == "__main__":
    unittest.main()
