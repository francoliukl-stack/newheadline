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
from app.notifications import NotificationResult, build_dingtalk_media_download_url, send_dingtalk_robot_group_image, upload_dingtalk_media  # noqa: E402
from app.publish_format import build_competitor_report_content, build_image_report_notification_content, report_content_to_document_markdown  # noqa: E402
from app.report_visual import build_one_page_report_svg, one_page_report_markdown, save_one_page_report  # noqa: E402
from app.research_topics import current_and_next_topics, ensure_research_topics_sheet, sync_research_topic_roadmap  # noqa: E402
from app.research_production import ensure_research_production_sheets, load_research_context, upsert_claim_candidates, upsert_evidence_from_news, upsert_research_queue  # noqa: E402
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
    topic_table = ensure_research_topics_sheet(settings, store)
    settings = store.load(masked=False)
    sync_research_topic_roadmap(settings, topic_table, now.date())
    topic_records = list_records(settings.dingtalk, topic_table)
    current_topic, next_topics = current_and_next_topics(topic_records, now.date())
    topic_fields = current_topic.get("fields") or {}
    audit_event("PUBLISH.topic", "Sync research topic roadmap", "success", output_summary=f"Current topic: {topic_fields.get('Topic') or '-'}; next topics: {len(next_topics)}.", result_count=len(topic_records), metadata={"current_topic": topic_fields.get("Topic") or "", "next_topic_count": len(next_topics)})
    research_tables = ensure_research_production_sheets(settings, store)
    research_queue = upsert_research_queue(settings, research_tables.queue, current_topic)
    research_id = str((research_queue.get("fields") or {}).get("Research ID") or "")
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
