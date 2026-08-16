"""Generate the weekly Insight analysis article and link it from the report.

Replaces the manual ChatGPT Deep Research handoff. The article is written from
the same Events the weekly report carries, saved to the existing GBSS Research
Reports folder, and its URL written into the Research Queue row so the Sunday
report links it.

Fails closed: if no carrier is available, or the article does not cite the
evidence it was given, nothing is written and the report falls back to its
verified-fact layer rather than linking an unvalidated document.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import cell_text, list_records, update_records  # noqa: E402
from app.dingtalk_docs import create_report_document  # noqa: E402
from app.event_weekly import load_weekly_input  # noqa: E402
from app.llm_carrier import ALL_CARRIERS, CarrierUnavailable, run_prompt  # noqa: E402
from app.research_production import build_research_input_fields, extract_research_document_url, research_input_preflight, select_manual_research_queue  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.weekly_insight_article import article_title, build_article_prompt, validate_article  # noqa: E402

DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"

parser = argparse.ArgumentParser(description="Generate and publish the weekly Insight analysis article.")
parser.add_argument("--days", type=int, default=7)
parser.add_argument("--carriers", default=",".join(ALL_CARRIERS))
parser.add_argument("--dry-run", action="store_true", help="generate and print without creating a document or writing the queue")
parser.add_argument("--force", action="store_true", help="regenerate even when an up-to-date article is already linked")
parser.add_argument("--for-publish-day", action="store_true", help="size the weekly window from the upcoming Sunday publish rather than today")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
run_logs = RunLogStore(DATA / "settings.sqlite3")
audit = AuditTrailWriter(settings, store, run_logs)
now = datetime.now(ZoneInfo(settings.system.timezone))
written_at = now
if args.for_publish_day:
    # The weekly window is a rolling `days`-long range ending at `now`, and the
    # Research Queue row is looked up by the label that range produces. Writing
    # the article on Saturday evening for a Sunday publish would therefore file
    # it under a range the publish run never asks for. Advance to the upcoming
    # Sunday so both runs agree on the label; today counts when it is already
    # Sunday, so the noon safety-net call still matches.
    now = now + timedelta(days=(6 - now.weekday()) % 7)
run_id = run_logs.start("generate_weekly_insight", provider="subscription_carrier", metadata={"days": args.days, "for_publish_day": args.for_publish_day, "window_ends": now.date().isoformat()})

try:
    weekly_input = load_weekly_input(
        settings, now, days=args.days, recent_count=0, include_sent=True,
        max_items=settings.rules.max_items_per_category,
        sent_fields=("Weekly Intelligence Sent At", "Weekly Sent At"),
    )
    records, range_label = weekly_input.report_records, weekly_input.range_label
    print(f"generate_weekly_insight: {len(records)} events for {range_label}")
    if not records:
        run_logs.finish(run_id, "success", result_count=0, message="no events in window; nothing to analyse")
        print("generate_weekly_insight: nothing to analyse")
        raise SystemExit(0)

    queue_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.research_queue_sheet_id})
    queue_records = list_records(settings.dingtalk, queue_table) if settings.dingtalk_ai_table.research_queue_sheet_id else []
    research_queue = select_manual_research_queue(queue_records, range_label, now=now)
    queue_fields = research_queue.get("fields") or {}
    research_topic = cell_text(queue_fields.get("Topic"))

    # The article is generated on Sunday morning so it can be reviewed before the
    # noon publish, and the publish run calls this script again as a safety net.
    # Reusing an article that already analysed exactly the current event set is
    # what makes that second call harmless: it protects the reviewed version
    # instead of silently replacing it. A drifted event set still regenerates,
    # so the report can never link a document describing other events.
    existing_url = extract_research_document_url(queue_fields.get("Research Document URL"))
    reuse_preflight = research_input_preflight(queue_fields, records)
    if not args.force and existing_url.startswith(("https://", "http://")) and reuse_preflight["matched"]:
        message = f"reused reviewed article for {range_label}; {existing_url}"
        run_logs.finish(run_id, "success", result_count=len(records), message=message, metadata={"reused": True, "preflight": reuse_preflight})
        audit.record(
            run_id=run_id, workflow="generate_weekly_insight", stage_code="RESEARCH.reuse_article",
            stage_name="Reuse the already-linked weekly Insight article", status="success",
            input_summary=f"{len(records)} events for {range_label}", output_summary=message,
            result_count=len(records), artifact_url=existing_url,
            related_sheet=queue_table.sheet_id, metadata={"reused": True, "preflight": reuse_preflight},
        )
        print(f"generate_weekly_insight: {message}")
        raise SystemExit(0)
    if existing_url and not reuse_preflight["matched"]:
        print(
            f"generate_weekly_insight: regenerating; event set drifted "
            f"(added={reuse_preflight['added_event_ids']}, removed={reuse_preflight['removed_event_ids']})"
        )

    carriers = tuple(name.strip() for name in args.carriers.split(",") if name.strip())
    response = run_prompt(build_article_prompt(records, range_label, research_topic), carriers=carriers)
    article = response.text.strip()
    errors = validate_article(article, records)
    if errors:
        raise RuntimeError(f"generated article rejected: {'; '.join(errors)}")
    print(f"generate_weekly_insight: {len(article)} chars via {response.carrier} (degraded={response.degraded})")

    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(records), message=f"dry-run generated {len(article)} chars via {response.carrier}")
        print("---")
        print(article)
        raise SystemExit(0)

    document = create_report_document(settings, store, article_title(range_label), article)
    print(f"generate_weekly_insight: document created {document.url}")

    if research_queue.get("id"):
        # Stamp the event set this article actually analysed. The drift check
        # exists because a hand-written document could describe events the
        # report no longer carries; an article generated from the current set
        # immediately before publication is synchronised by construction, and
        # without the stamp the report would discard the link it just created.
        patch = {
            # The field is a DingTalk link cell; a plain string is rejected.
            "Research Document URL": {"text": document.title, "link": document.url},
            "Deep Research Status": "Generated by assistant; pending human review",
            # Timestamps record when the article was actually written; only the
            # weekly window follows the publication day.
            "Updated At": written_at.isoformat(timespec="seconds"),
            **build_research_input_fields(records, written_at.isoformat(timespec="seconds")),
        }
        result = update_records(settings.dingtalk, queue_table, [{"id": research_queue["id"], "fields": patch}])
        if result.status != "sent":
            raise RuntimeError(result.message)
        print(f"generate_weekly_insight: Research Queue {cell_text(queue_fields.get('Research ID'))} linked")
    else:
        print("generate_weekly_insight: no Research Queue row for this period; document created but not linked")

    message = f"generated weekly insight article ({len(article)} chars) via {response.carrier}; {document.url}"
    run_logs.finish(run_id, "success", result_count=len(records), message=message, metadata=response.as_metadata())
    audit.record(
        run_id=run_id, workflow="generate_weekly_insight", stage_code="RESEARCH.generate_article",
        stage_name="Generate weekly Insight analysis article", status="success",
        input_summary=f"{len(records)} events for {range_label}", output_summary=message,
        result_count=len(records), artifact_url=document.url,
        related_sheet=queue_table.sheet_id, metadata=response.as_metadata(),
    )
    print(f"generate_weekly_insight success: {message}")
except SystemExit:
    raise
except CarrierUnavailable as exc:
    run_logs.finish(run_id, "failed", message="no analysis carrier available", error=str(exc))
    audit.record(
        run_id=run_id, workflow="generate_weekly_insight", stage_code="RESEARCH.generate_article",
        stage_name="Generate weekly Insight analysis article", status="failed",
        output_summary="No subscription carrier could serve the request; weekly report keeps its verified-fact layer.",
        error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id,
    )
    raise
except Exception as exc:
    run_logs.finish(run_id, "failed", message="weekly insight generation failed", error=str(exc))
    audit.record(
        run_id=run_id, workflow="generate_weekly_insight", stage_code="RESEARCH.generate_article",
        stage_name="Generate weekly Insight analysis article", status="failed",
        error=str(exc), related_sheet=settings.dingtalk_ai_table.sheet_id,
    )
    raise
