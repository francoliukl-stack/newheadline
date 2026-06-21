from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .dingtalk_ai_table import add_records, cell_text, create_sheet, ensure_fields, list_records, list_sheets
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


DETECT_SOURCES_SHEET_NAME = "Detect Sources"
DETECT_SOURCE_FIELDS = [
    {"name": "Source ID", "type": "text"},
    {"name": "Type", "type": "text"},
    {"name": "Name", "type": "text"},
    {"name": "Section", "type": "text"},
    {"name": "Keywords", "type": "text"},
    {"name": "Aliases", "type": "text"},
    {"name": "Domains", "type": "text"},
    {"name": "Priority", "type": "number"},
    {"name": "Enabled", "type": "text"},
    {"name": "Notes", "type": "text"},
    {"name": "Updated At", "type": "text"},
]


COMPANY_SEEDS = [
    ("company-antom", "company", "Antom", "Finance", "Antom", "Ant International, Alipay+", "antom.com, antgroup.com", 1, "self / baseline"),
    ("company-stripe", "company", "Stripe", "Finance", "Stripe", "", "stripe.com", 1, "payment benchmark"),
    ("company-adyen", "company", "Adyen", "Finance", "Adyen", "", "adyen.com", 1, "payment benchmark"),
    ("company-wise", "company", "Wise", "Finance", "Wise", "", "wise.com", 1, "cross-border benchmark"),
    ("company-airwallex", "company", "Airwallex", "Finance", "Airwallex", "", "airwallex.com", 1, "cross-border benchmark"),
    ("company-xtransfer", "company", "XTransfer", "Finance", "XTransfer", "", "xtransfer.com", 1, "cross-border benchmark"),
    ("company-paypal", "company", "PayPal", "Finance", "PayPal", "", "paypal.com", 2, "payment benchmark"),
    ("company-visa", "company", "Visa", "Finance", "Visa", "", "visa.com", 2, "network benchmark"),
    ("company-mastercard", "company", "Mastercard", "Finance", "Mastercard", "", "mastercard.com", 2, "network benchmark"),
    ("company-worldfirst", "company", "WorldFirst", "Finance", "WorldFirst", "", "worldfirst.com", 2, "cross-border benchmark"),
    ("company-deepgram", "company", "Deepgram", "Contact Center", "Deepgram", "Voice AI, Audio LLM", "deepgram.com", 1, "voice AI benchmark"),
    ("company-vapi", "company", "Vapi", "Contact Center", "Vapi", "Voice AI", "vapi.ai", 1, "voice AI benchmark"),
    ("company-sierra", "company", "Sierra.ai", "Contact Center", "Sierra.ai", "Sierra AI", "sierra.ai", 1, "AI customer service benchmark"),
    ("company-agentforce", "company", "Agentforce", "Contact Center", "Agentforce", "Salesforce Agentforce", "salesforce.com", 2, "enterprise AI agent benchmark"),
    ("company-amazon-connect", "company", "Amazon Connect", "Contact Center", "Amazon Connect", "AWS contact center AI", "aws.amazon.com", 2, "CCaaS benchmark"),
    ("company-twilio", "company", "Twilio", "Contact Center", "Twilio", "", "twilio.com", 2, "CCaaS benchmark"),
    ("company-genesys", "company", "Genesys", "Contact Center", "Genesys", "", "genesys.com", 2, "CCaaS benchmark"),
    ("company-nice", "company", "NICE", "Contact Center", "NICE", "", "nice.com", 2, "CCaaS benchmark"),
    ("company-five9", "company", "Five9", "Contact Center", "Five9", "", "five9.com", 2, "CCaaS benchmark"),
    ("company-talkdesk", "company", "Talkdesk", "Contact Center", "Talkdesk", "", "talkdesk.com", 2, "CCaaS benchmark"),
    ("company-zendesk", "company", "Zendesk", "Contact Center", "Zendesk", "", "zendesk.com", 3, "service platform benchmark"),
    ("company-intercom", "company", "Intercom", "Contact Center", "Intercom", "", "intercom.com", 3, "service platform benchmark"),
    ("company-elevenlabs", "company", "ElevenLabs", "Contact Center", "ElevenLabs", "Eleven Labs, Voice AI", "elevenlabs.io", 3, "voice AI benchmark"),
]

TOPIC_SEEDS = [
    ("topic-payments", "topic", "Payments / Fintech", "Finance", "fintech, payments, banking", "cross-border payments, stablecoin settlement, programmable payments", "", 1, "category search"),
    ("topic-contact-center-ai", "topic", "Contact Center AI", "Contact Center", "Voice AI, Contact Center AI, Conversational Intelligence", "Audio LLM, agent assist, AIQA, AIQC", "", 1, "category search"),
]

SOURCE_SEEDS = [
    ("domain-thepaypers-com", "source_domain", "thepaypers.com", "News", "", "", "thepaypers.com", 1, "payments and fintech industry coverage"),
    ("domain-callcentrehelper-com", "source_domain", "callcentrehelper.com", "News", "", "", "callcentrehelper.com", 1, "contact center and CCaaS industry coverage"),
]


@dataclass(frozen=True)
class PlannedQuery:
    key: str
    section: str
    text: str
    domains: List[str]


def _split_terms(value: Any) -> List[str]:
    text = cell_text(value)
    parts = []
    for chunk in text.replace("\n", ",").split(","):
        term = chunk.strip()
        if term:
            parts.append(term)
    return parts


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _detect_table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def default_detect_source_records(settings: Optional[AppSettings] = None) -> List[Dict[str, Any]]:
    updated_at = datetime.now().isoformat(timespec="seconds")
    records = []
    for source_id, source_type, name, section, keywords, aliases, domains, priority, notes in COMPANY_SEEDS + TOPIC_SEEDS + SOURCE_SEEDS:
        records.append({
            "Source ID": source_id,
            "Type": source_type,
            "Name": name,
            "Section": section,
            "Keywords": keywords,
            "Aliases": aliases,
            "Domains": domains,
            "Priority": priority,
            "Enabled": "true",
            "Notes": notes,
            "Updated At": updated_at,
        })
    if settings:
        existing_domains = {domain for row in records for domain in _split_terms(row.get("Domains"))}
        for item in settings.source_settings.sources:
            if item.domain in existing_domains:
                continue
            records.append({
                "Source ID": "domain-" + item.domain.replace(".", "-"),
                "Type": "source_domain",
                "Name": item.domain,
                "Section": "News",
                "Keywords": "",
                "Aliases": "",
                "Domains": item.domain,
                "Priority": item.weight,
                "Enabled": "true" if item.enabled else "false",
                "Notes": "news/source domain from local settings",
                "Updated At": updated_at,
            })
    return records


def ensure_detect_sources_sheet(settings: AppSettings, store: Optional[SettingsStore] = None) -> DingTalkAITableSettings:
    sheet_id = settings.dingtalk_ai_table.detect_sources_sheet_id.strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk AI table sheets"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, DETECT_SOURCES_SHEET_NAME)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, DETECT_SOURCES_SHEET_NAME, DETECT_SOURCE_FIELDS)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or "failed to create Detect Sources sheet"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError("Detect Sources sheet id is missing")

    detect_table = _detect_table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, detect_table, DETECT_SOURCE_FIELDS)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or "failed to ensure Detect Sources fields"))

    if settings.dingtalk_ai_table.detect_sources_sheet_id != sheet_id:
        settings.dingtalk_ai_table.detect_sources_sheet_id = sheet_id
        if store:
            store.save(settings)
    return detect_table


def sync_detect_sources(settings: AppSettings, detect_table: DingTalkAITableSettings) -> List[str]:
    existing = list_records(settings.dingtalk, detect_table)
    existing_ids = {
        cell_text((record.get("fields") or {}).get("Source ID"))
        for record in existing
        if cell_text((record.get("fields") or {}).get("Source ID"))
    }
    to_create = [
        row for row in default_detect_source_records(settings)
        if str(row.get("Source ID") or "") not in existing_ids
    ]
    if not to_create:
        return []
    result = add_records(settings.dingtalk, detect_table, to_create)
    if result.status != "sent":
        raise RuntimeError(result.message)
    return result.record_ids


def active_detect_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    active = []
    for record in records:
        fields = record.get("fields") or record
        enabled = cell_text(fields.get("Enabled") or "true").strip().lower()
        if enabled in {"false", "no", "0", "disabled", "停用"}:
            continue
        active.append(fields)
    return active


def _priority(fields: Dict[str, Any]) -> int:
    try:
        return int(float(cell_text(fields.get("Priority") or 99) or 99))
    except ValueError:
        return 99


def _unique_terms(values: Iterable[Any], max_terms: int = 60) -> List[str]:
    terms: List[str] = []
    seen = set()
    for value in values:
        for term in _split_terms(value):
            normalized = term.lower()
            if normalized not in seen:
                seen.add(normalized)
                terms.append(term)
            if len(terms) >= max_terms:
                return terms
    return terms


def _query_text(terms: Iterable[str]) -> str:
    formatted = []
    for term in terms:
        if " " in term or "+" in term or "/" in term:
            formatted.append(f'"{term}"')
        else:
            formatted.append(term)
    return " OR ".join(formatted)


def _active_domains(records: Iterable[Dict[str, Any]]) -> List[str]:
    domains: List[str] = []
    seen = set()
    for fields in active_detect_records(records):
        for domain in _split_terms(fields.get("Domains")):
            normalized = domain.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
            if normalized and normalized not in seen:
                seen.add(normalized)
                domains.append(normalized)
    return domains


def build_detect_query_plan(
    records: Iterable[Dict[str, Any]],
    anchor: Optional[date] = None,
    company_chunk_size: int = 5,
) -> List[PlannedQuery]:
    """Build compact, independently executable searches from the watchlist."""
    active = active_detect_records(records)
    domains = _active_domains(active)
    queries: List[PlannedQuery] = []
    sections = ["Finance", "Contact Center"]

    for section in sections:
        section_records = [row for row in active if cell_text(row.get("Section")) == section]
        topics = [row for row in section_records if cell_text(row.get("Type")).lower() == "topic"]
        topic_terms = _unique_terms(
            value
            for row in topics
            for value in (row.get("Keywords"), row.get("Aliases"))
        )
        if topic_terms:
            queries.append(PlannedQuery(
                key=f"{section.lower().replace(' ', '_')}_market",
                section=section,
                text=_query_text(topic_terms),
                domains=domains,
            ))

        companies = sorted(
            [row for row in section_records if cell_text(row.get("Type")).lower() == "company"],
            key=_priority,
        )
        for index in range(0, len(companies), company_chunk_size):
            chunk = companies[index : index + company_chunk_size]
            terms = _unique_terms(
                value
                for row in chunk
                for value in (row.get("Name"), row.get("Aliases"))
            )
            if terms:
                queries.append(PlannedQuery(
                    key=f"{section.lower().replace(' ', '_')}_companies_{index // company_chunk_size + 1}",
                    section=section,
                    text=_query_text(terms),
                    domains=domains,
                ))

    return queries


def build_query_from_detect_records(records: Iterable[Dict[str, Any]], max_terms: int = 60) -> Tuple[str, List[str]]:
    terms: List[str] = []
    domains: List[str] = []
    seen_terms = set()
    seen_domains = set()
    sorted_records = sorted(active_detect_records(records), key=_priority)
    for fields in sorted_records:
        source_type = cell_text(fields.get("Type")).strip().lower()
        text_values = [fields.get("Keywords"), fields.get("Aliases")]
        if source_type != "source_domain":
            text_values.append(fields.get("Name"))
        for value in text_values:
            for term in _split_terms(value):
                normalized = term.lower()
                if normalized not in seen_terms:
                    seen_terms.add(normalized)
                    terms.append(term)
        for domain in _split_terms(fields.get("Domains")):
            normalized_domain = domain.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
            if normalized_domain and normalized_domain not in seen_domains:
                seen_domains.add(normalized_domain)
                domains.append(normalized_domain)
    terms = terms[:max_terms]
    return _query_text(terms), domains


def fallback_detect_query(settings: AppSettings) -> Tuple[str, List[str]]:
    return build_query_from_detect_records(default_detect_source_records(settings))
