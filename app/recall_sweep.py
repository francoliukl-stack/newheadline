"""Weekly Recall Sweep over candidates that daily ingest discarded.

Daily ingest keeps 30 candidates so manual review stays bounded, and the pool
retains the rest. This module scores those retained-but-unselected candidates so
that (a) a handful of event-level leads can be surfaced for human judgement and
(b) the scores feed back into future candidate ranking.

The sweep proposes; it never writes News. INV-03 is unchanged: `News=已采纳`
remains the only publication gate and the only human review entry point.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Sequence


VERDICTS = ("likely_missed", "borderline", "noise")

# Monitoring scope, kept aligned with PRD v3.1 §2. Written into the prompt so a
# sweep judges against the documented business scope rather than a model's prior.
BUSINESS_SCOPE = """GBSS 关注的六个业务板块及其监控对象：
- Alipay+ 跨境移动支付网络、钱包互联、QR 互通。竞对/标杆：WeChat Pay Global, UnionPay International, SGQR, DuitNow, QRIS, PromptPay, GrabPay, PayNow, GCash, Kakao Pay, Touch 'n Go eWallet
- WorldFirst B2B 跨境金融与跨境电商资金服务。竞对：Wise, Payoneer, Airwallex, PingPong, LianLian Global, Currencycloud, Revolut Business
- Bettr SME 数字金融与中小微授信。竞对：Funding Societies, Aspire, Grab Finance, Validus, SeaMoney
- Antom 全球商户收单与支付网关。竞对：Adyen, Stripe, Checkout.com, dLocal, Worldpay, Fiserv, Nuvei, Rapyd, 2C2P
- Ant Bank HK / AlipayHK 香港虚拟银行与钱包。竞对/监管：ZA Bank, Mox Bank, WeLab Bank, Octopus, HSBC PayMe, WeChat Pay HK, HKMA, FPS
- GBSS Service Capability 服务支持能力底座。厂商：Salesforce, Zendesk, Intercom, Genesys, Five9, Talkdesk, NICE, Verint, Calabrio, PolyAI, Retell AI, OpenAI Realtime, Twilio"""


def build_sweep_prompt(candidates: Sequence[Dict[str, Any]]) -> str:
    """Ask a carrier which discarded candidates look like real GBSS-relevant events."""
    lines = []
    for index, row in enumerate(candidates, start=1):
        lines.append(
            f"{index}. title: {row.get('title') or ''}\n"
            f"   domain: {row.get('source_domain') or ''} | date: {row.get('publish_date') or ''} | lane: {row.get('source_lane') or ''}"
        )
    return "\n".join([
        "你在为 Ant International GBSS 的外部事件情报系统做召回补捞。",
        "",
        BUSINESS_SCOPE,
        "",
        "下面是每日采集时因为配额上限而被丢弃的候选条目。请判断其中哪些其实是与上述业务板块相关的真实外部业务事件，因而不应该被丢弃。",
        "",
        "判据：",
        "- likely_missed：确实是上述板块的外部业务事件（监管动作、竞对产品/融资/并购/财报、市场准入、支付事故、重大合作、服务技术厂商动向），被丢弃属于漏报。",
        "- borderline：主题相关但价值存疑，例如泛行业评论、二手转载、信息过薄。",
        "- noise：与 GBSS 无关、实体误匹配（如把 Bettr 匹配成人名 Bettis）、本地生活内容、招揽通稿、SEO 内容农场。",
        "",
        "注意：域名权威性不等于相关性，通稿平台上也可能有真实公司公告。宁可保守，不确定就给 borderline。",
        "",
        "候选列表：",
        *lines,
        "",
        "只输出一个 JSON 数组，不要任何解释文字或 markdown 代码块。每个元素形如：",
        '{"n": 1, "verdict": "likely_missed", "score": 0.85, "reason": "HKMA 监管动作，直接影响 AlipayHK"}',
        "score 为 0 到 1 的相关性置信度。必须为上面每一条候选各输出一个元素。",
    ])


def parse_sweep_response(text: str, candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map a carrier's JSON array back onto candidate URLs.

    Rows the carrier omitted, mislabelled or numbered out of range are dropped
    rather than guessed at, so an unparseable answer under-reports instead of
    inventing verdicts.
    """
    payload = _extract_json_array(text)
    results: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(candidates) or index in seen:
            continue
        verdict = str(item.get("verdict") or "").strip()
        if verdict not in VERDICTS:
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        seen.add(index)
        results.append({
            "url": candidates[index - 1].get("url"),
            "score": min(max(score, 0.0), 1.0),
            "verdict": verdict,
            "reason": str(item.get("reason") or "")[:400],
        })
    return results


def _extract_json_array(text: str) -> List[Any]:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def batched(items: Sequence[Dict[str, Any]], size: int) -> Iterable[Sequence[Dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def stratified_sample(
    scored_rows: Sequence[Dict[str, Any]],
    per_stratum: int,
    high_verdicts: Sequence[str] = ("likely_missed",),
    low_verdicts: Sequence[str] = ("noise",),
) -> Dict[str, List[Dict[str, Any]]]:
    """Split scored rows into a high and a low stratum for labelling.

    Sampling is deterministic (score order, then URL) so the drawn set can be
    reproduced from the pool without storing a random seed.
    """
    high = sorted(
        [row for row in scored_rows if row.get("sweep_verdict") in high_verdicts],
        key=lambda row: (-(row.get("sweep_score") or 0), str(row.get("url"))),
    )
    low = sorted(
        [row for row in scored_rows if row.get("sweep_verdict") in low_verdicts],
        key=lambda row: ((row.get("sweep_score") or 0), str(row.get("url"))),
    )
    return {"high": list(high[:per_stratum]), "low": list(low[:per_stratum])}
