# PRD：GBSS AI & Service Intelligence 自动化情报与研究生产系统

> Version: 2.1
> Last-Updated: 2026-07-05
> Status: superseded
> Supersedes: none

> [!WARNING]
> 本文档已被 [v3.1 PRD](prd_v3_1_event_intelligence.md) + [可执行规格](v3_1_event_intelligence_spec.md) 取代，仅保留历史背景。任何实现或验收冲突均以后两者为准。

**版本：** 2.1
**更新时间：** 2026-06-22
**系统名称：** Weekly Headlines / Weekly Insight
**当前生产面：** 本地 Python 服务 + macOS launchd + 钉钉 AI 表格/文档/群机器人
**本文定位：** 这是产品与运营合同。它区分已上线能力、受配置或审批门控的能力、以及明确不属于当前版本的能力；不把愿景当作既有功能。

---

## 1. 一句话定义

这是一个以人工审核为质量控制环节的行业情报系统：它自动发现、校验、归档并发布 GBSS 相关外部信号，最终交付 Weekly Headlines 与 Weekly Insight 两类管理层内容。

系统不是单纯的新闻爬虫，也不是自动生成观点的报告器。它的核心价值是：

`外部信号 -> 人工采纳 -> 可追溯发布 -> 证据驱动研究 -> 管理层行动判断`

---

## 2. 问题与目标

### 2.1 当前问题

GBSS 团队需要持续关注支付、金融科技、Merchant Service、Contact Center、Voice AI、AIQC、AICC、服务自动化、治理与供应商动态。纯人工流程存在以下问题：

- 多来源切换，容易遗漏关键变化。
- 线索、事实、判断、行动建议混在一起，后续无法回溯。
- 日报和周报依赖临时整理，节奏不稳定。
- 搜索源失效、群消息发错、链接不可点击、重复新闻等运营问题难以及时发现。
- 周报容易退化为“新闻标题 + 泛化观点”，没有明确研究问题、证据门槛和不确定性说明。

### 2.2 目标

1. 自动维护高质量的 `News` 信号池，人工只审核是否采纳。
2. 自动向审批群发送可直接进入审核视图的提醒。
3. 让审核者只处理 Daily News Review，让管理层分别收到 Weekly Headlines 与 Weekly Insight。
4. 将 Weekly Insight 升级为“信号层 + 研究层”：没有证据门槛时只发布 `Signal Brief`，不伪装为 Deep Research。
5. 让每一次搜索、入表、审核、生成、群发和失败都可审计、可恢复。

### 2.3 非目标

- 不替代人工对新闻是否相关、研究问题是否重要、最终周报是否适合管理层的判断。
- 不承诺所有网页都能被抓取或准确提取发布日期；反爬、付费墙和缺失元数据是外部限制。
- 不把任何单一 provider、搜索摘要或模型输出视为最终事实来源。
- 当前不做多租户、云端 SaaS、跨企业权限系统或移动端原生 App。

---

## 3. 用户、角色与责任

| 角色 | 核心工作 | 系统责任 | 人工责任 |
| --- | --- | --- | --- |
| 情报审核者 | 处理待审核 News | 汇总候选、去重、提供来源和审核入口 | 采纳/拒绝、填写拒绝原因 |
| 研究负责人 | 锁定每周专题与研究问题 | 准备证据候选、研究计划、质量门禁 | 批准研究计划、审核关键 Claim |
| 管理层读者 | 阅读 Weekly Headlines 与 Weekly Insight 并决定行动 | 输出清晰摘要、全文证据入口、来源追溯 | 对行动、资源和风险作决策 |
| 系统维护者 | 维护配置与运行质量 | 提供本地设置、日志、Audit Trail、失败告警 | 管理 provider、群路由、密钥、排程 |

### 3.1 人工门控原则

以下是明确的人工业务门：

1. `News.Status` 的采纳/拒绝。
2. Deep Research 计划的批准，或在分析窗口前记录的自动通过。
3. Claim Ledger 中战略性主张的批准，或在草稿窗口前记录的自动通过。

News 必须由人工显式采纳。其余环节包括采编、校时、去重、提醒、Weekly Headlines、Insight 分析草稿/终稿、文档留档、审计与失败告警均自动执行。Insight 的方案、证据、Claim 和草稿可人工处理；未在对应时限内操作时，系统记录 Auto-approved 后继续。**[已废止：v3.1 允许受限的 AI deadline 事实发布兜底，见 [可执行规格 §2](v3_1_event_intelligence_spec.md#2-state-machines)。]**

---

## 4. 产品边界与当前状态

### 4.1 能力状态定义

| 状态 | 定义 |
| --- | --- |
| **生产可用** | 有代码路径、配置入口、自动任务或可重复脚本，并有测试覆盖。 |
| **受配置限制** | 代码已实现，但依赖 API Key、外部权限、provider 状态或人工批准。 |
| **基础设施已具备** | 数据表/合同/门禁已实现，但尚未证明能稳定产出管理层级研究。 |
| **未实现** | 仅作为后续方向，不应承诺给运营使用。 |

### 4.2 当前能力矩阵

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Brave / SerpAPI / OpenClaw provider | 生产可用或受配置限制 | 当前本机主源为 Brave，OpenClaw 为 fallback；SerpAPI 需独立 Key。 |
| Provider 健康检查与 fallback | 生产可用 | 主源请求失败时降级；健康异常通知审批群。 |
| News 入表、标题/链接/日期规范化 | 生产可用 | 标题取原文页面，最多 20 个英文单词；URL 显示为域名文本。 |
| 语义去重 | 生产可用 | 主记录保留，重复项标 `已重复` 并关联 `Duplicate Of`。 |
| 审批提醒与直达审核视图 | 生产可用 | 发送到 `bot监控审核群`；使用专属审批视图 URL。 |
| Daily News Review | 生产可用 | 面向审核者；采编完成与待审核提醒直达审批视图，不承担管理层内容发布。 |
| Weekly Headlines | 生产可用 | 面向管理层；只消费已采纳且未发送摘要的 News，成功后写回 `Weekly Headlines Sent At`。 |
| Weekly Intelligence 草稿/终稿、图片、钉钉文档 | 生产可用 | 面向管理层；分析产物独立于 Weekly Headlines，终稿成功后写回 `Weekly Intelligence Sent At`。 |
| 研究主题、证据、主张、审计数据层 | 基础设施已具备 | 已有相应表和质量门禁。 |
| OpenAI Deep Research | 受配置与批准限制 | 已配置时仅在显式批准后调用；输出仍需按证据/主张门禁使用。 |
| Gemini / ChatGPT Web 浏览器自动化 | 未实现 | 可配置目标存在，但稳定无人值守 adapter 不应被当作生产承诺。 |
| 全自动战略结论 | 未实现且不应实现 | 所有管理层判断必须经过证据与人工责任门。 |

---

## 5. 核心数据产品

### 5.1 `News`：外部信号与人工审核池

`News` 是唯一的候选信号入口，也是 Weekly Headlines 与 Weekly Insight 的来源。canonical sheet 为 `News`（`oMbefcK`）。

| 字段 | 含义 | 规则 |
| --- | --- | --- |
| `No` | 稳定新闻编号 | 自动生成，不因重跑改变。 |
| `Title` | 标题 | 从 Source URL 提取；最多 20 个英文单词。 |
| `Source URL` | 原文链接 | 显示文本统一为域名，点击到原文。 |
| `Source Domain` | 来源域名 | 用于频率控制和质量分析。 |
| `Publish Date` | 原文发布日期 | 优先元数据/URL；无法提取时使用 First Seen At 兜底，并在任务级 RunLog/Audit Trail 中记录补齐方法。**[已废止：v3.1 禁止以 First Seen At 证明 Publish Date，见 [可执行规格 §2](v3_1_event_intelligence_spec.md#2-state-machines)。]** |
| `Section` / `Label` | 栏目与标签 | Finance、Contact Center 等。 |
| `Status` | 审核状态 | `待处理` / `已采纳` / `已拒绝` / `已重复`。 |
| `Rejection Reason` | 拒绝原因 | 为后续精确筛选与模型改进提供反馈。 |
| `Duplicate Of` | 主记录编号 | 仅用于语义重复记录。 |
| `Search Provider` / `Query` / `Batch` | 发现血缘 | 必须保留，支持 provider 质量比较。 |
| `First Seen At` | 系统首次发现时间 | 不是首选发布日期，但可作为日期兜底。**[已废止：仅保留发现时间，不得作为发布日期兜底；见 [可执行规格 §2](v3_1_event_intelligence_spec.md#2-state-machines)。]** |
| `Weekly Headlines Sent At` | 摘要发布状态 | 只防止 Weekly Headlines 重复发送。 |
| `Weekly Intelligence Sent At` | 分析发布状态 | 只防止 Weekly Insight 重复发送；历史 `Weekly Sent At` 只用于兼容旧记录。 |

### 5.2 周度运营工作面

| 表 | 面向谁 | 职责 |
| --- | --- | --- |
| `Weekly Editions` | 审核者与管理层 | 每周一条总控记录，聚合 Weekly Headlines、Insight 方案/草稿/终稿状态与文档链接。 |
| `Weekly Editorial Inputs` | 审核者 | 存放人工补充的新闻摘要、链接、钉钉文档与附件；没有材料时保持空白。 |
| `Detect Sources` | 系统维护者 | 维护来源和观察对象。 |
| `Config` | 系统维护者 | 维护排程、Provider 和发布规则。 |

长报告正文必须保存在钉钉文档/DWS，PDF/PPT 等作为附件保存；AI 表格只存链接、附件、简短摘要和用途。

### 5.3 后台研究与审计控制面

| 表 | 职责 | 不能替代什么 |
| --- | --- | --- |
| `Research Topics` | 当前主题和未来研究路线 | 不能替代明确研究问题。 |
| `Research Queue` | 每周问题、假设、检索计划、批准状态、冻结时间 | 不能直接等同于证据。 |
| `Evidence Bank` | 原子事实、来源等级、范围、数字、限制、审核状态 | 不能只存标题或摘要。 |
| `Claim Ledger` | 事实/推论/假设与证据关系、置信度、批准状态 | 不能把未批准 Claim 放进管理层结论。 |
| `Research Results` | 外部研究 provider 的完整输出和元数据 | 不能绕过 Evidence/Claim 门禁。 |
| `Insights` | 历史草稿、终稿、文档/图片链接、发送结果、源记录 ID；前台职责逐步迁入 Weekly Editions | 不能作为原始新闻池。 |
| `Audit Trail` | workflow 与步骤级追加审计 | 不能替代业务表。 |
| `Config` | 可运营的排程、输出和表配置 | 不存密钥。 |
| `Detect Sources` | 关注对象、主题、别名、来源域名和检索计划 | 不等于最终信号质量判断。 |

`Daily Headlines Review` 和 `Search Providers` 为历史/后台表，不再是日常工作入口；它们保留只读数据，不删除历史记录。

---

## 6. 端到端工作流

### 6.1 三个用户可感知阶段

| 阶段 | 英文代号 | 目标 | 人工参与 |
| --- | --- | --- |
| 采编 | `INGEST` | 把外部候选信号变成可审核的 News 记录 | 无，异常时人工修复配置。 |
| 催审 | `REVIEW` | 把待处理池转化为已采纳/拒绝决策 | 必须审核 News。 |
| 发布 | `PUBLISH` | 将已采纳信号转化为 Weekly Headlines 和 Weekly Insight | News 必须显式采纳；Insight 审核逾期自动通过并留痕。 |

### 6.2 `INGEST`：自动采编

**触发：** 周一至周六 02:00，或人工运行 `scripts/daily_fetch.py`。

**输入：** provider 配置、Detect Sources、关键词/实体、当前 News、去重规则。

**处理顺序：**

1. 检查主 provider 与 fallback provider。
2. 从 Detect Sources 或本地设置生成分组检索计划。
3. 搜索并平衡选择候选，保留查询和 provider 血缘。
4. URL 级去重后写入 News。
5. 从原文整理标题；规范 Source URL 显示文本。
6. 通过元数据、URL、First Seen At 补齐 Publish Date。**[已废止：v3.1 不允许 First Seen At 作为 Publish Date，见 [可执行规格 §2](v3_1_event_intelligence_spec.md#2-state-machines)。]**
7. 执行语义去重，更新 `已重复` 与 `Duplicate Of`。
8. 向审批群发送带审批视图链接的完成通知，并真正 @ 已配置手机号。
9. 写 RunLog 与 Audit Trail。

**成功标准：** 至少一个 provider 可用；写入/跳过原因可解释；每条新增记录有 URL、标题、日期或明确兜底方法、provider 和审核状态。

**失败策略：**

- 主 provider 失败，fallback 成功：采编成功，但记录降级原因并告警。
- 所有 provider 失败：任务失败，向审批群告警，不写伪造数据。
- 表格写入/更新临时失败：对 `429`/`5xx` 退避重试；仍失败时保留审计错误。

### 6.3 `REVIEW`：审核与催审

**触发：** 周一至周六 09:00，或人工运行 `scripts/daily_remind.py`。

**系统行为：**

1. 再次检查 provider 健康，避免失效静默。
2. 统计 `News.Status = 待处理` 的总数。
3. 向 `bot监控审核群` 发送提醒、审批视图链接与 @ Franco。

**人工行为：**

- `已采纳`：可进入 Weekly Headlines 与 Weekly Intelligence 候选池。
- `已拒绝`：必须尽量填写 Rejection Reason。
- `已重复`：由系统维护，人工可纠正误判。

### 6.4 `PUBLISH`：Weekly Headlines

**触发：** 周日 11:00。

**选择规则：** `Status = 已采纳` 且 `Weekly Headlines Sent At` 为空；默认按 `Publish Date` 回看 7 天，并按栏目平衡。

**输出：** 管理层新闻摘要 Markdown，含标题、来源链接、时间范围和审批视图链接；不包含战略推演或研究结论。

**路由：** 发送到 `daily news` / `publish_group`；成功后只写回 `Weekly Headlines Sent At`。

### 6.5 `PUBLISH`：Weekly Insight 与研究节奏

| 时间（Asia/Shanghai） | 任务 | 自动行为 | 人工门控 |
| --- | --- | --- | --- |
| 每日 00:00 | 健康检查 | provider、News 连通性、近期失败任务检查 | 无 |
| 周一至周六 02:00 | 采编 | `INGEST` | 无 |
| 周一至周六 09:00 | 催审 | `REVIEW` | News 审核 |
| 周日 11:00 | Weekly Headlines | 管理层新闻摘要并写回独立发送时间 | 无 |
| 周五 09:00 | 研究计划 | 生成不收费的 Deep Research proposal | 批准计划 |
| 周六 12:00 | Weekly Insight 草稿 | Signal Brief/研究草稿、文档、图片、Weekly Editions 待反馈 | 可审核 Claim/草稿；未操作按时限自动通过 |
| 周六 14:00 | Deep Research | 在方案已批准或自动通过后调用 OpenAI | 可审核方案；未操作按时限自动通过 |
| 周日 12:00 | Weekly Insight 终稿 | 生成终稿、文档、图片并发送 | 草稿未操作时自动通过并留痕 |

**Weekly Insight 选择规则：**

- 只选择 `已采纳` 的 News。
- 正式窗口默认按 `Publish Date` 回看 7 天。
- 草稿不写发送状态。
- 终稿成功发送后才写 `Weekly Intelligence Sent At`。
- 方案、Evidence、Claim 和草稿的每次人工操作或自动通过均写入 Weekly Editions 与 Audit Trail。
- 没有达到研究质量门禁时，输出必须明确标识 `Signal Brief`。

### 6.6 群路由合同

| 群别名 | 当前用途 | 不应发送的内容 |
| --- | --- | --- |
| `BOT监控审核群` / `review_group` | News 待审、Insight 方案/Evidence/Claim/草稿待审、超时催办、provider/运行异常 | 正式管理层发布 |
| `Daily News` / `publish_group` | Weekly Headlines、Weekly Insight 终稿、发送结果 | 审核噪音、健康检查告警 |

所有 Webhook 通知默认支持对已配置手机号使用钉钉真实 @；群名称不是由 Webhook 自动反查，应在配置与运营文档中显式维护。

---

## 7. 周报研究合同

### 7.1 报告层级

| 层级 | 允许输出 | 不允许输出 |
| --- | --- | --- |
| Signal Brief | 已采纳新闻、来源、有限且明确标注的观察 | 未验证战略结论、合成 P0、无证据 ROI |
| Evidence-backed Weekly Report | 已验证事实、来源、范围、置信度、GBSS 相关性 | 未批准的 Claim、没有边界条件的推论 |
| Deep Research | 研究问题、冻结证据、交叉验证、反证、批准 Claim、管理层判断 | 从标题或模型记忆直接推导结论 |

### 7.2 每周研究问题

每周只锁定一个可被证据回答或推翻的问题。一个合格问题必须包含：

- 变化对象：公司、技术、监管、运营模型或竞争格局。
- 作用机制：变化为什么可能影响 GBSS。
- 决策语境：Merchant Service/ePOS、Antom、WorldFirst、General GBSS Ops、Contact Center、AIQC、AICC、OPC、治理等。
- 可观察证据：所需来源、数字、客户部署、限制或反例。

不合格示例：`AI 正在改变行业`。
合格示例：`Voice AI 在受监管 Contact Center 的生产部署门槛是否已满足，哪些治理能力仍是限制？`

### 7.3 证据与 Claim 门禁

Deep Research Ready 的最低条件：

1. 至少 6 条已验证 Evidence。
2. 至少 3 条 T1/T2 来源。
3. 对材料结论有已批准 Claim。
4. 至少一条 Claim 包含限制、反证或边界条件。
5. 所有优先卡片都有 Source URL 和 Publish Date。

任何条件不满足：仍可发布为 Signal Brief，但不得写成确定性战略结论或 P0。

### 7.4 优先级

| 优先级 | 含义 | 进入条件 |
| --- | --- | --- |
| P0 | 30 天内需要管理层决定/风险响应 | 已确认事件、T1 证据、具体 GBSS 影响、明确决策窗口、批准 Claim 全部成立。 |
| P1 | 需要研究、Benchmark、PoC 或能力评估 | 有证据支持且存在可行动问题。 |
| P2 | 持续观察 | 有相关性但近期无需动作。 |
| Watch | 早期/弱信号 | 进入信号池，不进入正式管理层结论。 |

P0 可以为 0。系统禁止通过固定模板制造 P0。

---

## 8. 质量、可追溯与运营要求

### 8.1 新闻质量

- 每条 News 必须有可访问的 Source URL；付费墙/反爬允许存在，但必须保留原始链接。
- 标题、URL、发布时间、来源域名、provider、查询和发现时间必须可追溯。
- `Publish Date` 优先取原始发布日期；使用 First Seen At 兜底时，在 Audit Trail 中保留方法。**[已废止：v3.1 对缺失 Publish Date 失败关闭，不以发现时间冒充发布时间。]**
- 同事件多版本只保留一个人工审核主记录，其余标记重复。
- 采集候选不能直接进入日报/周报。

### 8.2 发布质量

- 日报和周报只消费 `已采纳` 记录。
- 成功写回发送时间；失败不写回，以便重试。
- 发布群与审批群必须分离配置并在每次变更后进行测试消息验证。
- 机器人消息必须包含必要的上下文和可点击链接；审核类消息必须直达审批视图。

### 8.3 研究质量

- 事实、推论、假设必须分开记录。
- 高影响数字、客户部署、ROI、监管判断、市场规模和 P0 必须有 T1/T2 证据。
- vendor 自述不得单独支撑管理层结论。
- 必须主动寻找反证、限制、样本边界和替代解释。
- 报告视觉稿只能从结构化 report data 渲染，不能在图片层补写未审查结论。

### 8.4 技术与安全

- 普通配置写入 SQLite；密钥优先保存在 macOS Keychain，降级文件权限为 `0600`。
- 密钥、数据库、缓存和运行日志不得提交 Git。
- 本机通过 launchd 运行；每个任务有 stdout/stderr 日志、RunLog 和 Audit Trail。
- 外部 API 失败、临时 `429`/`5xx`、表格写入失败应退避重试并保留错误上下文。

---

## 9. 可量化验收指标

### 9.1 运营指标

| 指标 | 目标 | 计算方式 |
| --- | --- | --- |
| 采编成功率 | >= 95% / 月 | 成功 INGEST / 已执行 INGEST。 |
| provider 可用性 | >= 1 个可用 | 每日健康检查至少一个 provider 成功。 |
| 审核链路可达性 | 100% | 审核通知均带审批视图链接。 |
| 重复发布率 | 0 | 已写 Sent At 的记录不得再次被同类流程发送。 |
| Publish Date 完整率 | >= 99% | 非异常记录中有日期的比例；First Seen fallback 单独统计。 |
| 群路由准确率 | 100% | 审批类不进发布群，正式发布不进审批群。 |

### 9.2 内容指标

| 指标 | 目标 |
| --- | --- |
| 已拒绝原因覆盖率 | >= 80% 的 `已拒绝` 记录有 Rejection Reason。 |
| 优先卡片可追溯率 | 100% 有 Source URL 与 Publish Date。 |
| P0 完整门禁率 | 100% 满足五项 P0 条件。 |
| Deep Research 门禁合规率 | 不达证据门槛时 100% 标记为 Signal Brief。 |
| 研究 Claim 可追溯率 | 100% 材料结论关联 Evidence ID。 |

---

## 10. 配置与优先级规则

### 10.1 配置源优先级

为避免“改了 Config 表但没有生效”的问题，配置读取优先级必须固定：

1. 本机 Keychain / secrets：只存密钥，永不被 Config 覆盖。
2. 本地 SQLite 设置：系统启动时的基础配置。
3. 钉钉 `Config` 表：仅允许覆盖明确标记为 Editable 的运营项。
4. CLI 参数：仅覆盖本次人工执行。

任何覆盖都应记录到 Audit Trail，包含原值、目标值、来源和生效时间。

### 10.2 Provider 策略

- 主 provider：优先真实、可无人值守、可输出结构化结果的 API provider。
- fallback provider：必须独立于主 provider，且能够实际返回候选。
- 交互式 provider（如 Codex）：只作补充或调试，不成为凌晨任务的单点依赖。
- 每个 provider 需记录成本、失败率、候选数、入表数、采纳率、拒绝率和重复率，以便淘汰低质量源。

---

## 11. 当前已知缺口与优化方向

本节不是承诺；它是必须在后续版本中解决的产品债务。

### P0：先解决“系统做对什么”

1. **审核默认通过需要真实运营验证。** 已确认方案、Evidence、Claim 与草稿在时限内未操作时自动通过；需要连续四周观察提醒频率、误发风险和人工负担。
2. **研究质量门禁需要真实运营验证。** 数据表与代码已存在，但尚未用连续多周的证据包证明能稳定产出管理层级洞察。
3. **群路由需要成为一等配置。** 已确认 BOT监控审核群只接收人工待办与异常，Daily News 只接收正式周度产出；应在 Config 与 UI 中显示群别名、用途和最近测试结果。
4. **发布日期兜底要透明。** `First Seen At` 不是原始发布日期；报告和数据质量面板必须区分 `source_metadata`、`url_path`、`first_seen_fallback`。**[已废止：v3.1 删除 `first_seen_fallback` 发布资格，见 [可执行规格 §2](v3_1_event_intelligence_spec.md#2-state-machines)。]**

### P1：提高内容质量和可控性

1. 对 News 增加“来源等级、原文可访问性、日期置信度、标题提取方法”。
2. 将 Reject Reason 归类为可分析标签，形成 provider/关键词/来源的质量反馈闭环。
3. 将测试消息、日报/周报发布与正式内容隔离，测试不得污染正式 Sent At 或 Insights。
4. 对随机测试与日常选数过滤栏目页、主页、搜索页和无正文 URL。
5. Provider 对比从“是否可用”升级为“有效候选、采纳率、重复率、人工拒绝原因”。

### P2：把研究从“表结构”升级为“可复用工作法”

1. 为每个 Research Topic 建立标准 Research Brief 模板和责任人。
2. Evidence Bank 增加访问快照/摘录、抓取时间、证据失效状态。
3. Claim Ledger 增加“结论使用位置”和“撤回/更新”流程。
4. 建立周报发布后的反馈回收：管理层问题、被采纳行动、被否定判断。

---

## 12. 版本路线图

### V2.0：运营稳定化（当前优先）

- 固定审批群与发布群路由，增加可视化配置与测试。
- 发布前质量门禁、日期方法标识、来源质量指标。
- Provider 质量仪表盘和 Reject Reason 反馈。
- 运行日志、Audit Trail、发布状态的统一运营视图。

### V2.1：周度工作面精简与研究生产验证

- 创建 Weekly Editions 与 Weekly Editorial Inputs，归档 Daily Headlines Review，并将后台研究表从日常导航隐藏。
- 支持钉钉文档链接和附件形式的人工长材料输入，不在 AI 表格保存长正文。
- 在 BOT监控审核群发送方案、Evidence、Claim、草稿的直达提醒，并记录人工或自动通过。
- 选择一个实际 GBSS 主题跑满一周 Research Queue -> Evidence -> Claim -> Signal Brief/Deep Research 链路。
- 对 Deep Research 结果做人工评审和反证评审。
- 将可复用的研究模板沉淀为 Topic playbook。

### V2.2：决策闭环

- 将周报中的行动项、owner、截止时间和后续验证结果写回 Insights。
- 追踪“信号 -> 判断 -> 行动 -> 结果”的闭环，而不是只追踪发送成功。

---

## 13. 发布验收清单

每次功能上线前至少验证：

1. `tests/` 全部通过。
2. provider 主/备失败路径可解释。
3. News 链接、标题、发布日期、状态和血缘字段正确。
4. 审批通知进入 `bot监控审核群`，发布内容进入 `daily news` 群。
5. 日报/周报不重复写入 Sent At。
6. 周报的每个优先项可回溯到 News 或 Evidence。
7. Deep Research 未达到门槛时明确输出 Signal Brief。
8. 图片版在移动端没有截断、重叠、空白占位或无来源结论。
9. RunLog 与 Audit Trail 均有完整结果。

---

## 14. 需要产品负责人确认的决策

以下已由产品负责人确认，并作为默认运营规则：

1. 最终只对外发送 Weekly Headlines 和 Weekly Insight；Daily News Review 只用于审核支持。
2. News 必须显式采纳，未审核 News 不进入任何最终交付，并持续提醒。
3. Insight 的方案、Evidence、Claim 和草稿可人工审核；逾期未操作时自动通过并留下审计记录。
4. 所有人工待办与异常只发送至 BOT监控审核群；Daily News 只接收正式周度产出。
5. 长文档使用钉钉文档或附件，AI 表格仅保存链接、附件、摘要和用途。

具体字段、状态和迁移顺序见 `docs/weekly_operating_model.md`。
