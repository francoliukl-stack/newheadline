from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .dingtalk_ai_table import cell_text
from .publish_dates import parse_date


AI_REVIEW_VERSION = "ai-review-v1.1"
AI_ACCEPT = "已采纳"
AI_REJECT = "已拒绝"
AI_REVIEW = "待处理"
AI_DUPLICATE = "已重复"
AI_STATUSES = {AI_ACCEPT, AI_REJECT, AI_REVIEW, AI_DUPLICATE}
CRITICAL_TYPES = {"Earnings", "Regulatory", "Market_Expansion", "Product_Launch", "Strategic_MA", "Ops_Incident"}


@dataclass(frozen=True)
class AIReviewRecommendation:
    status: str
    confidence: float
    reason: str


def effective_status(fields: Dict[str, Any]) -> str:
    return cell_text(fields.get("Status") or fields.get("Review Status")).strip()


def target_review_date(now: datetime, timezone_name: str) -> str:
    timezone = ZoneInfo(timezone_name)
    current = now.astimezone(timezone) if now.tzinfo else now.replace(tzinfo=timezone)
    return (current.date() - timedelta(days=1)).isoformat()


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(cell_text(value) or 0)))
    except (TypeError, ValueError):
        return 0.0


def _has_url(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("link") or value.get("url") or value.get("value") or value.get("text"))
    return bool(cell_text(value).strip())


def _url_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("link") or value.get("url") or value.get("value") or value.get("text") or "")
    return cell_text(value)


def review_fingerprint(fields: Dict[str, Any], event: Optional[Dict[str, Any]]) -> str:
    payload = {
        "event_id": cell_text(fields.get("Event Case ID")),
        "source_url": _url_text(fields.get("Source URL")),
        "publish_date": parse_date(fields.get("Publish Date")) or "",
        "duplicate_of": cell_text(fields.get("Duplicate Of")),
        "duplicate_reason": cell_text(fields.get("Duplicate Reason")),
        "event_type": cell_text((event or {}).get("Event Type")),
        "business_lines": cell_text((event or {}).get("Business Lines")),
        "relevance": cell_text((event or {}).get("Relevance Score") or (event or {}).get("Confidence")),
        "strategic": cell_text((event or {}).get("Strategic Candidate")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def recommend_news(fields: Dict[str, Any], event: Optional[Dict[str, Any]]) -> AIReviewRecommendation:
    if cell_text(fields.get("Duplicate Of")) or cell_text(fields.get("Duplicate Reason")):
        return AIReviewRecommendation(AI_DUPLICATE, 0.99, "News 已有明确重复关系，AI 状态标记为已重复。")
    if not _has_url(fields.get("Source URL")) or not parse_date(fields.get("Publish Date")):
        return AIReviewRecommendation(AI_REVIEW, 0.30, "缺少 Source URL 或 Publish Date，需要人工补充后判断。")
    if not cell_text(fields.get("Event Case ID")) or not event:
        return AIReviewRecommendation(AI_REVIEW, 0.40, "尚未形成可追溯 Event Case，需要人工复核业务相关性。")

    event_type = cell_text(event.get("Event Type")) or "General"
    business_lines = cell_text(event.get("Business Lines"))
    relevance = _score(event.get("Relevance Score") or event.get("Confidence"))
    strategic = cell_text(event.get("Strategic Candidate")).lower() in {"yes", "true", "1"}
    if not business_lines or event_type == "General":
        return AIReviewRecommendation(AI_REVIEW, max(0.50, relevance), "Event 缺少明确业务线或事件类型仍为 General，需要人工判断。")
    if event_type == "Market_Context" and not strategic:
        return AIReviewRecommendation(AI_REVIEW, max(0.55, relevance), "属于市场背景信息，不自动进入事实型 Daily Report。")
    if event_type in CRITICAL_TYPES or strategic or relevance >= 0.75:
        confidence = max(0.85, relevance)
        return AIReviewRecommendation(
            AI_ACCEPT,
            confidence,
            f"Event Type={event_type}；Business Lines={business_lines}；Relevance={relevance:.2f}；来源与日期完整。",
        )
    if relevance < 0.45:
        return AIReviewRecommendation(AI_REJECT, max(0.70, 1 - relevance), f"Event relevance={relevance:.2f}，低于业务相关性门槛。")
    return AIReviewRecommendation(AI_REVIEW, max(0.50, relevance), f"Event relevance={relevance:.2f}，未达到自动采纳门槛。")


def recommendation_fields(recommendation: AIReviewRecommendation, reviewed_at: str, fingerprint: str) -> Dict[str, str]:
    return {
        "AI Status": recommendation.status,
        "AI Confidence": f"{recommendation.confidence:.2f}",
        "AI Review Reason": recommendation.reason,
        "AI Review Version": AI_REVIEW_VERSION,
        "AI Review Fingerprint": fingerprint,
        "AI Reviewed At": reviewed_at,
    }


def feedback_fields(fields: Dict[str, Any], observed_at: str) -> Dict[str, str]:
    ai_status = cell_text(fields.get("AI Status"))
    status = effective_status(fields)
    if not ai_status or status in {"", "待处理"}:
        return {}
    decision_source = cell_text(fields.get("Review Decision Source"))
    applied_status = cell_text(fields.get("AI Applied Status"))
    if decision_source == "AI_Deadline":
        if applied_status and status != applied_status:
            return {
                "Review Decision Source": "Human_Override",
                "AI Feedback Outcome": "Overridden",
                "Human Override Status": status,
                "AI Feedback At": observed_at,
            }
        return {}
    previous_outcome = cell_text(fields.get("AI Feedback Outcome"))
    previous_human_status = cell_text(fields.get("Human Override Status"))
    expected = {
        AI_ACCEPT: {"已采纳"},
        AI_REJECT: {"已拒绝"},
        AI_REVIEW: set(),
        AI_DUPLICATE: {"已重复", "重复"},
    }.get(ai_status, set())
    outcome = "Human Resolved" if ai_status == AI_REVIEW else ("Matched" if status in expected else "Overridden")
    if decision_source == "Human" and previous_outcome == outcome:
        if outcome == "Matched" or previous_human_status == status:
            return {}
    return {
        "Review Decision Source": "Human",
        "AI Feedback Outcome": outcome,
        "Human Override Status": "" if outcome == "Matched" else status,
        "AI Feedback At": observed_at,
    }


def deadline_fields(fields: Dict[str, Any], event: Optional[Dict[str, Any]], applied_at: str, threshold: float = 0.85) -> Dict[str, str]:
    if effective_status(fields) != "待处理" or cell_text(fields.get("AI Status")) != AI_ACCEPT:
        return {}
    confidence = _score(fields.get("AI Confidence"))
    event_type = cell_text((event or {}).get("Event Type"))
    business_lines = cell_text((event or {}).get("Business Lines"))
    traceable = bool(cell_text(fields.get("Event Case ID")) and _has_url(fields.get("Source URL")) and parse_date(fields.get("Publish Date")))
    if confidence < threshold or not traceable or not business_lines or event_type in {"", "General", "Market_Context"}:
        return {}
    return {
        "Status": "已采纳",
        "Review Decision Source": "AI_Deadline",
        "AI Applied Status": "已采纳",
        "AI Applied At": applied_at,
        "AI Feedback Outcome": "Pending Human Feedback",
    }


def plan_review_updates(
    news_records: Iterable[Dict[str, Any]],
    event_records: Iterable[Dict[str, Any]],
    mode: str,
    now: datetime,
    timezone_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    event_index = {
        cell_text((record.get("fields") or {}).get("Event ID")): record.get("fields") or {}
        for record in event_records
        if cell_text((record.get("fields") or {}).get("Event ID"))
    }
    reviewed_at = now.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds") if now.tzinfo else now.replace(tzinfo=ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    review_date = target_review_date(now, timezone_name)
    patches: Dict[str, Dict[str, str]] = {}
    stats = {"total": 0, "target": 0, "suggested": 0, "unchanged": 0, "auto_accepted": 0, "feedback": 0}

    for record in news_records:
        record_id = str(record.get("id") or "")
        fields = record.get("fields") or {}
        if not record_id:
            continue
        stats["total"] += 1
        is_target = parse_date(fields.get("Publish Date")) == review_date
        if is_target:
            stats["target"] += 1
        event_id = cell_text(fields.get("Event Case ID"))
        event = event_index.get(event_id)
        effective_fields = dict(fields)
        fingerprint = review_fingerprint(fields, event)
        ai_status = cell_text(fields.get("AI Status"))
        stale = (
            ai_status not in AI_STATUSES
            or cell_text(fields.get("AI Review Version")) != AI_REVIEW_VERSION
            or cell_text(fields.get("AI Review Fingerprint")) != fingerprint
        )
        should_recommend = stale and (mode == "suggest" or is_target)
        if should_recommend:
            recommendation = recommend_news(fields, event)
            recommendation_patch = recommendation_fields(recommendation, reviewed_at, fingerprint)
            patches.setdefault(record_id, {}).update(recommendation_patch)
            effective_fields.update(recommendation_patch)
            stats["suggested"] += 1
        else:
            stats["unchanged"] += 1
        feedback = feedback_fields(effective_fields, reviewed_at)
        if feedback:
            patches.setdefault(record_id, {}).update(feedback)
            effective_fields.update(feedback)
            stats["feedback"] += 1
        if mode == "deadline" and is_target:
            applied = deadline_fields(effective_fields, event, reviewed_at)
            if applied:
                patches[record_id].update(applied)
                stats["auto_accepted"] += 1

    return [{"id": record_id, "fields": fields} for record_id, fields in patches.items()], stats
