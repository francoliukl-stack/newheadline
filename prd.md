# 产品需求文档 (PRD)：基于现有 AI 资产与免维护工具链的高信号行业动态追踪系统

## 1. 业务全景与核心原则 (Executive Summary)

### 1.1 背景与终极痛点
用户日常需跨多平台（Gemini/ChatGPT/Exam）人肉检索、复制、排版支付与 Contact Center (Voice AI) 行业的重磅动态，存在高频切换、信息遗漏焦虑、周末憋周报熵增的痛点。本系统旨在利用本地自动化脚本与轻量工具链，将用户的角色从“信息搬运工”彻底解放为“最高决策审查者（Hard Gate Keeper）”。

### 1.2 极致 ROI 与管理哲学
* **可替换搜索源，默认零增量资产消耗：** 系统底层不绑定 Codex，也不强制购买昂贵第三方搜索 API，而是抽象为 `Search Provider`。默认主源可使用用户已付费的 **ChatGPT Web 端（Plus 账号）**，通过 Playwright/Selenium 维护本地浏览器会话；备用源可使用 Gemini Web、OpenClaw 既有缓存、手工种子文件，或在未来按需接入 SerpAPI / Bing Web Search / Serpstack 等付费 API。
* **无人值守优先：** 正常运行链路必须脱离 Codex 当前会话。Codex 内置联网搜索只允许作为人工预览和调试来源，不进入 `daily_fetch.py` 的生产依赖。
* **零云端服务器成本：** 系统无需部署在任何云端服务器，完全依托用户本地工作站（如 Mac mini 或 PC），通过本地定时任务（`cron`）在后台静默驱动。
* **核心任务击穿与认知保护：** 宁缺毋滥，系统通过前置硬门槛挡掉 90% 噪音。用户日常只在飞书做单点审批（Y/N 采纳或拒绝），未处理内容滚动留存，从根本上消除遗漏焦虑。

---

## 2. 逆向倒排时间表与技术拓扑

为了确保**每周日下午 13:00 准时在钉钉公司群引爆高信号周报**，系统时间线进行了严密的逆向倒推排程：

* **周一至周六 02:00（`daily_fetch.py`）：** 静默触发。读取本地系统设置中的 `Search Provider`，按主源/备用源顺序进行全网海搜或缓存读取，洗出标准 JSON 格式数据，通过飞书官方轻量工具链直接写入飞书多维表格。
* **周一至周六 09:00（`daily_remind.py`）：** 自动盘点飞书所有处于“待处理”状态的行数，通过钉钉自定义机器人 Webhook 发送**滚雪球催办提醒**。用户在通勤或碎片时间花 1 分钟点选 [已采纳 / 已拒绝]。
* **周日早晨 09:00（`weekly_publish.py`）：** 定时收网。一键提取本周内所有标记为 `[已采纳]` 的黄金记录，调用配置中的 AI 编译器执行最终的格式严炼、超链接自动补全与英文翻译精炼。
* **周日早晨 09:30（自动发布）：** 最终 Markdown 周报自动发送到钉钉群；发送成功后回写 `Publish Status = 已发送` 与 `Sent At`。
* **周日下午 13:00（复核窗口）：** 如需补充说明，可在已发布周报基础上人工追加；正常情况下无需再手工复制分发。

### 2.1 自动化边界
* 除人工审核确认外，其余步骤必须自动运行：Provider 健康检查、采集、入表、发布时间补齐、链接规范化、语义去重、待审核提醒、周报发送、发送状态回写。
* `daily_fetch.py` 在采集前检查主 Provider 与备用 Provider；任一 Provider 无效时通过钉钉群机器人告警，主源失效但备用源有效时自动降级继续运行。
* `daily_remind.py` 在发送待审核提醒前再次执行 Provider 健康检查，确保失效问题不会静默存在。

### 2.2 编辑台流程名称
后台、运行日志和日常沟通统一使用以下短名称：

| 名称 | 英文代号 | 对应动作 | 自动执行时机 |
| --- | --- | --- | --- |
| **采编** | `INGEST` | 检查 Provider，获取候选新闻，规范链接，写入钉钉 `News` 表，补齐 `Publish Date`，识别并标记重复项 | 周一至周六 02:00 |
| **催审** | `REVIEW` | 汇总 `待处理` 数量并发送钉钉提醒 | 周一至周六 09:00 |
| **出刊** | `PUBLISH` | 将 `已采纳` 且未发送的新闻整理成周报并推送；成功后登记 `Publish Status` 与 `Sent At` | 周日 09:00 |

其中，来源检查、写入 `News`、补齐发布时间和语义去重仅作为“采编”的内部排错明细，不作为需要单独记忆的流程步骤。

---

## 3. 核心功能模块详细需求

### 3.1 漏斗前端：Search Provider 全网模糊海搜与消重 (`daily_fetch.py`)
* **Provider 抽象：** `daily_fetch.py` 不直接依赖 Codex，而是读取本地设置中的 `search_provider` 配置。支持的 Provider 类型包括 `chatgpt_web`、`gemini_web`、`serpapi`、`bing_web_search`、`serpstack`、`openclaw_cache`、`manual_seed`。默认主源为 `chatgpt_web`，默认备用源为 `openclaw_cache`。
* **执行逻辑：** 当 Provider 为 ChatGPT Web / Gemini Web 时，脚本利用 Playwright 或 Selenium 启动本地浏览器并维护登录会话；当 Provider 为 API 型搜索源时，通过本地保存的 API Key 调用；当 Provider 为 OpenClaw Cache 或 Manual Seed 时，从本地文件读取候选新闻。所有 Provider 必须输出统一的 `SearchResult` 结构，再进入同一套筛选、去重和落库流程。
* **AI 关键词联想扩展：** 搜索层按关键词矩阵做语义并集扩展。例如搜 `Antom` 自动联想并集检索 `Alipay+` 或 `Ant International`；搜 `Voice AI` 自动联想 `Audio LLM` 或 `Conversational Intelligence`，防止因文章用词局限导致漏网。
* **渠道进化提议机制：** 若任一 Provider 发现未在 50+ 基础列表中的行业垂直新黑马实体连续出现 $\ge 2$ 次，在输出中单独标记为 `[Channel_Proposal]`。
* **语义消重与格式化：** 同一个新闻事件在多个渠道同时报道时，后处理层判别事件相似度，仅保留最高权重源链接。最终强制输出标准 JSON，严禁任何零碎 Commentary 废话。

### 3.1.1 Search Provider 配置要求
* `provider`：主搜索源，默认 `chatgpt_web`。
* `fallback_provider`：备用搜索源，默认 `openclaw_cache`；主源未配置、登录失效、API 失败时自动降级。
* `api_key` / `api_base_url`：仅用于 SerpAPI、Bing Web Search、Serpstack 等 API 型 Provider，密钥必须本地脱敏保存。
* `browser_profile_path`：用于 ChatGPT Web / Gemini Web 的本地浏览器会话路径。
* `openclaw_cache_path`：用于读取 OpenClaw 已有新闻缓存，默认 `/Users/franco/.openclaw/workspace/tmp/news-pending.json`。
* `manual_seed_path`：用于离线调试或人工导入候选新闻。
* `use_codex_search`：仅允许人工预览，生产无人值守运行必须为 `false`。

### 3.2 漏斗中段：飞书 AI 表格画布与“滚雪球”防漏提醒 (`daily_remind.py`)
* **飞书多维表格（Bitable）设计：** 利用飞书官方轻量 SDK（如 `lark-oapi`）或本地 CLI 工具，通过环境变量（`APP_ID` / `APP_SECRET`）进行云端免密对刷：
  * `ID`：自动生成唯一流水号（如 `NEWS_20260524_001`）
  * `Section`：下拉菜单（Finance / Contact Center）
  * `Label`：单选（Regulation / Product / Funding / Partnership / Benchmark / M&A / Market Expansion / Earnings / Leadership）
  * `Title & URL`：文本（自动剥离重定向，保留最原始 Tier-1 域名超链接）
  * `Status`：单选（待处理 / 已采纳 / 已拒绝 / 已重复，**默认：待处理**）
  * `No`：新闻唯一编号。语义去重命中时，最早发现的记录保留 `待处理`，后续近似新闻标记为 `已重复`。
  * `Duplicate Of`：重复记录指向主记录的 `No`，便于回查同一事件的不同表达方式。
  * `Rejection Reason`：当 `Status == '已拒绝'` 时记录拒绝原因，支持人工输入并为后续 AI 精准标注提供训练依据。
* **滚雪球防漏算法（延续性提醒）：** 脚本每日 09:00 扫描飞书表格中所有 `Status == '待处理'` 的行。如果用户前几天因工作忙碌没有点选，历史未确认数据会自动滚动求和，连同当天新流入的数据一起打包提醒。池子里的未办事项会一直挂起，直到状态被变更为“已采纳”或“已拒绝”才移出待办池，实现绝对防漏。
* **钉钉每日催办通知格式（Webhook）：**
  > 🔔 **【山丰，今日信息流审核画布已就绪】**
  > * **今日新到：** 10 条（高亮命中：Antom, Sierra.ai）
  > * **历史积压（未确认）：** 14 条（*系统已自动去重合并，请尽快清理*）
  > * 💡 **【渠道扩充提议】**：检测到新实体 *Vapi.ai* 本周高频爆发，[点击此处] 查看理由并一键审批入库。
  > * 👉 [点击直达飞书多维表格专属视图]

### 3.3 漏斗后端：周日早晨自动打包精炼机制 (`weekly_publish.py`)
* **数据抓取窗口：** 每周日上午 09:00 触发，严格截取至**本周校准截点（BJ 时间）**，完美覆盖上周日到本周六的完整 7 天闭环数据。
* **执行逻辑：** 
  1. 自动调用飞书 SDK，一键拉取本周内所有 `Status == '已采纳'` 的黄金记录。
  2. 将这批高信号数据投喂给配置中的 AI 编译器（默认可复用 ChatGPT Web，会作为后续 `compiler_provider` 抽象），执行原 Prompt 的严苛编辑纪律：每行英文纯文本严格 $\le 20$ 字，单分类最多 10 行，单域名在单版块中最高频次 $\le 3$。
  3. **超链接自动补全：** 脚本自动解析源 URL 的根域名（如 `reuters.com`），并用 Markdown 的 `[简写](全量URL)` 语法自动包裹补全，确保在钉钉端既不破坏阅读体验，又能点击直达源头。
  4. 上午 09:30 前，通过 Webhook 将渲染好的最终 Markdown 结果打入用户的钉钉个人工作台。用户拥有 3.5 小时的弹性时间随时阅示或进行微调，锁定 13:00 准时发布。

---

## 4. 最终触达效果标准 (钉钉群直接发布版格式)

系统编译生成的最终交付物必须 100% 匹配以下格式（严格对齐火箭符号、小标题、免责声明及署名），以便一键复制直接发布：

```markdown
Finance & Contact Center Weekly Headlines 🚀

## Finance, Payments & Banking

* **Earnings:** Ant Group quarterly profit falls 79% as AI and healthcare spending surge ([fintechnews.hk](https://fintechnews.hk))
* **Product:** Stripe enables Link wallet for AI agents to autonomously execute secure B2B transactions ([linkedin.com](https://www.linkedin.com))
* **Product:** Ant International launches sustainability report, highlighting modular AI tools for 1.5M SMEs via WorldFirst ([forbes.com](https://www.forbes.com))
* **Market Expansion:** Wise completes London-to-Nasdaq listing migration ([reuters.com](https://www.reuters.com))
* **Market Expansion:** XTransfer opens São Paulo office, launches X-Net settlement network in Latin America ([businesswire.com](https://www.businesswire.com))
* **Regulation:** UK FCA probes PayPal, Visa, Mastercard wallet agreements ([reuters.com](https://www.reuters.com))
* **Product:** Airwallex launches global in-person payments strategy ([techcrunch.com](https://techcrunch.com))

## Contact Center with Voice AI

* **Product:** Salesforce Summer '26 features Multi-Agent Orchestration in Agentforce for complex service workflows ([salesforce.com](https://www.salesforce.com))
* **Product:** AWS rebrands Amazon Connect, expanding into four distinct agentic AI solutions ([nojitter.com](https://www.nojitter.com))
* **Funding:** Deepgram raises $130M Series C at $1.3B valuation for speech AI ([techcrunch.com](https://techcrunch.com))
* **Market Expansion:** Vapi wins Amazon Ring deployment, hitting $500M valuation ([techcrunch.com](https://techcrunch.com))
* **Benchmark:** Gartner flags CX observability as primary Voice AI deployment bottleneck ([cxtoday.com](https://www.cxtoday.com))

--------------------------
More details and prompt > Weekly Headlines <MAY - 17 23 MAY>

*Note: All the above information was generated by AI and merged manually for verification. If you have any suggestions or feedback, please feel free to contact me / @山丰/Franco at any time.*
