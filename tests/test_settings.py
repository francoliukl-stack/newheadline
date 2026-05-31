import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.dingtalk_ai_table import extract_base_id, normalize_news_record, normalize_url_cell, validate_ai_table_settings
from app.models import AppSettings
from app.publish_dates import date_from_html, date_from_url, parse_date
from app.dedupe import find_duplicate_clusters, is_article_url, title_similarity
from app.provider_health import check_provider
from app.notifications import (
    build_fetch_completion_message,
    dingtalk_signed_url,
    send_daily_fetch_notification,
)
from app.run_logs import RunLogStore
from app.scheduler import build_launchd_plist, next_run
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

    def test_dingtalk_signed_url_adds_signature(self):
        url = dingtalk_signed_url("https://example.com/hook", "secret", 1234567890)
        self.assertIn("timestamp=1234567890", url)
        self.assertIn("sign=", url)

    def test_fetch_completion_message_contains_status(self):
        message = build_fetch_completion_message("success", 10, "openclaw_cache", "done")
        self.assertIn("新闻抓取完成", message)
        self.assertIn("结果数：10", message)
        self.assertIn("来源：openclaw_cache", message)

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

    def test_dingtalk_ai_table_validates_required_fields(self):
        settings = AppSettings()
        settings.dingtalk.client_id = "client"
        settings.dingtalk.client_secret = "secret"
        missing = validate_ai_table_settings(settings.dingtalk, settings.dingtalk_ai_table)
        self.assertIn("dingtalk_ai_table.base_id", missing)
        self.assertIn("dingtalk_ai_table.sheet_id", missing)
        self.assertIn("dingtalk_ai_table.operator_id or operator_user_id", missing)

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
            },
            settings.dingtalk_ai_table.field_mapping,
            operator="23571816155520964978",
        )
        self.assertEqual(record["No"], "DH000001")
        self.assertEqual(record["Headline"], "Example headline")
        self.assertEqual(record["Review Status"], "待处理")
        self.assertEqual(record["Publish Date"], "2026-04-25")
        self.assertEqual(record["Operator"], "23571816155520964978")
        self.assertEqual(record["Publish Status"], "未发送")
        self.assertNotIn("Sent At", record)
        self.assertNotIn("Rejection Reason", record)

    def test_relative_publish_date_is_deferred_to_backfill(self):
        settings = AppSettings()
        record = normalize_news_record(
            {"title": "Example", "url": "https://example.com/story", "published_at": "2 days ago"},
            settings.dingtalk_ai_table.field_mapping,
        )
        self.assertNotIn("Publish Date", record)

    def test_markdown_link_is_normalized_for_dingtalk_url_field(self):
        value = normalize_url_cell("[Example](https://example.com/story)")
        self.assertEqual(value, {"text": "Example", "link": "https://example.com/story"})

    def test_publish_date_can_be_read_from_page_metadata(self):
        body = '<meta property="article:published_time" content="2026-05-24T09:30:00Z">'
        self.assertEqual(date_from_html(body), "2026-05-24")

    def test_publish_date_can_be_read_from_url_path(self):
        self.assertEqual(date_from_url("https://example.com/2026/05/24/story"), "2026-05-24")

    def test_publish_date_can_be_read_from_timestamp(self):
        self.assertEqual(parse_date(1777132800000), "2026-04-25")

    def test_similar_titles_are_grouped_as_duplicates(self):
        records = [
            {"id": "a", "fields": {"Title & URL": "Airwallex launches POS payments product", "Publish Date": 1}},
            {"id": "b", "fields": {"Title & URL": "Airwallex launches POS payments product", "Publish Date": 2}},
        ]
        clusters = find_duplicate_clusters(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].primary["id"], "a")
        self.assertEqual(clusters[0].duplicates[0]["id"], "b")

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
