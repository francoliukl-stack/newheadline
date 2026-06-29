import tempfile
import unittest
import httpx
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.dingtalk_ai_table import (
    extract_base_id,
    normalize_news_record,
    normalize_url_cell,
    retryable_request,
    resolve_operator_id,
    status_name,
    validate_ai_table_settings,
)
from app.article_titles import shorten_title, title_from_html, title_word_count
from app.config_sheet import CONFIG_FIELDS, apply_config_items, default_config_items
from app.audit_trail import AUDIT_TRAIL_FIELDS, build_audit_fields
from app.detect_sources import (
    DETECT_SOURCE_FIELDS,
    build_detect_query_plan,
    build_query_from_detect_records,
    select_balanced_candidates,
    default_detect_source_records,
    fallback_detect_query,
)
from app.insights import INSIGHT_FIELDS
from app.gbss_report import (
    SCORING_MODEL,
    build_report_data,
    calculate_priority_score,
    derive_priority,
    infer_business_relevance,
)
from app.models import AppSettings
from app.market_research_plan import build_market_led_research_plan
from app.openai_deep_research import extract_phrases, research_prompt
from app.publish_dates import date_from_html, date_from_url, parse_date
from app.publish_format import (
    build_competitor_report_content,
    build_report_notification_content,
    is_accepted_record,
    report_content_to_document_markdown,
)
from app.report_visual import build_one_page_report_svg, one_page_report_markdown
from app.research_topics import RESEARCH_TOPIC_FIELDS, current_and_next_topics, default_topic_records
from app.research_production import (
    CLAIM_LEDGER_FIELDS,
    EVIDENCE_BANK_FIELDS,
    RESEARCH_QUEUE_FIELDS,
    RESEARCH_RESULT_FIELDS,
    build_research_queue_fields,
    evidence_fields_from_news,
    research_quality_gate,
    source_tier,
    validate_synthesis_payload,
)
from app.dedupe import find_duplicate_clusters, is_article_url, title_similarity
from app.provider_health import check_provider
from app.notifications import (
    build_fetch_completion_message,
    build_dingtalk_ai_table_url,
    build_dingtalk_approval_url,
    dingtalk_signed_url,
    send_daily_fetch_notification,
    send_ingest_completion_notification,
    parse_at_mobiles,
    with_mobile_mentions,
)
from app.run_logs import RunLogStore
from app.scheduler import build_launchd_plist, next_run, schedule_status
from app.weekly_report import select_weekly_records
from app.search_providers import (
    ProviderNotConfigured,
    SearchQuery,
    build_fallback_provider,
    build_provider,
)
from app.secrets import SecretStore
from app.storage import MASK, SettingsStore


class SettingsTests(unittest.TestCase):
    def make_store(self, tmp: str) -> SettingsStore:
        return SettingsStore(
            Path(tmp) / "settings.sqlite3",
            SecretStore(Path(tmp) / "secrets.json", service="weekly-headlines-settings-test", use_keychain=False),
        )

    def test_defaults_include_prd_taxonomy(self):
        settings = AppSettings()
        self.assertIn("Finance", settings.taxonomy.sections)
        self.assertIn("Contact Center", settings.taxonomy.sections)
        self.assertIn("M&A", settings.taxonomy.labels)
        self.assertEqual(settings.taxonomy.default_status, "待处理")
        self.assertGreaterEqual(len(settings.source_settings.sources), 50)

    def test_detect_sources_seed_companies_and_domains(self):
        settings = AppSettings()
        records = default_detect_source_records(settings)
        names = {record["Name"] for record in records}
        self.assertIn("Stripe", names)
        self.assertIn("Sierra.ai", names)
        self.assertIn("Bettr", names)
        self.assertIn("Ant Bank HK", names)
        self.assertIn("AlipayHK", names)
        self.assertIn("The Paypers", names)
        self.assertIn("GBSS Core Businesses", names)
        self.assertIn("reuters.com", names)
        self.assertIn("Source ID", {field["name"] for field in DETECT_SOURCE_FIELDS})

    def test_detect_source_records_build_query(self):
        query, domains = build_query_from_detect_records([
            {"fields": {"Name": "Stripe", "Aliases": "Stripe Payments", "Domains": "stripe.com", "Priority": 2, "Enabled": "true"}},
            {"fields": {"Name": "DisabledCo", "Keywords": "ignore me", "Enabled": "false"}},
            {"fields": {"Name": "Voice AI", "Keywords": "Contact Center AI", "Priority": 1, "Enabled": "true"}},
        ])
        self.assertIn('"Contact Center AI"', query)
        self.assertIn("Stripe", query)
        self.assertNotIn("DisabledCo", query)
        self.assertEqual(domains, ["stripe.com"])

    def test_fallback_detect_query_uses_settings(self):
        query, domains = fallback_detect_query(AppSettings())
        self.assertIn("Antom", query)
        self.assertIn('"Voice AI"', query)
        self.assertNotIn("reuters.com", query)
        self.assertIn("stripe.com", domains)

    def test_detect_source_query_plan_splits_market_companies_and_sources(self):
        plan = build_detect_query_plan([
            {"fields": {"Type": "topic", "Section": "Finance", "Keywords": "payments, fintech", "Aliases": "stablecoin settlement", "Priority": 1, "Enabled": "true"}},
            {"fields": {"Type": "company", "Section": "Finance", "Name": "Stripe", "Aliases": "Stripe Payments", "Priority": 1, "Enabled": "true"}},
            {"fields": {"Type": "company", "Section": "Contact Center", "Name": "Deepgram", "Priority": 1, "Enabled": "true"}},
            {"fields": {"Type": "source_domain", "Section": "News", "Name": "finextra.com", "Domains": "finextra.com", "Priority": 1, "Enabled": "true"}},
            {"fields": {"Type": "trusted_source", "Section": "Finance", "Name": "The Paypers", "Domains": "thepaypers.com", "Priority": 1, "Enabled": "true"}},
        ], date(2026, 6, 21), company_chunk_size=1)
        self.assertEqual([item.key for item in plan], [
            "finance_market",
            "finance_companies_1",
            "finance_trusted_sources",
            "contact_center_companies_1",
        ])
        self.assertIn('"stablecoin settlement"', plan[0].text)
        self.assertIn("Stripe", plan[1].text)
        self.assertEqual(plan[2].text, "site:thepaypers.com")
        self.assertIn("finextra.com", plan[-1].domains)
        self.assertTrue(all(len(item.text) < 500 for item in plan))

    def test_candidate_selection_round_robins_query_groups(self):
        records = []
        for group in ("finance", "core", "contact"):
            for index in range(4):
                records.append({
                    "search_group": group,
                    "source": "thepaypers.com" if index == 3 else "example.com",
                    "url": f"https://example.com/{group}/{index}",
                })
        selected = select_balanced_candidates(records, {"thepaypers.com"}, max_per_group=3, total_limit=6)
        self.assertEqual([row["search_group"] for row in selected], ["finance", "core", "contact", "finance", "core", "contact"])
        self.assertTrue(all(row["source"] == "thepaypers.com" for row in selected[:3]))

    def test_sensitive_fields_are_masked_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            settings = AppSettings()
            settings.lark.app_secret = "secret-value"
            settings.search_provider.api_key = "search-secret"
            settings.search_provider.brave_api_key = "brave-secret"
            settings.search_provider.serpapi_api_key = "serpapi-secret"
            saved = store.save(settings)
            self.assertEqual(saved.lark.app_secret, MASK)
            self.assertEqual(saved.search_provider.api_key, MASK)
            self.assertEqual(saved.search_provider.brave_api_key, MASK)
            self.assertEqual(saved.search_provider.serpapi_api_key, MASK)
            unmasked = store.load(masked=False)
            self.assertEqual(unmasked.lark.app_secret, "secret-value")
            self.assertEqual(unmasked.search_provider.api_key, "search-secret")
            self.assertEqual(unmasked.search_provider.brave_api_key, "brave-secret")
            self.assertEqual(unmasked.search_provider.serpapi_api_key, "serpapi-secret")

    def test_openai_research_key_is_masked_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            settings = AppSettings()
            settings.openai_research.api_key = "openai-secret"
            saved = store.save(settings)
            self.assertEqual(saved.openai_research.api_key, MASK)
            self.assertEqual(store.load(masked=False).openai_research.api_key, "openai-secret")

    def test_mask_preserves_existing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            settings = AppSettings()
            settings.lark.app_secret = "secret-value"
            store.save(settings)
            masked = store.load(masked=True)
            masked.system.system_name = "Changed"
            store.save(masked)
            self.assertEqual(store.load(masked=False).lark.app_secret, "secret-value")

    def test_next_run_uses_utc8_weekdays(self):
        schedule = AppSettings().schedule.daily_fetch
        now = datetime(2026, 5, 24, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(next_run(schedule, "Asia/Shanghai", now), "2026-05-25T02:00+08:00")

    def test_launchd_plist_contains_calendar_interval(self):
        settings = AppSettings().schedule.daily_remind
        plist = build_launchd_plist(
            "com.example.test",
            Path("/tmp/project/scripts/daily_remind.py"),
            settings,
            "/usr/bin/python3",
        ).decode("utf-8")
        self.assertIn("<key>StartCalendarInterval</key>", plist)
        self.assertIn("<integer>9</integer>", plist)

    def test_daily_health_check_is_scheduled_every_day(self):
        settings = AppSettings().schedule.daily_health_check
        self.assertEqual(settings.hour, 0)
        self.assertEqual(settings.minute, 0)
        self.assertEqual(settings.weekdays, [0, 1, 2, 3, 4, 5, 6])

    def test_ingest_and_review_run_every_day(self):
        schedule = AppSettings().schedule
        self.assertEqual(schedule.daily_fetch.weekdays, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(schedule.daily_remind.weekdays, [0, 1, 2, 3, 4, 5, 6])

    def test_daily_report_and_weekly_intelligence_schedules(self):
        schedule = AppSettings().schedule
        self.assertFalse(schedule.daily_publish.enabled)
        self.assertEqual(schedule.weekly_research_plan.hour, 9)
        self.assertEqual(schedule.weekly_research_plan.minute, 0)
        self.assertEqual(schedule.weekly_research_plan.weekdays, [5])
        self.assertEqual(schedule.weekly_deep_research.hour, 14)
        self.assertEqual(schedule.weekly_deep_research.minute, 0)
        self.assertEqual(schedule.weekly_deep_research.weekdays, [6])
        self.assertEqual(schedule.weekly_draft.hour, 12)
        self.assertEqual(schedule.weekly_draft.minute, 0)
        self.assertEqual(schedule.weekly_draft.weekdays, [6])
        self.assertEqual(schedule.weekly_headlines.hour, 12)
        self.assertEqual(schedule.weekly_headlines.minute, 0)
        self.assertEqual(schedule.weekly_headlines.weekdays, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(schedule.weekly_publish.hour, 12)
        self.assertEqual(schedule.weekly_publish.minute, 0)
        self.assertEqual(schedule.weekly_publish.weekdays, [0])
        status = schedule_status(schedule, "Asia/Shanghai",)
        self.assertIn("weekly_research_plan", status)
        self.assertIn("weekly_deep_research", status)
        self.assertIn("weekly_draft", status)
        self.assertIn("weekly_headlines", status)
        self.assertIn("weekly_publish", status)

    def test_search_provider_defaults_support_unattended_cache(self):
        settings = AppSettings()
        self.assertEqual(settings.search_provider.provider, "openclaw_cache")
        self.assertFalse(settings.search_provider.use_codex_search)

    def test_openclaw_cache_provider_reads_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            seed.write_text(
                '[{"title":"One","url":"https://example.com/1","source":"example.com"},'
                '{"title":"Two","url":"https://example.com/2","source":"example.com"}]',
                encoding="utf-8",
            )
            settings = AppSettings()
            settings.search_provider.provider = "manual_seed"
            settings.search_provider.manual_seed_path = str(seed)
            settings.search_provider.max_results_per_query = 1
            provider = build_provider(settings.search_provider)
            results = provider.search(SearchQuery(text="x", section="Finance", domains=[]))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "One")

    def test_codex_search_provider_reads_interactive_bridge_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "codex.json"
            seed.write_text('[{"title":"Codex result","url":"https://example.com/codex","source":"example.com"}]', encoding="utf-8")
            settings = AppSettings()
            settings.search_provider.provider = "codex_search"
            settings.search_provider.codex_search_cache_path = str(seed)
            provider = build_provider(settings.search_provider)
            results = provider.search(SearchQuery(text="x", section="Finance", domains=[]))
            self.assertEqual(results[0].title, "Codex result")

    @patch("app.search_providers.httpx.get")
    def test_gdelt_provider_reads_public_api_articles(self, get: Mock):
        response = Mock()
        response.json.return_value = {
            "articles": [{
                "title": "Fintech result",
                "url": "https://example.com/fintech",
                "domain": "example.com",
                "seendate": "20260531T123000Z",
            }]
        }
        get.return_value = response
        settings = AppSettings()
        settings.search_provider.provider = "gdelt_doc"
        provider = build_provider(settings.search_provider)
        results = provider.search(SearchQuery(text="fintech", section="Finance", domains=[]))
        self.assertEqual(results[0].source, "example.com")
        self.assertEqual(results[0].published_at, "20260531T123000Z")

    @patch("app.search_providers.httpx.get")
    def test_serpapi_provider_reads_google_news_results(self, get: Mock):
        response = Mock()
        response.json.return_value = {
            "news_results": [{
                "title": "SerpApi result",
                "link": "https://example.com/serpapi",
                "source": "Example",
                "date": "1 hour ago",
            }]
        }
        get.return_value = response
        settings = AppSettings()
        settings.search_provider.provider = "serpapi"
        settings.search_provider.serpapi_api_key = "secret"
        provider = build_provider(settings.search_provider)
        results = provider.search(SearchQuery(text="fintech", section="Finance", domains=[]))
        self.assertEqual(results[0].title, "SerpApi result")
        self.assertEqual(results[0].source, "Example")

    @patch("app.search_providers.httpx.get")
    def test_brave_search_provider_reads_news_results(self, get: Mock):
        response = Mock()
        response.json.return_value = {
            "results": [{
                "title": "Brave result",
                "url": "https://example.com/brave",
                "source": "Example",
                "description": "News snippet",
                "age": "1 hour ago",
            }]
        }
        get.return_value = response
        settings = AppSettings()
        settings.search_provider.provider = "brave_search"
        settings.search_provider.brave_api_key = "secret"
        provider = build_provider(settings.search_provider)
        results = provider.search(SearchQuery(text="fintech", section="Finance", domains=[]))
        self.assertEqual(results[0].title, "Brave result")
        self.assertEqual(results[0].source, "Example")
        self.assertEqual(get.call_args.kwargs["headers"]["X-Subscription-Token"], "secret")

    def test_fallback_provider_uses_configured_openclaw_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "cache.json"
            seed.write_text('[{"title":"Fallback","url":"https://example.com","source":"example.com"}]', encoding="utf-8")
            settings = AppSettings()
            settings.search_provider.fallback_provider = "openclaw_cache"
            settings.search_provider.openclaw_cache_path = str(seed)
            provider = build_fallback_provider(settings.search_provider)
            results = provider.search(SearchQuery(text="x", section="Finance", domains=[]))
            self.assertEqual(results[0].title, "Fallback")

    def test_run_log_store_records_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = RunLogStore(Path(tmp) / "settings.sqlite3")
            run_id = logs.start("daily_fetch", provider="chatgpt_web", fallback_provider="openclaw_cache")
            logs.finish(run_id, "success", result_count=3, message="ok", metadata={"used_provider": "openclaw_cache"})
            runs = logs.list_recent()
            self.assertEqual(runs[0]["job_name"], "daily_fetch")
            self.assertEqual(runs[0]["status"], "success")
            self.assertEqual(runs[0]["result_count"], 3)
            self.assertEqual(runs[0]["metadata"]["used_provider"], "openclaw_cache")
            summary = logs.summary()
            self.assertEqual(summary["last_run"]["run_id"], run_id)
            self.assertEqual(summary["counts"]["success"], 1)
            self.assertEqual(summary["counts"]["failed"], 0)
            self.assertEqual(logs.first_success_started_at("daily_fetch"), runs[0]["started_at"])
            self.assertIsNone(logs.first_success_started_at("critical_event_scan"))

    def test_dingtalk_signed_url_adds_signature(self):
        url = dingtalk_signed_url("https://example.com/hook", "secret", 1234567890)
        self.assertIn("timestamp=1234567890", url)
        self.assertIn("sign=", url)

    def test_fetch_completion_message_contains_status(self):
        message = build_fetch_completion_message("success", 10, "openclaw_cache", "done")
        self.assertIn("新闻抓取完成", message)
        self.assertIn("结果数：10", message)
        self.assertIn("来源：openclaw_cache", message)

    def test_dingtalk_mobile_mentions_are_rendered(self):
        content, at_payload = with_mobile_mentions("hello", "13818018801, 13900000000")
        self.assertIn("@13818018801", content)
        self.assertEqual(at_payload["atMobiles"], ["13818018801", "13900000000"])
        self.assertEqual(parse_at_mobiles("13818018801，13900000000"), ["13818018801", "13900000000"])

    def test_fetch_completion_message_contains_approval_url(self):
        message = build_fetch_completion_message("success", 3, "brave_search", "done", "https://example.com/news")
        self.assertIn("点击进入 News 表审核", message)
        self.assertIn("https://example.com/news", message)

    def test_dingtalk_ai_table_url_is_built_from_node_id(self):
        self.assertEqual(
            build_dingtalk_ai_table_url("abc123"),
            "https://alidocs.dingtalk.com/i/nodes/abc123",
        )

    def test_dingtalk_approval_url_prefers_configured_view(self):
        self.assertEqual(
            build_dingtalk_approval_url("abc123", "https://example.com/review"),
            "https://example.com/review",
        )

    def test_notification_skips_without_webhook(self):
        settings = AppSettings()
        result = send_daily_fetch_notification(
            settings.dingtalk,
            status="success",
            result_count=1,
            provider="openclaw_cache",
            message="done",
        )
        self.assertEqual(result.status, "skipped")

    @patch("app.notifications.send_daily_fetch_notification")
    def test_successful_ingest_is_audit_only_but_failure_notifies(self, send: Mock):
        settings = AppSettings()
        success = send_ingest_completion_notification(settings.dingtalk, "success", 30, "brave_search", "done", "https://example.com/review")
        self.assertEqual(success.status, "skipped")
        self.assertIn("RunLog/Audit Trail", success.message)
        send.assert_not_called()
        send.return_value = Mock(status="sent", message="ok")
        failed = send_ingest_completion_notification(settings.dingtalk, "failed", 0, "brave_search", "error")
        self.assertEqual(failed.status, "sent")
        send.assert_called_once()

    def test_app_notification_requires_recipient(self):
        settings = AppSettings()
        settings.dingtalk.delivery_mode = "app"
        settings.dingtalk.agent_id = "123"
        settings.dingtalk.client_id = "client"
        settings.dingtalk.client_secret = "secret"
        result = send_daily_fetch_notification(
            settings.dingtalk,
            status="success",
            result_count=1,
            provider="openclaw_cache",
            message="done",
        )
        self.assertEqual(result.status, "skipped")
        self.assertIn("user_ids", result.message)

    def test_dingtalk_ai_table_extracts_base_id_from_link(self):
        link = "https://alidocs.dingtalk.com/i/nodes/abc123xyz?utm=share"
        self.assertEqual(extract_base_id(link), "abc123xyz")

    def test_insights_sheet_is_separate_from_news_sheet(self):
        settings = AppSettings()
        self.assertEqual(settings.dingtalk_ai_table.insights_sheet_id, "")
        field_names = {field["name"] for field in INSIGHT_FIELDS}
        self.assertIn("Report Content", field_names)
        self.assertIn("Report Doc URL", field_names)
        self.assertIn("Report Doc Node ID", field_names)
        self.assertIn("Image Report URL", field_names)
        self.assertIn("Text Report URL", field_names)
        self.assertIn("Image File Path", field_names)
        self.assertIn("Image Permission Status", field_names)
        self.assertIn("Text Permission Status", field_names)
        self.assertIn("Source Record IDs", field_names)
        self.assertIn("DingTalk Status", field_names)
        self.assertIn("Research ID", field_names)
        self.assertIn("Evidence IDs", field_names)
        self.assertIn("Claim IDs", field_names)

    def test_audit_trail_fields_capture_step_lineage(self):
        settings = AppSettings()
        self.assertEqual(settings.dingtalk_ai_table.audit_trail_sheet_id, "")
        field_names = {field["name"] for field in AUDIT_TRAIL_FIELDS}
        self.assertIn("Run ID", field_names)
        self.assertIn("Stage Code", field_names)
        self.assertIn("Source Record IDs", field_names)
        self.assertIn("Artifact URL", field_names)
        self.assertIn("Metadata JSON", field_names)
        fields = build_audit_fields(
            run_id="run-1",
            workflow="weekly_publish",
            stage_code="PUBLISH.notify",
            stage_name="Send final report image",
            status="success",
            source_record_ids="news-1, news-2",
            report_id="gbss-weekly-2026-06-20-final",
            artifact_url="https://alidocs.dingtalk.com/i/nodes/report",
            metadata={"image_status": "sent"},
            event_id="audit-1",
            recorded_at="2026-06-20T12:00:00+00:00",
        )
        self.assertEqual(fields["Audit Event ID"], "audit-1")
        self.assertEqual(fields["Run ID"], "run-1")
        self.assertEqual(fields["Report ID"], "gbss-weekly-2026-06-20-final")
        self.assertIn("image_status", fields["Metadata JSON"])

    def test_research_production_uses_source_tiers_and_pending_evidence(self):
        self.assertEqual(source_tier("https://stripe.com/news/release")[0], "T1")
        self.assertEqual(source_tier("https://www.ant-intl.com/en/news/detail/example")[0], "T1")
        self.assertEqual(source_tier("https://www.hkma.gov.hk/eng/news-and-media/press-releases")[0], "T1")
        self.assertEqual(source_tier("https://www.reuters.com/example")[0], "T2")
        self.assertEqual(source_tier("https://example-blog.invalid/post")[0], "T3")
        queue = build_research_queue_fields({"id": "topic-1", "fields": {
            "Topic ID": "research-topic-1",
            "Topic": "Enterprise Voice AI in Regulated Operations",
            "Research Question": "What makes voice AI production-ready?",
            "Status": "Locked",
        }})
        self.assertEqual(queue["Research Status"], "Locked")
        self.assertIn("counter", queue["Disconfirming Evidence"].lower())
        record = {"id": "news-1", "fields": {
            "Title": "Stripe launches an updated enterprise product",
            "Source URL": {"link": "https://stripe.com/news/product", "text": "stripe.com"},
            "Source": "stripe.com",
            "Publish Date": "2026-06-20",
        }}
        evidence = evidence_fields_from_news(queue["Research ID"], record)
        self.assertEqual(evidence["Source Tier"], "T1")
        self.assertEqual(evidence["Reviewer Status"], "Pending")
        self.assertEqual(evidence["Source Record ID"], "news-1")
        self.assertIn("Research ID", {field["name"] for field in EVIDENCE_BANK_FIELDS})
        self.assertIn("Claim Type", {field["name"] for field in CLAIM_LEDGER_FIELDS})
        self.assertIn("Primary Question", {field["name"] for field in RESEARCH_QUEUE_FIELDS})
        result_fields = {field["name"] for field in RESEARCH_RESULT_FIELDS}
        self.assertIn("Research Content", result_fields)
        self.assertIn("Research Document URL", result_fields)
        self.assertIn("Provider", result_fields)
        self.assertIn("Research Result Record ID", {field["name"] for field in RESEARCH_QUEUE_FIELDS})

    def test_research_quality_gate_requires_verified_evidence_claims_and_boundary(self):
        evidence = [{"fields": {
            "Evidence ID": f"e-{index}",
            "Reviewer Status": "Verified",
            "Source Tier": "T1" if index < 3 else "T2",
            "Publisher": f"source-{index % 3}.example",
        }} for index in range(6)]
        claims = [{"fields": {
            "Claim ID": f"c-{index}",
            "Reviewer Status": "Approved",
            "Counter-evidence / Boundary": "Limited to a named deployment" if index == 0 else "",
        }} for index in range(3)]
        ready = research_quality_gate(evidence, claims)
        self.assertTrue(ready["deep_research_ready"])
        self.assertEqual(ready["status"], "Deep Research Ready")
        not_ready = research_quality_gate(evidence[:5], claims[:2])
        self.assertFalse(not_ready["deep_research_ready"])
        self.assertIn("verified evidence 5/6", not_ready["blockers"])

    def test_deep_research_synthesis_requires_traceable_evidence_and_boundaries(self):
        evidence = [{"fields": {"Evidence ID": "e-1"}}]
        valid = {
            "research_id": "research-1",
            "claims": [{
                "claim_type": "Inference",
                "claim_text": "A limited pilot may justify a GBSS benchmark.",
                "evidence_ids": ["e-1"],
                "counter_evidence_or_boundary": "Not evidence of production readiness.",
                "confidence": "Medium",
            }],
        }
        self.assertEqual(validate_synthesis_payload(valid, "research-1", evidence), [])
        invalid = {**valid, "claims": [{**valid["claims"][0], "evidence_ids": ["unknown"], "counter_evidence_or_boundary": ""}]}
        errors = validate_synthesis_payload(invalid, "research-1", evidence)
        self.assertIn("claim 1 cites an unknown evidence_id", errors)
        self.assertIn("inference claim 1 requires counter_evidence_or_boundary", errors)

    def test_research_context_prevents_synthetic_p0(self):
        records = [{"id": "news-1", "fields": {
            "Title": "Deepgram launches a voice feature",
            "Source URL": {"link": "https://deepgram.com/news/voice", "text": "deepgram.com"},
            "Source": "deepgram.com",
            "Publish Date": "2026-06-20",
            "Review Status": "已采纳",
        }}]
        context = {
            "research": {"fields": {"Topic": "Voice AI production readiness", "Primary Question": "Is evidence sufficient?"}},
            "evidence": [{"fields": {
                "Source Record ID": "news-1", "Evidence ID": "e-1", "Reviewer Status": "Pending",
                "Source Tier": "T1", "Extracted Fact": "Deepgram announced a voice feature.", "Published Date": "2026-06-20", "Confidence": "Medium",
                "Source URL": "https://deepgram.com/news/voice",
            }}],
            "claims": [],
            "quality": {"status": "Signal Brief", "deep_research_ready": False, "blockers": ["verified evidence 0/6"]},
        }
        report = build_report_data(records, "JUN 14 - JUN 20", "Voice AI production readiness", research_context=context)
        self.assertEqual(report["researchQuality"]["status"], "Signal Brief")
        self.assertEqual(report["priorityNewsCards"][0]["priority"], "P1")
        self.assertFalse(any(item["priority"] == "P0" for item in report["onePageBrief"]["topPriorities"]))
        self.assertIn("Signal Brief", report["deepDive"]["researchStatus"])

    def test_event_priority_candidate_is_not_masked_by_none_final_priority(self):
        record = {"fields": {
            "Title": "Wise FY26 Results",
            "Source URL": {"link": "https://wise.com/results"},
            "Publish Date": "2026-06-26",
            "Final Priority": "None",
            "Priority Candidate": "P0_Candidate",
        }}
        report = build_report_data([record], "JUN 22 - JUN 28")
        self.assertEqual(report["priorityNewsCards"][0]["priority"], "P0 Candidate")

    def test_config_sheet_tracks_workflow_configuration(self):
        settings = AppSettings()
        self.assertEqual(settings.dingtalk_ai_table.config_sheet_id, "")
        field_names = {field["name"] for field in CONFIG_FIELDS}
        self.assertIn("Config Key", field_names)
        self.assertIn("Value", field_names)
        keys = {item["Config Key"] for item in default_config_items(settings)}
        self.assertIn("reports.daily_review.schedule", keys)
        self.assertIn("reports.weekly_headlines.schedule", keys)
        self.assertIn("reports.weekly_intelligence.draft_schedule", keys)
        self.assertIn("reports.weekly_intelligence.final_schedule", keys)
        self.assertIn("reports.weekly_intelligence.document_workspace_id", keys)
        self.assertIn("sheets.audit_trail.sheet_id", keys)
        self.assertIn("sheets.research_queue.sheet_id", keys)
        self.assertIn("sheets.evidence_bank.sheet_id", keys)
        self.assertIn("sheets.claim_ledger.sheet_id", keys)
        self.assertIn("reports.weekly_intelligence.document_folder_node_id", keys)
        self.assertIn("reports.weekly_intelligence.document_folder_url", keys)
        self.assertIn("reports.weekly_intelligence.document_folder_name", keys)
        self.assertIn("reports.weekly_intelligence.prompt", keys)
        self.assertIn("sheets.research_topics.sheet_id", keys)
        self.assertIn("research.rhythm", keys)

    def test_config_sheet_values_can_be_applied_to_settings(self):
        settings = AppSettings()
        applied = apply_config_items(settings, [
            {"fields": {"Config Key": "reports.weekly_headlines.schedule", "Value": "weekdays=[0,1,2,3,4,5,6]; time=12:00", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_headlines.lookback_days", "Value": "5", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.final_schedule", "Value": "weekdays=[0]; time=12:00", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.lookback_days", "Value": "14", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.max_items", "Value": "8", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.document_workspace_id", "Value": "workspace-1", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.document_folder_node_id", "Value": "folder-1", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.document_folder_url", "Value": "https://alidocs.dingtalk.com/i/desktop/folders/folder-1", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.document_folder_name", "Value": "Reports", "Editable": "yes"}},
            {"fields": {"Config Key": "reports.weekly_intelligence.prompt", "Value": "new prompt", "Editable": "yes"}},
            {"fields": {"Config Key": "sheets.news.sheet_id", "Value": "wrong", "Editable": "no"}},
        ])
        self.assertEqual(settings.schedule.weekly_publish.hour, 12)
        self.assertEqual(settings.schedule.weekly_publish.minute, 0)
        self.assertEqual(settings.schedule.weekly_publish.weekdays, [0])
        self.assertEqual(settings.schedule.weekly_headlines.hour, 12)
        self.assertEqual(settings.schedule.weekly_headlines.minute, 0)
        self.assertEqual(settings.schedule.weekly_headlines.weekdays, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(settings.rules.daily_report_lookback_days, 5)
        self.assertEqual(settings.rules.weekly_report_lookback_days, 14)
        self.assertEqual(settings.rules.max_items_per_category, 8)
        self.assertEqual(settings.dingtalk_ai_table.report_docs_workspace_id, "workspace-1")
        self.assertEqual(settings.dingtalk_ai_table.report_docs_folder_node_id, "folder-1")
        self.assertEqual(settings.dingtalk_ai_table.report_docs_folder_url, "https://alidocs.dingtalk.com/i/desktop/folders/folder-1")
        self.assertEqual(settings.dingtalk_ai_table.report_docs_folder_name, "Reports")
        self.assertEqual(settings.prompts.weekly_publish, "new prompt")
        self.assertEqual(applied, [
            "reports.weekly_headlines.schedule",
            "reports.weekly_headlines.lookback_days",
            "reports.weekly_intelligence.final_schedule",
            "reports.weekly_intelligence.lookback_days",
            "reports.weekly_intelligence.max_items",
            "reports.weekly_intelligence.document_workspace_id",
            "reports.weekly_intelligence.document_folder_node_id",
            "reports.weekly_intelligence.document_folder_url",
            "reports.weekly_intelligence.document_folder_name",
            "reports.weekly_intelligence.prompt",
        ])

    def test_report_document_and_notification_formats_separate_full_report(self):
        content = "\n".join([
            "GBSS Weekly AI & Service Intelligence",
            "Period: JUN 08 - JUN 13",
            "Weekly Topic: AI Agent Commerce and Programmable Payments",
            "Research Question: How will AI agents change payments?",
            "",
            "Executive Summary",
            "",
            "0. This week focuses on one research topic.",
            "1. This week includes 5 accepted external signals.",
            "",
            "I. Business Performance and Competitor Moves",
            "",
            "| Entity | Weekly Signals |",
            "| --- | --- |",
            "| Visa | 1 signal |",
        ])
        doc = report_content_to_document_markdown(content)
        notification = build_report_notification_content(
            content,
            "https://alidocs.dingtalk.com/i/nodes/image-report",
            "https://alidocs.dingtalk.com/i/nodes/text-report",
        )
        self.assertIn("# GBSS Weekly AI & Service Intelligence", doc)
        self.assertIn("## Executive Summary", doc)
        self.assertIn("| Visa | 1 signal |", doc)
        self.assertIn("[Open one-page report]", notification)
        self.assertIn("[Open full analysis]", notification)
        self.assertIn("CEO Summary", notification)
        self.assertNotIn("| Visa | 1 signal |", notification)

    def test_one_page_report_uses_fixed_formal_layout(self):
        records = [{
            "id": "1",
            "fields": {
                "Title": "Visa Unleashes OpenAI Alliance and Programmable Money Rails",
                "Label": "Product",
                "Section": "Finance",
                "Source URL": {"text": "thefintechtimes.com", "link": "https://thefintechtimes.com/example"},
                "Publish Date": "2026-06-10",
            },
        }]
        svg = build_one_page_report_svg(records, "JUN 08 - JUN 13", draft=True, detail_url="https://alidocs.dingtalk.com/i/nodes/example")
        markdown = one_page_report_markdown(svg, "2026-06 W24 GBSS Weekly AI & Service Intelligence - Draft")
        self.assertIn('width="900"', svg)
        self.assertIn('viewBox="0 0 900 ', svg)
        self.assertIn("GBSS Weekly AI &amp; Service Intelligence", svg)
        self.assertIn("One-page Brief | Signal Brief | Mobile View", svg)
        self.assertIn("Weekly Theme &amp; Deep Insight / 本周主题研判与深度洞察", svg)
        self.assertIn("Business &amp; Signal Pulse / 重点业务与外部信号", svg)
        self.assertIn("Top Signals / 本周重点动态", svg)
        self.assertIn("GBSS Strategic Impact / 对 GBSS 战略主线的影响", svg)
        self.assertIn("Weekly Deep Insight / 本周深度洞察", svg)
        self.assertIn("PUBLISH DATE", svg)
        self.assertIn("Access / 查看方式", svg)
        self.assertIn("Full Report /", svg)
        self.assertIn("报告详情", svg)
        self.assertIn("Join Group /", svg)
        self.assertIn("入群权限", svg)
        self.assertNotIn("CEO &amp; Direct Reports", svg)
        self.assertNotIn("This Week Actions", svg)
        self.assertLess(svg.index("Top Signals / 本周重点动态"), svg.index("Business &amp; Signal Pulse / 重点业务与外部信号"))
        self.assertLess(svg.index("Business &amp; Signal Pulse / 重点业务与外部信号"), svg.index("GBSS Strategic Impact / 对 GBSS 战略主线的影响"))
        self.assertLess(svg.index("GBSS Strategic Impact / 对 GBSS 战略主线的影响"), svg.index("Weekly Theme &amp; Deep Insight / 本周主题研判与深度洞察"))
        self.assertIn("data:image/svg+xml;base64,", markdown)

    def test_gbss_scoring_and_one_page_brief_cover_new_strategy(self):
        record = {
            "id": "1",
            "fields": {
                "Title": "OPC small team adds Voice AI, AIQC and Agent monitoring for Antom merchant onboarding",
                "Label": "Product",
                "Section": "Contact Center",
                "Source URL": {"text": "example.com", "link": "https://example.com/story"},
                "Publish Date": "2026-06-10",
            },
        }
        score = calculate_priority_score(record)
        self.assertGreaterEqual(score, 70)
        self.assertIn(derive_priority(score), {"P0 Candidate", "P1"})
        self.assertIn("Antom", infer_business_relevance(record))
        self.assertEqual(len(SCORING_MODEL["dimensions"]), 7)
        report = build_report_data([record], "JUN 08 - JUN 13", "AI-enabled OPC model")
        card = report["priorityNewsCards"][0]
        self.assertIn("businessRelevance", card)
        self.assertIn("impactedCapability", card)
        self.assertIn("Voice AI", card["impactedCapability"])
        self.assertIn("AIQC", card["impactedCapability"])
        self.assertIn("onePageBrief", report)
        self.assertIn("weeklyDeepInsight", report["onePageBrief"])
        self.assertEqual(len(report["impactAnalysis"]), 6)

    def test_signal_brief_does_not_assert_unreviewed_deep_insight(self):
        record = {
            "id": "news-1",
            "fields": {
                "Title": "Voice AI vendor announces a new product capability",
                "Source URL": {"text": "example.com", "link": "https://example.com/news"},
                "Publish Date": "2026-06-20",
                "Priority Candidate": "P0_Candidate",
            },
        }
        research_context = {
            "research": {"fields": {"Topic": "Voice AI in GBSS", "Primary Question": "Is this production-ready?"}},
            "evidence": [{"fields": {"Evidence ID": "e-1", "Source Record ID": "news-1", "Reviewer Status": "Pending", "Source Title": "Vendor release"}}],
            "claims": [],
        }
        report = build_report_data([record], "JUN 15 - JUN 20", research_context=research_context)
        deep = report["onePageBrief"]["weeklyDeepInsight"]
        self.assertIn("evidence gate", deep["insight"])
        self.assertIn("No verified evidence or approved claim", deep["whyNow"])
        self.assertNotIn("turns teams into small accountable", deep["insight"])
        rendered = str(report)
        self.assertNotIn("启动 OPC Model", rendered)
        self.assertNotIn("进入 PoC", rendered)
        self.assertIn("no GBSS impact or action is asserted", rendered)
        self.assertIn("evidence pending, no impact conclusion", report["onePageBrief"]["topPriorities"][0]["gbssRelevance"])
        self.assertEqual(report["priorityNewsCards"][0]["priority"], "P0 Candidate")
        content = build_competitor_report_content([record], "JUN 15 - JUN 20", research_context=research_context)
        self.assertIn("P0 Candidate 1", content)

    def test_openai_deep_research_result_cannot_bypass_evidence_gate(self):
        record = {"id": "news-1", "fields": {
            "Title": "Payments platform adds programmable agent controls",
            "Source URL": {"link": "https://example.com/payments"},
            "Publish Date": "2026-06-20",
        }}
        context = {
            "research": {"fields": {"Topic": "Agentic payments", "Primary Question": "What changed?"}},
            "evidence": [],
            "claims": [],
            "quality": {"status": "Signal Brief", "deep_research_ready": False, "blockers": []},
            "openaiDeepResearch": {
                "status": "completed",
                "response_id": "resp_test",
                "content": "## Research synthesis\nResearch result with citations.",
                "phrases": ["Programmable controls become payment infrastructure", "Human review remains essential"],
            },
        }
        report = build_report_data([record], "JUN 14 - JUN 20", research_context=context)
        self.assertEqual(report["deepDive"]["researchStatus"], "Signal Brief")
        self.assertNotIn("Programmable controls", report["onePageBrief"]["weeklyDeepInsight"]["insight"])

    def test_market_led_research_plan_uses_accepted_signal_titles(self):
        records = [
            {"fields": {"Title": "Adyen Announces Adyen Agentic for Commerce", "Section": "Finance"}},
            {"fields": {"Title": "Salesforce to Acquire Fin AI Customer Service Agent", "Section": "Contact Center"}},
            {"fields": {"Title": "Amundi and Ant International launch tokenised money market fund", "Section": "Finance"}},
            {"fields": {"Title": "PayPal considers options for its investment unit", "Section": "Finance"}},
        ]
        plan = build_market_led_research_plan(records, "JUN 14 - JUN 20")
        self.assertIn("Trusted Money Movement", plan["topic"])
        self.assertEqual(len(plan["core_sources"]), 3)
        self.assertEqual(len(plan["context_sources"]), 1)
        self.assertIn("Adyen", plan["core_sources"][0]["title"])

    def test_deep_research_phrase_parser_and_prompt(self):
        content = "## Deep Insight Phrases\n- Agent controls become infrastructure\n- Human review remains essential\n## Sources\n- https://example.com"
        self.assertEqual(extract_phrases(content), ["Agent controls become infrastructure", "Human review remains essential"])
        prompt = research_prompt("Topic", "Question", "JUN 14 - JUN 20", [{"fields": {"Title": "News", "Publish Date": "2026-06-20"}}])
        self.assertIn("Deep Insight Phrases", prompt)
        self.assertIn("News", prompt)

    def test_research_topics_define_current_and_next_pipeline(self):
        records = [{"id": str(index), "fields": fields} for index, fields in enumerate(default_topic_records(date(2026, 6, 13)))]
        current, next_topics = current_and_next_topics(records, date(2026, 6, 13))
        field_names = {field["name"] for field in RESEARCH_TOPIC_FIELDS}
        self.assertIn("Topic", field_names)
        self.assertIn("Research Question", field_names)
        self.assertEqual((current.get("fields") or {}).get("Status"), "Locked")
        self.assertEqual((current.get("fields") or {}).get("Topic"), "AI Agent Commerce and Programmable Payments")
        self.assertEqual(len(next_topics), 4)

    def test_dingtalk_ai_table_validates_required_fields(self):
        settings = AppSettings()
        settings.dingtalk.client_id = "client"
        settings.dingtalk.client_secret = "secret"
        missing = validate_ai_table_settings(settings.dingtalk, settings.dingtalk_ai_table)
        self.assertIn("dingtalk_ai_table.base_id", missing)
        self.assertIn("dingtalk_ai_table.sheet_id", missing)
        self.assertIn("dingtalk_ai_table.operator_id or operator_user_id", missing)

    def test_dingtalk_operator_lookup_retries_remote_timeout(self):
        settings = AppSettings()
        settings.dingtalk.client_id = "client"
        settings.dingtalk.client_secret = "secret"
        settings.dingtalk_ai_table.operator_user_id = "reviewer"
        transient = Mock()
        transient.json.return_value = {"errcode": 15, "sub_code": "isp.top-remote-connection-timeout"}
        success = Mock()
        success.json.return_value = {"errcode": 0, "result": {"unionid": "union-1"}}
        with patch("app.dingtalk_ai_table.get_dingtalk_access_token", return_value="token"), patch(
            "app.dingtalk_ai_table.httpx.post", side_effect=[transient, success]
        ) as post, patch("app.dingtalk_ai_table.time.sleep") as sleep:
            operator_id = resolve_operator_id(settings.dingtalk, settings.dingtalk_ai_table)
        self.assertEqual(operator_id, "union-1")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_dingtalk_operator_lookup_is_cached_per_process(self):
        settings = AppSettings()
        settings.dingtalk.client_id = "cache-client"
        settings.dingtalk.client_secret = "secret"
        settings.dingtalk_ai_table.operator_user_id = "cache-reviewer"
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {"errcode": 0, "result": {"unionid": "cached-union"}}
        with patch("app.dingtalk_ai_table.get_dingtalk_access_token", return_value="token"), patch(
            "app.dingtalk_ai_table.httpx.post", return_value=success
        ) as post:
            self.assertEqual(resolve_operator_id(settings.dingtalk, settings.dingtalk_ai_table), "cached-union")
            self.assertEqual(resolve_operator_id(settings.dingtalk, settings.dingtalk_ai_table), "cached-union")
        self.assertEqual(post.call_count, 1)

    def test_dingtalk_table_request_retries_transport_error(self):
        request = httpx.Request("POST", "https://api.dingtalk.com/v1.0/notable/bases/base/sheets/news/records/list")
        success = httpx.Response(200, request=request, json={"records": [], "hasMore": False})
        with patch(
            "app.dingtalk_ai_table.httpx.request",
            side_effect=[httpx.ReadTimeout("temporary", request=request), success],
        ) as call, patch("app.dingtalk_ai_table.time.sleep") as sleep:
            response = retryable_request("POST", str(request.url), timeout=12)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_weekly_scripts_parse_arguments_before_creating_run_log(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("weekly_draft.py", "weekly_publish.py", "weekly_headlines.py"):
            source = (root / "scripts" / name).read_text()
            self.assertLess(source.index("args = parser.parse_args()"), source.index("run_id = run_logs.start"), name)

    def test_news_record_maps_to_ai_table_fields(self):
        settings = AppSettings()
        record = normalize_news_record(
            {
                "No": "DH000001",
                "Category": "Finance Payments Banking",
                "Subject": "Example headline",
                "Tag": "Product",
                "Link": "https://example.com",
                "Link_Domain": "example.com",
                "releaseDate": 1777132800000,
                "snippet": "Official source excerpt",
            },
            settings.dingtalk_ai_table.field_mapping,
            operator="23571816155520964978",
        )
        self.assertEqual(record["No"], "DH000001")
        self.assertEqual(record["Title"], "Example headline")
        self.assertEqual(record["Review Status"], "待处理")
        self.assertEqual(record["Publish Date"], "2026-04-26")
        self.assertEqual(record["Source Excerpt"], "Official source excerpt")
        self.assertEqual(record["Operator"], "23571816155520964978")
        self.assertEqual(record["Publish Status"], "未发送")
        self.assertNotIn("Sent At", record)
        self.assertNotIn("Rejection Reason", record)

    def test_ai_table_status_uses_current_review_status_mapping(self):
        settings = AppSettings()
        fields = {"Review Status": {"name": "待处理"}, "Status": {"name": "已拒绝"}}
        self.assertEqual(status_name(fields, settings.dingtalk_ai_table.field_mapping), "待处理")

    def test_ai_table_status_falls_back_to_legacy_status_field(self):
        settings = AppSettings()
        fields = {"Status": "已采纳"}
        self.assertEqual(status_name(fields, settings.dingtalk_ai_table.field_mapping), "已采纳")

    def test_publish_filters_only_accepted_records(self):
        settings = AppSettings()
        mapping = settings.dingtalk_ai_table.field_mapping
        records = [
            {"fields": {"Review Status": {"name": "已采纳"}}},
            {"fields": {"Review Status": {"name": "待处理"}}},
            {"fields": {"Review Status": {"name": "已拒绝"}}},
            {"fields": {"Review Status": {"name": "已重复"}}},
        ]
        self.assertEqual([is_accepted_record(record, mapping) for record in records], [True, False, False, False])

    def test_weekly_selection_balances_sections_up_to_ten_records(self):
        settings = AppSettings()
        now = datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        records = []
        for index in range(8):
            records.append({"id": f"finance-{index}", "fields": {
                "Review Status": "已采纳", "Section": "Finance", "Publish Date": 1781452800000 + index,
            }})
        for index in range(3):
            records.append({"id": f"contact-{index}", "fields": {
                "Review Status": "已采纳", "Section": "Contact Center", "Publish Date": 1781452800000 + index,
            }})
        selected, _ = select_weekly_records(
            records,
            settings.dingtalk_ai_table.field_mapping,
            now,
            max_items=10,
        )
        counts = Counter((record.get("fields") or {}).get("Section") for record in selected)
        self.assertEqual(len(selected), 10)
        self.assertEqual(counts["Finance"], 7)
        self.assertEqual(counts["Contact Center"], 3)

    def test_daily_report_and_weekly_intelligence_keep_independent_delivery_states(self):
        settings = AppSettings()
        now = datetime(2026, 6, 21, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        records = [{"id": "news-1", "fields": {
            "Review Status": "已采纳",
            "Section": "Finance",
            "Publish Date": 1781452800000,
            "Daily Report Sent At": "2026-06-21",
        }}]
        daily_report, _ = select_weekly_records(
            records, settings.dingtalk_ai_table.field_mapping, now,
            sent_fields=("Daily Report Sent At", "Weekly Headlines Sent At"),
        )
        intelligence, _ = select_weekly_records(
            records, settings.dingtalk_ai_table.field_mapping, now,
            sent_fields=("Weekly Intelligence Sent At", "Weekly Sent At"),
        )
        self.assertEqual(daily_report, [])
        self.assertEqual([record["id"] for record in intelligence], ["news-1"])

    def test_competitor_report_uses_analysis_structure(self):
        content = build_competitor_report_content(
            [{
                "id": "1",
                "fields": {
                    "Title": "Wise expands business payments revenue in latest annual report",
                    "Label": "Earnings",
                    "Section": "Finance",
                    "Source URL": {"text": "wise.com", "link": "https://wise.com/news"},
                    "Publish Date": "2026-06-10",
                },
            }],
            "JUN 07 - JUN 13",
            "https://example.com/news",
            draft=True,
        )
        self.assertIn("[Draft for Review / 草稿待确认] GBSS Weekly AI & Service Intelligence", content)
        self.assertIn("Audience / 受众: CEO & Direct Reports", content)
        self.assertIn("Weekly Topic / 本周 Topic:", content)
        self.assertIn("1. Executive Summary / 本周关键结论与主题判断", content)
        self.assertIn("2. External Signal Radar / 外部动态雷达", content)
        self.assertIn("3. Priority News Cards / 本周重点动态卡片", content)
        self.assertIn("4. GBSS Impact Analysis / GBSS 影响分析", content)
        self.assertIn("5. Watchlist & Deep Dive / 下周观察与深度分析", content)
        self.assertIn("Business Support", content)
        self.assertIn("Organization Transformation", content)
        self.assertIn("OPC & Operating Model", content)
        self.assertIn("Internal Efficiency", content)
        self.assertIn("Contact Center Insight", content)
        self.assertIn("Governance & Vendor Strategy", content)
        self.assertIn("AICC", content)
        self.assertIn("AIQC", content)
        self.assertIn("Voice AI", content)
        self.assertIn("[wise.com](https://wise.com/news)", content)

    def test_relative_publish_date_is_deferred_to_backfill(self):
        settings = AppSettings()
        record = normalize_news_record(
            {"title": "Example", "url": "https://example.com/story", "published_at": "2 days ago"},
            settings.dingtalk_ai_table.field_mapping,
        )
        self.assertNotIn("Publish Date", record)

    def test_page_title_is_extracted_and_shortened(self):
        title = title_from_html('<meta property="og:title" content="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one">')
        shortened = shorten_title(title or "")
        self.assertEqual(shortened, "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty...")
        self.assertEqual(title_word_count(shortened), 20)

    def test_markdown_link_is_normalized_for_dingtalk_url_field(self):
        value = normalize_url_cell("[Example](https://example.com/story)")
        self.assertEqual(value, {"text": "example.com", "link": "https://example.com/story"})

    def test_existing_url_cell_uses_domain_as_description(self):
        value = normalize_url_cell({"text": "PYMNTS", "link": "https://www.pymnts.com/story"})
        self.assertEqual(value, {"text": "pymnts.com", "link": "https://www.pymnts.com/story"})

    def test_publish_date_can_be_read_from_page_metadata(self):
        body = '<meta property="article:published_time" content="2026-05-24T09:30:00Z">'
        self.assertEqual(date_from_html(body), "2026-05-24")

    def test_publish_date_can_be_read_from_url_path(self):
        self.assertEqual(date_from_url("https://example.com/2026/05/24/story"), "2026-05-24")
        self.assertEqual(date_from_url("https://example.com/news/videos/2026-05-31/story"), "2026-05-31")
        self.assertEqual(date_from_url("https://businesswire.com/news/home/20260601578779/en/story"), "2026-06-01")

    def test_publish_date_can_be_read_from_timestamp(self):
        self.assertEqual(parse_date(1777132800000), "2026-04-26")
        self.assertEqual(parse_date(1782316800000), "2026-06-25")

    def test_similar_titles_are_grouped_as_duplicates(self):
        records = [
            {"id": "a", "fields": {"Title": "Airwallex launches POS payments product", "Publish Date": 1}},
            {"id": "b", "fields": {"Title": "Airwallex launches POS payments product", "Publish Date": 2}},
        ]
        clusters = find_duplicate_clusters(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].primary["id"], "a")
        self.assertEqual(clusters[0].duplicates[0]["id"], "b")

    def test_same_investment_event_is_grouped_across_localized_titles(self):
        records = [
            {"id": "a", "fields": {"Title": "Poland Invests $11 Million in ElevenLabs to Build AI Tech Hub", "Publish Date": 1781625600000}},
            {"id": "b", "fields": {"Title": "Polski fundusz kupuje udziały w ElevenLabs i uruchamia AI Lab Poland", "Publish Date": 1781712000000}},
        ]
        clusters = find_duplicate_clusters(records)
        self.assertEqual(len(clusters), 1)
        self.assertIn("Same funding event for elevenlabs", clusters[0].reasons["b"])

    def test_shared_amount_is_not_an_event_entity(self):
        records = [
            {"id": "a", "fields": {"Title": "Voice AI startup raises $50 Million Series C", "Publish Date": 1781625600000}},
            {"id": "b", "fields": {"Title": "Poland Invests $11 Million in ElevenLabs", "Publish Date": 1781712000000}},
        ]
        self.assertEqual(find_duplicate_clusters(records), [])

    def test_different_titles_are_not_duplicates(self):
        self.assertLess(title_similarity("Stripe launches billing tools", "Genesys launches virtual agent"), 0.86)

    def test_category_url_is_not_treated_as_article_url(self):
        self.assertFalse(is_article_url("https://fintechnews.sg/payments/"))
        self.assertTrue(is_article_url("https://example.com/news/airwallex-launches-pos-payments"))

    def test_missing_browser_profile_marks_provider_invalid(self):
        settings = AppSettings().search_provider
        result = check_provider(settings, "chatgpt_web")
        self.assertFalse(result.ok)
        self.assertIn("Missing browser profile", result.message)


if __name__ == "__main__":
    unittest.main()
