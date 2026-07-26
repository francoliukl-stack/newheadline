from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .dingtalk_ai_table import add_records, cell_text, create_sheet, ensure_fields, list_records, list_sheets, update_records
from .models import AppSettings, DingTalkAITableSettings
from .publish_dates import parse_date
from .storage import SettingsStore
from .url_identity import article_url_identity


DETECT_SOURCES_SHEET_NAME = "Detect Sources"
DETECT_SOURCE_FIELDS = [
    {"name": "Source ID", "type": "text"},
    {"name": "Type", "type": "text"},
    {"name": "Name", "type": "text"},
    {"name": "Section", "type": "text"},
    {"name": "Keywords", "type": "text"},
    {"name": "Aliases", "type": "text"},
    {"name": "Domains", "type": "text"},
    {"name": "Collection Mode", "type": "text"},
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
    ("company-alipay-plus", "company", "Alipay+", "Finance", "Alipay+", "Alipay Plus", "alipayplus.com", 1, "core business"),
    ("company-bettr", "company", "Bettr", "Finance", "Bettr", "Ant International SME finance", "ant-intl.com", 1, "core business"),
    ("company-ant-bank-hk", "company", "Ant Bank HK", "Finance", "Ant Bank HK", "Ant Bank Hong Kong", "ant-intl.com", 1, "core business"),
    ("company-alipayhk", "company", "AlipayHK", "Finance", "AlipayHK", "Alipay HK", "alipayhk.com", 1, "core business"),
    ("company-payoneer", "company", "Payoneer", "Finance", "Payoneer", "", "payoneer.com", 1, "cross-border benchmark"),
    ("company-checkout-com", "company", "Checkout.com", "Finance", "Checkout.com", "Checkout Payments", "checkout.com", 1, "payment benchmark"),
    ("company-dlocal", "company", "dLocal", "Finance", "dLocal", "", "dlocal.com", 1, "emerging-market payments"),
    ("company-hkma", "company", "HKMA", "Finance", "HKMA", "Hong Kong Monetary Authority", "hkma.gov.hk", 1, "regulatory source"),
    ("company-qris", "company", "QRIS", "Finance", "QRIS", "Indonesia QR standard", "bi.go.id", 2, "regional payment network"),
    ("company-duitnow", "company", "DuitNow", "Finance", "DuitNow", "Malaysia DuitNow QR", "duitnow.my", 2, "regional payment network"),
    ("company-unionpay", "company", "UnionPay International", "Finance", "UnionPay International", "", "unionpayintl.com", 2, "regional payment network"),
    ("company-promptpay", "company", "PromptPay", "Finance", "PromptPay", "Thailand PromptPay", "bot.or.th", 2, "regional payment network"),
    ("company-paynow", "company", "PayNow", "Finance", "PayNow", "Singapore PayNow", "abs.org.sg", 2, "regional payment network"),
    ("company-gcash", "company", "GCash", "Finance", "GCash", "G-Xchange", "gcash.com", 2, "regional wallet"),
    ("company-touch-n-go", "company", "Touch 'n Go eWallet", "Finance", "Touch 'n Go eWallet", "TNG eWallet, Touch n Go", "touchngo.com.my", 2, "regional wallet"),
    ("company-funding-societies", "company", "Funding Societies", "Finance", "Funding Societies", "Modalku", "fundingsocieties.com", 2, "SME finance benchmark"),
    ("company-seamoney", "company", "SeaMoney", "Finance", "SeaMoney", "Sea Money", "seamoney.com", 2, "SME finance benchmark"),
    ("company-worldpay", "company", "Worldpay", "Finance", "Worldpay", "", "worldpay.com", 2, "payment benchmark"),
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
    ("company-polyai", "company", "PolyAI", "Contact Center", "PolyAI", "Conversational AI", "poly.ai", 2, "voice AI benchmark"),
    ("company-retell-ai", "company", "Retell AI", "Contact Center", "Retell AI", "Retell", "retellai.com", 2, "voice AI benchmark"),
    ("company-verint", "company", "Verint", "Contact Center", "Verint", "", "verint.com", 3, "service automation benchmark"),
    ("company-calabrio", "company", "Calabrio", "Contact Center", "Calabrio", "", "calabrio.com", 3, "workforce engagement benchmark"),
]

TOPIC_SEEDS = [
    ("topic-payments", "topic", "Payments / Fintech", "Finance", "fintech, payments, banking", "cross-border payments, stablecoin settlement, programmable payments", "", 1, "category search"),
    ("topic-contact-center-ai", "topic", "Contact Center AI", "Contact Center", "Voice AI, Contact Center AI, Conversational Intelligence", "Audio LLM, agent assist, AIQA, AIQC", "", 1, "category search"),
    ("topic-agentic-payments", "topic", "Agentic Payments", "Finance", "agentic payments, payments for AI agents, AI agent payments", "autonomous payments, agentic commerce, programmable commerce", "", 1, "strategic theme"),
    ("topic-embedded-finance-b2b", "topic", "Embedded Finance / B2B Payments", "Finance", "embedded finance, B2B payment automation, commercial payments", "cross-border B2B payments, freight payments, logistics payments, treasury infrastructure", "", 1, "strategic theme"),
    ("topic-agentic-cx", "topic", "Agentic CX", "Contact Center", "enterprise AI agents, customer service agents, AI agent governance", "voice and chat agents, agent evaluation, human escalation", "", 1, "strategic theme"),
]

CORE_WATCH_SEEDS = [
    ("core-gbss-businesses", "core_watch", "GBSS Core Businesses", "Finance", "Alipay+, WorldFirst, Bettr, Antom, Ant Bank HK, AlipayHK", "Alipay Plus, World First, Ant Bank Hong Kong, Alipay HK", "alipayplus.com, worldfirst.com, ant-intl.com, antom.com, alipayhk.com", 1, "dedicated daily recall for six core business objects"),
]

SOURCE_SEEDS = [
    ("domain-thepaypers-com", "source_domain", "thepaypers.com", "News", "", "", "thepaypers.com", 1, "payments and fintech industry coverage"),
    ("domain-callcentrehelper-com", "source_domain", "callcentrehelper.com", "News", "", "", "callcentrehelper.com", 1, "contact center and CCaaS industry coverage"),
    ("domain-pymnts-com", "source_domain", "PYMNTS", "Finance", "", "", "pymnts.com", 2, "specialist payments publication; independently queried without trusted-source status"),
    ("domain-uctoday-com", "source_domain", "UC Today", "Contact Center", "", "", "uctoday.com", 2, "specialist enterprise communications publication; independently queried without trusted-source status"),
]

TRUSTED_SOURCE_SEEDS = [
    ("trusted-finance-reuters", "trusted_source", "Reuters", "Finance", "", "", "reuters.com", 1, "actively queried independent reporting"),
    ("trusted-finance-techcrunch", "trusted_source", "TechCrunch", "Finance", "", "", "techcrunch.com", 1, "actively queried technology publication"),
    ("trusted-finance-epi", "trusted_source", "Electronic Payments International", "Finance", "", "", "electronicpaymentsinternational.com", 1, "actively queried payments publication"),
    ("trusted-finance-thepaypers", "trusted_source", "The Paypers", "Finance", "", "", "thepaypers.com", 1, "actively queried payments publication"),
    ("trusted-finance-finextra", "trusted_source", "Finextra", "Finance", "", "", "finextra.com", 1, "actively queried finance publication"),
    ("trusted-finance-paymentsdive", "trusted_source", "Payments Dive", "Finance", "", "", "paymentsdive.com", 1, "actively queried payments publication"),
    ("trusted-finance-fintechfutures", "trusted_source", "FinTech Futures", "Finance", "", "", "fintechfutures.com", 1, "actively queried fintech publication"),
    ("trusted-finance-ledgerinsights", "trusted_source", "Ledger Insights", "Finance", "", "", "ledgerinsights.com", 1, "actively queried digital-money publication"),
    ("trusted-finance-americanbanker", "trusted_source", "American Banker", "Finance", "", "", "americanbanker.com", 1, "actively queried banking publication"),
    ("trusted-contact-cxtoday", "trusted_source", "CX Today", "Contact Center", "", "", "cxtoday.com", 1, "actively queried CX publication"),
    ("trusted-contact-nojitter", "trusted_source", "No Jitter", "Contact Center", "", "", "nojitter.com", 1, "actively queried enterprise communications publication"),
    ("trusted-contact-openai", "trusted_source", "OpenAI", "Contact Center", "OpenAI Presence", "enterprise AI agents, customer service agents", "openai.com", 1, "actively queried official AI product source"),
    ("trusted-contact-callcentrehelper", "trusted_source", "Call Centre Helper", "Contact Center", "", "", "callcentrehelper.com", 1, "actively queried contact-center publication"),
    ("trusted-contact-cmswire", "trusted_source", "CMSWire", "Contact Center", "", "", "cmswire.com", 1, "actively queried CX publication"),
    ("trusted-contact-ccpipeline", "trusted_source", "Contact Center Pipeline", "Contact Center", "", "", "contactcenterpipeline.com", 1, "actively queried contact-center publication"),
    ("trusted-contact-destinationcrm", "trusted_source", "Destination CRM", "Contact Center", "", "", "destinationcrm.com", 1, "actively queried CRM publication"),
]

COLLECTION_MODE_BY_TYPE = {
    "company": "entity_query",
    "core_watch": "entity_query",
    "topic": "topic_query",
    "source_domain": "rank_only",
    "trusted_source": "direct_site",
}

COLLECTION_MODE_OVERRIDES = {
    "domain-pymnts-com": "direct_site",
    "domain-uctoday-com": "direct_site",
}


@dataclass(frozen=True)
class PlannedQuery:
    key: str
    section: str
    text: str
    domains: List[str]
    lane: str = "broad_market"


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
    for source_id, source_type, name, section, keywords, aliases, domains, priority, notes in COMPANY_SEEDS + TOPIC_SEEDS + CORE_WATCH_SEEDS + SOURCE_SEEDS + TRUSTED_SOURCE_SEEDS:
        records.append({
            "Source ID": source_id,
            "Type": source_type,
            "Name": name,
            "Section": section,
            "Keywords": keywords,
            "Aliases": aliases,
            "Domains": domains,
            "Collection Mode": COLLECTION_MODE_OVERRIDES.get(
                source_id,
                COLLECTION_MODE_BY_TYPE.get(source_type, "rank_only"),
            ),
            "Priority": priority,
            "Enabled": "true",
            "Notes": notes,
            "Updated At": updated_at,
        })
    if settings:
        existing_domains = {
            domain
            for row in records
            if str(row.get("Type") or "").lower() == "source_domain"
            for domain in _split_terms(row.get("Domains"))
        }
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
                "Collection Mode": "rank_only",
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
    existing_by_id = {
        cell_text((record.get("fields") or {}).get("Source ID")): record
        for record in existing
        if cell_text((record.get("fields") or {}).get("Source ID"))
    }
    defaults = default_detect_source_records(settings)
    to_create = [
        row for row in defaults
        if str(row.get("Source ID") or "") not in existing_by_id
    ]
    to_update = []
    for row in defaults:
        source_id = str(row.get("Source ID") or "")
        current = existing_by_id.get(source_id)
        if not current:
            continue
        current_fields = current.get("fields") or {}
        patch = {}
        if not cell_text(current_fields.get("Collection Mode")).strip():
            patch["Collection Mode"] = row["Collection Mode"]
        if (
            source_id in COLLECTION_MODE_OVERRIDES
            and cell_text(current_fields.get("Section")).strip() in {"", "News"}
            and cell_text(current_fields.get("Section")).strip() != str(row.get("Section") or "")
        ):
            patch["Section"] = row["Section"]
        if patch:
            patch["Updated At"] = row["Updated At"]
            to_update.append({
                "id": current["id"],
                "fields": patch,
            })
    changed: List[str] = []
    for index in range(0, len(to_update), 100):
        batch = to_update[index : index + 100]
        result = update_records(settings.dingtalk, detect_table, batch)
        if result.status != "sent":
            raise RuntimeError(result.message)
        changed.extend(result.record_ids)
    for index in range(0, len(to_create), 100):
        batch = to_create[index : index + 100]
        result = add_records(settings.dingtalk, detect_table, batch)
        if result.status != "sent":
            raise RuntimeError(result.message)
        changed.extend(result.record_ids)
    return changed


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


def trusted_source_domains(records: Iterable[Dict[str, Any]]) -> set[str]:
    return {
        domain.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        for fields in active_detect_records(records)
        if cell_text(fields.get("Type")).lower() == "trusted_source"
        for domain in _split_terms(fields.get("Domains"))
        if domain
    }


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
        core_watch = [row for row in section_records if cell_text(row.get("Type")).lower() == "core_watch"]
        core_terms = _unique_terms(
            value
            for row in core_watch
            for value in (row.get("Keywords"), row.get("Aliases"))
        )
        if core_terms:
            queries.append(PlannedQuery(
                key=f"{section.lower().replace(' ', '_')}_core_watch",
                section=section,
                text=_query_text(core_terms),
                domains=domains,
                lane="core_entity",
            ))
        topics = [row for row in section_records if cell_text(row.get("Type")).lower() == "topic"]
        strategic_topics = [
            row for row in topics
            if cell_text(row.get("Source ID")).startswith("topic-agentic")
            or cell_text(row.get("Source ID")).startswith("topic-embedded")
            or cell_text(row.get("Notes")).lower() == "strategic theme"
        ]
        market_topics = [row for row in topics if row not in strategic_topics]
        topic_terms = _unique_terms(
            value
            for row in market_topics
            for value in (row.get("Keywords"), row.get("Aliases"))
        )
        if topic_terms:
            queries.append(PlannedQuery(
                key=f"{section.lower().replace(' ', '_')}_market",
                section=section,
                text=_query_text(topic_terms),
                domains=domains,
                lane="broad_market",
            ))
        for topic_index, topic in enumerate(strategic_topics, start=1):
            terms = _unique_terms((topic.get("Keywords"), topic.get("Aliases")))
            if terms:
                slug = cell_text(topic.get("Source ID")).removeprefix("topic-") or str(topic_index)
                queries.append(PlannedQuery(
                    key=f"{section.lower().replace(' ', '_')}_strategic_{slug}",
                    section=section,
                    text=_query_text(terms),
                    domains=domains,
                    lane="strategic_theme",
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
                    lane="core_entity",
                ))

        trusted_rows = [
            row for row in section_records
            if cell_text(row.get("Type")).lower() == "trusted_source"
        ]
        for index in range(0, len(trusted_rows), 3):
            trusted_chunk = trusted_rows[index : index + 3]
            trusted_domains = _unique_terms(row.get("Domains") for row in trusted_chunk)
            if not trusted_domains:
                continue
            site_query = " OR ".join(f"site:{domain}" for domain in trusted_domains)
            queries.append(PlannedQuery(
                key=(
                    f"{section.lower().replace(' ', '_')}_trusted_sources"
                    if len(trusted_rows) <= 3
                    else f"{section.lower().replace(' ', '_')}_trusted_sources_{index // 3 + 1}"
                ),
                section=section,
                text=site_query,
                domains=domains,
                lane="trusted_media",
            ))

        direct_site_rows = [
            row for row in section_records
            if cell_text(row.get("Type")).lower() == "source_domain"
            and cell_text(row.get("Collection Mode")).lower() == "direct_site"
        ]
        for index in range(0, len(direct_site_rows), 3):
            direct_chunk = direct_site_rows[index : index + 3]
            direct_domains = _unique_terms(row.get("Domains") for row in direct_chunk)
            if not direct_domains:
                continue
            queries.append(PlannedQuery(
                key=(
                    f"{section.lower().replace(' ', '_')}_specialist_sources"
                    if len(direct_site_rows) <= 3
                    else f"{section.lower().replace(' ', '_')}_specialist_sources_{index // 3 + 1}"
                ),
                section=section,
                text=" OR ".join(f"site:{domain}" for domain in direct_domains),
                domains=domains,
                lane="specialist_media",
            ))

    return queries


def candidate_domain(record: Dict[str, Any]) -> str:
    source = str(record.get("source") or "").lower().strip()
    if "." in source and " " not in source:
        return source.removeprefix("www.")
    from urllib.parse import urlparse
    return urlparse(str(record.get("url") or "")).netloc.lower().removeprefix("www.")


def is_trusted_source(record: Dict[str, Any], trusted_domains: set[str]) -> bool:
    domain = candidate_domain(record)
    return any(domain == trusted or domain.endswith("." + trusted) for trusted in trusted_domains)


def validate_candidate_lanes(
    records: Iterable[Dict[str, Any]],
    trusted_domains: set[str],
) -> List[Dict[str, Any]]:
    validated: List[Dict[str, Any]] = []
    for record in records:
        candidate = dict(record)
        if str(candidate.get("source_lane") or "").lower() == "trusted_media" and not is_trusted_source(candidate, trusted_domains):
            candidate["source_lane"] = "broad_market"
            candidate["Source Lane"] = "broad_market"
        validated.append(candidate)
    return validated


def dedupe_candidates(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: List[Dict[str, Any]] = []
    seen_urls = set()
    for record in records:
        identity = article_url_identity(record.get("url") or record.get("Link") or "")
        if not identity or identity in seen_urls:
            continue
        seen_urls.add(identity)
        unique.append(record)
    return unique


def _candidate_date_priority(record: Dict[str, Any], target_publish_date: date) -> Tuple[int, int]:
    parsed = parse_date(record.get("published_at") or record.get("Publish Date"))
    if not parsed:
        return (4, 0)
    observed = date.fromisoformat(parsed)
    offset = (observed - target_publish_date).days
    if offset == 0:
        return (0, 0)
    if offset == 1:
        return (1, 0)
    if offset < 0:
        return (2, abs(offset))
    return (3, offset)


def select_balanced_candidates(
    records: List[Dict[str, Any]],
    trusted_domains: set[str],
    max_per_group: int,
    total_limit: int,
    target_publish_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    editorial = [
        record for record in records
        if str(record.get("source_lane") or "").lower() == "editorial"
        or str(record.get("Discovery Type") or record.get("discovery_type") or "").lower() == "editorial_must_include"
    ]
    automatic = [record for record in records if record not in editorial]

    lane_names = {"core_entity", "strategic_theme", "trusted_media", "specialist_media", "broad_market"}
    has_explicit_lanes = any(str(record.get("source_lane") or "") in lane_names for record in automatic)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in automatic:
        grouped.setdefault(str(record.get("search_group") or "unknown"), []).append(record)

    def rank(record: Dict[str, Any]) -> Tuple[Any, ...]:
        trusted_rank = not is_trusted_source(record, trusted_domains)
        if target_publish_date is None:
            return (trusted_rank,)
        return (*_candidate_date_priority(record, target_publish_date), trusted_rank)

    def round_robin(candidates: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        candidate_ids = {id(record) for record in candidates}
        ranked_groups = [
            sorted([record for record in group if id(record) in candidate_ids], key=rank)[:max_per_group]
            for group in grouped.values()
        ]
        ranked_groups = [group for group in ranked_groups if group]
        chosen: List[Dict[str, Any]] = []
        for position in range(max_per_group):
            for group in ranked_groups:
                if position < len(group):
                    chosen.append(group[position])
                    if len(chosen) >= limit:
                        return chosen
        return chosen

    if not has_explicit_lanes:
        return editorial + round_robin(automatic, total_limit)

    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    for lane in ("core_entity", "strategic_theme", "trusted_media"):
        lane_pool = [record for record in automatic if str(record.get("source_lane") or "") == lane]
        for record in round_robin(lane_pool, min(6, len(lane_pool))):
            selected.append(record)
            selected_ids.add(id(record))
    specialist_pool = [
        record for record in automatic
        if str(record.get("source_lane") or "") == "specialist_media"
    ]
    for record in round_robin(specialist_pool, min(3, len(specialist_pool))):
        selected.append(record)
        selected_ids.add(id(record))

    remaining = [record for record in automatic if id(record) not in selected_ids]
    selected.extend(round_robin(remaining, max(total_limit - len(selected), 0)))
    return editorial + selected[:total_limit]


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
