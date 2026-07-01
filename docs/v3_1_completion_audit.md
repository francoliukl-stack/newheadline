# GBSS v3.1 生产完成度审计

**审计时间：** 2026-06-30 00:06（Asia/Kuala_Lumpur）
**审计原则：** 只把当前代码、钉钉业务表、RunLog、Audit Trail、launchd 和可重复测试能够证明的事项标为完成。四周运营目标不能由一次绿色快照替代。

## 当前结论

v3.1 的工程实现和生产配置已基本完成，发布门禁为 `ready`，但产品目标仍处于生产观察期，不能宣布整体完成。

当前剩余的硬证据包括：28 天连续观察、上线后关键事件时效样本、周度 One Pager 连续产出，以及月度 INGEST 成功率。

## 工程交付证据

| 要求 | 状态 | 当前证据 |
| --- | --- | --- |
| 当前 workspace + 钉钉 AI 表格作为业务数据库 | 已验证 | Event、Entity、Source、Score、Alert、API Usage 均为钉钉表；SQLite 只保存 Settings、RunLog 和待补写审计。 |
| News → Event Case 聚合 | 已验证 | 静态聚类 precision/recall 均为 1.0。2026-07-01 将 3 条跨 4 天发布的 Airwallex 3.2 亿美元融资报道聚合为唯一 `event-25caac8c42ad921a`；两个旧 Event 均归档并写入合并目标，3 条 News 均回指 canonical Event。 |
| 核心 Entity Catalog | 已验证 | Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK 均启用、Watch Tier=critical、4 小时扫描，并配置官方站或 Ant International Newsroom。critical/high 实体的直接官方扫描页由 14 增至 20 个。 |
| Adapter 层 | 已验证 | Official、GDELT、yfinance、Marketaux、Firecrawl、Alpha Vantage 均有开关和 mock 测试；付费 adapter 默认关闭。Official HTML adapter 已用 Airwallex、Checkout.com、dLocal、PayPal、Genesys、NICE 真实页面验证文章识别与日期排序。 |
| OpenAI 结构化服务与成本门禁 | 已验证 | Structured Outputs、重试、超时、熔断、预算预留与 API Usage 测试通过；生产 OpenAI 当前关闭，28 天成本为 0 USD。 |
| P0 人工门禁 | 已验证 | 自动最终 P0 违规数为 0；系统只生成 Priority Candidate。 |
| News 最终生效门 | 已验证 | `News.Status=已采纳` 仍是唯一日常发布门；人工决定优先，11:50 仅允许高置信、可追溯的 AI 建议在无人处理时写入该状态。Event 状态、业务线、类型、优先级候选和影响方向自动同步。 |
| AI News 预审与兜底 | 已上线 | AI Status 明确三态，禁止待处理。2026-07-01 v1.3 全量重算 366/366 条：已采纳 40、已拒绝 272、已重复 54；第二次 dry-run 更新数为 0。352 条已比较记录的一致率为 77%，80 条覆盖中 73 条为“AI 拒绝→人工采纳”；主要缺口为 Eventization Gap 36 和 Event Type Underclassified 33。7 条“AI 采纳→人工拒绝”已进一步归因为弱相关、信息过薄、PR、来源无正文、签证实体误匹配和投资评论。当前 4 条规则达到 `支持数≥5、一致率≥80%`；规则详情及每日差异快照已进入 RunLog/Audit metadata，学习推翻基础规则时置信度封顶 0.84。 |
| Signal Brief 门禁 | 已验证 | Evidence/Claim 未达标时，影响结论和行动建议被抑制；静态评测与报告测试通过。 |
| 管理层追溯 | 已验证 | Daily Report 群消息保留来源 URL/Publish Date，内部 ID 为移动端可读性不展示；完整 Event/Evidence/Claim 追溯保存在钉钉业务表和 Audit Trail。Weekly Insight / One Pager 保留完整研究追溯。 |
| Daily Report 调度 | 已验证 | 2026-07-01 12:00 真实发送 8 个 Event，用户确认收到；无 @、每条显示 Publish Date。Airwallex 融资 Event 合并后再次 dry-run 返回 `nothing to publish`，证明旧 News 发送标记阻止重复播报；13:00 内部群仍由负责人手工转发。 |
| 新闻源扩展 | 已验证到真实 dry-run | Detect Sources 从 59 增至 94 条，Brave 查询从 7 组增至 15 组；真实 dry-run 分别得到 199 和 189 条原始候选，仍限制为 30 条且跨组轮询，未写 News。 |
| 昨日要闻审核门禁 | 已实跑并修正 | 2026-06-30 09:00 正常触发并选出 6 条 2026-06-29 News，但旧发送器只检查 HTTP 200，无法证明机器人实际接收。12:26 修复返回体 `errcode` 校验、剔除一条 H-1B `visa` 误匹配后，向审核群补发 5 条并获得有效确认。当前名单为 HKMA 2 条、GCash IPO、QRIS、Airwallex 融资。 |
| 关键事件扫描 | 已运行 | 每天 01/05/09/13/17/21；扩源后完整 dry-run 为 32 次 adapter 尝试、30 次成功，Fiserv 超时和 GDELT 429 被隔离。日期补齐后的二次门禁剔除 3 条历史/无日期候选，只保留 3 条窗口内候选，其中 2 条为 2026-06-29 HKMA 监管动态。 |
| Audit Trail | 已验证 | 工作流步骤、失败、KPI 快照和恢复记录写入钉钉；暂存事件可由健康检查补写。 |
| 回滚 | 已验证到 dry-run | `weekly_input_mode=news`、关闭 Event/critical flags、保留新增表和历史数据。 |
| 自动化回归 | 已验证 | 140 个单测通过；v3.1 golden 指标全部通过，包括融资跨日聚合、旧 Event 归档、学习规则门槛、硬门禁、标准差异归因和学习快照审计。 |

## 运营目标证据

| 指标 | 目标 | 当前证据 | 判定 |
| --- | ---: | ---: | --- |
| 高相关外部信号 | 10–30 / 周 | 8 | 尚未达下限；扩展来源尚未经历首个 02:00 生产周期 |
| Event Case | 5–10 / 周 | 7 | 达标，观察期不足 |
| 关键事件上线后当日/次日感知 | 100% | 暂无上线后样本；3 个上线前回填已单列 | 无数据 |
| 业务线映射完整率 | 100% | 1.0 | 当前达标 |
| 明确 Event Type 覆盖率 | 100% | 1.0 | 当前达标；市场背景类显式标为非关键 `Market_Context` |
| 候选/已采纳追溯率 | 100% | 1.0 / 1.0 | 当前达标 |
| 自动最终 P0 违规 | 0 | 0 | 当前达标 |
| API 成本 | <=25 USD/月 | 0 USD / 最近 28 天 | 当前达标 |
| Deep Research Ready Event | 按人工批准产生 | 0 | 尚无批准样本 |
| 四周稳定运行 | 28 天 | 第 3 天 | `observation_incomplete` |

## 尚未完成的生产验收

1. 继续观察下一次 02:00/09:00 自动周期，确认钉钉 QPS 退避、Eventize 和 webhook `errcode` 确认均无需人工恢复。
2. 连续四周保存每日 KPI 快照，并按周复盘信号量、Event 数量、关键事件召回、时效、成本和 AI/人工一致率。
3. 至少取得一个上线后关键事件样本，以 job run / First Seen 时间证明当日或次日感知。
4. Weekly Insight 与 One Pager 连续四周按 Event 输入产出；不能用单次渲染成功替代稳定性证明。
5. 若要产出 Evidence-backed Report 或付费 Deep Research，必须先取得逐次人工批准和完整 Evidence/Claim 门禁样本。

## 重复执行命令

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_v3_1_evaluation.py
.venv/bin/python scripts/daily_health_check.py --dry-run
.venv/bin/python scripts/v3_1_kpi_report.py
.venv/bin/python scripts/cutover_v3_1.py --dry-run
.venv/bin/python scripts/weekly_headlines.py --dry-run
```

在 12:00 实发后，应以 RunLog、Audit Trail、群消息和 News/Event Cases 字段四份证据共同关闭首次 Daily Report 验收项。
