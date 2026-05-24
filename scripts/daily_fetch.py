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

try:
    try:
        provider = build_provider(settings.search_provider)
        results = provider.search(SearchQuery(text="health check", section="Finance", domains=[]))
    except NotImplementedError as exc:
        print(f"daily_fetch primary provider adapter pending: {exc}")
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
        message = f"fallback returned {len(results)} cached/manual results"
        print(f"daily_fetch {message}")
        run_logs.finish(run_id, "success", len(results), message, metadata={"used_provider": settings.search_provider.fallback_provider})
    except ProviderNotConfigured as exc:
        print(f"daily_fetch primary provider not configured: {exc}")
        fallback = build_fallback_provider(settings.search_provider)
        results = fallback.search(SearchQuery(text="health check", section="Finance", domains=[]))
        message = f"fallback returned {len(results)} cached/manual results"
        print(f"daily_fetch {message}")
        run_logs.finish(run_id, "success", len(results), message, metadata={"used_provider": settings.search_provider.fallback_provider})
    else:
        message = f"primary provider returned {len(results)} results"
        print(f"daily_fetch {message}")
        run_logs.finish(run_id, "success", len(results), message, metadata={"used_provider": settings.search_provider.provider})
except (NotImplementedError, ProviderNotConfigured) as exc:
    message = f"provider unavailable: {exc}"
    print(f"daily_fetch {message}")
    run_logs.finish(run_id, "failed", message=message, error=str(exc))
