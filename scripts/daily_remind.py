"""Send a DingTalk reminder for pending News review records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import sys
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import cell_text, list_records, status_name  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.notifications import build_dingtalk_ai_table_url, send_dingtalk_action_card  # noqa: E402
from app.provider_health import check_configured_providers  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.publish_dates import parse_date  # noqa: E402
from app.ai_news_review import summarize_feedback  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"


@dataclass
class ReviewState:
    review_date: str
    pending_news: List[Dict[str, object]]
    related_events: List[Dict[str, object]]
    p0_candidates: int
    strategic_candidates: int
    ai_accept: int
    ai_reject: int
    ai_duplicate: int
    excluded: Dict[str, int]
    feedback_summary: Dict[str, object]


def collect_review_state(settings, now: Optional[datetime] = None) -> ReviewState:
    timezone = ZoneInfo(settings.system.timezone)
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    review_date = (current.date() - timedelta(days=1)).isoformat()
    records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    pending = []
    excluded = {"not_pending": 0, "wrong_date": 0, "missing_date": 0, "unmatched_event": 0}
    for record in records:
        fields = record.get("fields") or {}
        if status_name(fields, settings.dingtalk_ai_table.field_mapping) != "待处理":
            excluded["not_pending"] += 1
            continue
        published = parse_date(fields.get("Publish Date"))
        if not published:
            excluded["missing_date"] += 1
            continue
        if published != review_date:
            excluded["wrong_date"] += 1
            continue
        if not cell_text(fields.get("Event Case ID")):
            excluded["unmatched_event"] += 1
            continue
        pending.append(fields)
    eligible_event_ids = {cell_text(fields.get("Event Case ID")) for fields in pending}
    pending_events = []
    p0_candidates = 0
    strategic_candidates = 0
    ai_accept = sum(cell_text(fields.get("AI Status")) == "已采纳" for fields in pending)
    ai_reject = sum(cell_text(fields.get("AI Status")) == "已拒绝" for fields in pending)
    ai_duplicate = sum(cell_text(fields.get("AI Status")) == "已重复" for fields in pending)
    if settings.event_intelligence.enabled and settings.dingtalk_ai_table.event_cases_sheet_id:
        event_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.event_cases_sheet_id})
        for record in list_records(settings.dingtalk, event_table):
            fields = record.get("fields") or {}
            if cell_text(fields.get("Event ID")) in eligible_event_ids:
                pending_events.append(fields)
                p0_candidates += cell_text(fields.get("Priority Candidate")) == "P0_Candidate"
                strategic_candidates += cell_text(fields.get("Strategic Candidate")).lower() == "yes"
    feedback_summary = summarize_feedback(records, current.date().isoformat())
    return ReviewState(review_date, pending, pending_events, p0_candidates, strategic_candidates, ai_accept, ai_reject, ai_duplicate, excluded, feedback_summary)


def build_review_content(pending_news: int, pending_events: int, p0_candidates: int, strategic_candidates: int, review_date: str = "", headlines: Optional[List[str]] = None, ai_accept: int = 0, ai_reject: int = 0, ai_duplicate: int = 0, feedback_summary: Optional[Dict[str, object]] = None) -> str:
    sections = [
        "### 📢 GBSS 外部事件待审提醒",
        f"审核范围：**Publish Date = {review_date or '前一日'}**  ",
        f"昨日要闻待处理：**{pending_news}**  ",
        f"News 待审关联 Event Case：**{pending_events}**  ",
        f"P0 Candidate：**{p0_candidates}**  ",
        f"Strategic Event：**{strategic_candidates}**  ",
        f"AI Status 已采纳 / 已拒绝 / 已重复：**{ai_accept} / {ai_reject} / {ai_duplicate}**  ",
    ]
    if headlines:
        sections.append("昨日要闻：\n" + "\n".join(f"- {title}" for title in headlines[:10]))
    if feedback_summary and int(feedback_summary.get("reviewed") or 0):
        categories = "；".join(f"{name} {count}" for name, count in feedback_summary.get("top_categories", [])) or "无"
        directions = "；".join(f"{name} {count}" for name, count in feedback_summary.get("top_directions", [])) or "无"
        sections.append(
            "昨日人机差异复盘：\n"
            f"- 已比较：{feedback_summary['reviewed']} 条；一致率：{float(feedback_summary['agreement']):.0%}；人工覆盖：{feedback_summary['overridden']} 条\n"
            f"- 主要差异：{categories}\n"
            f"- 覆盖方向：{directions}\n"
            "- 达到 5 条样本且人工一致率 ≥80% 的 Event Type × Business Line 规则，会用于本轮 AI Status；重复与来源/日期完整性硬门禁不受影响。"
        )
    sections.append("只需审核以上日期且已关联 Event 的 News；标记为已采纳后，关联 Event 会自动进入发布候选。历史、缺日期或未关联 Event 的记录不进入本批次。")
    return "\n\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the DingTalk pending News/Event review reminder.")
    parser.add_argument("--dry-run", action="store_true", help="Read live counts and render the reminder without writes or messages.")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
    provider_results = check_configured_providers(settings.search_provider)
    if not any(result.ok for result in provider_results):
        messages = "; ".join(f"{result.provider}: {result.message}" for result in provider_results)
        raise RuntimeError(f"no healthy search provider: {messages}")
    state = collect_review_state(settings)
    total = len(state.pending_news)
    review_url = settings.dingtalk_ai_table.approval_view_url or build_dingtalk_ai_table_url(settings.dingtalk_ai_table.base_id)
    headlines = [cell_text(fields.get("Title") or fields.get("Subject")) for fields in state.pending_news]
    content = build_review_content(total, len(state.related_events), state.p0_candidates, state.strategic_candidates, state.review_date, headlines, state.ai_accept, state.ai_reject, state.ai_duplicate, state.feedback_summary)
    if args.dry_run:
        print(f"daily_remind dry-run: review_date={state.review_date}; pending_news={total}; pending_events={len(state.related_events)}; excluded={state.excluded}; review_url={review_url}")
        print(content)
        return 0

    run_logs = RunLogStore(DATA / "settings.sqlite3")
    audit = AuditTrailWriter(settings, store, run_logs)
    run_id = run_logs.start("daily_remind", provider="dingtalk_ai_table")
    audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.start", stage_name="Start review reminder", status="running", input_summary="Check providers, count pending News records and send review reminder.", related_sheet=settings.dingtalk_ai_table.sheet_id)
    try:
        audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.provider_check", stage_name="Check providers", status="success", output_summary="Provider health check completed.", related_sheet=settings.dingtalk_ai_table.sheet_id)
        audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.pending_count", stage_name="Count previous-day News and Event reviews", status="success", output_summary=f"Review Date={state.review_date}; Pending News={total}; Events={len(state.related_events)}; P0 Candidates={state.p0_candidates}", result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"review_date": state.review_date, "excluded": state.excluded})
        notification = send_dingtalk_action_card(
            settings.dingtalk.daily_webhook_url,
            settings.dingtalk.daily_signing_secret,
            "GBSS 外部事件待审提醒",
            content,
            "打开审核视图",
            review_url,
            settings.dingtalk.at_mobiles,
        )
        status = "success" if notification.status == "sent" else notification.status
        audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.notify", stage_name="Send review reminder", status=status, output_summary=notification.message, result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id, metadata={"notification": notification.__dict__, "review_date": state.review_date, "pending_news": total, "pending_events": len(state.related_events), "excluded": state.excluded})
        run_logs.finish(run_id, status, result_count=total, message=notification.message)
        audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status=status, output_summary=notification.message, result_count=total, related_sheet=settings.dingtalk_ai_table.sheet_id)
        print(f"daily_remind {status}: review_date={state.review_date}; pending_news={total}; pending_events={len(state.related_events)}; {notification.message}")
        return 0 if status == "success" else 1
    except Exception as exc:
        run_logs.finish(run_id, "failed", message="daily reminder failed", error=str(exc))
        audit.record(run_id=run_id, workflow="daily_remind", stage_code="REVIEW.complete", stage_name="Complete review reminder", status="failed", error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
