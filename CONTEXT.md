# GBSS 外部事件情报

面向 Ant International GBSS 的外部业务事件情报系统。它从公开信号中识别对 Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK / AlipayHK 及 GBSS 服务能力有影响的外部事件，经人工审核与证据门禁后，形成管理层可追溯的判断。

## Language

### 信号与事件

**Candidate（候选）**：
一次搜索返回、经 URL 去重后仍有效的外部条目。绝大多数候选不会进入 News。
_Avoid_: 新闻、结果、result

**Candidate Pool（候选池）**：
当日全部去重候选的留档，含未被选中写入 News 的部分。它是免费且已产生的存量数据，不承担审核语义。
_Avoid_: 垃圾桶、落选、丢弃项

**News（信号）**：
被选中写入业务表、进入人工审核视野的候选。`News` 是唯一的人工审核入口，`News=已采纳` 是唯一的日常发布门。
_Avoid_: 文章、报道、条目

**Event Case（事件）**：
多条 News 指向的同一件外部业务事件。判断、优先级和业务线映射都挂在事件上，不挂在单条 News 上。
_Avoid_: 话题、专题、cluster

### 判断与结论

**Evidence（证据）**：
从已采纳 News 中沉淀、带来源分级和原文摘录的可引用事实单元。
_Avoid_: 素材、引用、参考

**Claim（结论）**：
一条结构化判断，必须声明 `claim_type`（Fact / Inference / Hypothesis）、`confidence`（High / Medium / Low），并引用至少一个真实存在的 Evidence ID；Inference 还必须附反证或边界条件。
_Avoid_: 观点、分析、看法、takeaway

**Insight**：
指一组进入 Claim Ledger 的 Claim，而非一篇供人阅读的文章。文章是 Insight 的展现形式，不是 Insight 本身。
_Avoid_: 洞察文章、周报正文、研究报告

**Signal Brief**：
证据或结论未过门禁时允许输出的降级形态：只陈述已核实事实，不输出影响判断与行动建议。
_Avoid_: 简报、摘要版

**Recall Sweep（补捞）**：
对候选池与归档池的周期性回扫，用以发现已被系统丢弃、但可能构成漏报的事件。它只提议事件级线索，不直接写入 News。
_Avoid_: 二次抓取、重扫、回捞

**Publishable Claim（可发布结论）**：
允许不经人工批准即进入对外报告的 Claim。当前仅 `Fact` 类满足此条件，因为它能被机器比对其引用的 Evidence 原文；`Inference` 与 `Hypothesis` 一律待批。
_Avoid_: 已审结论、可信结论

### 质量目标

**Recall（召回）**：
真实发生且与 GBSS 相关的外部事件中，被系统捕获并送达人工视野的比例。当前的主优化目标。
_Avoid_: 覆盖率、抓取率

**Density（密度）**：
已发布条目中值得管理层阅读的比例。当前为约束，不得因提升召回而变差。
_Avoid_: 质量、精度

**Throughput（吞吐）**：
单位时间实际发布的条目数。当前为约束，不得因提升召回而变差。
_Avoid_: 产量、数量
