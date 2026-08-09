import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.weekly_insight_article import (  # noqa: E402
    article_title,
    build_article_prompt,
    event_digest,
    validate_article,
)


RECORDS = [
    {"id": "e1", "fields": {
        "Title": "Mastercard completes BVNK acquisition", "Label": "Strategic_MA",
        "Section": "Antom", "Publish Date": "2026-08-04",
        "Source URL": {"link": "https://example.com/bvnk"},
    }},
    {"id": "e2", "fields": {
        "Title": "HKMA shuts down stablecoin licence speculation", "Label": "Regulatory",
        "Section": "HK_Fintech", "Publish Date": "2026-08-06",
        "Source URL": "https://example.com/hkma",
    }},
]


class PromptTests(unittest.TestCase):
    def test_the_prompt_supplies_every_event_with_its_source(self):
        prompt = build_article_prompt(RECORDS, "AUG 03 - AUG 09")
        for fragment in ("Mastercard completes BVNK acquisition", "https://example.com/bvnk", "https://example.com/hkma"):
            self.assertIn(fragment, prompt)

    def test_the_prompt_forbids_facts_outside_the_supplied_events(self):
        prompt = build_article_prompt(RECORDS, "AUG 03 - AUG 09")
        self.assertIn("唯一可用的事实来源", prompt)
        self.assertIn("禁止引入列表之外的事实", prompt)

    def test_the_prompt_requires_inference_to_be_labelled_as_inference(self):
        prompt = build_article_prompt(RECORDS, "AUG 03 - AUG 09")
        self.assertIn("区分事实与判断", prompt)
        self.assertIn("什么条件下会不成立", prompt)

    def test_the_prompt_refuses_to_manufacture_recommendations(self):
        prompt = build_article_prompt(RECORDS, "AUG 03 - AUG 09")
        self.assertIn("不要凑", prompt)

    def test_the_digest_handles_both_link_object_and_plain_url_fields(self):
        lines = "\n".join(event_digest(RECORDS))
        self.assertIn("https://example.com/bvnk", lines)
        self.assertIn("https://example.com/hkma", lines)


class ValidationTests(unittest.TestCase):
    def good_article(self):
        return (
            "# GBSS Weekly Insight — AUG 03 - AUG 09\n\n## 本周主线\n"
            + "Mastercard 完成对 BVNK 的收购（[来源](https://example.com/bvnk)）。" * 12
        )

    def test_a_well_formed_article_passes(self):
        self.assertEqual(validate_article(self.good_article(), RECORDS), [])

    def test_an_article_citing_none_of_the_events_is_rejected(self):
        text = "# GBSS Weekly Insight\n\n" + "本周支付行业发生了一些变化。" * 40
        self.assertIn("article cites none of the supplied event sources", validate_article(text, RECORDS))

    def test_a_stub_answer_is_rejected_rather_than_published(self):
        errors = validate_article("好的，我明白了。", RECORDS)
        self.assertTrue(any("too short" in error for error in errors))

    def test_an_article_without_a_heading_is_rejected(self):
        text = "本周主线：" + "Mastercard 收购 BVNK（https://example.com/bvnk）。" * 20
        self.assertIn("article does not start with a markdown heading", validate_article(text, RECORDS))

    def test_an_empty_answer_is_rejected(self):
        self.assertTrue(validate_article("", RECORDS))


class TitleTests(unittest.TestCase):
    def test_the_title_carries_the_period_so_documents_stay_distinguishable(self):
        self.assertEqual(article_title("AUG 03 - AUG 09"), "GBSS Weekly Insight - AUG 03 - AUG 09")


class QueueLinkFormatTests(unittest.TestCase):
    def test_the_research_document_url_is_written_as_a_link_cell(self):
        # DingTalk rejects a plain string for this field with HTTP 400.
        from app.research_production import extract_research_document_url

        source = Path(ROOT / "scripts" / "generate_weekly_insight.py").read_text(encoding="utf-8")
        self.assertIn('"Research Document URL": {"text": document.title, "link": document.url}', source)
        cell = {"text": "GBSS Weekly Insight - AUG 03 - AUG 09", "link": "https://alidocs.dingtalk.com/i/nodes/abc"}
        self.assertEqual(extract_research_document_url(cell), "https://alidocs.dingtalk.com/i/nodes/abc")


if __name__ == "__main__":
    unittest.main()
