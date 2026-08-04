import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.candidate_pool import CandidatePoolStore  # noqa: E402


def candidate(url: str, title: str = "Title", lane: str = "broad_market", publish_date: str = "2026-08-04") -> dict:
    return {
        "title": title,
        "url": url,
        "source": "example.com",
        "published_at": publish_date,
        "source_excerpt": "excerpt",
        "search_query": "q",
        "search_group": "finance_core_watch",
        "source_lane": lane,
        "section": "Finance",
        "search_provider": "brave_search",
    }


class CandidatePoolTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = CandidatePoolStore(Path(self._dir.name) / "pool.sqlite3")

    def tearDown(self):
        self._dir.cleanup()

    def test_records_every_unique_candidate_and_marks_which_were_selected(self):
        unique = [candidate("https://a.com/1"), candidate("https://b.com/2"), candidate("https://c.com/3")]
        stats = self.store.record_daily_candidates(unique, [unique[0]], date(2026, 8, 4))
        self.assertEqual(stats["stored"], 3)
        self.assertEqual(stats["selected"], 1)
        self.assertEqual(stats["unselected"], 2)
        unselected = self.store.list_unselected()
        self.assertEqual({row["url"] for row in unselected}, {"https://b.com/2", "https://c.com/3"})

    def test_same_article_across_days_stays_one_row_and_counts_sightings(self):
        first = self.store.record_daily_candidates([candidate("https://a.com/1")], [], date(2026, 8, 3))
        second = self.store.record_daily_candidates([candidate("https://a.com/1")], [], date(2026, 8, 4))
        self.assertEqual(first["stored"], 1)
        self.assertEqual(second["stored"], 1)
        rows = self.store.list_unselected()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times_seen"], 2)
        self.assertEqual(rows[0]["first_seen_date"], "2026-08-03")
        self.assertEqual(rows[0]["last_seen_date"], "2026-08-04")

    def test_promotion_to_news_is_never_reverted_by_a_later_sighting(self):
        self.store.record_daily_candidates([candidate("https://a.com/1")], [candidate("https://a.com/1")], date(2026, 8, 3))
        self.store.record_daily_candidates([candidate("https://a.com/1")], [], date(2026, 8, 4))
        self.assertEqual(self.store.list_unselected(), [])

    def test_url_variants_of_the_same_article_collapse_to_one_row(self):
        unique = [candidate("https://www.a.com/1?utm_source=x"), candidate("https://a.com/1")]
        stats = self.store.record_daily_candidates(unique, [], date(2026, 8, 4))
        self.assertEqual(stats["stored"], 1)

    def test_prune_drops_rows_last_seen_beyond_the_retention_window(self):
        self.store.record_daily_candidates([candidate("https://old.com/1")], [], date(2026, 5, 1))
        self.store.record_daily_candidates([candidate("https://new.com/1")], [], date(2026, 8, 4))
        removed = self.store.prune(retention_days=90, today=date(2026, 8, 4))
        self.assertEqual(removed, 1)
        self.assertEqual({row["url"] for row in self.store.list_unselected()}, {"https://new.com/1"})

    def test_sweep_verdicts_are_written_back_and_readable_for_ranking(self):
        self.store.record_daily_candidates([candidate("https://a.com/1"), candidate("https://b.com/2")], [], date(2026, 8, 4))
        updated = self.store.apply_sweep_results([
            {"url": "https://a.com/1", "score": 0.82, "verdict": "likely_missed", "reason": "regulatory action on core entity"},
        ])
        self.assertEqual(updated, 1)
        rows = {row["url"]: row for row in self.store.list_unselected()}
        self.assertAlmostEqual(rows["https://a.com/1"]["sweep_score"], 0.82)
        self.assertEqual(rows["https://a.com/1"]["sweep_verdict"], "likely_missed")
        self.assertIsNone(rows["https://b.com/2"]["sweep_score"])

    def test_unselected_listing_is_scoped_to_a_window_and_ordered_by_sweep_score(self):
        self.store.record_daily_candidates(
            [candidate("https://a.com/1"), candidate("https://b.com/2"), candidate("https://c.com/3")],
            [],
            date(2026, 8, 4),
        )
        self.store.record_daily_candidates([candidate("https://old.com/9")], [], date(2026, 6, 1))
        self.store.apply_sweep_results([
            {"url": "https://a.com/1", "score": 0.4, "verdict": "noise"},
            {"url": "https://b.com/2", "score": 0.9, "verdict": "likely_missed"},
        ])
        rows = self.store.list_unselected(since=date(2026, 7, 29))
        self.assertEqual([row["url"] for row in rows][:2], ["https://b.com/2", "https://a.com/1"])
        self.assertNotIn("https://old.com/9", {row["url"] for row in rows})

    def test_recording_is_atomic_so_a_bad_row_cannot_leave_a_partial_day(self):
        unique = [candidate("https://a.com/1"), {"url": None, "title": "broken"}]
        with self.assertRaises(Exception):
            self.store.record_daily_candidates(unique, [], date(2026, 8, 4))
        self.assertEqual(self.store.list_unselected(), [])


if __name__ == "__main__":
    unittest.main()
