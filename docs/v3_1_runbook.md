# GBSS 外部事件情报系统 v3.1 运行手册

## 安全默认值

- 本项目直接使用当前 workspace，不执行数据库 migration，也不创建另一套本地业务数据库。
- Event、Entity、Score、Alert、API Usage、Evidence、Claim 和 Insights 等业务数据均保存到现有钉钉 AI 表格。
- 本地 `data/settings.sqlite3` 只保存配置与 RunLog，不作为业务数据源。
- 功能默认使用 `event_intelligence.enabled=false`、`critical_scan_enabled=false` 和 `weekly_input_mode=news`，通过发布门禁后再切换。
- 单元测试和 Golden Eval 不会调用 OpenAI 或外部数据源。
- 在 API Key 和 `API Usage` 表配置完成前，OpenAI 分类保持关闭。付费研究还必须满足 `Research Queue.Approval Status=Approved`。

## 直接运行当前 Workspace

```bash
.venv/bin/python scripts/eventize_news.py --dry-run --days 14
.venv/bin/python scripts/eventize_news.py --apply --days 14
.venv/bin/python scripts/critical_event_scan.py --dry-run
.venv/bin/python scripts/v3_1_kpi_report.py
```

当前 workspace 已与钉钉 AI 表格连接。正常执行时，代码直接读写现有 `News`、`Event Cases`、`Event Entities`、`Event Sources`、`Event Scores`、`Entity Catalog`、`Alert Log`、`API Usage`、`Evidence Bank`、`Claim Ledger` 和 `Insights`。表 ID、adapter 开关、模型配置和 feature flags 由现有 Settings/Config 管理。

| 数据位置 | 用途 |
| --- | --- |
| 钉钉 AI 表格 | 全部业务记录、审核状态、Evidence、Claim、成本账本和 Audit Trail |
| `data/settings.sqlite3` | 本地配置、任务 RunLog、待补写审计事件 |
| `data/reports/` | Weekly 和 One Pager 的本地渲染产物 |

关键事件扫描的 `--dry-run` 会读取真实的官方 IR/RSS、ticker 和 GDELT 数据，但不会写入 News、创建提醒或调用 OpenAI。发布时间早于 `event.critical_scan_lookback_days`（默认 7 天）的信号会被丢弃。正式扫描只保存和提醒本次扫描新发现的 News 所关联的 Event Case，不会重新事件化全部历史 News。

`v3_1_kpi_report.py` 是只读报告，包含最近 7 天的信号与 Event 数量、最近 7 天和当前有效的关键事件数量、按关联 News 的 Publish Date → First Seen At 计算的日期粒度发现时差、关键事件当日/次日命中率、业务线映射、明确 Event Type 覆盖率、候选/已采纳事件追溯率、等待 News 审核的 Event 数量、自动最终 P0 违规数以及最近 28 天 API 成本。

只有关联 News 在统计窗口内首次进入系统时，对应 Event 才计入本周新增，因此历史回填不会虚增周度产量。四周观察从首个成功的生产 `critical_event_scan` 开始；在此之前发布、上线后补录的关键事件单列为 `critical_backfill_events_7d`，保留历史滞后证据，但不计入上线后的时效 SLA。Event 观察不足 28 天时，报告返回 `observation_incomplete`；单次快照全部为绿色不代表已经证明四周运行成功。由于来源的 Publish Date 当前只有日期粒度，四小时关键扫描 SLA 应通过 job run 时间戳或注入测试信号验证，不能从该时差指标直接推断。

## 唯一人工审核入口

日常只审核 `News`：

1. `News=已采纳` 表示认可该信息来源，并允许其进入 Daily Report 或 Signal Brief。
2. 系统自动生成或更新关联 Event Case 的业务线、Event Type、评分、优先级候选和影响假设；不需要再次手工采纳 Event。
3. Event Case 至少关联一条已采纳 News 时，Event 状态自动变为 `已采纳`。
4. `Evidence=Verified` 和 `Claim=Approved` 只用于 Evidence-backed Report、Deep Research 或确定性战略结论，不阻止事实型 Daily Report 和 Signal Brief。
5. 如果人工决定最终优先级为 P0，仍必须设置 `P0 Approval Status=Approved`，并填写 `Reviewer` 和 `Reviewed At`。自动化流程永远不会批准最终 P0。

Signal Brief 会保留系统生成的 `P0 Candidate`、P1、P2、业务线和 Event Type，便于管理层识别重要候选；但在 Evidence/Claim 门禁通过前，报告中的 GBSS 影响、效率机会、组织模式含义和建议动作必须明确显示为“待核验/不输出结论”。即使 OpenAI Deep Research 已产生结果，也不能绕过该门禁。

审核提醒入口应指向 News 审核视图。关键 Event 提醒用于展示系统分类和优先级候选，最终操作仍是审核其关联 News。

## 发布门禁与正式切换

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_v3_1_evaluation.py
.venv/bin/python scripts/cutover_v3_1.py --dry-run
.venv/bin/python scripts/cutover_v3_1.py --apply
```

`cutover_v3_1.py --dry-run` 会重新运行自动化门禁，并确认至少一个 Event 关联了已采纳 News，且 Source URL 和 Publish Date 完整。条件未满足时，命令会以 blocked 状态退出，并且不会修改配置。

`cutover_v3_1.py --apply` 会再次执行同样的门禁。全部通过后，它会启用 Eventize 和每日六次关键事件扫描，将 Weekly 输入切换到 Event Case，并且只安装新增的关键扫描 launchd 任务。

## 回滚

```bash
.venv/bin/python scripts/cutover_v3_1.py --rollback
```

回滚会立即执行以下操作：

- 将 `weekly_input_mode` 恢复为 `news`。
- 关闭 Eventize 和关键事件扫描。
- 移除关键扫描 launchd 任务。

回滚不会删除 Event 相关表、News 追溯关系或 Audit Trail 历史。

## 数据源与密钥配置

密钥只能保存在 Settings UI、SecretStore 或进程环境变量中。不要将密钥写入本文档、Config 表或源代码仓库。

- OpenAI：`openai_service.api_key` 或 `OPENAI_API_KEY`。
- Marketaux：`event_intelligence.marketaux_api_key`。
- Firecrawl：`event_intelligence.firecrawl_api_key`。
- Alpha Vantage：`event_intelligence.alpha_vantage_api_key`。
- 钉钉审核提醒：Daily webhook、签名密钥以及用于真实 @ 的 `at_mobiles`。
- 钉钉正式发布：Weekly webhook 和签名密钥。

Official、GDELT 和 yfinance adapter 不需要商业 API Key。Marketaux、Firecrawl 和 Alpha Vantage 默认关闭，只有明确启用后才会运行。

## 成本控制

应用内默认成本上限如下：

| 范围 | 上限 |
| --- | ---: |
| 单次 INGEST 调用 | 0.30 USD |
| 单次 Insight/Research 调用 | 1.50 USD |
| 每日 | 1.00 USD |
| 每周 | 5.00 USD |
| 每月 | 25.00 USD |

每次付费调用前，系统必须先成功写入 Audit Trail 预检事件和 `API Usage` 预算预留记录。完成或失败记录复用同一个 Call ID，确保 append-only 账本只计算一次成本。

预算、熔断、Audit Trail 或人工审批任一环节不可用时，系统会在调用数据源之前跳过或失败关闭。还应在 OpenAI Project 中单独配置月度预算，作为系统外部的 hard cap。

## 日常运行

### News AI 预审与午前兜底

- 08:50：`ai_review_suggest.py` 保证 News 全表都有明确 `AI Status`，只允许 `已采纳 / 已拒绝 / 已重复`，不得留待处理。首次全量回填，之后根据 `AI Review Version + AI Review Fingerprint` 只更新新增、Event 变化或学习规则变化的记录。此步骤不修改最终人工 `Status`，也不产生 OpenAI 费用。
- 09:00：运营群审核卡片展示人工待处理数量、AI Status 三态分布，以及上一轮已识别的人机一致率、覆盖方向和主要差异。审核人仍在 News 表的 `Status` 字段处理，人工结果永远优先。
- 11:50：`ai_review_deadline.py` 只对人工 `Status` 仍为 `待处理`、`AI Status=已采纳`、置信度不低于 0.85，且 Event Case ID、Source URL、Publish Date、Business Line、Event Type 完整的 News 写入最终 `Status=已采纳`。AI 已拒绝或已重复不会自动改变最终 Status，继续保留给人工。
- 12:00：Daily Report 正常读取最终生效的 `Status`。AI 兜底采纳只允许事实型发布，不会批准 Claim、Deep Research 或最终 P0。

人工处理或后续修正会写入 `Review Decision Source`、`AI Feedback Outcome`、`Human Override Status`、`AI Feedback At`、`AI Difference Category` 和 `AI Difference Summary`。`Matched` 表示人工与 AI 一致，`Overridden` 表示人工推翻了 AI 明确建议。

差异类别会区分：漏判重复、重复误判、实体误匹配、来源无正文、信息量过薄、PR/宣传、投资评论、弱相关、Eventization 缺口和 Event Type 识别不足。人工填写的原始 `Rejection Reason` 永远保留，标准类别只用于统计和规则评测。

系统每天直接从 News 人工历史重算学习规则，不做黑盒在线训练：同一个 `Event Type × Business Line` 至少有 5 条人工决定，且其中一种状态占比不低于 80%，才允许影响下一轮 AI Status。显式重复、缺 Source URL、缺 Publish Date 始终是硬门禁。学习规则若推翻原有规则，置信度最高为 0.84，因此不会触发 11:50 自动采纳；只会给审核人一个更贴近历史操作的建议。

每次 `ai_review_suggest` 的 RunLog 与 Audit Trail 都保存 `learning_version`、每条规则的 segment/status/support/agreement，以及当日 reviewed/matched/overridden、主要差异和覆盖方向。排查时优先查看最新 `ai_review_suggest` 的 metadata；不需要从群消息反推规则。

### 同事件重复处理

- News 层：完全相同或语义近似的来源继续使用 `已重复 + Duplicate Of`。
- Event 层：同一实体、同一事件类型、同一标准化金额的融资报道，即使官方公告和媒体跟进相隔最多 7 天，也聚合为一个 Event Case。
- 实体消歧：印度/NPCI/即时转账语境中的 `UPI` 映射到 `Unified Payments Interface`；只有明确 UnionPay 文案或官方域名才映射 `UnionPay International`。Catalog 修正后，旧 Event Entity 关系保留但标为 `superseded`，不可继续视为活跃实体。
- 优先级防膨胀：合作伙伴认证/专项计划即使使用 `launches`，也归为 `Channel_Partner`，不会仅凭动词升级成 Strategic/P0 Candidate；官网列表标题末尾的 View/Read more/Learn more 会自动清理。
- 历史上已拆开的 Event 不删除：唯一 canonical Event 保留全部来源，旧 Event 改为 `已归档` 并写入 `Merged Into Event ID`。
- 每次完整 Eventize 后，非归档 Event 状态按全部关联 News 收敛：任一 News 已采纳则 Event 已采纳；没有待处理/已采纳且全部重复则 Event 已重复；终态集合中存在人工拒绝则 Event 已拒绝。历史已归档 Event 不会被状态同步重新打开。
- `已归档` Event 永远不进入 Daily Report、Weekly Insight 或 One Pager；已发送 News 的发送标记仍有效，合并后不会再次播报。

人工检查或修复命令：

```bash
.venv/bin/python scripts/eventize_news.py --dry-run --days 14
.venv/bin/python scripts/eventize_news.py --apply --days 14
.venv/bin/python scripts/ai_review_suggest.py --dry-run
```

- 完整 INGEST：每天 02:00。
- 运营群 News 审核提醒：每天 09:00，只包含 `Publish Date=前一日`、状态为 `待处理` 且已关联 Event Case 的要闻；卡片显示准确审核日期和标题。历史、缺日期和未匹配 Event 的记录不进入当天批次。
- 钉钉机器人交付成功必须同时满足 HTTP 成功和返回体 `errcode=0`（或未返回错误码）。HTTP 200 但 `errcode` 非零仍按失败写入 RunLog/Audit，并保留钉钉错误内容；不能仅凭 HTTP 200 判断群内已收到消息。
- 02:00 采集成功不发运营群消息，只写 RunLog/Audit Trail；采集失败仍告警。这样运营群的正常审核入口只有 09:00 昨日要闻卡片。
- 关键事件扫描：每天 01:00、05:00、09:00、13:00、17:00、21:00。
- Daily Report：每天 12:00，发送尚未发布且至少关联一条 `News=已采纳` 的 Event Case；群消息只展示业务线、事件类型、标题、来源链接和 Publish Date，不展示 Event / Event Source / Evidence / Claim 内部 ID，完整追溯关系仍保存在钉钉业务表和 Audit Trail。发送到 `AI_Intelligence` 时不 @ 任何人。回看 7 天用于接住延迟审核，发送标记防止重复。12:00–13:00 为人工检查窗口，13:00 由负责人转发到另一个内部群，系统不自动转发。
- 统一时区：`Asia/Kuala_Lumpur`。
- 审核提醒群：`BOT监控审核群`。
- 正式发布群：`Daily News`。
- `daily_health_check.py` 会将遗留的本地 running 任务标记为失败，并补写暂存的 Audit Trail 事件。
- Event 模式无法读取 Event/Evidence/Claim 追溯关系时，Daily Report 和 Weekly 流程会失败关闭并提醒，不会静默退回 News 模式。

查看当前运营指标：

```bash
.venv/bin/python scripts/v3_1_kpi_report.py
```

## 验收清单

- 当前 workspace 能读取全部钉钉业务表，所需字段和表 ID 配置完整。
- Entity Catalog 包含试点所需的全部核心业务、竞对、监管机构和能力实体。
- 静态评测达到阈值，自动最终 P0 违规数保持为 0。
- Event 审核提醒只发送到审核群，并包含真实 webhook @。
- Daily Report、Weekly Insight 和 One Pager 均展示 Event、Evidence、Claim、Source URL 和 Publish Date 追溯关系。
- 独立来源或 Claim 门禁不满足时，输出必须标记为 `Signal Brief`。
- 回滚能够恢复 News 输入，并且不删除任何新增数据。
