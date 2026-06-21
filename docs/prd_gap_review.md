# PRD 评审与优化建议

**评审对象：** `prd.md` 旧版本与当前已提交实现
**评审日期：** 2026-06-21
**结论：** 旧 PRD 的主要问题不是缺少功能描述，而是把运行现状、目标架构、研究方法论和愿景混在一起，导致读者无法判断“今天能依赖什么”“哪些需要人工批准”“失败时会发生什么”。

## P0：必须优先澄清

### 1. 产品的最终输出不够明确

旧文档同时把日报、新闻周报、GBSS 战略周报、Signal Brief、Deep Research 放在同一叙述中。它们的受众、来源门槛、发送群和发布条件不同。

**建议：** 固定三种产品：

| 产品 | 受众 | 输入门槛 | 输出群 | 发布状态 |
| --- | --- | --- | --- | --- |
| 审核提醒 | 审核者 | 待处理 News | bot监控审核群 | 无业务发布含义 |
| Daily Headlines | 日常读者 | 已采纳、未日报发送 | daily news | 写 `Daily Sent At` |
| Weekly AI & Service Intelligence | 管理层 | 已采纳 News + 研究质量门禁 | daily news | 写 `Weekly Sent At` |

### 2. “自动化”与“人工责任”边界没有落到状态机

旧文档说“人工审核是唯一门”，但又允许周日终稿自动发布；研究计划、Claim、终稿之间谁负责批准没有固定状态迁移。

**建议：** 定义明确状态机：

`News: 待处理 -> 已采纳/已拒绝/已重复`
`Research: Draft -> Awaiting Approval -> Approved -> Evidence Frozen -> Ready / Signal Brief`
`Report: Draft -> Review Copy -> Ready to Publish -> Published / Failed`

若周报需要业务最终确认，就不要让 launchd 直接发送终稿。

### 3. “Deep Research”被过早当作稳定交付

现有代码已经有 Research Queue、Evidence Bank、Claim Ledger 和质量门禁，这是正确方向；但它们还需要连续周度实际运行来证明输入质量、人工审核成本与最终洞察质量。

**建议：** 将 Deep Research 定义为受控试运行。未达证据门槛时，产品名称必须是 Signal Brief，不能在对管理层输出中使用 Deep Research 语言。

### 4. 群路由此前已经发生实际混淆

审批群和日报/周报群的 Webhook 曾被映射反向。旧 PRD 没有把群别名、用途和验收标准写成合同。

**建议：** Config 中维护 `review_group` 与 `publish_group` 的显示名称、Webhook 健康状态、最近测试时间；每次改动后发送受控测试消息。

## P1：显著影响质量与运营成本

### 5. Publish Date 不能只追求“非空”

通过 First Seen At 填补空日期能保证流程连续，但它不是原始发布日期。若不标记方法，周报时间窗口和排序会悄悄失真。

**建议：** 增加 `Publish Date Method` 和 `Publish Date Confidence`：

- `source_metadata / high`
- `url_path / medium`
- `provider_value / medium`
- `first_seen_fallback / low`
- `unconfirmed / none`

并让周报优先选择 high/medium 日期；low 日期在报告中不作为精确时点事实。

### 6. Provider 健康不等于 Provider 质量

当前健康检查主要验证“能不能返回结果”。但真正需要的是：哪些 provider 带来更多可采纳、少重复、少栏目页、少付费墙的新闻。

**建议：** 按 provider 计算：候选数、入表数、重复率、采纳率、拒绝原因、链接可访问率、日期可确认率、每条有效信号成本。

### 7. News 的质量字段仍不够

标题、URL、日期和 provider 已有，但来源可信度和正文可用性未显式沉淀。

**建议：** 增加：`Source Tier`、`URL Accessibility`、`Article URL Valid`、`Title Method`、`Publish Date Method`、`Content Type`。这会让后续日报/周报的选数更可控。

### 8. Config 表和本地设置的优先级要可见

现在两者都存在，但普通运营者不容易知道某个值究竟来自哪里。

**建议：** 在设置 UI 中显示“当前生效来源”和最近一次同步时间；所有 Config 覆盖写入 Audit Trail。

## P2：提升长期产品价值

### 9. 把拒绝原因转化为训练数据

目前已有 `Rejection Reason`，但尚未形成标准分类和 provider/关键词反馈。

**建议：** 预设拒绝原因：不相关、重复、来源弱、过旧、无行动价值、标题误导、付费墙、栏目页；按月回顾并调整 Detect Sources 与查询计划。

### 10. 从“发送成功”升级为“决策被使用”

目前 Audit Trail 能证明消息发出，但不能证明周报产生了什么行动。

**建议：** Insights 增加 `Decision / Owner / Due Date / Outcome`，形成信号到行动的闭环。

### 11. 报告视觉与内容质量需要独立评估

已有评测集是好的起点，但应把内容事实性、证据覆盖、布局可读性和群消息表现拆开评估。

**建议：** 每周固定抽样复盘 3 类失败：来源错误、推论过度、移动端版式问题；将结果写入 release evaluation。

## 建议的下一次产品评审

不要先新增更多 provider 或报告版式。先用一个真实专题完整跑一周，并评审以下五项：

1. 审核池是否把噪音控制在可接受范围。
2. 已采纳信号是否足以支持一个明确问题。
3. Evidence/Claim 门禁是否降低了泛化结论。
4. 管理层是否能在 One-page Brief 中看懂“事实、影响、行动、边界”。
5. 发布后是否产生可记录的行动或追问。

如果这五项没有通过，继续堆叠模型或搜索源只会放大系统复杂度，不会接近预期。
