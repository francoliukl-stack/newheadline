"""Build an approval-ready weekly research plan from accepted market signals."""

from __future__ import annotations

from hashlib import sha1
from collections import Counter
from typing import Any, Dict, Iterable, List


CORE_KEYWORDS = (
    "agentic", "agentforce", " ai ", "voice ai", "elevenlabs", "salesforce", "bland",
    "payment", "payments", "upi", "token", "blockchain", "treasury", "airwallex", "adyen",
)
CONTEXT_KEYWORDS = ("paypal", "worldpay", "nuvei", "gambling")


def _title(record: Dict[str, Any]) -> str:
    return str((record.get("fields") or {}).get("Title") or "").strip()


def _contains(title: str, keywords: Iterable[str]) -> bool:
    lowered = f" {title.lower()} "
    return any(keyword in lowered for keyword in keywords)


def _source_row(record: Dict[str, Any]) -> Dict[str, str]:
    fields = record.get("fields") or {}
    raw_url = fields.get("Source URL") or ""
    source_url = str(raw_url.get("link") or raw_url.get("text") or "") if isinstance(raw_url, dict) else str(raw_url)
    return {
        "title": _title(record),
        "section": str(fields.get("Section") or "News"),
        "event_type": str(fields.get("Label") or fields.get("Event Type") or ""),
        "source_url": source_url,
    }


def build_market_led_research_plan(records: List[Dict[str, Any]], period: str) -> Dict[str, Any]:
    """Turn the selected accepted News into a scoped, evidence-led research brief.

    The research question is deliberately tied to observable developments in the
    selected week, rather than an editorial roadmap topic.
    """
    rows = [_source_row(record) for record in records]
    typed = any(row["event_type"] for row in rows)
    if typed:
        context = [row for row in rows if row["event_type"] in {"General", "Market_Context"}]
        core = [row for row in rows if row not in context]
    else:
        core = [row for row in rows if _contains(row["title"], CORE_KEYWORDS)]
        context = [row for row in rows if row not in core and _contains(row["title"], CONTEXT_KEYWORDS)]
    remaining = [row for row in rows if row not in core and row not in context]

    type_counts = Counter(row["event_type"] for row in core if row["event_type"])
    payment_governance_count = sum(type_counts[name] for name in ("Market_Expansion", "Regulatory", "Channel_Partner", "Pricing_Fee"))
    service_ai_count = sum(type_counts[name] for name in ("Capability_Tech", "Product_Launch", "Ops_Incident"))
    if typed and payment_governance_count >= max(2, service_ai_count):
        topic = "Cross-Border Payment Expansion and Ecosystem Governance: Implications for GBSS"
        question = (
            "How do this week's payment-network expansion, regulatory-access and ecosystem-governance events change the "
            "competitive and operating requirements for Alipay+, WorldFirst, Antom and GBSS over the next 30–90 days?"
        )
        scope = (
            "Focus on cross-border acceptance, payment-network interoperability, regulatory market access, partner governance, "
            "merchant/customer operations and the capabilities GBSS must monitor. Treat leadership or service-AI events as "
            "supporting benchmarks unless they directly change payment execution or operating controls."
        )
    else:
        topic = "From AI-Enabled Service to Trusted Money Movement: Operating Priorities for GBSS"
        question = (
            "Which observable product, service, payment and governance changes this week should alter GBSS operating priorities, "
            "ownership or control design over the next 30–90 days?"
        )
        scope = (
            "Focus on accepted Event Cases with direct implications for service operations, merchant support, payment execution, "
            "risk escalation, auditability and supplier governance; exclude generic commentary without an observable trigger."
        )
    headline_evidence = "; ".join(row["title"] for row in core[:5]) or "No typed core Event was accepted."
    why = f"This week's accepted Event Cases include {headline_evidence} The research should test whether these are isolated announcements or evidence of a broader operating shift."
    change_by_type = {
        "Market_Expansion": "Cross-border payment networks are extending geographic reach or acceptance, creating concrete interoperability and servicing questions.",
        "Regulatory": "Regulatory access and policy expectations are changing market-entry, compliance or bank-partner requirements.",
        "Channel_Partner": "Payment and technology firms are using councils, partners and ecosystem programmes to influence standards and distribution.",
        "Product_Launch": "New products are moving from announcement into deployable payment or service capabilities.",
        "Capability_Tech": "Service-AI capabilities are becoming operational benchmarks for workforce, customer handoff and governance.",
        "Leadership_Change": "Leadership changes may signal execution or product-priority shifts but require corroborating evidence before strategic interpretation.",
        "Strategic_MA": "Capital and M&A moves may reshape competitive scale, distribution or capability ownership.",
    }
    market_changes = [change_by_type[name] for name, _count in type_counts.most_common() if name in change_by_type]
    if not market_changes:
        market_changes = ["Accepted signals show observable external changes, but their common mechanism still requires research validation."]
    source_titles = "|".join(row["title"] for row in core)
    research_id = "market-" + sha1(f"{period}|{source_titles}".encode("utf-8")).hexdigest()[:12]
    topic_record = {
        "id": research_id,
        "fields": {
            "Topic ID": research_id,
            "Publish Date": period,
            "Status": "Locked",
            "Topic": topic,
            "Research Question": question,
            "Why It Matters": why,
            "Scope": scope,
            "Source Signals": "; ".join(market_changes),
            "Owner": "GBSS Strategy / Ops",
        },
    }
    return {
        "topic_record": topic_record,
        "period": period,
        "topic": topic,
        "question": question,
        "why": why,
        "scope": scope,
        "market_changes": market_changes,
        "core_sources": core,
        "context_sources": context,
        "secondary_sources": remaining,
    }


def build_chatgpt_manual_research_handoff(plan: Dict[str, Any]) -> Dict[str, Any]:
    core_titles = [row["title"] for row in plan.get("core_sources", []) if row.get("title")]
    context_titles = [row["title"] for row in plan.get("context_sources", []) if row.get("title")]
    directions = [
        {
            "name": "市场机制与竞合格局",
            "question": plan["question"],
            "focus": "识别本周事件改变了哪些支付、跨境资金或 AI 服务市场机制，并区分短期新闻与结构性变化。",
        },
        {
            "name": "竞对动作与能力差距",
            "question": "这些事件分别反映了主要竞对怎样的产品、渠道、监管或运营能力变化？GBSS 与其相比有哪些可验证的能力差距？",
            "focus": "按 Alipay+、WorldFirst、Antom、香港金融科技和 GBSS Service 分组，避免泛化竞品点评。",
        },
        {
            "name": "GBSS 运营影响与下一步验证",
            "question": "哪些变化可能影响 GBSS 的客服、支付运营、风险升级、供应商治理或能力建设？未来 30–90 天应验证哪些指标？",
            "focus": "只提出有来源支撑的影响假设，明确 owner、观察指标、触发条件和不确定性。",
        },
        {
            "name": "反证、边界与不行动条件",
            "question": "有哪些反例、部署限制、监管边界或缺失指标，可能推翻本周最强的战略判断？",
            "focus": "为每个重要结论提供至少一个反证或边界，不把单一新闻升级为确定性战略结论。",
        },
    ]
    def source_line(row: Dict[str, str]) -> str:
        return f"- [{row['title']}]({row['source_url']})" if row.get("source_url") else f"- {row['title']}"

    sources = "\n".join(source_line(row) for row in plan.get("core_sources", [])) or "- 以 Research Queue 和关联 Event Sources 为准"
    context = "\n".join(source_line(row) for row in plan.get("context_sources", [])) or "- 无额外背景信号"
    direction_text = "\n".join(
        f"{index}. {item['name']}\n   核心问题：{item['question']}\n   研究重点：{item['focus']}"
        for index, item in enumerate(directions, 1)
    )
    prompt = f"""请使用 ChatGPT Deep Research 完成一份 GBSS Weekly Insight。

研究周期：{plan['period']}
主研究主题：{plan['topic']}
主问题：{plan['question']}
Why now：{plan['why']}
范围：{plan['scope']}

建议研究方向：
{direction_text}

本周核心 Event/新闻：
{sources}

仅作背景的信号：
{context}

输出要求：
1. Executive Summary：3–5 条有证据支撑的结论。
2. What changed：按 Event 描述事实、日期、实体和来源链接。
3. Business implications：分别映射 Alipay+、WorldFirst、Antom、Ant Bank HK/AlipayHK、GBSS Service。
4. Counter-evidence & limitations：每个高影响判断至少给出一个反证、边界或缺失数据。
5. 30–90 day watchlist：指标、触发条件和建议 owner；没有证据时明确写“待验证”。
6. 所有重要事实附可点击来源；区分事实、推断和假设；不得自动定性最终 P0。
7. 生成适合钉钉文档阅读的中文报告，保留必要英文产品名和机构名。
"""
    return {"directions": directions, "prompt": prompt, "plan": direction_text}
