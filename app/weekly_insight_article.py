"""Compose the weekly Insight analysis article from this week's Event set.

Replaces the manual ChatGPT Deep Research step: the article is generated from
the same Events the weekly report carries, written to a DingTalk document, and
linked from the report.

Two constraints shape the prompt. Every factual statement must trace to one of
the supplied Events -- the article may not introduce outside facts, because the
evidence chain is the whole reason the report can be trusted. And judgement is
labelled as judgement, so a reader can tell a fact from an inference without
opening the sources (ADR-0002).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .dingtalk_ai_table import cell_text


ARTICLE_MIN_CHARS = 400

BUSINESS_CONTEXT = """GBSS 关注六个业务板块：Alipay+（跨境钱包互联与 QR 互通）、WorldFirst（B2B 跨境金融）、
Bettr（SME 数字金融）、Antom（全球商户收单）、Ant Bank HK / AlipayHK（香港虚拟银行与钱包）、
GBSS Service Capability（Contact Center、AICC、Voice AI、客服自动化与供应商治理）。"""


def _source_url(fields: Dict[str, Any]) -> str:
    raw = fields.get("Source URL")
    url = raw.get("link") if isinstance(raw, dict) else raw
    return str(url or "").strip()


def event_digest(records: Sequence[Dict[str, Any]]) -> List[str]:
    lines = []
    for index, record in enumerate(records, start=1):
        fields = record.get("fields") or {}
        lines.append(
            f"{index}. [{cell_text(fields.get('Label')) or 'General'}] "
            f"{cell_text(fields.get('Title'))}\n"
            f"   业务线: {cell_text(fields.get('Section')) or '-'} | "
            f"发布日: {cell_text(fields.get('Publish Date')) or '-'} | "
            f"来源: {_source_url(fields) or '-'}"
        )
    return lines


def build_article_prompt(records: Sequence[Dict[str, Any]], range_label: str, research_topic: str = "") -> str:
    return "\n".join([
        "你在为 Ant International GBSS 的管理层撰写每周外部事件情报分析。",
        "",
        BUSINESS_CONTEXT,
        "",
        f"本周期：{range_label}",
        f"本周研究主题：{research_topic or '（未指定，请自行从事件中归纳）'}",
        "",
        "本周已通过审核的外部事件如下（这是你唯一可用的事实来源）：",
        *event_digest(records),
        "",
        "写作要求：",
        "1. 只能使用上面列出的事件作为事实依据。禁止引入列表之外的事实、数字或公司动态；",
        "   如果某个判断需要列表之外的信息才能成立，明确写出这是缺口，而不是编造。",
        "2. 区分事实与判断。陈述事件本身用直述；你的推断必须显式标注，并写出该推断在什么条件下会不成立。",
        "3. 面向管理层：回答“这周外部发生了什么、对 GBSS 哪条业务线意味着什么、我们应该注意什么”。",
        "4. 不要罗列全部事件。挑出 2-4 条真正有意义的主线，把相关事件串起来讲，其余可略。",
        "5. 用中文写作。使用 Markdown，包含以下结构：",
        "   # GBSS Weekly Insight — <周期>",
        "   ## 本周主线（2-4 条，每条一个小标题）",
        "   ## 对 GBSS 的影响（按业务线组织，明确标注哪些是推断）",
        "   ## 需要关注的缺口与不确定性",
        "   ## 建议动作（若证据不足以支撑行动建议，就写明不足以支撑，不要凑）",
        "6. 每提到一个事件，在句末用 markdown 链接附上其来源 URL。",
        "",
        "直接输出 Markdown 正文，不要任何前言、解释或代码块包裹。",
    ])


def validate_article(text: str, records: Sequence[Dict[str, Any]]) -> List[str]:
    """Reject an article that would misrepresent its own evidence base."""
    errors: List[str] = []
    body = str(text or "").strip()
    if len(body) < ARTICLE_MIN_CHARS:
        errors.append(f"article is too short to be a weekly analysis ({len(body)} chars)")
    if not body.lstrip().startswith("#"):
        errors.append("article does not start with a markdown heading")
    cited = sum(1 for record in records if _source_url(record.get("fields") or {}) and _source_url(record.get("fields") or {}) in body)
    if records and cited == 0:
        errors.append("article cites none of the supplied event sources")
    return errors


def article_title(range_label: str) -> str:
    return f"GBSS Weekly Insight - {range_label}"
