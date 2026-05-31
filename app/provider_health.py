from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .models import SearchProviderSettings
from .search_providers import ProviderNotConfigured, SearchQuery, build_provider_for_name


@dataclass
class ProviderHealth:
    provider: str
    ok: bool
    message: str
    result_count: int = 0


def check_provider(settings: SearchProviderSettings, provider_name: str) -> ProviderHealth:
    if provider_name == "none":
        return ProviderHealth(provider=provider_name, ok=False, message="provider is disabled")
    try:
        provider = build_provider_for_name(settings, provider_name)
        results = provider.search(SearchQuery(text="provider health check", section="Finance", domains=[]))
    except (ProviderNotConfigured, NotImplementedError) as exc:
        return ProviderHealth(provider=provider_name, ok=False, message=str(exc))
    except Exception as exc:
        return ProviderHealth(provider=provider_name, ok=False, message=f"unexpected error: {exc}")
    if not results:
        return ProviderHealth(provider=provider_name, ok=False, message="provider returned no results")
    return ProviderHealth(provider=provider_name, ok=True, message="provider is available", result_count=len(results))


def check_configured_providers(settings: SearchProviderSettings) -> List[ProviderHealth]:
    names = [settings.provider]
    if settings.fallback_provider not in {"none", settings.provider}:
        names.append(settings.fallback_provider)
    return [check_provider(settings, name) for name in names]


def health_summary(results: List[ProviderHealth]) -> Dict[str, object]:
    return {
        "ok": any(result.ok for result in results),
        "providers": [
            {
                "provider": result.provider,
                "ok": result.ok,
                "message": result.message,
                "result_count": result.result_count,
            }
            for result in results
        ],
    }
