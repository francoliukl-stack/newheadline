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
from app.notifications import send_daily_fetch_notification  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
run_id = run_logs.start(
    "daily_fetch",
    provider=settings.search_provider.provider,
    fallback_provider=settings.search_provider.fallback_provider,
    metadata={"max_results_per_query": settings.search_provider.max_results_per_query},
)

status = "failed"
result_count = 0
message = ""
error = ""
used_provider = ""

try:
    try:
        provider = build_provider(settings.search_provider)
        results = provider.search(SearchQuery(text="health check", section="Finance", domains=[]))
    except NotImplementedError as exc:
        print(f"daily_fetch primary provider adapter pending: {exc}")
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
        status = "success"
        result_count = len(results)
        used_provider = settings.search_provider.fallback_provider
        message = f"fallback returned {result_count} cached/manual results"
        print(f"daily_fetch {message}")
    except ProviderNotConfigured as exc:
        print(f"daily_fetch primary provider not configured: {exc}")
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
        status = "success"
        result_count = len(results)
        used_provider = settings.search_provider.fallback_provider
        message = f"fallback returned {result_count} cached/manual results"
        print(f"daily_fetch {message}")
    else:
        status = "success"
        result_count = len(results)
        used_provider = settings.search_provider.provider
        message = f"primary provider returned {result_count} results"
        print(f"daily_fetch {message}")
except (NotImplementedError, ProviderNotConfigured) as exc:
    status = "failed"
    message = f"provider unavailable: {exc}"
    error = str(exc)
    print(f"daily_fetch {message}")
except Exception as exc:
    status = "failed"
    message = f"unexpected error: {exc}"
    error = str(exc)
    print(f"daily_fetch {message}")

notification = send_daily_fetch_notification(
    settings.dingtalk,
    status=status,
    result_count=result_count,
    provider=used_provider or settings.search_provider.provider,
    message=message,
)
print(f"daily_fetch notification {notification.status}: {notification.message}")
run_logs.finish(
    run_id,
    status,
    result_count=result_count,
    message=message,
    error=error,
    metadata={
        "used_provider": used_provider,
        "notification_status": notification.status,
        "notification_message": notification.message,
    },
)
