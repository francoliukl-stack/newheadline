# 高价值新闻覆盖与周度输入新鲜度升级实施计划

> **状态：** 已获用户确认，按本计划在当前 `codex/gbss-v3-1-event-intelligence` 分支内实施。
>
> **设计合同：** `docs/superpowers/specs/2026-07-26-news-coverage-recall-upgrade-design.md`
>
> **实施方式：** 当前生产配置、运行数据库与既有功能分支在同一工作区；工作树已确认干净，因此不另建 worktree。每个功能先写失败测试，再写最小实现并单独验证。

## 目标

建立五路召回、人工策展、事件分类、覆盖审计和 Weekly Insight 输入指纹门禁，使本次五条高价值样本可稳定进入 News、Event、日报/周报合法输入，并在研究输入变化时阻止过期文档发布。

## Task 1：召回 Lane、主题与候选配额

**文件：**

- 修改：`app/detect_sources.py`
- 修改：`scripts/daily_fetch.py`
- 修改：`tests/test_settings.py`
- 新增：`evals/news_coverage_regression_set.json`

**步骤：**

1. 在 `tests/test_settings.py` 增加失败测试：
   - 默认 Detect Sources 包含 Agentic Payments、Embedded Finance / B2B Payments、Agentic CX。
   - Reuters、TechCrunch、Electronic Payments International、No Jitter、OpenAI 产生主动可信来源查询。
   - `PlannedQuery` 带 `lane`；Core、Theme、Trusted 查询分别可识别。
   - 自动候选池按 Core=6、Theme=6、Trusted=6 保留最低配额，缺额会释放；Editorial 记录不受自动池 30 条限制。
2. 运行定向测试并确认红灯：
   - `.venv/bin/python -m unittest tests.test_settings.SettingsTests.test_*coverage*`
   - 如测试类名不同，使用精确测试节点逐个运行。
3. 在 `app/detect_sources.py`：
   - 扩展 `PlannedQuery` 增加 `lane`。
   - 新增三个主题种子和五个主动可信来源种子。
   - 可信来源查询按小组、结合对应主题词生成，避免裸超长 OR。
   - 新增稳定 Lane 推断与 quota selection 纯函数；保留旧调用兼容。
4. 在 `scripts/daily_fetch.py`：
   - 将 lane 写入候选结构。
   - 使用 Lane 配额选择自动候选。
   - 在 `latest-provider-results.json` 和 RunLog metadata 中保存各 Lane raw/selected 计数。
5. 创建五条样本回归 fixture，记录 URL、预期 Lane、实体、事件类型、业务线和资格。
6. 运行定向测试至绿灯并提交：
   - `git add app/detect_sources.py scripts/daily_fetch.py tests/test_settings.py evals/news_coverage_regression_set.json`
   - `git commit -m "Add strategic news recall lanes and quotas"`

## Task 2：实体目录与事件类型覆盖

**文件：**

- 修改：`app/event_tables.py`
- 修改：`app/event_intelligence.py`
- 修改：`tests/test_v3_1_services.py`

**步骤：**

1. 增加五条回归标题的失败测试，断言：
   - Natural → `Strategic_MA`，业务线 `Antom, WorldFirst`
   - Visa × Airwallex → `Channel_Partner`，业务线 `Alipay_Plus, Antom, WorldFirst`
   - Visa × LianLian → `Product_Launch`，业务线 `Alipay_Plus, Antom, WorldFirst`
   - OpenAI Presence → `Product_Launch`，业务线 `GBSS_Service`
   - Ant International 融资 → `Strategic_MA`，五条核心业务线
2. 增加 `eventize_records` 读取 `Manual Status` 的回归测试。
3. 运行定向测试并确认红灯。
4. 在 `app/event_tables.py` 增加/扩展：
   - `ant-international`
   - `openai`
   - `agentic-payments`
   - `embedded-finance`
   - Visa、LianLian、Airwallex 的业务线映射。
5. 在 `app/event_intelligence.py` 增加确定性模式：
   - 支付语境下 `join forces/collaboration/teams up` → `Channel_Partner`
   - `first live/completes first` + agentic payment → `Product_Launch`
   - `OpenAI Presence` → `Product_Launch`
   - `agentic payments/payments for AI agents` 的产品或基础设施表达 → `Product_Launch`
   - 状态过滤统一使用 `status_name`。
6. 运行定向测试至绿灯并提交：
   - `git add app/event_tables.py app/event_intelligence.py tests/test_v3_1_services.py`
   - `git commit -m "Cover agentic payment and CX event signals"`

## Task 3：AI Review Rulebook 高价值模式

**文件：**

- 修改：`docs/ai_review_labeling_rules.md`
- 修改：`tests/test_v3_1_services.py`

**步骤：**

1. 已按项目规则读取 `docs/ai_review_labeling_rules.md`。
2. 先增加失败测试，覆盖：
   - 具体 agentic payment 基础设施/融资。
   - 官方企业 Agent 产品发布。
   - 明确支付合作和首笔 live transaction。
   - 缺 URL、缺 Publish Date、明确重复仍被硬门禁拒绝。
3. 运行定向测试并确认红灯。
4. 修改 rulebook JSON，新增高价值模式；保持 JSON 合法。
5. 在 `Change Log` 增加 `2026-07-26` 记录。
6. 运行 rulebook 加载、推荐与硬门禁测试至绿灯并提交：
   - `git add docs/ai_review_labeling_rules.md tests/test_v3_1_services.py`
   - `git commit -m "Teach review rules high-value agentic signals"`

## Task 4：人工 URL Intake 与 Coverage Audit

**文件：**

- 新增：`app/editorial_intake.py`
- 新增：`app/coverage_audit.py`
- 新增：`scripts/ingest_editorial_urls.py`
- 新增：`tests/test_news_coverage.py`
- 修改：`app/event_tables.py`（如需新增 News 审计字段）

**步骤：**

1. 在 `tests/test_news_coverage.py` 先写失败测试：
   - URL 规范化、无效 URL 和缺发布日期阻断。
   - `--approve` 生成 `editorial_input`、`editorial_must_include`、`Human`、`已采纳`。
   - 非 approve 保持 `待处理`。
   - 已存在 URL 只补缺失字段，不覆盖更高质量人工标题/摘要。
   - 五条输入能产生 created/updated/duplicate/blocked 稳定结果。
   - Coverage Audit 输出设计中的稳定原因枚举。
2. 运行新测试并确认红灯。
3. 在 `app/editorial_intake.py` 实现纯函数：
   - 输入验证、URL 规范化、现有记录索引、create/update patch 规划。
   - 明确人工审批字段和硬门禁。
4. 在 `app/coverage_audit.py` 实现目标 URL 到 News/Event/资格的纯函数映射与 JSON payload。
5. 在 `scripts/ingest_editorial_urls.py` 编排：
   - 读取 JSON。
   - 一次读取 News 与字段映射。
   - 应用 create/update。
   - 写 RunLog/Audit Trail。
   - 输出 `data/coverage-audit-latest.json`。
   - 成功后仅调用窄链路 `eventize_news.py --apply`，不运行完整 `daily_fetch`。
6. 运行新测试至绿灯，再运行脚本 `--dry-run`（若实现）或 fixture-only 验证并提交：
   - `git add app/editorial_intake.py app/coverage_audit.py scripts/ingest_editorial_urls.py tests/test_news_coverage.py app/event_tables.py`
   - `git commit -m "Add audited editorial news intake"`

## Task 5：Research Queue 输入指纹与发布门禁

**文件：**

- 修改：`app/research_production.py`
- 修改：`app/market_research_plan.py`
- 修改：`scripts/request_openai_deep_research.py`
- 修改：`scripts/prepare_weekly_research.py`
- 修改：`scripts/weekly_publish.py`
- 修改：`tests/test_settings.py`

**步骤：**

1. 先写失败测试：
   - 事件 ID 集合排序、去重后产生稳定 fingerprint。
   - 相同集合顺序不同 fingerprint 相同；新增/移除事件时 fingerprint 改变。
   - Queue upsert 保留现有人工状态，但正确更新输入字段。
   - publish preflight 在 fingerprint 不一致时返回稳定阻断结果，列出新增/移除 Event。
   - stale 时原地生成刷新 patch，状态改为等待新文档并清空旧 URL；一致且 HTTPS 才通过。
2. 运行定向测试并确认红灯。
3. 在 `RESEARCH_QUEUE_FIELDS` 增加：
   - `Input Event IDs`
   - `Input Fingerprint`
   - `Input Generated At`
   - `Coverage Checked At`
4. 在 `app/research_production.py` 实现：
   - `research_input_event_ids`
   - `research_input_fingerprint`
   - `research_input_preflight`
   - 原地 stale refresh patch 纯函数。
5. 在周五准备/请求脚本中写入输入集合与 fingerprint。
6. 在 `scripts/weekly_publish.py`：
   - 在 URL 门禁之前比较当前 accepted Event 输入。
   - stale 时更新同一 Queue 行、清空旧 URL、写 Audit/RunLog、fail closed，且不写 sent markers。
   - 一致后继续保留现有 HTTPS URL 门禁。
7. 运行定向测试至绿灯并提交：
   - `git add app/research_production.py app/market_research_plan.py scripts/request_openai_deep_research.py scripts/prepare_weekly_research.py scripts/weekly_publish.py tests/test_settings.py`
   - `git commit -m "Gate weekly research on fresh event inputs"`

## Task 6：全量验证、线上补录与当前周恢复

**本地验证：**

1. 运行五条回归评测。
2. 运行完整单元测试：
   - `.venv/bin/python -m unittest discover -s tests`
3. 运行相关 dry-run：
   - `.venv/bin/python scripts/ai_review_suggest.py --dry-run`
   - `.venv/bin/python scripts/daily_remind.py --dry-run`
   - `.venv/bin/python scripts/weekly_publish.py --dry-run`
4. 检查 `git diff --check`、`git status --short`。

**线上迁移与验证：**

1. 同步 Detect Sources 与 Entity Catalog 新种子；回读新增记录。
2. 用 `data/editorial-intake.json` 导入五条已获用户明确审批的 URL。
3. 回读 News 五条，确认：
   - canonical URL
   - `Manual Status/Review Status = 已采纳`
   - `Search Provider = editorial_input`
   - `Discovery Type = editorial_must_include`
   - `Review Decision Source = Human`
4. 运行窄链路 Eventize，回读五个 Event Case/Event Source，核对类型和业务线。
5. dry-run 日报与 Weekly Headlines/Insight 选择，证明五条进入合法输入，不发送。
6. 原地更新 Research Queue `iC8t3BSd21`：
   - 更新 Topic、Primary Question、Approval Plan/Evidence Plan。
   - 写入五条 Event ID 和 fingerprint。
   - 如果当前钉钉文档无法证明覆盖新输入，将旧 URL 清空或标记等待刷新链接。
7. 回读 Research Queue、Coverage Audit 与 RunLog。
8. 只有 Queue fingerprint 与当前 accepted Event 集合一致、研究文档覆盖新输入且 URL 有效时，才正式发布完整 Weekly Insight；否则保持阻断并明确告诉用户所需动作。

## 完成标准

- 五条回归样本 5/5 进入 News，5/5 已采纳，5/5 形成 Event。
- Event Type 和 Business Lines 5/5 与设计 fixture 一致。
- Core/Theme/Trusted Lane 的保留配额测试通过，Editorial 不受 30 条限制。
- Coverage Audit 对每条给出稳定、可追踪原因。
- Research Queue stale 输入会 fail closed，且不写任何 sent marker。
- 全量测试、rulebook dry-run、报告选择 dry-run 和线上回读均通过。

