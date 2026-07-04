from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .dingtalk_ai_table import cell_text, list_records, update_records
from .publish_dates import parse_date


AI_REVIEW_VERSION = "ai-review-v1.3"
AI_LEARNING_VERSION = "ai-learning-v1.0"
LEARNING_MIN_SUPPORT = 5
LEARNING_MIN_AGREEMENT = 0.80
AI_ACCEPT = "已采纳"
AI_REJECT = "已拒绝"
AI_DUPLICATE = "已重复"
AI_STATUSES = {AI_ACCEPT, AI_REJECT, AI_DUPLICATE}
CRITICAL_TYPES = {"Earnings", "Regulatory", "Market_Expansion", "Product_Launch", "Strategic_MA", "Ops_Incident"}


@dataclass(frozen=True)
class AIReviewRecommendation:
    status: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class LearnedReviewRule:
    event_type: str
    business_line: str
    status: str
    support: int
    agreement: float

    @property
    def key(self) -> str:
        return f"{self.event_type}|{self.business_line}"

    @property
    def signature(self) -> str:
        return f"{AI_LEARNING_VERSION}:{self.key}:{self.status}:{self.support}:{self.agreement:.3f}"


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


def _business_lines(event: Optional[Dict[str, Any]]) -> List[str]:
    raw = cell_text((event or {}).get("Business Lines"))
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def learn_review_rules(
    news_records: Iterable[Dict[str, Any]],
    event_records: Iterable[Dict[str, Any]],
    minimum_support: int = LEARNING_MIN_SUPPORT,
    minimum_agreement: float = LEARNING_MIN_AGREEMENT,
) -> List[LearnedReviewRule]:
    event_index = {
        cell_text((record.get("fields") or {}).get("Event ID")): record.get("fields") or {}
        for record in event_records
        if cell_text((record.get("fields") or {}).get("Event ID"))
    }
    counts: Dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for record in news_records:
        fields = record.get("fields") or {}
        if cell_text(fields.get("Review Decision Source")) not in {"Human", "Human_Override"}:
            continue
        status = effective_status(fields)
        if status not in {AI_ACCEPT, AI_REJECT}:
            continue
        event = event_index.get(cell_text(fields.get("Event Case ID")))
        event_type = cell_text((event or {}).get("Event Type"))
        if not event_type:
            continue
        for business_line in _business_lines(event):
            counts[(event_type, business_line)][status] += 1
    rules = []
    for (event_type, business_line), status_counts in sorted(counts.items()):
        support = sum(status_counts.values())
        status, count = status_counts.most_common(1)[0]
        agreement = count / support
        if support >= minimum_support and agreement >= minimum_agreement:
            rules.append(LearnedReviewRule(event_type, business_line, status, support, agreement))
    return rules


def select_learned_rule(event: Optional[Dict[str, Any]], rules: Iterable[LearnedReviewRule]) -> Optional[LearnedReviewRule]:
    event_type = cell_text((event or {}).get("Event Type"))
    lines = set(_business_lines(event))
    candidates = [rule for rule in rules if rule.event_type == event_type and rule.business_line in lines]
    if not candidates:
        return None
    return sorted(candidates, key=lambda rule: (rule.agreement, rule.support, rule.business_line), reverse=True)[0]


def review_fingerprint(fields: Dict[str, Any], event: Optional[Dict[str, Any]], learned_rule: Optional[LearnedReviewRule] = None) -> str:
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
        "learned_rule": learned_rule.signature if learned_rule else "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def recommend_news(fields: Dict[str, Any], event: Optional[Dict[str, Any]], learned_rule: Optional[LearnedReviewRule] = None) -> AIReviewRecommendation:
    if cell_text(fields.get("Duplicate Of")) or cell_text(fields.get("Duplicate Reason")):
        return AIReviewRecommendation(AI_DUPLICATE, 0.99, "News 已有明确重复关系，AI 状态标记为已重复。")
    if not _has_url(fields.get("Source URL")) or not parse_date(fields.get("Publish Date")):
        return AIReviewRecommendation(AI_REJECT, 0.65, "缺少 Source URL 或 Publish Date，AI 明确建议拒绝；人工补齐证据后可覆盖。")
    if not cell_text(fields.get("Event Case ID")) or not event:
        return AIReviewRecommendation(AI_REJECT, 0.60, "尚未形成可追溯 Event Case，AI 明确建议拒绝；人工确认相关时可覆盖。")

    event_type = cell_text(event.get("Event Type")) or "General"
    business_lines = cell_text(event.get("Business Lines"))
    relevance = _score(event.get("Relevance Score") or event.get("Confidence"))
    strategic = cell_text(event.get("Strategic Candidate")).lower() in {"yes", "true", "1"}
    if not business_lines or event_type == "General":
        base = AIReviewRecommendation(AI_REJECT, max(0.60, 1 - relevance), "Event 缺少明确业务线或事件类型仍为 General，AI 建议拒绝。")
    elif event_type == "Market_Context" and not strategic:
        base = AIReviewRecommendation(AI_REJECT, max(0.65, 1 - relevance), "属于市场背景信息，AI 建议拒绝进入事实型 Daily Report。")
    elif event_type in CRITICAL_TYPES or strategic or relevance >= 0.75:
        confidence = max(0.85, relevance)
        base = AIReviewRecommendation(
            AI_ACCEPT,
            confidence,
            f"Event Type={event_type}；Business Lines={business_lines}；Relevance={relevance:.2f}；来源与日期完整。",
        )
    elif relevance >= 0.60:
        base = AIReviewRecommendation(
            AI_ACCEPT,
            max(0.70, relevance),
            f"Event Type={event_type}；Business Lines={business_lines}；Relevance={relevance:.2f}；AI 建议采纳，未达到自动兜底置信度时仍由人工决定。",
        )
    else:
        base = AIReviewRecommendation(AI_REJECT, max(0.70, 1 - relevance), f"Event relevance={relevance:.2f}，低于业务相关性门槛。")
    if not learned_rule:
        return base
    confidence = min(0.84, learned_rule.agreement) if learned_rule.status != base.status else max(base.confidence, learned_rule.agreement)
    return AIReviewRecommendation(
        learned_rule.status,
        confidence,
        f"{base.reason} 人工反馈规则 {learned_rule.key}：{learned_rule.support} 条样本中 {learned_rule.agreement:.0%} 为{learned_rule.status}；规则版本={AI_LEARNING_VERSION}。",
    )


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
        AI_DUPLICATE: {"已重复", "重复"},
    }.get(ai_status, set())
    outcome = "Matched" if status in expected else "Overridden"
    if decision_source == "Human" and previous_outcome == outcome:
        if outcome == "Matched" or previous_human_status == status:
            return {}
    return {
        "Review Decision Source": "Human",
        "AI Feedback Outcome": outcome,
        "Human Override Status": "" if outcome == "Matched" else status,
        "AI Feedback At": observed_at,
    }


def difference_fields(fields: Dict[str, Any], event: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if cell_text(fields.get("AI Feedback Outcome")) == "Matched":
        if cell_text(fields.get("AI Difference Category")) or cell_text(fields.get("AI Difference Summary")):
            return {"AI Difference Category": "", "AI Difference Summary": ""}
        return {}
    if cell_text(fields.get("AI Feedback Outcome")) != "Overridden":
        return {}
    ai_status = cell_text(fields.get("AI Status"))
    human_status = effective_status(fields)
    event_type = cell_text((event or {}).get("Event Type")) or "Unknown"
    title = cell_text(fields.get("Title") or fields.get("Subject"))
    rejection_reason = cell_text(fields.get("Rejection Reason")).strip()
    reason_text = rejection_reason.lower()
    if human_status == AI_DUPLICATE and ai_status != AI_DUPLICATE:
        category = "Duplicate_Missed"
        explanation = "人工识别为重复，自动规则未找到明确 Duplicate Of / Duplicate Reason。"
    elif ai_status == AI_DUPLICATE and human_status != AI_DUPLICATE:
        category = "Duplicate_False_Positive"
        explanation = "自动规则判断重复，但人工认为该条具有独立信息价值。"
    elif human_status == AI_ACCEPT and ai_status == AI_REJECT:
        if not cell_text(fields.get("Event Case ID")):
            category = "Eventization_Gap"
            explanation = "人工采纳，但自动拒绝源于尚未形成 Event Case。"
        elif event_type == "General":
            category = "Event_Type_Underclassified"
            explanation = "人工采纳，但 Event Type 仍为 General，说明事件类型识别偏弱。"
        else:
            category = "Business_Relevance_Missed"
            explanation = "人工采纳但 AI 拒绝，说明当前业务相关性门槛或映射偏严。"
    elif human_status == AI_REJECT and ai_status == AI_ACCEPT:
        if re.search(r"\b(?:immigration|passport|university visas?|student visas?|education visas?|tourist visas?|work visas?)\b", title, re.I) and not re.search(r"\b(?:payment|card|merchant|fintech payment)\b", title, re.I):
            category = "Entity_False_Positive"
            explanation = "标题中的 Visa 属于签证/移民语义，不是支付网络实体。"
        elif any(token in reason_text for token in ("no content in url", "link no content", "链接无", "无法打开", "无正文")):
            category = "Source_Content_Unavailable"
            explanation = "人工拒绝原因表明来源链接没有可核验正文或无法读取。"
        elif any(token in reason_text for token in ("信息量太少", "no real content", "内容太少", "信息太少")):
            category = "Thin_Content"
            explanation = "人工认为可核验的新增事实或信息密度不足。"
        elif reason_text in {"pr", "广告", "软文", "promotional"} or "promotional" in reason_text:
            category = "Promotional_Content"
            explanation = "人工将内容识别为宣传或软文，不适合作为管理层事实输入。"
        elif re.search(r"\b(?:investment|investor|stock pick|hidden gem|buy rating|sell rating)\b", title, re.I):
            category = "Market_Commentary"
            explanation = "内容属于投资观点或市场评论，不是外部业务触发型事件。"
        elif any(token in reason_text for token in ("关系不大", "不相关", "irrelevant", "not relevant")):
            category = "Tangential_Relevance"
            explanation = "人工认为事件与 GBSS 核心业务线仅有弱关联。"
        else:
            category = "Business_Relevance_Overestimated"
            explanation = "AI 建议采纳但人工拒绝，说明业务相关性、信源质量或事件重要性被高估。"
    else:
        category = "Status_Disagreement"
        explanation = "人工最终状态与 AI 建议不一致，需要作为 bad case 继续观察。"
    return {
        "AI Difference Category": category,
        "AI Difference Summary": f"AI={ai_status}；人工={human_status}；Event Type={event_type}。{explanation}",
    }


def summarize_feedback(news_records: Iterable[Dict[str, Any]], feedback_date: str = "") -> Dict[str, Any]:
    reviewed = []
    for record in news_records:
        fields = record.get("fields") or {}
        if cell_text(fields.get("AI Feedback Outcome")) not in {"Matched", "Overridden"}:
            continue
        if feedback_date and not cell_text(fields.get("AI Feedback At")).startswith(feedback_date):
            continue
        reviewed.append(fields)
    matched = sum(cell_text(fields.get("AI Feedback Outcome")) == "Matched" for fields in reviewed)
    categories = Counter(cell_text(fields.get("AI Difference Category")) for fields in reviewed if cell_text(fields.get("AI Difference Category")))
    directions = Counter(
        f"{cell_text(fields.get('AI Status'))}→{effective_status(fields)}"
        for fields in reviewed
        if cell_text(fields.get("AI Feedback Outcome")) == "Overridden"
    )
    return {
        "reviewed": len(reviewed),
        "matched": matched,
        "overridden": len(reviewed) - matched,
        "agreement": matched / len(reviewed) if reviewed else 0.0,
        "top_categories": categories.most_common(3),
        "top_directions": directions.most_common(3),
    }


def learning_snapshot(news_records: Iterable[Dict[str, Any]], event_records: Iterable[Dict[str, Any]], feedback_date: str = "") -> Dict[str, Any]:
    news_records = list(news_records)
    event_records = list(event_records)
    rules = learn_review_rules(news_records, event_records)
    return {
        "learning_version": AI_LEARNING_VERSION,
        "learned_rule_details": [
            {"segment": rule.key, "status": rule.status, "support": rule.support, "agreement": round(rule.agreement, 4)}
            for rule in rules
        ],
        "feedback_summary": summarize_feedback(news_records, feedback_date),
    }


def deadline_fields(fields: Dict[str, Any], event: Optional[Dict[str, Any]], applied_at: str, threshold: float = 0.85) -> Dict[str, str]:
    if effective_status(fields) != "待处理" or cell_text(fields.get("AI Status")) != AI_ACCEPT:
        return {}
    confidence = _score(fields.get("AI Confidence"))
    event_type = cell_text((event or {}).get("Event Type"))
    business_lines = cell_text((event or {}).get("Business Lines"))
    event_status = cell_text((event or {}).get("Status"))
    merged_into = cell_text((event or {}).get("Merged Into Event ID"))
    traceable = bool(cell_text(fields.get("Event Case ID")) and _has_url(fields.get("Source URL")) and parse_date(fields.get("Publish Date")))
    if confidence < threshold or not traceable or not business_lines or event_type in {"", "General", "Market_Context"} or event_status in {"已归档", "已拒绝", "已重复"} or merged_into:
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
    include_overdue: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    news_records = list(news_records)
    event_records = list(event_records)
    event_index = {
        cell_text((record.get("fields") or {}).get("Event ID")): record.get("fields") or {}
        for record in event_records
        if cell_text((record.get("fields") or {}).get("Event ID"))
    }
    learned_rules = learn_review_rules(news_records, event_records)
    reviewed_at = now.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds") if now.tzinfo else now.replace(tzinfo=ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    review_date = target_review_date(now, timezone_name)
    recovery_start = (datetime.fromisoformat(review_date) - timedelta(days=7)).date().isoformat()
    patches: Dict[str, Dict[str, str]] = {}
    overdue_candidates: List[Tuple[str, str, Dict[str, str]]] = []
    stats = {"total": 0, "target": 0, "suggested": 0, "unchanged": 0, "auto_accepted": 0, "overdue_auto_accepted": 0, "feedback": 0, "learned_rules": len(learned_rules), "difference_updates": 0}

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
        learned_rule = select_learned_rule(event, learned_rules)
        fingerprint = review_fingerprint(fields, event, learned_rule)
        ai_status = cell_text(fields.get("AI Status"))
        stale = (
            ai_status not in AI_STATUSES
            or cell_text(fields.get("AI Review Version")) != AI_REVIEW_VERSION
            or cell_text(fields.get("AI Review Fingerprint")) != fingerprint
        )
        should_recommend = stale and (mode == "suggest" or is_target)
        if should_recommend:
            recommendation = recommend_news(fields, event, learned_rule)
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
        difference = difference_fields(effective_fields, event)
        changed_difference = {
            key: value for key, value in difference.items()
            if cell_text(effective_fields.get(key)) != value
        }
        if changed_difference:
            patches.setdefault(record_id, {}).update(changed_difference)
            effective_fields.update(changed_difference)
            stats["difference_updates"] += 1
        if mode == "deadline" and is_target:
            applied = deadline_fields(effective_fields, event, reviewed_at)
            if applied:
                patches.setdefault(record_id, {}).update(applied)
                stats["auto_accepted"] += 1
        elif mode == "deadline" and include_overdue and not stale:
            published = parse_date(fields.get("Publish Date")) or ""
            if recovery_start <= published < review_date:
                applied = deadline_fields(effective_fields, event, reviewed_at)
                if applied:
                    applied["Review Decision Source"] = "AI_Deadline_Recovery"
                    overdue_candidates.append((published, record_id, applied))

    for _published, record_id, applied in sorted(overdue_candidates, reverse=True)[:5]:
        patches.setdefault(record_id, {}).update(applied)
        stats["overdue_auto_accepted"] += 1

    return [{"id": record_id, "fields": fields} for record_id, fields in patches.items()], stats


def apply_deadline_guard(settings: Any, now: datetime, *, dry_run: bool = False) -> Tuple[int, Dict[str, Any]]:
    event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
    news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    events = list_records(settings.dingtalk, event_table)
    updates, stats = plan_review_updates(news, events, "deadline", now, settings.system.timezone, include_overdue=False)
    if dry_run or not updates:
        return len(updates), stats
    updated_ids: List[str] = []
    for index in range(0, len(updates), 100):
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, updates[index : index + 100])
        if result.status != "sent":
            raise RuntimeError(result.message)
        updated_ids.extend(result.record_ids)
    return len(updated_ids), stats
