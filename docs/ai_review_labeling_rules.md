# AI Review Labeling Rules

> Version: 2026-07-11.1
> Last-Updated: 2026-07-11
> Status: active
> Supersedes: none

This file is the pre-review rulebook for `scripts/ai_review_suggest.py`.
Update it only after comparing human `Review Status` with prior `AI Status`.

## Latest Learning Summary

Review snapshot after the July 11 manual review:

- Compared rows with feedback: 67
- Matched: 58
- Overridden: 9
- Agreement: 86.6%
- Main override direction: `AI 已拒绝 -> 人工 已采纳`
- Main gap categories: `Eventization_Gap`, `Event_Type_Underclassified`, `Business_Relevance_Overestimated`

## Experience Rules

1. Accept concrete payment-network expansion even when Eventization is late.
   Examples: bank joins Alipay+ network, QR/PayNow interoperability, cross-border payment infrastructure rollout.

2. Accept major financial market infrastructure announcements even before Event Case linkage is complete.
   Examples: PBOC/HKMA/SFC Hong Kong FIC Trading Platform, live tokenized-payment ledger with major banks.

3. Accept product launches only when the product changes customer, payment, banking, merchant or service capability.
   Generic rankings, buyer guides, alternatives lists and SEO comparison pages are not enough.

4. Reject investment commentary, stock hype, listicles and generic alternatives pages unless they contain a concrete product, market, regulatory or partnership event.

5. Keep hard gates above learned rules: explicit duplicate, missing source URL or missing publish date still block AI acceptance.

## Machine-Readable Rules

`ai_review_suggest.py` reads this JSON block before marking. Keep it valid JSON.

```json
{
  "version": "2026-07-11.1",
  "rules": [
    {
      "id": "accept-alipay-plus-network-expansion",
      "status": "已采纳",
      "confidence": 0.84,
      "title_all": ["alipay+", "network"],
      "title_any": ["joins", "join", "加入", "network"],
      "reason": "人工采纳 Hang Seng Bank joins Alipay+ network；Alipay+ 网络扩展属于新市场/渠道突破，即使 Event Type 尚未识别也应优先进入人工 review。"
    },
    {
      "id": "accept-hk-fic-trading-platform",
      "status": "已采纳",
      "confidence": 0.84,
      "title_any": ["fic trading platform", "fixed income and currency trading platform", "hong kong fic"],
      "reason": "PBOC/HKMA/SFC FIC Trading Platform 属于香港金融基础设施/监管协同事件，人工已采纳；Eventization 不完整时仍应建议采纳。"
    },
    {
      "id": "accept-tokenized-payment-rail",
      "status": "已采纳",
      "confidence": 0.84,
      "title_all": ["payment"],
      "title_any": ["tokenized", "blockchain ledger", "live tokenized payments", "global banks"],
      "reason": "Swift/tokenized payment ledger 这类银行级支付基础设施变化对跨境清结算有研究价值，人工已采纳。"
    },
    {
      "id": "accept-qr-payment-network-rollout",
      "status": "已采纳",
      "confidence": 0.84,
      "title_any": ["paynow gen2", "one qr code", "qris", "cross-border qr", "wallets, qr & rtp"],
      "reason": "QR/钱包/RTP 网络与区域互联属于 Alipay+、Antom 和区域支付体验相关信号，应优先进入人工 review。"
    },
    {
      "id": "reject-generic-payment-alternative-list",
      "status": "已拒绝",
      "confidence": 0.84,
      "title_any": ["best paypal alternatives", "alternatives in india", "vs payoneer vs paypal", "best cross-border payment"],
      "reason": "人工拒绝 PayPal alternatives / comparison list；SEO 排名和泛比较不是外部业务事件。"
    },
    {
      "id": "reject-stock-or-ipo-commentary",
      "status": "已拒绝",
      "confidence": 0.84,
      "title_any": ["rockets $", "stock", "ipo", "hidden gem", "investment"],
      "reason": "人工拒绝股价/IPO/投资观点型内容；除非包含明确财报、监管、产品或市场动作，否则不进入事实型 Daily Report。"
    }
  ]
}
```

## Change Log

- 2026-07-11.1: Added rules from July 11 human review. Main correction: do not reject concrete payment infrastructure or Alipay+ network expansion merely because Event Case is missing or Event Type is General. Added reject rules for alternatives/listicle and investment-commentary false positives.
