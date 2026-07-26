from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .dingtalk_ai_table import add_records, cell_text, create_sheet, ensure_fields, list_records, list_sheets, update_records
from .gbss_report import infer_business_relevance, infer_capabilities, infer_strategic_theme, record_publish_date, record_title, source_url
from .models import AppSettings, DingTalkAITableSettings
from .storage import SettingsStore


RESEARCH_QUEUE_SHEET_NAME = "Research Queue"
EVIDENCE_BANK_SHEET_NAME = "Evidence Bank"
CLAIM_LEDGER_SHEET_NAME = "Claim Ledger"
RESEARCH_RESULTS_SHEET_NAME = "Research Results"

RESEARCH_QUEUE_FIELDS = [
    {"name": "Research ID", "type": "text"},
    {"name": "Topic Source ID", "type": "text"},
    {"name": "Publish Date", "type": "text"},
    {"name": "Topic", "type": "text"},
    {"name": "Primary Question", "type": "text"},
    {"name": "Sub Questions", "type": "text"},
    {"name": "Hypothesis", "type": "text"},
    {"name": "Decision Context", "type": "text"},
    {"name": "Entity Map", "type": "text"},
    {"name": "Evidence Plan", "type": "text"},
    {"name": "Disconfirming Evidence", "type": "text"},
    {"name": "GBSS Scope", "type": "text"},
    {"name": "Research Status", "type": "text"},
    {"name": "Approval Status", "type": "text"},
    {"name": "Approval Plan", "type": "text"},
    {"name": "Approval Requested At", "type": "text"},
    {"name": "Approved At", "type": "text"},
    {"name": "OpenAI Response ID", "type": "text"},
    {"name": "Deep Insight Phrases", "type": "text"},
    {"name": "Deep Research Status", "type": "text"},
    {"name": "Research Result Record ID", "type": "text"},
    {"name": "Research Document URL", "type": "text"},
    {"name": "Evidence Freeze At", "type": "text"},
    {"name": "Owner", "type": "text"},
    {"name": "Updated At", "type": "text"},
]

EVIDENCE_BANK_FIELDS = [
    {"name": "Evidence ID", "type": "text"},
    {"name": "Research ID", "type": "text"},
    {"name": "Source Record ID", "type": "text"},
    {"name": "Source URL", "type": "url"},
    {"name": "Source Title", "type": "text"},
    {"name": "Publisher", "type": "text"},
    {"name": "Published Date", "type": "text"},
    {"name": "Source Tier", "type": "text"},
    {"name": "Source Type", "type": "text"},
    {"name": "Extracted Fact", "type": "text"},
    {"name": "Metric", "type": "text"},
    {"name": "Scope / Boundary", "type": "text"},
    {"name": "Business Relevance", "type": "text"},
    {"name": "Impacted Capability", "type": "text"},
    {"name": "Supports / Challenges", "type": "text"},
    {"name": "Confidence", "type": "text"},
    {"name": "Reviewer Status", "type": "text"},
    {"name": "Reviewer Notes", "type": "text"},
    {"name": "Captured At", "type": "text"},
]

CLAIM_LEDGER_FIELDS = [
    {"name": "Claim ID", "type": "text"},
    {"name": "Research ID", "type": "text"},
    {"name": "Claim Text", "type": "text"},
    {"name": "Claim Type", "type": "text"},
    {"name": "Evidence IDs", "type": "text"},
    {"name": "Counter-evidence / Boundary", "type": "text"},
    {"name": "GBSS Relevance", "type": "text"},
    {"name": "Strategic Theme", "type": "text"},
    {"name": "Confidence", "type": "text"},
    {"name": "Report Placement", "type": "text"},
    {"name": "Reviewer Status", "type": "text"},
    {"name": "Reviewer Notes", "type": "text"},
    {"name": "Updated At", "type": "text"},
]

RESEARCH_RESULT_FIELDS = [
    {"name": "Research Result ID", "type": "text"},
    {"name": "Research ID", "type": "text"},
    {"name": "Provider", "type": "text"},
    {"name": "Model", "type": "text"},
    {"name": "Response ID", "type": "text"},
    {"name": "Status", "type": "text"},
    {"name": "Generated At", "type": "text"},
    {"name": "Topic", "type": "text"},
    {"name": "Research Question", "type": "text"},
    {"name": "Source Record IDs", "type": "text"},
    {"name": "Evidence IDs", "type": "text"},
    {"name": "Research Content", "type": "text"},
    {"name": "Deep Insight Phrases", "type": "text"},
    {"name": "Research Document URL", "type": "text"},
    {"name": "Research Document Node ID", "type": "text"},
    {"name": "Research Document Key", "type": "text"},
    {"name": "Local Artifact Path", "type": "text"},
    {"name": "Error", "type": "text"},
]

T1_DOMAINS = {
    "antom.com", "ant-intl.com", "alipayplus.com", "alipayhk.com", "antbank.hk", "antgroup.com", "worldfirst.com", "stripe.com", "visa.com", "mastercard.com", "paypal.com",
    "wise.com", "airwallex.com", "payoneer.com", "nuvei.com", "revolut.com", "xtransfer.com",
    "openai.com", "aws.amazon.com", "salesforce.com", "microsoft.com", "deepgram.com", "genesys.com",
    "nice.com", "five9.com", "talkdesk.com", "zendesk.com", "intercom.com", "twilio.com",
    "sec.gov", "fca.org.uk", "europa.eu", "gov.uk", "hkma.gov.hk", "hkexnews.hk", "nasdaq.com",
}
T2_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "techcrunch.com", "theinformation.com",
    "finextra.com", "pymnts.com", "paymentsdive.com", "americanbanker.com", "ledgerinsights.com",
    "nojitter.com", "cxtoday.com", "contactcenterpipeline.com",
}


@dataclass
class ResearchTables:
    queue: DingTalkAITableSettings
    evidence: DingTalkAITableSettings
    claims: DingTalkAITableSettings
    results: DingTalkAITableSettings


def _sheet_id_by_name(payload: Dict[str, Any], name: str) -> str:
    for item in payload.get("value") or []:
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            return str(item["id"])
    return ""


def _table(settings: AppSettings, sheet_id: str) -> DingTalkAITableSettings:
    return settings.dingtalk_ai_table.model_copy(update={"sheet_id": sheet_id})


def _ensure_named_sheet(
    settings: AppSettings,
    store: Optional[SettingsStore],
    name: str,
    fields: List[Dict[str, str]],
    settings_field: str,
) -> DingTalkAITableSettings:
    sheet_id = str(getattr(settings.dingtalk_ai_table, settings_field) or "").strip()
    if not sheet_id:
        sheets = list_sheets(settings.dingtalk, settings.dingtalk_ai_table)
        if not sheets.get("ok"):
            raise RuntimeError(str(sheets.get("message") or f"failed to list sheets for {name}"))
        sheet_id = _sheet_id_by_name(sheets.get("payload") or {}, name)
    if not sheet_id:
        created = create_sheet(settings.dingtalk, settings.dingtalk_ai_table, name, fields)
        if not created.get("ok"):
            raise RuntimeError(str(created.get("message") or f"failed to create {name}"))
        sheet_id = str((created.get("payload") or {}).get("id") or "")
    if not sheet_id:
        raise RuntimeError(f"{name} sheet id is missing")
    table = _table(settings, sheet_id)
    ensured = ensure_fields(settings.dingtalk, table, fields)
    if not ensured.get("ok"):
        raise RuntimeError(str(ensured.get("message") or f"failed to ensure {name} fields"))
    if getattr(settings.dingtalk_ai_table, settings_field) != sheet_id:
        setattr(settings.dingtalk_ai_table, settings_field, sheet_id)
        if store:
            store.save(settings)
    return table


def ensure_research_production_sheets(settings: AppSettings, store: Optional[SettingsStore] = None) -> ResearchTables:
    return ResearchTables(
        queue=_ensure_named_sheet(settings, store, RESEARCH_QUEUE_SHEET_NAME, RESEARCH_QUEUE_FIELDS, "research_queue_sheet_id"),
        evidence=_ensure_named_sheet(settings, store, EVIDENCE_BANK_SHEET_NAME, EVIDENCE_BANK_FIELDS, "evidence_bank_sheet_id"),
        claims=_ensure_named_sheet(settings, store, CLAIM_LEDGER_SHEET_NAME, CLAIM_LEDGER_FIELDS, "claim_ledger_sheet_id"),
        results=_ensure_named_sheet(settings, store, RESEARCH_RESULTS_SHEET_NAME, RESEARCH_RESULT_FIELDS, "research_results_sheet_id"),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _field(fields: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = cell_text(fields.get(name)).strip()
        if value:
            return value
    return ""


def source_tier(url: str, publisher: str = "") -> Tuple[str, str]:
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    candidate = domain or publisher.lower().removeprefix("www.")
    if candidate in T1_DOMAINS or any(candidate.endswith(f".{item}") for item in T1_DOMAINS):
        return "T1", "official / primary"
    if candidate in T2_DOMAINS or any(candidate.endswith(f".{item}") for item in T2_DOMAINS):
        return "T2", "independent reporting"
    return "T3", "discovery / unverified secondary"


def stable_id(prefix: str, *parts: str) -> str:
    value = "|".join(str(part or "") for part in parts)
    return f"{prefix}-{sha1(value.encode('utf-8')).hexdigest()[:16]}"


def build_research_queue_fields(topic_record: Dict[str, Any], research_id: str = "") -> Dict[str, str]:
    fields = topic_record.get("fields") or {}
    topic_source_id = _field(fields, "Topic ID") or str(topic_record.get("id") or "")
    topic = _field(fields, "Topic") or "GBSS Weekly Research"
    question = _field(fields, "Research Question") or "What changed, why does it matter, and what should GBSS monitor?"
    scope = _field(fields, "Scope") or "Merchant Service / ePOS; Antom; WorldFirst; General GBSS Ops"
    signals = _field(fields, "Source Signals")
    publish_date = _field(fields, "Publish Date")
    return {
        "Research ID": research_id or stable_id("research", topic_source_id, publish_date, topic),
        "Topic Source ID": topic_source_id,
        "Publish Date": publish_date,
        "Topic": topic,
        "Primary Question": question,
        "Sub Questions": "1) What changed and which facts are confirmed?\n2) What market or operating mechanism changes?\n3) What is the specific GBSS relevance and boundary?",
        "Hypothesis": "",
        "Decision Context": _field(fields, "Why It Matters"),
        "Entity Map": _field(fields, "Scope"),
        "Evidence Plan": f"Prioritize T1 primary sources; obtain independent T2 corroboration for material claims. Target signals: {signals}",
        "Disconfirming Evidence": "Search for limited deployments, missing metrics, competing alternatives, regulatory constraints and counter-cases.",
        "GBSS Scope": scope,
        "Research Status": "Locked" if _field(fields, "Status").lower() == "locked" else "Planned",
        "Approval Status": "Pending Approval",
        "Approval Plan": "",
        "Approval Requested At": "",
        "Approved At": "",
        "OpenAI Response ID": "",
        "Deep Insight Phrases": "",
        "Deep Research Status": "Not requested",
        "Research Result Record ID": "",
        "Research Document URL": "",
        "Evidence Freeze At": "",
        "Owner": _field(fields, "Owner") or "GBSS Strategy / Ops",
        "Updated At": _now(),
    }


def _non_empty(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop blank values so DingTalk typed fields (e.g. URL cells) are omitted,
    not sent as an empty string that the API rejects on insert."""
    return {name: value for name, value in fields.items() if value != ""}


def upsert_research_queue(settings: AppSettings, table: DingTalkAITableSettings, topic_record: Dict[str, Any]) -> Dict[str, Any]:
    desired = build_research_queue_fields(topic_record)
    existing = list_records(settings.dingtalk, table)
    for record in existing:
        fields = record.get("fields") or {}
        if _field(fields, "Research ID") == desired["Research ID"]:
            current_status = _field(fields, "Research Status")
            if current_status:
                desired["Research Status"] = current_status
            for name in ("Approval Status", "Approval Plan", "Approval Requested At", "Approved At", "OpenAI Response ID", "Deep Insight Phrases", "Deep Research Status", "Research Result Record ID", "Research Document URL"):
                if name in fields:
                    desired[name] = fields[name]
            result = update_records(settings.dingtalk, table, [{"id": record["id"], "fields": _non_empty(desired)}])
            if result.status != "sent":
                raise RuntimeError(result.message)
            return {"id": record["id"], "fields": desired}
    created = add_records(settings.dingtalk, table, [_non_empty(desired)])
    if created.status != "sent" or not created.record_ids:
        raise RuntimeError(created.message)
    return {"id": created.record_ids[0], "fields": desired}


def extract_research_document_url(value: Any) -> str:
    """Return the URL from either a plain text cell or DingTalk link cell."""
    if isinstance(value, dict):
        return str(value.get("link") or value.get("url") or value.get("text") or "").strip()
    return str(value or "").strip()


def select_manual_research_queue(
    records: Iterable[Dict[str, Any]],
    period: str,
    *,
    now: Optional[datetime] = None,
    fallback_days: int = 3,
) -> Dict[str, Any]:
    manual = [
        row for row in records
        if _field(row.get("fields") or {}, "Approval Status") == "Manual ChatGPT workflow"
    ]
    matching = [row for row in manual if _field(row.get("fields") or {}, "Publish Date") == period]
    matching.sort(key=lambda row: _field(row.get("fields") or {}, "Updated At"), reverse=True)
    if matching:
        return matching[0]
    if now is None:
        return {}

    # The Friday plan freezes a seven-day evidence window, while Sunday's
    # delivery window ends two days later. Reuse only a freshly requested plan
    # so an old report can never be attached silently.
    recent = []
    for row in manual:
        requested = _field(row.get("fields") or {}, "Approval Requested At")
        try:
            requested_at = datetime.fromisoformat(requested)
            age_seconds = (now - requested_at).total_seconds()
        except (TypeError, ValueError):
            continue
        if 0 <= age_seconds <= fallback_days * 86400:
            recent.append(row)
    recent.sort(
        key=lambda row: _field(row.get("fields") or {}, "Approval Requested At"),
        reverse=True,
    )
    return recent[0] if recent else {}


def evidence_fields_from_news(research_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    fields = record.get("fields") or {}
    url = source_url(fields)
    publisher = _field(fields, "Source", "Source Domain") or urlparse(url).netloc.lower().removeprefix("www.")
    tier, source_type = source_tier(url, publisher)
    title = record_title(record)
    record_id = str(record.get("id") or "")
    return {
        "Evidence ID": stable_id("evidence", research_id, record_id, url, title),
        "Research ID": research_id,
        "Event ID": _field(fields, "Event ID"),
        "Event Source IDs": _field(fields, "Event Source IDs"),
        "Source Record ID": record_id,
        "Source URL": {"text": publisher or url, "link": url} if url else "",
        "Source Title": title,
        "Publisher": publisher,
        "Published Date": record_publish_date(record),
        "Source Tier": tier,
        "Source Type": source_type,
        "Extracted Fact": title,
        "Metric": "",
        "Scope / Boundary": "Candidate evidence: verify source text, scope, metric definition and counter-case before approving a material claim.",
        "Business Relevance": " / ".join(infer_business_relevance(record)),
        "Impacted Capability": " / ".join(infer_capabilities(record)),
        "Supports / Challenges": "Candidate support",
        "Confidence": "Medium" if tier in {"T1", "T2"} else "Low",
        "Reviewer Status": "Pending",
        "Reviewer Notes": "",
        "Captured At": _now(),
    }


def upsert_evidence_from_news(
    settings: AppSettings,
    table: DingTalkAITableSettings,
    research_id: str,
    records: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    desired: List[Dict[str, Any]] = [evidence_fields_from_news(research_id, record) for record in records]
    existing = list_records(settings.dingtalk, table)
    by_id = {_field(record.get("fields") or {}, "Evidence ID"): record for record in existing}
    creates: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    for fields in desired:
        existing_record = by_id.get(fields["Evidence ID"])
        if existing_record:
            previous = existing_record.get("fields") or {}
            for name in ("Reviewer Status", "Reviewer Notes", "Supports / Challenges", "Metric", "Scope / Boundary", "Confidence"):
                prior = _field(previous, name)
                if prior:
                    fields[name] = prior
            updates.append({"id": existing_record["id"], "fields": fields})
        else:
            creates.append(fields)
    if updates:
        result = update_records(settings.dingtalk, table, updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    if creates:
        result = add_records(settings.dingtalk, table, creates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    return desired


def claim_fields_from_evidence(research_id: str, evidence: Dict[str, Any]) -> Dict[str, str]:
    fields = evidence.get("fields") or evidence
    evidence_id = _field(fields, "Evidence ID")
    fact = _field(fields, "Extracted Fact", "Source Title")
    tier = _field(fields, "Source Tier")
    confidence = "High" if tier == "T1" else "Medium" if tier == "T2" else "Low"
    return {
        "Claim ID": stable_id("claim", research_id, evidence_id),
        "Research ID": research_id,
        "Claim Text": fact,
        "Claim Type": "Fact",
        "Evidence IDs": evidence_id,
        "Counter-evidence / Boundary": _field(fields, "Scope / Boundary"),
        "GBSS Relevance": _field(fields, "Business Relevance") or "No direct relevance",
        "Strategic Theme": "",
        "Confidence": confidence,
        "Report Placement": "Signal Radar",
        "Reviewer Status": "Draft",
        "Reviewer Notes": "Generated from verified evidence; approve only after checking fact wording and relevance.",
        "Updated At": _now(),
    }


def upsert_claim_candidates(settings: AppSettings, table: DingTalkAITableSettings, research_id: str, evidence_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    candidates = [claim_fields_from_evidence(research_id, row) for row in evidence_rows if _field((row.get("fields") or row), "Reviewer Status").lower() == "verified"]
    existing = list_records(settings.dingtalk, table)
    by_id = {_field(record.get("fields") or {}, "Claim ID"): record for record in existing}
    creates: List[Dict[str, str]] = []
    updates: List[Dict[str, Any]] = []
    for fields in candidates:
        prior = by_id.get(fields["Claim ID"])
        if prior:
            previous = prior.get("fields") or {}
            for name in ("Reviewer Status", "Reviewer Notes", "Counter-evidence / Boundary", "Strategic Theme", "Report Placement"):
                value = _field(previous, name)
                if value:
                    fields[name] = value
            updates.append({"id": prior["id"], "fields": fields})
        else:
            creates.append(fields)
    if updates:
        result = update_records(settings.dingtalk, table, updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    if creates:
        result = add_records(settings.dingtalk, table, creates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    return candidates


def save_research_result(
    settings: AppSettings,
    table: DingTalkAITableSettings,
    *,
    research_id: str,
    provider: str,
    model: str,
    response_id: str,
    status: str,
    topic: str,
    question: str,
    source_record_ids: Iterable[str],
    evidence_ids: Iterable[str],
    content: str,
    phrases: Iterable[str],
    document_url: str = "",
    document_node_id: str = "",
    document_key: str = "",
    local_artifact_path: str = "",
    error: str = "",
) -> str:
    """Upsert one auditable external-research result, including the full raw output."""
    result_id = stable_id("research-result", research_id, provider, response_id or status)
    fields = {
        "Research Result ID": result_id,
        "Research ID": research_id,
        "Provider": provider,
        "Model": model,
        "Response ID": response_id,
        "Status": status,
        "Generated At": _now(),
        "Topic": topic,
        "Research Question": question,
        "Source Record IDs": ", ".join(str(item) for item in source_record_ids if item),
        "Evidence IDs": ", ".join(str(item) for item in evidence_ids if item),
        "Research Content": content,
        "Deep Insight Phrases": " | ".join(str(item) for item in phrases if item),
        "Research Document URL": document_url,
        "Research Document Node ID": document_node_id,
        "Research Document Key": document_key,
        "Local Artifact Path": local_artifact_path,
        "Error": error,
    }
    for record in list_records(settings.dingtalk, table):
        if _field(record.get("fields") or {}, "Research Result ID") == result_id:
            result = update_records(settings.dingtalk, table, [{"id": record["id"], "fields": fields}])
            if result.status != "sent":
                raise RuntimeError(result.message)
            return str(record["id"])
    created = add_records(settings.dingtalk, table, [fields])
    if created.status != "sent" or not created.record_ids:
        raise RuntimeError(created.message)
    return str(created.record_ids[0])


def research_quality_gate(evidence_rows: Iterable[Dict[str, Any]], claim_rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    evidence = [row.get("fields") or row for row in evidence_rows]
    claims = [row.get("fields") or row for row in claim_rows]
    verified = [row for row in evidence if _field(row, "Reviewer Status").lower() == "verified"]
    tier12 = [row for row in verified if _field(row, "Source Tier") in {"T1", "T2"}]
    independent_tier12 = {
        (urlparse(_field(row, "Source URL")).netloc.lower().removeprefix("www.") or _field(row, "Publisher").lower())
        for row in tier12
    }
    independent_tier12.discard("")
    approved = [row for row in claims if _field(row, "Reviewer Status").lower() == "approved"]
    high_impact = [row for row in claims if _field(row, "Impact Level").lower() == "high"]
    unapproved_high_impact = [row for row in high_impact if _field(row, "Reviewer Status").lower() != "approved"]
    countered = [row for row in approved if _field(row, "Counter-evidence / Boundary")]
    blockers = []
    if len(verified) < 6:
        blockers.append(f"verified evidence {len(verified)}/6")
    if len(independent_tier12) < 3:
        blockers.append(f"independent T1/T2 sources {len(independent_tier12)}/3")
    if not approved:
        blockers.append("approved claims 0/1")
    if unapproved_high_impact:
        blockers.append(f"unapproved high-impact claims {len(unapproved_high_impact)}")
    if not countered:
        blockers.append("no approved claim has counter-evidence or boundary")
    return {
        "status": "Deep Research Ready" if not blockers else "Signal Brief",
        "deep_research_ready": not blockers,
        "verified_evidence_count": len(verified),
        "tier12_evidence_count": len(tier12),
        "independent_tier12_source_count": len(independent_tier12),
        "approved_claim_count": len(approved),
        "countered_claim_count": len(countered),
        "blockers": blockers,
    }


def load_research_context(settings: AppSettings, tables: ResearchTables, research_id: str) -> Dict[str, Any]:
    evidence = [record for record in list_records(settings.dingtalk, tables.evidence) if _field(record.get("fields") or {}, "Research ID") == research_id]
    claims = [record for record in list_records(settings.dingtalk, tables.claims) if _field(record.get("fields") or {}, "Research ID") == research_id]
    queue_rows = [record for record in list_records(settings.dingtalk, tables.queue) if _field(record.get("fields") or {}, "Research ID") == research_id]
    quality = research_quality_gate(evidence, claims)
    return {"research": queue_rows[0] if queue_rows else {}, "evidence": evidence, "claims": claims, "quality": quality}


def validate_synthesis_payload(payload: Dict[str, Any], research_id: str, evidence_rows: Iterable[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    if str(payload.get("research_id") or "") != research_id:
        errors.append("research_id does not match the target Research Queue record")
    evidence_ids = {_field(row.get("fields") or row, "Evidence ID") for row in evidence_rows}
    evidence_ids.discard("")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be a non-empty list")
        return errors
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            errors.append(f"claim {index} must be an object")
            continue
        if str(claim.get("claim_type") or "") not in {"Fact", "Inference", "Hypothesis"}:
            errors.append(f"claim {index} has an invalid claim_type")
        if not str(claim.get("claim_text") or "").strip():
            errors.append(f"claim {index} is missing claim_text")
        linked = claim.get("evidence_ids")
        if not isinstance(linked, list) or not linked:
            errors.append(f"claim {index} must cite one or more evidence_ids")
        elif any(str(item) not in evidence_ids for item in linked):
            errors.append(f"claim {index} cites an unknown evidence_id")
        if str(claim.get("confidence") or "") not in {"High", "Medium", "Low"}:
            errors.append(f"claim {index} has an invalid confidence")
        if str(claim.get("claim_type") or "") == "Inference" and not str(claim.get("counter_evidence_or_boundary") or "").strip():
            errors.append(f"inference claim {index} requires counter_evidence_or_boundary")
    return errors


def import_synthesis_claims(
    settings: AppSettings,
    claims_table: DingTalkAITableSettings,
    research_id: str,
    payload: Dict[str, Any],
    evidence_rows: Iterable[Dict[str, Any]],
) -> List[str]:
    errors = validate_synthesis_payload(payload, research_id, evidence_rows)
    if errors:
        raise ValueError("; ".join(errors))
    now = _now()
    records = list_records(settings.dingtalk, claims_table)
    existing = {_field(record.get("fields") or {}, "Claim ID"): record for record in records}
    creates: List[Dict[str, str]] = []
    updates: List[Dict[str, Any]] = []
    for item in payload["claims"]:
        evidence_ids = [str(value) for value in item.get("evidence_ids") or []]
        claim_id = str(item.get("claim_id") or stable_id("claim", research_id, "|".join(evidence_ids), str(item.get("claim_text") or "")))
        fields = {
            "Claim ID": claim_id,
            "Research ID": research_id,
            "Claim Text": str(item.get("claim_text") or "").strip(),
            "Claim Type": str(item.get("claim_type") or ""),
            "Evidence IDs": ", ".join(evidence_ids),
            "Counter-evidence / Boundary": str(item.get("counter_evidence_or_boundary") or "").strip(),
            "GBSS Relevance": str(item.get("gbss_relevance") or "No direct relevance").strip(),
            "Strategic Theme": str(item.get("strategic_theme") or "").strip(),
            "Confidence": str(item.get("confidence") or "Low"),
            "Report Placement": str(item.get("report_placement") or "Deep Dive"),
            "Reviewer Status": "Draft",
            "Reviewer Notes": "Imported from structured Deep Research synthesis; reviewer approval is required before publication.",
            "Updated At": now,
        }
        existing_record = existing.get(claim_id)
        if existing_record:
            current = existing_record.get("fields") or {}
            for name in ("Reviewer Status", "Reviewer Notes"):
                current_value = _field(current, name)
                if current_value:
                    fields[name] = current_value
            updates.append({"id": existing_record["id"], "fields": fields})
        else:
            creates.append(fields)
    saved: List[str] = []
    if updates:
        result = update_records(settings.dingtalk, claims_table, updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
        saved.extend(result.record_ids)
    if creates:
        result = add_records(settings.dingtalk, claims_table, creates)
        if result.status != "sent":
            raise RuntimeError(result.message)
        saved.extend(result.record_ids)
    return saved


def load_synthesis_payload(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("synthesis payload must be a JSON object")
    return payload
