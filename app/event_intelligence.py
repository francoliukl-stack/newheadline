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
from .research_production import source_tier


EVENT_TYPES = (
    "Earnings", "Stock_Shock", "Regulatory", "Pricing_Fee", "Market_Expansion", "Product_Launch", "Strategic_MA",
    "Merchant_Win_Loss", "Ops_Incident", "Credit_Risk", "Channel_Partner", "Capability_Tech", "Leadership_Change", "Market_Context", "General",
)
CRITICAL_EVENT_TYPES = {"Earnings", "Regulatory", "Market_Expansion", "Product_Launch", "Strategic_MA", "Ops_Incident"}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.-]+", re.IGNORECASE)
STOPWORDS = {"the", "and", "for", "with", "from", "into", "new", "its", "this", "that", "latest", "announces", "announced", "launches", "introduces", "reports", "report"}

EVENT_KEYWORDS = {
    "Earnings": ("earnings", "annual results", "quarter results", "financial results", "guidance"),
    "Stock_Shock": ("shares fall", "shares rise", "stock drops", "stock jumps", "share price"),
    "Regulatory": ("regulator", "regulatory", "investigation", "probe", "licence", "license", "rule", "rules", "policy", "penalty", "sanction", "hkma", "monetary authority", "urges banks", "six-point strategy", "consultation"),
    "Pricing_Fee": ("pricing", "fee", "fees", "fx rate", "tariff", "commission"),
    "Market_Expansion": ("market entry", "enters the market", "expands into", "expands to", "expands merchant acceptance", "expansion into", "launches in", "goes global", "takes upi", "desembarcar en", "entra en", "ingresa a"),
    "Product_Launch": ("launch", "launches", "introduces", "introducing", "unveils", "releases", "rolls out", "upgrade"),
    "Strategic_MA": ("acquire", "acquisition", "merger", "merge", "strategic partnership", "joint venture", "investment", "funding"),
    "Merchant_Win_Loss": ("merchant win", "selected by", "exclusive payment", "terminates partnership", "merchant loss"),
    "Ops_Incident": ("outage", "incident", "data breach", "disruption", "payment failure", "service unavailable"),
    "Credit_Risk": ("npl", "non-performing", "delinquency", "default rate", "credit loss", "loan loss"),
    "Channel_Partner": ("interoperability", "integration", "partners with", "qr linkage", "wallet linkage", "payment linkage", "cross-border qr", "channel partner"),
    "Capability_Tech": ("contact center", "voice ai", "aiqc", "quality management", "service quality evaluation", "customer service ai", "aicc"),
    "Market_Context": ("valued at", "valuation", "focuses on", "focus on", "infrastructure", "comparison", " vs ", "initiative", "initiatives", "was built", "bikin jualan", "lebih praktis"),
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
    scan_urls: List[str] = field(default_factory=list)


@dataclass
class EventSourceCandidate:
    news_record_id: str
    title: str
    url: str
    source_domain: str
    publish_date: str
    provider: str
    accepted: bool
    source_grade: str = "T3"
    source_excerpt: str = ""


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
    if (
        re.search(r"\b(?:appoints?|names?|hires?)\b.{0,60}\b(?:ceo|cfo|cpo|chief executive officer|chief financial officer|chief product officer)\b", text)
        or re.search(r"\b(?:ceo|cfo|cpo|chief executive officer|chief financial officer|chief product officer)\b.{0,40}\b(?:steps? down|departs?|resigns?|exits?|interim)\b", text)
    ):
        return "Leadership_Change"
    if re.search(r"\b(?:fy|q[1-4]|h[12])\s*\d{2,4}\s+(?:financial\s+)?(?:results|earnings)\b", text):
        return "Earnings"
    if re.search(r"\$[\d.]+\s*(?:b|bn|billion|m|million).{0,50}\bbuy\b", text):
        return "Strategic_MA"
    if re.search(r"\b(?:raise[sd]?|raising)\b.{0,24}\$[\d.]+\s*(?:b|bn|billion|m|million)\b", text):
        return "Strategic_MA"
    if (
        re.search(r"\b(?:raise[sd]?|raising|secure[sd]?|close[sd]?|complete[sd]?)\b", text)
        and re.search(r"\b(?:series\s+[a-z0-9]+(?:\s+round)?|funding(?:\s+round)?)\b", text)
    ):
        return "Strategic_MA"
    if re.search(r"\b(?:specialization|certification|partner)\s+program\b", text) and re.search(r"\bpartners?\b", text):
        return "Channel_Partner"
    if re.search(r"\b(?:announc(?:e|es|ed|ing)|launch(?:es|ed|ing)?|rolls?\s+out|unveil(?:s|ed|ing)?|introduc(?:e|es|ed|ing))\b", text) and re.search(r"\b(?:agentic|agent builder|product|platform|service|solution|feature)\b", text):
        return "Product_Launch"
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
    if transaction_signature(left_title) and transaction_signature(left_title) == transaction_signature(right_title):
        return True
    if normalize_title(left_title) == normalize_title(right_title):
        return True
    similarity = title_similarity(left_title, right_title)
    if left_type == "Channel_Partner" and shared_entity:
        return True
    return similarity >= 0.14 or (left_type in CRITICAL_EVENT_TYPES and similarity >= 0.07)


def transaction_signature(title: str) -> str:
    match = re.search(r"\$\s*([\d.]+)\s*(b|bn|billion|m|million)\b", title, re.I)
    if not match:
        return ""
    suffix = "b" if match.group(2).lower() in {"b", "bn", "billion"} else "m"
    return f"${float(match.group(1)):g}{suffix}"


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
        official_urls = _split(fields.get("Official URLs"))
        scan_urls = _split(fields.get("IR URLs")) + _split(fields.get("Newsroom URLs")) + _split(fields.get("Regulatory URLs"))
        entities.append(EntityRecord(entity_id, name, _split(fields.get("Aliases")), _split(fields.get("Business Lines")), cell_text(fields.get("Ticker")).strip(), official_urls, cell_text(fields.get("Watch Tier")).strip().lower() or "standard", cell_text(fields.get("Active")).strip().lower() not in {"no", "false", "0", "disabled"}, list(dict.fromkeys(scan_urls))))
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
        domain_match = any(
            domain and (
                domain == urlparse(candidate).netloc.lower().removeprefix("www.")
                or domain.endswith(f".{urlparse(candidate).netloc.lower().removeprefix('www.')}")
            )
            for candidate in entity.official_urls
            if urlparse(candidate).netloc
        )
        if entity.entity_id == "visa" and name_match and not domain_match:
            immigration_context = bool(re.search(r"\b(?:h-?1b|immigration|immigrant|passport|consular|consulate|embassy|tourist|student|work)\b.{0,30}\bvisa\b|\bvisa\b.{0,30}\b(?:application|applicant|immigration|passport|consular|travel)\b", title, re.I))
            payment_context = bool(re.search(r"\b(?:payment|payments|card|cards|merchant|transaction|issuer|acquirer|fintech|commerce|checkout|stablecoin)\b", title, re.I))
            explicit_brand_case = bool(re.search(r"(?<![A-Za-z0-9])Visa(?![A-Za-z0-9])", title))
            name_match = (payment_context or explicit_brand_case) and not (immigration_context and not payment_context)
        if entity.entity_id == "unionpay-international" and name_match and not domain_match:
            name_match = bool(re.search(r"\bunionpay(?:\s+international)?\b", title, re.I))
        if entity.entity_id == "india-upi" and name_match and not domain_match:
            india_upi_context = bool(re.search(r"\b(?:india|indian|npci|instant money transfers?|instant bank transfers?|upi expands?|upi goes global)\b", title, re.I))
            unionpay_context = bool(re.search(r"\bunionpay(?:\s+international)?\b", title, re.I))
            name_match = india_upi_context and not unionpay_context
        if name_match or domain_match:
            matches.append(entity)
    return matches


def is_critical_signal(signal: Any, catalog: Sequence[EntityRecord], *, lookback_days: Optional[int] = None, now: Optional[datetime] = None) -> bool:
    event_type = infer_event_type(str(getattr(signal, "title", "") or ""))
    if event_type not in CRITICAL_EVENT_TYPES | {"Stock_Shock"}:
        return False
    matches = match_entities(str(getattr(signal, "title", "") or ""), str(getattr(signal, "source_url", "") or ""), catalog)
    if not any(entity.watch_tier in {"critical", "high"} for entity in matches):
        return False
    published = parse_date(str(getattr(signal, "publish_date", "") or ""))
    if lookback_days and published:
        current = (now or datetime.now(timezone.utc)).date()
        if date.fromisoformat(published) < current - timedelta(days=max(lookback_days - 1, 0)):
            return False
    return True


def score_event(event_type: str, entities: Sequence[EntityRecord], source_grade: str = "T2", market_confirmed: bool = False, novelty: float = 0.7) -> Tuple[Dict[str, float], float]:
    severity = {"Ops_Incident": 1.0, "Regulatory": 0.95, "Strategic_MA": 0.9, "Earnings": 0.85, "Market_Expansion": 0.85, "Product_Launch": 0.8, "Pricing_Fee": 0.8, "Stock_Shock": 0.75}.get(event_type, 0.55)
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
    if event_type == "Market_Context":
        return "Watch"
    if strategic and score >= p0_threshold:
        return "P0_Candidate"
    if score >= p1_threshold:
        return "P1"
    if score >= watch_threshold:
        return "Watch"
    return "Watch"


def deterministic_impact_hypothesis(event_type: str, business_lines: Sequence[str]) -> str:
    lines = set(business_lines)
    if "WorldFirst" in lines and event_type == "Earnings":
        focus = "Compare disclosed cross-border volume, take rate, business-customer growth and guidance with WorldFirst pricing, product and service-demand assumptions."
    elif "Antom" in lines and event_type in {"Product_Launch", "Strategic_MA", "Channel_Partner"}:
        focus = "Review implications for Antom merchant onboarding, payment acceptance, authorization performance, disputes and merchant-support workload."
    elif "Alipay_Plus" in lines:
        focus = "Review implications for Alipay+ wallet/QR coverage, partner operations, merchant acceptance and cross-border customer experience."
    elif "Bettr" in lines:
        focus = "Review implications for Bettr SME credit access, underwriting, collections, risk operations and customer support."
    elif "HK_Fintech" in lines:
        focus = "Review implications for Hong Kong regulatory compliance, banking operations, customer communication and service controls."
    elif "GBSS_Service" in lines:
        focus = "Review implications for GBSS Contact Center AI, Voice AI, AIQC, agent operations and service governance."
    else:
        focus = "Review the mapped business-line impact on operations, compliance, service demand and customer experience."
    return f"Reviewer hypothesis only — not a verified claim. {focus}"


def deterministic_limitations(event_type: str) -> str:
    return f"Deterministic {event_type} candidate based on retained source metadata/excerpt. Verify source scope, metrics, dates and counter-evidence before approving any Claim or management conclusion."


def event_status_from_news(sources: Sequence[EventSourceCandidate], previous_status: str = "") -> str:
    if any(source.accepted for source in sources):
        return "已采纳"
    return previous_status if previous_status in {"已拒绝", "已重复", "已归档"} else "待处理"


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
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    grade, _reason = source_tier(url, domain)
    return EventSourceCandidate(str(record.get("id") or fields.get("No") or ""), cell_text(fields.get("Title") or fields.get("Subject")), url, domain, _publish_date(fields), cell_text(fields.get("Search Provider") or fields.get("Provider")), cell_text(fields.get("Status") or fields.get("Review Status")) == "已采纳", grade, cell_text(fields.get("Source Excerpt"))[:1800])


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
                day_gap = abs((date.fromisoformat(item["event_date"]) - date.fromisoformat(first["event_date"])).days)
                same_transaction = bool(
                    transaction_signature(item["source"].title)
                    and transaction_signature(item["source"].title) == transaction_signature(first["source"].title)
                    and item["event_type"] == first["event_type"]
                    and entity_ids & first_ids
                )
                date_close = day_gap <= (7 if same_transaction else settings.event_intelligence.event_window_days)
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
        grade_rank = {"T1": 0, "T2": 1, "T3": 2}
        sources = sorted((item["source"] for item in group), key=lambda source: (grade_rank.get(source.source_grade, 3), not source.accepted, source.publish_date or "9999-99-99"))
        event_type = first["event_type"]
        strategic = event_type in CRITICAL_EVENT_TYPES and any(entity.watch_tier in {"critical", "high"} for entity in entities)
        grade = sources[0].source_grade if sources else "T3"
        scores, overall = score_event(event_type, entities, grade, event_type == "Stock_Shock")
        event_id = _event_id(entities[0].entity_id if entities else "", event_type, first["event_date"], first["source"].title)
        business_lines = sorted({line for entity in entities for line in entity.business_lines})
        priority = machine_priority(overall, event_type, strategic, settings.event_intelligence.p0_candidate_score, settings.event_intelligence.p1_score, settings.event_intelligence.watch_score)
        candidates.append(EventCandidate(event_id, first["source"].title, event_type, business_lines, entities, sources, first["event_date"], strategic, 0.9 if entities else 0.55, scores, overall, priority, first["source"].title, deterministic_impact_hypothesis(event_type, business_lines), deterministic_limitations(event_type)))
    return candidates


def enrich_events_with_llm(events: Sequence[EventCandidate], service: Any, settings: AppSettings, run_id: str) -> List[EventCandidate]:
    allowed_lines = {"Alipay_Plus", "WorldFirst", "Bettr", "Antom", "HK_Fintech", "GBSS_Service"}
    for event in events:
        needs_analysis = event.event_type == "General" or len(event.entities) > 1 or event.strategic_candidate
        if not needs_analysis:
            continue
        model = settings.openai_service.analysis_model if event.strategic_candidate else settings.openai_service.classification_model
        result = service.execute(
            task="event_analysis",
            schema=EventLLMAnalysis,
            context={
                "event_id": event.event_id,
                "title": event.title,
                "source_urls": [source.url for source in event.sources],
                "publish_dates": [source.publish_date for source in event.sources],
                "matched_entities": [entity.canonical_name for entity in event.entities],
                "deterministic_event_type": event.event_type,
                "deterministic_business_lines": event.business_lines,
                "rules": {"allowed_event_types": EVENT_TYPES, "allowed_business_lines": sorted(allowed_lines), "maximum_machine_priority": "P0_Candidate"},
            },
            budget_scope="ingest",
            event_id=event.event_id,
            run_id=run_id,
            model=model,
            max_output_tokens=900,
        )
        if result.status != "completed" or result.value is None:
            continue
        analysis = result.value
        if analysis.event_type in EVENT_TYPES:
            event.event_type = analysis.event_type
        mapped_lines = [line for line in analysis.business_lines if line in allowed_lines]
        if mapped_lines:
            event.business_lines = list(dict.fromkeys(mapped_lines))
        event.summary = analysis.summary.strip() or event.summary
        event.impact_hypothesis = analysis.gbss_relevance.strip() or event.impact_hypothesis
        event.limitations = "; ".join(analysis.limitations) or event.limitations
        event.confidence = analysis.confidence
        event.strategic_candidate = event.event_type in CRITICAL_EVENT_TYPES and any(entity.watch_tier in {"critical", "high"} for entity in event.entities)
        source_grade = event.sources[0].source_grade if event.sources else "T3"
        event.scores, event.overall_score = score_event(event.event_type, event.entities, source_grade, event.event_type == "Stock_Shock")
        event.priority_candidate = machine_priority(event.overall_score, event.event_type, event.strategic_candidate, settings.event_intelligence.p0_candidate_score, settings.event_intelligence.p1_score, settings.event_intelligence.watch_score)
    return list(events)


def _upsert(settings: AppSettings, table: Any, key: str, rows: List[Dict[str, Any]], *, preserve_nonempty: Sequence[str] = (), preserve_when_reviewed: Sequence[str] = (), review_field: str = "", unlocked_statuses: Sequence[str] = (), existing_records: Optional[Sequence[Dict[str, Any]]] = None) -> None:
    records = list_records(settings.dingtalk, table) if existing_records is None else existing_records
    existing = {cell_text((record.get("fields") or {}).get(key)): record for record in records}
    creates, updates = [], []
    for fields in rows:
        previous = existing.get(str(fields.get(key) or ""))
        if previous:
            merged = dict(fields)
            previous_fields = previous.get("fields") or {}
            for name in preserve_nonempty:
                if name in previous_fields and cell_text(previous_fields.get(name)).strip():
                    merged[name] = previous_fields[name]
            review_status = cell_text(previous_fields.get(review_field)).strip().lower() if review_field else ""
            if preserve_when_reviewed and review_status not in {item.lower() for item in unlocked_statuses}:
                for name in preserve_when_reviewed:
                    if name in previous_fields and cell_text(previous_fields.get(name)).strip():
                        merged[name] = previous_fields[name]
            updates.append({"id": previous["id"], "fields": merged})
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


def reconcile_event_ids(candidates: Sequence[EventCandidate], event_source_records: Sequence[Dict[str, Any]]) -> int:
    by_content_hash: Dict[str, str] = {}
    for record in event_source_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID")).strip()
        content_hash = cell_text(fields.get("Content Hash")).strip()
        source_url = _source_url(fields)
        if event_id and not content_hash and source_url:
            content_hash = sha1(normalize_url(source_url).encode()).hexdigest()
        if event_id and content_hash:
            by_content_hash.setdefault(content_hash, event_id)
    reconciled = 0
    for event in candidates:
        stable_id = next((by_content_hash.get(sha1(normalize_url(source.url).encode()).hexdigest()) for source in event.sources if normalize_url(source.url) and by_content_hash.get(sha1(normalize_url(source.url).encode()).hexdigest())), "")
        if stable_id and stable_id != event.event_id:
            event.event_id = stable_id
            reconciled += 1
    return reconciled


def superseded_entity_relation_updates(
    existing_records: Sequence[Dict[str, Any]],
    expected_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    active_event_ids = {cell_text(row.get("Event ID")) for row in expected_rows if cell_text(row.get("Event ID"))}
    expected_pairs = {
        (cell_text(row.get("Event ID")), cell_text(row.get("Entity ID")))
        for row in expected_rows
        if cell_text(row.get("Event ID")) and cell_text(row.get("Entity ID"))
    }
    updates = []
    for record in existing_records:
        fields = record.get("fields") or {}
        pair = (cell_text(fields.get("Event ID")), cell_text(fields.get("Entity ID")))
        if pair[0] not in active_event_ids or pair in expected_pairs or cell_text(fields.get("Role")) == "superseded":
            continue
        updates.append({"id": record["id"], "fields": {
            "Role": "superseded",
            "Match Method": "catalog_reconciliation",
            "Confidence": "0",
        }})
    return updates


def persist_event_candidates(settings: AppSettings, tables: EventIntelligenceTables, candidates: Sequence[EventCandidate]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing_sources = list_records(settings.dingtalk, tables.event_sources)
    existing_event_records = list_records(settings.dingtalk, tables.event_cases)
    existing_entity_records = list_records(settings.dingtalk, tables.event_entities)
    reconcile_event_ids(candidates, existing_sources)
    existing_events = {cell_text((record.get("fields") or {}).get("Event ID")): record for record in existing_event_records}
    event_rows, entity_rows, source_rows, score_rows, news_updates, evidence_rows, claim_rows = [], [], [], [], [], [], []
    for event in candidates:
        previous = (existing_events.get(event.event_id) or {}).get("fields") or {}
        primary = event.sources[0]
        accepted_news_count = sum(source.accepted for source in event.sources)
        previous_status = cell_text(previous.get("Status"))
        event_status = event_status_from_news(event.sources, previous_status)
        event_rows.append({
            "Event ID": event.event_id, "Event Title": event.title, "Event Type": event.event_type,
            "Business Lines": ", ".join(event.business_lines), "Primary Entity IDs": ", ".join(entity.entity_id for entity in event.entities),
            "Strategic Candidate": "yes" if event.strategic_candidate else "no", "First Seen At": cell_text(previous.get("First Seen At")) or now,
            "Event Date": event.event_date, "Status": event_status, "Priority Candidate": event.priority_candidate,
            "Final Priority": cell_text(previous.get("Final Priority")) or "None", "P0 Approval Status": cell_text(previous.get("P0 Approval Status")) or "Not requested",
            "Confidence": str(event.confidence), "Relevance Score": str(event.overall_score), "Summary": event.summary,
            "GBSS Impact Hypothesis": event.impact_hypothesis, "Limitations": event.limitations,
            "Primary Source URL": {"text": primary.source_domain or primary.url, "link": primary.url}, "Publish Date": primary.publish_date,
            "Source Count": str(len(event.sources)), "Accepted News Count": str(accepted_news_count),
            "Reviewer": cell_text(previous.get("Reviewer")), "Reviewed At": cell_text(previous.get("Reviewed At")),
            "Daily Report Sent At": cell_text(previous.get("Daily Report Sent At")), "Weekly Headlines Sent At": cell_text(previous.get("Weekly Headlines Sent At")), "Weekly Intelligence Sent At": cell_text(previous.get("Weekly Intelligence Sent At")),
            "Event Version": sha1("|".join(sorted(source.news_record_id for source in event.sources)).encode("utf-8")).hexdigest()[:12], "Updated At": now,
        })
        for entity in event.entities:
            relation_id = f"event-entity-{sha1(f'{event.event_id}|{entity.entity_id}'.encode()).hexdigest()[:16]}"
            entity_rows.append({"Event Entity ID": relation_id, "Event ID": event.event_id, "Entity ID": entity.entity_id, "Role": "primary" if entity == event.entities[0] else "related", "Match Method": "catalog_alias_or_domain", "Confidence": str(event.confidence), "Created At": now})
        for index, source in enumerate(event.sources):
            relation_id = f"event-source-{sha1(f'{event.event_id}|{source.news_record_id}|{source.url}'.encode()).hexdigest()[:16]}"
            source_rows.append({"Event Source ID": relation_id, "Event ID": event.event_id, "News Record ID": source.news_record_id, "Source URL": {"text": source.source_domain or source.url, "link": source.url}, "Source Domain": source.source_domain, "Publish Date": source.publish_date, "Source Grade": source.source_grade, "Source Excerpt": source.source_excerpt, "Is Primary Source": "yes" if index == 0 else "no", "Evidence Value": "core" if index == 0 else "supporting", "Provider": source.provider, "Duplicate Of": "", "Content Hash": sha1(normalize_url(source.url).encode()).hexdigest(), "Created At": now})
            if source.news_record_id:
                news_updates.append({"id": source.news_record_id, "fields": {"Event Case ID": event.event_id, "Entity Candidates": ", ".join(entity.entity_id for entity in event.entities), "LLM Processed At": now}})
            if index == 0:
                evidence_id = f"evidence-{sha1(f'{event.event_id}|{source.url}'.encode()).hexdigest()[:16]}"
                evidence_rows.append({"Evidence ID": evidence_id, "Research ID": f"event:{event.event_id}", "Event ID": event.event_id, "Event Source IDs": relation_id, "Source Record ID": source.news_record_id, "Source URL": {"text": source.source_domain or source.url, "link": source.url}, "Source Title": source.title, "Publisher": source.source_domain, "Published Date": source.publish_date, "Source Tier": source.source_grade, "Source Type": "event primary source", "Extracted Fact": source.source_excerpt or source.title, "Metric": "", "Scope / Boundary": event.limitations, "Business Relevance": ", ".join(event.business_lines), "Impacted Capability": "", "Supports / Challenges": "Candidate support", "Confidence": "High" if event.confidence >= 0.8 else "Medium", "Reviewer Status": "Pending", "Reviewer Notes": "Verify the retained source excerpt against the linked official page before approving the event claim.", "Captured At": now})
                claim_rows.append({"Claim ID": f"claim-{event.event_id}", "Research ID": f"event:{event.event_id}", "Event ID": event.event_id, "Claim Text": event.summary, "Claim Type": "Fact", "Evidence IDs": evidence_id, "Counter-evidence / Boundary": event.limitations, "GBSS Relevance": event.impact_hypothesis, "Strategic Theme": ", ".join(event.business_lines), "Confidence": "Medium", "Report Placement": "Event Case", "Impact Level": "High" if event.strategic_candidate else "Standard", "Reviewer Status": "Draft", "Reviewer Notes": "Approve only after Evidence verification.", "Updated At": now})
        score_rows.append({"Event Score ID": f"score-{event.event_id}", "Event ID": event.event_id, "Source Grade Score": str(event.scores["source_grade"]), "Entity Match Score": str(event.scores["entity_match"]), "Event Severity Score": str(event.scores["event_severity"]), "Business Line Fit Score": str(event.scores["business_line_fit"]), "Novelty Score": str(event.scores["novelty"]), "Market Confirmation Score": str(event.scores["market_confirmation"]), "Overall Score": str(event.overall_score), "Scoring Reason": json.dumps(event.scores, ensure_ascii=False), "Scoring Version": "v3.1.0", "Model": "deterministic", "Prompt Version": "none", "Scored At": now, "Human Override": ""})
    _upsert(settings, tables.event_cases, "Event ID", event_rows, existing_records=existing_event_records)
    _upsert(settings, tables.event_entities, "Event Entity ID", entity_rows, existing_records=existing_entity_records)
    stale_entity_updates = superseded_entity_relation_updates(existing_entity_records, entity_rows)
    if stale_entity_updates:
        result = update_records(settings.dingtalk, tables.event_entities, stale_entity_updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    _upsert(settings, tables.event_sources, "Event Source ID", source_rows, existing_records=existing_sources)
    _upsert(settings, tables.event_scores, "Event Score ID", score_rows, preserve_nonempty=("Human Override",))
    if settings.dingtalk_ai_table.evidence_bank_sheet_id:
        evidence_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.evidence_bank_sheet_id})
        _upsert(settings, evidence_table, "Evidence ID", evidence_rows, preserve_when_reviewed=("Extracted Fact", "Metric", "Scope / Boundary", "Business Relevance", "Impacted Capability", "Supports / Challenges", "Confidence", "Reviewer Status", "Reviewer Notes"), review_field="Reviewer Status", unlocked_statuses=("", "pending"))
    if settings.dingtalk_ai_table.claim_ledger_sheet_id:
        claim_table = settings.dingtalk_ai_table.model_copy(update={"sheet_id": settings.dingtalk_ai_table.claim_ledger_sheet_id})
        _upsert(settings, claim_table, "Claim ID", claim_rows, preserve_when_reviewed=("Claim Text", "Claim Type", "Evidence IDs", "Counter-evidence / Boundary", "GBSS Relevance", "Strategic Theme", "Confidence", "Report Placement", "Impact Level", "Reviewer Status", "Reviewer Notes"), review_field="Reviewer Status", unlocked_statuses=("", "draft", "pending"))
    if news_updates:
        result = update_records(settings.dingtalk, settings.dingtalk_ai_table, news_updates)
        if result.status != "sent":
            raise RuntimeError(result.message)
    return len(event_rows)


def archive_stale_pending_events(settings: AppSettings, tables: EventIntelligenceTables, active_event_ids: Iterable[str], cutoff_date: date) -> int:
    active = set(active_event_ids)
    updates = []
    for record in list_records(settings.dingtalk, tables.event_cases):
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        if not event_id or event_id in active or cell_text(fields.get("Status")) != "待处理" or cell_text(fields.get("Reviewer")):
            continue
        observed = parse_date(fields.get("Publish Date"))
        if not observed:
            continue
        try:
            if date.fromisoformat(observed) < cutoff_date:
                continue
        except ValueError:
            continue
        updates.append({"id": record["id"], "fields": {"Status": "已归档", "Limitations": "Archived by idempotent backfill reconciliation because the event no longer satisfies current v3.1 rules."}})
    if not updates:
        return 0
    result = update_records(settings.dingtalk, tables.event_cases, updates)
    if result.status != "sent":
        raise RuntimeError(result.message)
    return len(result.record_ids)


def superseded_event_updates(
    event_records: Sequence[Dict[str, Any]],
    event_source_records: Sequence[Dict[str, Any]],
    news_records: Sequence[Dict[str, Any]],
    active_event_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    active = set(active_event_ids)
    news_targets = {
        str(record.get("id") or ""): cell_text((record.get("fields") or {}).get("Event Case ID"))
        for record in news_records
        if record.get("id")
    }
    source_news_by_event: Dict[str, set[str]] = {}
    for record in event_source_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        news_id = cell_text(fields.get("News Record ID"))
        if event_id and news_id:
            source_news_by_event.setdefault(event_id, set()).add(news_id)
    updates = []
    for record in event_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        if not event_id or event_id in active:
            continue
        source_news_ids = source_news_by_event.get(event_id) or set()
        targets = {news_targets.get(news_id, "") for news_id in source_news_ids}
        if not source_news_ids or "" in targets or len(targets) != 1:
            continue
        target = next(iter(targets))
        if target not in active or target == event_id:
            continue
        updates.append({"id": record["id"], "fields": {
            "Status": "已归档",
            "Merged Into Event ID": target,
            "Limitations": f"Superseded by canonical Event merge into {target}; retained for audit history.",
        }})
    return updates


def archive_superseded_events(settings: AppSettings, tables: EventIntelligenceTables, active_event_ids: Iterable[str]) -> int:
    event_records = list_records(settings.dingtalk, tables.event_cases)
    source_records = list_records(settings.dingtalk, tables.event_sources)
    news_records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = superseded_event_updates(event_records, source_records, news_records, active_event_ids)
    if not updates:
        return 0
    result = update_records(settings.dingtalk, tables.event_cases, updates)
    if result.status != "sent":
        raise RuntimeError(result.message)
    return len(result.record_ids)


def terminal_event_status_updates(
    event_records: Sequence[Dict[str, Any]],
    event_source_records: Sequence[Dict[str, Any]],
    news_records: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    news_status = {
        str(record.get("id") or ""): cell_text((record.get("fields") or {}).get("Status") or (record.get("fields") or {}).get("Review Status"))
        for record in news_records
        if record.get("id")
    }
    source_news_by_event: Dict[str, set[str]] = {}
    for record in event_source_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        news_id = cell_text(fields.get("News Record ID"))
        if event_id and news_id:
            source_news_by_event.setdefault(event_id, set()).add(news_id)
    updates = []
    for record in event_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        current = cell_text(fields.get("Status"))
        if not event_id or current == "已归档":
            continue
        source_ids = source_news_by_event.get(event_id) or set()
        statuses = [news_status.get(news_id, "") for news_id in source_ids]
        if not statuses:
            continue
        if "已采纳" in statuses:
            desired = "已采纳"
        elif any(status in {"", "待处理"} for status in statuses):
            desired = "待处理"
        elif all(status in {"已拒绝", "已重复"} for status in statuses):
            desired = "已归档" if all(status == "已重复" for status in statuses) else "已拒绝"
        else:
            continue
        if desired != current:
            updates.append({"id": record["id"], "fields": {"Status": desired}})
    return updates


def reconcile_terminal_event_statuses(settings: AppSettings, tables: EventIntelligenceTables) -> int:
    event_records = list_records(settings.dingtalk, tables.event_cases)
    source_records = list_records(settings.dingtalk, tables.event_sources)
    news_records = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = terminal_event_status_updates(event_records, source_records, news_records)
    if not updates:
        return 0
    result = update_records(settings.dingtalk, tables.event_cases, updates)
    if result.status != "sent":
        raise RuntimeError(result.message)
    return len(result.record_ids)


def stale_ai_rejected_event_updates(
    event_records: Sequence[Dict[str, Any]],
    event_source_records: Sequence[Dict[str, Any]],
    news_records: Sequence[Dict[str, Any]],
    last_completed_review_date: date,
) -> List[Dict[str, Any]]:
    news_fields = {str(record.get("id") or ""): record.get("fields") or {} for record in news_records if record.get("id")}
    source_news_by_event: Dict[str, set[str]] = {}
    for record in event_source_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        news_id = cell_text(fields.get("News Record ID"))
        if event_id and news_id:
            source_news_by_event.setdefault(event_id, set()).add(news_id)
    updates = []
    for record in event_records:
        fields = record.get("fields") or {}
        event_id = cell_text(fields.get("Event ID"))
        if (
            not event_id
            or cell_text(fields.get("Status")) != "待处理"
            or cell_text(fields.get("Event Type")) not in {"General", "Market_Context"}
            or cell_text(fields.get("Strategic Candidate")).lower() in {"yes", "true", "1"}
            or cell_text(fields.get("Priority Candidate")) == "P0_Candidate"
        ):
            continue
        source_ids = source_news_by_event.get(event_id) or set()
        linked = [news_fields.get(news_id) for news_id in source_ids]
        if not linked or any(item is None for item in linked):
            continue
        dates = [parse_date(item.get("Publish Date")) for item in linked if item is not None]
        if not dates or any(not value for value in dates):
            continue
        if any(date.fromisoformat(value) > last_completed_review_date for value in dates if value):
            continue
        if not all(
            cell_text(item.get("Status") or item.get("Review Status")) in {"", "待处理"}
            and cell_text(item.get("AI Status")) == "已拒绝"
            for item in linked
            if item is not None
        ):
            continue
        updates.append({"id": record["id"], "fields": {"Status": "已归档"}})
    return updates


def archive_stale_ai_rejected_events(settings: AppSettings, tables: EventIntelligenceTables, last_completed_review_date: date) -> int:
    events = list_records(settings.dingtalk, tables.event_cases)
    sources = list_records(settings.dingtalk, tables.event_sources)
    news = list_records(settings.dingtalk, settings.dingtalk_ai_table)
    updates = stale_ai_rejected_event_updates(events, sources, news, last_completed_review_date)
    if not updates:
        return 0
    result = update_records(settings.dingtalk, tables.event_cases, updates)
    if result.status != "sent":
        raise RuntimeError(result.message)
    return len(result.record_ids)


def validate_final_p0(fields: Dict[str, Any]) -> bool:
    if cell_text(fields.get("Final Priority")) != "P0":
        return True
    return cell_text(fields.get("P0 Approval Status")) == "Approved" and bool(cell_text(fields.get("Reviewer"))) and bool(cell_text(fields.get("Reviewed At")))


def publication_eligible(event_fields: Dict[str, Any], accepted_news_count: Optional[int] = None) -> bool:
    source = event_fields.get("Primary Source URL")
    source_url = source.get("link") if isinstance(source, dict) else source
    if accepted_news_count is None:
        try:
            accepted_news_count = int(float(cell_text(event_fields.get("Accepted News Count")) or 0))
        except ValueError:
            accepted_news_count = 0
    return accepted_news_count >= 1 and bool(source_url) and bool(cell_text(event_fields.get("Publish Date"))) and validate_final_p0(event_fields)
