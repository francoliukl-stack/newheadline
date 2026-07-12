# 设计：工作时段高频快扫 + 快讯 RSS + 财报日历（更快的关键事件播报）

> Date: 2026-07-12
> Status: draft (待评审)
> Owner: Franco / GBSS
> 目标读者: 实现者（写实现计划前的合同）

## 1. 背景与问题

老板反馈"消息推送太滞后，做不到第一时间播报"，尤其是**公司财报发出及对应解读**。

现状（本次评估结论）：
- "实时"路径是 `scripts/critical_event_scan.py`，launchd 固定每 4 小时跑一次（本地 GMT+8 的 1/5/9/13/17/21 点）。落在工作时段（9–18）的只有 9/13/17 三次。
- **没有财报日历**：系统不知道某公司"何时"发财报，只能等财报新闻在某次 4 小时扫描里被动撞到。
- 一条 09:05 发出的财报，最坏要等到 13:00 才被发现 → 结构性滞后 ~4 小时。

已核实、决定不改的事实：
- **解读已内联**：发现新关键事件时，`enrich_events_with_llm` 就地生成解读并随 `send_event_alerts` 推送。解读不是瓶颈，**检测时延**才是。
- **计费成本按事件数、不按扫描频率**：LLM 解读与 Firecrawl 抽正文仅对 `new_record_ids`（新加入的 News）触发，且按 URL 去重；同一条财报被去重后不会重复处理。扫得勤只是让它更早被发现，不额外烧 token。
- OpenAI 花费已有 `BudgetController` 的 daily/weekly/**monthly** 硬上限预检保护。

## 2. 目标与非目标

### 目标
1. 在 **GMT+8 工作时段（9:00–18:00）**将关键事件（尤其财报）的检测时延从最坏 ~4h 压到 ~3h 内，并通过更快、更直接的源进一步降低实际时延。
2. 覆盖两类主体：有财报日历的**美股上市竞对**、以及无日历的**私有自家公司**（Alipay+/WorldFirst/Antom/Ant Bank HK/AlipayHK 等）。
3. **不超月度免费额度**：新闻类计费 API 与 AlphaVantage 维持受控用量。

### 非目标
- 秒级/真实推送（webhook/流式付费源）——本期不做。
- 非工作时段的加速——维持现有稀疏锚点即可。
- 为私有公司造"财报日历"——它们不在任何交易所日历，物理上做不到；靠高频 IR/快讯覆盖。

## 3. 架构：双模关键扫描

引入扫描模式 `--mode {fast,anchor}`（默认 `anchor`，保持向后兼容）。

| 模式 | 触发 | 源 | 目的 |
| --- | --- | --- | --- |
| **fast** | 工作时段 **9/12/15/18 GMT+8**（每 3h） | **仅 官方 IR + 快讯 RSS**（免费直连） | 低时延捕获财报/关键事件；无 token、无计费 API |
| **anchor** | 稀疏（详见 §8 调度） | 全部源（IR/RSS + GDELT + marketaux + AlphaVantage 价格 + yfinance） | 广度召回 |

两种模式发现新事件后走**完全相同**的 `eventize → enrich_events_with_llm（解读）→ send_event_alerts` 链路。差异只在**采集的源集合**与**调度**。

### 为什么保留双模（而非直接提高全量扫描频率）
更高频运行会成比例消耗 **AlphaVantage**（免费 ~25 次/天）与触发更多 GDELT 429。fast 模式把计费/限流源排除在外，只跑免费直连源，从而"频率与额度解耦"。

## 4. 组件与改动

### C1. 扫描模式与工作时段闸门 — `scripts/critical_event_scan.py`
- `main()` 增加 `--mode {fast,anchor}`（默认 `anchor`）。
- 增加工作时段闸门：`fast` 模式下若当前不在 9:00–18:00 GMT+8（用 `settings.system.timezone`）则记一条 no-op RunLog 后退出（幂等、便宜）。`anchor` 不受闸门限制。
- 将 `mode` 传入 `collect_critical_signals`。

### C2. 按模式过滤源 — `collect_critical_signals(settings, catalog, mode="anchor")`
- 新增 `mode` 参数。`fast` 模式：**只调 OfficialSourceAdapter**（官方 IR + RSS），跳过 GDELT / marketaux / AlphaVantage / yfinance。
- `anchor` 模式：维持现状（所有 `*_enabled` 门控的源）。
- 该函数为纯采集，便于单测：给定 mode 断言只调用了预期的适配器集合。

### C3. 快讯 RSS 源接入 — 实体/来源配置（数据 + 少量代码）
- `OfficialSourceAdapter` 已能识别 XML/RSS 内容并解析 `<item>/<{*}entry>`（`app/adapters/official.py`），**无需新适配器**。
- 工作：为相关实体补充**快讯 feed URL**（GlobeNewswire / Business Wire / PR Newswire 的公司或主题 feed，及各公司 IR RSS）到其 `scan_urls`（Entity Catalog / detect 源）。
- 私有自家公司（如 Ant International 业绩）多经 GlobeNewswire 发布——这是它们无日历时的主要抓取面。
- 交付含一份**按实体筛好的 feed 清单**（需人工核对 feed 有效性）。

### C4. AlphaVantage 每日调用上限（省额度护栏）— `app/adapters/market.py` + ledger
- 现状：每次 anchor 扫描对 11 个 ticker 各调一次价格快照 × 多次/天 ≈ **66+ 次/天，已超免费 ~25/天**。
- 改动：为 AlphaVantage 调用增加**每日计数上限**，计数落在 **API Usage Ledger**（`DingTalkUsageLedger` / `app/cost_control.py`，已被 `critical_event_scan.py` 使用；按 `provider=alpha_vantage` 过滤当日记录计数，天然跨 anchor 的多次运行累计，RunLog 是单次 job 记录、不适合做跨运行累计上限）；超限则跳过 AlphaVantage、由免费的 `yfinance` 兜底价格。上限可配置（默认 20，留余量）。
- marketaux / GDELT 维持仅在 anchor 跑（不进 fast）。

### C5. 财报日历定点（Phase 2，仅美股上市竞对）
- 每日 1 次拉 AlphaVantage `EARNINGS_CALENDAR`（`horizon=3month`，1 次调用）。
- 匹配监控实体的 ticker（约 8 家美股：PAYO/DLO/SE/V/FISV/PYPL/CRM/MA），把"预计财报日"写入 Entity Catalog 的新字段 `Expected Earnings Date`。
- 报告日：这些实体在 fast 扫描中已被 IR/RSS 覆盖；额外可选：
  - 发"X 今日发财报，盯盘中"预告（低优先）。
  - 给该实体新事件的解读补"对比市场预期"上下文（若日历带 EPS 估计）。
- 私有公司无 ticker → 不进日历，靠 C3 的快讯 RSS 覆盖。

### C6. 解读质量（不改逻辑，确认保留）
- 财报解读需真实数字；`enrich_official_excerpts`（official extract + Firecrawl，`firecrawl_enabled` 门控）已抽取发布正文喂 LLM。保留现状即可。

## 5. 数据流（fast 模式）

```
launchd(9/12/15/18) → critical_event_scan --mode fast
  → 工作时段闸门（否则 no-op 退出）
  → collect_critical_signals(mode=fast)  # 仅 official IR + RSS
  → new_signal_rows(去重 vs 现有 News by URL)   # 高频不重复
  → enrich_official_excerpts(仅新 official 行, Firecrawl 事件绑定)
  → fresh_critical_rows(lookback 门控)
  → 若有新行: add_news_records → eventize_records
             → enrich_events_with_llm(仅 new_events, 解读)
             → send_event_alerts(推送)
     否则: no-op（fast_path=no_change）
```

## 6. 成本 / 额度分析

| 依赖 | 计费性质 | 是否随频率涨 | 护栏 |
| --- | --- | --- | --- |
| 官方 IR + 快讯 RSS | 免费 HTTP | 是（仅 HTTP，对 IR 站点礼貌，可加 ETag/Last-Modified 条件请求） | 每 3h，量可控 |
| OpenAI 解读 | 付费 token | 否（事件绑定） | 已有 monthly cap 预检 |
| Firecrawl 抽正文 | 月度额度 | 否（事件绑定，excerpt<800 才抽） | `firecrawl_enabled` + 事件绑定 |
| AlphaVantage | 免费 ~25/天 | 是（价格快照按 ticker×run） | **C4 每日上限**，仅 anchor |
| marketaux | 免费 100/天 | 是 | 仅 anchor |
| GDELT | 免费/限流 | 是 | 仅 anchor（fast 排除） |

结论：fast 提频不增计费消耗；AlphaVantage 由 C4 拉回免费档内。

## 7. 分期

- **Phase 1（本设计核心，最大收益+直接省额度）**：C1 双模 + C2 源过滤 + 工作时段每 3h 调度 + C3 快讯 RSS + C4 AlphaVantage 每日上限。
- **Phase 2**：C5 财报日历定点（竞对精调 + 预告 + 对比解读）。

两期各自独立可发布；Phase 1 即可解决私有与公有公司的时延主问题。

## 8. 调度（launchd）

- **fast**：工作时段每 3h。实现用脚本内工作时段闸门（launchd 触发在 9/12/15/18，或用一个 StartInterval + 闸门）；机器**休眠**（sleep，非关机）期间错过的触发点，launchd 会在设备唤醒后补跑一次。注意这与已发生过的 2026-07-08~10 断供事故不是同一场景——那次是**机器关机/未开机**，daemon 本身没有运行，launchd 无法补跑；本设计的补跑假设仅适用于"睡眠唤醒"，不覆盖"关机"，关机场景仍需依赖 `daily_health_check` 的滞后告警兜底。
- **anchor**：精简为 06 / 21（+ 视需要保留工作时段一两次全量）。避免与 AlphaVantage 上限冲突。
- 具体 plist 槽位在实现计划中确定；沿用现有 `com.franco.weekly-headlines.critical_event_scan` 命名族，新增 `...critical_event_scan_fast`。

## 9. 测试

- `collect_critical_signals(mode=fast)` 只调用 OfficialSourceAdapter，不触碰 GDELT/marketaux/AlphaVantage/yfinance（mock 断言）。
- 工作时段闸门：9–18 内运行、之外 no-op（注入固定 now）。
- RSS 解析：给 OfficialSourceAdapter 一段 newswire feed fixture，断言解析出 title/link/date。
- AlphaVantage 每日上限：达到上限后跳过并回退 yfinance（mock 计数）。
- 高频不重复告警：同一 URL 二次扫描不再进入 new_rows。
- Phase 2：EARNINGS_CALENDAR 解析 + 按 ticker 映射到实体 + 写 `Expected Earnings Date`。

## 10. 成功标准

- 工作时段关键事件（尤其 Earnings 类型）**中位检测时延 < 3h**，快讯覆盖的条目显著更快。
- AlphaVantage 日调用回落到免费额度内（≤ 上限）。
- 无月度 token 超支（monthly cap 未被触发为拒绝）。
- fast 扫描不产生重复告警。

## 11. 未决 / 依赖

- C3 需要人工核对各实体的**有效快讯 feed URL**（GlobeNewswire/Business Wire 的公司页 feed 格式）。
- C5 的 AlphaVantage EARNINGS_CALENDAR 覆盖以美股为主；非美股 ticker（WISE.L/ADYEN.AS）可能不在覆盖内，按"尽力而为"处理。
