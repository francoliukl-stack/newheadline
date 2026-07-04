from __future__ import annotations

from datetime import date, datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch

import httpx
from pydantic import BaseModel

from app.adapters import AdapterRequest, AlphaVantageAdapter, FirecrawlAdapter, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter, SourceSignal
from app.ai_news_review import AI_ACCEPT, AI_DUPLICATE, AI_REJECT, AI_REVIEW_VERSION, AI_STATUSES, LearnedReviewRule, accepted_event_status_updates, apply_deadline_guard, deadline_fields, difference_fields, feedback_fields, learn_review_rules, learning_snapshot, plan_review_updates, recommend_news, review_fingerprint, summarize_feedback
from app.cost_control import BudgetController, MemoryUsageLedger, calculate_cost, estimate_cost
from app.event_intelligence import EntityRecord, EventCandidate, EventLLMAnalysis, EventSourceCandidate, _upsert, deterministic_impact_hypothesis, enrich_events_with_llm, event_status_from_news, eventize_records, infer_event_type, is_critical_signal, machine_priority, match_entities, publication_eligible, reconcile_event_ids, same_event, stale_ai_rejected_event_updates, superseded_entity_relation_updates, superseded_event_updates, terminal_event_status_updates, validate_final_p0
from types import SimpleNamespace
from app.llm_service import LLMService
from app.models import AppSettings, OpenAIServiceSettings
from app.run_logs import RunLogStore
from app.scheduler import build_critical_scan_plist
from app.notifications import send_dingtalk_action_card
from app.event_alerts import send_event_alerts
from app.event_weekly import load_weekly_input
from app.event_tables import ENTITY_SOURCE_SEEDS, EVENT_CASE_FIELDS, EVENT_SOURCE_FIELDS, NEWS_LINEAGE_FIELDS, SHEET_DEFINITIONS
from app.gbss_report import build_report_data
from app.publish_format import build_competitor_report_content, build_empty_daily_report_content, build_headlines_content, build_weekly_research_link_content, concise_headline
from app.report_visual import build_one_page_report_svg
from scripts.run_v3_1_evaluation import evaluate
from scripts.daily_remind import build_review_content, collect_review_state, review_readiness_error
from scripts.record_review_timing import validate_review_timing
from scripts.cutover_v3_1 import readiness_failures
from scripts.critical_event_scan import fresh_critical_rows, recent_news_records


def response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.com"))


class SampleOutput(BaseModel):
    label: str
    confidence: float


class NestedOutput(BaseModel):
    label: str


class StrictOutput(BaseModel):
    nested: NestedOutput
    note: Optional[str] = None


class FakeAudit:
    def __init__(self, status: str = "sent") -> None:
        self.status = status
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)
        return SimpleNamespace(status=self.status, message="" if self.status == "sent" else "offline")


class V31ServiceTests(unittest.TestCase):
    def test_daily_headline_prefers_readable_translation_over_non_latin_prefix(self):
        title = "അന്താരാഷ്ട്ര ഇടപാടുകൾക്കായി യു.പി.ഐ. | NPCI Expands UPI for International Payments with HSBC & JP Morgan | Mathrubhumi"
        self.assertEqual(concise_headline(title), "NPCI Expands UPI for International Payments with HSBC & JP Morgan")
        self.assertEqual(concise_headline("PayPal Secures EPC Seat | PYMNTS.com"), "PayPal Secures EPC Seat")

    def test_daily_report_discloses_ai_deadline_fallback_without_claiming_manual_verification(self):
        record = {"id": "event", "fields": {"Title": "Event", "Section": "Antom", "Label": "Regulatory", "Source URL": {"link": "https://example.com"}, "Publish Date": "2026-07-03", "Review Decision Sources": "AI_Deadline_Recovery"}}
        content = build_headlines_content([record], "Daily", "JUL 03")
        self.assertIn("deadline-fallback", content)
        self.assertIn("not individually approved", content)
        self.assertNotIn("merged with manual verification", content)

    def test_weekly_link_digest_contains_manual_report_and_news_without_internal_ids(self):
        record = {"id": "event", "fields": {"Title": "PayPal EPC seat", "Section": "Antom", "Label": "Channel_Partner", "Source URL": {"link": "https://example.com/news"}, "Publish Date": "2026-07-03", "Event ID": "event-secret"}}
        content = build_weekly_research_link_content([record], "JUN 28 - JUL 04", "Payment network governance", "https://alidocs.dingtalk.com/i/nodes/report", 10)
        self.assertIn("Open DingTalk document", content)
        self.assertIn("PayPal EPC seat", content)
        self.assertIn("Publish Date: 2026-07-03", content)
        self.assertIn("No access?", content)
        self.assertIn("qr.dingtalk.com/action/joingroup", content)
        self.assertLess(content.index("No access?"), content.index("Weekly Key Events & News"))
        self.assertNotIn("event-secret", content)
        with self.assertRaises(ValueError):
            build_weekly_research_link_content([record], "period", "topic", "", 10)

    def test_manual_review_timing_sample_is_bounded_and_targeted(self):
        sample = validate_review_timing("2026-07-03", 8.5, 12, date(2026, 7, 4))
        self.assertEqual(sample["measurement_mode"], "manual_timed_sample")
        self.assertEqual(sample["target_status"], "met")
        with self.assertRaises(ValueError):
            validate_review_timing("2026-07-05", 8.5, 12, date(2026, 7, 4))
        with self.assertRaises(ValueError):
            validate_review_timing("2026-07-03", 0, 12, date(2026, 7, 4))

    def test_event_split_cannot_assign_one_stable_id_to_two_candidates(self):
        source_a = EventSourceCandidate("n1", "QRIS merchant promotion", "https://example.com/promo", "example.com", "2026-07-01", "mock", False)
        source_b = EventSourceCandidate("n2", "QRIS available in Thailand", "https://example.com/thailand", "example.com", "2026-07-03", "mock", False)
        make_event = lambda event_id, source, event_type: EventCandidate(event_id, source.title, event_type, ["Alipay_Plus"], [], [source], source.publish_date, event_type == "Market_Expansion", 0.9, {}, 0.8, "P1", source.title, "Review", "Boundary")
        candidates = [make_event("new-expansion", source_b, "Market_Expansion"), make_event("old-qris", source_a, "General")]
        existing_sources = [
            {"fields": {"Event ID": "old-qris", "Source URL": {"link": source_a.url}}},
            {"fields": {"Event ID": "old-qris", "Source URL": {"link": source_b.url}}},
        ]
        self.assertEqual(reconcile_event_ids(candidates, existing_sources), 2)
        self.assertEqual(len({event.event_id for event in candidates}), 2)
        self.assertEqual(candidates[0].event_id, "old-qris")
        self.assertNotEqual(candidates[1].event_id, "old-qris")

    def test_ai_review_deadline_is_high_confidence_traceable_and_human_first(self):
        news = {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-29"}
        event = {"Event Type": "Earnings", "Business Lines": "WorldFirst", "Relevance Score": "0.91", "Strategic Candidate": "yes"}
        recommendation = recommend_news(news, event)
        self.assertEqual(recommendation.status, AI_ACCEPT)
        ai_fields = {**news, "AI Status": recommendation.status, "AI Confidence": str(recommendation.confidence)}
        self.assertEqual(deadline_fields(ai_fields, event, "2026-06-30T11:50:00+08:00")["Status"], "已采纳")
        self.assertEqual(deadline_fields({**ai_fields, "Status": "已拒绝"}, event, "now"), {})
        self.assertEqual(deadline_fields({**ai_fields, "AI Confidence": "0.84"}, event, "now"), {})
        self.assertEqual(deadline_fields({**ai_fields, "Source URL": ""}, event, "now"), {})
        self.assertEqual(deadline_fields(ai_fields, {**event, "Status": "已归档"}, "now"), {})

    def test_ai_review_makes_explicit_decisions_and_captures_bad_cases(self):
        news = {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com"}, "Publish Date": "2026-06-29"}
        self.assertEqual(recommend_news(news, {"Event Type": "General", "Business Lines": "Antom", "Relevance Score": "0.8"}).status, AI_REJECT)
        matched = feedback_fields({"Status": "已采纳", "AI Status": AI_ACCEPT}, "now")
        self.assertEqual(matched["AI Feedback Outcome"], "Matched")
        overridden = feedback_fields({"Status": "已拒绝", "AI Status": AI_ACCEPT}, "now")
        self.assertEqual(overridden["AI Feedback Outcome"], "Overridden")
        rejected_match = feedback_fields({"Status": "已拒绝", "AI Status": AI_REJECT}, "now")
        self.assertEqual(rejected_match["AI Feedback Outcome"], "Matched")
        later_override = feedback_fields({"Status": "已拒绝", "AI Status": AI_ACCEPT, "Review Decision Source": "AI_Deadline", "AI Applied Status": "已采纳"}, "now")
        self.assertEqual(later_override["Review Decision Source"], "Human_Override")

    def test_ai_review_plan_only_auto_accepts_previous_day(self):
        events = [{"id": "e", "fields": {"Event ID": "event-1", "Event Type": "Product_Launch", "Business Lines": "Antom", "Relevance Score": "0.9"}}]
        news = [
            {"id": "target", "fields": {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-29"}},
            {"id": "old", "fields": {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/b"}, "Publish Date": "2026-06-28"}},
        ]
        updates, stats = plan_review_updates(news, events, "deadline", datetime(2026, 6, 30, 11, 50, tzinfo=timezone.utc), "Asia/Kuala_Lumpur")
        by_id = {row["id"]: row["fields"] for row in updates}
        self.assertEqual(by_id["target"]["Status"], "已采纳")
        self.assertNotIn("old", by_id)
        self.assertEqual(stats["auto_accepted"], 1)

    def test_ai_deadline_handles_unchanged_recommendation(self):
        event = {"Event ID": "event-1", "Event Type": "Regulatory", "Business Lines": "HK_Fintech", "Relevance Score": "0.9"}
        fields = {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-29", "AI Status": AI_ACCEPT, "AI Confidence": "0.90"}
        fields["AI Review Version"] = AI_REVIEW_VERSION
        fields["AI Review Fingerprint"] = review_fingerprint(fields, event)
        updates, stats = plan_review_updates(
            [{"id": "target", "fields": fields}],
            [{"id": "event-row", "fields": event}],
            "deadline",
            datetime(2026, 6, 30, 11, 50, tzinfo=timezone.utc),
            "Asia/Kuala_Lumpur",
        )
        self.assertEqual(updates, [{"id": "target", "fields": {
            "Status": "已采纳",
            "Review Decision Source": "AI_Deadline",
            "AI Applied Status": "已采纳",
            "AI Applied At": "2026-06-30T19:50:00+08:00",
            "AI Feedback Outcome": "Pending Human Feedback",
        }}])
        self.assertEqual(stats["auto_accepted"], 1)

    def test_ai_deadline_recovers_only_five_current_traceable_overdue_rows(self):
        active_event = {"Event ID": "event-1", "Event Type": "Regulatory", "Business Lines": "HK_Fintech", "Relevance Score": "0.9", "Status": "待处理"}
        archived_event = {"Event ID": "event-archived", "Event Type": "Regulatory", "Business Lines": "HK_Fintech", "Relevance Score": "0.9", "Status": "已归档"}
        news = []
        for index in range(6):
            fields = {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": f"https://example.com/{index}"}, "Publish Date": "2026-06-28", "AI Status": AI_ACCEPT, "AI Confidence": "0.90", "AI Review Version": AI_REVIEW_VERSION}
            fields["AI Review Fingerprint"] = review_fingerprint(fields, active_event)
            news.append({"id": f"overdue-{index}", "fields": fields})
        archived_fields = {"Status": "待处理", "Event Case ID": "event-archived", "Source URL": {"link": "https://example.com/archived"}, "Publish Date": "2026-06-28", "AI Status": AI_ACCEPT, "AI Confidence": "0.90", "AI Review Version": AI_REVIEW_VERSION}
        archived_fields["AI Review Fingerprint"] = review_fingerprint(archived_fields, archived_event)
        news.append({"id": "archived", "fields": archived_fields})
        updates, stats = plan_review_updates(news, [{"fields": active_event}, {"fields": archived_event}], "deadline", datetime(2026, 6, 30, 3, 50, tzinfo=timezone.utc), "Asia/Kuala_Lumpur")
        recovered = [row for row in updates if (row.get("fields") or {}).get("Review Decision Source") == "AI_Deadline_Recovery"]
        self.assertEqual(len(recovered), 5)
        self.assertEqual(stats["overdue_auto_accepted"], 5)
        self.assertNotIn("archived", {row["id"] for row in recovered})

        guard_updates, guard_stats = plan_review_updates(news, [{"fields": active_event}, {"fields": archived_event}], "deadline", datetime(2026, 6, 30, 3, 50, tzinfo=timezone.utc), "Asia/Kuala_Lumpur", include_overdue=False)
        self.assertEqual(guard_stats["overdue_auto_accepted"], 0)
        self.assertFalse(any((row.get("fields") or {}).get("Review Decision Source") == "AI_Deadline_Recovery" for row in guard_updates))

    def test_ai_deadline_accepts_only_active_linked_events_after_news_write(self):
        news = [{"id": "n1", "fields": {"Event Case ID": "active"}}, {"id": "n2", "fields": {"Event Case ID": "archived"}}, {"id": "n3", "fields": {"Event Case ID": "already-accepted", "Status": "已采纳"}}]
        events = [
            {"id": "e1", "fields": {"Event ID": "active", "Status": "待处理"}},
            {"id": "e2", "fields": {"Event ID": "archived", "Status": "已归档"}},
            {"id": "e3", "fields": {"Event ID": "already-accepted", "Status": "待处理"}},
        ]
        updates = [{"id": "n1", "fields": {"Status": "已采纳"}}, {"id": "n2", "fields": {"Status": "已采纳"}}]
        self.assertEqual(accepted_event_status_updates(news, events, updates), [{"id": "e1", "fields": {"Status": "已采纳"}}, {"id": "e3", "fields": {"Status": "已采纳"}}])

    @patch("app.ai_news_review.update_records")
    @patch("app.ai_news_review.list_records")
    def test_daily_report_deadline_guard_is_idempotent(self, list_rows: Mock, update: Mock):
        settings = AppSettings()
        settings.system.timezone = "Asia/Kuala_Lumpur"
        settings.dingtalk_ai_table.sheet_id = "news"
        settings.dingtalk_ai_table.event_cases_sheet_id = "events"
        event = {"Event ID": "event-1", "Event Type": "Regulatory", "Business Lines": "HK_Fintech", "Relevance Score": "0.9"}
        fields = {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-29", "AI Status": AI_ACCEPT, "AI Confidence": "0.90"}
        fields["AI Review Version"] = AI_REVIEW_VERSION
        fields["AI Review Fingerprint"] = review_fingerprint(fields, event)
        rows = {"news": [{"id": "target", "fields": fields}], "events": [{"id": "event-row", "fields": event}]}
        list_rows.side_effect = lambda _dingtalk, table: rows[table.sheet_id]
        update.return_value = SimpleNamespace(status="sent", record_ids=["target"], message="")
        count, stats = apply_deadline_guard(settings, datetime(2026, 6, 30, 11, 59, tzinfo=timezone.utc))
        self.assertEqual((count, stats["auto_accepted"]), (1, 1))
        self.assertEqual(len(update.call_args_list), 2)
        rows["news"][0]["fields"].update(update.call_args_list[0].args[2][0]["fields"])
        rows["events"][0]["fields"].update(update.call_args_list[1].args[2][0]["fields"])
        update.reset_mock()
        count, stats = apply_deadline_guard(settings, datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc))
        self.assertEqual((count, stats["auto_accepted"]), (0, 0))
        update.assert_not_called()

    def test_ai_status_is_decisive_and_has_full_table_incremental_coverage(self):
        events = [{"id": "e", "fields": {"Event ID": "event-1", "Event Type": "Product_Launch", "Business Lines": "Antom", "Relevance Score": "0.9"}}]
        news = [
            {"id": "recent", "fields": {"Status": "待处理", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-29"}},
            {"id": "legacy", "fields": {"Status": "已拒绝", "Source URL": {"link": "https://example.com/old"}, "Publish Date": "2026-05-01"}},
            {"id": "duplicate", "fields": {"Status": "已重复", "Duplicate Of": "recent", "Source URL": {"link": "https://example.com/dup"}, "Publish Date": "2026-06-20"}},
        ]
        updates, stats = plan_review_updates(news, events, "suggest", datetime(2026, 6, 30, tzinfo=timezone.utc), "Asia/Kuala_Lumpur")
        by_id = {row["id"]: row["fields"] for row in updates}
        self.assertEqual(set(by_id), {"recent", "legacy", "duplicate"})
        self.assertTrue({row["AI Status"] for row in by_id.values()}.issubset(AI_STATUSES))
        self.assertNotIn("待处理", {row["AI Status"] for row in by_id.values()})
        self.assertEqual(by_id["duplicate"]["AI Status"], AI_DUPLICATE)
        self.assertEqual(stats["total"], 3)
        enriched = [{"id": row["id"], "fields": {**news[index]["fields"], **by_id[row["id"]]}} for index, row in enumerate(updates)]
        second, second_stats = plan_review_updates(enriched, events, "suggest", datetime(2026, 6, 30, 1, tzinfo=timezone.utc), "Asia/Kuala_Lumpur")
        self.assertEqual(second, [])
        self.assertEqual(second_stats["unchanged"], 3)

    def test_ai_review_learning_policy_is_support_gated(self):
        events = [{"id": "e", "fields": {"Event ID": "event-1", "Event Type": "Product_Launch", "Business Lines": "GBSS_Service"}}]
        news = [
            {"id": f"n{i}", "fields": {"Event Case ID": "event-1", "Status": status, "Review Decision Source": "Human"}}
            for i, status in enumerate([AI_ACCEPT, AI_ACCEPT, AI_ACCEPT, AI_ACCEPT, AI_REJECT])
        ]
        rules = learn_review_rules(news, events)
        self.assertEqual(len(rules), 1)
        self.assertEqual((rules[0].status, rules[0].support, rules[0].agreement), (AI_ACCEPT, 5, 0.8))
        self.assertEqual(learn_review_rules(news[:4], events), [])
        split = [
            {"id": f"s{i}", "fields": {"Event Case ID": "event-1", "Status": status, "Review Decision Source": "Human"}}
            for i, status in enumerate([AI_ACCEPT, AI_ACCEPT, AI_ACCEPT, AI_REJECT, AI_REJECT])
        ]
        self.assertEqual(learn_review_rules(split, events), [])

    def test_ai_review_hard_gates_override_learned_policy(self):
        rule = LearnedReviewRule("Market_Context", "GBSS_Service", AI_ACCEPT, 10, 0.9)
        event = {"Event Type": "Market_Context", "Business Lines": "GBSS_Service", "Relevance Score": "0.2"}
        duplicate = {"Duplicate Of": "canonical", "Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-07-01"}
        self.assertEqual(recommend_news(duplicate, event, rule).status, AI_DUPLICATE)
        missing_url = {"Event Case ID": "event-1", "Publish Date": "2026-07-01"}
        self.assertEqual(recommend_news(missing_url, event, rule).status, AI_REJECT)
        learned = recommend_news({"Event Case ID": "event-1", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-07-01"}, event, rule)
        self.assertEqual(learned.status, AI_ACCEPT)
        self.assertLess(learned.confidence, 0.85)

    def test_ai_review_difference_summary_is_explainable(self):
        fields = {"Status": AI_DUPLICATE, "AI Status": AI_ACCEPT, "AI Feedback Outcome": "Overridden", "AI Feedback At": "2026-07-01T08:50:00+08:00"}
        difference = difference_fields(fields, {"Event Type": "Product_Launch"})
        self.assertEqual(difference["AI Difference Category"], "Duplicate_Missed")
        record = {"id": "n1", "fields": {**fields, **difference}}
        summary = summarize_feedback([record], "2026-07-01")
        self.assertEqual((summary["reviewed"], summary["overridden"]), (1, 1))
        self.assertEqual(summary["top_categories"], [("Duplicate_Missed", 1)])
        content = build_review_content(1, 1, 0, 0, "2026-06-30", feedback_summary=summary)
        self.assertIn("昨日人机差异复盘", content)
        self.assertIn("Duplicate_Missed 1", content)

    def test_ai_review_difference_reasons_are_normalized(self):
        base = {"Status": AI_REJECT, "AI Status": AI_ACCEPT, "AI Feedback Outcome": "Overridden"}
        cases = [
            ({**base, "Title": "Thailand Visa Platform Makes University Visas Free"}, "Entity_False_Positive"),
            ({**base, "Title": "Visa partners with AI fintechs", "Rejection Reason": "信息量太少"}, "Thin_Content"),
            ({**base, "Title": "HKMA Bulletin", "Rejection Reason": "no content in URL"}, "Source_Content_Unavailable"),
            ({**base, "Title": "Zendesk Pricing Plans", "Rejection Reason": "PR"}, "Promotional_Content"),
            ({**base, "Title": "PayPal: a hidden gem?"}, "Market_Commentary"),
            ({**base, "Title": "Payment rules hearing", "Rejection Reason": "关系不大"}, "Tangential_Relevance"),
        ]
        for fields, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(difference_fields(fields, {"Event Type": "General"})["AI Difference Category"], expected)
        cleared = difference_fields({
            "Status": AI_ACCEPT,
            "AI Status": AI_ACCEPT,
            "AI Feedback Outcome": "Matched",
            "AI Difference Category": "Event_Type_Underclassified",
            "AI Difference Summary": "old",
        }, {"Event Type": "Market_Expansion"})
        self.assertEqual(cleared, {"AI Difference Category": "", "AI Difference Summary": ""})

    def test_ai_review_learning_snapshot_is_auditable(self):
        events = [{"id": "e", "fields": {"Event ID": "event-1", "Event Type": "Product_Launch", "Business Lines": "Antom"}}]
        news = [
            {"id": f"n{i}", "fields": {"Event Case ID": "event-1", "Status": AI_ACCEPT, "Review Decision Source": "Human", "AI Status": AI_ACCEPT, "AI Feedback Outcome": "Matched", "AI Feedback At": "2026-07-01T09:00:00+08:00"}}
            for i in range(5)
        ]
        snapshot = learning_snapshot(news, events, "2026-07-01")
        self.assertEqual(snapshot["learned_rule_details"], [{"segment": "Product_Launch|Antom", "status": AI_ACCEPT, "support": 5, "agreement": 1.0}])
        self.assertEqual(snapshot["feedback_summary"]["agreement"], 1.0)

    def test_high_value_competitors_have_verified_official_scan_pages(self):
        expected = {"airwallex", "checkout-com", "dlocal", "paypal", "genesys", "nice"}
        self.assertTrue(expected.issubset(ENTITY_SOURCE_SEEDS))
        self.assertTrue(all(ENTITY_SOURCE_SEEDS[entity].get("Newsroom URLs") for entity in expected))

    def test_critical_rows_fail_closed_without_fresh_publish_date(self):
        rows = [
            {"title": "fresh", "published_at": "2026-06-29"},
            {"title": "old", "published_at": "2026-05-01"},
            {"title": "missing", "published_at": ""},
            {"title": "future", "published_at": "2026-07-01"},
        ]
        selected = fresh_critical_rows(rows, 7, "Asia/Kuala_Lumpur", datetime(2026, 6, 30, 9, tzinfo=timezone.utc))
        self.assertEqual([row["title"] for row in selected], ["fresh"])

    @staticmethod
    def event_report_record() -> dict:
        return {
            "id": "row-event-1",
            "fields": {
                "Event ID": "event-1",
                "Title": "Wise publishes annual results",
                "Label": "Earnings",
                "Section": "WorldFirst",
                "Source URL": {"link": "https://wise.com/results"},
                "Publish Date": "2026-06-27",
                "Status": "已采纳",
                "Review Status": "已采纳",
                "Priority Candidate": "P1",
                "Final Priority": "P1",
                "Event Source IDs": "event-source-1",
                "Evidence IDs": "evidence-1",
                "Claim IDs": "claim-1",
                "Limitations": "Company guidance is forward-looking.",
            },
        }

    def test_cost_estimate_uses_pinned_model_prices(self):
        estimate = estimate_cost("gpt-5.4-nano-2026-03-17", "hello", 1000)
        self.assertGreater(estimate.cost_usd, 0)
        self.assertEqual(calculate_cost("gpt-5.4-mini-2026-03-17", 1_000_000, 1_000_000), 5.25)

    def test_budget_preflight_blocks_monthly_cap(self):
        config = OpenAIServiceSettings(monthly_cap_usd=1, weekly_cap_usd=5, daily_cap_usd=5)
        ledger = MemoryUsageLedger([{"Started At": datetime.now(timezone.utc).isoformat(), "Actual Cost USD": "0.9999"}])
        decision = BudgetController(config, ledger, "Asia/Kuala_Lumpur").preflight(config.classification_model, "payload", 1000, "ingest")
        self.assertFalse(decision.allowed)
        self.assertIn("monthly", decision.reason)

    def test_budget_counts_reservation_once_after_append_only_completion(self):
        now = datetime.now(timezone.utc).isoformat()
        ledger = MemoryUsageLedger([
            {"Call ID": "call-1", "Status": "reserved", "Estimated Cost USD": "0.90", "Actual Cost USD": "0", "Started At": now, "Finished At": ""},
            {"Call ID": "call-1", "Status": "completed", "Estimated Cost USD": "0.90", "Actual Cost USD": "0.20", "Started At": now, "Finished At": now},
        ])
        config = OpenAIServiceSettings(monthly_cap_usd=0.5, weekly_cap_usd=0.5, daily_cap_usd=0.5)
        decision = BudgetController(config, ledger, "Asia/Kuala_Lumpur").preflight(config.classification_model, "payload", 1000, "ingest")
        self.assertTrue(decision.allowed)

    def test_circuit_opens_after_five_consecutive_failures(self):
        now = datetime.now(timezone.utc).isoformat()
        rows = [{"Provider": "openai", "Model": "m", "Status": "failed", "Started At": now} for _ in range(5)]
        config = OpenAIServiceSettings(circuit_failure_threshold=5)
        self.assertTrue(BudgetController(config, MemoryUsageLedger(rows), "Asia/Kuala_Lumpur").circuit_open("openai", "m"))

    def test_llm_structured_output_and_usage(self):
        config = OpenAIServiceSettings(enabled=True, api_key="test")
        ledger = MemoryUsageLedger()
        budget = BudgetController(config, ledger, "Asia/Kuala_Lumpur")
        client = Mock()
        client.post.return_value = response(200, {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"label": "Earnings", "confidence": 0.9})}]}], "usage": {"input_tokens": 100, "output_tokens": 20}})
        audit = FakeAudit()
        result = LLMService(config, budget, ledger, audit=audit, client=client).execute(task="classify", schema=SampleOutput, context={"title": "Results"}, budget_scope="ingest", run_id="run-1")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.value.label, "Earnings")
        self.assertEqual(ledger.records()[-1]["Status"], "completed")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        schema = payload["text"]["format"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["label", "confidence"])
        self.assertEqual(ledger.records()[0]["Status"], "reserved")
        self.assertEqual(audit.records[0]["status"], "started")

    def test_llm_strict_schema_is_recursive_and_requires_optional_fields(self):
        config = OpenAIServiceSettings(enabled=True, api_key="test")
        ledger = MemoryUsageLedger()
        client = Mock()
        client.post.return_value = response(200, {"id": "resp-2", "output_text": json.dumps({"nested": {"label": "x"}, "note": None}), "usage": {"input_tokens": 10, "output_tokens": 10}})
        result = LLMService(config, BudgetController(config, ledger, "Asia/Kuala_Lumpur"), ledger, audit=FakeAudit(), client=client).execute(task="classify", schema=StrictOutput, context={"title": "x"}, budget_scope="ingest", run_id="run-2")
        self.assertEqual(result.status, "completed")
        schema = client.post.call_args.kwargs["json"]["text"]["format"]["schema"]
        self.assertEqual(schema["required"], ["nested", "note"])
        self.assertFalse(schema["$defs"]["NestedOutput"]["additionalProperties"])

    def test_llm_fails_closed_without_audit_writer(self):
        config = OpenAIServiceSettings(enabled=True, api_key="test")
        ledger = MemoryUsageLedger()
        client = Mock()
        result = LLMService(config, BudgetController(config, ledger, "Asia/Kuala_Lumpur"), ledger, client=client).execute(task="classify", schema=SampleOutput, context={"title": "x"}, budget_scope="ingest", run_id="run-3")
        self.assertEqual(result.status, "skipped")
        self.assertIn("Audit Trail", result.message)
        client.post.assert_not_called()

    def test_golden_evaluation_uses_actual_catalog_mapping(self):
        payload = {
            "thresholds": {
                "clustering_precision": 0.9,
                "clustering_recall": 0.9,
                "business_line_accuracy": 0.9,
                "event_type_accuracy": 0.85,
                "critical_event_recall": 1.0,
                "automatic_final_p0_violations": 0,
                "lineage_completeness": 1.0,
            },
            "cases": [{
                "id": "wrong-line",
                "title": "Wise publishes annual results",
                "source_url": "https://wise.com/results",
                "expected_business_lines": ["Antom"],
            }],
            "lineage_cases": [{
                "fields": {"Status": "已采纳", "Accepted News Count": "1", "Primary Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-27", "Final Priority": "P1"},
                "expected_publication_eligible": True,
            }],
        }
        result = evaluate(payload)
        self.assertEqual(result["metrics"]["business_line_accuracy"], 0)
        self.assertIn("business_line_accuracy=0.000 threshold=0.900", result["failures"])

    def test_llm_web_search_requires_explicit_approval(self):
        config = OpenAIServiceSettings(enabled=True, api_key="test")
        ledger = MemoryUsageLedger()
        client = Mock()
        result = LLMService(config, BudgetController(config, ledger, "Asia/Kuala_Lumpur"), ledger, client=client).execute(task="research", schema=SampleOutput, context={"topic": "x"}, budget_scope="research", use_web_search=True, approval_granted=False)
        self.assertEqual(result.status, "skipped")
        self.assertIn("approval", result.message)
        client.post.assert_not_called()

    @patch("app.adapters.gdelt.httpx.get")
    def test_gdelt_adapter_normalizes_articles(self, get: Mock):
        get.return_value = response(200, {"articles": [{"title": "Wise results", "url": "https://wise.com/a", "domain": "wise.com", "seendate": "20260627T010000Z"}]})
        rows = GdeltAdapter().collect(AdapterRequest(query="Wise", limit=1))
        self.assertEqual(rows[0].provider, "gdelt")
        self.assertEqual(rows[0].source_domain, "wise.com")
        self.assertEqual(rows[0].publish_date, "2026-06-27")

    @patch("app.adapters.gdelt.httpx.get")
    def test_gdelt_adapter_retries_rate_limit(self, get: Mock):
        rate_limited = response(429, {"error": "rate limited"})
        rate_limited.headers["retry-after"] = "0.1"
        get.side_effect = [rate_limited, response(200, {"articles": [{"title": "Wise results", "url": "https://wise.com/a", "domain": "wise.com"}]})]
        sleep = Mock()
        rows = GdeltAdapter(max_retries=1, sleep_fn=sleep).collect(AdapterRequest(query="Wise", limit=1))
        self.assertEqual(len(rows), 1)
        sleep.assert_called_once_with(0.1)

    @patch("app.adapters.marketaux.httpx.get")
    def test_marketaux_adapter_requires_and_uses_key(self, get: Mock):
        get.return_value = response(200, {"data": [{"title": "Adyen launch", "url": "https://adyen.com/news/a", "published_at": "2026-06-27"}]})
        rows = MarketauxAdapter("key").collect(AdapterRequest(query="Adyen", limit=1))
        self.assertEqual(rows[0].provider, "marketaux")
        self.assertEqual(get.call_args.kwargs["params"]["api_token"], "key")

    @patch("app.adapters.firecrawl.httpx.post")
    def test_firecrawl_adapter_extracts_markdown(self, post: Mock):
        post.return_value = response(200, {"data": {"markdown": "# Result", "metadata": {"title": "Result", "publishedTime": "2026-06-27"}}})
        item = FirecrawlAdapter("key").extract("https://example.com")
        self.assertEqual(item.markdown, "# Result")

    @patch("app.adapters.official.httpx.get")
    def test_official_adapter_reads_rss(self, get: Mock):
        get.return_value = response(200, {})
        get.return_value._content = b"<rss><channel><item><title>Wise publishes annual results</title><link>https://wise.com/results</link><pubDate>2026-06-27</pubDate><description>Wise reported 20% volume growth &amp; introduced FY2027 guidance.</description></item></channel></rss>"
        get.return_value.headers["content-type"] = "application/xml"
        rows = OfficialSourceAdapter().collect(AdapterRequest(urls=["https://wise.com/feed"], limit=5))
        self.assertEqual(rows[0].metadata["source_grade"], "T1")
        self.assertIn("20% volume growth", rows[0].snippet)

    @patch("app.adapters.official.httpx.get")
    def test_official_adapter_normalizes_rfc822_date(self, get: Mock):
        get.return_value = response(200, {})
        get.return_value._content = b"<rss><channel><item><title>Wise publishes annual results</title><link>https://wise.com/results</link><pubDate>Thu, 25 Jun 2026 16:01:00 -0400</pubDate></item></channel></rss>"
        get.return_value.headers["content-type"] = "application/rss+xml"
        rows = OfficialSourceAdapter().collect(AdapterRequest(urls=["https://wise.com/feed"], limit=5))
        self.assertEqual(rows[0].publish_date, "2026-06-25")

    @patch("app.adapters.official.httpx.get")
    def test_official_adapter_prioritizes_article_links_over_navigation(self, get: Mock):
        get.return_value = response(200, {})
        get.return_value._content = '''
            <html><head><style>.hero{display:block}</style></head><body>
              <header><a href="/products/payments">Accept Online Process payments your way</a></header>
              <main>
                <a href="/products/treasury">Treasury products for global companies</a>
                <article class="news-card featured"><time>Jul 25, 2024</time><a href="/newsroom/company-announces-old-bank-partnership">Company announces old bank partnership</a></article>
                <article><time>Jun 29, 2026</time><a href="/newsroom/company-launches-new-cross-border-settlement-service">Company launches new cross-border settlement service View</a></article>
              </main>
              <footer><a href="/languages/es">América Latina (Español)</a></footer>
            </body></html>
        '''.encode("utf-8")
        get.return_value.headers["content-type"] = "text/html"
        rows = OfficialSourceAdapter().collect(AdapterRequest(entity_id="example", urls=["https://example.com/newsroom"], limit=1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, "Company launches new cross-border settlement service")
        self.assertEqual(rows[0].source_url, "https://example.com/newsroom/company-launches-new-cross-border-settlement-service")
        self.assertEqual(rows[0].publish_date, "2026-06-29")

    @patch("app.adapters.official.httpx.get")
    def test_official_content_adapter_extracts_main_text(self, get: Mock):
        get.return_value = response(200, {})
        get.return_value._content = b'<html><head><meta property="og:title" content="Wise FY2026 results"><meta property="article:published_time" content="2026-06-25T16:01:00Z"></head><body><nav>Navigation</nav><main><h1>Wise FY2026 results</h1><p>Cross-border volume reached $243 billion and customer holdings grew 40%.</p></main></body></html>'
        extracted = OfficialSourceAdapter().extract("https://wise.com/results")
        self.assertEqual(extracted.title, "Wise FY2026 results")
        self.assertEqual(extracted.publish_date, "2026-06-25")
        self.assertIn("customer holdings grew 40%", extracted.markdown)
        self.assertNotIn("Navigation", extracted.markdown)

    @patch("app.adapters.official.time.sleep")
    @patch("app.adapters.official.httpx.get")
    def test_official_adapter_retries_timeout(self, get: Mock, sleep: Mock):
        timeout = httpx.ReadTimeout("timeout", request=httpx.Request("GET", "https://wise.com/feed"))
        get.side_effect = [timeout, response(200, {"ok": True})]
        result = OfficialSourceAdapter(max_retries=1)._get("https://wise.com/feed")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(1)

    @patch("app.adapters.market.httpx.get")
    def test_alpha_vantage_adapter_normalizes_market_signal(self, get: Mock):
        get.return_value = response(200, {"Global Quote": {"05. price": "105", "08. previous close": "100"}})
        row = AlphaVantageAdapter("key").snapshot("PAYO")[0]
        self.assertEqual(row.change_pct, 5)

    def test_event_rules_never_assign_final_p0(self):
        self.assertEqual(machine_priority(0.9, "Regulatory", True), "P0_Candidate")
        self.assertNotEqual(machine_priority(1.0, "Ops_Incident", True), "P0")
        self.assertFalse(validate_final_p0({"Final Priority": "P0", "P0 Approval Status": "Approved"}))
        self.assertTrue(validate_final_p0({"Final Priority": "P0", "P0 Approval Status": "Approved", "Reviewer": "owner", "Reviewed At": "now"}))
        self.assertEqual(infer_event_type("Wise FY26 Results"), "Earnings")

    def test_event_type_rules_cover_common_critical_headline_phrasing(self):
        self.assertEqual(infer_event_type("Adyen introducing an agentic commerce product"), "Product_Launch")
        self.assertEqual(infer_event_type("Adyen announces Adyen Agentic for commerce"), "Product_Launch")
        self.assertEqual(infer_event_type("Senator calls for investigation and probe into Airwallex"), "Regulatory")
        self.assertEqual(infer_event_type("Stripe tells Congress payment rules need reform"), "Regulatory")
        self.assertEqual(infer_event_type("Visa partners with fintechs through a new integration"), "Channel_Partner")
        self.assertEqual(infer_event_type("Ant International quiere desembarcar en la Argentina con Alipay+"), "Market_Expansion")
        self.assertEqual(infer_event_type("Alipay+ expands into a new market"), "Market_Expansion")
        self.assertEqual(infer_event_type("UPI expands to Greece, enables instant money transfers"), "Market_Expansion")
        self.assertEqual(infer_event_type("UPI goes global: Greece joins digital payment network"), "Market_Expansion")
        self.assertEqual(infer_event_type("Tak Lagi Bongkar Dompet, QRIS BRI Bikin Jualan Murtini Lebih Praktis"), "Market_Context")
        self.assertEqual(infer_event_type("NiCE Launches AI Specialization Program, Recognizing Partners Driving Significant AI Outcomes"), "Channel_Partner")
        self.assertEqual(infer_event_type("Hong Kong Monetary Authority urges banks to drive global yuan adoption with six-point strategy"), "Regulatory")
        self.assertEqual(infer_event_type("Nuvei to Acquire Payoneer for $2.75 Billion"), "Strategic_MA")
        self.assertEqual(infer_event_type("xAI rolls out Grok Voice AI Agent Builder for enterprise integrations"), "Product_Launch")
        self.assertEqual(infer_event_type("Adyen appoints interim CFO and chief product officer"), "Leadership_Change")
        self.assertEqual(infer_event_type("Airwallex secures $320 million in Series H funding to accelerate global expansion"), "Strategic_MA")
        self.assertEqual(infer_event_type("Airwallex raises $320M for planned AI expansion and growth in Israel"), "Strategic_MA")
        self.assertEqual(infer_event_type("Airwallex raises $320m to build out AI financial software | FinanceAsia"), "Strategic_MA")
        self.assertEqual(infer_event_type("Stripe valued at $159 billion among private companies"), "Market_Context")
        self.assertEqual(infer_event_type("Stripe vs Worldpay: payment infrastructure comparison"), "Market_Context")
        self.assertEqual(infer_event_type("Airwallex focuses on agentic commerce"), "Market_Context")
        self.assertEqual(infer_event_type("Alipay+ kicks off joint sustainability initiatives"), "Market_Context")
        self.assertEqual(machine_priority(0.95, "Market_Context", False), "Watch")

    def test_visa_entity_disambiguates_immigration_from_payments(self):
        visa = EntityRecord("visa", "Visa", [], ["Alipay_Plus", "Antom"], "V", ["https://www.visa.com"], "high")
        self.assertEqual(match_entities("The impact of H-1B visa rules on Indian workers", "https://example.com/immigration", [visa]), [])
        self.assertEqual(match_entities("Visa launches new merchant payment controls", "https://example.com/payments", [visa]), [visa])
        self.assertEqual(match_entities("New product announcement", "https://usa.visa.com/newsroom", [visa]), [visa])

    def test_upi_disambiguates_india_payments_from_unionpay(self):
        india_upi = EntityRecord("india-upi", "Unified Payments Interface", ["UPI", "India UPI"], ["Alipay_Plus"], "", ["https://www.npci.org.in"], "high")
        unionpay = EntityRecord("unionpay-international", "UnionPay International", ["UPI"], ["Alipay_Plus"], "", ["https://www.unionpayintl.com"], "high")
        catalog = [india_upi, unionpay]
        self.assertEqual(match_entities("NPCI takes UPI instant payments to Greece", "https://example.com/a", catalog), [india_upi])
        self.assertEqual(match_entities("UPI expands to Greece, enables instant money transfers", "https://example.com/b", catalog), [india_upi])
        self.assertEqual(match_entities("UnionPay International expands merchant acceptance in Greece", "https://example.com/c", catalog), [unionpay])
        self.assertEqual(match_entities("UPI product update", "https://example.com/d", catalog), [])

    def test_obsolete_event_entity_relations_are_superseded(self):
        existing = [
            {"id": "old", "fields": {"Event ID": "event-1", "Entity ID": "unionpay-international", "Role": "primary"}},
            {"id": "current", "fields": {"Event ID": "event-1", "Entity ID": "india-upi", "Role": "primary"}},
            {"id": "unrelated", "fields": {"Event ID": "event-2", "Entity ID": "unionpay-international", "Role": "primary"}},
        ]
        expected = [{"Event ID": "event-1", "Entity ID": "india-upi", "Role": "primary"}]
        self.assertEqual(superseded_entity_relation_updates(existing, expected), [{"id": "old", "fields": {
            "Role": "superseded",
            "Match Method": "catalog_reconciliation",
            "Confidence": "0",
        }}])

    def test_eventization_groups_same_entity_event(self):
        settings = AppSettings()
        catalog = [EntityRecord("wise", "Wise", [], ["WorldFirst"], "WISE.L", ["https://wise.com"], "high")]
        records = [
            {"id": "n1", "fields": {"Title": "Wise publishes annual earnings and guidance", "Source URL": {"link": "https://wise.com/a"}, "Publish Date": "2026-06-26", "Status": "已采纳"}},
            {"id": "n2", "fields": {"Title": "Wise annual results update profit guidance", "Source URL": {"link": "https://reuters.com/b"}, "Publish Date": "2026-06-27", "Status": "待处理"}},
        ]
        events = eventize_records(records, catalog, settings)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "Earnings")
        self.assertEqual(len(events[0].sources), 2)
        self.assertEqual(events[0].priority_candidate, "P0_Candidate")

    def test_eventization_groups_differently_worded_funding_coverage(self):
        settings = AppSettings()
        catalog = [EntityRecord("airwallex", "Airwallex", [], ["WorldFirst", "Antom"], "", ["https://airwallex.com"], "high")]
        records = [
            {"id": "n1", "fields": {"Title": "Airwallex raises $320M for planned AI expansion and growth in Israel", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-29", "Status": "已采纳"}},
            {"id": "n2", "fields": {"Title": "Airwallex raises $320m to build out AI financial software | FinanceAsia", "Source URL": {"link": "https://example.com/b"}, "Publish Date": "2026-06-29", "Status": "已采纳"}},
            {"id": "n3", "fields": {"Title": "Airwallex Secures $320 Million in Series H Funding, Valuation Hits $11 Billion", "Source URL": {"link": "https://example.com/c"}, "Publish Date": "2026-06-25", "Status": "已采纳"}},
        ]
        events = eventize_records(records, catalog, settings)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "Strategic_MA")
        self.assertEqual(len(events[0].sources), 3)

    def test_superseded_event_is_archived_into_active_canonical_event(self):
        events = [
            {"id": "row-old", "fields": {"Event ID": "event-old", "Status": "已采纳"}},
            {"id": "row-canonical", "fields": {"Event ID": "event-canonical", "Status": "已采纳"}},
            {"id": "row-unrelated", "fields": {"Event ID": "event-unrelated", "Status": "待处理"}},
        ]
        sources = [{"id": "source-old", "fields": {"Event ID": "event-old", "News Record ID": "news-1"}}]
        news = [{"id": "news-1", "fields": {"Event Case ID": "event-canonical"}}]
        updates = superseded_event_updates(events, sources, news, {"event-canonical"})
        self.assertEqual(updates, [{"id": "row-old", "fields": {
            "Status": "已归档",
            "Merged Into Event ID": "event-canonical",
            "Limitations": "Superseded by canonical Event merge into event-canonical; retained for audit history.",
        }}])

    def test_terminal_event_status_reconciliation_is_human_first(self):
        events = [
            {"id": "accepted", "fields": {"Event ID": "event-accepted", "Status": "待处理"}},
            {"id": "rejected", "fields": {"Event ID": "event-rejected", "Status": "已采纳"}},
            {"id": "duplicate", "fields": {"Event ID": "event-duplicate", "Status": "待处理"}},
            {"id": "pending", "fields": {"Event ID": "event-pending", "Status": "已采纳"}},
            {"id": "merged", "fields": {"Event ID": "event-merged", "Status": "已归档", "Merged Into Event ID": "event-accepted"}},
            {"id": "archived", "fields": {"Event ID": "event-archived", "Status": "已归档"}},
        ]
        sources = [
            {"fields": {"Event ID": "event-accepted", "News Record ID": "n-accepted"}},
            {"fields": {"Event ID": "event-rejected", "News Record ID": "n-rejected"}},
            {"fields": {"Event ID": "event-rejected", "News Record ID": "n-duplicate-a"}},
            {"fields": {"Event ID": "event-duplicate", "News Record ID": "n-duplicate-a"}},
            {"fields": {"Event ID": "event-duplicate", "News Record ID": "n-duplicate-b"}},
            {"fields": {"Event ID": "event-pending", "News Record ID": "n-pending"}},
            {"fields": {"Event ID": "event-merged", "News Record ID": "n-rejected"}},
            {"fields": {"Event ID": "event-archived", "News Record ID": "n-accepted"}},
        ]
        news = [
            {"id": "n-accepted", "fields": {"Status": "已采纳"}},
            {"id": "n-rejected", "fields": {"Status": "已拒绝"}},
            {"id": "n-duplicate-a", "fields": {"Status": "已重复"}},
            {"id": "n-duplicate-b", "fields": {"Status": "已重复"}},
            {"id": "n-pending", "fields": {"Status": "待处理"}},
        ]
        updates = {row["id"]: row["fields"]["Status"] for row in terminal_event_status_updates(events, sources, news)}
        self.assertEqual(updates, {"accepted": "已采纳", "rejected": "已拒绝", "duplicate": "已归档", "pending": "待处理"})
        self.assertNotIn("merged", updates)
        self.assertNotIn("archived", updates)

    def test_stale_ai_rejected_general_events_are_archived_safely(self):
        events = [
            {"id": "stale", "fields": {"Event ID": "event-stale", "Status": "待处理", "Event Type": "General", "Strategic Candidate": "no", "Priority Candidate": "P1"}},
            {"id": "current", "fields": {"Event ID": "event-current", "Status": "待处理", "Event Type": "General", "Strategic Candidate": "no", "Priority Candidate": "P1"}},
            {"id": "strategic", "fields": {"Event ID": "event-strategic", "Status": "待处理", "Event Type": "General", "Strategic Candidate": "yes", "Priority Candidate": "P0_Candidate"}},
            {"id": "typed", "fields": {"Event ID": "event-typed", "Status": "待处理", "Event Type": "Regulatory", "Strategic Candidate": "no", "Priority Candidate": "P1"}},
            {"id": "accepted", "fields": {"Event ID": "event-accepted", "Status": "待处理", "Event Type": "General", "Strategic Candidate": "no", "Priority Candidate": "P1"}},
        ]
        sources = [{"fields": {"Event ID": f"event-{name}", "News Record ID": f"news-{name}"}} for name in ("stale", "current", "strategic", "typed", "accepted")]
        news = [
            {"id": "news-stale", "fields": {"Status": "待处理", "AI Status": "已拒绝", "Publish Date": "2026-07-01"}},
            {"id": "news-current", "fields": {"Status": "待处理", "AI Status": "已拒绝", "Publish Date": "2026-07-03"}},
            {"id": "news-strategic", "fields": {"Status": "待处理", "AI Status": "已拒绝", "Publish Date": "2026-07-01"}},
            {"id": "news-typed", "fields": {"Status": "待处理", "AI Status": "已拒绝", "Publish Date": "2026-07-01"}},
            {"id": "news-accepted", "fields": {"Status": "已采纳", "AI Status": "已拒绝", "Publish Date": "2026-07-01"}},
        ]
        updates = stale_ai_rejected_event_updates(events, sources, news, date(2026, 7, 2))
        self.assertEqual(updates, [{"id": "stale", "fields": {"Status": "已归档"}}])
        self.assertEqual(news[0]["fields"]["Status"], "待处理")

    def test_event_source_grade_comes_from_domain_not_strategic_flag(self):
        settings = AppSettings()
        catalog = [EntityRecord("wise", "Wise", [], ["WorldFirst"], "WISE.L", ["https://wise.com"], "high")]
        records = [{"id": "n1", "fields": {"Title": "Wise publishes annual earnings", "Source URL": {"link": "https://www.reuters.com/business/wise-results"}, "Source Excerpt": "Wise reported higher cross-border volume.", "Publish Date": "2026-06-27", "Status": "待处理"}}]
        event = eventize_records(records, catalog, settings)[0]
        self.assertTrue(event.strategic_candidate)
        self.assertEqual(event.sources[0].source_grade, "T2")
        self.assertEqual(event.sources[0].source_excerpt, "Wise reported higher cross-border volume.")
        self.assertEqual(event.scores["source_grade"], 0.8)
        self.assertIn("WorldFirst", event.impact_hypothesis)
        self.assertIn("take rate", event.impact_hypothesis)
        self.assertIn("not a verified claim", event.impact_hypothesis)

    def test_deterministic_impact_mapping_is_review_prompt_not_claim(self):
        hypothesis = deterministic_impact_hypothesis("Product_Launch", ["Antom"])
        self.assertIn("merchant onboarding", hypothesis)
        self.assertIn("not a verified claim", hypothesis)

    def test_event_id_survives_publish_date_correction_for_same_source(self):
        settings = AppSettings()
        catalog = [EntityRecord("wise", "Wise", [], ["WorldFirst"], "WISE.L", ["https://wise.com"], "high")]
        event = eventize_records([{"id": "n1", "fields": {"Title": "Wise publishes annual earnings", "Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-25", "Status": "待处理"}}], catalog, settings)[0]
        generated_id = event.event_id
        reconciled = reconcile_event_ids([event], [{"fields": {"Event ID": "event-stable", "Source URL": {"link": "https://wise.com/results"}, "Content Hash": ""}}])
        self.assertNotEqual(generated_id, "event-stable")
        self.assertEqual(event.event_id, "event-stable")
        self.assertEqual(reconciled, 1)

    def test_critical_signal_requires_key_event_and_watched_entity(self):
        catalog = [EntityRecord("stripe", "Stripe", [], ["Antom"], "", ["https://stripe.com"], "high")]
        launch = SourceSignal("official", "Stripe launches agentic payment controls", "https://stripe.com/newsroom/launch")
        navigation = SourceSignal("official", "Stripe product documentation and support", "https://stripe.com/products")
        unrelated = SourceSignal("official", "OtherCo launches a new wallet", "https://other.example/news")
        self.assertTrue(is_critical_signal(launch, catalog))
        self.assertFalse(is_critical_signal(navigation, catalog))
        self.assertFalse(is_critical_signal(unrelated, catalog))
        old = SourceSignal("official", "Stripe launches agentic payment controls", "https://stripe.com/newsroom/old", publish_date="2026-05-01")
        self.assertFalse(is_critical_signal(old, catalog, lookback_days=7, now=datetime(2026, 6, 28, tzinfo=timezone.utc)))

    @patch("app.event_intelligence.add_records")
    @patch("app.event_intelligence.update_records")
    @patch("app.event_intelligence.list_records")
    def test_event_upsert_never_overwrites_human_review(self, list_rows: Mock, update: Mock, add: Mock):
        list_rows.return_value = [{"id": "row-1", "fields": {"Evidence ID": "evidence-1", "Extracted Fact": "Human verified fact", "Reviewer Status": "Verified", "Reviewer Notes": "Checked source text"}}]
        update.return_value = SimpleNamespace(status="sent", message="")
        _upsert(
            AppSettings(),
            SimpleNamespace(sheet_id="evidence"),
            "Evidence ID",
            [{"Evidence ID": "evidence-1", "Extracted Fact": "Generated title", "Reviewer Status": "Pending", "Reviewer Notes": "Generated note"}],
            preserve_when_reviewed=("Extracted Fact", "Reviewer Status", "Reviewer Notes"),
            review_field="Reviewer Status",
            unlocked_statuses=("", "pending"),
        )
        written = update.call_args.args[2][0]["fields"]
        self.assertEqual(written["Extracted Fact"], "Human verified fact")
        self.assertEqual(written["Reviewer Status"], "Verified")
        self.assertEqual(written["Reviewer Notes"], "Checked source text")
        add.assert_not_called()

    @patch("app.event_intelligence.add_records")
    @patch("app.event_intelligence.update_records")
    @patch("app.event_intelligence.list_records")
    def test_event_score_upsert_preserves_human_override(self, list_rows: Mock, update: Mock, add: Mock):
        list_rows.return_value = [{"id": "row-1", "fields": {"Event Score ID": "score-1", "Overall Score": "0.5", "Human Override": "0.9 - reviewer"}}]
        update.return_value = SimpleNamespace(status="sent", message="")
        _upsert(AppSettings(), SimpleNamespace(sheet_id="scores"), "Event Score ID", [{"Event Score ID": "score-1", "Overall Score": "0.6", "Human Override": ""}], preserve_nonempty=("Human Override",))
        written = update.call_args.args[2][0]["fields"]
        self.assertEqual(written["Overall Score"], "0.6")
        self.assertEqual(written["Human Override"], "0.9 - reviewer")
        add.assert_not_called()

    def test_llm_enrichment_is_schema_bounded_and_never_sets_final_p0(self):
        settings = AppSettings()
        catalog = [EntityRecord("wise", "Wise", [], ["WorldFirst"], "WISE.L", [], "high")]
        events = eventize_records([{"id": "n1", "fields": {"Title": "Wise announces a new service", "Source URL": {"link": "https://wise.com/a"}, "Publish Date": "2026-06-27", "Status": "已采纳"}}], catalog, settings)
        class FakeService:
            def execute(self, **_kwargs):
                value = EventLLMAnalysis(event_type="Product_Launch", business_lines=["WorldFirst", "invalid"], entities=["Wise"], summary="Wise launched a service.", gbss_relevance="Review comparable service operations.", severity_candidate="P0", confidence=0.8, evidence_needed=["official page"], limitations=["Scope not confirmed"])
                return SimpleNamespace(status="completed", value=value)
        enriched = enrich_events_with_llm(events, FakeService(), settings, "run")
        self.assertEqual(enriched[0].business_lines, ["WorldFirst"])
        self.assertEqual(enriched[0].priority_candidate, "P0_Candidate")
        self.assertFalse(hasattr(enriched[0], "final_priority"))

    def test_publication_gate_uses_accepted_news_as_the_human_gate(self):
        fields = {"Status": "待处理", "Accepted News Count": "1", "Primary Source URL": {"link": "https://example.com"}, "Publish Date": "2026-06-27", "Final Priority": "P1"}
        self.assertTrue(publication_eligible(fields))
        fields["Accepted News Count"] = "0"
        self.assertFalse(publication_eligible(fields))

    def test_event_status_is_derived_from_news_review(self):
        pending = EventSourceCandidate("news-1", "Title", "https://example.com", "example.com", "2026-06-27", "official", False)
        accepted = EventSourceCandidate("news-2", "Title", "https://example.com/2", "example.com", "2026-06-27", "official", True)
        self.assertEqual(event_status_from_news([pending], "已采纳"), "待处理")
        self.assertEqual(event_status_from_news([pending, accepted], "待处理"), "已采纳")
        self.assertEqual(event_status_from_news([pending], "已归档"), "待处理")
        self.assertEqual(event_status_from_news([pending], "已归档", "event-canonical"), "已归档")

    def test_critical_launchd_plist_has_six_intervals(self):
        payload = build_critical_scan_plist(Path("/tmp/project"), "/tmp/python", [1, 5, 9, 13, 17, 21]).decode("utf-8")
        self.assertEqual(payload.count("<key>Hour</key>"), 6)

    @patch("app.notifications.httpx.post")
    def test_event_action_card_uses_real_mobile_mentions(self, post: Mock):
        post.return_value = response(200, {})
        result = send_dingtalk_action_card("https://example.com/robot", "", "Review", "Event", "Open", "https://example.com/review", "60123456789")
        self.assertEqual(result.status, "sent")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "actionCard")
        self.assertEqual(payload["at"]["atMobiles"], ["60123456789"])
        self.assertIn("@60123456789", payload["actionCard"]["text"])

    @patch("app.notifications.httpx.post")
    def test_event_action_card_rejects_http_200_robot_error(self, post: Mock):
        post.return_value = response(200, {"errcode": 310000, "errmsg": "keywords not in content"})
        result = send_dingtalk_action_card("https://example.com/robot", "", "Review", "Event", "Open", "https://example.com/review")
        self.assertEqual(result.status, "failed")
        self.assertIn("310000", result.message)
        self.assertIn("keywords not in content", result.message)

    @patch("app.event_alerts.add_records")
    @patch("app.event_alerts.send_dingtalk_action_card")
    @patch("app.event_alerts.list_records")
    def test_event_alert_dedupes_by_event_and_level(self, list_rows: Mock, send: Mock, add: Mock):
        list_rows.return_value = [{"fields": {"Event ID": "event-1", "Alert Level": "P0_Candidate", "Dedupe Key": "legacy-key-with-source-count"}}]
        source = EventSourceCandidate("news-1", "Wise FY26 Results", "https://wise.com/results", "wise.com", "2026-06-25", "official", False, "T1")
        event = EventCandidate("event-1", source.title, "Earnings", ["WorldFirst"], [], [source], "2026-06-25", True, 0.9, {}, 0.9, "P0_Candidate", source.title, "Review", "Boundary")
        self.assertEqual(send_event_alerts(AppSettings(), SimpleNamespace(alert_log=SimpleNamespace(sheet_id="alerts")), [event]), 0)
        send.assert_not_called()
        add.assert_not_called()

    def test_review_reminder_content_reports_event_gates(self):
        content = build_review_content(3, 20, 7, 9, "2026-06-28", ["Wise FY26 Results"])
        self.assertIn("Publish Date = 2026-06-28", content)
        self.assertIn("昨日要闻待处理：**3**", content)
        self.assertIn("News 待审关联 Event Case：**20**", content)
        self.assertIn("P0 Candidate：**7**", content)
        self.assertIn("AI Status 已采纳 / 已拒绝 / 已重复", content)
        self.assertIn("Wise FY26 Results", content)

    @patch("scripts.daily_remind.list_records")
    def test_review_state_only_includes_previous_day_pending_event_news(self, list_rows: Mock):
        settings = AppSettings()
        settings.event_intelligence.enabled = True
        settings.dingtalk_ai_table.sheet_id = "news"
        settings.dingtalk_ai_table.event_cases_sheet_id = "events"
        rows = {
            "news": [
                {"fields": {"Title": "Eligible", "Review Status": "待处理", "Publish Date": "2026-06-28", "Event Case ID": "event-1", "AI Status": "已采纳"}},
                {"fields": {"Title": "Old", "Review Status": "待处理", "Publish Date": "2026-06-27", "Event Case ID": "event-2"}},
                {"fields": {"Title": "Missing", "Review Status": "待处理", "Event Case ID": "event-3"}},
                {"fields": {"Title": "Unmatched", "Review Status": "待处理", "Publish Date": "2026-06-28"}},
                {"fields": {"Title": "Accepted", "Review Status": "已采纳", "Publish Date": "2026-06-28", "Event Case ID": "event-4"}},
            ],
            "events": [{"fields": {"Event ID": "event-1", "Priority Candidate": "P0_Candidate", "Strategic Candidate": "yes"}}],
        }
        list_rows.side_effect = lambda _dingtalk, table: rows[table.sheet_id]
        state = collect_review_state(settings, datetime(2026, 6, 29, 9, tzinfo=timezone.utc))
        self.assertEqual(state.review_date, "2026-06-28")
        self.assertEqual(state.ai_missing, 0)
        self.assertEqual([row["Title"] for row in state.pending_news], ["Eligible"])
        self.assertEqual(len(state.related_events), 1)
        self.assertEqual(state.p0_candidates, 1)
        self.assertEqual(state.strategic_candidates, 1)
        self.assertEqual((state.ai_accept, state.ai_reject, state.ai_duplicate), (1, 0, 0))
        self.assertEqual(state.excluded, {"not_pending": 1, "wrong_date": 1, "missing_date": 1, "unmatched_event": 1})

    @patch("scripts.daily_remind.list_records")
    def test_review_reminder_fails_closed_when_ai_prerequisite_is_missing(self, list_rows: Mock):
        settings = AppSettings()
        settings.event_intelligence.enabled = False
        list_rows.return_value = [
            {"fields": {"Title": "Unprocessed", "Review Status": "待处理", "Publish Date": "2026-06-28", "Event Case ID": "event-1"}}
        ]
        state = collect_review_state(settings, datetime(2026, 6, 29, 9, tzinfo=timezone.utc))
        self.assertEqual(state.ai_missing, 1)
        self.assertIn("1/1", review_readiness_error(state))

    def test_cutover_readiness_fails_closed_without_lineage_tables(self):
        settings = AppSettings()
        settings.dingtalk_ai_table.event_cases_sheet_id = ""
        failures = readiness_failures(settings)
        self.assertEqual(failures, ["v3.1 schema and lineage sheets must be configured before cutover"])

    def test_critical_scan_only_eventizes_recent_news(self):
        records = [
            {"id": "recent", "fields": {"Publish Date": "2026-06-24"}},
            {"id": "old", "fields": {"Publish Date": "2026-05-20"}},
            {"id": "missing", "fields": {}},
        ]
        selected = recent_news_records(records, 7, "Asia/Kuala_Lumpur", now=datetime(2026, 6, 28, tzinfo=timezone.utc))
        self.assertEqual([row["id"] for row in selected], ["recent"])

    @patch("app.event_weekly.list_records")
    def test_event_weekly_input_uses_live_accepted_news_without_event_or_claim_review(self, list_rows: Mock):
        settings = AppSettings()
        settings.event_intelligence.weekly_input_mode = "event_cases"
        settings.dingtalk_ai_table.sheet_id = "news"
        settings.dingtalk_ai_table.event_cases_sheet_id = "events"
        settings.dingtalk_ai_table.event_sources_sheet_id = "sources"
        settings.dingtalk_ai_table.evidence_bank_sheet_id = "evidence"
        settings.dingtalk_ai_table.claim_ledger_sheet_id = "claims"
        rows = {
            "events": [{"id": "row-event", "fields": {"Event ID": "event-1", "Event Title": "Wise annual results", "Event Type": "Earnings", "Business Lines": "WorldFirst", "Status": "待处理", "Accepted News Count": "0", "Primary Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-27", "Final Priority": "P1", "Relevance Score": "0.9"}}],
            "sources": [{"id": "row-source", "fields": {"Event Source ID": "source-1", "Event ID": "event-1", "News Record ID": "news-1", "Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-27"}}],
            "evidence": [{"id": "row-evidence", "fields": {"Evidence ID": "evidence-1", "Event ID": "event-1", "Reviewer Status": "Pending"}}],
            "claims": [{"id": "row-claim", "fields": {"Claim ID": "claim-1", "Event ID": "event-1", "Reviewer Status": "Draft"}}],
            "news": [{"id": "news-1", "fields": {"Review Status": "已采纳"}}],
        }
        list_rows.side_effect = lambda _dingtalk, table: rows[table.sheet_id]
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Weekly Intelligence Sent At",))
        self.assertEqual(result.mode, "event_cases")
        self.assertEqual(result.report_records[0]["fields"]["Event ID"], "event-1")
        self.assertEqual(result.linked_news_ids, ["news-1"])
        rows["news"][0]["fields"]["Weekly Headlines Sent At"] = "2026-06-28"
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Daily Report Sent At", "Weekly Headlines Sent At"))
        self.assertEqual(result.report_records, [])
        rows["sources"].append({"id": "row-source-2", "fields": {"Event Source ID": "source-2", "Event ID": "event-1", "News Record ID": "news-2", "Source URL": {"link": "https://example.com/wise-results"}, "Publish Date": "2026-06-27"}})
        rows["news"].append({"id": "news-2", "fields": {"Review Status": "已采纳"}})
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Daily Report Sent At", "Weekly Headlines Sent At"))
        self.assertEqual(result.report_records, [])
        rows["sources"].pop()
        rows["news"].pop()
        rows["news"][0]["fields"].pop("Weekly Headlines Sent At")
        rows["news"][0]["fields"]["Review Status"] = "待处理"
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Weekly Intelligence Sent At",))
        self.assertEqual(result.report_records, [])
        rows["news"][0]["fields"]["Review Status"] = "已采纳"
        rows["events"][0]["fields"]["Status"] = "已归档"
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Weekly Intelligence Sent At",))
        self.assertEqual(result.report_records, [])

    def test_event_lineage_is_visible_in_all_management_outputs(self):
        record = self.event_report_record()
        headlines = build_headlines_content([record], "Daily", "JUN 21 - JUN 27")
        report = build_competitor_report_content([record], "JUN 21 - JUN 27")
        svg = build_one_page_report_svg([record], "JUN 21 - JUN 27")
        for output in (report, svg):
            self.assertIn("event-1", output)
            self.assertIn("evidence-1", output)
            self.assertIn("claim-1", output)
            self.assertIn("https://wise.com/results", output)
            self.assertIn("2026-06-27", output)
        self.assertIn("Finance & Contact Center Daily Report", headlines)
        self.assertIn("Publish Date: 2026-06-27", headlines)
        self.assertIn("https://wise.com/results", headlines)
        self.assertNotIn("event-1", headlines)
        self.assertNotIn("evidence-1", headlines)
        self.assertNotIn("claim-1", headlines)
        report_data = build_report_data([record], "JUN 21 - JUN 27", "Wise results")
        card = report_data["priorityNewsCards"][0]
        self.assertEqual(card["eventSourceIds"], "event-source-1")
        self.assertEqual(card["limitations"], "Company guidance is forward-looking.")

    def test_empty_daily_report_is_readable_and_unambiguous(self):
        content = build_empty_daily_report_content("2026-07-04")
        self.assertIn("Finance & Contact Center Daily Report", content)
        self.assertIn("No newly accepted external events today.", content)
        self.assertIn("completed successfully", content)
        self.assertNotIn("Event ID", content)
        self.assertNotIn("@", content)

    def test_v3_1_schema_has_seven_business_sheets(self):
        self.assertEqual(len(SHEET_DEFINITIONS), 7)
        self.assertIn("Daily Report Sent At", {field["name"] for field in EVENT_CASE_FIELDS})
        self.assertIn("Merged Into Event ID", {field["name"] for field in EVENT_CASE_FIELDS})
        self.assertIn("Daily Report Sent At", {field["name"] for field in NEWS_LINEAGE_FIELDS})
        self.assertIn("Source Excerpt", {field["name"] for field in EVENT_SOURCE_FIELDS})
        self.assertIn("Source Excerpt", {field["name"] for field in NEWS_LINEAGE_FIELDS})

    def test_run_log_retains_pending_audit_and_recovers_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunLogStore(Path(temp) / "settings.sqlite3")
            run_id = store.start("job")
            store.append_pending_audit(run_id, {"stage_code": "x"})
            store.finish(run_id, "failed", metadata={"other": True})
            row = store.list_recent(1)[0]
            self.assertEqual(row["metadata"]["pending_audit_events"][0]["stage_code"], "x")
            self.assertTrue(row["metadata"]["other"])


if __name__ == "__main__":
    unittest.main()
