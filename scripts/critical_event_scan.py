"""Four-hour critical-source scan for earnings, product, strategy, regulation and incidents."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters import AdapterRequest, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter, SourceSignal, YFinanceAdapter  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.cost_control import BudgetController, DingTalkUsageLedger  # noqa: E402
from app.dingtalk_ai_table import add_news_records, list_records  # noqa: E402
from app.event_alerts import send_event_alerts  # noqa: E402
from app.event_intelligence import EntityRecord, catalog_from_records, enrich_events_with_llm, eventize_records, is_critical_signal, normalize_url, persist_event_candidates  # noqa: E402
from app.event_tables import EventIntelligenceTables  # noqa: E402
from app.llm_service import LLMService  # noqa: E402
from app.models import AppSettings  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"


def tables_from_settings(settings: AppSettings) -> EventIntelligenceTables:
    ai = settings.dingtalk_ai_table
    ids = [ai.event_cases_sheet_id, ai.event_entities_sheet_id, ai.event_sources_sheet_id, ai.event_scores_sheet_id, ai.entity_catalog_sheet_id, ai.alert_log_sheet_id, ai.api_usage_sheet_id]
    if not all(ids):
        raise RuntimeError("v3.1 event schema is not applied")
    table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
    return EventIntelligenceTables(*[table(sheet_id) for sheet_id in ids])


def collect_critical_signals(settings: AppSettings, catalog: Sequence[EntityRecord]) -> Tuple[List[SourceSignal], List[str], int, int]:
    watched = [entity for entity in catalog if entity.active and entity.watch_tier in {"critical", "high"}]
    signals: List[SourceSignal] = []
    errors: List[str] = []
    attempts = successes = 0
    official = OfficialSourceAdapter(settings.search_provider.request_timeout_seconds)
    gdelt = GdeltAdapter(settings.search_provider.request_timeout_seconds)
    marketaux = MarketauxAdapter(settings.event_intelligence.marketaux_api_key)
    yfinance = YFinanceAdapter()

    for entity in watched:
        if settings.event_intelligence.official_enabled and entity.scan_urls:
            attempts += 1
            try:
                signals.extend(official.collect(AdapterRequest(entity_id=entity.entity_id, query=entity.canonical_name, urls=entity.scan_urls, limit=8)))
                successes += 1
            except Exception as exc:
                errors.append(f"official:{entity.entity_id}:{exc}")
        if settings.event_intelligence.yfinance_enabled and entity.ticker:
            attempts += 1
            try:
                for market in yfinance.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        url = f"https://finance.yahoo.com/quote/{entity.ticker}"
                        signals.append(SourceSignal("yfinance", f"{entity.canonical_name} shares move {market.change_pct:+.1f}% in one session", url, "finance.yahoo.com", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id}))
                successes += 1
            except Exception as exc:
                errors.append(f"yfinance:{entity.entity_id}:{exc}")

    for index in range(0, len(watched), 5):
        batch = watched[index:index + 5]
        names = " OR ".join(f'"{entity.canonical_name}"' for entity in batch)
        query = f"({names}) (earnings OR launch OR partnership OR acquisition OR regulation OR outage)"
        if settings.event_intelligence.gdelt_enabled:
            attempts += 1
            try:
                signals.extend(gdelt.collect(AdapterRequest(query=query, limit=20)))
                successes += 1
            except Exception as exc:
                errors.append(f"gdelt:batch-{index // 5}:{exc}")
        if settings.event_intelligence.marketaux_enabled:
            attempts += 1
            try:
                signals.extend(marketaux.collect(AdapterRequest(query=names, limit=20)))
                successes += 1
            except Exception as exc:
                errors.append(f"marketaux:batch-{index // 5}:{exc}")

    if attempts and not successes:
        raise RuntimeError("all configured critical-scan adapters failed: " + "; ".join(errors))
    filtered: Dict[str, SourceSignal] = {}
    for signal in signals:
        url = normalize_url(signal.source_url)
        if url and is_critical_signal(signal, catalog):
            filtered.setdefault(url, signal)
    return list(filtered.values()), errors, attempts, successes


def new_signal_rows(signals: Sequence[SourceSignal], existing_news: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing_urls = {
        normalize_url(((row.get("fields") or {}).get("Source URL") or {}).get("link") if isinstance((row.get("fields") or {}).get("Source URL"), dict) else (row.get("fields") or {}).get("Source URL"))
        for row in existing_news
    }
    rows = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for signal in signals:
        url = normalize_url(signal.source_url)
        if not url or url in existing_urls:
            continue
        existing_urls.add(url)
        rows.append({
            "title": signal.title,
            "url": url,
            "source": signal.source_domain or urlparse(url).netloc,
            "published_at": signal.publish_date,
            "provider": signal.provider,
            "query": signal.query,
            "section": "Event Intelligence",
            "Discovery Type": "critical_scan",
            "First Seen At": now,
            "Date Confidence": "source_metadata" if signal.publish_date else "missing_requires_backfill",
        })
    return rows


def preview_records(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], set[str]]:
    records, ids = [], set()
    for index, row in enumerate(rows):
        record_id = f"dry-run-critical-{index}"
        ids.add(record_id)
        records.append({"id": record_id, "fields": {
            "Title": row["title"],
            "Source URL": {"text": row["source"], "link": row["url"]},
            "Publish Date": row.get("published_at") or "",
            "Review Status": "待处理",
            "Search Provider": row.get("provider") or "",
            "First Seen At": row.get("First Seen At") or "",
        }})
    return records, ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan critical sources and optionally preview without writes.")
    parser.add_argument("--dry-run", action="store_true", help="Collect and eventize live signals without writes, alerts or paid model calls.")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    if not settings.event_intelligence.critical_scan_enabled and not args.dry_run:
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        runs.finish(run_id, "success", message="critical scan disabled")
        print("critical_event_scan skipped: disabled")
        return 0

    tables = tables_from_settings(settings)
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    existing_news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    signals, errors, attempts, successes = collect_critical_signals(settings, catalog)
    new_rows = new_signal_rows(signals, existing_news)

    if args.dry_run:
        preview, preview_ids = preview_records(new_rows)
        events = eventize_records(list(existing_news) + preview, catalog, settings)
        candidate_events = [event for event in events if any(source.news_record_id in preview_ids for source in event.sources)]
        print(json.dumps({
            "mode": "dry-run",
            "adapter_attempts": attempts,
            "adapter_successes": successes,
            "adapter_errors": errors,
            "critical_signals": len(signals),
            "new_news_candidates": len(new_rows),
            "event_candidates": [{
                "event_id": event.event_id,
                "title": event.title,
                "event_type": event.event_type,
                "business_lines": event.business_lines,
                "priority_candidate": event.priority_candidate,
                "source_urls": [source.url for source in event.sources],
            } for event in candidate_events],
        }, ensure_ascii=False, indent=2))
        return 0

    runs = RunLogStore(DATA / "settings.sqlite3")
    run_id = runs.start("critical_event_scan", provider="event_adapters")
    audit = AuditTrailWriter(settings, store, runs)
    try:
        new_record_ids: set[str] = set()
        if new_rows:
            result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, new_rows)
            if result.status != "sent":
                raise RuntimeError(result.message)
            new_record_ids.update(result.record_ids)
        news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
        events = eventize_records(news, catalog, settings)
        if settings.openai_service.enabled:
            ledger = DingTalkUsageLedger(settings, tables.api_usage)
            service = LLMService(settings.openai_service, BudgetController(settings.openai_service, ledger, settings.system.timezone), ledger, audit)
            events = enrich_events_with_llm(events, service, settings, run_id)
        count = persist_event_candidates(settings, tables, events)
        new_events = [event for event in events if any(source.news_record_id in new_record_ids for source in event.sources)]
        alerts = send_event_alerts(settings, tables, new_events)
        message = f"signals={len(signals)}; new_news={len(new_rows)}; events={count}; new_events={len(new_events)}; alerts={alerts}"
        metadata = {"adapter_attempts": attempts, "adapter_successes": successes, "adapter_errors": errors}
        runs.finish(run_id, "success", result_count=count, message=message, metadata=metadata)
        audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="success", result_count=count, output_summary=message, metadata=metadata)
        print(f"critical_event_scan success: {message}")
        return 0
    except Exception as exc:
        runs.finish(run_id, "failed", message="critical scan failed", error=str(exc), metadata={"adapter_errors": errors})
        audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="failed", error=str(exc), metadata={"adapter_errors": errors})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
