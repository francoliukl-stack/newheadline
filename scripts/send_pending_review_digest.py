"""Send an on-demand digest of News still awaiting a human decision.

The daily reminder deliberately covers only the previous day's batch. This is
the wider ad-hoc view: everything still pending inside a window, grouped by what
the AI recommended, so an operator can re-check rejections rather than only
confirming acceptances.

Read-only against the business table; the only write is the DingTalk message.
Whatever falls outside the window or a per-section cap is stated in the message
rather than silently dropped.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.audit_trail import AuditTrailWriter  # noqa: E402
from app.dingtalk_ai_table import cell_text, list_records, status_name  # noqa: E402
from app.notifications import build_dingtalk_ai_table_url, send_dingtalk_action_card  # noqa: E402
from app.publish_dates import parse_date  # noqa: E402
from app.run_logs import RunLogStore  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402

DATA = ROOT / "data"
CANONICAL_SHEET_ID = "oMbefcK"
SECTION_CAP = 40

parser = argparse.ArgumentParser(description="Send an on-demand pending-News review digest.")
parser.add_argument("--days", type=int, default=7, help="publish-date window to list")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
settings = store.load(masked=False)
settings.dingtalk_ai_table.sheet_id = CANONICAL_SHEET_ID
now = datetime.now(ZoneInfo(settings.system.timezone))
today = now.date()
cutoff = today - timedelta(days=max(args.days - 1, 0))


def source_link(fields) -> str:
    raw = fields.get("Source URL")
    url = raw.get("link") if isinstance(raw, dict) else raw
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    label = cell_text(fields.get("Source Domain")).strip() or (urlparse(url).hostname or "").removeprefix("www.")
    return f" ([{label or '来源'}]({url}))"


records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
pending = [
    record.get("fields") or {}
    for record in records
    if status_name(record.get("fields") or {}, settings.dingtalk_ai_table.field_mapping) == "待处理"
]

in_window, older, undated = [], 0, 0
for fields in pending:
    published = parse_date(fields.get("Publish Date"))
    if not published:
        undated += 1
        continue
    if date.fromisoformat(published) >= cutoff:
        in_window.append(fields)
    else:
        older += 1

groups = {"已采纳": [], "已拒绝": [], "已重复": [], "未标记": []}
for fields in in_window:
    groups.get(cell_text(fields.get("AI Status")), groups["未标记"]).append(fields)
for rows in groups.values():
    rows.sort(key=lambda item: (parse_date(item.get("Publish Date")) or "", cell_text(item.get("Title"))), reverse=True)

sections = [
    "### 📋 待确认 News 全量复核",
    f"窗口：**Publish Date ≥ {cutoff.isoformat()}**（最近 {args.days} 天）  ",
    f"窗口内待处理：**{len(in_window)}**  ",
    f"AI 建议采纳 / 拒绝 / 重复 / 未标记：**{len(groups['已采纳'])} / {len(groups['已拒绝'])} / {len(groups['已重复'])} / {len(groups['未标记'])}**  ",
    f"窗口外仍待处理：**{older}**；缺发布日期：**{undated}**；待处理合计：**{len(pending)}**  ",
]

titles = {"已采纳": "AI 建议采纳（优先确认）", "已拒绝": "AI 建议拒绝（请复核是否误杀）", "未标记": "AI 未标记", "已重复": "AI 判为重复"}
for key in ("已采纳", "已拒绝", "未标记", "已重复"):
    rows = groups[key]
    if not rows:
        continue
    shown = rows[:SECTION_CAP]
    lines = [
        f"- {parse_date(f.get('Publish Date')) or '?'} · {cell_text(f.get('Title')) or '（无标题）'}{source_link(f)}"
        for f in shown
    ]
    header = f"**{titles[key]}（{len(rows)}）**"
    if len(rows) > len(shown):
        header += f" — 仅列出前 {len(shown)} 条，其余 {len(rows) - len(shown)} 条请在审核视图查看"
    sections.append(header + "\n" + "\n".join(lines))

sections.append(
    "人工 Status 永远优先于 AI 建议。标记为已采纳后，关联 Event 会自动进入发布候选；"
    "非英文与中文的标题现已默认建议拒绝，确有价值时人工直接覆盖即可。"
)
content = "\n\n".join(sections)
review_url = settings.dingtalk_ai_table.approval_view_url or build_dingtalk_ai_table_url(settings.dingtalk_ai_table.base_id)

if args.dry_run:
    print(f"dry-run: pending={len(pending)}; in_window={len(in_window)}; older={older}; undated={undated}; bytes={len(content.encode('utf-8'))}")
    print(content)
    raise SystemExit(0)

run_logs = RunLogStore(DATA / "settings.sqlite3")
audit = AuditTrailWriter(settings, store, run_logs)
run_id = run_logs.start("pending_review_digest", provider="dingtalk_ai_table", metadata={"days": args.days})
try:
    notification = send_dingtalk_action_card(
        settings.dingtalk.daily_webhook_url,
        settings.dingtalk.daily_signing_secret,
        "GBSS 待确认 News 全量复核",
        content,
        "打开审核视图",
        review_url,
        settings.dingtalk.at_mobiles,
    )
    status = "success" if notification.status == "sent" else notification.status
    run_logs.finish(run_id, status, result_count=len(in_window), message=notification.message)
    audit.record(
        run_id=run_id, workflow="pending_review_digest", stage_code="REVIEW.digest",
        stage_name="Send on-demand pending review digest", status=status,
        output_summary=notification.message, result_count=len(in_window),
        related_sheet=settings.dingtalk_ai_table.sheet_id,
        metadata={"in_window": len(in_window), "older": older, "undated": undated, "pending_total": len(pending)},
    )
    print(f"pending_review_digest {status}: in_window={len(in_window)}; pending_total={len(pending)}; {notification.message}")
    raise SystemExit(0 if status == "success" else 1)
except SystemExit:
    raise
except Exception as exc:
    run_logs.finish(run_id, "failed", message="pending review digest failed", error=str(exc))
    raise
