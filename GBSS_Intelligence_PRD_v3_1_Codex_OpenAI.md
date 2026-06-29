# PRD：GBSS 外部事件情报系统（Codex + OpenAI 版）

**版本：** v3.1  
**更新时间：** 2026-06-27  
**系统名称：** Daily Report / Weekly Insight / Event Intelligence
**适用团队：** Ant International GBSS  
**当前生产面：** 当前 workspace 的本地 Python 服务 + macOS launchd + 钉钉 AI 表格业务数据库/文档/群机器人 + SQLite 配置与 RunLog
**目标开发方式：** 使用 Codex 在现有 v2.1 系统基础上增量开发  
**月度预算上限：** 200 RMB/月，建议技术 hard cap 按 25 USD/月配置  
**模型策略：** OpenAI API 为主，不依赖 Gemini 作为生产模型  

---

## 0. 文档定位

本文是对现有 `GBSS AI & Service Intelligence 自动化情报与研究生产系统 v2.1` 的增量升级方案。

v3.1 不推翻现有系统，而是在既有能力基础上新增：

1. **Event Case 层**：把多条新闻聚合为同一外部业务事件。
2. **Entity Catalog 层**：维护业务线、竞对、监管机构、产品、ticker、别名。
3. **OpenAI 结构化分析层**：用低成本模型完成分类、摘要、相关性打分和业务线映射。
4. **轻量商业接口层**：在 200 RMB/月预算内，引入可复用的数据源 adapter。
5. **P0 Candidate 机制**：系统只能提出高优先级候选，最终 P0 必须人工批准。
6. **成本与证据门禁**：所有模型调用、搜索调用、结论输出均可审计、可限流、可回滚。

系统定位不是全网舆情平台，而是：

> 面向 GBSS 的外部业务事件情报系统。它优先捕获对 Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK 以及 GBSS 服务能力有影响的外部事件，并通过人工审核、证据门禁和周度研究输出，帮助 GBSS 更早理解业务变化、竞对动作和运营风险。

---

## 1. 业务目标

### 1.1 根本目标

帮助 Ant International GBSS 团队建立稳定的行业感知能力，使团队能够：

1. 更早捕捉支付、跨境金融、数字银行、钱包、收单、Contact Center 与 AI Service 领域的重要变化。
2. 更好地理解外部事件对 GBSS 服务、运营、流程、风险、供应商、能力建设的潜在影响。
3. 以 Daily Report 和 Weekly Insight 的形式，为管理层提供可追溯、证据驱动、可行动的外部情报。
4. 避免周报退化为“新闻标题 + 泛化观点”，建立从信号到判断再到行动的闭环。

### 1.2 当前问题

现有系统 v2.1 已具备新闻采编、人工审核、周报发布、研究门禁与审计能力，但仍存在以下不足：

1. `News` 粒度过细，同一事件可能被多个来源重复报道，难以形成事件级判断。
2. 业务线和竞对实体主要依赖关键词配置，缺少统一的 Entity Catalog。
3. 财报发布、股价异动、监管变化、竞对产品发布等“事件触发”能力不足。
4. 对 Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK 的业务映射还不够结构化。
5. 商业数据源和模型调用缺少统一成本控制。
6. AI 可以生成摘要和判断，但缺少足够严格的 P0 / P1 / Watch 分层机制。

### 1.3 v3.1 升级目标

v3.1 的目标是把现有系统从“新闻池驱动”升级为“事件池驱动”：

```text
外部信号 News
  -> 事件聚合 Event Case
  -> 业务线映射 Business Line Mapping
  -> 证据沉淀 Evidence Bank
  -> 人工审核 Human Review
  -> Daily Report / Weekly Insight
  -> 行动建议与审计闭环
```

---

## 2. 监控范围与业务线定义

### 2.1 核心业务板块

| 业务板块 | 业务含义 | GBSS 关注点 |
| --- | --- | --- |
| Alipay+ | 跨境移动支付网络、钱包互联、QR 互通 | 跨境漫游、钱包体验、商户受理、国家 QR 标准、费率和合规变化 |
| WorldFirst | B2B 跨境金融、跨境电商资金服务 | FX、到账时效、费率、平台合作、制裁与高风险地区合规 |
| Bettr | SME 数字金融与中小微授信 | 授信模型、SME 还款表现、NPL、Embedded Finance、资金成本 |
| Antom | 全球商户收单与支付网关 | 收单成功率、LPM 覆盖、3DS 合规、支付事故、大商户赢输 |
| Ant Bank HK / AlipayHK | 香港虚拟银行与钱包 | HKMA 政策、虚拟银行存款竞争、钱包场景、交通与跨境支付 |
| GBSS Service Capability | 服务支持能力底座 | Contact Center、AICC、AIQC、Voice AI、客服自动化、供应商治理 |

### 2.2 重点监控对象

| 业务板块 | 竞对/标杆/关键词 |
| --- | --- |
| Alipay+ | WeChat Pay Global, UnionPay International, SGQR, DuitNow, QRIS, PromptPay, GrabPay, PayNow, GCash, Kakao Pay, Touch 'n Go eWallet |
| WorldFirst | Wise, Payoneer, Airwallex, PingPong, LianLian Global, Currencycloud, Revolut Business |
| Bettr | Funding Societies, Aspire, Grab Finance, Validus, SeaMoney, regional SME lending, embedded finance |
| Antom | Adyen, Stripe, Checkout.com, dLocal, Worldpay, Fiserv, Nuvei, Rapyd, 2C2P |
| Ant Bank HK / AlipayHK | ZA Bank, Mox Bank, WeLab Bank, Octopus, HSBC PayMe, WeChat Pay HK, HKMA, FPS |
| GBSS Service Capability | Salesforce, Zendesk, Intercom, Genesys, Five9, Talkdesk, NICE, Verint, Calabrio, PolyAI, Retell AI, OpenAI Realtime, Twilio |

---

## 3. 产品原则

### 3.1 不做全网舆情平台

本系统不追求全网覆盖，不替代 Meltwater、Brandwatch、Factiva、Bloomberg、Refinitiv 等重型情报服务。

当前预算下，系统应聚焦：

1. 官方源优先。
2. 金融与商业新闻 API 辅助。
3. 免费全球新闻召回补充。
4. 股价异动和财报触发。
5. OpenAI 低成本模型做结构化分析。
6. `News=已采纳` 作为唯一日常人工发布门控；Evidence/Claim 审核保留给深度结论。

### 3.2 不把新闻直接等同于洞察

一条新闻只能是信号。洞察必须经过：

1. 事件聚合。
2. 多来源证据验证。
3. 业务线影响判断。
4. Claim Ledger 记录。
5. 人工审核或自动通过留痕。

### 3.3 P0 必须人工批准

系统不能自动定性 P0，只能输出 `P0 Candidate`。

最终 P0 必须满足：

1. 事件已被确认。
2. 至少 2 个独立 T1/T2 来源支撑。
3. 具备明确业务影响链路。
4. 有具体可观察数字、客户、费率、监管条款、事故影响或时间窗口。
5. 人工批准。

### 3.4 费用可控优先于覆盖率

所有商业 API 与 OpenAI 调用必须：

1. 调用前估算成本。
2. 每日、每周、每月有硬上限。
3. 超出阈值自动熔断。
4. 熔断后写 Audit Trail，不生成伪数据。

---

## 4. 系统架构

### 4.1 总体架构

```text
[外部数据源]
  |-- 官方 Newsroom / IR / Regulatory Pages
  |-- Marketaux
  |-- GDELT DOC 2.0
  |-- yfinance / Alpha Vantage
  |-- Firecrawl
        |
        v
[Ingest Adapter Layer]
  |-- source normalization
  |-- url deduplication
  |-- publish date extraction
  |-- provider health check
        |
        v
[News Pool]
  |-- raw candidate signals
  |-- status: 待处理 / 已采纳 / 已拒绝 / 已重复
        |
        v
[Event Intelligence Layer]
  |-- Entity Catalog matching
  |-- Event clustering
  |-- Event type classification
  |-- Business line mapping
  |-- Relevance scoring
        |
        v
[OpenAI Analysis Layer]
  |-- summary
  |-- event explanation
  |-- evidence extraction
  |-- P0/P1 Candidate reason
  |-- weekly synthesis
        |
        v
[Human Review]
  |-- News review
  |-- Event review
  |-- Claim review
  |-- P0 approval
        |
        v
[Publish]
  |-- Daily Report
  |-- Weekly Insight
  |-- DingTalk Document
  |-- DingTalk Group Bot
        |
        v
[Audit & Feedback]
  |-- Audit Trail
  |-- RunLog
  |-- Reject Reason analysis
  |-- Provider quality dashboard
```

### 4.2 生产形态

| 模块 | 方案 |
| --- | --- |
| 运行环境 | 本地 Mac / Python |
| 调度 | macOS launchd |
| 业务数据库与运营面 | 现有钉钉 AI 表格 |
| 本地状态 | SQLite，仅保存配置与 RunLog |
| 长文档 | 钉钉文档 / DWS |
| 群通知 | 钉钉群机器人 |
| 开发方式 | Codex 分阶段修改现有仓库 |
| 模型 | OpenAI API |
| 商业数据源 | 免费优先，必要时小额付费 |

---

## 5. 数据源与 API 策略

### 5.1 数据源分层

| 层级 | 数据源 | 费用 | 角色 |
| --- | --- | --- | --- |
| L1 官方源 | 竞对官网、IR、监管机构、交易所公告 | 免费 | T1/T2 核心证据 |
| L2 金融新闻 API | Marketaux Free | 免费 | 金融商业新闻召回 |
| L3 全球新闻 API | GDELT DOC 2.0 | 免费 | 多语种和全球补召回 |
| L4 页面抽取 | Firecrawl Free / Hobby | 免费优先；必要时付费 | 官网/公告页正文抽取 |
| L5 市场数据 | yfinance / Alpha Vantage Free | 免费 | 股价异动触发 |
| L6 模型分析 | OpenAI API | 付费 | 结构化分类、摘要、判断 |

### 5.2 推荐 adapter

| Adapter | 优先级 | 功能 | 第一阶段是否必须 |
| --- | --- | --- | --- |
| `yfinance_adapter` | P0 | 监控核心上市竞对股价异动 | 是 |
| `gdelt_adapter` | P0 | 免费全球新闻召回 | 是 |
| `marketaux_adapter` | P1 | 金融新闻结构化召回 | 是，先用免费版 |
| `firecrawl_adapter` | P1 | URL 正文抽取和 Markdown 化 | 是，先用免费额度 |
| `alpha_vantage_adapter` | P2 | 股价/市场数据备用 | 可选 |
| `fmp_adapter` | P2 | 财报日历/财务数据增强 | 暂不付费，后续评估 |

### 5.3 不建议第一阶段购买的服务

| 服务 | 原因 |
| --- | --- |
| Meltwater / Brandwatch | 超预算，适合成熟 PR/品牌舆情团队 |
| Bloomberg / Refinitiv / Factiva | 超预算，且采购复杂 |
| FMP 付费版 | 当前最需要的是事件召回，不是财务建模 |
| Marketaux Basic | 接近预算上限，应先验证免费版采纳率 |
| Firecrawl Hobby | 可作为第二阶段增强，不应第一天就买 |

### 5.4 日常新闻源扩展规则

1. Detect Sources 必须覆盖六个核心业务对象、HKMA，以及 Entity Catalog 中高 Watch Tier 的主要竞对、区域钱包/支付网络和 GBSS 服务技术厂商。
2. 日常查询分为主题、实体分组和可信垂直媒体 `site:` 查询三类；“配置了域名”不等于“已主动查询该来源”。
3. Finance/Payments 优先 The Paypers、Finextra、Payments Dive、Fintech Futures、Ledger Insights、American Banker；Contact Center 优先 CX Today、No Jitter、Call Centre Helper、CMSWire、Contact Center Pipeline、Destination CRM。
4. 每日仍最多写入 30 条候选，按查询组轮询分配名额，避免前几个热门查询吃完全部配额。
5. 增加来源不能放宽 News 人工审核、URL 去重、事件聚合或发布门禁。

---

## 6. OpenAI 模型策略

### 6.1 模型分工

| 任务 | 推荐模型层级 | 调用频率 |
| --- | --- | --- |
| 新闻清洗 | 低成本模型 | 高频 |
| 业务线分类 | 低成本模型 | 高频 |
| 实体抽取 | 低成本模型 | 高频 |
| 事件类型判断 | 低成本模型 | 高频 |
| 相关性打分 | 低成本模型 | 高频 |
| 事件摘要 | 中低成本模型 | 中频 |
| Daily Report | 规则优先、可选低成本模型 | 每日 |
| Weekly Insight 草稿 | 中低成本模型 | 每周 |
| P0 Candidate 复核 | 更强模型 + 人工审核 | 低频 |
| 管理层终稿润色 | 更强模型少量使用 | 低频 |

### 6.2 调用要求

所有 OpenAI 调用必须通过统一 `llm_service`：

1. 支持 JSON Schema 输出。
2. 支持重试和超时。
3. 支持 token 估算。
4. 支持单次、日度、周度、月度成本控制。
5. 支持 fallback 模型。
6. 支持调用日志写入 Audit Trail。
7. 支持 prompt version 管理。
8. 不允许在业务代码中散落直接 OpenAI 调用。

### 6.3 模型输出结构

LLM 不直接写最终结论，只输出结构化中间结果：

```json
{
  "event_type": "Pricing_Fee",
  "business_lines": ["WorldFirst"],
  "entities": ["Wise"],
  "summary": "Wise announced a pricing adjustment for selected cross-border transfer corridors.",
  "gbss_relevance": "May affect merchant perception of FX transparency and transfer cost in comparable corridors.",
  "severity_candidate": "P1",
  "confidence": 0.72,
  "evidence_needed": [
    "official pricing page",
    "independent media report",
    "corridor-level pricing number"
  ],
  "limitations": [
    "No direct evidence of customer migration",
    "May be limited to selected corridors"
  ]
}
```

---

## 7. 预算与成本控制

### 7.1 月度预算

| 项目 | 默认预算 | 说明 |
| --- | ---: | --- |
| OpenAI 日常分类/摘要 | 8-10 USD | 高频低成本模型 |
| OpenAI Web Search / 强模型复核 | 2-4 USD | 只给 P0/P1 Candidate 使用 |
| Firecrawl | 0 USD | 免费额度优先 |
| Marketaux | 0 USD | 免费额度优先 |
| Alpha Vantage / yfinance | 0 USD | 免费额度优先 |
| Buffer | 5-8 USD | 财报季、专题、异常重跑 |
| **建议 hard cap** | **25 USD/月** | 对应约 200 RMB/月以内 |

### 7.2 成本阈值

| 维度 | 阈值建议 |
| --- | --- |
| 单次 INGEST OpenAI 成本 | <= 0.30 USD |
| 单次 Weekly Insight 成本 | <= 1.50 USD |
| 日度 OpenAI 成本 | <= 1.00 USD |
| 周度 OpenAI 成本 | <= 5.00 USD |
| 月度 OpenAI + API 成本 | <= 25.00 USD |

### 7.3 熔断规则

1. 调用前预估成本超过阈值：跳过调用，写 Audit Trail。
2. 当日成本超过 80%：降级为只做采集，不做 LLM 分析。
3. 当月成本超过 90%：停止非必要 LLM 调用，仅保留 P0 Candidate 复核。
4. 当月成本达到 100%：全部商业调用熔断，保留本地采集和人工审核。

---

## 8. 核心数据模型

### 8.1 保留现有 `News`

v3.1 不删除现有 `News` 表。`News` 仍是候选信号入口。

建议新增字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Entity Candidates` | JSON/Text | 初步识别出的实体 |
| `Event Case ID` | String | 所属事件 |
| `Provider Score` | Float | 来源质量得分 |
| `Date Confidence` | Enum | source_metadata / url_path / first_seen_fallback |
| `Original Language` | String | 原文语言 |
| `LLM Processed At` | Datetime | LLM 分析时间 |

### 8.2 新增 `Entity Catalog`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Entity_ID` | String | 唯一 ID |
| `Canonical_Name` | String | 标准名称 |
| `Aliases` | JSON/Text | 别名 |
| `Entity_Type` | Enum | company / regulator / product / payment_method / market / technology |
| `Business_Line` | Enum/Multi | Alipay+ / WorldFirst / Bettr / Antom / HK_Fintech / GBSS_Service |
| `Ticker` | String | 上市公司 ticker |
| `Official_URLs` | JSON/Text | 官网、IR、Newsroom、监管页面 |
| `Source_Grade_Default` | Enum | T1 / T2 / T3 |
| `Active` | Boolean | 是否启用 |
| `Notes` | Text | 运营备注 |

### 8.3 新增 `Event Cases`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Event_ID` | String | 事件编号 |
| `Event_Title` | String | 事件标题 |
| `Event_Type` | Enum | Earnings / Stock_Shock / Regulatory / Pricing_Fee / Market_Expansion / Product_Launch / Strategic_MA / Merchant_Win_Loss / Ops_Incident / Credit_Risk / Channel_Partner / Capability_Tech |
| `Business_Lines` | JSON/Text | 相关业务线 |
| `Primary_Entities` | JSON/Text | 核心实体 |
| `First_Seen_At` | Datetime | 首次发现时间 |
| `Event_Date` | Date | 事件发生或发布日 |
| `Status` | Enum | 待处理 / 已采纳 / 已拒绝 / 已重复 / 已归档 |
| `Priority_Candidate` | Enum | P0_Candidate / P1 / P2 / Watch |
| `Final_Priority` | Enum | P0 / P1 / P2 / Watch / None |
| `Confidence` | Float | 置信度 |
| `Relevance_Score` | Float | 相关性总分 |
| `Summary` | Text | 事件摘要 |
| `GBSS_Impact_Hypothesis` | Text | 对 GBSS 的潜在影响假设 |
| `Limitations` | Text | 限制与反证 |
| `Reviewer` | String | 审核人 |
| `Reviewed_At` | Datetime | 审核时间 |

### 8.4 新增 `Event Sources`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Event_ID` | String | 事件 ID |
| `News_No` | String | News 编号 |
| `Source_URL` | String | 来源链接 |
| `Source_Domain` | String | 来源域名 |
| `Source_Grade` | Enum | T1 / T2 / T3 |
| `Is_Primary_Source` | Boolean | 是否主来源 |
| `Evidence_Value` | Enum | core / supporting / context / weak |

### 8.5 新增 `Event Scores`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Event_ID` | String | 事件 ID |
| `Source_Grade_Score` | Float | 来源等级分 |
| `Entity_Match_Score` | Float | 实体匹配分 |
| `Event_Severity_Score` | Float | 事件严重度分 |
| `Business_Line_Fit_Score` | Float | 业务线贴合分 |
| `Novelty_Score` | Float | 新颖度分 |
| `Market_Confirmation_Score` | Float | 市场确认分 |
| `Overall_Score` | Float | 总分 |
| `Scoring_Reason` | Text | 打分理由 |
| `Scored_At` | Datetime | 打分时间 |

### 8.6 新增 `Alert Log`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Alert_ID` | String | 告警编号 |
| `Event_ID` | String | 关联事件 |
| `Alert_Level` | Enum | P0_Candidate / P1 / Watch / System_Error |
| `Sent_To` | String | 群别名 |
| `Message` | Text | 告警内容 |
| `Sent_At` | Datetime | 发送时间 |
| `Ack_Status` | Enum | unacknowledged / acknowledged / ignored |
| `Ack_By` | String | 确认人 |
| `Ack_At` | Datetime | 确认时间 |

---

## 9. 事件类型与优先级

### 9.1 Event Type

| Event Type | 说明 | 默认处理 |
| --- | --- | --- |
| `Earnings` | 财报、业绩指引、投资者日 | P1，强相关可升 P0 Candidate |
| `Stock_Shock` | 单日涨跌超过阈值 | Watch/P1，需要解释原因 |
| `Regulatory` | 牌照、处罚、监管新政、征求意见 | P1/P0 Candidate |
| `Pricing_Fee` | 费率、FX、手续费、结算价格变化 | P1/P0 Candidate |
| `Market_Expansion` | 明确进入或扩展到新国家/市场 | P1，核心业务重大扩张可升 P0 Candidate |
| `Product_Launch` | 新产品、新 LPM、新 corridor、新能力 | P1 |
| `Strategic_MA` | 并购、融资、战略投资或重大合作 | P1/P0 Candidate |
| `Merchant_Win_Loss` | 大商户赢单/流失/合作终止 | P1/P0 Candidate |
| `Ops_Incident` | 宕机、支付失败、数据泄露、风控误杀 | P0 Candidate |
| `Credit_Risk` | NPL、逾期、融资、授信模型变化 | P1 |
| `Channel_Partner` | 钱包互联、国家 QR、平台合作 | P1 |
| `Capability_Tech` | Voice AI、AIQC、AICC、客服自动化 | P1/Watch |
| `Market_Context` | 估值、公司画像、行业比较、战略叙事或非交易型市场背景 | Watch/P2；不得触发 Strategic 或 P0 Candidate |

### 9.2 优先级

| 优先级 | 含义 | 进入条件 |
| --- | --- | --- |
| P0 | 30 天内需要管理层决定/风险响应 | 人工批准 + T1/T2 证据 + 明确 GBSS 影响 + 决策窗口 |
| P0 Candidate | 系统识别的潜在重大事件 | 高相关性 + 高影响 + 证据待确认 |
| P1 | 需要研究、Benchmark、PoC 或能力评估 | 有证据支持且有可行动问题 |
| P2 | 持续观察 | 有相关性但近期无需动作 |
| Watch | 早期/弱信号 | 进入信号池，不进入管理层结论 |

---

## 10. 相关性评分机制

### 10.1 总分公式

```text
Overall Score =
0.25 * Source Grade Score
+ 0.20 * Entity Match Score
+ 0.20 * Event Severity Score
+ 0.15 * Business Line Fit Score
+ 0.10 * Novelty Score
+ 0.10 * Market Confirmation Score
```

### 10.2 分数解释

| 分数 | 处理方式 |
| ---: | --- |
| >= 0.80 | 推送审核群，标记 P0/P1 Candidate |
| 0.60 - 0.79 | 进入待审池，News 采纳后可进入 Daily Report |
| 0.40 - 0.59 | 进入 Watch，不主动打扰 |
| < 0.40 | 归档或自动拒绝候选 |

### 10.3 打分要求

1. 每个分项必须可解释。
2. LLM 可以给出初始分，但必须保存 reason。
3. 人工可覆盖优先级和分数。
4. 被人工拒绝的事件必须记录 Reject Reason，用于后续调参。

---

## 11. 工作流

### 11.1 INGEST：自动采编

**触发：** 周一至周六 02:00，或人工执行。  
**目标：** 从外部数据源生成可审核 News 候选。

步骤：

1. Provider 健康检查。
2. 从 Entity Catalog 生成搜索计划。
3. 拉取 Marketaux / GDELT / 官方源 / yfinance 结果。
4. URL 去重。
5. 抽取标题、发布时间、来源域名。
6. 必要时调用 Firecrawl 抽取正文。
7. 写入 News。
8. 写 RunLog 与 Audit Trail。

### 11.2 EVENTIZE：事件聚合

**触发：** INGEST 后自动执行。  
**目标：** 把 News 聚合为 Event Case。

步骤：

1. 基于 URL、标题、实体、时间窗口做候选聚类。
2. 调用 OpenAI 进行事件类型识别和业务线映射。
3. 关联 Entity Catalog。
4. 写入 Event Cases / Event Sources。
5. 执行相关性打分。
6. 将低分事件归为 Watch 或归档。

### 11.3 REVIEW：News 人工审核

**触发：** 每天 09:00。
**目标：** 判断单条 News 来源是否可信、是否允许进入周报。

审核对象：

1. 待处理 News。
2. News 来源、标题、Publish Date 与业务相关性。
3. 系统生成的关联 Event Case、P0 Candidate / P1 Candidate 作为审核辅助信息。
4. Event 的业务线、事件类型、相关性分数和影响方向由系统自动生成，不要求再次人工采纳。
5. 每日运营群审核批次只包含 `Publish Date=前一个自然日`、状态为 `待处理` 且已关联 Event Case 的 News；时区统一为 `Asia/Kuala_Lumpur`，周日也运行。
6. 缺少 Publish Date、早于前一日或尚未关联 Event 的 News 不进入当天运营群提醒，但保留在后台用于补齐、去重和审计。
7. 同日发现的 Strategic/P0 Candidate 仍可由关键扫描即时提醒，不受“昨日批次”限制。

钉钉提醒样例：

```text
📢 GBSS 外部事件待审提醒

今日新增 Event Case：8 个
其中 P0 Candidate：1 个，P1：4 个，Watch：3 个

🌐 Alipay+：2 个，涉及 QRIS / DuitNow 互通
💼 WorldFirst：2 个，涉及 Wise 费率与 Payoneer 财报
💳 Antom：3 个，涉及 Adyen 财报、Stripe 新产品、dLocal 股价异动
🏦 HK Fintech：1 个，涉及 HKMA 虚拟银行政策

请进入 News 审核视图处理：{review_url}
```

### 11.4 PUBLISH：Daily Report

**触发：** 每天 12:00；预留一小时人工检查，13:00 由负责人手工转发到另一个内部群，系统不自动转发。
**输入：** 至少关联一条 `News=已采纳` 的自动生成 Event Case。
**输出：** 管理层新闻摘要，不做深度战略推演。

规则：

1. 只消费至少关联一条 `News=已采纳` 的 Event Case，不要求第二次人工采纳 Event。
2. 每个业务线优先选高分事件。
3. 每个事件必须有 Source URL 和 Publish Date。
4. 不得包含未批准 P0 结论。
5. 成功后写回 `Daily Report Sent At`；使用 7 天回看窗口接住延迟审核，但同一 Event 不重复发送。

### 11.5 PUBLISH：Weekly Insight

**触发：** 周六草稿、周日终稿。  
**输入：** 已采纳 News 对应的 Event Case + 可用的 Evidence Bank + Claim Ledger。
**输出：** Signal Brief 或 Evidence-backed Weekly Report。

规则：

1. Evidence/Claim 未审核不阻止事实型输入，但不达 Deep Research 门禁时只能输出 Signal Brief。
2. 达到门禁后，才能输出 Evidence-backed Weekly Report。
3. 所有战略性 Claim 必须关联 Evidence ID。
4. P0 必须人工批准。
5. 报告必须包含限制、反证或不确定性。

---

## 12. 质量门禁

### 12.1 Deep Research Ready 条件

必须同时满足：

1. 至少 6 条已验证 Evidence。
2. 至少 3 个 T1/T2 独立来源。
3. 所有高影响 Claim 均已批准。
4. 至少一个 Claim 包含限制、反证或边界条件。
5. 所有优先卡片都有 Source URL 和 Publish Date。

否则输出 `Signal Brief`。

### 12.2 来源等级

| 等级 | 类型 | 用途 |
| --- | --- | --- |
| T1 | 监管机构公告、交易所文件、审计后财报、官方产品文档 | 可支撑核心结论 |
| T2 | Reuters、Bloomberg、FT、WSJ、竞对官网新闻稿、行业协会报告 | 可支撑辅助结论 |
| T3 | 社交媒体、自媒体、论坛、二手转述 | 仅作弱信号 |

### 12.3 禁止行为

系统不得：

1. 把单一媒体报道直接升级为 P0。
2. 把 vendor PR 软文当作唯一证据。
3. 把模型推测写成事实。
4. 把未审核 News 放进正式周报。
5. 在图片或海报层补写未经 Evidence/Claim 审核的结论。

---

## 13. 配置文件样例

```json
{
  "system_mode": "production",
  "timezone": "Asia/Kuala_Lumpur",
  "data_paths": {
    "settings_and_runlog_db": "data/settings.sqlite3",
    "business_datastore": "dingtalk_ai_table"
  },
  "business_lines": [
    "Alipay_Plus",
    "WorldFirst",
    "Bettr",
    "Antom",
    "HK_Fintech",
    "GBSS_Service"
  ],
  "budget": {
    "monthly_budget_rmb": 200,
    "monthly_hard_cap_usd": 25,
    "daily_openai_cap_usd": 1.0,
    "weekly_openai_cap_usd": 5.0,
    "single_ingest_cap_usd": 0.3,
    "single_insight_cap_usd": 1.5
  },
  "providers": {
    "gdelt": {"enabled": true},
    "marketaux": {"enabled": true, "plan": "free"},
    "firecrawl": {"enabled": true, "plan": "free"},
    "yfinance": {"enabled": true},
    "alpha_vantage": {"enabled": false},
    "fmp": {"enabled": false}
  },
  "openai": {
    "enabled": true,
    "default_model": "low_cost_model",
    "analysis_model": "mid_cost_model",
    "review_model": "strong_model_low_frequency",
    "use_web_search_for": ["P0_Candidate", "high_impact_P1"]
  },
  "tickers_to_watch": [
    "WISE.L",
    "PAYO",
    "ADYEN.AS",
    "DLO"
  ],
  "thresholds": {
    "stock_shock_abs_pct": 5,
    "p0_candidate_score": 0.80,
    "p1_candidate_score": 0.60,
    "watch_score": 0.40
  },
  "dingtalk": {
    "review_group_alias": "BOT监控审核群",
    "publish_group_alias": "Daily News",
    "review_webhook_secret_name": "DINGTALK_REVIEW_WEBHOOK",
    "publish_webhook_secret_name": "DINGTALK_PUBLISH_WEBHOOK"
  }
}
```

---

## 14. Codex 开发路线

### Sprint 0：现状扫描

目标：不改代码，只理解现有系统。

Codex 应输出：

1. 当前目录结构。
2. 现有脚本列表。
3. 现有钉钉 AI 表格和本地配置/RunLog。
4. 钉钉配置点。
5. launchd 任务。
6. provider 相关代码。
7. 测试覆盖情况。
8. 风险点和推荐修改顺序。

### Sprint 1：现有钉钉表数据契约与校验

在当前 workspace 和既有钉钉 AI 表格中确认以下业务表契约：

1. `entity_catalog`
2. `event_cases`
3. `event_entities`
4. `event_sources`
5. `event_scores`
6. `alert_log`
7. `api_usage`

验收：

1. 不执行数据库 migration，不创建第二套本地业务数据库。
2. 当前 workspace 可读写所需钉钉业务表和字段。
3. 不破坏现有 News 表。
4. 有回滚方案。
5. 有单元测试。

### Sprint 2：Provider Adapter 层

实现：

1. `gdelt_adapter`
2. `marketaux_adapter`
3. `firecrawl_adapter`
4. `yfinance_adapter`
5. `alpha_vantage_adapter` 可选

验收：

1. 每个 adapter 可单独启停。
2. 每个 adapter 有 mock 测试。
3. 每个 adapter 记录 provider、query、source_url、publish_date。
4. 失败写 Audit Trail。

### Sprint 3：OpenAI LLM Service

实现统一 LLM 服务。

要求：

1. JSON Schema 输出。
2. 成本估算。
3. 超预算熔断。
4. prompt version 管理。
5. fallback 模型。
6. 失败重试。
7. 所有调用写日志。

### Sprint 4：Eventize 层

实现：

1. News -> Event Case 聚合。
2. Entity Catalog 匹配。
3. Event Type 判断。
4. Business Line 映射。
5. Relevance Scoring。

验收：

1. 同一事件多来源可聚合。
2. 低相关事件不推送。
3. 分数和理由可解释。
4. 人工可覆盖。

### Sprint 5：钉钉审核改造

实现：

1. News 待审提醒，并附系统生成的 Event Case 分类信息。
2. P0 Candidate 单独提醒。
3. 按业务线统计。
4. 审核视图直达。
5. Alert Log 记录。

### Sprint 6：Daily / Weekly 输出改造

实现：

1. Daily Report 优先消费已采纳 News 对应的 Event Case，每天 12:00 增量发送，13:00 人工转发。
2. Weekly Insight 使用 Event Case + Evidence + Claim。
3. 不达门禁输出 Signal Brief。
4. 成功后写回发送状态。
5. 群路由保持审批群和发布群隔离。

---

## 15. 给 Codex 的总提示词

```text
你是我的工程实现助手。请基于当前仓库中已有的 GBSS AI & Service Intelligence PRD 和代码，实现 v3.1：GBSS 外部事件情报系统（Codex + OpenAI 版）。

目标：
1. 保留现有 News -> 人工审核 -> Daily Report / Weekly Insight -> Audit Trail 的主链路。
2. 直接使用当前 workspace；钉钉 AI 表格作为业务数据库，本地 SQLite 只保存配置与 RunLog，不执行数据库 migration。
3. 在现有 News 信号池基础上新增 Event Case 层，把多条新闻聚合为同一个外部业务事件。
4. 新增 Entity Catalog，用于维护 Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK、GBSS capability track 相关的竞对、监管机构、产品、ticker、别名。
5. 新增 OpenAI 模型调用层，默认使用低成本模型做分类、摘要、业务线映射、事件类型判断和 relevance scoring；高价值事件才使用更强模型。
6. 新增成本控制：月度预算上限按 200 RMB 口径设计，实际 API hard cap 建议设置为 25 USD/月。每次调用前预估成本，超过单次或日度上限则跳过并写 Audit Trail。
7. 新增数据源 adapter：Marketaux、GDELT、Firecrawl、Alpha Vantage/yfinance。每个 adapter 必须可配置、可关闭、有健康检查、有 mock 测试。
8. 不允许系统自动定性 P0，只允许输出 P0 Candidate。最终 P0 必须人工批准。
9. 所有管理层输出必须能追溯到 Event Case、Evidence、Source URL、Publish Date 和 Claim。
10. 不达 Deep Research 门禁时，只输出 Signal Brief，不得生成确定性战略结论。

请按以下顺序开发：
第一步：做现状扫描，列出相关文件、数据表、脚本、定时任务、钉钉 webhook 配置点，不修改代码。
第二步：在现有钉钉 AI 表格中确认 Event Cases、Event Entities、Event Sources、Event Scores、Entity Catalog、Alert Log、API Usage 的字段契约与读写校验，不执行数据库 migration。
第三步：补充测试，确保现有 News 流程不被破坏。
第四步：实现数据源 adapter 层。
第五步：实现 OpenAI LLM service，要求结构化 JSON 输出、重试、超时、成本估算、熔断。
第六步：实现事件聚合、业务线映射、事件类型判断和 relevance scoring。
第七步：改造钉钉审核提醒卡片。
第八步：改造 Daily Report / Weekly Insight 生成逻辑，让它优先消费已采纳 News 对应的 Event Case。
第九步：输出运行文档、配置样例、回滚方案和验收清单。

开发原则：
- 小步提交。
- 每一步必须有测试。
- 不要删除历史表。
- 不要把密钥写入代码或仓库。
- 所有失败都必须进入 Audit Trail。
- 优先保证可运行、可回滚、可解释，再追求智能化。
```

---

## 16. 验收指标

### 16.1 运营指标

| 指标 | 目标 |
| --- | --- |
| INGEST 成功率 | >= 95% / 月 |
| 至少一个 provider 可用 | 100% 日常健康检查 |
| Event Case 聚合成功率 | >= 90% 的重复新闻可正确聚合 |
| 审核链路可达率 | 100% |
| 群路由准确率 | 100% |
| 重复发布率 | 0 |
| Publish Date 完整率 | >= 99% |

### 16.2 内容指标

| 指标 | 目标 |
| --- | --- |
| 业务线分类准确率 | >= 90% |
| Event Type 分类准确率 | >= 85% |
| 已拒绝原因覆盖率 | >= 80% |
| P0 完整门禁率 | 100% |
| Deep Research 门禁合规率 | 100% |
| Claim 可追溯率 | 100% |

### 16.3 成本指标

| 指标 | 目标 |
| --- | --- |
| 月度总成本 | <= 200 RMB |
| OpenAI/API hard cap | <= 25 USD/月 |
| 超预算熔断 | 100% 生效 |
| 异常重跑成本可解释 | 100% 写入 Audit Trail |

---

## 17. 当前不做的事项

v3.1 不做：

1. 全网舆情平台。
2. 多租户 SaaS。
3. 移动端 App。
4. 自动决策 P0。
5. 无人审核的管理层战略结论。
6. 大规模社交媒体情绪分析。
7. 采购重型付费情报系统。
8. 把 Codex、ChatGPT 浏览器自动化作为无人值守生产 provider。

---

## 18. 推荐落地顺序

第一优先级：

1. Event Case 数据层。
2. Entity Catalog。
3. OpenAI LLM Service。
4. yfinance / GDELT adapter。
5. 钉钉 Event Review 提醒。

第二优先级：

1. Marketaux adapter。
2. Firecrawl adapter。
3. Daily Report 改造。
4. Weekly Insight 改造。
5. Provider 质量面板。

第三优先级：

1. Alpha Vantage。
2. FMP 免费版。
3. Firecrawl Hobby。
4. OpenAI Web Search for P0 Candidate。
5. 研究结果闭环。

---

## 19. 最终定版口径

v3.1 的一句话定义：

> 用 200 RMB/月以内的轻量商业接口和 OpenAI 模型，把 GBSS 当前 Daily Report / Weekly Insight 系统升级为事件级外部情报生产系统。系统不追求全网舆情覆盖，而是优先捕获对 Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK 和 GBSS 服务能力有业务影响的外部事件，并通过人工审核、证据门禁、日度事实播报和周度研究输出，帮助 GBSS 更早理解业务变化、竞对动作和运营风险。
