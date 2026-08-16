import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.candidate_ranking import domain_relevance_priors, prior_for, rank_penalty  # noqa: E402
from app.detect_sources import select_balanced_candidates  # noqa: E402


def swept(domain, verdict, count=1):
    return [{"source_domain": domain, "sweep_verdict": verdict} for _ in range(count)]


class DomainPriorTests(unittest.TestCase):
    def test_a_domain_that_repeatedly_produced_noise_scores_negative(self):
        priors = domain_relevance_priors(swept("junk.com", "noise", 4))
        self.assertEqual(priors["junk.com"], -1.0)

    def test_a_domain_that_repeatedly_produced_real_events_scores_positive(self):
        priors = domain_relevance_priors(swept("thepaypers.com", "likely_missed", 3))
        self.assertEqual(priors["thepaypers.com"], 1.0)

    def test_one_unlucky_article_cannot_bury_a_domain(self):
        priors = domain_relevance_priors(swept("newsite.com", "noise", 2))
        self.assertNotIn("newsite.com", priors)

    def test_mixed_history_lands_between_the_extremes(self):
        rows = swept("mixed.com", "likely_missed", 2) + swept("mixed.com", "noise", 2)
        self.assertAlmostEqual(domain_relevance_priors(rows)["mixed.com"], 0.0)

    def test_unswept_rows_are_ignored_rather_than_counted_as_neutral(self):
        rows = swept("a.com", "noise", 3) + [{"source_domain": "a.com", "sweep_verdict": None}] * 10
        self.assertEqual(domain_relevance_priors(rows)["a.com"], -1.0)

    def test_domain_matching_ignores_www_and_scheme(self):
        priors = domain_relevance_priors(swept("example.com", "noise", 3))
        self.assertEqual(prior_for({"source": "https://www.example.com/x"}, priors), -1.0)

    def test_a_subdomain_inherits_its_parents_history_when_it_has_none(self):
        priors = domain_relevance_priors(swept("iheart.com", "noise", 3))
        self.assertEqual(prior_for({"source": "961kiss.iheart.com"}, priors), -1.0)

    def test_an_unknown_domain_is_neutral_not_penalised(self):
        priors = domain_relevance_priors(swept("known.com", "noise", 3))
        self.assertEqual(prior_for({"source": "brand-new.com"}, priors), 0.0)
        self.assertEqual(rank_penalty({"source": "brand-new.com"}, priors), 0.0)


class SelectionWithPriorsTests(unittest.TestCase):
    def records(self):
        # Same lane, same group, same publish date: only the domain differs.
        return [
            {"search_group": "g", "source_lane": "core_entity", "source": "junk.com",
             "url": "https://junk.com/1", "published_at": "2026-08-04"},
            {"search_group": "g", "source_lane": "core_entity", "source": "signal.com",
             "url": "https://signal.com/1", "published_at": "2026-08-04"},
        ]

    def test_without_priors_the_ordering_is_unchanged(self):
        selected = select_balanced_candidates(
            self.records(), set(), max_per_group=2, total_limit=1,
            target_publish_date=date(2026, 8, 4),
        )
        self.assertEqual(selected[0]["source"], "junk.com")

    def test_a_known_noise_domain_sinks_below_a_known_signal_domain(self):
        priors = domain_relevance_priors(swept("junk.com", "noise", 3) + swept("signal.com", "likely_missed", 3))
        selected = select_balanced_candidates(
            self.records(), set(), max_per_group=2, total_limit=1,
            target_publish_date=date(2026, 8, 4), domain_priors=priors,
        )
        self.assertEqual(selected[0]["source"], "signal.com")

    def test_priors_never_outrank_the_previous_day_priority_rule(self):
        records = [
            {"search_group": "g", "source_lane": "core_entity", "source": "signal.com",
             "url": "https://signal.com/old", "published_at": "2026-06-20"},
            {"search_group": "g", "source_lane": "core_entity", "source": "junk.com",
             "url": "https://junk.com/fresh", "published_at": "2026-08-04"},
        ]
        priors = domain_relevance_priors(swept("junk.com", "noise", 5) + swept("signal.com", "likely_missed", 5))
        selected = select_balanced_candidates(
            records, set(), max_per_group=2, total_limit=1,
            target_publish_date=date(2026, 8, 4), domain_priors=priors,
        )
        self.assertEqual(selected[0]["url"], "https://junk.com/fresh")



class BacklogSlotTests(unittest.TestCase):
    def records(self):
        fresh = [
            {"search_group": "g", "source_lane": "core_entity", "source": "noise.com",
             "url": f"https://noise.com/{i}", "published_at": "2026-08-04"}
            for i in range(10)
        ]
        recent = [
            {"search_group": "g", "source_lane": "core_entity", "source": "signal.com",
             "url": "https://signal.com/recent", "published_at": "2026-07-30"},
        ]
        stale = [
            {"search_group": "g", "source_lane": "core_entity", "source": "signal.com",
             "url": "https://signal.com/stale", "published_at": "2026-01-01"},
        ]
        return fresh + recent + stale

    def select(self, **kwargs):
        return select_balanced_candidates(
            self.records(), set(), max_per_group=20, total_limit=5,
            target_publish_date=date(2026, 8, 4), **kwargs,
        )

    def test_without_reserved_slots_only_the_freshest_tier_is_selected(self):
        urls = [row["url"] for row in self.select()]
        self.assertTrue(all("noise.com" in url for url in urls))

    def test_a_reserved_slot_rescues_a_recent_candidate_the_freshness_rule_buried(self):
        urls = [row["url"] for row in self.select(backlog_slots=1)]
        self.assertIn("https://signal.com/recent", urls)

    def test_reserved_slots_do_not_raise_the_daily_cap(self):
        self.assertEqual(len(self.select(backlog_slots=2)), 5)

    def test_genuinely_stale_material_is_still_excluded(self):
        urls = [row["url"] for row in self.select(backlog_slots=3)]
        self.assertNotIn("https://signal.com/stale", urls)

    def test_reserved_slots_are_inert_without_a_target_date(self):
        selected = select_balanced_candidates(
            self.records(), set(), max_per_group=20, total_limit=5, backlog_slots=3,
        )
        self.assertEqual(len(selected), 5)


class StarvedGroupTests(unittest.TestCase):
    """With fewer slots than groups, the cut must fall on the weakest groups.

    Production symptom: the same trailing search groups were selected 0 times
    over a week despite ~60 candidates each, because dict insertion order —
    not quality — decided who got cut.
    """

    def records(self):
        # Four groups, identical except the last-inserted one holds the only
        # candidate from a domain the sweep repeatedly confirmed as signal.
        rows = [
            {"search_group": f"g{index}", "source_lane": "core_entity", "source": "junk.com",
             "url": f"https://junk.com/{index}", "published_at": "2026-08-04"}
            for index in range(3)
        ]
        rows.append(
            {"search_group": "g_last", "source_lane": "core_entity", "source": "signal.com",
             "url": "https://signal.com/1", "published_at": "2026-08-04"}
        )
        return rows

    def test_the_last_inserted_group_is_not_starved_when_it_holds_the_best_candidate(self):
        priors = domain_relevance_priors(
            swept("junk.com", "noise", 3) + swept("signal.com", "likely_missed", 3)
        )
        selected = select_balanced_candidates(
            self.records(), set(), max_per_group=5, total_limit=1,
            target_publish_date=date(2026, 8, 4), domain_priors=priors,
        )
        self.assertEqual([row["source"] for row in selected], ["signal.com"])

    def test_every_group_still_gets_a_slot_when_there_is_room_for_all(self):
        selected = select_balanced_candidates(
            self.records(), set(), max_per_group=5, total_limit=4,
            target_publish_date=date(2026, 8, 4),
        )
        self.assertEqual(len({row["search_group"] for row in selected}), 4)


if __name__ == "__main__":
    unittest.main()
