# PRD：GBSS AI & Service Intelligence 自动化采编与研究周报系统

> **产品状态（2026-06-20）**：当前生产链路已具备信号采集、人工采纳、周报渲染、图片推送和钉钉文档留档能力；但其分析层仍以规则分类和固定模板为主。本文将 vNext 定义为“证据驱动的研究生产线”。在 `docs/gbss_research_production_spec.md` 完成确认前，不将 vNext 能力视为已实现。

## 1. 产品意图

本项目的目标不是“自动抓新闻”或“把新闻套进模板”，而是把 GBSS 管理层需要的外部信号，稳定转化为可审核、可追溯、可复用、可被管理层用于判断的行业与竞争情报。

用户原本需要在多个搜索工具、新闻源、表格、钉钉群和文档之间人工切换：找信号、判断价值、复制链接、整理标题、做周报、发群同步、留档复盘。这个流程的问题是噪音多、容易漏、周末集中爆发、格式难稳定、后续也很难知道每条结论来自哪里。

系统要解决的核心问题是：

- 每天自动收集支付、金融科技、Contact Center、Voice AI、AIQC、AICC、OPC、服务自动化、风险合规与供应商动态。
- 把候选信号统一写入钉钉 AI 表格 `News`，用户只做“待处理 / 已采纳 / 已拒绝 / 已重复”的单点审核。
- 每日把最新已采纳内容发成轻量 headline，同一条只发送一次。
- 每周生成 `GBSS Weekly AI & Service Intelligence`，输出文字版全文、图片版 One-page Brief、钉钉文档留档、Insights 记录和源记录回写。
- 通过健康检查、运行日志、发布评测集和 launchd 定时任务，让整个链路可验证、可恢复、可持续迭代。

产品的判断标准是：用户不需要每天重新组织信息流，只需要审核高信号输入，并在周报前确认管理层能看清事实、理解判断依据、识别不确定性，并可追溯到原始来源。

### 1.1 vNext 研究生产线目标

vNext 将每周产出从“新闻信号的格式化摘要”升级为“一个主题的证据驱动研究结论”。完整链路为：

`News 信号池 -> Research Queue -> Evidence Bank -> Claim Ledger -> Deep Research Synthesis -> CEO Report / One-page Brief`

- `News` 只负责发现与审核外部信号，不直接等同于战略结论。
- 每周只锁定一个研究主题；专题研究优先回答一个明确、可证伪的管理问题。
- 每个对外事实、数字、P0 判断和管理层结论必须可回链到证据。
- 模型负责检索规划、证据整理、跨来源综合和表达；不得将标题、关键词或固定话术伪装成研究结论。
- One-page Brief 是决策摘要；全文文档是证据、推理和边界条件的阅读入口。

## 2. 用户与场景

### 2.1 核心用户

- GBSS / AI Enablement 负责人：需要快速知道外部市场、竞品、服务 AI、组织转型和供应商能力的变化。
- 管理层阅读对象：需要一页图和一份全文，快速判断“发生了什么、证据是什么、为什么重要、对 GBSS 的含义是什么”。
- 系统维护者：需要通过本地设置中心、钉钉 AI 表格 Config、运行日志和评测集来维护 workflow。

### 2.2 高频场景

- 工作日早晨：系统完成采编，用户收到 News 审核入口，快速处理待审核池。
- 每天上午：系统从已采纳且未 daily 发送的记录中挑选最新内容，推送 Daily Headlines，并回写 `Daily Sent At`。
- 周六中午：锁定下一周专题与研究问题；系统为本周报告冻结候选证据包并生成内部草稿。需要 review 时，仅向审核/运营群推送图片，不写 `Weekly Sent At`。
- 周日中午：系统生成最终周报、全文钉钉文档和图片版 One-page Brief，写入 Insights，向周报群仅推送可放大的图片，并回写 `Weekly Sent At`。
- 每次上线新 feature：先按 `evals/release_evaluation_set.md` 跑完整评测，确认没有破坏 PRD 的关键能力。

## 3. 产品原则

- 审核优先：AI 负责收集、整理、排序、证据整理和表达，人负责是否采纳、研究范围和最终责任。
- 接受态驱动：日报、周报和 Insights 只消费 `News` 中已采纳的记录，不能把待处理、已拒绝或已重复内容带入正式发布。
- 来源可追溯：每条正式输出必须保留源 URL 或源域名链接，不能只留下改写后的无源结论。
- 事实与判断分离：事实、推论和待验证假设必须明确标识；未被证据支持的内容不得作为对外结论。
- P0 稀缺性：P0 不是版式标签。没有满足门槛的真实 P0 时，报告必须明确显示 `P0 = 0`，不得用静态战略话术补位。
- 主题优先：周主题必须驱动检索、证据选择和 Deep Dive，不得只作为报告标题。
- 自动化但可降级：主搜索源失败时优先使用 fallback provider，不因为一个 provider 异常阻塞整个采编。
- 钉钉为当前生产面：当前表格、通知、文档与群发布均以钉钉链路为准。历史 Feishu/Lark 相关表述只作为旧设计，不作为当前主路径。
- News 与 Insights 分层：`News` 存外部信号与审核状态；`Insights` 存周报草稿、终稿、文档链接、图片路径、发送状态和源记录 ID。
- 本地可运营：服务、设置、密钥、运行日志和 launchd 均在本地机器上闭环，不依赖云端服务器。

## 4. 现有解决方案

### 4.1 系统组成

- FastAPI 设置中心：`app.main` 提供本地配置 UI，配置系统、搜索源、钉钉、AI 表格、Prompt、日程和 launchd。
- 设置存储：普通配置写入 `data/settings.sqlite3`，敏感密钥优先写入 macOS Keychain，降级到 `data/secrets.json`。
- 运行日志：`app.run_logs.RunLogStore` 记录每个任务的开始、结束、状态、provider、结果数、错误和 metadata。
- 搜索 Provider：`app.search_providers` 支持 `openclaw_cache`、`manual_seed`、`codex_search`、`gdelt_doc`、`serpapi`、`brave_search` 等配置目标。
- 钉钉 AI 表格：`app.dingtalk_ai_table` 负责表格读写、字段补齐、记录新增、批量更新。
- 周报生成：`app.gbss_report`、`app.publish_format`、`app.weekly_report` 负责选数、打分、分区、内容生成和格式化。
- 图片简报：`app.report_visual` 从同一份 report data 生成 mobile-first One-page Brief，并保存到 `data/reports`。
- 钉钉文档与权限：`app.dingtalk_docs` 和 `app.dingtalk_permissions` 负责创建全文文档、图片版文档并设置组织可读。
- 调度：`app.scheduler` 生成并安装 launchd plist，按配置触发脚本。

### 4.2 数据表职责

- `News` / canonical sheet `oMbefcK`：原始外部信号、标题、来源、发布时间、审核状态、搜索来源、去重关系、Daily/Weekly 发送标记。
- `Insights`：周报草稿和终稿的结构化留档，包括报告类型、状态、周期、源记录数量、源记录 ID、文档 URL、图片 URL、发送状态。
- `Config`：面向运营的配置视图，包括日报/周报开关、日程、输出表、文档 workspace/folder、Prompt 和系统时区。
- `Research Topics`：当前周研究主题和未来四个研究方向，周报读取它来呈现管理层关注的持续研究路线。
- `Research Queue`（已实现基础能力）：每周专题的管理问题、研究假设、检索计划、优先实体、研究状态和证据冻结时间。
- `Evidence Bank`（已实现基础能力）：可引用的原始证据、来源等级、发布日期、关键事实、量化指标、适用范围、相关业务和可信度。
- `Claim Ledger`（已实现基础能力）：报告中每项事实或推论、关联证据、反证/边界条件、置信度和最终使用位置。
- `Research Results`（已实现基础能力）：外部研究 Provider 生成的完整正文，保存在 `Research Content` 字段；同时保留 Provider、Model、Response ID、源记录、证据、调研文档链接和本地原始产物路径。
- `Audit Trail`：每次 workflow 和关键步骤的追加式审计记录，包括输入/输出摘要、状态、耗时、关联记录、报告/文档产物、错误与 metadata；它独立于 `News` 与 `Insights`，用于审查、复盘与质量优化。

### 4.3 任务流程

| 流程 | 脚本 | 当前节奏 | 核心行为 | 成功标记 |
| --- | --- | --- | --- | --- |
| 健康检查 | `scripts/daily_health_check.py` | 每日 00:00 | 检查至少一个 provider 可用、News 表可连通、近 24 小时无失败任务 | 健康时只写日志；异常时钉钉告警 |
| 采编 | `scripts/daily_fetch.py` | 周一至周六 02:00 | Provider 检查、搜索/读取结果、写入 News、标题整理、Publish Date 补齐、语义去重 | `latest-provider-results.json` 更新，News 新增/更新，run log success |
| 催审 | `scripts/daily_remind.py` | 周一至周六 09:00 | 检查 provider，统计 `待处理` 记录，发送 News 审核入口 | 钉钉发送成功，run log 记录 pending 数 |
| 每日出刊 | `scripts/daily_publish.py` | 每日 09:30 | 选择最新已采纳且未 `Daily Sent At` 的记录，发送 Daily Headlines | 成功后回写 `Daily Sent At` |
| 周报草稿 | `scripts/weekly_draft.py` | 周六 12:00 | 选择本周期已采纳且未周报发送记录，生成草稿、全文文档、图片版、Insights 待反馈记录 | 不写 `Weekly Sent At` |
| 周报终稿 | `scripts/weekly_publish.py` | 周日 12:00 | 生成最终 GBSS 周报、全文文档、图片版、Insights 已发布记录，发送钉钉 | 成功后回写 `Weekly Sent At` |

### 4.4 Provider 与 fallback

采编任务先跑 `provider_health_check.py`，再使用主 provider 搜索。主 provider 不可用时，系统尝试 fallback provider。fallback 成功时，采编仍继续进入写 News、标题整理、Publish Date 补齐和去重；同时运行日志记录 `used_provider` 和 pipeline steps。

Provider 设计要求：

- 每个 provider 输出统一记录结构：title、url、source、published_at。
- 文件型 provider 可用于稳定调试和低成本运行。
- API 型 provider 适合作为生产无人值守实时源。
- `codex_search` 是交互式补充，不是凌晨无人值守任务的唯一依赖。

## 5. 关键能力需求

### 5.1 News 入表与审核

- 新候选记录默认进入 `待处理`。
- 必须保留 `Source URL`、`Source`、`Search Provider`、`Search Query`、`Search Batch`、`Discovery Type`、`First Seen At` 等追踪字段。
- `Publish Date` 为空但 URL 可访问时，系统应通过元数据、页面内容或 fallback 自动补齐。
- 语义重复记录应标记为 `已重复`，并通过 `Duplicate Of` 指向主记录。
- 催审通知必须带 News 审核视图链接；配置专属 `approval_view_url` 时优先使用它。

### 5.2 Daily Headlines

- 只选择 `已采纳` 且未写 `Daily Sent At` 的 News 记录。
- 默认每天只发最新 1 条，可通过 `--limit` 调整。
- 发送成功后写回 `Daily Sent At`，避免重复发送。
- 正文中标题不得把源链接藏丢，链接应指向来源或源域名。
- 标题缩短按英文单词数控制，不按字符数误判。

### 5.3 GBSS Weekly AI & Service Intelligence

周报不再是泛行业新闻摘要，而是面向 Ant International GBSS 管理层的 AI 与服务运营情报。它必须回答：

- 哪些外部信号会影响 ePOS、Antom、WorldFirst 或 General GBSS Ops？
- 哪些动态会影响 Contact Center、Voice AI、AIQC、AICC、Service Automation、OPC 或 Vendor Strategy？
- 哪些事项需要管理层行动、PoC、benchmark、风险预警或继续观察？

固定文字结构：

1. `Executive Summary / 本周关键结论与主题判断`
2. `External Signal Radar / 外部动态雷达`
3. `Priority News Cards / 本周重点动态卡片`
4. `GBSS Impact Analysis / GBSS 影响分析`
5. `Actions, Watchlist & Deep Dive / 行动建议、下周观察与深度分析`

周报选择规则：

- 默认使用 `Publish Date` 落在周报 lookback 窗口内的已采纳记录。
- 周日终稿默认排除已写 `Weekly Sent At` 的记录。
- `--recent-count` 用于临时预览最近 N 条，不改变正式窗口规则。
- 周六草稿必须不写 `Weekly Sent At`；周日终稿发送成功后才写。

#### 5.3.1 Research 的定义：从“新闻摘要”到“决策级 Insight”

Research 的工作不是扩大新闻数量，也不是把新闻标题翻译或套入 GBSS 话术。它要回答一个更严格的问题：**在本周出现的外部变化中，哪些事实改变了 GBSS 对重点业务、竞争格局、能力建设、组织模式或风险的判断，改变的机制是什么，证据强度如何？**

每一份周报由两层内容组成：

- **Signal Layer / 信号层**：完整覆盖本周已采纳的重要外部事件，回答“发生了什么”。
- **Research Layer / 研究层**：围绕一个锁定主题，对有限的高价值信号进行证据收集、比较、反证和综合，回答“这意味着什么、为什么是现在、GBSS 应如何理解该变化”。

只有 Research Layer 可以形成管理层 Key Takeaway、Deep Dive 和战略影响判断。Signal Layer 中的单条新闻不能因命中了关键词就自动升级为 Insight。

#### 5.3.2 Topic Framing：先定义问题，再开始检索

每周主题必须来自已锁定的 `Research Queue`，并在检索前完成一页 Research Brief。Research Brief 至少包含：

| 要素 | 要求 |
| --- | --- |
| Primary Question / 主问题 | 一个可回答、可被证据推翻的管理问题，而非宽泛领域名 |
| Decision Context / 决策语境 | 该问题关联的 GBSS 战略主线、重点业务和潜在决策窗口 |
| Hypothesis / 初始假设 | 可为空；必须标为待验证，不得写成结论 |
| Sub-questions / 子问题 | 最多三个，分别覆盖事实、机制和 GBSS 影响 |
| Entity Map / 实体地图 | 需研究的公司、平台、监管方、客户案例、对标组织和反例 |
| Evidence Plan / 证据计划 | 每个子问题需要的来源类型、最低证据数量及预期指标 |
| Disconfirming Evidence / 反证方向 | 哪些事实出现时会推翻或显著削弱初始假设 |

主问题应优先采用“变化 - 机制 - 影响”的形式，例如：

- “某类支付基础设施变化，是否正在重构 Merchant Service / Antom / WorldFirst 的支持责任边界？”
- “Voice AI 在受监管 Contact Center 从 Pilot 进入 Production 的门槛是否已经满足？哪些能力仍是约束？”
- “OPC Model 的最小责任单元，是否能提升 AI 与 A2A 协作下的服务结果、质量与治理？”

“AI 正在改变行业”或“某公司发布了产品”不能单独作为 Research Topic。

#### 5.3.3 Source Strategy：为不同问题寻找最接近事实的来源

可靠性首先取决于来源离事实有多近，而不是来源数量。研究必须建立 Source Map，并按结论类型选择来源：

| 研究对象 | 首选 T1 证据 | 必要补充 | 不足以单独支持结论的材料 |
| --- | --- | --- | --- |
| M&A、融资、估值、财务表现、市场覆盖 | 公司公告、交易文件、财报、投资者材料、交易所/监管披露 | 买卖双方公告、电话会、可信独立报道 | 转载、融资数据库、社媒帖子 |
| 产品/能力发布 | 官方产品文档、版本说明、官方演示、合作公告 | 真实客户部署、技术评测、独立报道 | 仅供应商营销页或新闻标题 |
| 客户 ROI、Production readiness、运营效果 | 可核验客户案例、客户方公告、披露的运营指标 | 多个独立客户案例、行业基准、失败案例 | 未说明样本、场景或时间范围的供应商宣称 |
| 监管、合规、跨境数据与风险 | 监管机构、法律/政策原文、官方执法/指引 | 权威法律解读、受监管机构披露 | 二手转述或未经引用的媒体摘要 |
| Contact Center、AIQC、Voice AI、AICC 能力对标 | 平台产品文档、技术文档、客户部署、财报/电话会 | 独立评测、客户案例、实施边界和限制 | 单一 vendor 的能力清单 |
| OPC Model、组织和 A2A operating model | 公开的 operating practice、组织设计案例、可观察的职责/指标/接口 | 至少两个独立行业案例、失败或适用边界 | 将“团队小”或“使用 AI”直接等同于 OPC 最佳实践 |

来源分级使用 T1/T2/T3，但不以分级代替判断：

- **T1 / 原始权威来源**：直接参与事件的一方或有法定/官方披露责任的一方，如公司、交易所、监管机构、合作双方、客户方、产品官方文档、财报和电话会。
- **T2 / 独立验证来源**：能说明信息来源、方法或样本的主流媒体、专业研究、技术评测或法律分析。
- **T3 / 线索来源**：vendor marketing、聚合站、数据库、博客、社交内容。T3 用于发现线索，不能独自支撑 P0、ROI、市场规模、客户生产部署或管理层结论。

每条关键来源还需按五项记录质量：`Authority`（权威性）、`Proximity`（与事实的距离）、`Transparency`（方法与指标透明度）、`Corroboration`（可交叉验证性）、`Recency`（时效性）。来源很多但都来自同一份 vendor 新闻稿，仍视为单一证据链。

#### 5.3.4 Evidence Development：用原子事实建立可验证证据链

研究过程必须先产出 Evidence Pack，再写报告。Evidence Pack 的最小单位不是“文章摘要”，而是一个可以被独立核查的原子事实。例如：

`[事实] 公司 X 于 YYYY-MM-DD 宣布 Y；适用场景为 Z；已披露指标为 N；来源为 Evidence-012。`

每条证据必须保留：原始 URL、标题、发布日、访问日、来源等级、原文事实、数字及口径、适用场景、涉及实体、支持或挑战的假设，以及审核状态。模型不得从标题、搜索摘要或自身记忆中补写未被来源支持的数字、客户范围、能力状态或因果关系。

证据构建采用以下顺序：

1. **Discover / 发现**：从 News 和专题检索中发现候选事件与来源。
2. **Verify / 验证**：回到原始页面，确认事件、时间、主体、范围和数字；确认原报道并未被更新、撤回或否认。
3. **Triangulate / 交叉验证**：对高影响事件寻找第二条独立证据，尤其是财务、客户部署、合规、ROI 和竞争判断。对于自利性强的 vendor/customer 宣称，必须补充外部证据或明确标注“vendor-reported”。
4. **Contextualize / 置于背景**：补充历史基线、竞品对比、客户/地区/业务范围和已知限制，避免把单点发布误读为行业普遍趋势。
5. **Challenge / 反证**：主动检索失败案例、实施约束、未披露信息、竞争替代方案和不适用场景；反证不是附注，而是判断置信度的输入。
6. **Freeze / 冻结**：在周四的 Evidence Freeze 后为本周报告锁定来源版本；后续新信息进入下一期或作为明确的更新说明。

对于 Deep Dive，至少需要 6 条已验证证据、至少 3 条 T1/T2 来源，并且必须覆盖“支持结论的证据”和“限制/反证证据”。无法达到门槛时，只能输出“Signal Brief / 初步观察”，不得以 Deep Research 名义输出确定性战略结论。

#### 5.3.5 Insight Synthesis：从事实到 GBSS 判断的六层框架

参考高质量 Competitor Weekly Intelligence 的写法，每条 Key Takeaway 必须具备以下六层。它不是固定字数模板，而是一条完整推理链：

| 层级 | 必须回答的问题 | 写作标准 |
| --- | --- | --- |
| 1. Event / 事件 | 谁在何时做了什么？ | 明确主体、发布日期和已确认变化；不把传闻写成事实 |
| 2. Evidence / 证据 | 哪些数字、范围、产品能力或监管事实支持它？ | 保留指标口径、时间范围和来源 ID；无指标时不虚构量化表达 |
| 3. Market Mechanism / 行业机制 | 该变化改变了价值链、成本结构、竞争位置、服务责任或进入壁垒的哪一环？ | 解释“为什么重要”，不能停留在“这是一个重要动态” |
| 4. GBSS Relevance / GBSS 关联 | 它具体影响 Merchant Service / ePOS、Antom、WorldFirst、General GBSS Ops、AICC、AIQC、Voice AI、Contact Center 或 OPC 的哪一项？ | 指向具体业务场景、能力或治理问题；无直接关联必须明示 |
| 5. Strategic Implication / 战略含义 | 若趋势延续，GBSS 当前假设、能力优先级、风险边界或竞争判断需要如何更新？ | 使用条件化表达，清楚区分已证实事实与分析推论 |
| 6. Confidence and Watch Condition / 置信度与观察条件 | 结论有多可靠？下周看到什么会加强、削弱或推翻该判断？ | 标注 High/Medium/Low，并给出具体可观察的触发条件 |

推荐的 Key Takeaway 表达形态为：

`Entity / Event: Confirmed change + key metric or scope. Market mechanism: what position, cost, control point or operating model changes. GBSS implication: the specific business/capability affected, stated as fact or conditional inference. Confidence: level + source IDs + what to monitor next.`

这套结构要求报告像“结论 + 证据 + 判断”，而不是“新闻标题 + 泛化影响”。例如，涉及交易、融资、产品扩张或竞争动作时，必须写清楚事件是否已确认、关键交易/财务/产品范围、对竞争位置的影响、与 WorldFirst/Antom/Merchant Service 的具体比较，以及结论的边界条件。

#### 5.3.6 GBSS Causal Mapping：防止“任何新闻都相关”

外部信号必须经过因果映射，才能进入 GBSS Impact Analysis。映射至少包含：

`External change -> affected actor/process -> operating mechanism -> GBSS business/capability -> measurable outcome or risk -> confidence`

可接受的映射示例：

`跨境支付平台扩展企业账单与对账能力 -> 商户资金/对账流程被平台吸收 -> 客户期望和支持问题类型变化 -> WorldFirst 跨境 SMB 支持与 Merchant Service case taxonomy -> 一次解决率、case volume、培训与知识库覆盖 -> Medium confidence。`

不可接受的映射示例：

`某公司发布 AI 产品 -> AI 很重要 -> Antom/WorldFirst 应采用。`

对于每个重点业务，研究必须回答：

- **Merchant Service / ePOS**：是否改变商户入驻、问题分流、线下/门店服务、case 处理或风险控制？
- **Antom**：是否改变 merchant onboarding、KYC/KYB、支付支持、渠道报备、case follow-up、支付授权或合规责任？
- **WorldFirst**：是否改变跨境 SMB、收款/付款、资金管理、全球服务、争议处理或 B2B support 的竞争条件？
- **General GBSS Ops**：是否改变服务运营、AICC、AIQC、Voice AI、知识治理、组织设计、OPC、供应商或风险治理？

“当前无直接关联”是允许且有价值的结论。报告不得因为业务标签需要覆盖，就人为把每条新闻映射到所有重点业务。

#### 5.3.7 Deep Dive 标准：解释趋势，而不重复新闻

Weekly Deep Dive 必须围绕一个已经被本周证据支持、但仅靠单条新闻无法回答的问题展开。它至少应包含：

1. **Thesis / 核心命题**：对研究问题的条件化回答，而不是主题复述。
2. **Evidence Base / 证据基础**：支持命题的主要事实、关键数据、来源分布与已知信息缺口。
3. **Competitive and Industry Reading / 竞争与行业解读**：比较至少两个相关参与者、模式或案例，说明差异而非罗列公司。
4. **Mechanism and Boundary / 机制与边界**：趋势何时成立、在什么场景失效、实施的技术/运营/合规约束是什么。
5. **GBSS Strategic Reading / GBSS 战略解读**：对业务支持、组织、OPC、内部效率、Contact Center 与治理六条主线的具体影响。
6. **Counter-case / 反例**：至少一个可能削弱主要判断的替代解释、失败模式或证据缺口。
7. **Watch Conditions / 后续观察条件**：未来 30 天需要验证的外部信号，而非泛化的行动清单。

OPC Model 研究尤其不能把“小团队”或“使用 Agent”视为最佳实践的充分证据。必须研究最小单元承担的业务结果、目标/指标、决策权、服务接口、质量机制、与其他单元或 Agent 的协作方式，以及在何种规模与治理条件下成立。

#### 5.3.8 Research Quality Rubric：以研究质量而非篇幅验收

每周最终报告应在发布前按以下维度评分并存档：

| 维度 | 核心问题 | 最低要求 |
| --- | --- | --- |
| Source Integrity / 来源完整性 | 关键事实是否来自最接近事实的来源？ | 100% 重点卡片有 URL、发布日期和来源等级 |
| Evidence Sufficiency / 证据充分性 | 是否有足够证据和交叉验证支撑结论？ | Deep Dive 达到 6 条证据和反证要求；P0 达到 P0 门槛 |
| Analytical Depth / 分析深度 | 是否解释机制、比较与边界，而非复述新闻？ | 每条 Key Takeaway 通过六层框架 |
| GBSS Specificity / GBSS 特异性 | 是否明确到业务、能力、流程或风险，而非泛化 AI 术语？ | 每条影响均可映射到具体 GBSS 场景或标注无直接关联 |
| Calibration / 判断校准 | 事实、推论和假设是否区分？不确定性是否透明？ | 100% 材料结论有 Claim Type 和 Confidence |
| Novelty / 新信息密度 | 是否提供新闻标题之外的竞争、机制或战略判断？ | Deep Dive 至少包含一个经证据支撑的非显而易见判断 |
| Executive Readability / 管理层可读性 | CEO 是否能在 30 秒理解本周核心变化？ | One-page 只保留已验证的三条以内重点和一条深度判断 |

如果 Research Quality Rubric 未达到最低要求，系统应发布为“Signal Brief / 信号简报”，明确说明本周不具备足够证据形成 Deep Research，而不是用更多排版或泛化文字掩盖研究不足。

### 5.4 优先级评分

周报优先级按七个维度计算：

| 维度 | 权重 |
| --- | --- |
| Business Criticality | 25% |
| GBSS Strategic Relevance | 20% |
| Contact Center Relevance | 15% |
| Actionability | 15% |
| Operating Model Impact | 10% |
| Risk / Compliance Impact | 10% |
| Industry Signal Strength | 5% |

优先级含义：

| 分数 | 优先级 | 含义 |
| --- | --- | --- |
| 85+ | P0 | 需要管理层立即关注 |
| 70-84 | P1 | 进入研究、PoC、benchmark 或流程优化 |
| 50-69 | P2 | 持续观察 |
| <50 | Watch | 仅记录趋势 |

vNext P0 资格门槛：

1. 事件本身已被可靠来源确认，且有可引用发布日期；
2. 至少有一条一手/权威证据；
3. 具有具体而非泛化的 GBSS、重点业务、风险、预算或组织影响；
4. 需要在未来 30 天内做管理层判断、风险处置、资源安排或研究立项；
5. 结论在 `Claim Ledger` 中被审批，且置信度为 High 或 Medium。

任一条件不满足时，不得标为 P0。P1 表示值得进入调研、PoC 或 benchmark；P2 与 Watch 不进入管理层重点动态区。

### 5.5 图片版 One-page Brief

图片版不是装饰物，而是用于钉钉群同步、管理层会议快速扫描和转发的主要阅读入口。它必须从同一份周报数据生成，包含：

- Weekly Theme
- Business & Signal Radar
- Top Priorities
- GBSS Strategic Impact
- Weekly Deep Insight
- 全文报告入口或二维码
- AI GBSS 群二维码

群内推送只发送图片，不再单独发送文字版。全文钉钉文档仅作为图片二维码的详情入口。

如果图片上传失败，系统必须标记发送失败并触发重试/运营告警；不得用文字版群消息替代图片推送。

### 5.6 Insights 与文档留档

- 草稿保存为 `Report Type = Draft`，状态为 `待反馈`。
- 终稿保存为 `Report Type = Final`，发送前可为 `待发送`，发送成功后为 `已发布`。
- Insights 必须记录源 News record IDs，保证每份报告能追溯回输入记录。
- 全文文档和图片版文档应创建在配置的 DingTalk Docs workspace/folder 下，并设置组织可读。

### 5.7 配置与调度

- 本地设置中心负责编辑真实配置。
- `Config` 表负责把关键配置同步到钉钉侧，便于查看与调整。
- 配置变更如果影响 launchd，必须重新安装并验证 plist 与 `launchctl` 状态。
- 日程默认值以 `app.models.ScheduleSettings` 为准：健康检查每日 00:00，采编周一至周六 02:00，催审周一至周六 09:00，日报每日 09:30，周报草稿周六 12:00，周报终稿周日 12:00。

### 5.8 Audit Trail / 过程审计

审计目标不是只记录“任务是否成功”，而是让任意一次新闻采集、审核提醒、日报、周报草稿或终稿，都可以回答：谁/哪个任务在何时执行了哪个步骤、使用了什么输入、产出了什么、影响了哪些记录、生成了哪个文档、是否发送成功，以及失败发生在哪里。

- `Audit Trail` 必须是独立、追加式 AI 表格；运行记录不得覆盖历史步骤，也不得混入 News 或 Insights。
- 每条记录至少包括：Audit Event ID、Run ID、Workflow、Stage Code、Stage Name、状态、模式（live/dry-run）、开始/结束时间、输入/输出摘要、结果数量、关联 Sheet、Source Record IDs、Report ID、Artifact URL/Path、错误和 Metadata JSON。
- 核心 workflow 至少记录开始、数据选择/读取、核心处理、文档/图片产物、通知、状态回写和最终完成/失败；采编还必须记录 provider、News 写入、标题整理、发布时间补齐和去重步骤。
- 任何失败必须写入失败步骤和 workflow 最终失败记录，且保留错误文本；审计表不可用时不能阻断业务主流程，但本地 RunLog 必须保留审计写入失败原因。
- 审计记录需能通过 Run ID 串起完整流程，并能通过 Source Record IDs、Report ID 和 Artifact URL 回溯到 News、Insights、钉钉文档和图片。
- 审计表用于每周质量复盘：统计来源/步骤失败率、平均耗时、发送失败、无来源报告、P0 审核异常和研究质量门禁失败。

## 6. 非目标

- 不做无审核的全自动事实判断和正式发布。
- 不把 Codex 当前会话当作唯一生产搜索源。
- 不把 `Daily Headlines Review` 当作默认目标表；当前 canonical 目标是 `News` / `oMbefcK`。
- 不在 `News` 中存周报成品；周报成品属于 `Insights` 与 DingTalk Docs。
- 不为了新功能牺牲 accepted-only、来源可追溯和发送去重这些底线。

## 7. 成功指标

- 采编任务：主源失败但 fallback 可用时仍能完成 News 入表链路。
- 审核效率：用户只需要处理 `待处理` 池，不再人工找链接和整理标题。
- 发布准确性：日报和周报只消费已采纳内容，并正确写回发送标记。
- 追溯性：任意周报都能从 Insights 找到文档、图片、源记录 ID 和发送状态。
- 过程可审计性：任意 workflow 可在 Audit Trail 中按 Run ID 还原关键步骤、输入输出、关联记录、产物和异常。
- 稳定性：每日健康检查可发现 provider、News 表和近期任务异常。
- 可回归：每次 feature 上线前，`evals/release_evaluation_set.md` 的完整评测能跑通或明确记录豁免。

## 8. 下一步计划

### P0：发布前质量门禁

- 将 `evals/release_evaluation_set.json` 作为发布评测集基线。
- 每次上线前执行完整 release eval，并把结果记录到发布说明或运行日志。
- 为评测集中已能自动化的项补充 unittest 或 dry-run 脚本，减少纯人工检查。

### P1：线上运行闭环

- 固化 launchd 安装后验证流程：plist 内容、`launchctl print` 状态、下一次触发时间。
- 增强 health check：加入 `Insights`、`Config`、`Research Topics` 表连通性检查。
- 增强 DingTalk 发送前检查：群路由、真实 mention、图片上传、文档权限。

### P2：证据驱动研究能力

- 已建立 Research Queue、Evidence Bank 和 Claim Ledger，并在 `Config` 中保留其表 ID；每周 research preparation、报告渲染和导入综合结论均写入 Audit Trail。
- 已实现证据分级、一手来源优先、事实/推论/假设标识、P0 不自动补齐，以及 `Signal Brief` / `Deep Research Ready` 质量门禁。
- 下一步接入受控的 Deep Research 检索与综合执行器：仅允许基于冻结的 Evidence Pack 产出带引用的结论和全文报告，导入后仍需人工审核 Claim Ledger。
- 下一步将专题研究计划驱动到检索策略，而不是仅使用固定关键词矩阵。
- 继续替换残余的通用 Impact、Watchlist 与 Deep Dive fallback 话术，优先覆盖有已审批 Claim Ledger 的研究主题。

### P3：内容质量与评估

- 为 GBSS 周报增加历史对比能力：本周信号与上周/上月主题变化。
- 将人工拒绝原因沉淀为分类样本，优化后续信号筛选。
- 建立 report quality rubric：证据覆盖、来源完整性、推理完整性、管理层可读性、无幻觉、无重复。

### P4：Provider 与检索扩展

- 增加 provider 级别的结果质量评分和成本统计。
- 对 Brave/SerpAPI/GDELT/OpenClaw/Codex Search 的命中率做周期性对比。
- 支持按 Research Topics 动态生成搜索 query，而不是只用固定关键词矩阵。
