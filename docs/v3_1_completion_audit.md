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
| News → Event Case 聚合 | 已验证 | 静态聚类 precision/recall 均为 1.0；生产已有 16 个有效 Event Case。 |
| 核心 Entity Catalog | 已验证 | Alipay+、WorldFirst、Bettr、Antom、Ant Bank HK、AlipayHK 均启用、Watch Tier=critical、4 小时扫描，并配置官方站或 Ant International Newsroom。 |
| Adapter 层 | 已验证 | Official、GDELT、yfinance、Marketaux、Firecrawl、Alpha Vantage 均有开关和 mock 测试；付费 adapter 默认关闭。 |
| OpenAI 结构化服务与成本门禁 | 已验证 | Structured Outputs、重试、超时、熔断、预算预留与 API Usage 测试通过；生产 OpenAI 当前关闭，28 天成本为 0 USD。 |
| P0 人工门禁 | 已验证 | 自动最终 P0 违规数为 0；系统只生成 Priority Candidate。 |
| 唯一日常人工门 | 已验证 | 按最新运营决定，`News=已采纳` 是唯一日常人工发布门；Event 状态、业务线、类型、优先级候选和影响方向自动同步。 |
| Signal Brief 门禁 | 已验证 | Evidence/Claim 未达标时，影响结论和行动建议被抑制；静态评测与报告测试通过。 |
| 管理层追溯 | 已验证 | Daily Report 群消息保留来源 URL/Publish Date，内部 ID 为移动端可读性不展示；完整 Event/Evidence/Claim 追溯保存在钉钉业务表和 Audit Trail。Weekly Insight / One Pager 保留完整研究追溯。 |
| Daily Report 调度 | 已验证 | 2026-06-29 12:00 首次真实发送 4 个 Event；Event Cases 与 4 条关联 News 的 `Daily Report Sent At` 均写回。随后按运营修正无 @ 重推一次，每条明确显示 Publish Date；13:00 内部群仍由负责人手工转发。 |
| 新闻源扩展 | 已验证到真实 dry-run | Detect Sources 从 59 增至 94 条，Brave 查询从 7 组增至 15 组；真实 dry-run 得到 199 条原始候选，仍限制为 30 条且跨组轮询，未写 News。 |
| 昨日要闻审核门禁 | 已配置，待首次实跑 | 每天 02:00 采集、09:00 提醒；只纳入前一自然日、待处理且已关联 Event 的 News。只读预演排除了 8 条历史待处理；首次计划运行将在 2026-06-30 09:00 验证。 |
| 关键事件扫描 | 已运行 | 每天 01/05/09/13/17/21；最近真实运行恢复正常；adapter 单点超时/429 被隔离并进入 RunLog/Audit。 |
| Audit Trail | 已验证 | 工作流步骤、失败、KPI 快照和恢复记录写入钉钉；暂存事件可由健康检查补写。 |
| 回滚 | 已验证到 dry-run | `weekly_input_mode=news`、关闭 Event/critical flags、保留新增表和历史数据。 |
| 自动化回归 | 已验证 | 118 个单测通过；v3.1 golden 指标全部通过；cutover dry-run=`ready`。 |

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

1. 验证 2026-06-30 02:00 扩展来源首次生产采集，以及 09:00 仅前一日要闻的运营群提醒。
2. 次日再次验证 `Daily Report Sent At` 去重，确认 6 月 29 日已发送 Event 不会重复出现。
3. 连续四周保存每日 KPI 快照，并按周复盘信号量、Event 数量、关键事件召回、时效和成本。
4. 至少取得一个上线后关键事件样本，以 job run / First Seen 时间证明当日或次日感知。
5. Weekly Insight 与 One Pager 连续四周按 Event 输入产出；不能用单次渲染成功替代稳定性证明。
6. 若要产出 Evidence-backed Report 或付费 Deep Research，必须先取得逐次人工批准和完整 Evidence/Claim 门禁样本。

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
