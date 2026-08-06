import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_news_review import (  # noqa: E402
    AI_ACCEPT,
    AI_DUPLICATE,
    AI_REJECT,
    SWEEP_RESCUE_MAX_CONFIDENCE,
    deadline_fields,
    recommend_news,
)


NEWS = {"Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-08-04", "Event Case ID": "event-1"}
# An Event the base rules reject: no business line, type still General.
WEAK_EVENT = {"Event Type": "General", "Business Lines": "", "Relevance Score": "0.30"}
STRONG_EVENT = {"Event Type": "Regulatory", "Business Lines": "AlipayHK", "Relevance Score": "0.90"}


class SweepSecondOpinionTests(unittest.TestCase):
    def test_without_a_sweep_score_the_recommendation_is_unchanged(self):
        self.assertEqual(recommend_news(NEWS, WEAK_EVENT).status, AI_REJECT)

    def test_a_strong_sweep_score_turns_a_rejection_into_a_suggestion(self):
        result = recommend_news(NEWS, WEAK_EVENT, sweep_score=0.88)
        self.assertEqual(result.status, AI_ACCEPT)
        self.assertIn("Recall Sweep", result.reason)

    def test_a_rescued_item_can_never_auto_accept_itself(self):
        result = recommend_news(NEWS, WEAK_EVENT, sweep_score=0.95)
        self.assertLessEqual(result.confidence, SWEEP_RESCUE_MAX_CONFIDENCE)
        self.assertLess(result.confidence, 0.85)
        patch = deadline_fields(
            {**NEWS, "AI Status": result.status, "AI Confidence": f"{result.confidence:.2f}", "Status": "待处理"},
            {**WEAK_EVENT, "Event Type": "Regulatory", "Business Lines": "AlipayHK"},
            "2026-08-05T11:50:00+08:00",
        )
        self.assertEqual(patch, {})

    def test_a_weak_sweep_score_does_not_overturn_a_rejection(self):
        self.assertEqual(recommend_news(NEWS, WEAK_EVENT, sweep_score=0.60).status, AI_REJECT)

    def test_the_sweep_never_turns_an_acceptance_into_a_rejection(self):
        baseline = recommend_news(NEWS, STRONG_EVENT)
        self.assertEqual(baseline.status, AI_ACCEPT)
        rescued = recommend_news(NEWS, STRONG_EVENT, sweep_score=0.01)
        self.assertEqual(rescued.status, AI_ACCEPT)
        self.assertEqual(rescued.confidence, baseline.confidence)

    def test_hard_gates_stay_stronger_than_any_sweep_score(self):
        duplicate = recommend_news({**NEWS, "Duplicate Of": "rec-9"}, STRONG_EVENT, sweep_score=0.99)
        self.assertEqual(duplicate.status, AI_DUPLICATE)
        missing_url = recommend_news({**NEWS, "Source URL": ""}, STRONG_EVENT, sweep_score=0.99)
        self.assertEqual(missing_url.status, AI_REJECT)
        missing_date = recommend_news({**NEWS, "Publish Date": ""}, STRONG_EVENT, sweep_score=0.99)
        self.assertEqual(missing_date.status, AI_REJECT)

    def test_an_untraceable_item_is_not_rescued_either(self):
        untraceable = recommend_news({**NEWS, "Event Case ID": ""}, None, sweep_score=0.99)
        self.assertEqual(untraceable.status, AI_REJECT)


class FingerprintStabilityTests(unittest.TestCase):
    """Introducing the sweep must not churn records that have no verdict."""

    def test_a_record_without_a_verdict_keeps_its_existing_fingerprint(self):
        from app.ai_news_review import review_fingerprint

        self.assertEqual(
            review_fingerprint(NEWS, STRONG_EVENT),
            review_fingerprint(NEWS, STRONG_EVENT, sweep_score=None),
        )

    def test_a_record_with_a_verdict_gets_a_new_fingerprint(self):
        from app.ai_news_review import review_fingerprint

        self.assertNotEqual(
            review_fingerprint(NEWS, STRONG_EVENT),
            review_fingerprint(NEWS, STRONG_EVENT, sweep_score=0.9),
        )

    def test_a_changed_verdict_invalidates_the_cached_recommendation(self):
        from app.ai_news_review import review_fingerprint

        self.assertNotEqual(
            review_fingerprint(NEWS, STRONG_EVENT, sweep_score=0.80),
            review_fingerprint(NEWS, STRONG_EVENT, sweep_score=0.90),
        )


if __name__ == "__main__":
    unittest.main()
