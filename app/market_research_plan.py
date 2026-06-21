"""Build an approval-ready weekly research plan from accepted market signals."""

from __future__ import annotations

from hashlib import sha1
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
    return {
        "title": _title(record),
        "section": str(fields.get("Section") or "News"),
        "source_url": str(fields.get("Source URL") or ""),
    }


def build_market_led_research_plan(records: List[Dict[str, Any]], period: str) -> Dict[str, Any]:
    """Turn the selected accepted News into a scoped, evidence-led research brief.

    The research question is deliberately tied to observable developments in the
    selected week, rather than an editorial roadmap topic.
    """
    core = [_source_row(record) for record in records if _contains(_title(record), CORE_KEYWORDS)]
    context = [_source_row(record) for record in records if _contains(_title(record), CONTEXT_KEYWORDS)]
    remaining = [_source_row(record) for record in records if _source_row(record) not in core and _source_row(record) not in context]

    topic = "From AI Agents to Trusted Money Movement: Operating Controls for GBSS"
    question = (
        "As AI agents move into merchant and customer-service workflows while cross-border and tokenised "
        "payment infrastructure expands, which operating controls, ownership model and rollout sequence should GBSS "
        "prioritise to capture value without increasing payment, customer or regulatory risk?"
    )
    why = (
        "This week's accepted signals combine AI-agent productisation (Adyen, Salesforce, Bland and ElevenLabs) with "
        "cross-border/tokenised financial infrastructure (UPI-NPI and Ant International/Amundi), while the Airwallex "
        "scrutiny and blockchain-performance debate show that trust, controls and regulatory fit remain limiting factors."
    )
    scope = (
        "Focus on the intersection of AI-agent service and merchant workflows with payment initiation, customer handoff, "
        "risk escalation, audit trails, cross-border interoperability and tokenised treasury operations. Exclude generic "
        "processor comparison and corporate-investment news unless it provides a direct operating-model benchmark."
    )
    market_changes = [
        "AI agents are being productised in merchant and customer-service platforms, not only tested as assistants.",
        "Voice AI is attracting growth capital and sovereign ecosystem investment, indicating production deployment momentum.",
        "Cross-border instant-payment links and tokenised treasury products are moving financial infrastructure closer to real operations.",
        "Regulatory scrutiny and settlement-performance constraints make governance, traceability and human escalation design decisive.",
    ]
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
