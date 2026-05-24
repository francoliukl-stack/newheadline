import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models import AppSettings
from app.scheduler import build_launchd_plist, next_run
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
            saved = store.save(settings)
            self.assertEqual(saved.lark.app_secret, MASK)
            unmasked = store.load(masked=False)
            self.assertEqual(unmasked.lark.app_secret, "secret-value")

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


if __name__ == "__main__":
    unittest.main()
