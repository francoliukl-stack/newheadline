from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


BusinessPriority = str
StrategicTheme = str
CapabilityArea = str
PriorityLevel = str

BUSINESS_PRIORITIES = ["ePOS", "Antom", "WorldFirst", "General GBSS Ops"]
STRATEGIC_THEMES = [
    "Business Support",
    "Organization Transformation",
    "OPC & Operating Model",
    "Internal Efficiency",
    "Contact Center Insight",
    "Governance & Vendor Strategy",
]
CAPABILITY_AREAS = [
    "AICC",
    "AIQC",
    "AI QA",
    "Voice AI",
    "Contact Center",
    "Service Automation",
    "Merchant Ops",
    "KYC / KYB",
    "Vendor Management",
    "Agent Ops",
    "OPC",
    "Risk & Compliance",
]

SIGNAL_DOMAINS = [
    "Business & Payment Ops",
    "Contact Center AI",
    "Voice AI / Realtime AI",
    "AI QA / AIQC / WEM",
    "OPC Model",
    "Agentic Service & Automation",
    "Governance / Risk / Compliance",
    "Vendor / Funding Signal",
]

SCORING_MODEL = {
    "dimensions": [
        {
            "name": "Business Criticality",
            "weight": 0.25,
            "description": "Impact on ePOS, Antom, WorldFirst or other key GBSS business support priorities.",
        },
        {
            "name": "GBSS Strategic Relevance",
            "weight": 0.20,
            "description": "Alignment with Organization Transformation, OPC, Internal Efficiency, Contact Center Insight or Governance & Vendor Strategy.",
        },
        {
            "name": "Contact Center Relevance",
            "weight": 0.15,
            "description": "Relevance to Contact Center, Voice AI, AIQC, AICC, CCaaS, WEM, Agent Assist or Service Automation.",
        },
        {
            "name": "Actionability",
            "weight": 0.15,
            "description": "Can be turned into research, PoC, process improvement, vendor evaluation or capability building within 1-2 quarters.",
        },
        {
            "name": "Operating Model Impact",
            "weight": 0.10,
            "description": "Impact on organization structure, OPC units, small-team ownership, A2A readiness or human + AI workforce.",
        },
        {
            "name": "Risk / Compliance Impact",
            "weight": 0.10,
            "description": "Impact on data security, authorization, auditability, compliance, performance fairness or customer experience.",
        },
        {
            "name": "Industry Signal Strength",
            "weight": 0.05,
            "description": "Backed by major players, funding, regulation, customer case or strategic partnership.",
        },
    ],
    "priorityRules": [
        {"scoreRange": "85+", "priority": "P0 Candidate", "meaning": "Requires human review before any final P0 decision."},
        {"scoreRange": "70-84", "priority": "P1", "meaning": "Should enter research, PoC or benchmarking."},
        {"scoreRange": "50-69", "priority": "P2", "meaning": "Keep observing, no immediate action."},
        {"scoreRange": "<50", "priority": "Watch", "meaning": "Record trend only."},
    ],
}

DOMAIN_KEYWORDS = {
    "Business & Payment Ops": (
        "payment", "payments", "merchant", "antom", "worldfirst", "epos", "pos",
        "cross-border", "onboarding", "kyc", "kyb", "stripe", "visa", "mastercard",
        "wise", "payoneer", "airwallex", "checkout",
    ),
    "Contact Center AI": (
        "contact center", "ccaas", "agent assist", "customer service", "service cloud",
        "zendesk", "intercom", "genesys", "nice", "five9", "talkdesk", "amazon connect",
        "conversation intelligence", "knowledge management",
    ),
    "Voice AI / Realtime AI": (
        "voice ai", "voice", "realtime", "real-time", "speech", "low latency",
        "deepgram", "polyai", "retell", "elevenlabs", "speechmatics", "outbound",
        "inbound",
    ),
    "AI QA / AIQC / WEM": (
        "qa", "quality", "aiqc", "ai qa", "wem", "wfo", "workforce", "speech analytics",
        "calabrio", "verint", "observe.ai", "quality assurance", "performance",
    ),
    "OPC Model": (
        "opc", "one person company", "small team", "ownership", "accountability",
        "workforce", "human + ai", "a2a", "operating model", "agent ops",
    ),
    "Agentic Service & Automation": (
        "agent", "agentic", "automation", "copilot", "workflow", "case automation",
        "service automation", "classification", "root cause",
    ),
    "Governance / Risk / Compliance": (
        "risk", "compliance", "governance", "audit", "security", "authorization",
        "regulated", "privacy", "cross-border data", "kyc", "kyb", "fraud",
    ),
    "Vendor / Funding Signal": (
        "funding", "raises", "investment", "partnership", "partner", "acquire",
        "acquisition", "launch", "vendor", "nvidia", "fortanix",
    ),
}


def field_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("link") or "")
    if isinstance(value, list):
        return ", ".join(field_text(item) for item in value if field_text(item))
    return str(value or "")


def source_url(fields: Dict[str, Any]) -> str:
    value = fields.get("Source URL") or {}
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "")
    return str(value or "")


def source_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().removeprefix("www.") or url


def record_title(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    return field_text(fields.get("Title") or fields.get("Title & URL") or "-")


def record_publish_date(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    value = fields.get("Publish Date") or fields.get("First Seen At") or ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return str(value)
    text = field_text(value).strip()
    if not text:
        return "-"
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text) / 1000).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return text
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def record_text(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    values = [
        fields.get("Title"),
        fields.get("Title & URL"),
        fields.get("Label"),
        fields.get("Tag"),
        fields.get("Section"),
        fields.get("Source"),
        fields.get("Source Domain"),
        source_url(fields),
    ]
    return " ".join(field_text(value) for value in values).lower()


def truncate_text(text: Any, max_length: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - 3)].rstrip(" .,;:，。") + "..."


METRIC_PATTERN = re.compile(
    r"(?:[$€£]\s?\d+(?:\.\d+)?\s?(?:B|M|bn|mn|million|billion)?"
    r"|\d+(?:\.\d+)?\s?%|\+\d+(?:\.\d+)?\s?%"
    r"|\d+\+?\s?(?:markets|users|countries|customers)"
    r"|FY20\d{2}|Q[1-4]\s?20\d{2}|TPV\s?[$€£]?\s?\d+(?:\.\d+)?\s?(?:B|M)?)",
    re.IGNORECASE,
)

TAKEAWAY_ENTITIES = (
    "Nuvei", "Payoneer", "Revolut", "Airwallex", "Wise", "XTransfer",
    "Stripe", "Visa", "Mastercard", "OpenAI", "Deepgram", "Fortanix",
    "Nvidia", "Aethexai", "Antom", "WorldFirst", "NICE", "Genesys",
    "Intercom", "Salesforce", "Amazon Connect", "PolyAI", "Retell",
)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def infer_business_relevance(record: Dict[str, Any]) -> List[BusinessPriority]:
    text = record_text(record)
    relevance: List[BusinessPriority] = []
    if _contains_any(text, ("epos", "pos", "merchant terminal", "merchant service", "store")):
        relevance.append("ePOS")
    if _contains_any(text, ("antom", "payment", "payments", "merchant onboarding", "kyc", "kyb", "agentic commerce", "visa", "stripe", "mastercard")):
        relevance.append("Antom")
    if _contains_any(text, ("worldfirst", "cross-border", "b2b", "global", "smb", "treasury", "payout")):
        relevance.append("WorldFirst")
    if not relevance or _contains_any(text, ("contact center", "voice ai", "aiqc", "opc", "vendor", "governance", "service automation")):
        relevance.append("General GBSS Ops")
    return list(dict.fromkeys(relevance))


def infer_signal_domain(record: Dict[str, Any]) -> str:
    text = record_text(record)
    scores = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        scores.append((sum(1 for keyword in keywords if keyword in text), domain))
    scores.sort(reverse=True)
    return scores[0][1] if scores and scores[0][0] > 0 else "Vendor / Funding Signal"


def infer_strategic_theme(record: Dict[str, Any]) -> StrategicTheme:
    text = record_text(record)
    domain = infer_signal_domain(record)
    if domain == "OPC Model":
        return "OPC & Operating Model"
    if domain in {"Contact Center AI", "Voice AI / Realtime AI"}:
        return "Contact Center Insight"
    if domain in {"AI QA / AIQC / WEM", "Agentic Service & Automation"}:
        return "Internal Efficiency"
    if domain == "Governance / Risk / Compliance":
        return "Governance & Vendor Strategy"
    if _contains_any(text, ("organization", "workforce", "role", "training", "team", "human + ai")):
        return "Organization Transformation"
    return "Business Support"


def infer_capabilities(record: Dict[str, Any]) -> List[CapabilityArea]:
    text = record_text(record)
    capabilities: List[CapabilityArea] = []
    checks = [
        ("AICC", ("aicc", "service orchestration", "workflow", "case", "routing")),
        ("AIQC", ("aiqc", "quality", "qa", "score", "speech analytics")),
        ("AI QA", ("ai qa", "quality assurance", "review", "appeal")),
        ("Voice AI", ("voice", "speech", "realtime", "deepgram", "polyai", "retell")),
        ("Contact Center", ("contact center", "ccaas", "agent assist", "customer service")),
        ("Service Automation", ("automation", "copilot", "agent", "workflow", "classification")),
        ("Merchant Ops", ("merchant", "onboarding", "case follow-up", "epos", "antom")),
        ("KYC / KYB", ("kyc", "kyb", "onboarding", "risk review")),
        ("Vendor Management", ("vendor", "bpo", "outsourcing", "managed service", "supplier")),
        ("Agent Ops", ("agent ops", "agent monitoring", "ai ops", "agentic")),
        ("OPC", ("opc", "one person company", "small team", "a2a", "ownership")),
        ("Risk & Compliance", ("risk", "compliance", "audit", "security", "regulated", "fraud")),
    ]
    for capability, keywords in checks:
        if _contains_any(text, keywords):
            capabilities.append(capability)
    return capabilities or ["Service Automation"]


def calculate_priority_score(record: Dict[str, Any]) -> int:
    text = record_text(record)
    business_relevance = infer_business_relevance(record)
    capabilities = infer_capabilities(record)
    theme = infer_strategic_theme(record)
    domain = infer_signal_domain(record)
    scores = {
        "Business Criticality": 90 if any(item in business_relevance for item in ("ePOS", "Antom", "WorldFirst")) else 65,
        "GBSS Strategic Relevance": 90 if theme in STRATEGIC_THEMES else 50,
        "Contact Center Relevance": 90 if any(item in capabilities for item in ("Contact Center", "Voice AI", "AIQC", "AI QA", "AICC")) else 45,
        "Actionability": 85 if any(item in capabilities for item in ("AICC", "AIQC", "Voice AI", "Service Automation", "Vendor Management")) else 60,
        "Operating Model Impact": 90 if theme in {"OPC & Operating Model", "Organization Transformation"} or "OPC" in capabilities else 45,
        "Risk / Compliance Impact": 85 if "Risk & Compliance" in capabilities or _contains_any(text, ("risk", "compliance", "regulated", "audit", "security", "kyc", "kyb")) else 45,
        "Industry Signal Strength": 85 if _contains_any(text, ("visa", "stripe", "openai", "nvidia", "genesys", "nice", "salesforce", "amazon", "funding", "raises", "partnership")) or domain == "Vendor / Funding Signal" else 60,
    }
    weighted = 0.0
    for dimension in SCORING_MODEL["dimensions"]:
        weighted += scores[dimension["name"]] * float(dimension["weight"])
    if "Risk & Compliance" in capabilities and "Voice AI" in capabilities:
        weighted += 8
    if "Antom" in business_relevance and "Service Automation" in capabilities and _contains_any(text, ("agent", "openai", "programmable", "payment")):
        weighted += 8
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        weighted += 10
    return int(round(weighted))


def derive_priority(score: int) -> PriorityLevel:
    if score >= 85:
        return "P0 Candidate"
    if score >= 70:
        return "P1"
    if score >= 50:
        return "P2"
    return "Watch"


def gbss_scenarios(record: Dict[str, Any]) -> List[str]:
    capabilities = infer_capabilities(record)
    scenarios = []
    if "Merchant Ops" in capabilities or "KYC / KYB" in capabilities:
        scenarios.append("Merchant onboarding / KYC / case follow-up")
    if "Contact Center" in capabilities or "AICC" in capabilities:
        scenarios.append("AICC / agent assist / service orchestration")
    if "AIQC" in capabilities or "AI QA" in capabilities:
        scenarios.append("AIQC / QA review / vendor performance")
    if "Voice AI" in capabilities:
        scenarios.append("Inbound / outbound voice AI and real-time assist")
    if "OPC" in capabilities or "Vendor Management" in capabilities:
        scenarios.append("OPC Model / small-unit ownership / A2A readiness")
    if "Risk & Compliance" in capabilities:
        scenarios.append("Risk, compliance, auditability and authorization")
    return scenarios or ["General service automation and operating efficiency"]


def build_priority_news_card(record: Dict[str, Any]) -> Dict[str, Any]:
    score = calculate_priority_score(record)
    fields = record.get("fields") or {}
    explicit_priority = str(fields.get("Final Priority") or fields.get("Priority Candidate") or "").strip()
    priority = explicit_priority if explicit_priority in {"P0", "P0_Candidate", "P0 Candidate", "P1", "P2", "Watch"} else derive_priority(score)
    if priority == "P0_Candidate":
        priority = "P0 Candidate"
    title = record_title(record)
    business_relevance = infer_business_relevance(record)
    strategic_theme = infer_strategic_theme(record)
    capabilities = infer_capabilities(record)
    scenarios = gbss_scenarios(record)
    source_url_value = source_url(fields)
    return {
        "priority": priority,
        "score": score,
        "newsTitle": title,
        "publishDate": record_publish_date(record),
        "whatHappened": truncate_text(title, 150),
        "whyItMattersToGBSS": "该信号需要从 GBSS 业务支持、Contact Center 能力、OPC 模式和 AI 治理角度判断是否进入下一步调研或 PoC。",
        "businessRelevance": business_relevance,
        "businessImpactSummary": business_impact_summary(business_relevance),
        "strategicTheme": strategic_theme,
        "impactedCapability": capabilities,
        "efficiencyOpportunity": efficiency_opportunity(capabilities),
        "operatingModelImplication": operating_model_implication(strategic_theme, capabilities),
        "strategicLink": [strategic_theme] + [capability for capability in capabilities[:3]],
        "suggestedAction": suggested_action(strategic_theme, capabilities),
        "suggestedOwner": suggested_owner(strategic_theme, capabilities),
        "timeline": suggested_timeline(priority),
        "gbssRelevantScenarios": scenarios,
        "source": source_link(record),
        "sourceUrl": source_url_value,
        "eventId": field_text(fields.get("Event ID")),
        "eventSourceIds": field_text(fields.get("Event Source IDs")),
        "evidenceIds": field_text(fields.get("Evidence IDs")),
        "claimIds": field_text(fields.get("Claim IDs")),
        "limitations": field_text(fields.get("Limitations")),
    }


def executive_takeaway_subject(title: str) -> str:
    clean = " ".join(str(title or "").replace("–", "-").split())
    matched = [entity for entity in TAKEAWAY_ENTITIES if entity.lower() in clean.lower()]
    if len(matched) >= 2:
        return " × ".join(matched[:3])
    if matched:
        return matched[0]
    for separator in (":", " - ", " | "):
        if separator in clean:
            subject = clean.split(separator, 1)[0].strip()
            if 2 <= len(subject) <= 70:
                return subject
    words = clean.split()
    return " ".join(words[: min(6, len(words))]).rstrip(".,;:") or "External signal"


def executive_takeaway_verdict(card: Dict[str, Any]) -> str:
    theme = card.get("strategicTheme") or ""
    capabilities = card.get("impactedCapability") or []
    relevance = card.get("businessRelevance") or []
    title = str(card.get("newsTitle") or "")
    lower_title = title.lower()
    if any(word in lower_title for word in ("acquire", "acquisition", "deal", "merger")):
        return "Deal signal confirmed"
    if any(word in lower_title for word in ("valuation", "ipo", "raises", "funding", "annual report", "revenue", "arr", "tpv")):
        return "Scale and capital signal"
    if any(word in lower_title for word in ("launch", "unveils", "enables", "partners", "alliance")):
        return "Capability expansion signal"
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        return "Operating model signal"
    if "Voice AI" in capabilities or "Contact Center" in capabilities:
        return "Contact Center AI signal"
    if any(item in relevance for item in ("Antom", "WorldFirst", "ePOS")):
        return "Business support signal"
    return "Strategic weak signal"


def executive_takeaway_impact(card: Dict[str, Any]) -> Tuple[str, str]:
    relevance = card.get("businessRelevance") or []
    capabilities = card.get("impactedCapability") or []
    theme = card.get("strategicTheme") or ""
    if "WorldFirst" in relevance:
        return (
            "Potentially relevant to WorldFirst's cross-border service, SMB support and B2B operating model.",
            "对 WorldFirst 的跨境服务、SMB 支持和 B2B 运营模式有潜在参考价值。",
        )
    if "Antom" in relevance:
        return (
            "Potentially relevant to Antom merchant onboarding, payment support, KYC/KYB and case follow-up.",
            "对 Antom 的商户入驻、支付支持、KYC/KYB 和 case follow-up 有潜在参考价值。",
        )
    if "ePOS" in relevance:
        return (
            "Potentially relevant to Merchant Service / ePOS support, issue triage and service response.",
            "对 Merchant Service / ePOS 的服务支持、问题分流和响应效率有潜在参考价值。",
        )
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        return (
            "This supports the OPC Model direction: smaller accountable units with clear ownership, metrics and A2A-ready interfaces.",
            "这支持 OPC Model 方向：用更小的责任单元承接目标、指标和 A2A-ready 协作接口。",
        )
    if "Voice AI" in capabilities or "Contact Center" in capabilities:
        return (
            "This can inform GBSS Voice AI, Contact Center AI and AIQC production-readiness decisions.",
            "可用于判断 GBSS Voice AI、Contact Center AI 和 AIQC 的生产可用性。",
        )
    return (
        "Track as a management-level signal for GBSS business support, efficiency and governance roadmap.",
        "建议作为 GBSS 业务支持、效率提升和治理路线的管理层信号持续跟踪。",
    )


def build_executive_takeaways(cards: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, str]]:
    takeaways: List[Dict[str, str]] = []
    for card in cards[:limit]:
        title = str(card.get("newsTitle") or "-")
        subject = executive_takeaway_subject(title)
        metrics = METRIC_PATTERN.findall(title)
        metric_text = "; ".join(dict.fromkeys(item.strip() for item in metrics if item.strip()))
        date_text = card.get("publishDate") or "-"
        verdict = executive_takeaway_verdict(card)
        impact_en, impact_cn = executive_takeaway_impact(card)
        metric_sentence = f" Key metrics: {metric_text}." if metric_text else ""
        takeaways.append({
            "subject": subject,
            "priority": str(card.get("priority") or "Watch"),
            "publishDate": str(date_text),
            "en": (
                f"{subject}: {verdict}. Published {date_text}. "
                f"{truncate_text(title, 170)}.{metric_sentence} {impact_en}"
            ),
            "zh": (
                f"{subject}：{verdict}。发布时间 {date_text}。"
                f"{truncate_text(title, 120)}。{impact_cn}"
            ),
        })
    return takeaways


def business_impact_summary(relevance: List[str]) -> str:
    if any(item in relevance for item in ("ePOS", "Antom", "WorldFirst")):
        return "May improve merchant/customer support, onboarding, case follow-up and service response. 可提升重点业务的商户/客户支持、入驻、case follow-up 和服务响应。"
    return "May improve shared GBSS operating efficiency, quality governance or vendor management. 可提升 GBSS 共享运营效率、质量治理或供应商管理。"


def efficiency_opportunity(capabilities: List[str]) -> str:
    if "Voice AI" in capabilities:
        return "Can support low-risk inbound/outbound calls, real-time assist and AIQC linkage. 可用于低风险呼入/外呼、实时辅助、通话小结和 AIQC 联动。"
    if "AIQC" in capabilities or "AI QA" in capabilities:
        return "Can support full-volume QA, human review, fatal error detection and appeal governance. 可用于全量质检、人工复核、fatal error 识别、申诉和供应商绩效治理。"
    if "AICC" in capabilities or "Service Automation" in capabilities:
        return "Can improve routing, knowledge recommendation, case classification and root-cause analysis. 可用于智能分流、知识推荐、case classification、root cause analysis 和流程追踪。"
    if "Vendor Management" in capabilities or "OPC" in capabilities:
        return "Can turn 1-3 person teams into accountable OPC units for goals, process, quality and Agent collaboration. 可将 1-3 人小团队沉淀为最小经营单元，承担目标、流程、质量和 Agent 协同结果。"
    return "Can serve as a weak signal for GBSS efficiency benchmarking. 可作为 GBSS 内部效率项目或能力对标的弱信号。"


def operating_model_implication(theme: str, capabilities: List[str]) -> str:
    if theme in {"OPC & Operating Model", "Organization Transformation"} or "OPC" in capabilities:
        return "OPC should be designed as 1-3 person operating units with clear goals, outcomes and Agent collaboration. OPC 应被设计为 1-3 人小经营单元，围绕目标、能力、结果和 Agent 协同独立运转。"
    if "AIQC" in capabilities or "Voice AI" in capabilities:
        return "Team roles may shift from execution to designing, monitoring and governing AI + human operations. 团队职责会从执行服务流程转向设计、监控、治理和优化 AI + human 运行体系。"
    return "Collaboration boundaries should be clarified across business, AI Enablement and Contact Center Ops. 需要明确业务团队、AI Enablement 和 Contact Center Ops 的协作边界。"


def suggested_action(theme: str, capabilities: List[str]) -> str:
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        return "启动 OPC Model 设计，明确 1-3 人小经营单元的边界、指标、协作机制和 A2A readiness。"
    if "Voice AI" in capabilities:
        return "更新 Voice AI Vendor Radar，筛选 1-2 个低风险场景进入 PoC 设计。"
    if "AIQC" in capabilities or "AI QA" in capabilities:
        return "补齐 AIQC 准确率、复核、申诉、fatal error 和供应商绩效规则。"
    if "AICC" in capabilities or "Service Automation" in capabilities:
        return "将能力映射到 AICC 升级路线，形成服务编排能力 gap list。"
    if theme == "Governance & Vendor Strategy":
        return "建立 AI vendor governance checklist，覆盖安全、审计、授权、合规和稳定性。"
    return "输出业务支持场景 mapping，判断是否进入调研、PoC 或能力建设。"


def suggested_owner(theme: str, capabilities: List[str]) -> str:
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        return "GBSS Strategy + AI Enablement + Ops Leads"
    if "Voice AI" in capabilities:
        return "AI Enablement + Contact Center Ops + Business Ops"
    if "AIQC" in capabilities or "AI QA" in capabilities:
        return "AI Enablement + QA + Vendor Management"
    if "AICC" in capabilities:
        return "AI Enablement + AICC Product + Contact Center Ops"
    if theme == "Governance & Vendor Strategy":
        return "AI Enablement + Risk / Compliance + Vendor Management"
    return "GBSS Strategy / Biz Ops"


def suggested_timeline(priority: str) -> str:
    if priority in {"P0", "P0 Candidate"}:
        return "1-2 weeks"
    if priority == "P1":
        return "2-4 weeks"
    return "Next review cycle"


def source_link(record: Dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    url = source_url(fields)
    if not url:
        return source_domain(field_text(fields.get("Source") or fields.get("Source Domain")))
    return "[{}]({})".format(source_domain(url), url)


def brief_gbss_relevance(card: Dict[str, Any]) -> str:
    capabilities = card.get("impactedCapability") or []
    theme = card.get("strategicTheme") or ""
    if theme == "OPC & Operating Model" or "OPC" in capabilities:
        return "Clarifies OPC unit ownership and A2A-ready boundaries. 明确 OPC 单元责任与 A2A-ready 协作边界。"
    if "Voice AI" in capabilities:
        return "Supports regulated voice service and AIQC linkage. 支持合规语音服务与 AIQC 联动。"
    if "AICC" in capabilities or "Service Automation" in capabilities:
        return "Improves routing, knowledge and case automation. 提升分流、知识推荐和 case 自动化。"
    if "Risk & Compliance" in capabilities:
        return "Strengthens auditability, authorization and governance. 强化审计、授权和治理能力。"
    return "Helps define GBSS business support priorities. 帮助判断 GBSS 业务支持优先级。"


def build_signal_radar(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[infer_signal_domain(record)].append(record)
    rows: List[Dict[str, Any]] = []
    for domain in SIGNAL_DOMAINS:
        domain_records = grouped.get(domain, [])
        if not domain_records:
            continue
        cards = [build_priority_news_card(record) for record in domain_records]
        priorities = Counter(card["priority"] for card in cards)
        top_card = sorted(cards, key=lambda card: (-card["score"], card["newsTitle"]))[0]
        business = []
        scenarios = []
        for card in cards:
            business.extend(card["businessRelevance"])
            scenarios.extend(card["gbssRelevantScenarios"])
        rows.append({
            "domain": domain,
            "signalCount": len(domain_records),
            "representativeEvents": [truncate_text(record_title(record), 70) for record in domain_records[:3]],
            "businessRelevance": list(dict.fromkeys(business)),
            "gbssRelevantScenarios": list(dict.fromkeys(scenarios))[:4],
            "strategicTheme": top_card["strategicTheme"],
            "priority": max(priorities, key=lambda item: ("Watch", "P2", "P1", "P0 Candidate", "P0").index(item)),
            "initialJudgement": top_card["whyItMattersToGBSS"],
        })
    return rows


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P0 Candidate": 1, "P1": 2, "P2": 3, "Watch": 4}.get(priority, 5)


def build_priority_cards(records: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    cards = [build_priority_news_card(record) for record in records]
    cards.sort(key=lambda card: (priority_rank(card["priority"]), -int(card["score"]), card["newsTitle"]))
    return cards[:limit]


def build_impact_analysis(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "strategicTheme": "Business Support",
            "externalTrend": "Payment, merchant service and agentic automation signals are increasing.",
            "businessImpact": "ePOS / Antom / WorldFirst 需要更稳定、更智能的商户入驻、服务响应和 case follow-up 能力。",
            "operatingModelImpact": "前台服务、业务运营和中台流程需要更紧密协同。",
            "efficiencyImpact": "可沉淀 Merchant Support automation、case classification 和知识推荐机会。",
            "currentJudgement": "P1",
            "suggestedAction": "输出重点业务服务能力缺口清单。",
        },
        {
            "strategicTheme": "Organization Transformation",
            "externalTrend": "AI is reshaping service, QA, training and operations roles.",
            "businessImpact": "重点业务支持会更依赖 AI + human 协同和 Agent Ops 运行机制。",
            "operatingModelImpact": "团队需要从职能分工转向以小经营单元承担端到端结果。",
            "efficiencyImpact": "需要建立 Agent Ops / AI Ops、AIQC 复核、知识治理和单元经营能力。",
            "currentJudgement": "P0 Candidate",
            "suggestedAction": "设计 AI 影响下的组织转型路径。",
        },
        {
            "strategicTheme": "OPC & Operating Model",
            "externalTrend": "AI and A2A are pushing service teams toward smaller accountable operating units.",
            "businessImpact": "Merchant Service / ePOS、Antom、WorldFirst 需要更清晰的最小责任单元承接服务结果。",
            "operatingModelImpact": "OPC Model 应把 1-3 人小团队作为最小经营单元，负责目标、流程、质量和 AI/Agent 协同。",
            "efficiencyImpact": "AIQC、异常处理、Agent 监控、知识维护和流程优化可沉淀到 OPC 单元的日常经营动作。",
            "currentJudgement": "P0 Candidate",
            "suggestedAction": "设计 GBSS OPC Model operating blueprint。",
        },
        {
            "strategicTheme": "Internal Efficiency",
            "externalTrend": "AICC, AIQC, Voice AI and Service Automation are converging into one efficiency portfolio.",
            "businessImpact": "可提升重点业务服务响应、一次解决率、商户体验和跨境客户支持效率。",
            "operatingModelImpact": "人员从重复处理转向复杂问题、异常兜底和 AI 运行监控。",
            "efficiencyImpact": "AICC + AIQC + Voice AI 可形成组合式效率提升项目。",
            "currentJudgement": "P1",
            "suggestedAction": "形成 AICC + AIQC + Voice AI 效率项目组合图。",
        },
        {
            "strategicTheme": "Contact Center Insight",
            "externalTrend": "CCaaS is shifting from agent assist to AI-native service orchestration.",
            "businessImpact": "对全球服务能力建设和重点业务支持有直接参考。",
            "operatingModelImpact": "需要提升 Contact Center 产品化、知识治理和 AI 编排能力。",
            "efficiencyImpact": "AICC 升级应参考识别、分流、辅助、质检、复盘和优化全链路。",
            "currentJudgement": "P1",
            "suggestedAction": "输出 Contact Center 行业能力对标。",
        },
        {
            "strategicTheme": "Governance & Vendor Strategy",
            "externalTrend": "AI governance becomes critical in regulated service and payment scenarios.",
            "businessImpact": "Antom / WorldFirst / ePOS 均涉及合规、审计、授权和客户体验风险。",
            "operatingModelImpact": "供应商选择需要纳入治理、安全、稳定性、可追溯和复核能力。",
            "efficiencyImpact": "AI 项目开量必须有审计、授权、人工复核和异常处理机制。",
            "currentJudgement": "P0 Candidate",
            "suggestedAction": "建立 AI vendor governance checklist。",
        },
    ]


def build_actions() -> List[Dict[str, Any]]:
    return [
        {
            "priority": "P0 Candidate",
            "action": "启动 OPC Model operating blueprint",
            "businessRelevance": ["General GBSS Ops"],
            "strategicTheme": "OPC & Operating Model",
            "owner": "GBSS Strategy + AI Enablement + Ops Leads",
            "timeline": "2-4 weeks",
            "expectedOutput": "OPC unit blueprint",
            "status": "Not Started",
        },
        {
            "priority": "P1",
            "action": "输出 AICC + AIQC + Voice AI 效率项目组合图",
            "businessRelevance": ["ePOS", "Antom", "WorldFirst"],
            "strategicTheme": "Internal Efficiency",
            "owner": "AI Enablement",
            "timeline": "2 weeks",
            "expectedOutput": "Efficiency Portfolio",
            "status": "Not Started",
        },
        {
            "priority": "P1",
            "action": "梳理 ePOS / Antom / WorldFirst 服务能力缺口",
            "businessRelevance": ["ePOS", "Antom", "WorldFirst"],
            "strategicTheme": "Business Support",
            "owner": "OE + Business Ops",
            "timeline": "2 weeks",
            "expectedOutput": "Business Support Gap Map",
            "status": "Not Started",
        },
        {
            "priority": "P1",
            "action": "更新 Voice AI Vendor Radar",
            "businessRelevance": ["General GBSS Ops"],
            "strategicTheme": "Contact Center Insight",
            "owner": "AI Enablement + Contact Center Ops",
            "timeline": "1 week",
            "expectedOutput": "Vendor Radar",
            "status": "In Progress",
        },
    ]


def build_watchlist() -> List[Dict[str, Any]]:
    return [
        {
            "topic": "OPC Model",
            "focus": "行业中是否存在小经营单元、mini-P&L、two-pizza team、DRI / owner model 等最佳实践",
            "businessRelevance": ["General GBSS Ops"],
            "strategicTheme": "OPC & Operating Model",
            "whyItMatters": "可为 GBSS 设计 1-3 人 OPC 最小经营单元、责任接口和 A2A-ready 协作机制提供参考。",
            "triggerCondition": "若出现可复用的 owner model / operating unit 案例，进入 P0 blueprint。",
        },
        {
            "topic": "Contact Center AI",
            "focus": "NICE / Genesys / Intercom / Salesforce 是否发布 AI orchestration 能力",
            "businessRelevance": ["ePOS", "Antom", "WorldFirst"],
            "strategicTheme": "Contact Center Insight",
            "whyItMatters": "影响 AICC 升级方向。",
            "triggerCondition": "若能力可借鉴，进入平台差距分析。",
        },
        {
            "topic": "Voice AI",
            "focus": "是否出现金融级 production 案例",
            "businessRelevance": ["ePOS", "Antom", "WorldFirst"],
            "strategicTheme": "Internal Efficiency",
            "whyItMatters": "影响呼入 / 外呼 PoC 设计。",
            "triggerCondition": "若出现同类场景案例，进入供应商评估。",
        },
        {
            "topic": "AIQC / WEM",
            "focus": "绩效、合规、申诉相关最佳实践",
            "businessRelevance": ["General GBSS Ops"],
            "strategicTheme": "Internal Efficiency",
            "whyItMatters": "影响 AIQC 开量规则设计。",
            "triggerCondition": "若出现成熟案例，纳入规则设计。",
        },
    ]


def build_deep_dive() -> Dict[str, Any]:
    return {
        "topic": "AI 时代 OPC Model 如何把 1-3 人小团队升级为 A2A-ready 经营单元",
        "relatedBusinessPriority": ["ePOS", "Antom", "WorldFirst", "General GBSS Ops"],
        "relatedStrategicTheme": ["OPC & Operating Model", "Organization Transformation", "Internal Efficiency"],
        "background": "GBSS 的 OPC Model 是 One Person Company 的组织经营理念：把一个人或 2-3 人小团队作为最小经营单元，围绕清晰目标、服务结果、流程质量和 AI/Agent 协同独立运转。",
        "externalSignals": [
            "AI Agent 和 A2A 协作会要求团队有更清晰的责任边界、输入输出和结果指标。",
            "行业最佳实践可重点参考 small accountable teams、DRI / owner model、mini-P&L、two-pizza team 和 product squad 等组织机制。",
            "Contact Center 平台从坐席工具转向 AI-native service orchestration。",
            "Voice AI、AIQC 和 AICC 的成熟，使服务单元可以从执行任务升级为经营流程、质量和自动化能力。",
        ],
        "whyItMattersToGBSS": "GBSS 同时支持 Merchant Service / ePOS、Antom、WorldFirst，又要提升组织效率和应对 AI 带来的组织转型；OPC Model 可以把业务支持、质量、流程和 AI/Agent 协同沉淀到最小经营单元，为后续 A2A 模式打基础。",
        "impactOnCurrentStrategy": [
            {"area": "Business Support", "impact": "重点业务需要更稳定、更智能、更可扩展的服务支持能力。"},
            {"area": "OPC Model", "impact": "1-3 人小团队需要像小公司一样经营目标、服务结果、质量和效率。"},
            {"area": "A2A Readiness", "impact": "每个 OPC 单元需要具备清晰输入输出，便于未来与 Agent 或其他单元协同。"},
        ],
        "internalEfficiencyLink": "AICC、AIQC、Voice AI 和 Service Automation 可以共同构成新的 AI-enabled service operating model。",
        "operatingModelImplication": "OPC 单元职责应从被动执行任务，升级为主动经营目标、流程、服务质量、异常处理、知识维护和 Agent 协同效率。",
        "keyRisks": [
            "如果 OPC 单元边界不清晰，A2A 协作会缺少稳定的责任接口。",
            "如果只按个人任务管理，而不是按小经营单元管理，AI 提效难以转化为业务结果。",
            "如果指标只看产能不看质量、异常和知识沉淀，OPC 单元会退化为执行小组。",
        ],
        "opportunities": [
            "把 1-3 人小团队沉淀为面向业务结果的最小经营单元。",
            "将 OPC 管理从任务分配升级为目标、质量、效率和能力经营。",
            "为 Merchant Service / ePOS、Antom、WorldFirst 提供更稳定、更可扩展的服务支持能力。",
        ],
        "recommendedActions": [
            "定义 OPC 单元的最小粒度：一个人或 2-3 人小团队，对应明确业务场景和结果指标。",
            "梳理每个 OPC 单元的输入、输出、Owner、质量指标、异常处理边界和协作接口。",
            "将 AIQC 复核、Agent 监控、异常处理、知识维护纳入 OPC 单元的经营动作。",
            "形成 AICC + AIQC + Voice AI + OPC + A2A readiness 的协同运营蓝图。",
        ],
        "next30DayStep": "完成一版 GBSS OPC Model Blueprint，覆盖 Merchant Service / ePOS、Antom、WorldFirst 重点业务支持，明确每个 OPC 单元的目标、边界、指标、AI/Agent 协同方式和 A2A readiness。",
        "managementTakeaway": "AI 时代 GBSS 的核心挑战不是单点工具落地，而是把团队拆解并升级为面向业务结果、质量和 Agent 协同的 OPC 最小经营单元。",
    }


def build_executive_summary(records: List[Dict[str, Any]], range_label: str, topic: str) -> Dict[str, Any]:
    cards = [build_priority_news_card(record) for record in records]
    priority_summary = Counter(card["priority"] for card in cards)
    business_relevant = [card for card in cards if any(item in card["businessRelevance"] for item in ("ePOS", "Antom", "WorldFirst"))]
    contact_center = [card for card in cards if "Contact Center" in card["impactedCapability"] or "Voice AI" in card["impactedCapability"]]
    op_model = [card for card in cards if card["strategicTheme"] == "OPC & Operating Model" or "OPC" in card["impactedCapability"]]
    return {
        "reportTitle": "GBSS Weekly AI & Service Intelligence",
        "reportingPeriod": range_label,
        "weeklyTopic": topic or "AI is reshaping Contact Center operating model and business support capability",
        "oneSentenceConclusion": "AI is not only a tool upgrade for GBSS; it reshapes business support, OPC Model, org ownership and Contact Center efficiency. AI 对 GBSS 不只是工具升级，而是同时影响重点业务支持、OPC Model、组织分工和 Contact Center 效率体系。",
        "signalCount": len(records),
        "businessRelevantSignalCount": len(business_relevant),
        "contactCenterSignalCount": len(contact_center),
        "opModelSignalCount": len(op_model),
        "prioritySummary": {
            "P0": priority_summary.get("P0", 0),
            "P0 Candidate": priority_summary.get("P0 Candidate", 0),
            "P1": priority_summary.get("P1", 0),
            "P2": priority_summary.get("P2", 0),
            "Watch": priority_summary.get("Watch", 0),
        },
        "businessImpactHighlights": [
            "ePOS 可优先关注商户服务自动化、问题分流和低风险语音场景。",
            "Antom 可关注 merchant onboarding、KYC / KYB、case follow-up 和 agentic service automation。",
            "WorldFirst 可借鉴跨境服务、全球客服和 Contact Center AI 的效率提升实践。",
        ],
        "gbssCoreImpacts": [
            "OPC Model should evolve into small accountable operating units for business result, quality and A2A readiness.",
            "AICC, AIQC and Voice AI should be managed as one efficiency improvement portfolio.",
            "Contact Center industry is moving from agent assist to AI-native service orchestration.",
        ],
        "organizationInsight": "AI 正在重定义服务、质检、培训和运营团队的角色边界。",
        "contactCenterInsight": "Contact Center 正从 seat-based efficiency tools 转向 AI-native service orchestration。",
        "managementTakeaway": "GBSS should use OPC Model to build small accountable units for business result, quality and AI/Agent collaboration. GBSS 需要用 OPC Model 把团队升级为面向业务结果、质量和 AI/Agent 协同的小经营单元。",
    }


def generate_one_page_brief(report_data: Dict[str, Any]) -> Dict[str, Any]:
    summary = report_data.get("executiveSummary") or {}
    cards = report_data.get("priorityNewsCards") or []
    impacts = report_data.get("impactAnalysis") or []
    actions = report_data.get("actions") or []
    deep_dive = report_data.get("deepDive") or {}
    phrases = deep_dive.get("phrases") or []
    business_counts = {key: 0 for key in BUSINESS_PRIORITIES}
    for card in cards:
        for item in card.get("businessRelevance") or []:
            if item in business_counts:
                business_counts[item] += 1
    top_priorities = [
        {
            "priority": card.get("priority", "Watch"),
            "signal": truncate_text(card.get("newsTitle", "-"), 180),
            "publishDate": card.get("publishDate", "-"),
            "gbssRelevance": brief_gbss_relevance(card),
            "sourceUrl": card.get("sourceUrl", ""),
            "eventId": card.get("eventId", ""),
            "eventSourceIds": card.get("eventSourceIds", ""),
            "evidenceIds": card.get("evidenceIds", ""),
            "claimIds": card.get("claimIds", ""),
        }
        for card in cards[:10]
    ]
    return {
        "title": "GBSS Weekly AI & Service Intelligence | One-page Brief",
        "reportingPeriod": summary.get("reportingPeriod", "-"),
        "weeklyTheme": {
            "topic": summary.get("weeklyTopic", "-"),
            "oneSentenceJudgement": summary.get("oneSentenceConclusion", "-"),
            "managementTakeaway": summary.get("managementTakeaway", "-"),
        },
        "businessSignalRadar": {
            "merchantServiceSignals": business_counts["ePOS"],
            "antomSignals": business_counts["Antom"],
            "worldFirstSignals": business_counts["WorldFirst"],
            "contactCenterSignals": summary.get("contactCenterSignalCount", 0),
            "opModelSignals": summary.get("opModelSignalCount", 0),
            "prioritySummary": summary.get("prioritySummary", {}),
        },
        "topPriorities": top_priorities,
        "gbssStrategicImpact": [
            {
                "theme": item.get("strategicTheme", "-"),
                "impact": truncate_text(item.get("businessImpact") or item.get("efficiencyImpact"), 220),
                "priority": item.get("currentJudgement", "P2"),
            }
            for item in impacts[:6]
        ],
        "actions": [
            {
                "priority": item.get("priority", "P2"),
                "action": truncate_text(item.get("action"), 60),
                "owner": truncate_text(item.get("owner"), 42),
                "output": truncate_text(item.get("expectedOutput"), 42),
            }
            for item in actions[:3]
        ],
        "weeklyDeepInsight": {
            "insight": truncate_text(
                " | ".join(str(item) for item in phrases) or deep_dive.get("managementTakeaway") or deep_dive.get("background") or "No weekly deep insight is available.",
                260,
            ),
            "whyNow": truncate_text(
                deep_dive.get("whyItMattersToGBSS") or deep_dive.get("background") or "No supporting rationale is available.",
                280,
            ),
            "next30DayMove": truncate_text(
                deep_dive.get("next30DayStep") or "Refresh the research evidence and review open claims.",
                300,
            ),
        },
    }


def _research_field(record: Dict[str, Any], name: str) -> str:
    return field_text((record.get("fields") or record).get(name)).strip()


def _research_url(record: Dict[str, Any], name: str = "Source URL") -> str:
    value = (record.get("fields") or record).get(name)
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "")
    return str(value or "")


def _research_quality(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict((context or {}).get("quality") or {})


def _research_priority_cards(records: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = context.get("evidence") or []
    evidence_by_source = {
        _research_field(item, "Source Record ID"): item
        for item in evidence
        if _research_field(item, "Source Record ID")
    }
    cards: List[Dict[str, Any]] = []
    for record in records:
        source_id = str(record.get("id") or "")
        evidence_row = evidence_by_source.get(source_id)
        base = build_priority_news_card(record)
        if evidence_row:
            reviewer_status = _research_field(evidence_row, "Reviewer Status").lower()
            tier = _research_field(evidence_row, "Source Tier") or "T3"
            fact = _research_field(evidence_row, "Extracted Fact") or base["whatHappened"]
            confidence = _research_field(evidence_row, "Confidence") or "Low"
            base["whatHappened"] = fact
            base["publishDate"] = _research_field(evidence_row, "Published Date") or base["publishDate"]
            base["source"] = _research_url(evidence_row) or base["source"]
            base["evidenceId"] = _research_field(evidence_row, "Evidence ID")
            base["sourceTier"] = tier
            base["confidence"] = confidence
            base["whyItMattersToGBSS"] = (
                "Evidence is verified and ready for claim review. 已验证证据可进入 Claim Ledger 审核。"
                if reviewer_status == "verified"
                else "Evidence is a candidate pending source-text verification. 该证据仍待核验，不能作为确定性结论。"
            )
            if reviewer_status != "verified":
                base["priority"] = "P2"
            elif base["priority"] in {"P0", "P0 Candidate"}:
                base["priority"] = "P1"
        else:
            base["priority"] = "Watch"
            base["whyItMattersToGBSS"] = "No Evidence Bank record is linked yet. 尚未建立可审核的 Evidence Bank 记录。"
        cards.append(base)
    cards.sort(key=lambda card: (priority_rank(card["priority"]), -int(card["score"]), card["newsTitle"]))
    return cards[:10]


def _research_impact_analysis(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    claims = context.get("claims") or []
    approved = [item for item in claims if _research_field(item, "Reviewer Status").lower() == "approved"]
    rows: List[Dict[str, Any]] = []
    for claim in approved[:6]:
        text = _research_field(claim, "Claim Text")
        theme = _research_field(claim, "Strategic Theme") or "Business Support"
        relevance = _research_field(claim, "GBSS Relevance") or "No direct relevance"
        confidence = _research_field(claim, "Confidence") or "Medium"
        rows.append({
            "strategicTheme": theme,
            "externalTrend": text,
            "businessImpact": relevance,
            "operatingModelImpact": _research_field(claim, "Counter-evidence / Boundary") or "No operating-model claim approved yet.",
            "efficiencyImpact": "Use only after the approved claim is mapped to a named GBSS capability.",
            "currentJudgement": "P1" if confidence in {"High", "Medium"} else "P2",
            "suggestedAction": "Monitor the claim's stated boundary and evidence updates.",
            "claimId": _research_field(claim, "Claim ID"),
            "confidence": confidence,
        })
    if rows:
        return rows
    quality = _research_quality(context)
    return [{
        "strategicTheme": "Research Quality / 研究质量",
        "externalTrend": "No approved claim is available for management impact analysis. 暂无已审批论点可用于管理层影响分析。",
        "businessImpact": "Signal Brief only: GBSS relevance remains under evidence and claim review. 信号简报：GBSS 相关性仍在证据与论点审核中。",
        "operatingModelImpact": "Do not infer organization or OPC implications before claim approval. 在论点获批前，不推断组织或 OPC 影响。",
        "efficiencyImpact": "Do not assign an efficiency opportunity before evidence verification. 在证据验证前，不分配效率提升机会。",
        "currentJudgement": "P2",
        "suggestedAction": "Complete Evidence Bank verification and approve the Claim Ledger before publishing a Deep Research conclusion.",
        "quality": quality.get("status", "Signal Brief"),
    }]


def _research_deep_dive(context: Dict[str, Any], fallback_topic: str) -> Dict[str, Any]:
    research = context.get("research") or {}
    quality = _research_quality(context)
    topic = _research_field(research, "Topic") or fallback_topic
    question = _research_field(research, "Primary Question") or "What changed, why does it matter, and what should GBSS monitor?"
    evidence = context.get("evidence") or []
    claims = context.get("claims") or []
    approved = [item for item in claims if _research_field(item, "Reviewer Status").lower() == "approved"]
    verified = [item for item in evidence if _research_field(item, "Reviewer Status").lower() == "verified"]
    deep_result = context.get("openaiDeepResearch") or {}
    if deep_result.get("status") == "completed" and deep_result.get("content"):
        phrases = [str(item) for item in deep_result.get("phrases") or []][:10]
        synthesis = str(deep_result.get("content") or "")
        takeaway = phrases[0] if phrases else truncate_text(synthesis, 220)
        return {
            "topic": topic,
            "relatedBusinessPriority": ["ePOS", "Antom", "WorldFirst", "General GBSS Ops"],
            "relatedStrategicTheme": ["Business Support", "Contact Center Insight", "Governance & Vendor Strategy"],
            "background": question,
            "externalSignals": phrases,
            "whyItMattersToGBSS": "OpenAI Deep Research completed with web research. Conclusions remain subject to GBSS owner review before execution decisions.",
            "impactOnCurrentStrategy": [{"area": "OpenAI Deep Research", "impact": takeaway}],
            "internalEfficiencyLink": "Use the research output to prioritize evidence-backed GBSS benchmarks and operating-model experiments.",
            "operatingModelImplication": "Review the cited findings with GBSS owners before converting them into operating-model commitments.",
            "keyRisks": ["Model research output requires human review and source validation before execution."],
            "opportunities": ["Use cited external evidence to narrow the next GBSS benchmark or pilot."],
            "recommendedActions": ["Review the Deep Research synthesis and assign owners for the top cited implications."],
            "next30DayStep": "Validate the highest-impact citations and translate approved findings into a GBSS action plan.",
            "managementTakeaway": takeaway,
            "researchStatus": "OpenAI Deep Research",
            "phrases": phrases,
            "researchSynthesis": synthesis,
            "responseId": deep_result.get("response_id", ""),
        }
    if quality.get("deep_research_ready"):
        claim_text = [_research_field(item, "Claim Text") for item in approved[:4] if _research_field(item, "Claim Text")]
        boundaries = [_research_field(item, "Counter-evidence / Boundary") for item in approved if _research_field(item, "Counter-evidence / Boundary")]
        takeaway = claim_text[0] if claim_text else "Approved evidence supports the research thesis."
        return {
            "topic": topic,
            "relatedBusinessPriority": ["ePOS", "Antom", "WorldFirst", "General GBSS Ops"],
            "relatedStrategicTheme": ["Business Support", "Contact Center Insight", "Governance & Vendor Strategy"],
            "background": question,
            "externalSignals": claim_text,
            "whyItMattersToGBSS": "The evidence and approved claims have passed the Deep Research minimum gate; assess only the stated GBSS relevance and boundaries.",
            "impactOnCurrentStrategy": [{"area": "Approved Claims", "impact": item} for item in claim_text],
            "internalEfficiencyLink": "Map approved claims to AICC, AIQC, Voice AI or Service Automation only when the claim specifies that capability.",
            "operatingModelImplication": boundaries[0] if boundaries else "No organization/OPC implication is approved beyond the evidence boundary.",
            "keyRisks": boundaries or ["Continue to monitor source updates and counter-evidence."],
            "opportunities": ["Use approved evidence as a benchmark input, not as a pre-decided implementation recommendation."],
            "recommendedActions": ["Monitor the evidence-defined watch conditions."],
            "next30DayStep": "Refresh the Evidence Pack and reassess approved claims as new primary or independent sources emerge.",
            "managementTakeaway": takeaway,
            "researchStatus": "Deep Research",
        }
    blockers = quality.get("blockers") or ["Research evidence has not reached the publication gate."]
    return {
        "topic": f"Signal Brief / 信号简报: {topic}",
        "relatedBusinessPriority": ["General GBSS Ops"],
        "relatedStrategicTheme": ["Research Quality"],
        "background": question,
        "externalSignals": [_research_field(item, "Source Title") for item in verified[:4] if _research_field(item, "Source Title")],
        "whyItMattersToGBSS": "No verified evidence or approved claim supports a Deep Research conclusion yet. 尚无已验证证据或已审批论点支撑 Deep Research 结论。",
        "impactOnCurrentStrategy": [{"area": "Research Gate", "impact": blocker} for blocker in blockers],
        "internalEfficiencyLink": "No efficiency claim is approved yet. 尚无已审批的效率提升结论。",
        "operatingModelImplication": "No organization or OPC conclusion is approved yet. 尚无已审批的组织或 OPC 结论。",
        "keyRisks": blockers,
        "opportunities": ["Use the Evidence Bank to verify primary sources, metrics, scope and counter-cases before making a strategic inference."],
        "recommendedActions": ["Complete evidence verification and Claim Ledger approval."],
        "next30DayStep": "Verify evidence, approve fact/inference claims and record one boundary. 验证证据、审批事实/推论论点并记录一项边界条件。",
        "managementTakeaway": "Signal activity is visible, but the evidence gate is not yet satisfied; no Deep Research conclusion is asserted. 信号活动已出现，但证据门禁尚未满足，不输出 Deep Research 确定性结论。",
        "researchStatus": "Signal Brief",
    }


def _apply_research_context(report_data: Dict[str, Any], records: List[Dict[str, Any]], context: Dict[str, Any], topic: str) -> None:
    cards = _research_priority_cards(records, context)
    impacts = _research_impact_analysis(context)
    deep_dive = _research_deep_dive(context, topic)
    quality = _research_quality(context)
    summary = report_data["executiveSummary"]
    summary["weeklyTopic"] = _research_field(context.get("research") or {}, "Topic") or topic
    summary["prioritySummary"] = dict(Counter(card["priority"] for card in cards))
    summary["prioritySummary"] = {key: summary["prioritySummary"].get(key, 0) for key in ("P0", "P0 Candidate", "P1", "P2", "Watch")}
    summary["oneSentenceConclusion"] = (
        "This is an evidence-backed Deep Research report based on verified evidence and approved claims."
        if quality.get("deep_research_ready")
        else "This is a Signal Brief: evidence and claims are still under review, so no unverified strategic conclusion is asserted."
    )
    summary["managementTakeaway"] = deep_dive["managementTakeaway"]
    summary["organizationInsight"] = deep_dive["operatingModelImplication"]
    summary["contactCenterInsight"] = "No Contact Center conclusion is asserted unless it is represented by a verified, approved claim."
    report_data["priorityNewsCards"] = cards
    report_data["executiveTakeaways"] = build_executive_takeaways(cards)
    report_data["impactAnalysis"] = impacts
    report_data["actions"] = []
    report_data["watchlist"] = [{
        "topic": "Research Quality Gate",
        "focus": "; ".join(quality.get("blockers") or ["Refresh approved evidence and claims."]),
        "businessRelevance": ["General GBSS Ops"],
        "strategicTheme": "Governance & Vendor Strategy",
        "whyItMatters": "Prevents unsupported research conclusions from entering a CEO report.",
        "triggerCondition": "Publish as Deep Research only when all evidence and claim gates pass.",
    }]
    report_data["deepDive"] = deep_dive
    report_data["researchContext"] = context
    report_data["researchQuality"] = quality



def build_report_data(
    records: List[Dict[str, Any]],
    range_label: str,
    topic: str = "",
    research_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    priority_cards = build_priority_cards(records, limit=10)
    summary = build_executive_summary(records, range_label, topic)
    report_data = {
        "reportTitle": "GBSS Weekly AI & Service Intelligence",
        "reportingPeriod": range_label,
        "executiveSummary": summary,
        "executiveTakeaways": build_executive_takeaways(priority_cards),
        "signalRadar": build_signal_radar(records),
        "priorityNewsCards": priority_cards,
        "impactAnalysis": build_impact_analysis(records),
        "actions": build_actions(),
        "watchlist": build_watchlist(),
        "deepDive": build_deep_dive(),
        "scoringModel": SCORING_MODEL,
    }
    if research_context is not None:
        _apply_research_context(report_data, records, research_context, topic)
    report_data["onePageBrief"] = generate_one_page_brief(report_data)
    return validate_report_data(report_data)


def validate_report_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
    report_data.setdefault("executiveSummary", {})
    report_data.setdefault("executiveTakeaways", [])
    report_data.setdefault("signalRadar", [])
    report_data.setdefault("priorityNewsCards", [])
    report_data.setdefault("impactAnalysis", [])
    report_data.setdefault("actions", [])
    report_data.setdefault("watchlist", [])
    report_data.setdefault("deepDive", build_deep_dive())
    report_data.setdefault("onePageBrief", generate_one_page_brief(report_data))
    return report_data
