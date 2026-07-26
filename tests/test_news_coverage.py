from __future__ import annotations

import unittest

from app.coverage_audit import build_coverage_audit
from app.editorial_intake import plan_editorial_intake


class NewsCoverageTests(unittest.TestCase):
    def test_editorial_approval_creates_human_accepted_traceable_record(self):
        plan = plan_editorial_intake(
            [{
                "url": "https://example.com/news/?utm_source=test#section",
                "title": "Visa and Example join forces on payment infrastructure",
                "publish_date": "2026-07-21",
                "section": "Finance",
                "source_excerpt": "Official announcement.",
            }],
            [],
            approve=True,
            reason="User explicitly requested Daily/Weekly/Insight inclusion",
            now="2026-07-26T10:00:00+08:00",
            status_field="Manual Status",
        )
        self.assertEqual(plan["counts"], {"created": 1, "updated": 0, "duplicate": 0, "blocked": 0})
        fields = plan["creates"][0]
        self.assertEqual(fields["Source URL"]["link"], "https://example.com/news")
        self.assertEqual(fields["Manual Status"], "已采纳")
        self.assertEqual(fields["Search Provider"], "editorial_input")
        self.assertEqual(fields["Discovery Type"], "editorial_must_include")
        self.assertEqual(fields["Source Lane"], "editorial")
        self.assertEqual(fields["Review Decision Source"], "Human")
        self.assertEqual(fields["Editorial Approved At"], "2026-07-26T10:00:00+08:00")

    def test_editorial_non_approval_stays_pending(self):
        plan = plan_editorial_intake(
            [{"url": "https://example.com/news", "title": "A useful signal", "publish_date": "2026-07-21"}],
            [],
            approve=False,
            reason="Evaluate only",
            now="2026-07-26T10:00:00+08:00",
        )
        fields = plan["creates"][0]
        self.assertEqual(fields["Review Status"], "待处理")
        self.assertNotIn("Editorial Approved At", fields)
        self.assertNotIn("Review Decision Source", fields)

    def test_editorial_update_preserves_human_title_and_excerpt(self):
        existing = [{
            "id": "news-1",
            "fields": {
                "Title": "Human-edited title",
                "Source URL": {"link": "https://example.com/news"},
                "Source Excerpt": "Human-written excerpt",
                "Manual Status": "待处理",
            },
        }]
        plan = plan_editorial_intake(
            [{
                "url": "https://example.com/news?utm_campaign=test",
                "title": "Fetched title",
                "publish_date": "2026-07-21",
                "section": "Finance",
                "source_excerpt": "Fetched excerpt",
            }],
            existing,
            approve=True,
            reason="Explicit inclusion",
            now="2026-07-26T10:00:00+08:00",
            status_field="Manual Status",
        )
        self.assertEqual(plan["counts"], {"created": 0, "updated": 1, "duplicate": 1, "blocked": 0})
        patch = plan["updates"][0]["fields"]
        self.assertNotIn("Title", patch)
        self.assertNotIn("Source Excerpt", patch)
        self.assertEqual(patch["Publish Date"], "2026-07-21")
        self.assertEqual(patch["Manual Status"], "已采纳")
        self.assertEqual(patch["Review Decision Source"], "Human")

    def test_editorial_hard_gates_invalid_url_and_missing_date(self):
        plan = plan_editorial_intake(
            [
                {"url": "not-a-url", "title": "Invalid", "publish_date": "2026-07-21"},
                {"url": "https://example.com/no-date", "title": "Missing date"},
            ],
            [],
            approve=True,
            reason="Explicit inclusion",
            now="2026-07-26T10:00:00+08:00",
        )
        self.assertEqual(plan["counts"]["blocked"], 2)
        self.assertEqual([row["reason"] for row in plan["results"]], ["invalid_url", "missing_publish_date"])

    def test_coverage_audit_reports_stable_block_reasons_and_eligibility(self):
        targets = [
            {"url": "https://example.com/missing"},
            {"url": "https://example.com/quota"},
            {"url": "https://example.com/no-entity"},
            {"url": "https://example.com/general"},
            {"url": "https://example.com/pending"},
            {"url": "https://example.com/eligible"},
        ]
        news = [
            {"id": "no-entity", "fields": {"Source URL": {"link": "https://example.com/no-entity"}, "Publish Date": "2026-07-21", "Manual Status": "已采纳"}},
            {"id": "general", "fields": {"Source URL": {"link": "https://example.com/general"}, "Publish Date": "2026-07-21", "Manual Status": "已采纳", "Event Case ID": "event-general"}},
            {"id": "pending", "fields": {"Source URL": {"link": "https://example.com/pending"}, "Publish Date": "2026-07-21", "Manual Status": "待处理", "Event Case ID": "event-product"}},
            {"id": "eligible", "fields": {"Source URL": {"link": "https://example.com/eligible"}, "Publish Date": "2026-07-21", "Manual Status": "已采纳", "AI Status": "已采纳", "Event Case ID": "event-product"}},
        ]
        events = [
            {"fields": {"Event ID": "event-general", "Event Type": "General", "Status": "已采纳"}},
            {"fields": {"Event ID": "event-product", "Event Type": "Product_Launch", "Status": "已采纳"}},
        ]
        audit = build_coverage_audit(
            targets,
            news,
            events,
            discovered_urls={
                "https://example.com/quota",
                "https://example.com/no-entity",
                "https://example.com/general",
                "https://example.com/pending",
                "https://example.com/eligible",
            },
            selected_urls={
                "https://example.com/no-entity",
                "https://example.com/general",
                "https://example.com/pending",
                "https://example.com/eligible",
            },
            research_event_ids={"event-product"},
        )
        by_url = {row["url"]: row for row in audit["items"]}
        self.assertEqual(by_url["https://example.com/missing"]["reason"], "not_discovered")
        self.assertEqual(by_url["https://example.com/quota"]["reason"], "candidate_quota_excluded")
        self.assertEqual(by_url["https://example.com/no-entity"]["reason"], "missing_entity")
        self.assertEqual(by_url["https://example.com/general"]["reason"], "general_event_type")
        self.assertEqual(by_url["https://example.com/pending"]["reason"], "pending_human_review")
        self.assertEqual(by_url["https://example.com/eligible"]["reason"], "eligible")
        self.assertTrue(by_url["https://example.com/eligible"]["daily_eligible"])
        self.assertTrue(by_url["https://example.com/eligible"]["weekly_eligible"])
        self.assertTrue(by_url["https://example.com/eligible"]["research_input"])


if __name__ == "__main__":
    unittest.main()
