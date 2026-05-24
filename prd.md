# 产品需求文档 (PRD)：基于现有 AI 资产与免维护工具链的高信号行业动态追踪系统

## 1. 业务全景与核心原则 (Executive Summary)

### 1.1 背景与终极痛点
用户日常需跨多平台（Gemini/ChatGPT/Exam）人肉检索、复制、排版支付与 Contact Center (Voice AI) 行业的重磅动态，存在高频切换、信息遗漏焦虑、周末憋周报熵增的痛点。本系统旨在利用本地自动化脚本与轻量工具链，将用户的角色从“信息搬运工”彻底解放为“最高决策审查者（Hard Gate Keeper）”。

### 1.2 极致 ROI 与管理哲学
* **零增量资产消耗：** 坚决不购买昂贵的第三方搜索/数据源 API。直接通过网页自动化技术（Playwright/Selenium）模拟登录用户已付费的 **ChatGPT Web 端（Plus 账号）**，利用其强大的全网联网检索与大规模语义清洗能力，作为免费的底层“信息编译器”。
* **零云端服务器成本：** 系统无需部署在任何云端服务器，完全依托用户本地工作站（如 Mac mini 或 PC），通过本地定时任务（`cron`）在后台静默驱动。
* **核心任务击穿与认知保护：** 宁缺毋滥，系统通过前置硬门槛挡掉 90% 噪音。用户日常只在飞书做单点审批（Y/N 采纳或拒绝），未处理内容滚动留存，从根本上消除遗漏焦虑。

---

## 2. 逆向倒排时间表与技术拓扑

为了确保**每周日下午 13:00 准时在钉钉公司群引爆高信号周报**，系统时间线进行了严密的逆向倒推排程：

* **周一至周六 02:00（`daily_fetch.py`）：** 静默触发。驱动自动化浏览器登录 ChatGPT Web 端进行全网海搜，洗出标准 JSON 格式数据，通过飞书官方轻量工具链直接写入飞书多维表格。
* **周一至周六 09:00（`daily_remind.py`）：** 自动盘点飞书所有处于“待处理”状态的行数，通过钉钉自定义机器人 Webhook 发送**滚雪球催办提醒**。用户在通勤或碎片时间花 1 分钟点选 [已采纳 / 已拒绝]。
* **周日早晨 09:00（`weekly_publish.py`）：** 定时收网。一键提取本周内所有标记为 `[已采纳]` 的黄金记录，再次驱动 ChatGPT 进行最终的格式严炼、超链接自动补全与英文翻译精炼。
* **周日早晨 09:30（交付件就绪）：** 最终的 Markdown 格式周报静静躺在用户的钉钉个人待办中，为下午 13:00 的准时发布留出 **3.5 小时绝对黄金缓冲垫**，供用户进行终审或微调。
* **周日下午 13:00（准时发布）：** 发布截止点。用户一键复制，准时分发轰炸群聊。

---

## 3. 核心功能模块详细需求

### 3.1 漏斗前端：ChatGPT Web 全网模糊海搜与消重 (`daily_fetch.py`)
* **执行逻辑：** 脚本利用 Playwright 或 Selenium 启动本地浏览器，静默维护/登录用户的 ChatGPT 账号。自动灌入包含 50+ 核心域名（如 Reuters, Payments Dive, CX Today）及特定垂直行业的 Prompt 矩阵。
* **AI 关键词联想扩展：** 约束 ChatGPT 联网时进行语义并集检索。例如搜 `Antom` 自动联想并集检索 `Alipay+` 或 `Ant International`；搜 `Voice AI` 自动联想 `Audio LLM` 或 `Conversational Intelligence`，防止因文章用词局限导致漏网。
* **渠道进化提议机制：** 约束 ChatGPT 在全网盲抓时，若发现未在 50+ 基础列表中的行业垂直新黑马实体连续出现 $\ge 2$ 次，在输出中单独标记为 `[Channel_Proposal]`。
* **语义消重与格式化：** 同一个新闻事件在多个渠道同时报道时，大模型需秒读正文并判别，仅保留最高权重源链接。最终强制约束 ChatGPT 仅输出标准的 JSON 文本块，严禁任何零碎的 Commentary 废话。

### 3.2 漏斗中段：飞书 AI 表格画布与“滚雪球”防漏提醒 (`daily_remind.py`)
* **飞书多维表格（Bitable）设计：** 利用飞书官方轻量 SDK（如 `lark-oapi`）或本地 CLI 工具，通过环境变量（`APP_ID` / `APP_SECRET`）进行云端免密对刷：
  * `ID`：自动生成唯一流水号（如 `NEWS_20260524_001`）
  * `Section`：下拉菜单（Finance / Contact Center）
  * `Label`：单选（Regulation / Product / Funding / Partnership / Benchmark / M&A / Market Expansion / Earnings / Leadership）
  * `Title & URL`：文本（自动剥离重定向，保留最原始 Tier-1 域名超链接）
  * `Status`：单选（待处理 / 已采纳 / 已拒绝，**默认：待处理**）
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
  2. 将这批高信号数据再次投喂给 ChatGPT Web 端，执行原 Prompt 的严苛编辑纪律：每行英文纯文本严格 $\le 20$ 字，单分类最多 10 行，单域名在单版块中最高频次 $\le 3$。
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