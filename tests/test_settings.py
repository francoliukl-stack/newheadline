import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models import AppSettings
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
            saved = store.save(settings)
            self.assertEqual(saved.lark.app_secret, MASK)
            self.assertEqual(saved.search_provider.api_key, MASK)
            unmasked = store.load(masked=False)
            self.assertEqual(unmasked.lark.app_secret, "secret-value")
            self.assertEqual(unmasked.search_provider.api_key, "search-secret")

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

    def test_search_provider_defaults_avoid_codex_dependency(self):
        settings = AppSettings()
        self.assertEqual(settings.search_provider.provider, "chatgpt_web")
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

    def test_codex_search_is_not_allowed_for_unattended_provider(self):
        settings = AppSettings()
        settings.search_provider.use_codex_search = True
        with self.assertRaises(ProviderNotConfigured):
            build_provider(settings.search_provider)

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


if __name__ == "__main__":
    unittest.main()
