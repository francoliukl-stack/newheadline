import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_news_review import learn_review_rules  # noqa: E402
from app.stale_review import (  # noqa: E402
    BULK_DECISION_SOURCE,
    snapshot_rows,
    stale_close_patch,
    stale_pending_news,
)


TODAY = date(2026, 8, 8)


def news(record_id, publish_date, status="待处理", **extra):
    return {"id": record_id, "fields": {"Title": f"t-{record_id}", "Publish Date": publish_date, "Status": status, **extra}}


class StaleSelectionTests(unittest.TestCase):
    def test_selects_pending_news_older_than_the_window(self):
        records = [news("old", "2026-06-01"), news("fresh", "2026-08-07")]
        self.assertEqual([r["id"] for r in stale_pending_news(records, TODAY)], ["old"])

    def test_the_window_boundary_is_kept_not_closed(self):
        records = [news("edge", "2026-08-01"), news("just-over", "2026-07-31")]
        self.assertEqual([r["id"] for r in stale_pending_news(records, TODAY)], ["just-over"])

    def test_records_already_decided_by_a_human_are_never_touched(self):
        records = [news("accepted", "2026-06-01", status="已采纳"), news("rejected", "2026-06-01", status="已拒绝")]
        self.assertEqual(stale_pending_news(records, TODAY), [])

    def test_an_item_with_no_usable_publish_date_is_left_alone(self):
        # Age is the entire basis of the policy, so unknown age cannot be judged by it.
        records = [news("undated", ""), news("garbage", "not-a-date")]
        self.assertEqual(stale_pending_news(records, TODAY), [])

    def test_a_custom_window_is_honoured(self):
        records = [news("a", "2026-07-20")]
        self.assertEqual(stale_pending_news(records, TODAY, max_age_days=30), [])
        self.assertEqual(len(stale_pending_news(records, TODAY, max_age_days=7)), 1)


class StalePatchTests(unittest.TestCase):
    def test_the_patch_records_that_this_was_a_bulk_policy_not_a_review(self):
        patch = stale_close_patch(7, "2026-08-08T10:00:00+08:00")
        self.assertEqual(patch["Status"], "已拒绝")
        self.assertEqual(patch["Review Decision Source"], BULK_DECISION_SOURCE)
        self.assertIn("非逐条判断", patch["Rejection Reason"])

    def test_the_patch_targets_the_configured_status_field(self):
        patch = stale_close_patch(7, "2026-08-08T10:00:00+08:00", status_field="Manual Status")
        self.assertIn("Manual Status", patch)
        self.assertNotIn("Status", patch)

    def test_bulk_closures_never_become_training_data_for_the_rulebook(self):
        patch = stale_close_patch(7, "2026-08-08T10:00:00+08:00")
        closed = [
            {"id": str(i), "fields": {
                "Event Case ID": "event-1", "Status": patch["Status"],
                "Review Decision Source": patch["Review Decision Source"],
            }}
            for i in range(50)
        ]
        events = [{"fields": {"Event ID": "event-1", "Event Type": "Product_Launch", "Business Lines": "Antom"}}]
        self.assertEqual(learn_review_rules(closed, events), [])


class SnapshotTests(unittest.TestCase):
    def test_the_snapshot_captures_what_is_needed_to_restore_each_row(self):
        records = [news("a", "2026-06-01", **{"Review Decision Source": "", "Rejection Reason": ""})]
        rows = snapshot_rows(records)
        self.assertEqual(rows[0]["id"], "a")
        self.assertEqual(rows[0]["previous_status"], "待处理")
        self.assertEqual(rows[0]["publish_date"], "2026-06-01")


if __name__ == "__main__":
    unittest.main()
