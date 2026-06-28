from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch

import httpx
from pydantic import BaseModel

from app.adapters import AdapterRequest, AlphaVantageAdapter, FirecrawlAdapter, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter, SourceSignal
from app.cost_control import BudgetController, MemoryUsageLedger, calculate_cost, estimate_cost
from app.event_intelligence import EntityRecord, EventCandidate, EventLLMAnalysis, EventSourceCandidate, _upsert, deterministic_impact_hypothesis, enrich_events_with_llm, event_status_from_news, eventize_records, infer_event_type, is_critical_signal, machine_priority, publication_eligible, reconcile_event_ids, same_event, validate_final_p0
from types import SimpleNamespace
from app.llm_service import LLMService
from app.models import AppSettings, OpenAIServiceSettings
from app.run_logs import RunLogStore
from app.scheduler import build_critical_scan_plist
from app.notifications import send_dingtalk_action_card
from app.event_alerts import send_event_alerts
from app.event_weekly import load_weekly_input
from app.event_tables import EVENT_CASE_FIELDS, EVENT_SOURCE_FIELDS, NEWS_LINEAGE_FIELDS, SHEET_DEFINITIONS
from app.gbss_report import build_report_data
from app.publish_format import build_competitor_report_content, build_headlines_content
from app.report_visual import build_one_page_report_svg
from scripts.run_v3_1_evaluation import evaluate
from scripts.daily_remind import build_review_content
from scripts.cutover_v3_1 import readiness_failures
from scripts.critical_event_scan import recent_news_records


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
        self.assertEqual(event_status_from_news([pending], "已归档"), "已归档")

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
        content = build_review_content(3, 20, 7, 9)
        self.assertIn("News 待审关联 Event Case：**20**", content)
        self.assertIn("P0 Candidate：**7**", content)
        self.assertIn("只需审核 News", content)

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
        rows["news"][0]["fields"]["Review Status"] = "待处理"
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Weekly Intelligence Sent At",))
        self.assertEqual(result.report_records, [])

    def test_event_lineage_is_visible_in_all_management_outputs(self):
        record = self.event_report_record()
        headlines = build_headlines_content([record], "Daily", "JUN 21 - JUN 27")
        report = build_competitor_report_content([record], "JUN 21 - JUN 27")
        svg = build_one_page_report_svg([record], "JUN 21 - JUN 27")
        for output in (headlines, report, svg):
            self.assertIn("event-1", output)
            self.assertIn("evidence-1", output)
            self.assertIn("claim-1", output)
            self.assertIn("https://wise.com/results", output)
            self.assertIn("2026-06-27", output)
        self.assertIn("Finance & Contact Center Daily Report", headlines)
        report_data = build_report_data([record], "JUN 21 - JUN 27", "Wise results")
        card = report_data["priorityNewsCards"][0]
        self.assertEqual(card["eventSourceIds"], "event-source-1")
        self.assertEqual(card["limitations"], "Company guidance is forward-looking.")

    def test_v3_1_schema_has_seven_business_sheets(self):
        self.assertEqual(len(SHEET_DEFINITIONS), 7)
        self.assertIn("Daily Report Sent At", {field["name"] for field in EVENT_CASE_FIELDS})
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
