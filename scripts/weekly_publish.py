"""Publish the weekly GBSS strategic insight report to DingTalk and mark the weekly send."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import ensure_fields, list_records, update_records  # noqa: E402
from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_docs import create_report_document  # noqa: E402
from app.dingtalk_permissions import make_document_org_readable  # noqa: E402
from app.insights import ensure_insights_sheet, save_insight_report  # noqa: E402
from app.openai_deep_research import load_result  # noqa: E402
from app.notifications import NotificationResult, build_dingtalk_media_download_url, send_dingtalk_robot_group_image, send_dingtalk_webhook_markdown, upload_dingtalk_media  # noqa: E402
from app.publish_format import build_competitor_report_content, build_image_report_notification_content, build_weekly_research_link_content, report_content_to_document_markdown  # noqa: E402
from app.market_research_plan import build_chatgpt_manual_research_handoff, build_market_led_research_plan  # noqa: E402
from app.report_visual import build_one_page_report_svg, one_page_report_markdown, save_one_page_report  # noqa: E402
from app.research_topics import current_and_next_topics, ensure_research_topics_sheet, sync_research_topic_roadmap  # noqa: E402
from app.research_production import build_research_queue_fields, ensure_research_production_sheets, extract_research_document_url, load_research_context, research_input_preflight, select_manual_research_queue, stale_research_queue_patch, upsert_claim_candidates, upsert_evidence_from_news, upsert_research_queue  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.weekly_report import select_weekly_records  # noqa: E402
from app.event_weekly import load_weekly_input, write_sent_markers  # noqa: E402


DATA = ROOT / "data"
GROUP_QR_PATH = DATA / "assets" / "ai_gbss_group_qr.png"
CANONICAL_SHEET_ID = "oMbefcK"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
audit = AuditTrailWriter(settings, store, run_logs)
parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--days", type=int, default=settings.rules.weekly_report_lookback_days)
parser.add_argument("--recent-count", type=int, default=0)
parser.add_argument("--include-sent", action="store_true")
args = parser.parse_args()
run_id = run_logs.start("weekly_publish", provider="dingtalk_ai_table")


def audit_event(stage_code: str, stage_name: str, status: str, **kwargs: object) -> None:
    audit.record(
        run_id=run_id,
        workflow="weekly_publish",
        stage_code=stage_code,
        stage_name=stage_name,
        status=status,
        mode="dry-run" if args.dry_run else "live",
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        **kwargs,
    )


audit_event("PUBLISH.start", "Start weekly final report", "running", input_summary=f"Select accepted weekly News records; days={args.days}, recent_count={args.recent_count}.")


def batched(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


try:
    now = datetime.now(ZoneInfo(settings.system.timezone))
    _, iso_week, _ = now.date().isocalendar()
    weekly_input = load_weekly_input(settings, now, days=args.days, recent_count=args.recent_count, include_sent=args.include_sent, max_items=settings.rules.max_items_per_category, sent_fields=("Weekly Intelligence Sent At", "Weekly Sent At"))
    accepted, range_label = weekly_input.report_records, weekly_input.range_label
    max_items_per_section = None if args.recent_count > 0 else settings.rules.max_items_per_category
    selected_ids = ", ".join(str(record.get("id") or "") for record in accepted if record.get("id"))
    audit_event("PUBLISH.select", "Select weekly source records", "success", output_summary=f"Selected {len(accepted)} accepted unsent records for {range_label}.", result_count=len(accepted), source_record_ids=selected_ids, metadata={"range_label": range_label, "recent_count": args.recent_count, "input_mode": weekly_input.mode})
    if not accepted:
        run_logs.finish(run_id, "success", result_count=0, message="no accepted unsent records")
        audit_event("PUBLISH.complete", "Complete weekly final report", "success", output_summary="No accepted unsent records.", result_count=0)
        print("weekly_publish success: nothing to publish")
        raise SystemExit(0)
    if not settings.dingtalk_ai_table.research_queue_sheet_id:
        raise RuntimeError("Research Queue sheet is not configured")
    queue_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.research_queue_sheet_id})
    queue_records = list_records(settings.dingtalk, queue_table)
    research_queue = select_manual_research_queue(queue_records, range_label, now=now)
    matching_count = sum(
        str((row.get("fields") or {}).get("Approval Status") or "") == "Manual ChatGPT workflow"
        and str((row.get("fields") or {}).get("Publish Date") or "") == range_label
        for row in queue_records
    )
    queue_fields = research_queue.get("fields") or {}
    research_id = str(queue_fields.get("Research ID") or "")
    research_document_url = extract_research_document_url(queue_fields.get("Research Document URL"))
    research_topic = str(queue_fields.get("Topic") or "GBSS Weekly Deep Research")
    audit_event("PUBLISH.topic", "Select manual ChatGPT Research Queue record", "success" if research_queue else "failed", output_summary=f"Matched manual Research Queue records={matching_count} for {range_label}; selected={research_id or '-'}.", result_count=matching_count, report_id=research_id, metadata={"period": range_label, "research_id": research_id, "delivery_mode": "manual_research_link_plus_news"})
    input_preflight = research_input_preflight(queue_fields, accepted)
    audit_event(
        "PUBLISH.input_fingerprint",
        "Validate weekly research input fingerprint",
        "success" if input_preflight["matched"] else "failed",
        output_summary=(
            f"Research input matched={input_preflight['matched']}; "
            f"added={input_preflight['added_event_ids']}; removed={input_preflight['removed_event_ids']}."
        ),
        result_count=len(input_preflight["current_event_ids"]),
        source_record_ids=selected_ids,
        report_id=research_id,
        metadata=input_preflight,
    )
    if not input_preflight["matched"]:
        market_plan = build_market_led_research_plan(accepted, range_label)
        handoff = build_chatgpt_manual_research_handoff(market_plan)
        refresh_plan = "\n".join([
            f"Period: {range_label}",
            f"Topic: {market_plan['topic']}",
            f"Question: {market_plan['question']}",
            f"Why now: {market_plan['why']}",
            "Current accepted Event signals:",
            *[f"- {row['title']}" for row in market_plan["core_sources"]],
            "",
            "Paste-ready ChatGPT prompt:",
            handoff["prompt"],
        ])
        stale_patch = stale_research_queue_patch(
            accepted,
            now.isoformat(timespec="seconds"),
            topic=market_plan["topic"],
            primary_question=market_plan["question"],
            approval_plan=refresh_plan,
            evidence_plan=f"Use the current accepted Event set: {', '.join(input_preflight['current_event_ids'])}.",
        )
        message = (
            f"Research Queue {research_id or range_label} input is stale; "
            f"added={input_preflight['added_event_ids']}; removed={input_preflight['removed_event_ids']}. "
            "The same queue row must use a refreshed manual ChatGPT report link."
        )
        if args.dry_run:
            run_logs.finish(run_id, "success", result_count=0, message=f"dry-run blocked: {message}", metadata={"preflight": input_preflight, "refresh_patch": stale_patch})
            print(f"weekly_publish dry-run: blocked; {message}")
            raise SystemExit(0)
        if not research_queue.get("id"):
            raise RuntimeError(message)
        queue_update = update_records(settings.dingtalk, queue_table, [{"id": research_queue["id"], "fields": stale_patch}])
        if queue_update.status != "sent":
            raise RuntimeError(queue_update.message)
        blocked_notice = send_dingtalk_webhook_markdown(
            settings.dingtalk.daily_webhook_url,
            settings.dingtalk.daily_signing_secret,
            "Weekly Insight blocked: research input changed",
            f"### Weekly Insight 未发送\n\n周期：{range_label}\n\n新增 Event：{', '.join(input_preflight['added_event_ids']) or '无'}\n\n移除 Event：{', '.join(input_preflight['removed_event_ids']) or '无'}\n\nResearch Queue 已原地刷新；请更新研究文档后再发布。本次未写 Weekly Intelligence Sent At。",
            "",
        )
        audit_event("PUBLISH.blocked_notice", "Notify stale research input", blocked_notice.status, output_summary=blocked_notice.message, report_id=research_id, metadata={"notification": blocked_notice.__dict__, "preflight": input_preflight})
        raise RuntimeError(message)

    if str(queue_fields.get("Deep Research Status") or "") == "Waiting for refreshed manual ChatGPT report link":
        message = f"Research Queue {research_id or range_label} is waiting for a refreshed manual ChatGPT report link after input drift."
        audit_event("PUBLISH.manual_research_link", "Validate refreshed research document", "failed" if not args.dry_run else "skipped", output_summary=message, report_id=research_id)
        if args.dry_run:
            run_logs.finish(run_id, "success", result_count=0, message=f"dry-run blocked: {message}")
            print(f"weekly_publish dry-run: blocked; {message}")
            raise SystemExit(0)
        raise RuntimeError(message)

    if not research_document_url.startswith(("https://", "http://")):
        queue_label = research_id or f"manual ChatGPT plan for {range_label}"
        message = f"Research Queue {queue_label} is missing Research Document URL; paste the completed DingTalk document link before Sunday publication."
        audit_event("PUBLISH.manual_research_link", "Validate manual ChatGPT research link", "failed" if not args.dry_run else "skipped", output_summary=message, report_id=research_id, metadata={"research_id": research_id, "required_field": "Research Document URL"})
        if args.dry_run:
            run_logs.finish(run_id, "success", result_count=0, message=f"dry-run blocked: {message}")
            print(f"weekly_publish dry-run: blocked; {message}")
            raise SystemExit(0)
        blocked_notice = send_dingtalk_webhook_markdown(
            settings.dingtalk.daily_webhook_url,
            settings.dingtalk.daily_signing_secret,
            "Weekly Insight blocked: missing research document",
            f"### Weekly Insight 未发送\n\n周期：{range_label}\n\n请在 Research Queue `{queue_label}` 的 `Research Document URL` 填入已完成的钉钉文档链接，然后重新运行周日发布。\n\n本次未发送、未写 Weekly Intelligence Sent At。",
            "",
        )
        audit_event("PUBLISH.blocked_notice", "Notify missing manual research link", blocked_notice.status, output_summary=blocked_notice.message, report_id=research_id, metadata={"notification": blocked_notice.__dict__})
        raise RuntimeError(message)

    link_content = build_weekly_research_link_content(
        accepted,
        range_label,
        research_topic,
        research_document_url,
        max_items_per_section,
    )
    audit_event("PUBLISH.manual_research_link", "Validate manual ChatGPT research link", "success", output_summary="Manual DingTalk research document linked; image One Pager generation skipped.", result_count=len(accepted), source_record_ids=selected_ids, report_id=research_id, artifact_url=research_document_url)
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(accepted), message=f"dry-run selected {len(accepted)} accepted Event records with manual research link")
        audit_event("PUBLISH.complete", "Complete weekly link digest", "success", output_summary="Dry-run rendered report link plus weekly Event/news digest without document/image creation or writeback.", result_count=len(accepted), source_record_ids=selected_ids, report_id=research_id, artifact_url=research_document_url)
        print(f"weekly_publish dry-run: selected={len(accepted)}; manual_research_link=yes")
        print(link_content)
        raise SystemExit(0)

    insights_table = ensure_insights_sheet(settings, store)
    if research_queue.get("id"):
        queue_update = update_records(settings.dingtalk, queue_table, [{"id": research_queue["id"], "fields": {"Deep Research Status": "Ready for Sunday link delivery", "Coverage Checked At": now.isoformat(timespec="seconds"), "Updated At": now.isoformat(timespec="seconds")}}])
        if queue_update.status != "sent":
            raise RuntimeError(queue_update.message)
    report_id = f"gbss-weekly-{now.date().isoformat()}-manual-research-link"
    target_url = settings.dingtalk.weekly_webhook_url or settings.dingtalk.daily_webhook_url
    target_secret = settings.dingtalk.weekly_signing_secret or settings.dingtalk.daily_signing_secret
    notification = send_dingtalk_webhook_markdown(target_url, target_secret, "GBSS Weekly AI & Service Intelligence", link_content, "")
    published_at = datetime.now(ZoneInfo(settings.system.timezone)).isoformat(timespec="seconds")
    save_insight_report(
        settings,
        insights_table,
        report_id,
        "Final",
        "已发布" if notification.status == "sent" else "发送失败",
        range_label,
        link_content,
        accepted,
        now,
        published_at=published_at if notification.status == "sent" else "",
        report_content_excerpt=link_content,
        report_doc_url=research_document_url,
        text_report_url=research_document_url,
        image_dingtalk_status="skipped",
        image_dingtalk_message="Image One Pager disabled; weekly delivery is report link plus news digest.",
        text_dingtalk_status=notification.status,
        text_dingtalk_message=notification.message,
        dingtalk_status=notification.status,
        dingtalk_message=notification.message,
        research_id=research_id,
        research_quality_status="Manual ChatGPT Deep Research",
        research_quality_gate="User-provided DingTalk research document; weekly message links the document and retains Event source dates/URLs.",
    )
    audit_event("PUBLISH.notify", "Send research link and weekly news digest", notification.status, output_summary=notification.message, result_count=len(accepted), source_record_ids=selected_ids, report_id=report_id, artifact_url=research_document_url, metadata={"notification": notification.__dict__, "delivery_mode": "manual_research_link_plus_news"})
    if notification.status != "sent":
        raise RuntimeError(notification.message)
    sent_at = now.date().isoformat()
    updated_ids = write_sent_markers(settings, weekly_input, "Weekly Intelligence Sent At", sent_at)
    run_logs.finish(run_id, "success", result_count=len(updated_ids), message=f"published manual research link plus {len(accepted)} Event records")
    audit_event("PUBLISH.complete", "Complete weekly link digest", "success", output_summary=f"Published manual research link plus {len(accepted)} unique Event records; no image One Pager generated.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids), report_id=report_id, artifact_url=research_document_url)
    print(f"weekly_publish success: manual_research_link=yes; published={len(updated_ids)}")
    raise SystemExit(0)

    evidence_rows = upsert_evidence_from_news(settings, research_tables.evidence, research_id, accepted)
    research_context = load_research_context(settings, research_tables, research_id)
    claim_rows = upsert_claim_candidates(settings, research_tables.claims, research_id, research_context["evidence"])
    research_context = load_research_context(settings, research_tables, research_id)
    research_context["openaiDeepResearch"] = load_result(DATA, research_id)
    evidence_ids = ", ".join(str((row.get("fields") or {}).get("Evidence ID") or "") for row in research_context["evidence"] if (row.get("fields") or {}).get("Evidence ID"))
    claim_ids = ", ".join(str((row.get("fields") or {}).get("Claim ID") or "") for row in research_context["claims"] if (row.get("fields") or {}).get("Claim ID"))
    research_quality_status = str(research_context["quality"].get("status") or "Signal Brief")
    research_quality_gate = "; ".join(str(item) for item in research_context["quality"].get("blockers") or [])
    audit_event("PUBLISH.research", "Prepare research evidence and claims", "success", output_summary=f"Research {research_id}: evidence={len(evidence_rows)}, claim candidates={len(claim_rows)}, quality={research_context['quality']['status']}.", result_count=len(evidence_rows), source_record_ids=selected_ids, report_id=research_id, metadata=research_context["quality"])
    content = build_competitor_report_content(
        accepted,
        range_label,
        settings.dingtalk_ai_table.approval_view_url,
        max_items_per_section,
        draft=False,
        research_topic=current_topic,
        next_topics=next_topics,
        research_context=research_context,
    )
    audit_event("PUBLISH.render", "Render final report data", "success", output_summary="Generated full report content and one-page report SVG.", result_count=len(accepted), source_record_ids=selected_ids, metadata={"report_title": f"{now:%Y-%m} W{iso_week:02d} GBSS Weekly AI & Service Intelligence - Final"})
    report_title = f"{now:%Y-%m} W{iso_week:02d} GBSS Weekly AI & Service Intelligence - Final"
    image_report_title = f"{report_title} - Image"
    text_report_title = f"{report_title} - Text"
    report_svg = build_one_page_report_svg(
        accepted,
        range_label,
        draft=False,
        research_topic=current_topic,
        next_topics=next_topics,
        generated_at=now,
        group_qr_path=str(GROUP_QR_PATH),
        research_context=research_context,
    )
    _, image_path = save_one_page_report(report_svg, DATA / "reports", f"{now:%Y-%m}-W{iso_week:02d}-final")
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(accepted), message=f"dry-run selected {len(accepted)} accepted records")
        audit_event("PUBLISH.complete", "Complete weekly final report", "success", output_summary="Dry-run completed without document creation, group send or News writeback.", result_count=len(accepted), source_record_ids=selected_ids, artifact_path=str(image_path or ""))
        print(f"weekly_publish dry-run: selected={len(accepted)}")
        print(content)
        raise SystemExit(0)
    insights_table = ensure_insights_sheet(settings, store)
    report_id = f"gbss-weekly-{now.date().isoformat()}-final"
    text_doc = create_report_document(
        settings,
        store,
        text_report_title,
        report_content_to_document_markdown(content),
    )
    text_permission = make_document_org_readable(settings, text_doc)
    audit_event("PUBLISH.text_document", "Create final full report document", "success", output_summary=f"Full report document created; permission={text_permission.status}.", result_count=len(accepted), source_record_ids=selected_ids, report_id=report_id, artifact_url=text_doc.url, metadata={"permission": text_permission.__dict__})
    report_svg = build_one_page_report_svg(
        accepted,
        range_label,
        draft=False,
        research_topic=current_topic,
        next_topics=next_topics,
        generated_at=now,
        detail_url=text_doc.url,
        group_qr_path=str(GROUP_QR_PATH),
        research_context=research_context,
    )
    _, image_path = save_one_page_report(report_svg, DATA / "reports", f"{now:%Y-%m}-W{iso_week:02d}-final")
    image_doc = create_report_document(
        settings,
        store,
        image_report_title,
        one_page_report_markdown(report_svg, image_report_title),
    )
    image_permission = make_document_org_readable(settings, image_doc)
    audit_event("PUBLISH.image_document", "Create final image report document", "success", output_summary=f"Image report document created; permission={image_permission.status}.", result_count=1, report_id=report_id, artifact_url=image_doc.url, artifact_path=str(image_path or ""), metadata={"permission": image_permission.__dict__})
    settings = store.load(masked=False)
    image_notification_content = build_image_report_notification_content(
        content,
        image_doc.url,
        draft=False,
    )
    notification_content = image_notification_content
    save_insight_report(
        settings,
        insights_table,
        report_id,
        "Final",
        "待发送",
        range_label,
        content,
        accepted,
        now,
        report_content_excerpt=notification_content,
        report_doc_url=text_doc.url,
        report_doc_node_id=text_doc.node_id,
        report_doc_key=text_doc.doc_key,
        report_doc_workspace_id=text_doc.workspace_id,
        image_report_url=image_doc.url,
        image_report_node_id=image_doc.node_id,
        image_report_key=image_doc.doc_key,
        text_report_url=text_doc.url,
        text_report_node_id=text_doc.node_id,
        text_report_key=text_doc.doc_key,
        image_file_path=str(image_path or ""),
        image_permission_status=image_permission.status,
        image_permission_message=image_permission.message,
        text_permission_status=text_permission.status,
        text_permission_message=text_permission.message,
        research_id=research_id,
        evidence_ids=evidence_ids,
        claim_ids=claim_ids,
        research_quality_status=research_quality_status,
        research_quality_gate=research_quality_gate,
    )
    audit_event("PUBLISH.insights_pending", "Store final report in Insights", "success", output_summary="Final report stored in Insights with pending-delivery status.", result_count=len(accepted), source_record_ids=selected_ids, report_id=report_id, artifact_url=text_doc.url)
    target_url = settings.dingtalk.weekly_webhook_url or settings.dingtalk.daily_webhook_url
    image_notification = NotificationResult(status="skipped", message="image file is not available")
    if image_path:
        try:
            media_id = upload_dingtalk_media(settings.dingtalk, image_path)
            pic_url = build_dingtalk_media_download_url(settings.dingtalk, media_id)
            image_notification = send_dingtalk_robot_group_image(settings.dingtalk, target_url, pic_url)
        except Exception as exc:
            image_notification = NotificationResult(status="failed", message=str(exc))
    if image_notification.status != "sent":
        image_notification = NotificationResult(
            status="failed",
            message=f"image-only delivery failed; no text fallback was sent: {image_notification.message}",
        )
    audit_event("PUBLISH.notify", "Send final report image", image_notification.status, output_summary=image_notification.message, result_count=1, report_id=report_id, artifact_url=image_doc.url, artifact_path=str(image_path or ""), metadata={"notification": image_notification.__dict__})
    text_notification = NotificationResult(status="skipped", message="text doc generated for QR only; no text message sent")
    notification_status = "sent" if image_notification.status == "sent" else "failed"
    notification_message = f"image: {image_notification.message}; text: {text_notification.message}"
    published_at = datetime.now(ZoneInfo(settings.system.timezone)).isoformat(timespec="seconds")
    save_insight_report(
        settings,
        insights_table,
        report_id,
        "Final",
        "已发布" if notification_status == "sent" else "发送失败",
        range_label,
        content,
        accepted,
        now,
        published_at=published_at if notification_status == "sent" else "",
        report_content_excerpt=notification_content,
        report_doc_url=text_doc.url,
        report_doc_node_id=text_doc.node_id,
        report_doc_key=text_doc.doc_key,
        report_doc_workspace_id=text_doc.workspace_id,
        image_report_url=image_doc.url,
        image_report_node_id=image_doc.node_id,
        image_report_key=image_doc.doc_key,
        text_report_url=text_doc.url,
        text_report_node_id=text_doc.node_id,
        text_report_key=text_doc.doc_key,
        image_file_path=str(image_path or ""),
        image_permission_status=image_permission.status,
        image_permission_message=image_permission.message,
        text_permission_status=text_permission.status,
        text_permission_message=text_permission.message,
        image_dingtalk_status=image_notification.status,
        image_dingtalk_message=image_notification.message,
        text_dingtalk_status=text_notification.status,
        text_dingtalk_message=text_notification.message,
        dingtalk_status=notification_status,
        dingtalk_message=notification_message,
        research_id=research_id,
        evidence_ids=evidence_ids,
        claim_ids=claim_ids,
        research_quality_status=research_quality_status,
        research_quality_gate=research_quality_gate,
    )
    audit_event("PUBLISH.insights_final", "Update final report delivery status", notification_status, output_summary=notification_message, result_count=len(accepted), source_record_ids=selected_ids, report_id=report_id, artifact_url=text_doc.url)
    if notification_status != "sent":
        raise RuntimeError(notification_message)
    sent_at = datetime.now(ZoneInfo(settings.system.timezone)).date().isoformat()
    updated_ids = write_sent_markers(settings, weekly_input, "Weekly Intelligence Sent At", sent_at)
    audit_event("PUBLISH.writeback", "Write Weekly Intelligence Sent At", "success", output_summary=f"Updated Weekly Intelligence Sent At for {len(updated_ids)} News records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids), report_id=report_id)
    run_logs.finish(run_id, "success", result_count=len(updated_ids), message=f"published {len(updated_ids)} accepted records")
    audit_event("PUBLISH.complete", "Complete weekly final report", "success", output_summary=f"Published {len(updated_ids)} accepted records.", result_count=len(updated_ids), source_record_ids=", ".join(updated_ids), report_id=report_id, artifact_url=text_doc.url, artifact_path=str(image_path or ""))
    print(f"weekly_publish success: published={len(updated_ids)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="weekly publish failed", error=str(exc))
    audit_event("PUBLISH.complete", "Complete weekly final report", "failed", error=str(exc))
    raise
