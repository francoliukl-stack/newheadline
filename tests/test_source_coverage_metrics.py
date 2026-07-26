import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.source_coverage_metrics import build_source_coverage_snapshot


class SourceCoverageMetricsTests(unittest.TestCase):
    def test_snapshot_reports_recall_purity_funnel_freshness_and_detection_time(self):
        now = datetime(2026, 7, 26, 12, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
        targets = [
            {"id": "known-1", "url": "https://reuters.com/story?a=1"},
            {"id": "known-2", "url": "https://example.com/missing"},
        ]
        news = [
            {"id": "n1", "fields": {
                "Source URL": {"link": "https://www.reuters.com/story?a=1&utm_source=test"},
                "Source Lane": "trusted_media",
                "Publish Date": "2026-07-25",
                "First Seen At": "2026-07-25T06:00:00+08:00",
                "Event Case ID": "event-1",
                "Review Status": "已采纳",
            }},
            {"id": "n2", "fields": {
                "Source URL": {"link": "https://fake.example/story"},
                "Source Lane": "trusted_media",
                "Publish Date": "1784822400000",
                "First Seen At": "1784887200000",
                "Review Status": "待处理",
            }},
        ]
        entities = [
            {"fields": {
                "Entity ID": "reuters-proxy",
                "Watch Tier": "high",
                "Active": "yes",
                "Newsroom URLs": "https://www.reuters.com/",
            }},
            {"fields": {
                "Entity ID": "missing-official",
                "Watch Tier": "high",
                "Active": "yes",
            }},
        ]
        detect = [
            {"fields": {
                "Type": "trusted_source",
                "Domains": "reuters.com",
                "Enabled": "true",
                "Collection Mode": "direct_site",
            }},
        ]
        snapshot = build_source_coverage_snapshot(
            news,
            entities,
            detect,
            targets,
            now=now,
            freshness_days=7,
        )
        self.assertEqual(snapshot["known_important_recall"]["ratio"], 0.5)
        self.assertEqual(snapshot["trusted_lane_purity"]["ratio"], 0.5)
        self.assertEqual(snapshot["official_source_coverage"]["ratio"], 0.5)
        self.assertEqual(snapshot["official_source_freshness"]["fresh_entities"], 1)
        self.assertEqual(snapshot["news_event_acceptance_funnel"]["news_total"], 2)
        self.assertEqual(snapshot["news_event_acceptance_funnel"]["event_linked"], 1)
        self.assertEqual(snapshot["news_event_acceptance_funnel"]["accepted_event_linked"], 1)
        self.assertEqual(snapshot["time_to_detect_hours"]["median"], 12.0)

    def test_trusted_lane_purity_is_not_reported_as_zero_without_samples(self):
        snapshot = build_source_coverage_snapshot(
            [],
            [],
            [{"fields": {"Type": "trusted_source", "Domains": "reuters.com", "Enabled": "true"}}],
            [],
            now=datetime(2026, 7, 26, 12, tzinfo=ZoneInfo("Asia/Kuala_Lumpur")),
        )
        self.assertIsNone(snapshot["trusted_lane_purity"]["ratio"])
        self.assertEqual(snapshot["trusted_lane_purity"]["status"], "no_sample")
