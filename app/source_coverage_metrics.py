from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, Iterable, Sequence
from urllib.parse import urlparse

from .dingtalk_ai_table import cell_text, status_name
from .url_identity import article_url_identity


def _fields(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("fields") or row


def _url(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("link") or value.get("url") or "")
    return cell_text(value)


def _domain(value: str) -> str:
    return urlparse(value).netloc.lower().removeprefix("www.")


def _split(value: Any) -> list[str]:
    return [
        item.strip()
        for item in cell_text(value).replace("\n", ",").split(",")
        if item.strip()
    ]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _parse_datetime(value: Any) -> datetime | None:
    text = cell_text(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed


def build_source_coverage_snapshot(
    news_records: Sequence[Dict[str, Any]],
    entity_records: Sequence[Dict[str, Any]],
    detect_records: Sequence[Dict[str, Any]],
    known_targets: Sequence[Dict[str, Any]],
    *,
    now: datetime,
    freshness_days: int = 7,
) -> Dict[str, Any]:
    news_by_identity = {
        article_url_identity(_url(_fields(row).get("Source URL")))
        for row in news_records
        if article_url_identity(_url(_fields(row).get("Source URL")))
    }
    known_items = [
        {
            "id": str(target.get("id") or ""),
            "url": str(target.get("url") or ""),
            "found": article_url_identity(target.get("url") or "") in news_by_identity,
        }
        for target in known_targets
    ]
    known_found = sum(item["found"] for item in known_items)

    trusted_domains = {
        domain.lower().removeprefix("www.")
        for row in detect_records
        if cell_text(_fields(row).get("Type")).lower() == "trusted_source"
        and cell_text(_fields(row).get("Enabled") or "true").lower() not in {"false", "no", "0", "disabled"}
        for domain in _split(_fields(row).get("Domains"))
    }
    trusted_lane = [
        row
        for row in news_records
        if cell_text(_fields(row).get("Source Lane")).lower() == "trusted_media"
    ]
    trusted_valid = sum(
        any(
            _domain(_url(_fields(row).get("Source URL"))) == trusted
            or _domain(_url(_fields(row).get("Source URL"))).endswith("." + trusted)
            for trusted in trusted_domains
        )
        for row in trusted_lane
    )

    priority_entities = []
    for row in entity_records:
        fields = _fields(row)
        if cell_text(fields.get("Watch Tier")).lower() not in {"critical", "high"}:
            continue
        if cell_text(fields.get("Active") or "yes").lower() in {"false", "no", "0", "disabled"}:
            continue
        scan_urls = [
            url
            for name in ("IR URLs", "Newsroom URLs", "Regulatory URLs")
            for url in _split(fields.get(name))
        ]
        priority_entities.append({
            "entity_id": cell_text(fields.get("Entity ID")),
            "scan_urls": scan_urls,
            "domains": {_domain(url) for url in scan_urls if _domain(url)},
        })
    covered_entities = [item for item in priority_entities if item["scan_urls"]]
    freshness_cutoff = now - timedelta(days=max(freshness_days, 1))
    fresh_entity_ids = set()
    for entity in covered_entities:
        for row in news_records:
            fields = _fields(row)
            if _domain(_url(fields.get("Source URL"))) not in entity["domains"]:
                continue
            published = _parse_datetime(fields.get("Publish Date"))
            if published:
                if published.tzinfo is None:
                    published = published.replace(tzinfo=now.tzinfo)
                if published >= freshness_cutoff:
                    fresh_entity_ids.add(entity["entity_id"])
                    break

    event_linked = sum(bool(cell_text(_fields(row).get("Event Case ID"))) for row in news_records)
    accepted = sum(status_name(_fields(row)) == "已采纳" for row in news_records)
    accepted_event_linked = sum(
        status_name(_fields(row)) == "已采纳"
        and bool(cell_text(_fields(row).get("Event Case ID")))
        for row in news_records
    )
    detection_hours = []
    for row in news_records:
        fields = _fields(row)
        published = _parse_datetime(fields.get("Publish Date"))
        first_seen = _parse_datetime(fields.get("First Seen At"))
        if not published or not first_seen:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=first_seen.tzinfo or now.tzinfo)
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=published.tzinfo or now.tzinfo)
        detection_hours.append(max((first_seen - published).total_seconds() / 3600, 0.0))

    mode_counts: Dict[str, int] = {}
    for row in detect_records:
        mode = cell_text(_fields(row).get("Collection Mode") or "unspecified").lower()
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "known_important_recall": {
            "found": known_found,
            "total": len(known_items),
            "ratio": _ratio(known_found, len(known_items)),
            "items": known_items,
        },
        "official_source_coverage": {
            "covered_entities": len(covered_entities),
            "priority_entities": len(priority_entities),
            "ratio": _ratio(len(covered_entities), len(priority_entities)),
            "missing_entity_ids": [item["entity_id"] for item in priority_entities if not item["scan_urls"]],
        },
        "official_source_freshness": {
            "fresh_entities": len(fresh_entity_ids),
            "covered_entities": len(covered_entities),
            "ratio": _ratio(len(fresh_entity_ids), len(covered_entities)),
            "window_days": freshness_days,
        },
        "trusted_lane_purity": {
            "valid": trusted_valid,
            "trusted_lane_total": len(trusted_lane),
            "ratio": _ratio(trusted_valid, len(trusted_lane)),
        },
        "news_event_acceptance_funnel": {
            "news_total": len(news_records),
            "event_linked": event_linked,
            "accepted": accepted,
            "accepted_event_linked": accepted_event_linked,
            "event_link_rate": _ratio(event_linked, len(news_records)),
            "accepted_event_link_rate": _ratio(accepted_event_linked, len(news_records)),
        },
        "time_to_detect_hours": {
            "sample_count": len(detection_hours),
            "median": round(float(median(detection_hours)), 2) if detection_hours else None,
        },
        "collection_mode_counts": dict(sorted(mode_counts.items())),
    }
