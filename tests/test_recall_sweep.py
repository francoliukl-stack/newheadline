import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.recall_sweep import (  # noqa: E402
    batched,
    build_sweep_prompt,
    parse_sweep_response,
    stratified_sample,
    stratum_weights,
)


CANDIDATES = [
    {"url": "https://a.com/1", "title": "HKMA issues new stored value facility rules", "source_domain": "hkma.gov.hk", "publish_date": "2026-08-04", "source_lane": "core_entity"},
    {"url": "https://b.com/2", "title": "Whippin My Bettis Bass Around", "source_domain": "961kiss.iheart.com", "publish_date": "2026-08-04", "source_lane": "core_entity"},
]


class SweepPromptTests(unittest.TestCase):
    def test_prompt_carries_the_documented_business_scope_not_a_paraphrase(self):
        prompt = build_sweep_prompt(CANDIDATES)
        for entity in ("Alipay+", "WorldFirst", "Bettr", "Antom", "AlipayHK", "HKMA", "Adyen", "Genesys"):
            self.assertIn(entity, prompt)

    def test_prompt_numbers_every_candidate_and_demands_one_verdict_each(self):
        prompt = build_sweep_prompt(CANDIDATES)
        self.assertIn("1. title: HKMA issues new stored value facility rules", prompt)
        self.assertIn("2. title: Whippin My Bettis Bass Around", prompt)
        self.assertIn("必须为上面每一条候选各输出一个元素", prompt)


class SweepParsingTests(unittest.TestCase):
    def test_maps_verdicts_back_onto_candidate_urls(self):
        text = '[{"n":1,"verdict":"likely_missed","score":0.9,"reason":"regulatory"},{"n":2,"verdict":"noise","score":0.02,"reason":"entity mismatch"}]'
        results = parse_sweep_response(text, CANDIDATES)
        self.assertEqual([r["url"] for r in results], ["https://a.com/1", "https://b.com/2"])
        self.assertEqual(results[0]["verdict"], "likely_missed")
        self.assertAlmostEqual(results[1]["score"], 0.02)

    def test_tolerates_a_fenced_code_block_and_surrounding_chatter(self):
        text = 'Here you go:\n```json\n[{"n":1,"verdict":"noise","score":0.1}]\n```\nHope that helps!'
        self.assertEqual(len(parse_sweep_response(text, CANDIDATES)), 1)

    def test_drops_rows_it_cannot_trust_rather_than_guessing(self):
        text = (
            '[{"n":1,"verdict":"definitely","score":0.9},'          # invalid verdict
            '{"n":99,"verdict":"noise","score":0.1},'               # out of range
            '{"n":2,"verdict":"noise","score":"high"},'             # unparseable score
            '{"verdict":"noise","score":0.1}]'                      # missing index
        )
        self.assertEqual(parse_sweep_response(text, CANDIDATES), [])

    def test_ignores_a_repeated_index_instead_of_double_counting(self):
        text = '[{"n":1,"verdict":"noise","score":0.1},{"n":1,"verdict":"likely_missed","score":0.9}]'
        results = parse_sweep_response(text, CANDIDATES)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "noise")

    def test_unparseable_output_yields_nothing_rather_than_raising(self):
        self.assertEqual(parse_sweep_response("the model refused", CANDIDATES), [])
        self.assertEqual(parse_sweep_response("", CANDIDATES), [])

    def test_scores_are_clamped_into_range(self):
        text = '[{"n":1,"verdict":"likely_missed","score":4.2},{"n":2,"verdict":"noise","score":-1}]'
        results = parse_sweep_response(text, CANDIDATES)
        self.assertEqual([r["score"] for r in results], [1.0, 0.0])


class StratifiedSampleTests(unittest.TestCase):
    def rows(self):
        return [
            {"url": "h1", "sweep_verdict": "likely_missed", "sweep_score": 0.9},
            {"url": "h2", "sweep_verdict": "likely_missed", "sweep_score": 0.7},
            {"url": "b1", "sweep_verdict": "borderline", "sweep_score": 0.5},
            {"url": "n1", "sweep_verdict": "noise", "sweep_score": 0.2},
            {"url": "n2", "sweep_verdict": "noise", "sweep_score": 0.05},
        ]

    def test_every_verdict_gets_a_stratum_so_the_whole_pool_is_estimable(self):
        sample = stratified_sample(self.rows(), per_stratum=5)
        self.assertEqual(set(sample), {"high", "middle", "low"})
        self.assertEqual([r["url"] for r in sample["middle"]], ["b1"])
        drawn = {r["url"] for rows in sample.values() for r in rows}
        self.assertEqual(drawn, {"h1", "h2", "b1", "n1", "n2"})

    def test_draws_across_a_stratum_rather_than_only_its_top(self):
        members = [{"url": f"n{i}", "sweep_verdict": "noise", "sweep_score": 1 - i / 100} for i in range(100)]
        sample = stratified_sample(members, per_stratum=4)
        self.assertEqual([r["url"] for r in sample["low"]], ["n0", "n25", "n50", "n75"])

    def test_sampling_is_deterministic_so_the_drawn_set_is_reproducible(self):
        first = stratified_sample(self.rows(), per_stratum=2)
        second = stratified_sample(list(reversed(self.rows())), per_stratum=2)
        for name in ("high", "middle", "low"):
            self.assertEqual([r["url"] for r in first[name]], [r["url"] for r in second[name]])

    def test_a_short_stratum_is_returned_short_rather_than_padded(self):
        sample = stratified_sample(self.rows(), per_stratum=10)
        self.assertEqual(len(sample["high"]), 2)
        self.assertEqual(len(sample["middle"]), 1)
        self.assertEqual(len(sample["low"]), 2)

    def test_stratum_weights_report_true_population_sizes_for_reweighting(self):
        self.assertEqual(stratum_weights(self.rows()), {"high": 2, "middle": 1, "low": 2})


class BatchingTests(unittest.TestCase):
    def test_batches_cover_every_item_exactly_once(self):
        items = [{"url": str(i)} for i in range(7)]
        batches = list(batched(items, 3))
        self.assertEqual([len(b) for b in batches], [3, 3, 1])
        self.assertEqual([r["url"] for b in batches for r in b], [str(i) for i in range(7)])


if __name__ == "__main__":
    unittest.main()
