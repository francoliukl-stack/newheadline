# Release Evaluation Set

> Version: 3.1
> Last-Updated: 2026-07-11
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
.venv/bin/python -m unittest tests.test_settings.SettingsTests.test_gdelt_provider_reads_public_api_articles tests.test_settings.SettingsTests.test_gdelt_provider_translates_site_queries_to_domain tests.test_settings.SettingsTests.test_supplemental_providers_default_to_gdelt tests.test_settings.SettingsTests.test_supplemental_providers_skip_primary_and_fallback_duplicates tests.test_settings.SettingsTests.test_provider_health_marks_supplemental_provider_role
.venv/bin/python -m unittest tests.test_settings.SettingsTests.test_ai_table_write_mapping_uses_existing_manual_status_field
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

<!-- BEGIN GENERATED EVAL CHECKLIST -->
| Case ID | Type | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| EV-V31-AUTO-001 | automated |  |  |  |
| EV-V31-AUTO-005 | automated |  |  |  |
| EV-V31-AUTO-002 | automated |  |  |  |
| EV-V31-AUTO-003 | automated |  |  |  |
| EV-V31-AUTO-004 | automated |  |  |  |
| EV-PROVIDER-SUPPLEMENTAL-001 | automated |  |  |  |
| EV-DINGTALK-STATUS-FIELD-001 | automated |  |  |  |
| EV-AUTO-001 | automated |  |  |  |
| EV-DRY-001 | dry_run |  |  |  |
| EV-DRY-002 | manual |  |  |  |
| EV-DRY-002B | dry_run |  |  |  |
| EV-V31-DRY-002 | dry_run |  |  |  |
| EV-DRY-003 | dry_run |  |  |  |
| EV-DRY-004 | dry_run |  |  |  |
| EV-DRY-005 | live_safe |  |  |  |
| EV-LIVE-001 | manual |  |  |  |
| EV-LIVE-002 | manual |  |  |  |
| EV-LIVE-003 | manual |  |  |  |
| EV-LIVE-004 | manual |  |  |  |
| EV-LIVE-005 | manual |  |  |  |
| EV-LIVE-006 | manual |  |  |  |
| EV-AI-REVIEW-LEARNING-001 | automated |  |  |  |
| EV-AI-DEADLINE-001 | automated |  |  |  |
| EV-DAILY-EMPTY-001 | automated |  |  |  |
| EV-EVENT-STATUS-001 | automated |  |  |  |
| EV-ENTITY-RELATION-001 | automated |  |  |  |
| EV-BACKLOG-001 | automated |  |  |  |
| EV-MANUAL-001 | manual |  |  |  |
| EV-MANUAL-002 | manual |  |  |  |
| EV-MANUAL-003 | manual |  |  |  |
| EV-MANUAL-004 | manual |  |  |  |
| EV-DOC-001 | manual |  |  |  |
<!-- END GENERATED EVAL CHECKLIST -->
```

## 系统不变量索引

本评测说明不复述规则；完整定义见 [Spec §1](../docs/v3_1_event_intelligence_spec.md#1-invariants)。

- INV-01 — News 是信号与首次审核入口。
- INV-02 — 当前 workspace + 钉钉 AI 表格是生产形态。
- INV-03 — 已采纳 News、来源日期与血缘构成发布门。
- INV-04 — 最终 P0 必须人工批准。
- INV-05 — 付费调用必须通过预算与审批门禁。
- INV-06 — 关键存储不可用时失败关闭。
- INV-07 — 研究门禁未通过时只能输出 Signal Brief。
