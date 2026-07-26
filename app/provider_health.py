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
    role: str = "primary"


def check_provider(settings: SearchProviderSettings, provider_name: str, role: str = "primary") -> ProviderHealth:
    if provider_name == "none":
        return ProviderHealth(provider=provider_name, ok=False, message="provider is disabled", role=role)
    try:
        provider = build_provider_for_name(settings, provider_name)
        results = provider.search(SearchQuery(text="provider health check", section="Finance", domains=[]))
    except (ProviderNotConfigured, NotImplementedError) as exc:
        return ProviderHealth(provider=provider_name, ok=False, message=str(exc), role=role)
    except Exception as exc:
        return ProviderHealth(provider=provider_name, ok=False, message=f"unexpected error: {exc}", role=role)
    if not results:
        return ProviderHealth(provider=provider_name, ok=False, message="provider returned no results", role=role)
    return ProviderHealth(provider=provider_name, ok=True, message="provider is available", result_count=len(results), role=role)


def check_configured_providers(settings: SearchProviderSettings) -> List[ProviderHealth]:
    checks = [(settings.provider, "primary")]
    if settings.fallback_provider not in {"none", settings.provider}:
        checks.append((settings.fallback_provider, "fallback"))
    seen = {name for name, _ in checks}
    for name in settings.supplemental_providers:
        if name not in {"none", ""} and name not in seen:
            seen.add(name)
            checks.append((name, "supplemental"))
    return [check_provider(settings, name, role) for name, role in checks]


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
