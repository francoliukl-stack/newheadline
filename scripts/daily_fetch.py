"""Daily search-provider entrypoint.

This script is intentionally independent from Codex. It reads local settings
and instantiates the configured search provider. Full extraction, ranking,
dedupe, and Lark writes are implemented in later workflow modules.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.search_providers import (  # noqa: E402
    ProviderNotConfigured,
    SearchQuery,
    build_fallback_provider,
    build_provider,
)
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)
try:
    provider = build_provider(settings.search_provider)
    results = provider.search(SearchQuery(text="health check", section="Finance", domains=[]))
except NotImplementedError as exc:
    print(f"daily_fetch primary provider adapter pending: {exc}")
    try:
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
    except (NotImplementedError, ProviderNotConfigured) as fallback_exc:
        print(f"daily_fetch fallback unavailable: {fallback_exc}")
    else:
        print(f"daily_fetch fallback returned {len(results)} cached/manual results")
except ProviderNotConfigured as exc:
    print(f"daily_fetch primary provider not configured: {exc}")
    try:
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
    except (NotImplementedError, ProviderNotConfigured) as fallback_exc:
        print(f"daily_fetch fallback unavailable: {fallback_exc}")
    else:
        print(f"daily_fetch fallback returned {len(results)} cached/manual results")
else:
    print(f"daily_fetch primary provider returned {len(results)} results")
