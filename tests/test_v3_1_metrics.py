from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.v3_1_metrics import build_v3_1_metrics


class V31MetricsTests(unittest.TestCase):
    def test_metrics_measure_lineage_latency_cost_and_human_gate(self):
        news = [{"id": "n1", "fields": {"First Seen At": "2026-06-27T08:00:00+08:00", "Publish Date": "2026-06-25", "Event Case ID": "event-1", "Review Status": "已采纳"}}]
        events = [{"id": "row-event", "fields": {
            "Event ID": "event-1", "Status": "已采纳", "First Seen At": "2026-06-27T08:00:00+08:00", "Publish Date": "2026-06-25",
            "Primary Source URL": {"link": "https://wise.com/results"}, "Business Lines": "WorldFirst", "Event Type": "Earnings",
            "Strategic Candidate": "yes", "Final Priority": "P1",
        }}]
        evidence = [{"fields": {"Event ID": "event-1", "Evidence ID": "evidence-1", "Source URL": {"link": "https://wise.com/results"}, "Published Date": "2026-06-25", "Reviewer Status": "Verified"}}]
        claims = [{"fields": {"Event ID": "event-1", "Claim ID": "claim-1", "Evidence IDs": "evidence-1", "Reviewer Status": "Approved"}}]
        usage = [
            {"fields": {"Call ID": "call-1", "Status": "reserved", "Estimated Cost USD": "0.2", "Actual Cost USD": "0", "Started At": "2026-06-27", "Finished At": ""}},
            {"fields": {"Call ID": "call-1", "Status": "completed", "Estimated Cost USD": "0.2", "Actual Cost USD": "0.1", "Started At": "2026-06-27", "Finished At": "2026-06-27"}},
        ]
        report = build_v3_1_metrics(news=news, events=events, evidence=evidence, claims=claims, usage=usage, now=datetime(2026, 6, 28, tzinfo=timezone.utc))
        metrics = report["metrics"]
        self.assertEqual(metrics["high_relevance_signals_7d"], 1)
        self.assertEqual(metrics["event_cases_created_7d"], 1)
        self.assertEqual(metrics["critical_event_cases_7d"], 1)
        self.assertEqual(metrics["critical_event_cases_active"], 1)
        self.assertEqual(metrics["business_mapping_completeness"], 1.0)
        self.assertEqual(metrics["specific_event_type_completeness"], 1.0)
        self.assertEqual(metrics["candidate_lineage_completeness"], 1.0)
        self.assertEqual(metrics["accepted_lineage_completeness"], 1.0)
        self.assertEqual(metrics["deep_research_ready_event_cases"], 1)
        self.assertEqual(metrics["median_publish_to_event_lag_days"], 2)
        self.assertEqual(metrics["critical_detection_within_1d_rate_7d"], 0.0)
        self.assertEqual(report["targets"]["critical_detection_within_1d_rate_7d"]["status"], "not_met")
        self.assertEqual(metrics["publish_to_event_lag_resolution"], "date_only")
        self.assertEqual(metrics["api_cost_usd_28d"], 0.1)
        self.assertEqual(metrics["automatic_final_p0_violations"], 0)
        self.assertEqual(report["four_week_success_status"], "observation_incomplete")

    def test_metrics_exclude_archived_events_and_detect_unsafe_p0(self):
        events = [
            {"fields": {"Event ID": "active", "Status": "待处理", "First Seen At": "2026-06-28", "Publish Date": "2026-06-28", "Primary Source URL": {"link": "https://example.com"}, "Business Lines": "Antom", "Event Type": "Product_Launch", "Final Priority": "P0"}},
            {"fields": {"Event ID": "archived", "Status": "已归档", "First Seen At": "2026-06-28", "Business Lines": "Antom", "Event Type": "Product_Launch"}},
            {"fields": {"Event ID": "duplicate", "Status": "已重复", "First Seen At": "2026-06-28", "Business Lines": "Antom", "Event Type": "Product_Launch"}},
        ]
        report = build_v3_1_metrics(news=[], events=events, evidence=[], claims=[], usage=[], now=datetime(2026, 6, 28, tzinfo=timezone.utc))
        self.assertEqual(report["metrics"]["active_event_cases"], 1)
        self.assertEqual(report["metrics"]["automatic_final_p0_violations"], 1)
        self.assertEqual(report["targets"]["automatic_final_p0_violations"]["status"], "not_met")

    def test_historical_backfill_is_not_counted_as_a_new_weekly_event(self):
        news = [{"fields": {"First Seen At": "2026-05-01", "Event Case ID": "event-backfill", "Review Status": "待处理"}}]
        events = [{"fields": {
            "Event ID": "event-backfill", "Status": "待处理", "First Seen At": "2026-06-28",
            "Publish Date": "2026-05-01", "Primary Source URL": {"link": "https://example.com/backfill"},
            "Business Lines": "WorldFirst", "Event Type": "General",
        }}]
        report = build_v3_1_metrics(news=news, events=events, evidence=[], claims=[], usage=[], now=datetime(2026, 6, 28, tzinfo=timezone.utc))
        self.assertEqual(report["metrics"]["event_cases_created_7d"], 0)
        self.assertEqual(report["metrics"]["critical_event_cases_7d"], 0)
        self.assertEqual(report["metrics"]["business_mapping_completeness"], 1.0)
        self.assertEqual(report["metrics"]["specific_event_type_completeness"], 0.0)


if __name__ == "__main__":
    unittest.main()
