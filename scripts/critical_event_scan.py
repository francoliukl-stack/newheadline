"""Four-hour critical-source scan for earnings, product, strategy, regulation and incidents."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters import AlphaVantageAdapter, AdapterRequest, FirecrawlAdapter, GdeltAdapter, MarketauxAdapter, OfficialSourceAdapter, SourceSignal, YFinanceAdapter  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.cost_control import BudgetController, CostEstimate, DingTalkUsageLedger, UsageLedger, count_provider_calls_today, usage_fields  # noqa: E402
from app.dingtalk_ai_table import add_news_records, list_records, normalize_news_record  # noqa: E402
from app.event_alerts import send_event_alerts  # noqa: E402
from app.event_intelligence import EntityRecord, catalog_from_records, enrich_events_with_llm, eventize_records, is_critical_signal, normalize_url, persist_event_candidates  # noqa: E402
from app.event_tables import EventIntelligenceTables  # noqa: E402
from app.llm_service import LLMService  # noqa: E402
from app.models import AppSettings  # noqa: E402
from app.publish_dates import parse_date  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402


DATA = ROOT / "data"


def entities_for_scan_mode(catalog: Sequence[EntityRecord], mode: str) -> List[EntityRecord]:
    watched = [
        entity
        for entity in catalog
        if entity.active and entity.watch_tier in {"critical", "high"}
    ]
    if mode == "fast":
        return [entity for entity in watched if entity.scan_cadence_hours <= 4]
    return watched


def tables_from_settings(settings: AppSettings) -> EventIntelligenceTables:
    ai = settings.dingtalk_ai_table
    ids = [ai.event_cases_sheet_id, ai.event_entities_sheet_id, ai.event_sources_sheet_id, ai.event_scores_sheet_id, ai.entity_catalog_sheet_id, ai.alert_log_sheet_id, ai.api_usage_sheet_id]
    if not all(ids):
        raise RuntimeError("v3.1 event schema is not applied")
    table = lambda sheet_id: ai.model_copy(update={"sheet_id": sheet_id})
    return EventIntelligenceTables(*[table(sheet_id) for sheet_id in ids])


def collect_critical_signals(
    settings: AppSettings,
    catalog: Sequence[EntityRecord],
    mode: str = "anchor",
    usage_ledger: Optional[UsageLedger] = None,
    run_id: str = "",
) -> Tuple[List[SourceSignal], List[str], int, int]:
    watched = entities_for_scan_mode(catalog, mode)
    signals: List[SourceSignal] = []
    errors: List[str] = []
    attempts = successes = 0
    official = OfficialSourceAdapter(min(20, settings.search_provider.request_timeout_seconds))
    gdelt = GdeltAdapter(settings.search_provider.request_timeout_seconds)
    marketaux = MarketauxAdapter(settings.event_intelligence.marketaux_api_key)
    yfinance = YFinanceAdapter()
    alpha_vantage = AlphaVantageAdapter(settings.event_intelligence.alpha_vantage_api_key)
    alpha_vantage_calls_today = (
        count_provider_calls_today(usage_ledger, "alpha_vantage", settings.system.timezone)
        if mode != "fast" and settings.event_intelligence.alpha_vantage_enabled and usage_ledger is not None
        else 0
    )
    alpha_vantage_daily_limit = settings.event_intelligence.alpha_vantage_daily_call_limit

    for entity in watched:
        if settings.event_intelligence.official_enabled and entity.scan_urls:
            attempts += 1
            try:
                signals.extend(official.collect(AdapterRequest(entity_id=entity.entity_id, query=entity.canonical_name, urls=entity.scan_urls, limit=8)))
                successes += 1
            except Exception as exc:
                errors.append(f"official:{entity.entity_id}:{exc}")
        if mode == "fast":
            continue
        if settings.event_intelligence.yfinance_enabled and entity.ticker:
            attempts += 1
            try:
                for market in yfinance.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        direction = "rise" if market.change_pct >= 0 else "fall"
                        url = f"https://finance.yahoo.com/quote/{entity.ticker}"
                        signals.append(SourceSignal("yfinance", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "finance.yahoo.com", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id}))
                successes += 1
            except Exception as exc:
                errors.append(f"yfinance:{entity.entity_id}:{exc}")
        if settings.event_intelligence.alpha_vantage_enabled and entity.ticker:
            if alpha_vantage_calls_today >= alpha_vantage_daily_limit:
                errors.append(f"alpha_vantage:{entity.entity_id}:daily call limit {alpha_vantage_daily_limit} reached, skipped")
            else:
                attempts += 1
                try:
                    for market in alpha_vantage.snapshot(entity.ticker):
                        if abs(market.change_pct) >= 5:
                            direction = "rise" if market.change_pct >= 0 else "fall"
                            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={entity.ticker}"
                            signals.append(SourceSignal("alpha_vantage", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "alphavantage.co", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id, "ticker": entity.ticker}))
                    successes += 1
                    alpha_vantage_calls_today += 1
                    if usage_ledger is not None:
                        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        try:
                            usage_ledger.append(usage_fields(
                                run_id=run_id,
                                event_id="",
                                provider="alpha_vantage",
                                operation="market_snapshot",
                                model=entity.ticker,
                                pricing_version="n/a",
                                estimate=CostEstimate(0, 0, 0.0),
                                status="completed",
                                started_at=started,
                                finished_at=started,
                            ))
                        except Exception as exc:
                            errors.append(f"alpha_vantage:{entity.entity_id}:usage ledger append failed: {exc}")
                except Exception as exc:
                    errors.append(f"alpha_vantage:{entity.entity_id}:{exc}")

    if mode == "fast":
        gdelt_batches = []
    else:
        gdelt_entities = [entity for entity in watched if entity.watch_tier == "critical"]
        gdelt_batches = [gdelt_entities] if gdelt_entities else []
    for index, batch in enumerate(gdelt_batches):
        names = " OR ".join(f'"{entity.canonical_name}"' for entity in batch)
        query = f"({names}) (earnings OR launch OR partnership OR acquisition OR regulation OR outage)"
        if settings.event_intelligence.gdelt_enabled:
            attempts += 1
            try:
                signals.extend(gdelt.collect(AdapterRequest(query=query, limit=40)))
                successes += 1
            except Exception as exc:
                errors.append(f"gdelt:batch-{index}:{exc}")
        if settings.event_intelligence.marketaux_enabled:
            attempts += 1
            try:
                signals.extend(marketaux.collect(AdapterRequest(query=names, limit=20)))
                successes += 1
            except Exception as exc:
                errors.append(f"marketaux:batch-{index}:{exc}")
        if index < len(gdelt_batches) - 1 and settings.event_intelligence.gdelt_enabled:
            time.sleep(6)

    if attempts and not successes:
        raise RuntimeError("all configured critical-scan adapters failed: " + "; ".join(errors))
    filtered: Dict[str, SourceSignal] = {}
    for signal in signals:
        url = normalize_url(signal.source_url)
        if url and is_critical_signal(signal, catalog, lookback_days=settings.event_intelligence.critical_scan_lookback_days):
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
            "source_excerpt": signal.snippet,
            "query": signal.query,
            "section": "Event Intelligence",
            "Discovery Type": "critical_scan",
            "First Seen At": now,
            "Date Confidence": "source_metadata" if signal.publish_date else "missing_requires_backfill",
        })
    return rows


def enrich_official_excerpts(rows: Sequence[Dict[str, Any]], settings: AppSettings) -> List[str]:
    errors = []
    adapter = OfficialSourceAdapter(min(20, settings.search_provider.request_timeout_seconds))
    firecrawl = FirecrawlAdapter(
        settings.event_intelligence.firecrawl_api_key,
        min(60, settings.search_provider.request_timeout_seconds),
    )
    for row in rows:
        if row.get("provider") != "official" or len(str(row.get("source_excerpt") or "")) >= 800:
            continue
        try:
            extracted = adapter.extract(str(row.get("url") or ""))
            if extracted.markdown:
                row["source_excerpt"] = " ".join(extracted.markdown.split())[:1800]
            if not row.get("published_at") and extracted.publish_date:
                row["published_at"] = extracted.publish_date
        except Exception as exc:
            errors.append(f"official_extract:{row.get('url')}:{exc}")
        if not settings.event_intelligence.firecrawl_enabled or len(str(row.get("source_excerpt") or "")) >= 800:
            continue
        try:
            extracted = firecrawl.extract(str(row.get("url") or ""))
            if extracted.markdown:
                row["source_excerpt"] = " ".join(extracted.markdown.split())[:1800]
            if not row.get("published_at") and extracted.publish_date:
                row["published_at"] = extracted.publish_date
        except Exception as exc:
            errors.append(f"firecrawl_extract:{row.get('url')}:{exc}")
    return errors


def fresh_critical_rows(
    rows: Sequence[Dict[str, Any]],
    lookback_days: int,
    timezone_name: str,
    now: datetime = None,
) -> List[Dict[str, Any]]:
    current = now or datetime.now(ZoneInfo(timezone_name))
    current_date = current.astimezone(ZoneInfo(timezone_name)).date() if current.tzinfo else current.date()
    cutoff = current_date - timedelta(days=max(lookback_days - 1, 0))
    fresh = []
    for row in rows:
        published = parse_date(row.get("published_at"))
        if not published:
            continue
        observed = datetime.fromisoformat(published).date()
        if cutoff <= observed <= current_date:
            fresh.append(row)
    return fresh


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
            "Source Excerpt": row.get("source_excerpt") or "",
            "First Seen At": row.get("First Seen At") or "",
        }})
    return records, ids


def recent_news_records(records: Sequence[Dict[str, Any]], days: int, timezone_name: str, now: datetime = None) -> List[Dict[str, Any]]:
    current = now or datetime.now(ZoneInfo(timezone_name))
    cutoff = current.date() - timedelta(days=max(days - 1, 0))
    recent = []
    for record in records:
        fields = record.get("fields") or {}
        observed = parse_date(fields.get("Publish Date") or fields.get("First Seen At"))
        if not observed:
            continue
        try:
            if datetime.fromisoformat(observed).date() >= cutoff:
                recent.append(record)
        except ValueError:
            continue
    return recent


def append_created_news_records(
    existing: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    record_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    """Reuse the initial News snapshot after a batch insert."""
    if len(rows) != len(record_ids):
        raise RuntimeError("DingTalk returned an unexpected number of created News record ids")
    created = [{"id": record_id, "fields": row} for row, record_id in zip(rows, record_ids)]
    return [*existing, *created]


def is_fast_scan_window(now: datetime, timezone_name: str) -> bool:
    local_now = now.astimezone(ZoneInfo(timezone_name)) if now.tzinfo else now.replace(tzinfo=ZoneInfo(timezone_name))
    return 9 <= local_now.hour < 18


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan critical sources and optionally preview without writes.")
    parser.add_argument("--dry-run", action="store_true", help="Collect and eventize live signals without writes, alerts or paid model calls.")
    parser.add_argument("--mode", choices=["fast", "anchor"], default="anchor", help="fast: official IR/RSS sources during 9-18 local time; anchor: full source set.")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    if not settings.event_intelligence.critical_scan_enabled and not args.dry_run:
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        runs.finish(run_id, "success", message="critical scan disabled")
        print("critical_event_scan skipped: disabled")
        return 0
    if args.mode == "fast" and not args.dry_run and not is_fast_scan_window(datetime.now(ZoneInfo(settings.system.timezone)), settings.system.timezone):
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        runs.finish(run_id, "success", message="fast mode outside 9-18 local work hours")
        print("critical_event_scan skipped: fast mode outside work hours")
        return 0

    tables = tables_from_settings(settings)
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    existing_news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    run_id = ""
    usage_ledger = None
    if not args.dry_run:
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        usage_ledger = DingTalkUsageLedger(settings, tables.api_usage)
    signals, errors, attempts, successes = collect_critical_signals(
        settings,
        catalog,
        mode=args.mode,
        usage_ledger=usage_ledger,
        run_id=run_id,
    )
    new_rows = new_signal_rows(signals, existing_news)
    errors.extend(enrich_official_excerpts(new_rows, settings))
    pre_freshness_count = len(new_rows)
    new_rows = fresh_critical_rows(
        new_rows,
        settings.event_intelligence.critical_scan_lookback_days,
        settings.system.timezone,
    )
    freshness_excluded = pre_freshness_count - len(new_rows)

    if args.dry_run:
        preview, preview_ids = preview_records(new_rows)
        recent_news = recent_news_records(existing_news, settings.event_intelligence.critical_scan_lookback_days, settings.system.timezone)
        events = eventize_records(recent_news + preview, catalog, settings)
        candidate_events = [event for event in events if any(source.news_record_id in preview_ids for source in event.sources)]
        print(json.dumps({
            "mode": "dry-run",
            "scan_mode": args.mode,
            "adapter_attempts": attempts,
            "adapter_successes": successes,
            "adapter_errors": errors,
            "critical_signals": len(signals),
            "new_news_candidates": len(new_rows),
            "freshness_excluded": freshness_excluded,
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

    audit = AuditTrailWriter(settings, store, runs)
    try:
        new_record_ids: set[str] = set()
        if new_rows:
            result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, new_rows)
            if result.status != "sent":
                raise RuntimeError(result.message)
            new_record_ids.update(result.record_ids)
            operator = settings.dingtalk_ai_table.operator_user_id or settings.dingtalk_ai_table.operator_id
            normalized_rows = [
                normalize_news_record(row, settings.dingtalk_ai_table.field_mapping, operator)
                for row in new_rows
            ]
            existing_news = append_created_news_records(existing_news, normalized_rows, result.record_ids)
        else:
            message = f"signals={len(signals)}; new_news=0; events=0; new_events=0; alerts=0; fast_path=no_change"
            metadata = {"adapter_attempts": attempts, "adapter_successes": successes, "adapter_errors": errors, "freshness_excluded": freshness_excluded, "api_optimization": "skip_event_tables_when_no_new_news"}
            runs.finish(run_id, "success", result_count=0, message=message, metadata=metadata)
            audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="success", result_count=0, output_summary=message, metadata=metadata)
            print(f"critical_event_scan success: {message}")
            return 0
        news = recent_news_records(existing_news, settings.event_intelligence.critical_scan_lookback_days, settings.system.timezone)
        events = eventize_records(news, catalog, settings)
        new_events = [event for event in events if any(source.news_record_id in new_record_ids for source in event.sources)]
        if settings.openai_service.enabled:
            ledger = DingTalkUsageLedger(settings, tables.api_usage)
            service = LLMService(settings.openai_service, BudgetController(settings.openai_service, ledger, settings.system.timezone), ledger, audit)
            new_events = enrich_events_with_llm(new_events, service, settings, run_id)
        count = persist_event_candidates(settings, tables, new_events)
        alerts = send_event_alerts(settings, tables, new_events)
        message = f"signals={len(signals)}; new_news={len(new_rows)}; events={count}; new_events={len(new_events)}; alerts={alerts}"
        metadata = {"adapter_attempts": attempts, "adapter_successes": successes, "adapter_errors": errors, "freshness_excluded": freshness_excluded}
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
