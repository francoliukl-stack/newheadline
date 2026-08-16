# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

GBSS 外部事件情报系统：每天从公开信号中召回候选 → 写入钉钉 AI 表格的 `News` → 人工/AI 审核 → 聚合为 Event Case → 产出 Daily Report 与 Weekly Insight。

这不是一个部署到服务器的服务，而是一组由本机 launchd 定时触发的一次性 Python 脚本，加上一个只用于改配置的本地 FastAPI 页面。

## 常用命令

```bash
# 全量单元测试（约 350 个用例，纯本地，不联网、不调用 OpenAI）
.venv/bin/python -m unittest discover -s tests

# 单个测试文件 / 单个用例（必须在仓库根目录运行）
.venv/bin/python -m unittest tests.test_v3_1_services
.venv/bin/python -m unittest tests.test_v3_1_services.EventIntelligenceTests.test_same_event

# 静态 golden eval（发布门禁的一部分，同样离线）
.venv/bin/python scripts/run_v3_1_evaluation.py

# 配置 UI（改 Settings / 密钥 / 计划任务；不是业务入口）
.venv/bin/python -m uvicorn app.main:app --port 8765
```

发布门禁的完整顺序见 `docs/v3_1_runbook.md`：单测 → eval → `cutover_v3_1.py --dry-run` → `--apply`，回滚用 `cutover_v3_1.py --rollback`。

几乎每个 `scripts/*.py` 都支持 `--dry-run`，且 dry-run 意味着"读真实数据源但不写业务表、不发群消息、不计费"。改动任何写路径后，先跑对应脚本的 `--dry-run`。

## 数据放在哪里（最容易搞错的一点）

| 位置 | 内容 |
| --- | --- |
| 钉钉 AI 表格 | **全部业务数据**：News、Event Cases、Evidence Bank、Claim Ledger、Insights、API Usage、Audit Trail、Config、Detect Sources |
| `data/settings.sqlite3` | 只有本地配置、RunLog、待补写审计事件、候选池（candidate_pool） |
| `data/reports/`、`data/*.json` | 本地渲染产物与快照，均已 gitignore |

不要新建本地业务数据库，也不要写 migration（INV-02）。`app/dingtalk_ai_table.py` 是唯一的表格读写层；它自带 QPS 限流重试，并且**只对幂等请求做传输层重试**（POST 创建记录不重试，避免重复写入）。

候选池是未经审核的原始召回留档，任何报告都不得直接引用其中未进入 News 的条目。

## 架构分层

**采集** `app/detect_sources.py`（查询计划、去重、按 lane 平衡选取 30 条）+ `app/search_providers.py`（主/备/补召回 provider）+ `app/adapters/`（official RSS、GDELT、Marketaux、Firecrawl、yfinance、AlphaVantage，统一返回 `SourceSignal`/`ExtractedContent`/`MarketSignal`）。

**审核** `app/ai_news_review.py`：确定性打分 + 从人工历史重算的学习规则（`learn_review_rules`），产出 `AI Status`；`app/ai_review_rulebook.py` 加载 `docs/ai_review_labeling_rules.md` 里的机器可读 JSON 块。

**事件化** `app/event_intelligence.py`：`infer_event_type` / `match_entities` / `same_event` / `machine_priority` / `eventize_records` 是 eval 直接调用的纯函数，改动它们会同时影响 `evals/v3_1_event_cases*.json`。`app/event_tables.py` 负责建表与 Entity Catalog 种子。

**发布** `app/publish_format.py`、`app/gbss_report.py`、`app/event_weekly.py`、`app/weekly_insight_article.py`、`app/notifications.py`（钉钉 webhook）。

**治理横切** `app/run_logs.py`（RunLog）、`app/audit_trail.py`（写回钉钉 Audit Trail 表）、`app/cost_control.py`（预算预检 + API Usage 账本）、`app/storage.py` + `app/secrets.py`（配置与密钥）、`app/scheduler.py`（launchd plist 生成/安装）。

`app/scheduler.py` 的 `TASKS` 字典是 job 名到脚本的唯一映射；新增定时任务必须同时改 `TASKS`、`ScheduleSettings` 和 `install_launchd`。

## 脚本写法约定

`scripts/` 下大多数脚本**没有 `if __name__ == "__main__"`**，逻辑直接写在模块顶层，并遵循固定开头：

```python
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
run_logs = RunLogStore(DATA / "settings.sqlite3")
settings = store.load(masked=False)
audit = AuditTrailWriter(settings, store, run_logs)
run_id = run_logs.start("<job_name>", ...)
```

新脚本照抄这个结构。**RunLog 与 Audit 必须在读钉钉之前就 start**，这样连"读失败"也留痕。任务结束必须 `run_logs.finish(...)` 并写 Audit 终态。

失败一律 **fail closed**：宁可任务报错、不发消息，也不要发出 `0 / 0 / 0` 之类的半成品卡片或把空结果当成正常。钉钉投递成功的判定是 HTTP 成功 **且** 返回体 `errcode=0`，只看 HTTP 200 是错的。

## 不变量（改代码前必须知道）

来自 `docs/v3_1_event_intelligence_spec.md` §1，spec 是唯一实现依据：

- **INV-03**：`News=已采纳` 是唯一发布门。任何新链路都不能绕过它直接发布，也不能替人工写终态（Recall Sweep 只"提议"，不写 News）。
- **INV-04**：自动化只能给出 `P0 Candidate`/`P1`/`P2`/`Watch`；最终 `P0` 必须有 Reviewer + 审批状态 + 审批时间。eval 会统计 `p0_violations`，必须为 0。
- **INV-05/06**：付费调用前必须先成功写入 Audit 预检与 API Usage 预算预留；Event/Audit/Usage 任一不可用就跳过或失败关闭。
- 硬门禁强于任何学习规则：显式重复、缺 Source URL、缺 Publish Date 永远不得自动采纳。学习规则推翻原判时置信度上限 0.84，因此不会触发 11:50 自动采纳（阈值 0.85）。
- ADR-0002：自动生成的 Claim 中只有 `Fact` 类可自动对外，`Inference`/`Hypothesis` 待批；分界线是 `claim_type` 不是 `confidence`。

## 分析算力走订阅制 CLI，不走 OpenAI API

见 `docs/adr/0001`。`app/llm_carrier.py` 通过子进程调用 `codex exec`（主）/ `claude -p`（备）执行 Recall Sweep 与 Claim 生成，`openai_service` / `openai_research` 保持 `enabled=false`。

`app/llm_service.py` + `app/cost_control.py` 那一整套计量付费设施是**有意闲置**的，不是遗漏，不要"修复"它。同时注意：该链路的成本不进 API Usage 账本，故障只能靠 RunLog 与告警发现。

## 文档与评测的硬性规则

`tests/test_documentation_consistency.py` 会把下列规则跑成测试，违反即红：

- 根目录只允许 `README.md`、`CONTEXT.md`、`AGENTS.md`；所有新文档放 `docs/`，评测资产放 `evals/`。
- `docs/*.md` 与 `evals/*.md` 头部必须有 `> Version: / > Last-Updated: / > Status: (active|superseded) / > Supersedes:` 四行。
- `evals/release_evaluation_set.json` 的每条 case 必须引用 spec 中真实存在的 `REQ-\d{3}` / `INV-\d{2}` 编号；`release_evaluation_set.md` 的清单由 `scripts/generate_eval_checklist.py` 生成，不要手改。

改产品规则的顺序固定为：L1 PRD → L2 Spec（写 INV/REQ）→ L3 evals（引用编号）→ L4 Runbook。冲突时 L2 Spec 优先，详见 `docs/DOCS_GUIDE.md`。

`evals/v3_1_event_cases.json`（可见回归集）要求逐条 100% 通过；`evals/v3_1_event_cases_holdout.json` 是隔离 holdout，**设计或修改 eventization 规则时禁止查看其中 case**，也不得把 holdout 的答案抄进规则。新坏案例按进入顺序奇偶交替分配到两个集合。

## AI 审核规则手册

改 `scripts/ai_review_suggest.py` 前先读 `docs/ai_review_labeling_rules.md`（见 `AGENTS.md`）。该文件同时是人读文档和机读 JSON，改完保持 JSON 合法，并在 `Change Log` 加一条带日期的条目。人工推翻 AI 后，先跑一次 `ai_review_suggest.py` 写回反馈字段，只有反复出现的模式才升级为规则。

## 密钥

只能存在 Settings UI、`SecretStore`（`data/secrets.json`）或进程环境变量里。`app/models.py` 的 `SENSITIVE_FIELDS` 列出全部敏感字段，`SettingsStore` 靠它做掩码与落盘剥离——新增密钥字段必须同步加入该集合，否则会被明文写进 sqlite。密钥不得进入 Config 表、文档或仓库。

## 交流语言

仓库文档与提交信息以中文为主，代码注释与 spec 用英文；沿用所在文件的既有语言。`CONTEXT.md` 是领域术语表，写代码或文档时用它规定的词（Candidate / News / Event Case / Evidence / Claim / Signal Brief / Recall Sweep），避开其中标注的 `Avoid` 说法。
