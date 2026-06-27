"""Four-hour critical-source scan for earnings, product, strategy, regulation and incidents."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters import AdapterRequest, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter, SourceSignal, YFinanceAdapter  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import add_news_records, list_records  # noqa: E402
from app.event_alerts import send_event_alerts  # noqa: E402
from app.event_intelligence import catalog_from_records, enrich_events_with_llm, eventize_records, normalize_url, persist_event_candidates  # noqa: E402
from app.cost_control import BudgetController, DingTalkUsageLedger  # noqa: E402
from app.llm_service import LLMService  # noqa: E402
from app.event_tables import EventIntelligenceTables  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


data = ROOT / "data"
store = SettingsStore(data / "settings.sqlite3", SecretStore(data / "secrets.json"))
settings = store.load(masked=False)
runs = RunLogStore(data / "settings.sqlite3")
run_id = runs.start("critical_event_scan", provider="event_adapters")
audit = AuditTrailWriter(settings, store, runs)


def tables_from_settings() -> EventIntelligenceTables:
    ai = settings.dingtalk_ai_table
    ids = [ai.event_cases_sheet_id, ai.event_entities_sheet_id, ai.event_sources_sheet_id, ai.event_scores_sheet_id, ai.entity_catalog_sheet_id, ai.alert_log_sheet_id, ai.api_usage_sheet_id]
    if not all(ids):
        raise RuntimeError("v3.1 event schema is not applied")
    table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
    return EventIntelligenceTables(*[table(sheet_id) for sheet_id in ids])


try:
    if not settings.event_intelligence.critical_scan_enabled:
        runs.finish(run_id, "success", message="critical scan disabled")
        print("critical_event_scan skipped: disabled")
        raise SystemExit(0)
    tables = tables_from_settings()
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    watched = [entity for entity in catalog if entity.active and entity.watch_tier in {"critical", "high"}]
    signals = []
    errors = []
    official = OfficialSourceAdapter()
    gdelt = GdeltAdapter(settings.search_provider.request_timeout_seconds)
    marketaux = MarketauxAdapter(settings.event_intelligence.marketaux_api_key)
    yfinance = YFinanceAdapter()
    for entity in watched:
        if settings.event_intelligence.official_enabled and entity.watch_tier == "critical" and entity.official_urls:
            try:
                signals.extend(official.collect(AdapterRequest(entity_id=entity.entity_id, query=entity.canonical_name, urls=entity.official_urls, limit=8)))
            except Exception as exc:
                errors.append(f"official:{entity.entity_id}:{exc}")
        if settings.event_intelligence.yfinance_enabled and entity.ticker:
            try:
                for market in yfinance.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        url = f"https://finance.yahoo.com/quote/{entity.ticker}"
                        signals.append(SourceSignal("yfinance", f"{entity.canonical_name} shares move {market.change_pct:+.1f}% in one session", url, "finance.yahoo.com", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id}))
            except Exception as exc:
                errors.append(f"yfinance:{entity.entity_id}:{exc}")
    for index in range(0, len(watched), 5):
        batch = watched[index:index + 5]
        names = " OR ".join(f'"{entity.canonical_name}"' for entity in batch)
        query = f"({names}) (earnings OR launch OR partnership OR acquisition OR regulation OR outage)"
        if settings.event_intelligence.gdelt_enabled:
            try:
                signals.extend(gdelt.collect(AdapterRequest(query=query, limit=20)))
            except Exception as exc:
                errors.append(f"gdelt:batch-{index // 5}:{exc}")
        if settings.event_intelligence.marketaux_enabled:
            try:
                signals.extend(marketaux.collect(AdapterRequest(query=names, limit=20)))
            except Exception as exc:
                errors.append(f"marketaux:batch-{index // 5}:{exc}")
    existing_news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    existing_urls = {normalize_url(((row.get("fields") or {}).get("Source URL") or {}).get("link") if isinstance((row.get("fields") or {}).get("Source URL"), dict) else (row.get("fields") or {}).get("Source URL")) for row in existing_news}
    new_rows = []
    for signal in signals:
        url = normalize_url(signal.source_url)
        if not url or url in existing_urls:
            continue
        existing_urls.add(url)
        new_rows.append({"title": signal.title, "url": url, "source": signal.source_domain or urlparse(url).netloc, "published_at": signal.publish_date, "provider": signal.provider, "query": signal.query, "section": "Event Intelligence", "Discovery Type": "critical_scan", "First Seen At": datetime.now(timezone.utc).isoformat(timespec="seconds"), "Date Confidence": "source_metadata" if signal.publish_date else "first_seen_fallback"})
    if new_rows:
        result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, new_rows)
        if result.status != "sent":
            raise RuntimeError(result.message)
    news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    events = eventize_records(news, catalog, settings)
    if settings.openai_service.enabled:
        ledger = DingTalkUsageLedger(settings, tables.api_usage)
        service = LLMService(settings.openai_service, BudgetController(settings.openai_service, ledger, settings.system.timezone), ledger, audit)
        events = enrich_events_with_llm(events, service, settings, run_id)
    count = persist_event_candidates(settings, tables, events)
    alerts = send_event_alerts(settings, tables, events)
    runs.finish(run_id, "success", result_count=count, message=f"signals={len(signals)}; new_news={len(new_rows)}; events={count}; alerts={alerts}", metadata={"adapter_errors": errors})
    audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="success", result_count=count, output_summary=f"signals={len(signals)}; new_news={len(new_rows)}; events={count}; alerts={alerts}", metadata={"adapter_errors": errors})
    print(f"critical_event_scan success: signals={len(signals)}; new_news={len(new_rows)}; events={count}; alerts={alerts}")
except Exception as exc:
    runs.finish(run_id, "failed", message="critical scan failed", error=str(exc))
    audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="failed", error=str(exc))
    raise
