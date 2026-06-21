from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .dingtalk_ai_table import add_records, create_sheet, ensure_fields, list_records, list_sheets, update_records
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


RESEARCH_TOPICS_SHEET_NAME = "Research Topics"
RESEARCH_TOPIC_FIELDS = [
    {"name": "Topic ID", "type": "text"},
    {"name": "Publish Week", "type": "text"},
    {"name": "Publish Date", "type": "text"},
    {"name": "Status", "type": "text"},
    {"name": "Priority", "type": "text"},
    {"name": "Topic", "type": "text"},
    {"name": "Research Question", "type": "text"},
    {"name": "Why It Matters", "type": "text"},
    {"name": "Scope", "type": "text"},
    {"name": "Source Signals", "type": "text"},
    {"name": "Output Type", "type": "text"},
    {"name": "Owner", "type": "text"},
    {"name": "Insight Record ID", "type": "text"},
    {"name": "Updated At", "type": "text"},
]


DEFAULT_TOPIC_PIPELINE = [
    {
        "topic": "AI Agent Commerce and Programmable Payments",
        "question": "How will AI agents change payment initiation, authorization, fraud control, and merchant/customer ownership?",
        "why": "Visa/OpenAI and card-network agent initiatives suggest the payment layer is moving closer to AI decision flows.",
        "scope": "Visa, Mastercard, OpenAI, Stripe, stablecoin settlement, tokenization, agent identity, transaction controls.",
        "signals": "AI payment partnerships, agent registry/scoring, programmable money, merchant adoption, risk controls.",
    },
    {
        "topic": "Enterprise Voice AI in Regulated Operations",
        "question": "What makes voice AI production-ready for regulated service operations, and where can GBSS adopt it safely?",
        "why": "Voice AI is moving from demo to on-prem, confidential-computing, compliance-sensitive deployment.",
        "scope": "Deepgram, NVIDIA, Fortanix, contact center AI, data residency, auditability, model security.",
        "signals": "On-prem voice AI, confidential inference, regulated-industry deployments, call-center ROI evidence.",
    },
    {
        "topic": "Cross-border Operating Infrastructure for Global SMBs",
        "question": "How are payment platforms abstracting tax, disputes, treasury, payout, and compliance for global expansion?",
        "why": "Stripe and peers are packaging operating complexity into infrastructure, reshaping what business support teams must provide.",
        "scope": "Stripe, Airwallex, Wise, Payoneer, WorldFirst, Antom, treasury, payout, managed payments.",
        "signals": "Managed payments, multi-currency accounts, payout coverage, tax/dispute automation, SMB global sales tools.",
    },
    {
        "topic": "Stablecoin Settlement and Programmable Treasury",
        "question": "Where are stablecoin settlement and programmable treasury becoming practical enterprise infrastructure?",
        "why": "Payment networks and fintechs are using stablecoins to compete on settlement speed, liquidity, and always-on money movement.",
        "scope": "Visa, Mastercard, Stripe, PayPal, Circle, banks, B2B settlement, treasury operations.",
        "signals": "Stablecoin settlement launches, bank partnerships, treasury products, regulatory clarity, enterprise use cases.",
    },
    {
        "topic": "Emerging Market Service Automation and Localized AI",
        "question": "Which emerging-market service workflows can AI automate faster because phone-first and local-language needs are stronger?",
        "why": "AethexAI and similar companies indicate voice-first service automation may have high ROI in Africa, Middle East, and other emerging markets.",
        "scope": "AethexAI, regional voice AI, KYC, debt collection, customer support, local languages, telecom channels.",
        "signals": "Funding, local-language models, call-center automation, enterprise pilots, unit economics.",
    },
]


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _topic_table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def ensure_research_topics_sheet(settings: AppSettings, store: Optional[SettingsStore] = None) -> DingTalkAITableSettings:
    sheet_id = settings.dingtalk_ai_table.research_topics_sheet_id.strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk AI table sheets"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, RESEARCH_TOPICS_SHEET_NAME)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, RESEARCH_TOPICS_SHEET_NAME, RESEARCH_TOPIC_FIELDS)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or "failed to create Research Topics sheet"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError("Research Topics sheet id is missing")

    topic_table = _topic_table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, topic_table, RESEARCH_TOPIC_FIELDS)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or "failed to ensure Research Topics fields"))

    if settings.dingtalk_ai_table.research_topics_sheet_id != sheet_id:
        settings.dingtalk_ai_table.research_topics_sheet_id = sheet_id
        if store:
            store.save(settings)
    return topic_table


def next_publish_sunday(anchor: Optional[date] = None) -> date:
    current = anchor or date.today()
    days_until_sunday = (6 - current.weekday()) % 7
    return current + timedelta(days=days_until_sunday)


def default_topic_records(anchor: Optional[date] = None) -> List[Dict[str, Any]]:
    first_publish = next_publish_sunday(anchor)
    updated_at = datetime.now().isoformat(timespec="seconds")
    records: List[Dict[str, Any]] = []
    for index, topic in enumerate(DEFAULT_TOPIC_PIPELINE):
        publish_date = first_publish + timedelta(days=index * 7)
        records.append({
            "Topic ID": f"research-{publish_date.isoformat()}",
            "Publish Week": f"Week of {publish_date.isoformat()}",
            "Publish Date": publish_date.isoformat(),
            "Status": "Locked" if index == 0 else "Planned",
            "Priority": f"P{1 if index < 2 else 2}",
            "Topic": topic["topic"],
            "Research Question": topic["question"],
            "Why It Matters": topic["why"],
            "Scope": topic["scope"],
            "Source Signals": topic["signals"],
            "Output Type": "GBSS Weekly AI & Service Intelligence",
            "Owner": "GBSS Strategy / Ops",
            "Insight Record ID": "",
            "Updated At": updated_at,
        })
    return records


def sync_research_topic_roadmap(
    settings: AppSettings,
    topic_table: DingTalkAITableSettings,
    anchor: Optional[date] = None,
) -> List[str]:
    desired = default_topic_records(anchor)
    existing = list_records(settings.dingtalk, topic_table)
    existing_by_id = {
        str((record.get("fields") or {}).get("Topic ID") or ""): record
        for record in existing
        if (record.get("fields") or {}).get("Topic ID")
    }
    touched: List[str] = []
    to_create = []
    to_update = []
    for row in desired:
        existing_record = existing_by_id.get(row["Topic ID"])
        if existing_record:
            current_fields = existing_record.get("fields") or {}
            update = {**row}
            if current_fields.get("Status") and current_fields.get("Status") != row["Status"]:
                update["Status"] = current_fields["Status"]
            if current_fields.get("Topic") and current_fields.get("Topic") != row["Topic"]:
                update["Topic"] = current_fields["Topic"]
            if current_fields.get("Research Question") and current_fields.get("Research Question") != row["Research Question"]:
                update["Research Question"] = current_fields["Research Question"]
            to_update.append({"id": existing_record["id"], "fields": update})
            touched.append(str(existing_record["id"]))
        else:
            to_create.append(row)
    if to_update:
        result = update_records(settings.dingtalk, topic_table, to_update)
        if result.status != "sent":
            raise RuntimeError(result.message)
    if to_create:
        result = add_records(settings.dingtalk, topic_table, to_create)
        if result.status != "sent":
            raise RuntimeError(result.message)
        touched.extend(result.record_ids)
    return touched


def topic_sort_key(record: Dict[str, Any]) -> Tuple[str, str]:
    fields = record.get("fields") or {}
    return str(fields.get("Publish Date") or ""), str(fields.get("Topic ID") or "")


def current_and_next_topics(records: List[Dict[str, Any]], anchor: Optional[date] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    current_date = anchor or date.today()
    candidates = sorted(records, key=topic_sort_key)
    locked = [
        record for record in candidates
        if str((record.get("fields") or {}).get("Status") or "").lower() == "locked"
    ]
    current = locked[0] if locked else {}
    if not current:
        upcoming = [
            record for record in candidates
            if str((record.get("fields") or {}).get("Publish Date") or "") >= current_date.isoformat()
        ]
        current = upcoming[0] if upcoming else (candidates[0] if candidates else {})
    next_topics = [record for record in candidates if record.get("id") != current.get("id")]
    next_topics = [
        record for record in next_topics
        if str((record.get("fields") or {}).get("Status") or "").lower() in {"planned", "candidate", "locked"}
    ]
    return current, next_topics[:4]
