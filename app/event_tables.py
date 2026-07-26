from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .dingtalk_ai_table import (
    add_records,
    create_sheet,
    ensure_fields,
    list_fields,
    list_records,
    list_sheets,
    update_records,
)
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


EVENT_CASES_SHEET_NAME = "Event Cases"
EVENT_ENTITIES_SHEET_NAME = "Event Entities"
EVENT_SOURCES_SHEET_NAME = "Event Sources"
EVENT_SCORES_SHEET_NAME = "Event Scores"
ENTITY_CATALOG_SHEET_NAME = "Entity Catalog"
ALERT_LOG_SHEET_NAME = "Alert Log"
API_USAGE_SHEET_NAME = "API Usage"

EVENT_CASE_FIELDS = [
    {"name": name, "type": field_type}
    for name, field_type in [
        ("Event ID", "text"), ("Event Title", "text"), ("Event Type", "text"),
        ("Business Lines", "text"), ("Primary Entity IDs", "text"), ("Strategic Candidate", "text"),
        ("First Seen At", "text"), ("Event Date", "text"), ("Status", "text"),
        ("Priority Candidate", "text"), ("Final Priority", "text"), ("P0 Approval Status", "text"),
        ("Confidence", "text"), ("Relevance Score", "text"), ("Summary", "text"),
        ("GBSS Impact Hypothesis", "text"), ("Limitations", "text"), ("Primary Source URL", "url"),
        ("Publish Date", "text"), ("Source Count", "text"), ("Accepted News Count", "text"),
        ("Reviewer", "text"), ("Reviewed At", "text"), ("Daily Report Sent At", "text"), ("Weekly Headlines Sent At", "text"),
        ("Weekly Intelligence Sent At", "text"), ("Event Version", "text"), ("Updated At", "text"),
        ("Merged Into Event ID", "text"),
    ]
]

EVENT_ENTITY_FIELDS = [
    {"name": name, "type": "text"}
    for name in ("Event Entity ID", "Event ID", "Entity ID", "Role", "Match Method", "Confidence", "Created At")
]

EVENT_SOURCE_FIELDS = [
    {"name": name, "type": "url" if name == "Source URL" else "text"}
    for name in (
        "Event Source ID", "Event ID", "News Record ID", "Source URL", "Source Domain", "Publish Date",
        "Source Grade", "Source Excerpt", "Is Primary Source", "Evidence Value", "Provider", "Duplicate Of", "Content Hash", "Created At",
    )
]

EVENT_SCORE_FIELDS = [
    {"name": name, "type": "text"}
    for name in (
        "Event Score ID", "Event ID", "Source Grade Score", "Entity Match Score", "Event Severity Score",
        "Business Line Fit Score", "Novelty Score", "Market Confirmation Score", "Overall Score", "Scoring Reason",
        "Scoring Version", "Model", "Prompt Version", "Scored At", "Human Override",
    )
]

ENTITY_CATALOG_FIELDS = [
    {"name": name, "type": "text"}
    for name in (
        "Entity ID", "Canonical Name", "Aliases", "Entity Type", "Business Lines", "Ticker", "Official URLs",
        "IR URLs", "Newsroom URLs", "Regulatory URLs", "Source Grade Default", "Watch Tier", "Critical Event Types",
        "Scan Cadence Hours", "Active", "Notes", "Updated At",
    )
]

ALERT_LOG_FIELDS = [
    {"name": name, "type": "text"}
    for name in (
        "Alert ID", "Event ID", "Alert Level", "Sent To", "Message", "Dedupe Key", "Sent At", "Ack Status",
        "Ack By", "Ack At", "Error",
    )
]

API_USAGE_FIELDS = [
    {"name": name, "type": "text"}
    for name in (
        "Call ID", "Run ID", "Event ID", "Provider", "Operation", "Model", "Pricing Version",
        "Estimated Input Tokens", "Estimated Output Tokens", "Estimated Cost USD", "Actual Input Tokens",
        "Actual Output Tokens", "Actual Cost USD", "Status", "Retry Count", "Skip Reason", "Started At", "Finished At",
    )
]

NEWS_LINEAGE_FIELDS = [
    {"name": "Entity Candidates", "type": "text"},
    {"name": "Event Case ID", "type": "text"},
    {"name": "Provider Score", "type": "text"},
    {"name": "Date Confidence", "type": "text"},
    {"name": "Original Language", "type": "text"},
    {"name": "Source Excerpt", "type": "text"},
    {"name": "LLM Processed At", "type": "text"},
    {"name": "Daily Report Sent At", "type": "text"},
    {"name": "AI Status", "type": "text"},
    {"name": "AI Confidence", "type": "text"},
    {"name": "AI Review Reason", "type": "text"},
    {"name": "AI Review Version", "type": "text"},
    {"name": "AI Review Fingerprint", "type": "text"},
    {"name": "AI Reviewed At", "type": "text"},
    {"name": "Review Decision Source", "type": "text"},
    {"name": "AI Applied Status", "type": "text"},
    {"name": "AI Applied At", "type": "text"},
    {"name": "AI Feedback Outcome", "type": "text"},
    {"name": "Human Override Status", "type": "text"},
    {"name": "AI Feedback At", "type": "text"},
    {"name": "AI Difference Category", "type": "text"},
    {"name": "AI Difference Summary", "type": "text"},
    {"name": "Source Lane", "type": "text"},
    {"name": "Search Group", "type": "text"},
    {"name": "Editorial Reason", "type": "text"},
    {"name": "Editorial Approved At", "type": "text"},
]
EVIDENCE_LINEAGE_FIELDS = [{"name": "Event ID", "type": "text"}, {"name": "Event Source IDs", "type": "text"}]
CLAIM_LINEAGE_FIELDS = [{"name": "Event ID", "type": "text"}, {"name": "Impact Level", "type": "text"}]
INSIGHT_LINEAGE_FIELDS = [{"name": "Event IDs", "type": "text"}, {"name": "Event Source IDs", "type": "text"}]


SHEET_DEFINITIONS: List[Tuple[str, str, List[Dict[str, str]]]] = [
    (EVENT_CASES_SHEET_NAME, "event_cases_sheet_id", EVENT_CASE_FIELDS),
    (EVENT_ENTITIES_SHEET_NAME, "event_entities_sheet_id", EVENT_ENTITY_FIELDS),
    (EVENT_SOURCES_SHEET_NAME, "event_sources_sheet_id", EVENT_SOURCE_FIELDS),
    (EVENT_SCORES_SHEET_NAME, "event_scores_sheet_id", EVENT_SCORE_FIELDS),
    (ENTITY_CATALOG_SHEET_NAME, "entity_catalog_sheet_id", ENTITY_CATALOG_FIELDS),
    (ALERT_LOG_SHEET_NAME, "alert_log_sheet_id", ALERT_LOG_FIELDS),
    (API_USAGE_SHEET_NAME, "api_usage_sheet_id", API_USAGE_FIELDS),
]


ENTITY_SEEDS = [
    ("alipay-plus", "Alipay+", "Alipay Plus", "product", "Alipay_Plus", "", "https://www.alipayplus.com", "critical"),
    ("worldfirst", "WorldFirst", "World First", "company", "WorldFirst", "", "https://www.worldfirst.com", "critical"),
    ("bettr", "Bettr", "", "company", "Bettr", "", "", "critical"),
    ("antom", "Antom", "Ant International merchant payments", "company", "Antom", "", "https://www.antom.com", "critical"),
    ("ant-international", "Ant International", "Ant Group International", "company", "Alipay_Plus,WorldFirst,Antom,Bettr,HK_Fintech", "", "https://www.ant-intl.com", "critical"),
    ("ant-bank-hk", "Ant Bank HK", "Ant Bank Hong Kong", "company", "HK_Fintech", "", "", "critical"),
    ("alipay-hk", "AlipayHK", "Alipay HK", "product", "HK_Fintech", "", "https://www.alipayhk.com", "critical"),
    ("wise", "Wise", "TransferWise", "company", "WorldFirst", "WISE.L", "https://wise.com", "high"),
    ("payoneer", "Payoneer", "", "company", "WorldFirst", "PAYO", "https://www.payoneer.com", "high"),
    ("airwallex", "Airwallex", "", "company", "WorldFirst,Antom", "", "https://www.airwallex.com", "high"),
    ("adyen", "Adyen", "", "company", "Antom", "ADYEN.AS", "https://www.adyen.com", "high"),
    ("stripe", "Stripe", "", "company", "Antom", "", "https://stripe.com", "high"),
    ("agentic-payments", "Agentic Payments", "agentic payment,payments for AI agents,AI agent payments,autonomous payments,agentic commerce,agentic B2B payment", "capability", "Antom,WorldFirst", "", "", "high"),
    ("embedded-finance", "Embedded Finance", "embedded payments,B2B payment infrastructure,financial infrastructure,freight payments,logistics payments", "capability", "Antom,WorldFirst", "", "", "high"),
    ("checkout-com", "Checkout.com", "Checkout", "company", "Antom", "", "https://www.checkout.com", "high"),
    ("dlocal", "dLocal", "Dlocal", "company", "Antom", "DLO", "https://www.dlocal.com", "high"),
    ("paypal", "PayPal", "", "company", "WorldFirst,Antom", "PYPL", "https://www.paypal.com", "high"),
    ("visa", "Visa", "", "company", "Alipay_Plus,Antom", "V", "https://www.visa.com", "high"),
    ("mastercard", "Mastercard", "MasterCard", "company", "Alipay_Plus,Antom", "MA", "https://www.mastercard.com", "high"),
    ("hkma", "HKMA", "Hong Kong Monetary Authority", "regulator", "HK_Fintech", "", "https://www.hkma.gov.hk", "critical"),
    ("qris", "QRIS", "Indonesia QR standard", "payment_method", "Alipay_Plus", "", "", "high"),
    ("duitnow", "DuitNow", "Malaysia DuitNow QR", "payment_method", "Alipay_Plus", "", "https://www.duitnow.my", "high"),
    ("genesys", "Genesys", "", "company", "GBSS_Service", "", "https://www.genesys.com", "high"),
    ("nice", "NICE", "NICE CXone", "company", "GBSS_Service", "NICE", "https://www.nice.com", "high"),
    ("salesforce", "Salesforce", "Agentforce", "company", "GBSS_Service", "CRM", "https://www.salesforce.com", "high"),
    ("openai", "OpenAI", "OpenAI Presence", "company", "GBSS_Service", "", "https://openai.com", "high"),
    ("zendesk", "Zendesk", "", "company", "GBSS_Service", "", "https://www.zendesk.com", "standard"),
    ("twilio", "Twilio", "", "company", "GBSS_Service", "TWLO", "https://www.twilio.com", "standard"),
    ("unionpay-international", "UnionPay International", "", "company", "Alipay_Plus", "", "https://www.unionpayintl.com", "high"),
    ("india-upi", "Unified Payments Interface", "UPI,India UPI", "payment_method", "Alipay_Plus", "", "https://www.npci.org.in/what-we-do/upi/product-overview", "high"),
    ("wechat-pay-global", "WeChat Pay Global", "Weixin Pay Global", "product", "Alipay_Plus", "", "https://pay.weixin.qq.com", "high"),
    ("promptpay", "PromptPay", "Thailand PromptPay", "payment_method", "Alipay_Plus", "", "", "high"),
    ("grabpay", "GrabPay", "Grab Pay", "product", "Alipay_Plus", "", "https://www.grab.com", "high"),
    ("paynow", "PayNow", "Singapore PayNow", "payment_method", "Alipay_Plus", "", "", "high"),
    ("gcash", "GCash", "G-Xchange", "product", "Alipay_Plus", "", "https://www.gcash.com", "high"),
    ("touch-n-go", "Touch 'n Go eWallet", "TNG eWallet,Touch n Go", "product", "Alipay_Plus", "", "https://www.touchngo.com.my", "high"),
    ("pingpong", "PingPong", "PingPong Payments", "company", "WorldFirst", "", "https://www.pingpongx.com", "standard"),
    ("lianlian", "LianLian Global", "LianLian", "company", "WorldFirst", "", "https://www.lianlianglobal.com", "standard"),
    ("revolut-business", "Revolut Business", "Revolut", "product", "WorldFirst", "", "https://www.revolut.com/business", "high"),
    ("funding-societies", "Funding Societies", "Modalku", "company", "Bettr", "", "https://fundingsocieties.com", "high"),
    ("aspire", "Aspire", "Aspire Financial Technologies", "company", "Bettr", "", "https://aspireapp.com", "high"),
    ("grab-finance", "Grab Finance", "Grab Financial Group", "company", "Bettr", "", "https://www.grab.com", "high"),
    ("validus", "Validus", "Validus Capital", "company", "Bettr", "", "https://validus.sg", "standard"),
    ("seamoney", "SeaMoney", "Sea Money", "company", "Bettr", "SE", "https://www.seamoney.com", "high"),
    ("worldpay", "Worldpay", "", "company", "Antom", "", "https://www.worldpay.com", "high"),
    ("fiserv", "Fiserv", "", "company", "Antom", "FISV", "https://www.fiserv.com", "high"),
    ("nuvei", "Nuvei", "", "company", "Antom", "", "https://www.nuvei.com", "high"),
    ("rapyd", "Rapyd", "", "company", "Antom", "", "https://www.rapyd.net", "standard"),
    ("2c2p", "2C2P", "", "company", "Antom", "", "https://www.2c2p.com", "standard"),
    ("za-bank", "ZA Bank", "", "company", "HK_Fintech", "", "https://bank.za.group", "high"),
    ("mox-bank", "Mox Bank", "Mox", "company", "HK_Fintech", "", "https://mox.com", "high"),
    ("welab-bank", "WeLab Bank", "", "company", "HK_Fintech", "", "https://www.welab.bank", "high"),
    ("octopus", "Octopus", "Octopus Cards", "product", "HK_Fintech", "", "https://www.octopus.com.hk", "high"),
    ("hsbc-payme", "HSBC PayMe", "PayMe", "product", "HK_Fintech", "", "https://payme.hsbc.com.hk", "high"),
    ("wechat-pay-hk", "WeChat Pay HK", "WeChat Pay Hong Kong", "product", "HK_Fintech", "", "https://pay.wechat.com.hk", "high"),
    ("five9", "Five9", "", "company", "GBSS_Service", "FIVN", "https://www.five9.com", "standard"),
    ("talkdesk", "Talkdesk", "", "company", "GBSS_Service", "", "https://www.talkdesk.com", "standard"),
    ("verint", "Verint", "", "company", "GBSS_Service", "VRNT", "https://www.verint.com", "standard"),
    ("calabrio", "Calabrio", "", "company", "GBSS_Service", "", "https://www.calabrio.com", "standard"),
    ("polyai", "PolyAI", "", "company", "GBSS_Service", "", "https://poly.ai", "high"),
    ("retell-ai", "Retell AI", "Retell", "company", "GBSS_Service", "", "https://www.retellai.com", "high"),
    ("xai", "xAI", "Grok,Grok Voice AI", "company", "GBSS_Service", "", "https://x.ai", "high"),
    ("swift", "Swift", "SWIFT,Society for Worldwide Interbank Financial Telecommunication", "payment_network", "Alipay_Plus,WorldFirst,Antom", "", "https://www.swift.com", "high"),
    ("bis", "Bank for International Settlements", "BIS", "regulator", "Alipay_Plus,WorldFirst,Antom,HK_Fintech", "", "https://www.bis.org", "high"),
]


ENTITY_SOURCE_SEEDS = {
    "alipay-plus": {"Newsroom URLs": "https://www.alipayplus.com/news/"},
    "worldfirst": {"Newsroom URLs": "https://www.ant-intl.com/en/news/"},
    "bettr": {"Newsroom URLs": "https://www.ant-intl.com/en/news/"},
    "antom": {"Newsroom URLs": "https://www.antom.com/news/"},
    "ant-international": {"Newsroom URLs": "https://www.ant-intl.com/en/news/"},
    "ant-bank-hk": {"Newsroom URLs": "https://www.ant-intl.com/en/news/"},
    "alipay-hk": {"Newsroom URLs": "https://www.alipayplus.com/news/"},
    "wise": {"IR URLs": "https://owners.wise.com/rss/news-releases.xml"},
    "payoneer": {"IR URLs": "https://investor.payoneer.com/rss/news-releases.xml"},
    "adyen": {"IR URLs": "https://investors.adyen.com/"},
    "stripe": {"Newsroom URLs": "https://stripe.com/newsroom"},
    "openai": {"Newsroom URLs": "https://openai.com/news/", "Scan Cadence Hours": "4"},
    "airwallex": {"Newsroom URLs": "https://www.airwallex.com/global/newsroom"},
    "checkout-com": {"Newsroom URLs": "https://www.checkout.com/newsroom"},
    "dlocal": {"Newsroom URLs": "https://www.dlocal.com/press-releases/"},
    "paypal": {"Newsroom URLs": "https://newsroom.paypal-corp.com/"},
    "visa": {"IR URLs": "https://investor.visa.com/news/default.aspx"},
    "mastercard": {"IR URLs": "https://investor.mastercard.com/investor-news/default.aspx"},
    "fiserv": {"IR URLs": "https://investors.fiserv.com/"},
    "hkma": {"Regulatory URLs": "https://www.hkma.gov.hk/eng/news-and-media/press-releases"},
    "genesys": {"Newsroom URLs": "https://www.genesys.com/company/newsroom/announcements"},
    "nice": {"Newsroom URLs": "https://www.nice.com/press-releases"},
    "xai": {"Newsroom URLs": "https://x.ai/news"},
    "india-upi": {"Regulatory URLs": "https://www.npci.org.in/media/press-release", "Scan Cadence Hours": "24"},
    "qris": {"Regulatory URLs": "https://www.bi.go.id/en/publikasi/ruang-media/news-release/", "Scan Cadence Hours": "24"},
    "duitnow": {"Newsroom URLs": "https://paynet.my/press-release/", "Scan Cadence Hours": "24"},
    "salesforce": {"Newsroom URLs": "https://www.salesforce.com/news/", "Scan Cadence Hours": "24"},
    "polyai": {"Newsroom URLs": "https://poly.ai/resources/", "Scan Cadence Hours": "24"},
    "retell-ai": {"Newsroom URLs": "https://www.retellai.com/blog", "Scan Cadence Hours": "24"},
    "swift": {"Newsroom URLs": "https://www.swift.com/news-events/press-releases", "Scan Cadence Hours": "24"},
    "bis": {"Regulatory URLs": "https://www.bis.org/press/index.htm", "Scan Cadence Hours": "24"},
}

ENTITY_SOURCE_REPLACEMENTS = {
    ("wise", "IR URLs"): {"https://owners.wise.com/"},
    ("payoneer", "IR URLs"): {"https://investor.payoneer.com/news-events/news-releases"},
    **{
        (entity_id, "Scan Cadence Hours"): {"4"}
        for entity_id in (
            "india-upi", "qris", "duitnow", "salesforce", "polyai",
            "retell-ai", "swift", "bis",
        )
    },
}

ENTITY_VALUE_REPLACEMENTS = {
    ("nuvei", "Ticker", "NVEI"): "",
    ("fiserv", "Ticker", "FI"): "FISV",
    ("unionpay-international", "Aliases", "UPI"): "",
}


@dataclass
class EventIntelligenceTables:
    event_cases: DingTalkAITableSettings
    event_entities: DingTalkAITableSettings
    event_sources: DingTalkAITableSettings
    event_scores: DingTalkAITableSettings
    entity_catalog: DingTalkAITableSettings
    alert_log: DingTalkAITableSettings
    api_usage: DingTalkAITableSettings


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def _ensure_sheet(settings: AppSettings, store: SettingsStore, name: str, settings_field: str, fields: List[Dict[str, str]], sheets_payload: Dict[str, Any]) -> DingTalkAITableSettings:
    sheet_id = str(getattr(settings.dingtalk_ai_table, settings_field) or "").strip() or _sheet_id_by_name(sheets_payload, name)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, name, fields)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or f"failed to create {name}"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    table = _table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, table, fields)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or f"failed to ensure {name} fields"))
    setattr(settings.dingtalk_ai_table, settings_field, sheet_id)
    return table


def ensure_event_intelligence_sheets(settings: AppSettings, store: SettingsStore) -> EventIntelligenceTables:
    sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
    if not sheets.get("ok"):
        raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk sheets"))
    payload = sheets.get("payload") or {}
    tables = {}
    for name, settings_field, fields in SHEET_DEFINITIONS:
        tables[settings_field] = _ensure_sheet(settings, store, name, settings_field, fields, payload)
    store.save(settings)
    return EventIntelligenceTables(
        event_cases=tables["event_cases_sheet_id"], event_entities=tables["event_entities_sheet_id"],
        event_sources=tables["event_sources_sheet_id"], event_scores=tables["event_scores_sheet_id"],
        entity_catalog=tables["entity_catalog_sheet_id"], alert_log=tables["alert_log_sheet_id"],
        api_usage=tables["api_usage_sheet_id"],
    )


def schema_plan(settings: AppSettings) -> List[Dict[str, Any]]:
    sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
    if not sheets.get("ok"):
        raise RuntimeError(str(sheets.get("message") or "failed to list DingTalk sheets"))
    payload = sheets.get("payload") or {}
    plan: List[Dict[str, Any]] = []
    for name, settings_field, fields in SHEET_DEFINITIONS:
        sheet_id = str(getattr(settings.dingtalk_ai_table, settings_field) or "").strip() or _sheet_id_by_name(payload, name)
        existing_names = set()
        if sheet_id:
            result = list_fields(settings.dingtalk, _table(settings, sheet_id))
            if result.get("ok"):
                existing_names = {str(item.get("name") or "") for item in (result.get("payload") or {}).get("value") or []}
        plan.append({"sheet": name, "sheet_id": sheet_id, "action": "ensure" if sheet_id else "create", "missing_fields": [field["name"] for field in fields if field["name"] not in existing_names]})
    return plan


def ensure_lineage_fields(settings: AppSettings, tables: EventIntelligenceTables) -> None:
    targets = [
        (settings.dingtalk_ai_table, NEWS_LINEAGE_FIELDS),
        (_table(settings, settings.dingtalk_ai_table.evidence_bank_sheet_id), EVIDENCE_LINEAGE_FIELDS),
        (_table(settings, settings.dingtalk_ai_table.claim_ledger_sheet_id), CLAIM_LINEAGE_FIELDS),
        (_table(settings, settings.dingtalk_ai_table.insights_sheet_id), INSIGHT_LINEAGE_FIELDS),
    ]
    for table, fields in targets:
        if not table.sheet_id:
            continue
        result = ensure_fields(settings.dingtalk, table, fields)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("message") or "failed to ensure lineage fields"))


def seed_entity_catalog(settings: AppSettings, table: DingTalkAITableSettings) -> int:
    existing = {str((record.get("fields") or {}).get("Entity ID") or ""): record for record in list_records(settings.dingtalk, table)}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, updates = [], []
    for entity_id, name, aliases, entity_type, lines, ticker, official_url, tier in ENTITY_SEEDS:
        sources = ENTITY_SOURCE_SEEDS.get(entity_id) or {}
        if entity_id in existing:
            current = existing[entity_id].get("fields") or {}
            fields = {
                key: value
                for key, value in sources.items()
                if value and (
                    not str(current.get(key) or "").strip()
                    or str(current.get(key) or "").strip() in ENTITY_SOURCE_REPLACEMENTS.get((entity_id, key), set())
                )
            }
            for (replacement_entity, field_name, old_value), new_value in ENTITY_VALUE_REPLACEMENTS.items():
                if entity_id == replacement_entity and str(current.get(field_name) or "").strip() == old_value:
                    fields[field_name] = new_value
            if fields:
                fields["Updated At"] = now
                updates.append({"id": existing[entity_id]["id"], "fields": fields})
            continue
        rows.append({
            "Entity ID": entity_id, "Canonical Name": name, "Aliases": aliases, "Entity Type": entity_type,
            "Business Lines": lines, "Ticker": ticker, "Official URLs": official_url, "IR URLs": sources.get("IR URLs", ""),
            "Newsroom URLs": sources.get("Newsroom URLs", ""), "Regulatory URLs": sources.get("Regulatory URLs", ""), "Source Grade Default": "T1" if official_url else "T2",
            "Watch Tier": tier, "Critical Event Types": "Earnings,Product_Launch,Strategic_MA,Regulatory,Ops_Incident",
            "Scan Cadence Hours": sources.get("Scan Cadence Hours", "4" if tier in {"critical", "high"} else "24"),
            "Active": "yes", "Notes": "v3.1 seed", "Updated At": now,
        })
    changed = 0
    if updates:
        result = update_records(settings.dingtalk, table, updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
        changed += len(result.record_ids)
    if rows:
        result = add_records(settings.dingtalk, table, rows)
        if result.status != "sent":
            raise RuntimeError(result.message)
        changed += len(result.record_ids)
    return changed
