# Release Evaluation Set

这份评测集用于每次 feature 上线前验证：代码变化没有破坏 PRD 中定义的采编、审核、日报、周报、钉钉触达、追溯和运营能力。

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
.venv/bin/python scripts/ensure_audit_trail.py
.venv/bin/python scripts/daily_health_check.py --dry-run
.venv/bin/python scripts/daily_publish.py --dry-run --limit 1
.venv/bin/python scripts/weekly_draft.py --dry-run --recent-count 5
.venv/bin/python scripts/weekly_publish.py --dry-run --recent-count 5
.venv/bin/python scripts/prepare_weekly_research.py --recent-count 5
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
- 正式发布只消费 `已采纳` 记录。
- Daily 和 Weekly 的发送标记彼此独立。
- 周六草稿不写 `Weekly Sent At`。
- 周日终稿发送成功后才写 `Weekly Sent At`。
- 周报成品写入 `Insights`，并保留源 News record IDs。
- 每次核心 workflow 与关键步骤写入独立 `Audit Trail`；审计记录可通过 Run ID、Source Record IDs、Report ID 和 Artifact URL 回溯。
- 每周研究必须将问题、证据、论点和审核状态分别保留在 `Research Queue`、`Evidence Bank` 和 `Claim Ledger`；未达到证据门槛时只能标记为 `Signal Brief`，不能冒充 Deep Research。
- 来源链接不能丢；周报和日报应使用源 URL 或源域名链接。
- Provider 主源失败时，有可用 fallback 就继续采编。
- 钉钉通知按 daily/weekly 配置路由，真实 mention 使用配置中的 mobiles/user ids。
- 周报群只推送可放大的图片；图片发送失败必须被记录，不得退回为文字版通知。
- launchd 日程变更必须持久化并验证安装状态。
