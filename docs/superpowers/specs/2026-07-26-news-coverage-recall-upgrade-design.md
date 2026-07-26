# 设计：高价值新闻覆盖、人工策展与周度输入新鲜度升级

> Date: 2026-07-26
> Status: approved in conversation; written spec pending final review
> Owner: Franco / GBSS
> 目标读者: 实现者（写实现计划前的合同）

## 1. 背景与问题

2026-07-26 的生产核验发现，系统每日能稳定抓取 200–300 条原始候选，并选出 30 条进入平衡候选，但仍会漏掉 GBSS 明确关注的高价值信号。此次五条回归样本是：

1. TechCrunch：Natural 融资 3000 万美元，建设面向 AI Agent 的支付基础设施并挑战 Stripe。
2. Airwallex 官方：Visa 与 Airwallex 为货运平台建设嵌入式金融基础设施。
3. Electronic Payments International：Visa 与 LianLian 在大中华区完成首笔 live agentic B2B payment。
4. No Jitter / OpenAI 官方：OpenAI Presence 进入企业 CX、语音和客服 Agent 生产部署。
5. Reuters：Ant International 融资 12 亿美元推动全球扩张。

生产状态表明这不是单点故障，而是跨层损失：

- Natural、Airwallex、EPI 原文未进入 News。
- No Jitter 已进入 News，但 OpenAI 不在 Entity Catalog，未形成 Event Case，AI 以无事件关联为由拒绝。
- Reuters 原文未进入 News；系统抓到 Investing.com、PYMNTS、TNW 等二手版本，但缺少可匹配的 Ant International 母实体，未形成正确 Event。
- `source_domain` 记录只参与可信域名集合，不会生成独立搜索；Reuters 和 TechCrunch 虽在配置中，却没有获得稳定的主动召回。
- 财务主题缺少 `agentic payments`、`payments for AI agents`、`embedded finance`、`B2B payment automation`、`freight finance` 等表达。
- 当前事件分类会把 Airwallex/Visa 合作判为 `Market_Context`，把 Visa/LianLian live agentic payment 判为 `General`。
- 30 条候选上限按查询组轮询和日期优先，不能为官方源、核心实体、战略主题或人工指定内容保留容量。
- 周五生成 Research Queue 后，到周日发布前没有比较当前已采纳事件集合是否变化，容易让 Weekly Insight 使用过期输入。

2026-07-26 12:00 的 Weekly Insight 因本周 Research Queue 缺少 `Research Document URL` 被正确阻断，没有发送不完整内容。该门禁保留。

## 2. 已确认的操作契约

### 2.1 人工策展即人工审批

- 用户在对话中提供 URL，并明确说“纳入”“放进日报/周报/Insight”时，该动作视为 News 的显式人工审批。
- 这类记录写入 `News / oMbefcK` 时直接使用人工最终状态 `已采纳`，并保留：
  - `Search Provider = editorial_input`
  - `Discovery Type = editorial_must_include`
  - `Review Decision Source = Human`
  - 可审计的输入说明和时间
- 仅提供链接、询问评价或要求检查，但没有明确要求纳入时，不构成审批；记录若被导入，仍保持 `待处理`。
- 人工策展不能绕过硬证据门禁：URL 必须有效、Publish Date 必须可解析；无法抓取正文可以保留为 Evidence 待核验，但不能伪造摘要或事实。

### 2.2 产品与审批边界

- News 继续要求明确人工审批；普通自动抓取不得因 AI 推荐而改变人工最终状态。
- Weekly Headlines 只使用正式已采纳且具备可追溯 Event Case 的 News。
- Weekly Insight 可以按既有时限规则处理研究审批，但研究输入必须来自正式已采纳 Event，且必须有有效研究文档 URL 才能发布。
- 长正文继续放在钉钉文档；AI 表只保留链接、短摘要、状态和审计字段。
- 不新建新的可见业务表。覆盖诊断使用 RunLog、Audit Trail 和本地 JSON artifact。

## 3. 目标与非目标

### 目标

1. 五条回归样本全部进入 News；明确要求纳入的五条全部标记为人工已采纳。
2. 五条样本全部形成可追溯 Event Case，并映射到正确业务线。
3. 已采纳样本能够进入 Daily Report、Weekly Headlines 和 Weekly Insight 的合法输入集合，不依赖重复手工搬运。
4. 官方源、核心实体、战略主题和人工策展内容不会再被每日 30 条平衡上限静默挤掉。
5. 对每条高价值目标都能回答“在哪一层被保留或淘汰，以及为什么”。
6. 周日发布前发现 Research Queue 输入陈旧时必须阻断发布，并原地刷新当前周期，不创建重复行。
7. 保持当前 OpenAI/API 成本上限，不要求开启生产 OpenAI 分类。

### 非目标

- 不追求全网舆情覆盖或无限扩张关键词。
- 不取消人工 News 审批。
- 不为所有新公司永久建立公司实体；主题实体应覆盖长尾创新者。
- 不自动生成或伪造 Weekly Insight 研究文档链接。
- 不因本次升级自动重发历史日报或周报；恢复发布前必须回读完整集合。

## 4. 推荐架构：五路召回 + 统一事件与覆盖门禁

### 4.1 五路召回

| Lane | 输入 | 优先级 | 作用 |
| --- | --- | --- | --- |
| Editorial | 用户明确指定 URL | 最高，绕过候选上限 | 保证人工策展内容进入 News |
| Core Entity | GBSS 六大业务与高优先竞对 | 高，保留配额 | 保证 Ant International、Alipay+、WorldFirst、Antom 等召回 |
| Strategic Theme | Agentic Payments、Embedded Finance、Agentic CX 等 | 高，保留配额 | 覆盖 Natural 等长尾创新者 |
| Trusted Media | Reuters、TechCrunch、EPI、No Jitter 等主动查询 | 中高，保留配额 | 让可信域名真正产生查询，而不只是排序标签 |
| Broad Market | 现有 Finance / Contact Center 市场查询 | 标准 | 保留探索性覆盖 |

所有 Lane 输出统一的候选结构，至少包含：

```python
{
    "title": str,
    "url": str,
    "published_at": str,
    "source": str,
    "section": str,
    "search_group": str,
    "discovery_type": str,
    "editorial_approved": bool,
}
```

### 4.2 候选选择

替换“所有查询组简单轮询直到 30 条”的单一机制：

1. `editorial_must_include` 不进入 30 条竞争，完成 URL 规范化和去重后直接进入写入阶段。
2. 30 条自动候选池内设置最低保留量：
   - Core Entity：至少 6 条
   - Strategic Theme：至少 6 条
   - Trusted Media：至少 6 条
   - 其余 12 条由各 Lane 按轮询补齐
3. Lane 内排序使用：
   - 业务/事件触发词相关性
   - 官方或可信来源
   - 目标发布日期距离
   - URL 稳定性与完整性
4. 同一 URL 只保留一次；同一事件的多来源版本允许进入后续事件聚合，由 Event Source 选择 T1/T2 主来源。
5. 如果某 Lane 数量不足，其配额自动释放给其他 Lane，不为了凑数引入弱新闻。

## 5. 来源与主题设计

### 5.1 新增战略主题

在 Detect Sources 中新增并保持可配置：

- `Agentic Payments`
  - agentic payments
  - payments for AI agents
  - AI agent payments
  - autonomous payments
  - agentic commerce
  - programmable commerce
- `Embedded Finance / B2B Payments`
  - embedded finance
  - B2B payment automation
  - commercial payments
  - cross-border B2B payments
  - freight payments
  - logistics payments
  - treasury infrastructure
- `Agentic CX`
  - enterprise AI agents
  - customer service agents
  - AI agent governance
  - voice and chat agents
  - agent evaluation
  - human escalation

主题拆成紧凑查询组，不回退到曾导致 Brave 422 的超长 OR 查询。

### 5.2 主动可信来源

Trusted Media 至少加入：

- Finance：Reuters、TechCrunch、Electronic Payments International
- Contact Center：No Jitter、OpenAI 官方

`source_domain` 仍可用于来源等级和候选排序，但重要来源必须以 `trusted_source` 或官方 Entity `scan_url` 进入可执行查询。可信来源查询按小组分块，并与对应主题词结合，避免裸 `site:` 查询只返回站内最新但不相关内容。

### 5.3 官方源

- 保留并强化 Airwallex、Visa、Stripe、Ant International、OpenAI 的 newsroom/press/IR URL。
- 官方源扫描结果写入统一候选合同，优先级高于二手转载。
- 页面返回 403 或正文抓取失败时，保留 URL、标题、发布日期和“正文待核验”限制，不静默丢弃，也不编造内容。

## 6. 实体、事件分类与业务映射

### 6.1 Entity Catalog

新增或扩展：

- `ant-international`
  - Canonical Name: Ant International
  - Business Lines: Alipay_Plus, WorldFirst, Antom, Bettr, HK_Fintech
  - Watch Tier: critical
- `openai`
  - Canonical Name: OpenAI
  - Aliases: OpenAI Presence
  - Business Lines: GBSS_Service
  - Watch Tier: high
- `agentic-payments`
  - Canonical Name: Agentic Payments
  - Aliases: payments for AI agents, AI agent payments, autonomous payments, agentic commerce
  - Business Lines: Antom, WorldFirst
  - Type: capability/topic
  - Watch Tier: high
- `embedded-finance`
  - Canonical Name: Embedded Finance
  - Aliases: embedded payments, B2B payment infrastructure
  - Business Lines: Antom, WorldFirst
  - Type: capability/topic
  - Watch Tier: high

长尾公司不必全部成为永久实体；只要标题或摘要命中主题实体，就能形成 Event 并进入人工判断。

### 6.2 事件分类

增加确定性模式：

- `join forces / collaboration / partners / teams up` + 明确支付/平台实体 → `Channel_Partner`
- `first live / goes live / completes first` + agentic payment → `Product_Launch`
- `OpenAI Presence` → `Product_Launch`
- `agentic payments / payments for AI agents` + product/platform/infrastructure → `Product_Launch` 或 `Capability_Tech`
- `raises $X` 继续使用 `Strategic_MA`

五条回归样本的目标分类：

| 新闻 | Event Type | Business Lines |
| --- | --- | --- |
| Natural $30M / Agentic Payments | Strategic_MA | Antom, WorldFirst |
| Visa × Airwallex freight infrastructure | Channel_Partner | Alipay_Plus, Antom, WorldFirst |
| Visa × LianLian first live agentic B2B payment | Product_Launch | Alipay_Plus, Antom, WorldFirst |
| OpenAI Presence in CX | Product_Launch | GBSS_Service |
| Ant International $1.2B global expansion | Strategic_MA | Alipay_Plus, WorldFirst, Antom, Bettr, HK_Fintech |

### 6.3 AI Review Rulebook

按项目规则更新 `docs/ai_review_labeling_rules.md`：

- 新增“具体 agentic payment 基础设施、live transaction、官方企业 Agent 产品发布、明确支付合作”建议采纳规则。
- 增加 2026-07-26 Change Log。
- 保持重复、缺 Source URL、缺 Publish Date 三个硬门禁。
- 规则只产生 AI Status；除 `editorial_must_include` 的显式人工审批外，不改最终人工状态。

## 7. Editorial URL Intake

新增可复用脚本，例如：

```text
scripts/ingest_editorial_urls.py
```

接口要求：

```bash
.venv/bin/python scripts/ingest_editorial_urls.py \
  --input data/editorial-intake.json \
  --approve \
  --reason "User explicitly requested Daily/Weekly/Insight inclusion"
```

输入每条至少包含 URL；可选 title、publish_date、section、notes。处理流程：

1. 规范化并验证 URL。
2. 对可访问页面提取 title/publish date；失败时使用经人工提供并核验的字段。
3. 与 News 全表按规范化 URL 去重。
4. 已存在记录：只补齐缺失证据字段和人工审批字段，不覆盖更高质量人工编辑。
5. 新记录：写入 News，并记录 editorial 来源。
6. `--approve` 仅用于明确人工纳入；没有该参数时保持 `待处理`。
7. 写 RunLog/Audit Trail，输出 created / updated / duplicate / blocked 数量和每条原因。
8. 运行窄链路：标题/日期补齐 → dedupe → eventize；不得重跑完整搜索抓取。

当前五条使用 `--approve`。

## 8. Coverage Audit

新增纯函数和本地 artifact：

```text
data/coverage-audit-latest.json
```

每个目标 URL 记录：

```python
{
    "url": str,
    "discovered": bool,
    "candidate_selected": bool,
    "news_record_id": str,
    "event_id": str,
    "manual_status": str,
    "ai_status": str,
    "daily_eligible": bool,
    "weekly_eligible": bool,
    "research_input": bool,
    "blocked_stage": str,
    "reason": str,
}
```

原因值必须是稳定枚举，例如：

- `not_discovered`
- `candidate_quota_excluded`
- `duplicate_existing`
- `missing_publish_date`
- `missing_entity`
- `general_event_type`
- `pending_human_review`
- `research_input_stale`
- `research_document_missing`
- `eligible`

RunLog 保存汇总，Audit Trail 保存关键阶段；详细逐条内容放本地 artifact，避免钉钉 API 和可见表膨胀。

## 9. 日报、周报与 Insight 数据流

### 9.1 日报与 Weekly Headlines

```text
Editorial / Automated Discovery
  → News
  → Eventize
  → Human final status
  → accepted Event
  → Daily Report / Weekly Headlines
```

- Editorial approved 记录仍需成功形成 Event Case 才能发布。
- 如果人工已采纳但事件化失败，Coverage Audit 必须报警并给出 `missing_entity` 或分类原因，不能静默等待。

### 9.2 Weekly Insight 输入新鲜度

Research Queue 增加后台字段：

- `Input Event IDs`
- `Input Fingerprint`
- `Input Generated At`
- `Coverage Checked At`

周五生成计划时写入当时已采纳 Event 集合和 fingerprint。周日发布前：

1. 重新读取当前周期已采纳 Event。
2. 计算当前 fingerprint。
3. 若与 Research Queue 不同：
   - 阻断发布。
   - 原地刷新同一周期的 Topic/Primary Question/Approval Plan/Evidence Plan。
   - 清空已不可信的 Research Document URL，或标记 `Waiting for refreshed manual ChatGPT report link`。
   - 明确列出新增/移除 Event。
4. fingerprint 一致且 Research Document URL 是有效 HTTPS，才允许发布。

本周 `JUL 18–JUL 24` 的现有 Research Queue 行必须原地更新，不创建重复周期。

## 10. 当前五条恢复方案

设计批准并完成实现后：

1. 通过 Editorial Intake 导入或修复五条 News。
2. 根据本次用户明确授权，把五条最终状态设为 `已采纳`。
3. 运行窄链路 eventize，回读五个 Event ID、类型、业务线和来源。
4. 更新现有 `JUL 18–JUL 24` Research Queue：
   - 主题升级为“Agentic Payments、Embedded Finance 与 Enterprise Agent：对 Ant International / GBSS 的业务与运营影响”。
   - 核心信号包含五条新闻。
   - 生成可复制的外部 Deep Research Prompt。
   - 状态设为等待用户提供新的钉钉研究文档链接。
5. 在链接到达前不发布 Weekly Insight。
6. 链接到达后先校验完整 Event 集合，再发布完整而非增量清单，并回读 RunLog、Queue、sent markers 和总数。

## 11. 测试与评测

### 11.1 单元测试

- Detect Sources 会生成三个新增主题查询。
- Reuters、TechCrunch、EPI、No Jitter、OpenAI 会产生主动查询或官方扫描输入。
- 候选选择为 Core/Theme/Trusted 保留配额，Editorial 不受 30 条限制。
- Editorial URL 去重、补齐、`--approve` 与非 approve 状态正确。
- 五条标题全部匹配实体、事件类型和业务线。
- AI Rulebook 对这些高价值模式建议采纳，同时保留三个硬门禁。
- Coverage Audit 为每种阻断阶段输出稳定原因。
- Research Queue fingerprint 变化会阻断发布并原地刷新。

### 11.2 回归评测

新增：

```text
evals/news_coverage_regression_set.json
```

至少包含五条本次样本，每条声明：

- canonical URL
- expected source lane
- expected entities
- expected event type
- expected business lines
- expected manual result when editorial approved
- expected daily/weekly/research eligibility

发布门禁：

- Editorial approved：5/5 进入 News。
- Eventization：5/5 形成 Event。
- Event Type / Business Lines：5/5 满足 fixture。
- Weekly research input：5/5 被当前周期 fingerprint 纳入。
- 自动最终 P0：仍为 0。

### 11.3 线上验证

- 回读 News 五条状态和 ID。
- 回读五个 Event Case、Event Source 和主来源等级。
- 运行日报/周报选择 dry-run，证明五条已进入合法集合，但不发送。
- 回读更新后的 Research Queue Prompt 和 fingerprint。
- 用户补链接后再执行正式 Weekly Insight，并明确本次是完整清单及总数。

## 12. 错误处理与成本

- 外部页面 403/超时：保留人工核验 URL 和元数据，标记 Evidence 待核验。
- Brave/GDELT/Marketaux 单组失败：其他 Lane 继续，汇总降级原因。
- DingTalk QPS：复用已读 News/字段集合；Editorial 恢复只跑窄链路，不重跑 daily_fetch。
- OpenAI 服务保持可关闭；确定性主题/实体/规则能够完成本次交付。
- 不增加可见业务表，避免额外日常维护成本。

## 13. 成功标准

1. 五条回归样本通过全部覆盖评测。
2. 用户明确纳入的 URL 在一次窄链路运行后可追踪到 News、Event 和所有报告资格。
3. 连续 14 天内，Core/Theme/Trusted Lane 不出现因总候选上限造成的静默全灭。
4. 每次周日发布都验证 Research Queue fingerprint 与当前 accepted Event 集合一致。
5. 缺文档、输入陈旧或证据不完整时 fail closed，不写 sent markers。
6. DingTalk API 调用量不因覆盖审计新增全表重复读取。

## 14. 实施边界

- 当前工作树已有未提交修改；实现必须保留并兼容现有改动，不重置、不覆盖无关文件。
- 先以 TDD 修改纯函数和评测，再更新默认配置、远端 Detect Sources / Entity Catalog 和当前 News。
- 所有远端写入必须在本地测试通过后执行，并逐条回读验证。
- 正式外发仍需用户提供本周新的 Research Document URL。
