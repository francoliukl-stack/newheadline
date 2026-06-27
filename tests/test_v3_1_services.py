from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from pydantic import BaseModel

from app.adapters import AdapterRequest, AlphaVantageAdapter, FirecrawlAdapter, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter
from app.cost_control import BudgetController, MemoryUsageLedger, calculate_cost, estimate_cost
from app.event_intelligence import EntityRecord, EventLLMAnalysis, enrich_events_with_llm, eventize_records, infer_event_type, machine_priority, publication_eligible, same_event, validate_final_p0
from types import SimpleNamespace
from app.llm_service import LLMService
from app.models import AppSettings, OpenAIServiceSettings
from app.run_logs import RunLogStore
from app.scheduler import build_critical_scan_plist
from app.notifications import send_dingtalk_action_card
from app.event_weekly import load_weekly_input
from app.event_tables import SHEET_DEFINITIONS


def response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.com"))


class SampleOutput(BaseModel):
    label: str
    confidence: float


class V31ServiceTests(unittest.TestCase):
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
        result = LLMService(config, budget, ledger, client=client).execute(task="classify", schema=SampleOutput, context={"title": "Results"}, budget_scope="ingest")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.value.label, "Earnings")
        self.assertEqual(ledger.records()[-1]["Status"], "completed")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")

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
        get.return_value._content = b"<rss><channel><item><title>Wise publishes annual results</title><link>https://wise.com/results</link><pubDate>2026-06-27</pubDate></item></channel></rss>"
        get.return_value.headers["content-type"] = "application/xml"
        rows = OfficialSourceAdapter().collect(AdapterRequest(urls=["https://wise.com/feed"], limit=5))
        self.assertEqual(rows[0].metadata["source_grade"], "T1")

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

    def test_llm_enrichment_is_schema_bounded_and_never_sets_final_p0(self):
        settings = AppSettings()
        catalog = [EntityRecord("wise", "Wise", [], ["WorldFirst"], "WISE.L", [], "high")]
        events = eventize_records([{"id": "n1", "fields": {"Title": "Wise announces a new service", "Source URL": {"link": "https://example.com/a"}, "Publish Date": "2026-06-27", "Status": "已采纳"}}], catalog, settings)
        class FakeService:
            def execute(self, **_kwargs):
                value = EventLLMAnalysis(event_type="Product_Launch", business_lines=["WorldFirst", "invalid"], entities=["Wise"], summary="Wise launched a service.", gbss_relevance="Review comparable service operations.", severity_candidate="P0", confidence=0.8, evidence_needed=["official page"], limitations=["Scope not confirmed"])
                return SimpleNamespace(status="completed", value=value)
        enriched = enrich_events_with_llm(events, FakeService(), settings, "run")
        self.assertEqual(enriched[0].business_lines, ["WorldFirst"])
        self.assertEqual(enriched[0].priority_candidate, "P0_Candidate")
        self.assertFalse(hasattr(enriched[0], "final_priority"))

    def test_publication_gate_requires_dual_review_and_lineage(self):
        fields = {"Status": "已采纳", "Accepted News Count": "1", "Primary Source URL": {"link": "https://example.com"}, "Publish Date": "2026-06-27", "Final Priority": "P1"}
        self.assertTrue(publication_eligible(fields))
        fields["Accepted News Count"] = "0"
        self.assertFalse(publication_eligible(fields))

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

    @patch("app.event_weekly.list_records")
    def test_event_weekly_input_requires_verified_evidence_and_approved_claim(self, list_rows: Mock):
        settings = AppSettings()
        settings.event_intelligence.weekly_input_mode = "event_cases"
        settings.dingtalk_ai_table.event_cases_sheet_id = "events"
        settings.dingtalk_ai_table.event_sources_sheet_id = "sources"
        settings.dingtalk_ai_table.evidence_bank_sheet_id = "evidence"
        settings.dingtalk_ai_table.claim_ledger_sheet_id = "claims"
        rows = {
            "events": [{"id": "row-event", "fields": {"Event ID": "event-1", "Event Title": "Wise annual results", "Event Type": "Earnings", "Business Lines": "WorldFirst", "Status": "已采纳", "Accepted News Count": "1", "Primary Source URL": {"link": "https://wise.com/results"}, "Publish Date": "2026-06-27", "Final Priority": "P1", "Relevance Score": "0.9"}}],
            "sources": [{"id": "row-source", "fields": {"Event Source ID": "source-1", "Event ID": "event-1", "News Record ID": "news-1"}}],
            "evidence": [{"id": "row-evidence", "fields": {"Evidence ID": "evidence-1", "Event ID": "event-1", "Reviewer Status": "Verified"}}],
            "claims": [{"id": "row-claim", "fields": {"Claim ID": "claim-1", "Event ID": "event-1", "Reviewer Status": "Approved"}}],
        }
        list_rows.side_effect = lambda _dingtalk, table: rows[table.sheet_id]
        result = load_weekly_input(settings, datetime(2026, 6, 27, tzinfo=timezone.utc), days=7, recent_count=0, include_sent=False, max_items=10, sent_fields=("Weekly Intelligence Sent At",))
        self.assertEqual(result.mode, "event_cases")
        self.assertEqual(result.report_records[0]["fields"]["Event ID"], "event-1")
        self.assertEqual(result.linked_news_ids, ["news-1"])

    def test_v3_1_schema_has_seven_business_sheets(self):
        self.assertEqual(len(SHEET_DEFINITIONS), 7)

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
