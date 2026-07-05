# Release Evaluation Set

> Version: 3.1
> Last-Updated: 2026-07-05
> Status: active
> Supersedes: none

这份评测集用于每次 feature 上线前验证：代码变化没有破坏 PRD 中定义的采编、审核、日报、周报、钉钉触达、追溯和运营能力。v3.1 还必须验证 Event Case、关键事件召回、OpenAI/钉钉付费调用治理和 P0 人工门禁。

结构化用例在 `evals/release_evaluation_set.json`。本文件是执行说明和人工验收入口。

## 执行原则

- 每次发布前至少跑完 `automated` 和 `dry_run` 用例。
- `live_safe` 用例会连接真实钉钉表或本地 launchd，发布前应跑；如果跳过，必须记录原因。
- `manual` 用例用于检查钉钉群渲染、文档权限、图片效果和管理层阅读质量。
- 任何影响 News、Daily publish、Weekly publish、Insights、Audit Trail、Config、Research Topics、DingTalk 路由、schedule 的 feature，都必须跑完整套。
- 如果只改文档或注释，可以只跑 `EV-AUTO-001`、`EV-DOC-001` 和相关文档检查。

## 快速命令

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_v3_1_evaluation.py
.venv/bin/python scripts/daily_health_check.py --dry-run
.venv/bin/python scripts/weekly_headlines.py --dry-run
.venv/bin/python scripts/request_openai_deep_research.py --dry-run --recent-count 5
.venv/bin/python scripts/weekly_publish.py --dry-run --recent-count 5
.venv/bin/python -m unittest tests.test_v3_1_services.V31ServiceTests.test_critical_scan_reuses_news_snapshot_after_insert tests.test_v3_1_services.V31ServiceTests.test_empty_event_upsert_does_not_read_remote_table tests.test_settings.SettingsTests.test_configured_audit_sheet_skips_paid_schema_reads
```

## 发布验收记录模板

```markdown
## Release Eval Result

- Date:
- Feature / branch:
- Evaluator:
- Commit:
- Environment:
- Overall result: Pass / Conditional Pass / Fail

| Case ID | Result | Evidence | Notes |
| --- | --- | --- | --- |
| EV-V31-AUTO-001 |  |  |  |
| EV-V31-AUTO-002 |  |  |  |
| EV-V31-AUTO-003 |  |  |  |
| EV-V31-AUTO-004 |  |  |  |
| EV-V31-AUTO-005 |  |  |  |
| EV-AUTO-001 |  |  |  |
| EV-DRY-001 |  |  |  |
| EV-DRY-002 |  |  |  |
| EV-DRY-003 |  |  |  |
| EV-DRY-004 |  |  |  |
| EV-DRY-005 |  |  |  |
| EV-LIVE-001 |  |  |  |
| EV-LIVE-002 |  |  |  |
| EV-LIVE-005 |  |  |  |
| EV-LIVE-006 |  |  |  |
| EV-MANUAL-001 |  |  |  |
| EV-MANUAL-002 |  |  |  |
| EV-MANUAL-003 |  |  |  |
| EV-MANUAL-004 |  |  |  |
```

## 必须守住的 PRD 底线

- `News` / `oMbefcK` 是当前 canonical 输入表。
- 日常唯一人工发布门是 `News=已采纳`；关联 Event Case 状态由系统同步，不要求人工重复采纳，并须具备 Event/Evidence/Claim/URL/Publish Date 追溯。
- 系统不得自动设置最终 P0；只能提出 P0 Candidate。
- 任何付费调用必须先通过单次、日、周、月成本门禁；钉钉 AI 表格调用额度也属于生产预算。
- 无新增关键新闻时不得继续读取下游 Event/Evidence/Claim/Alert 表；空 Upsert 必须做到零远端读取；Audit Trail Sheet ID 已配置时定时任务不得重复枚举字段。
- 正式发布只消费 `已采纳` 记录。
- Daily Report 和 Weekly Insight 的发送标记彼此独立；旧单条 `daily_publish` 必须保持关闭。
- 周五研究任务只生成 3–4 个方向和可粘贴 ChatGPT Deep Research Prompt，不调用项目内付费研究 API。
- 周日 Weekly Insight 只在有效 `Research Document URL` 存在时发送“钉钉报告链接 + Event/新闻”；成功后才写 `Weekly Intelligence Sent At`。
- 权限提示必须紧跟报告链接并位于 `Weekly Key Events & News` 之前；钉钉 link-cell 对象及最近三天周五计划复用必须有自动测试。
- 周报成品写入 `Insights`，并保留源 News record IDs。
- 每次核心 workflow 与关键步骤写入独立 `Audit Trail`；审计记录可通过 Run ID、Source Record IDs、Report ID 和 Artifact URL 回溯。
- 每周人工研究方向和 Prompt 保存在 `Research Queue.Approval Plan`，成稿链接保存在 `Research Document URL`；缺链接时失败关闭。
- 来源链接不能丢；周报和日报应使用源 URL 或源域名链接。
- Provider 主源失败时，有可用 fallback 就继续采编。
- 钉钉通知按 daily/weekly 配置路由，真实 mention 使用配置中的 mobiles/user ids。
- Weekly Insight 不再生成图片 One Pager；群内只发送人工研究文档链接及可追溯新闻摘要。
- launchd 日程变更必须持久化并验证安装状态。
