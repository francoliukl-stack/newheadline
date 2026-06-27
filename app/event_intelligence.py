from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha1
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field

from .dingtalk_ai_table import add_records, cell_text, list_records, update_records
from .event_tables import EventIntelligenceTables
from .models import AppSettings
from .publish_dates import parse_date


EVENT_TYPES = (
    "Earnings", "Stock_Shock", "Regulatory", "Pricing_Fee", "Product_Launch", "Strategic_MA",
    "Merchant_Win_Loss", "Ops_Incident", "Credit_Risk", "Channel_Partner", "Capability_Tech", "General",
)
CRITICAL_EVENT_TYPES = {"Earnings", "Regulatory", "Product_Launch", "Strategic_MA", "Ops_Incident"}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.-]+", re.IGNORECASE)
STOPWORDS = {"the", "and", "for", "with", "from", "into", "new", "its", "this", "that", "latest", "announces", "announced", "launches", "introduces", "reports", "report"}

EVENT_KEYWORDS = {
    "Earnings": ("earnings", "annual results", "quarter results", "financial results", "revenue", "guidance", "profit"),
    "Stock_Shock": ("shares fall", "shares rise", "stock drops", "stock jumps", "share price"),
    "Regulatory": ("regulator", "regulatory", "licence", "license", "rule", "policy", "penalty", "sanction", "hkma", "consultation"),
    "Pricing_Fee": ("pricing", "fee", "fees", "fx rate", "tariff", "commission"),
    "Product_Launch": ("launch", "launches", "introduces", "unveils", "releases", "rolls out", "product", "upgrade", "announces"),
    "Strategic_MA": ("acquire", "acquisition", "merger", "merge", "strategic partnership", "joint venture", "investment", "funding", "buy"),
    "Merchant_Win_Loss": ("merchant win", "selected by", "exclusive payment", "terminates partnership", "merchant loss"),
    "Ops_Incident": ("outage", "incident", "data breach", "disruption", "payment failure", "service unavailable"),
    "Credit_Risk": ("npl", "non-performing", "delinquency", "default rate", "credit loss", "loan loss"),
    "Channel_Partner": ("interoperability", "qr linkage", "wallet linkage", "payment linkage", "cross-border qr", "channel partner"),
    "Capability_Tech": ("contact center", "voice ai", "aiqc", "quality management", "service quality evaluation", "customer service ai", "aicc"),
}


class EventLLMAnalysis(BaseModel):
    event_type: str
    business_lines: List[str]
    entities: List[str]
    summary: str
    gbss_relevance: str
    severity_candidate: str
    confidence: float = Field(ge=0, le=1)
    evidence_needed: List[str]
    limitations: List[str]


@dataclass
class EntityRecord:
    entity_id: str
    canonical_name: str
    aliases: List[str]
    business_lines: List[str]
    ticker: str = ""
    official_urls: List[str] = field(default_factory=list)
    watch_tier: str = "standard"
    active: bool = True


@dataclass
class EventSourceCandidate:
    news_record_id: str
    title: str
    url: str
    source_domain: str
    publish_date: str
    provider: str
    accepted: bool


@dataclass
class EventCandidate:
    event_id: str
    title: str
    event_type: str
    business_lines: List[str]
    entities: List[EntityRecord]
    sources: List[EventSourceCandidate]
    event_date: str
    strategic_candidate: bool
    confidence: float
    scores: Dict[str, float]
    overall_score: float
    priority_candidate: str
    summary: str
    impact_hypothesis: str
    limitations: str


def normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    clean = parsed._replace(fragment="", query="")
    return urlunparse(clean).rstrip("/")


def title_tokens(title: str) -> Set[str]:
    return {token.lower() for token in TOKEN_RE.findall(title or "") if token.lower() not in STOPWORDS and len(token) > 2}


def title_similarity(left: str, right: str) -> float:
    a, b = title_tokens(left), title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def infer_event_type(title: str) -> str:
    text = str(title or "").lower()
    if any(_keyword_present(text, keyword) for keyword in EVENT_KEYWORDS["Capability_Tech"]):
        return "Capability_Tech"
    matches = []
    for event_type, keywords in EVENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if _keyword_present(text, keyword))
        if score:
            matches.append((score, event_type))
    if not matches:
        return "General"
    matches.sort(key=lambda item: (item[0], item[1] in CRITICAL_EVENT_TYPES), reverse=True)
    return matches[0][1]


def _keyword_present(text: str, keyword: str) -> bool:
    if " " in keyword or any(char in keyword for char in "+/&"):
        return keyword in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text))


def same_event(left_title: str, right_title: str, left_type: str = "", right_type: str = "", shared_entity: bool = True) -> bool:
    left_type = left_type or infer_event_type(left_title)
    right_type = right_type or infer_event_type(right_title)
    if not shared_entity or left_type != right_type:
        return False
    if normalize_title(left_title) == normalize_title(right_title):
        return True
    similarity = title_similarity(left_title, right_title)
    if left_type == "Channel_Partner" and shared_entity:
        return True
    return similarity >= 0.14 or (left_type in CRITICAL_EVENT_TYPES and similarity >= 0.07)


def normalize_title(title: str) -> str:
    return " ".join(sorted(title_tokens(title)))


def _split(value: Any) -> List[str]:
    text = cell_text(value)
    return [item.strip() for item in re.split(r"[,|;\n]", text) if item.strip()]


def catalog_from_records(records: Iterable[Dict[str, Any]]) -> List[EntityRecord]:
    entities = []
    for record in records:
        fields = record.get("fields") or record
        entity_id = cell_text(fields.get("Entity ID")).strip()
        name = cell_text(fields.get("Canonical Name")).strip()
        if not entity_id or not name:
            continue
        entities.append(EntityRecord(entity_id, name, _split(fields.get("Aliases")), _split(fields.get("Business Lines")), cell_text(fields.get("Ticker")).strip(), _split(fields.get("Official URLs")) + _split(fields.get("IR URLs")) + _split(fields.get("Newsroom URLs")) + _split(fields.get("Regulatory URLs")), cell_text(fields.get("Watch Tier")).strip().lower() or "standard", cell_text(fields.get("Active")).strip().lower() not in {"no", "false", "0", "disabled"}))
    return entities


def match_entities(title: str, url: str, catalog: Sequence[EntityRecord]) -> List[EntityRecord]:
    text = f" {title.lower()} "
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    matches = []
    for entity in catalog:
        if not entity.active:
            continue
        names = [entity.canonical_name] + entity.aliases + ([entity.ticker] if entity.ticker else [])
        name_match = any(name and re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", text) for name in names)
        domain_match = any(domain and domain == urlparse(candidate).netloc.lower().removeprefix("www.") for candidate in entity.official_urls)
        if name_match or domain_match:
            matches.append(entity)
    return matches


def score_event(event_type: str, entities: Sequence[EntityRecord], source_grade: str = "T2", market_confirmed: bool = False, novelty: float = 0.7) -> Tuple[Dict[str, float], float]:
    severity = {"Ops_Incident": 1.0, "Regulatory": 0.95, "Strategic_MA": 0.9, "Earnings": 0.85, "Product_Launch": 0.8, "Pricing_Fee": 0.8, "Stock_Shock": 0.75}.get(event_type, 0.55)
    scores = {
        "source_grade": {"T1": 1.0, "T2": 0.8, "T3": 0.4}.get(source_grade, 0.5),
        "entity_match": 1.0 if entities else 0.2,
        "event_severity": severity,
        "business_line_fit": 1.0 if any(entity.business_lines for entity in entities) else 0.3,
        "novelty": max(0.0, min(1.0, novelty)),
        "market_confirmation": 1.0 if market_confirmed else 0.5,
    }
    overall = round(0.25 * scores["source_grade"] + 0.20 * scores["entity_match"] + 0.20 * scores["event_severity"] + 0.15 * scores["business_line_fit"] + 0.10 * scores["novelty"] + 0.10 * scores["market_confirmation"], 4)
    return scores, overall


def machine_priority(score: float, event_type: str, strategic: bool, p0_threshold: float = 0.8, p1_threshold: float = 0.6, watch_threshold: float = 0.4) -> str:
    if strategic and score >= p0_threshold:
        return "P0_Candidate"
    if score >= p1_threshold:
        return "P1"
    if score >= watch_threshold:
        return "Watch"
    return "P2"


def _source_url(fields: Dict[str, Any]) -> str:
    value = fields.get("Source URL") or fields.get("Link") or ""
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "")
    return str(value or "")


def _publish_date(fields: Dict[str, Any]) -> str:
    value = fields.get("Publish Date") or fields.get("releaseDate") or ""
    return parse_date(value) or ""


def _news_source(record: Dict[str, Any]) -> EventSourceCandidate:
    fields = record.get("fields") or {}
    url = normalize_url(_source_url(fields))
    return EventSourceCandidate(str(record.get("id") or fields.get("No") or ""), cell_text(fields.get("Title") or fields.get("Subject")), url, urlparse(url).netloc.lower().removeprefix("www."), _publish_date(fields), cell_text(fields.get("Search Provider") or fields.get("Provider")), cell_text(fields.get("Status") or fields.get("Review Status")) == "已采纳")


def _event_id(entity_id: str, event_type: str, event_date: str, title: str) -> str:
    canonical = "|".join((entity_id or "unmatched", event_type, event_date, " ".join(sorted(title_tokens(title))[:6])))
    return f"event-{sha1(canonical.encode('utf-8')).hexdigest()[:16]}"


def eventize_records(records: Sequence[Dict[str, Any]], catalog: Sequence[EntityRecord], settings: AppSettings) -> List[EventCandidate]:
    items = []
    for record in records:
        fields = record.get("fields") or {}
        status = cell_text(fields.get("Status") or fields.get("Review Status"))
        if status in {"已拒绝", "已重复"}:
            continue
        source = _news_source(record)
        if not source.title or not source.url:
            continue
        entities = match_entities(source.title, source.url, catalog)
        if not entities:
            continue
        event_type = infer_event_type(source.title)
        event_date = source.publish_date or datetime.now(timezone.utc).date().isoformat()
        items.append({"source": source, "entities": entities, "event_type": event_type, "event_date": event_date})
    groups: List[List[Dict[str, Any]]] = []
    for item in items:
        entity_ids = {entity.entity_id for entity in item["entities"]}
        matched = None
        for group in groups:
            first = group[0]
            first_ids = {entity.entity_id for entity in first["entities"]}
            try:
                date_close = abs((date.fromisoformat(item["event_date"]) - date.fromisoformat(first["event_date"])).days) <= settings.event_intelligence.event_window_days
            except ValueError:
                date_close = True
            if date_close and same_event(item["source"].title, first["source"].title, item["event_type"], first["event_type"], bool(entity_ids & first_ids)):
                matched = group
                break
        if matched is not None:
            matched.append(item)
        else:
            groups.append([item])
    candidates = []
    for group in groups:
        first = group[0]
        entities_by_id = {entity.entity_id: entity for item in group for entity in item["entities"]}
        entities = list(entities_by_id.values())
        sources = [item["source"] for item in group]
        event_type = first["event_type"]
        strategic = event_type in CRITICAL_EVENT_TYPES and any(entity.watch_tier in {"critical", "high"} for entity in entities)
        grade = "T1" if any(any(source.source_domain == urlparse(url).netloc.lower().removeprefix("www.") for url in entity.official_urls) for source in sources for entity in entities) else "T2"
        scores, overall = score_event(event_type, entities, grade, event_type == "Stock_Shock")
        event_id = _event_id(entities[0].entity_id if entities else "", event_type, first["event_date"], first["source"].title)
        business_lines = sorted({line for entity in entities for line in entity.business_lines})
        priority = machine_priority(overall, event_type, strategic, settings.event_intelligence.p0_candidate_score, settings.event_intelligence.p1_score, settings.event_intelligence.watch_score)
        candidates.append(EventCandidate(event_id, first["source"].title, event_type, business_lines, entities, sources, first["event_date"], strategic, 0.9 if entities else 0.55, scores, overall, priority, first["source"].title, "Potential impact requires reviewer validation against the mapped GBSS business line.", "Machine-generated candidate; verify scope, metrics and counter-evidence before publication."))
    return candidates


def _upsert(settings: AppSettings, table: Any, key: str, rows: List[Dict[str, Any]]) -> None:
    existing = {cell_text((record.get("fields") or {}).get(key)): record for record in list_records(settings.dingtalk, table)}
    creates, updates = [], []
    for fields in rows:
        previous = existing.get(str(fields.get(key) or ""))
        if previous:
            updates.append({"id": previous["id"], "fields": fields})
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


def persist_event_candidates(settings: AppSettings, tables: EventIntelligenceTables, candidates: Sequence[EventCandidate]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing_events = {cell_text((record.get("fields") or {}).get("Event ID")): record for record in list_records(settings.dingtalk, tables.event_cases)}
    event_rows, entity_rows, source_rows, score_rows, news_updates, evidence_rows, claim_rows = [], [], [], [], [], [], []
    for event in candidates:
        previous = (existing_events.get(event.event_id) or {}).get("fields") or {}
        primary = event.sources[0]
        event_rows.append({
            "Event ID": event.event_id, "Event Title": event.title, "Event Type": event.event_type,
            "Business Lines": ", ".join(event.business_lines), "Primary Entity IDs": ", ".join(entity.entity_id for entity in event.entities),
            "Strategic Candidate": "yes" if event.strategic_candidate else "no", "First Seen At": cell_text(previous.get("First Seen At")) or now,
            "Event Date": event.event_date, "Status": cell_text(previous.get("Status")) or "待处理", "Priority Candidate": event.priority_candidate,
            "Final Priority": cell_text(previous.get("Final Priority")) or "None", "P0 Approval Status": cell_text(previous.get("P0 Approval Status")) or "Not requested",
            "Confidence": str(event.confidence), "Relevance Score": str(event.overall_score), "Summary": event.summary,
            "GBSS Impact Hypothesis": event.impact_hypothesis, "Limitations": event.limitations,
            "Primary Source URL": {"text": primary.source_domain or primary.url, "link": primary.url}, "Publish Date": primary.publish_date,
            "Source Count": str(len(event.sources)), "Accepted News Count": str(sum(source.accepted for source in event.sources)),
            "Reviewer": cell_text(previous.get("Reviewer")), "Reviewed At": cell_text(previous.get("Reviewed At")),
            "Weekly Headlines Sent At": cell_text(previous.get("Weekly Headlines Sent At")), "Weekly Intelligence Sent At": cell_text(previous.get("Weekly Intelligence Sent At")),
            "Event Version": sha1("|".join(sorted(source.news_record_id for source in event.sources)).encode("utf-8")).hexdigest()[:12], "Updated At": now,
        })
        for entity in event.entities:
            relation_id = f"event-entity-{sha1(f'{event.event_id}|{entity.entity_id}'.encode()).hexdigest()[:16]}"
            entity_rows.append({"Event Entity ID": relation_id, "Event ID": event.event_id, "Entity ID": entity.entity_id, "Role": "primary" if entity == event.entities[0] else "related", "Match Method": "catalog_alias_or_domain", "Confidence": str(event.confidence), "Created At": now})
        for index, source in enumerate(event.sources):
            relation_id = f"event-source-{sha1(f'{event.event_id}|{source.news_record_id}|{source.url}'.encode()).hexdigest()[:16]}"
            source_rows.append({"Event Source ID": relation_id, "Event ID": event.event_id, "News Record ID": source.news_record_id, "Source URL": {"text": source.source_domain or source.url, "link": source.url}, "Source Domain": source.source_domain, "Publish Date": source.publish_date, "Source Grade": "T1" if index == 0 and event.strategic_candidate else "T2", "Is Primary Source": "yes" if index == 0 else "no", "Evidence Value": "core" if index == 0 else "supporting", "Provider": source.provider, "Duplicate Of": "", "Content Hash": sha1(normalize_url(source.url).encode()).hexdigest(), "Created At": now})
            if source.news_record_id:
                news_updates.append({"id": source.news_record_id, "fields": {"Event Case ID": event.event_id, "Entity Candidates": ", ".join(entity.entity_id for entity in event.entities), "LLM Processed At": now}})
            if index == 0:
                evidence_id = f"evidence-{sha1(f'{event.event_id}|{source.url}'.encode()).hexdigest()[:16]}"
                evidence_rows.append({"Evidence ID": evidence_id, "Research ID": f"event:{event.event_id}", "Event ID": event.event_id, "Event Source IDs": relation_id, "Source Record ID": source.news_record_id, "Source URL": {"text": source.source_domain or source.url, "link": source.url}, "Source Title": source.title, "Publisher": source.source_domain, "Published Date": source.publish_date, "Source Tier": "T1" if event.strategic_candidate else "T2", "Source Type": "event primary source", "Extracted Fact": source.title, "Metric": "", "Scope / Boundary": event.limitations, "Business Relevance": ", ".join(event.business_lines), "Impacted Capability": "", "Supports / Challenges": "Candidate support", "Confidence": "High" if event.confidence >= 0.8 else "Medium", "Reviewer Status": "Pending", "Reviewer Notes": "Verify source text before approving the linked event claim.", "Captured At": now})
                claim_rows.append({"Claim ID": f"claim-{event.event_id}", "Research ID": f"event:{event.event_id}", "Event ID": event.event_id, "Claim Text": event.summary, "Claim Type": "Fact", "Evidence IDs": evidence_id, "Counter-evidence / Boundary": event.limitations, "GBSS Relevance": event.impact_hypothesis, "Strategic Theme": ", ".join(event.business_lines), "Confidence": "Medium", "Report Placement": "Event Case", "Impact Level": "High" if event.strategic_candidate else "Standard", "Reviewer Status": "Draft", "Reviewer Notes": "Approve only after Evidence verification.", "Updated At": now})
        score_rows.append({"Event Score ID": f"score-{event.event_id}", "Event ID": event.event_id, "Source Grade Score": str(event.scores["source_grade"]), "Entity Match Score": str(event.scores["entity_match"]), "Event Severity Score": str(event.scores["event_severity"]), "Business Line Fit Score": str(event.scores["business_line_fit"]), "Novelty Score": str(event.scores["novelty"]), "Market Confirmation Score": str(event.scores["market_confirmation"]), "Overall Score": str(event.overall_score), "Scoring Reason": json.dumps(event.scores, ensure_ascii=False), "Scoring Version": "v3.1.0", "Model": "deterministic", "Prompt Version": "none", "Scored At": now, "Human Override": ""})
    _upsert(settings, tables.event_cases, "Event ID", event_rows)
    _upsert(settings, tables.event_entities, "Event Entity ID", entity_rows)
    _upsert(settings, tables.event_sources, "Event Source ID", source_rows)
    _upsert(settings, tables.event_scores, "Event Score ID", score_rows)
    if settings.dingtalk_ai_table.evidence_bank_sheet_id:
        evidence_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.evidence_bank_sheet_id})
        _upsert(settings, evidence_table, "Evidence ID", evidence_rows)
    if settings.dingtalk_ai_table.claim_ledger_sheet_id:
        claim_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.claim_ledger_sheet_id})
        _upsert(settings, claim_table, "Claim ID", claim_rows)
    if news_updates:
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, news_updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    return len(event_rows)


def validate_final_p0(fields: Dict[str, Any]) -> bool:
    if cell_text(fields.get("Final Priority")) != "P0":
        return True
    return cell_text(fields.get("P0 Approval Status")) == "Approved" and bool(cell_text(fields.get("Reviewer"))) and bool(cell_text(fields.get("Reviewed At")))


def publication_eligible(event_fields: Dict[str, Any]) -> bool:
    source = event_fields.get("Primary Source URL")
    source_url = source.get("link") if isinstance(source, dict) else source
    try:
        accepted_count = int(float(cell_text(event_fields.get("Accepted News Count")) or 0))
    except ValueError:
        accepted_count = 0
    return cell_text(event_fields.get("Status")) == "已采纳" and accepted_count >= 1 and bool(source_url) and bool(cell_text(event_fields.get("Publish Date"))) and validate_final_p0(event_fields)
