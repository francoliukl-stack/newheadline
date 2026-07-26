"""Create a no-cost, paste-ready ChatGPT Deep Research handoff."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records, update_records  # noqa: E402
from app.research_production import build_research_input_fields, ensure_research_production_sheets, upsert_research_queue  # noqa: E402
from app.market_research_plan import build_chatgpt_manual_research_handoff, build_market_led_research_plan  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from app.event_weekly import load_weekly_input  # noqa: E402


DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=7)
parser.add_argument("--recent-count", type=int, default=0)
parser.add_argument("--include-sent", action="store_true")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
run_id = run_logs.start("weekly_research_plan", provider="chatgpt_manual")

try:
    now = datetime.now(ZoneInfo(settings.system.timezone))
    weekly_input = load_weekly_input(
        settings,
        now,
        days=args.days,
        recent_count=args.recent_count,
        include_sent=args.include_sent,
        max_items=settings.rules.max_items_per_category,
        sent_fields=("Weekly Intelligence Sent At", "Weekly Sent At"),
    )
    selected, period = weekly_input.report_records, weekly_input.range_label
    market_plan = build_market_led_research_plan(selected, period)
    handoff = build_chatgpt_manual_research_handoff(market_plan)
    topic = market_plan["topic_record"]
    titles = [row["title"] for row in market_plan["core_sources"]]
    plan = "\n".join([
        f"Period: {period}",
        f"Topic: {market_plan['topic']}",
        f"Question: {market_plan['question']}",
        f"Why now: {market_plan['why']}",
        f"Scope: {market_plan['scope']}",
        f"Accepted sources: {len(selected)}",
        "Market changes:",
        *[f"- {change}" for change in market_plan["market_changes"]],
        "Method: run manually in ChatGPT Deep Research; no project API call or project token cost.",
        "Research directions:",
        handoff["plan"],
        "Core news signals:",
        *[f"- {title}" for title in titles],
        "Context only:",
        *[f"- {row['title']}" for row in market_plan["context_sources"]],
        "",
        "Paste-ready ChatGPT prompt:",
        handoff["prompt"],
    ])
    if args.dry_run:
        run_logs.finish(run_id, "success", result_count=len(selected), message="manual ChatGPT research handoff dry-run")
        print(plan)
        raise SystemExit(0)
    tables = ensure_research_production_sheets(settings, store)
    queue = upsert_research_queue(settings, tables.queue, topic)
    approval = {
        "Approval Status": "Manual ChatGPT workflow",
        "Approval Plan": plan,
        "Approval Requested At": now.isoformat(timespec="seconds"),
        "Approved At": "",
        "Deep Research Status": "Waiting for manual ChatGPT report link",
        **build_research_input_fields(selected, now.isoformat(timespec="seconds")),
    }
    result = update_records(settings.dingtalk, tables.queue, [{"id": queue["id"], "fields": approval}])
    if result.status != "sent":
        raise RuntimeError(result.message)
    run_logs.finish(run_id, "success", result_count=len(selected), message="manual ChatGPT research handoff created", metadata={"research_id": queue["fields"]["Research ID"], "plan": plan})
    print(f"weekly_research_plan success: manual_chatgpt; research_id={queue['fields']['Research ID']}; selected={len(selected)}")
except Exception as exc:
    run_logs.finish(run_id, "failed", message="manual ChatGPT research handoff failed", error=str(exc))
    raise
