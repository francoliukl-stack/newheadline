from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, Iterable, List

from .dingtalk_ai_table import add_records, cell_text, list_records
from .event_intelligence import EventCandidate
from .event_tables import EventIntelligenceTables
from .models import AppSettings
from .notifications import build_dingtalk_ai_table_url, send_dingtalk_action_card


def send_event_alerts(settings: AppSettings, tables: EventIntelligenceTables, events: Iterable[EventCandidate]) -> int:
    existing_rows = list_records(settings.dingtalk, tables.alert_log)
    existing = {cell_text((row.get("fields") or {}).get("Dedupe Key")) for row in existing_rows}
    existing_event_levels = {
        (cell_text((row.get("fields") or {}).get("Event ID")), cell_text((row.get("fields") or {}).get("Alert Level")))
        for row in existing_rows
    }
    review_url = settings.dingtalk_ai_table.approval_view_url or build_dingtalk_ai_table_url(settings.dingtalk_ai_table.base_id)
    sent = 0
    for event in events:
        if not event.strategic_candidate and event.priority_candidate != "P0_Candidate":
            continue
        level = "P0_Candidate" if event.priority_candidate == "P0_Candidate" else "Strategic_Event"
        dedupe_key = sha1(f"{event.event_id}|{level}".encode("utf-8")).hexdigest()
        if dedupe_key in existing or (event.event_id, level) in existing_event_levels:
            continue
        content = "\n\n".join([
            f"### {'🚨' if level == 'P0_Candidate' else '📌'} {level}",
            f"**{event.title}**",
            f"业务线：{', '.join(event.business_lines) or '-'}  ",
            f"事件类型：{event.event_type}  ",
            f"相关性：{event.overall_score:.2f}  ",
            f"来源数：{len(event.sources)}  ",
            "请审核关联 News。业务线、事件类型和影响方向由系统生成；最终 P0 仍必须人工批准。",
        ])
        notification = send_dingtalk_action_card(settings.dingtalk.daily_webhook_url, settings.dingtalk.daily_signing_secret, "GBSS 关键外部事件待审", content, "打开 News 审核", review_url, settings.dingtalk.at_mobiles)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        alert_id = f"alert-{sha1(dedupe_key.encode()).hexdigest()[:16]}"
        result = add_records(settings.dingtalk, tables.alert_log, [{"Alert ID": alert_id, "Event ID": event.event_id, "Alert Level": level, "Sent To": "BOT监控审核群", "Message": content, "Dedupe Key": dedupe_key, "Sent At": now if notification.status == "sent" else "", "Ack Status": "unacknowledged", "Ack By": "", "Ack At": "", "Error": "" if notification.status == "sent" else notification.message}])
        if result.status != "sent":
            raise RuntimeError(result.message)
        existing.add(dedupe_key)
        existing_event_levels.add((event.event_id, level))
        sent += notification.status == "sent"
    return sent
