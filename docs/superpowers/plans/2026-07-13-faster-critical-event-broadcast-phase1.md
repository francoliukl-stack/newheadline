# 更快的关键事件播报 · Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `critical_event_scan.py` 支持 `fast`/`anchor` 双模扫描，工作时段（GMT+8 9:00–18:00）每 3 小时用免费官方 IR/RSS 源做低时延扫描，anchor 精简为每天 2 次全量扫描，并给 AlphaVantage 加每日调用上限，从而把关键事件（尤其财报）的检测时延从最坏 ~4h 压到 ~3h 内，且不增加计费 API 用量。

**Architecture:** 在既有的 `collect_critical_signals()` 纯函数上加 `mode` 参数做源过滤（fast 只跑 `OfficialSourceAdapter`），复用已有的 `DingTalkUsageLedger`（`app/cost_control.py`）做 AlphaVantage 跨运行的每日计数与上限；`scripts/critical_event_scan.py` 的 `main()` 加 `--mode` 与工作时段闸门；`app/scheduler.py` 的 launchd plist 生成器加 `mode` 参数，产出两个独立 label 的 plist（anchor 沿用现有 label，fast 新增 `_fast` 后缀 label）。

**Tech Stack:** Python 3 / pydantic settings（`app/models.py`）/ DingTalk AI Table 作为存储 / launchd（macOS）/ unittest（现有测试风格，全部落在 `tests/test_v3_1_services.py` 的 `V31ServiceTests` 类里，与仓库现状一致，不新建测试文件）。

对应 spec：[`docs/superpowers/specs/2026-07-12-faster-critical-event-broadcast-design.md`](../specs/2026-07-12-faster-critical-event-broadcast-design.md)（本计划只覆盖 spec §7 的 **Phase 1**：C1 双模 + C2 源过滤 + C4 AlphaVantage 每日上限 + §8 调度；C5 财报日历是 Phase 2，不在本计划内）。

## Global Constraints

- 不引入新依赖包；只用仓库已有的 `httpx`/`pydantic`/`zoneinfo`/标准库。
- 所有新函数必须向后兼容：现有调用方（`collect_critical_signals(settings, catalog)` 无 `mode` 参数、`build_critical_scan_plist(root, python, hours)` 无 `mode` 参数）在不传新参数时行为与改动前完全一致——这是因为 `tests/test_v3_1_services.py` 里已有测试用旧签名调用它们，不能破坏。
- AlphaVantage 每日计数落在 API Usage Ledger（`DingTalkUsageLedger`），不用 RunLog；空/未提供 ledger 时视为不限流（保持 dry-run 等无副作用路径的行为不变）。
- `--dry-run` 路径必须保持零写入（不写 RunLog、不写 API Usage Ledger、不装 launchd plist）。
- launchd plist 的**安装/生效**（`launchctl bootstrap`）是有真实副作用、影响生产调度的操作；本计划里写代码和写测试都不触发它，最后是否执行 `install_v3_1_schedule.py --apply` 需要用户明确批准（见计划末尾"部署"一节）。
- 用中文写所有新增的用户可见文案、commit message 说明性文字、计划/测试里的注释（如果需要注释的话），沿用仓库现有的中英混排风格（字段名、日志 key 保持英文，符合现状）。

---

### Task 1: `collect_critical_signals` 按 mode 过滤源（C2）

**Files:**
- Modify: `scripts/critical_event_scan.py:45-115`（`collect_critical_signals` 函数）
- Test: `tests/test_v3_1_services.py`（在 `test_critical_scan_uses_alpha_vantage_when_enabled` 测试，约第 616 行，后面加新测试）

**Interfaces:**
- Consumes: 无新依赖，沿用文件已有的 `OfficialSourceAdapter`/`GdeltAdapter`/`MarketauxAdapter`/`YFinanceAdapter`/`AlphaVantageAdapter`/`EntityRecord`/`AdapterRequest`/`SourceSignal`。
- Produces: `collect_critical_signals(settings, catalog, mode: str = "anchor") -> Tuple[List[SourceSignal], List[str], int, int]`——`mode` 是新增的第三个位置/关键字参数，`"fast"` 时只调用 `OfficialSourceAdapter`（跳过 yfinance/AlphaVantage/GDELT/marketaux），`"anchor"`（默认）行为与改动前完全一致。后续 Task 2 会在这个函数上继续加参数。

- [ ] **Step 1: 写失败测试**

在 `tests/test_v3_1_services.py` 里 `test_critical_scan_uses_alpha_vantage_when_enabled` 测试后面加：

```python
    @patch("scripts.critical_event_scan.MarketauxAdapter")
    @patch("scripts.critical_event_scan.GdeltAdapter")
    @patch("scripts.critical_event_scan.AlphaVantageAdapter")
    @patch("scripts.critical_event_scan.YFinanceAdapter")
    @patch("scripts.critical_event_scan.OfficialSourceAdapter")
    def test_fast_mode_only_calls_official_adapter(
        self,
        official_adapter: Mock,
        yfinance_adapter: Mock,
        alpha_adapter: Mock,
        gdelt_adapter: Mock,
        marketaux_adapter: Mock,
    ):
        settings = AppSettings()
        settings.event_intelligence.official_enabled = True
        settings.event_intelligence.gdelt_enabled = True
        settings.event_intelligence.marketaux_enabled = True
        settings.event_intelligence.yfinance_enabled = True
        settings.event_intelligence.alpha_vantage_enabled = True
        settings.event_intelligence.alpha_vantage_api_key = "key"
        official_adapter.return_value.collect.return_value = []
        catalog = [
            EntityRecord(
                "payoneer", "Payoneer", [], ["WorldFirst"],
                ticker="PAYO", watch_tier="critical",
                scan_urls=["https://payoneer.com/ir/rss"],
            )
        ]

        signals, errors, attempts, successes = collect_critical_signals(settings, catalog, mode="fast")

        official_adapter.return_value.collect.assert_called_once()
        yfinance_adapter.return_value.snapshot.assert_not_called()
        alpha_adapter.return_value.snapshot.assert_not_called()
        gdelt_adapter.return_value.collect.assert_not_called()
        marketaux_adapter.return_value.collect.assert_not_called()
        self.assertEqual(errors, [])
        self.assertEqual(signals, [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_fast_mode_only_calls_official_adapter -v`
Expected: FAIL，报 `TypeError: collect_critical_signals() got an unexpected keyword argument 'mode'`

- [ ] **Step 3: 实现 mode 过滤**

把 `scripts/critical_event_scan.py` 里的 `collect_critical_signals` 函数签名和函数体改成：

```python
def collect_critical_signals(settings: AppSettings, catalog: Sequence[EntityRecord], mode: str = "anchor") -> Tuple[List[SourceSignal], List[str], int, int]:
    watched = [entity for entity in catalog if entity.active and entity.watch_tier in {"critical", "high"}]
    signals: List[SourceSignal] = []
    errors: List[str] = []
    attempts = successes = 0
    official = OfficialSourceAdapter(min(20, settings.search_provider.request_timeout_seconds))
    gdelt = GdeltAdapter(settings.search_provider.request_timeout_seconds)
    marketaux = MarketauxAdapter(settings.event_intelligence.marketaux_api_key)
    yfinance = YFinanceAdapter()
    alpha_vantage = AlphaVantageAdapter(settings.event_intelligence.alpha_vantage_api_key)

    for entity in watched:
        if settings.event_intelligence.official_enabled and entity.scan_urls:
            attempts += 1
            try:
                signals.extend(official.collect(AdapterRequest(entity_id=entity.entity_id, query=entity.canonical_name, urls=entity.scan_urls, limit=8)))
                successes += 1
            except Exception as exc:
                errors.append(f"official:{entity.entity_id}:{exc}")
        if mode == "fast":
            continue
        if settings.event_intelligence.yfinance_enabled and entity.ticker:
            attempts += 1
            try:
                for market in yfinance.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        direction = "rise" if market.change_pct >= 0 else "fall"
                        url = f"https://finance.yahoo.com/quote/{entity.ticker}"
                        signals.append(SourceSignal("yfinance", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "finance.yahoo.com", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id}))
                successes += 1
            except Exception as exc:
                errors.append(f"yfinance:{entity.entity_id}:{exc}")
        if settings.event_intelligence.alpha_vantage_enabled and entity.ticker:
            attempts += 1
            try:
                for market in alpha_vantage.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        direction = "rise" if market.change_pct >= 0 else "fall"
                        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={entity.ticker}"
                        signals.append(SourceSignal("alpha_vantage", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "alphavantage.co", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id, "ticker": entity.ticker}))
                successes += 1
            except Exception as exc:
                errors.append(f"alpha_vantage:{entity.entity_id}:{exc}")

    if mode == "fast":
        gdelt_batches = []
    else:
        gdelt_entities = [entity for entity in watched if entity.watch_tier == "critical"]
        gdelt_batches = [gdelt_entities] if gdelt_entities else []
    for index, batch in enumerate(gdelt_batches):
        names = " OR ".join(f'"{entity.canonical_name}"' for entity in batch)
        query = f"({names}) (earnings OR launch OR partnership OR acquisition OR regulation OR outage)"
        if settings.event_intelligence.gdelt_enabled:
            attempts += 1
            try:
                signals.extend(gdelt.collect(AdapterRequest(query=query, limit=40)))
                successes += 1
            except Exception as exc:
                errors.append(f"gdelt:batch-{index}:{exc}")
        if settings.event_intelligence.marketaux_enabled:
            attempts += 1
            try:
                signals.extend(marketaux.collect(AdapterRequest(query=names, limit=20)))
                successes += 1
            except Exception as exc:
                errors.append(f"marketaux:batch-{index}:{exc}")
        if index < len(gdelt_batches) - 1 and settings.event_intelligence.gdelt_enabled:
            time.sleep(6)

    if attempts and not successes:
        raise RuntimeError("all configured critical-scan adapters failed: " + "; ".join(errors))
    filtered: Dict[str, SourceSignal] = {}
    for signal in signals:
        url = normalize_url(signal.source_url)
        if url and is_critical_signal(signal, catalog, lookback_days=settings.event_intelligence.critical_scan_lookback_days):
            filtered.setdefault(url, signal)
    return list(filtered.values()), errors, attempts, successes
```

（唯一的实质改动：加了 `mode: str = "anchor"` 参数，以及 `if mode == "fast": continue` / `if mode == "fast": gdelt_batches = []` 两处过滤；其余逻辑逐字不变。）

- [ ] **Step 4: 跑测试确认通过，并跑一遍现有相关测试确认没有回归**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -k "critical_scan or fast_mode or alpha_vantage" -v`
Expected: 全部 PASS，包括新加的 `test_fast_mode_only_calls_official_adapter` 和已有的 `test_critical_scan_uses_alpha_vantage_when_enabled`。

- [ ] **Step 5: Commit**

```bash
git add scripts/critical_event_scan.py tests/test_v3_1_services.py
git commit -m "$(cat <<'EOF'
Add mode-based source filtering to collect_critical_signals

fast mode only queries OfficialSourceAdapter (free IR/RSS); anchor mode
(default) is unchanged and still queries the full source set.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

### Task 2: AlphaVantage 每日调用上限（C4）

**Files:**
- Modify: `app/models.py:76-96`（`EventIntelligenceSettings`，加一个字段）
- Modify: `app/cost_control.py:92-101`（`_parse_timestamp` 之后加一个新函数）
- Modify: `scripts/critical_event_scan.py`（Task 1 改完之后的 `collect_critical_signals`，加 `usage_ledger`/`run_id` 参数，且 AlphaVantage 分支加上限检查与 ledger 写入）
- Test: `tests/test_v3_1_services.py`

**Interfaces:**
- Consumes: Task 1 产出的 `collect_critical_signals(settings, catalog, mode="anchor")`；`app.cost_control.MemoryUsageLedger`/`DingTalkUsageLedger`（已存在，实现 `records() -> List[Dict[str,Any]]` 和 `append(fields) -> None`）；`app.cost_control.usage_fields(...)`、`CostEstimate`（已存在）。
- Produces:
  - `app.cost_control.count_provider_calls_today(ledger, provider: str, timezone_name: str, now: datetime | None = None) -> int`——供 Task 2 内部使用，也可单独单测。
  - `EventIntelligenceSettings.alpha_vantage_daily_call_limit: int`（默认 20）。
  - `collect_critical_signals(settings, catalog, mode="anchor", usage_ledger: Any = None, run_id: str = "") -> Tuple[...]`（4 元组返回值不变，新增两个可选关键字参数，供 Task 3 在 `main()` 里传入真实的 `DingTalkUsageLedger` 与 `run_id`）。

- [ ] **Step 1: 写失败测试（`count_provider_calls_today`）**

先确认测试文件顶部有 `from zoneinfo import ZoneInfo`（现在没有，加进 `tests/test_v3_1_services.py` 的 import 区）：

```python
from zoneinfo import ZoneInfo
```

并把 `from app.cost_control import BudgetController, MemoryUsageLedger, calculate_cost, estimate_cost` 改成：

```python
from app.cost_control import BudgetController, MemoryUsageLedger, calculate_cost, count_provider_calls_today, estimate_cost
```

在 `test_budget_preflight_blocks_monthly_cap`（约第 424 行）附近加：

```python
    def test_count_provider_calls_today_filters_by_provider_and_local_date(self):
        now = datetime(2026, 7, 12, 15, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))
        ledger = MemoryUsageLedger([
            {"Provider": "alpha_vantage", "Started At": "2026-07-12T03:00:00+00:00"},  # KL 11:00 07-12，算今天
            {"Provider": "alpha_vantage", "Started At": "2026-07-11T10:00:00+00:00"},  # KL 18:00 07-11，算昨天
            {"Provider": "openai", "Started At": "2026-07-12T05:00:00+00:00"},  # provider 不同
        ])

        count = count_provider_calls_today(ledger, "alpha_vantage", "Asia/Kuala_Lumpur", now=now)

        self.assertEqual(count, 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_count_provider_calls_today_filters_by_provider_and_local_date -v`
Expected: FAIL，`ImportError: cannot import name 'count_provider_calls_today'`

- [ ] **Step 3: 实现 `count_provider_calls_today`**

在 `app/cost_control.py` 的 `_parse_timestamp` 函数（第 93-101 行）之后加：

```python
def count_provider_calls_today(ledger: UsageLedger, provider: str, timezone_name: str, now: datetime = None) -> int:
    current = now or datetime.now(ZoneInfo(timezone_name))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(timezone_name))
    current = current.astimezone(ZoneInfo(timezone_name))
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [row for row in ledger.records() if str(row.get("Provider") or "") == provider]
    return sum(1 for row in rows if _parse_timestamp(row.get("Started At")).astimezone(current.tzinfo) >= day_start)
```

（跟 `BudgetController.preflight` 里 `day_start`/`_parse_timestamp` 的算法完全一致，复用已有私有函数，不重复造轮子。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_count_provider_calls_today_filters_by_provider_and_local_date -v`
Expected: PASS

- [ ] **Step 5: 写失败测试（AlphaVantage 上限生效 + 用量落 ledger）**

加两个测试：

```python
    @patch("scripts.critical_event_scan.AlphaVantageAdapter")
    def test_alpha_vantage_daily_cap_skips_call_when_reached(self, alpha_adapter: Mock):
        settings = AppSettings()
        settings.event_intelligence.official_enabled = False
        settings.event_intelligence.gdelt_enabled = False
        settings.event_intelligence.marketaux_enabled = False
        settings.event_intelligence.yfinance_enabled = False
        settings.event_intelligence.alpha_vantage_enabled = True
        settings.event_intelligence.alpha_vantage_api_key = "key"
        settings.event_intelligence.alpha_vantage_daily_call_limit = 1
        ledger = MemoryUsageLedger([
            {"Provider": "alpha_vantage", "Started At": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        ])
        catalog = [EntityRecord("payoneer", "Payoneer", [], ["WorldFirst"], ticker="PAYO", watch_tier="critical")]

        signals, errors, attempts, successes = collect_critical_signals(settings, catalog, mode="anchor", usage_ledger=ledger, run_id="run-1")

        alpha_adapter.return_value.snapshot.assert_not_called()
        self.assertEqual(signals, [])
        self.assertTrue(any("daily call limit" in error for error in errors))

    def test_alpha_vantage_call_appends_usage_ledger_row(self):
        settings = AppSettings()
        settings.event_intelligence.official_enabled = False
        settings.event_intelligence.gdelt_enabled = False
        settings.event_intelligence.marketaux_enabled = False
        settings.event_intelligence.yfinance_enabled = False
        settings.event_intelligence.alpha_vantage_enabled = True
        settings.event_intelligence.alpha_vantage_api_key = "key"
        ledger = MemoryUsageLedger()
        catalog = [EntityRecord("payoneer", "Payoneer", [], ["WorldFirst"], ticker="PAYO", watch_tier="critical")]

        with patch("scripts.critical_event_scan.AlphaVantageAdapter") as alpha_adapter:
            alpha_adapter.return_value.snapshot.return_value = [SimpleNamespace(change_pct=5.2, observed_at="2026-07-11T00:00:00Z")]
            collect_critical_signals(settings, catalog, mode="anchor", usage_ledger=ledger, run_id="run-9")

        rows = ledger.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Provider"], "alpha_vantage")
        self.assertEqual(rows[0]["Run ID"], "run-9")
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -k "alpha_vantage_daily_cap or alpha_vantage_call_appends" -v`
Expected: FAIL，`TypeError: collect_critical_signals() got an unexpected keyword argument 'usage_ledger'`

- [ ] **Step 7: 加配置字段**

在 `app/models.py` 的 `EventIntelligenceSettings`（第 93 行 `alpha_vantage_enabled: bool = False` 附近）加：

```python
    alpha_vantage_daily_call_limit: int = Field(default=20, ge=0)
```

放在 `alpha_vantage_api_key: str = ""` 那一行之后即可。

- [ ] **Step 8: 实现上限检查 + ledger 写入**

在 `scripts/critical_event_scan.py` 顶部的 import 区，把：

```python
from app.cost_control import BudgetController, DingTalkUsageLedger  # noqa: E402
```

改成：

```python
from app.cost_control import BudgetController, CostEstimate, DingTalkUsageLedger, UsageLedger, count_provider_calls_today, usage_fields  # noqa: E402
```

再把 `from typing import Any, Dict, List, Sequence, Tuple` 改成：

```python
from typing import Any, Dict, List, Optional, Sequence, Tuple
```

把 `collect_critical_signals` 的签名和 AlphaVantage 分支改成（其余部分保持 Task 1 完成后的样子不变）：

```python
def collect_critical_signals(
    settings: AppSettings,
    catalog: Sequence[EntityRecord],
    mode: str = "anchor",
    usage_ledger: Optional[UsageLedger] = None,
    run_id: str = "",
) -> Tuple[List[SourceSignal], List[str], int, int]:
    watched = [entity for entity in catalog if entity.active and entity.watch_tier in {"critical", "high"}]
    signals: List[SourceSignal] = []
    errors: List[str] = []
    attempts = successes = 0
    official = OfficialSourceAdapter(min(20, settings.search_provider.request_timeout_seconds))
    gdelt = GdeltAdapter(settings.search_provider.request_timeout_seconds)
    marketaux = MarketauxAdapter(settings.event_intelligence.marketaux_api_key)
    yfinance = YFinanceAdapter()
    alpha_vantage = AlphaVantageAdapter(settings.event_intelligence.alpha_vantage_api_key)
    alpha_vantage_calls_today = (
        count_provider_calls_today(usage_ledger, "alpha_vantage", settings.system.timezone)
        if usage_ledger is not None
        else 0
    )
    alpha_vantage_daily_limit = settings.event_intelligence.alpha_vantage_daily_call_limit

    for entity in watched:
        if settings.event_intelligence.official_enabled and entity.scan_urls:
            attempts += 1
            try:
                signals.extend(official.collect(AdapterRequest(entity_id=entity.entity_id, query=entity.canonical_name, urls=entity.scan_urls, limit=8)))
                successes += 1
            except Exception as exc:
                errors.append(f"official:{entity.entity_id}:{exc}")
        if mode == "fast":
            continue
        if settings.event_intelligence.yfinance_enabled and entity.ticker:
            attempts += 1
            try:
                for market in yfinance.snapshot(entity.ticker):
                    if abs(market.change_pct) >= 5:
                        direction = "rise" if market.change_pct >= 0 else "fall"
                        url = f"https://finance.yahoo.com/quote/{entity.ticker}"
                        signals.append(SourceSignal("yfinance", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "finance.yahoo.com", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id}))
                successes += 1
            except Exception as exc:
                errors.append(f"yfinance:{entity.entity_id}:{exc}")
        if settings.event_intelligence.alpha_vantage_enabled and entity.ticker:
            if alpha_vantage_calls_today >= alpha_vantage_daily_limit:
                errors.append(f"alpha_vantage:{entity.entity_id}:daily call limit {alpha_vantage_daily_limit} reached, skipped")
            else:
                attempts += 1
                try:
                    for market in alpha_vantage.snapshot(entity.ticker):
                        if abs(market.change_pct) >= 5:
                            direction = "rise" if market.change_pct >= 0 else "fall"
                            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={entity.ticker}"
                            signals.append(SourceSignal("alpha_vantage", f"{entity.canonical_name} shares {direction} {market.change_pct:+.1f}% in one session", url, "alphavantage.co", market.observed_at, query=entity.ticker, metadata={"entity_id": entity.entity_id, "ticker": entity.ticker}))
                    successes += 1
                    alpha_vantage_calls_today += 1
                    if usage_ledger is not None:
                        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        usage_ledger.append(usage_fields(
                            run_id=run_id, event_id="", provider="alpha_vantage", operation="market_snapshot",
                            model=entity.ticker, pricing_version="n/a", estimate=CostEstimate(0, 0, 0.0),
                            status="completed", started_at=started, finished_at=started,
                        ))
                except Exception as exc:
                    errors.append(f"alpha_vantage:{entity.entity_id}:{exc}")

    if mode == "fast":
        gdelt_batches = []
    else:
        gdelt_entities = [entity for entity in watched if entity.watch_tier == "critical"]
        gdelt_batches = [gdelt_entities] if gdelt_entities else []
    for index, batch in enumerate(gdelt_batches):
        names = " OR ".join(f'"{entity.canonical_name}"' for entity in batch)
        query = f"({names}) (earnings OR launch OR partnership OR acquisition OR regulation OR outage)"
        if settings.event_intelligence.gdelt_enabled:
            attempts += 1
            try:
                signals.extend(gdelt.collect(AdapterRequest(query=query, limit=40)))
                successes += 1
            except Exception as exc:
                errors.append(f"gdelt:batch-{index}:{exc}")
        if settings.event_intelligence.marketaux_enabled:
            attempts += 1
            try:
                signals.extend(marketaux.collect(AdapterRequest(query=names, limit=20)))
                successes += 1
            except Exception as exc:
                errors.append(f"marketaux:batch-{index}:{exc}")
        if index < len(gdelt_batches) - 1 and settings.event_intelligence.gdelt_enabled:
            time.sleep(6)

    if attempts and not successes:
        raise RuntimeError("all configured critical-scan adapters failed: " + "; ".join(errors))
    filtered: Dict[str, SourceSignal] = {}
    for signal in signals:
        url = normalize_url(signal.source_url)
        if url and is_critical_signal(signal, catalog, lookback_days=settings.event_intelligence.critical_scan_lookback_days):
            filtered.setdefault(url, signal)
    return list(filtered.values()), errors, attempts, successes
```

- [ ] **Step 9: 跑测试确认通过，并跑全量相关测试确认无回归**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -v`
Expected: 全部 PASS（含 `test_critical_scan_uses_alpha_vantage_when_enabled`——它没传 `usage_ledger`，默认 `None`，上限检查被跳过，行为不变）。

- [ ] **Step 10: Commit**

```bash
git add app/models.py app/cost_control.py scripts/critical_event_scan.py tests/test_v3_1_services.py
git commit -m "$(cat <<'EOF'
Add AlphaVantage daily call cap backed by the API Usage Ledger

count_provider_calls_today() reads DingTalkUsageLedger records to track
cross-run daily AlphaVantage usage; collect_critical_signals() skips the
call and records the skip reason once alpha_vantage_daily_call_limit
(default 20) is reached, falling back to the already-independent
yfinance branch for price signals. usage_ledger defaults to None so
existing callers (and dry-run) are unaffected.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

### Task 3: `--mode` 参数、工作时段闸门与 `main()` 接线（C1）

**Files:**
- Modify: `scripts/critical_event_scan.py:244-341`（`main()` 函数），并在其上方加一个新的纯函数 `is_fast_scan_window`
- Test: `tests/test_v3_1_services.py`

**Interfaces:**
- Consumes: Task 1+2 产出的 `collect_critical_signals(settings, catalog, mode=..., usage_ledger=..., run_id=...)`；已有的 `RunLogStore`/`AuditTrailWriter`/`DingTalkUsageLedger`。
- Produces: `is_fast_scan_window(now: datetime, timezone_name: str) -> bool`（纯函数，可单测）；`critical_event_scan.py --mode {fast,anchor}` CLI 参数（默认 `anchor`，保持向后兼容）。

**说明：** 仓库现有测试从不直接调用脚本的 `main()`（它做真实 I/O：读设置、读写 DingTalk、写 RunLog），只测里面的纯函数——这个任务延续同样的做法：`is_fast_scan_window` 单测覆盖，`main()` 的接线改动用 `--dry-run` 手工跑一遍验证（Step 5），不写伪造的 `main()` 单测。

- [ ] **Step 1: 写失败测试（`is_fast_scan_window`）**

把 `from scripts.critical_event_scan import append_created_news_records, collect_critical_signals, enrich_official_excerpts, fresh_critical_rows, recent_news_records` 改成：

```python
from scripts.critical_event_scan import append_created_news_records, collect_critical_signals, enrich_official_excerpts, fresh_critical_rows, is_fast_scan_window, recent_news_records
```

在 `test_fast_mode_only_calls_official_adapter` 测试后面加：

```python
    def test_fast_scan_window_is_nine_to_eighteen_local(self):
        tz = ZoneInfo("Asia/Kuala_Lumpur")
        self.assertTrue(is_fast_scan_window(datetime(2026, 7, 13, 9, 0, tzinfo=tz), "Asia/Kuala_Lumpur"))
        self.assertTrue(is_fast_scan_window(datetime(2026, 7, 13, 18, 0, tzinfo=tz), "Asia/Kuala_Lumpur"))
        self.assertFalse(is_fast_scan_window(datetime(2026, 7, 13, 8, 59, tzinfo=tz), "Asia/Kuala_Lumpur"))
        self.assertFalse(is_fast_scan_window(datetime(2026, 7, 13, 21, 0, tzinfo=tz), "Asia/Kuala_Lumpur"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_fast_scan_window_is_nine_to_eighteen_local -v`
Expected: FAIL，`ImportError: cannot import name 'is_fast_scan_window'`

- [ ] **Step 3: 实现 `is_fast_scan_window` 并接线 `main()`**

在 `scripts/critical_event_scan.py` 的 `collect_critical_signals` 函数定义之前加：

```python
def is_fast_scan_window(now: datetime, timezone_name: str) -> bool:
    tz = ZoneInfo(timezone_name)
    current = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    return 9 <= current.hour <= 18
```

把 `main()`（第 244-341 行）改成：

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="Scan critical sources and optionally preview without writes.")
    parser.add_argument("--dry-run", action="store_true", help="Collect and eventize live signals without writes, alerts or paid model calls.")
    parser.add_argument("--mode", choices=["fast", "anchor"], default="anchor", help="fast: 9-18 GMT+8 only, official IR/RSS sources; anchor: full source set on the sparse schedule.")
    args = parser.parse_args()

    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    if not settings.event_intelligence.critical_scan_enabled and not args.dry_run:
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        runs.finish(run_id, "success", message="critical scan disabled")
        print("critical_event_scan skipped: disabled")
        return 0

    if args.mode == "fast" and not args.dry_run and not is_fast_scan_window(datetime.now(ZoneInfo(settings.system.timezone)), settings.system.timezone):
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        runs.finish(run_id, "success", message="fast mode outside 9-18 GMT+8 work hours")
        print("critical_event_scan skipped: fast mode outside work hours")
        return 0

    tables = tables_from_settings(settings)
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    existing_news = list_records(settings.dingtalk, settings.dingtalk_ai_table)

    runs = None
    run_id = ""
    usage_ledger = None
    if not args.dry_run:
        runs = RunLogStore(DATA / "settings.sqlite3")
        run_id = runs.start("critical_event_scan", provider="event_adapters")
        usage_ledger = DingTalkUsageLedger(settings, tables.api_usage)

    signals, errors, attempts, successes = collect_critical_signals(settings, catalog, mode=args.mode, usage_ledger=usage_ledger, run_id=run_id)
    new_rows = new_signal_rows(signals, existing_news)
    errors.extend(enrich_official_excerpts(new_rows, settings))
    pre_freshness_count = len(new_rows)
    new_rows = fresh_critical_rows(
        new_rows,
        settings.event_intelligence.critical_scan_lookback_days,
        settings.system.timezone,
    )
    freshness_excluded = pre_freshness_count - len(new_rows)

    if args.dry_run:
        preview, preview_ids = preview_records(new_rows)
        recent_news = recent_news_records(existing_news, settings.event_intelligence.critical_scan_lookback_days, settings.system.timezone)
        events = eventize_records(recent_news + preview, catalog, settings)
        candidate_events = [event for event in events if any(source.news_record_id in preview_ids for source in event.sources)]
        print(json.dumps({
            "mode": "dry-run",
            "scan_mode": args.mode,
            "adapter_attempts": attempts,
            "adapter_successes": successes,
            "adapter_errors": errors,
            "critical_signals": len(signals),
            "new_news_candidates": len(new_rows),
            "freshness_excluded": freshness_excluded,
            "event_candidates": [{
                "event_id": event.event_id,
                "title": event.title,
                "event_type": event.event_type,
                "business_lines": event.business_lines,
                "priority_candidate": event.priority_candidate,
                "source_urls": [source.url for source in event.sources],
            } for event in candidate_events],
        }, ensure_ascii=False, indent=2))
        return 0

    audit = AuditTrailWriter(settings, store, runs)
    try:
        new_record_ids: set[str] = set()
        if new_rows:
            result = add_news_records(settings.dingtalk, settings.dingtalk_ai_table, new_rows)
            if result.status != "sent":
                raise RuntimeError(result.message)
            new_record_ids.update(result.record_ids)
            operator = settings.dingtalk_ai_table.operator_user_id or settings.dingtalk_ai_table.operator_id
            normalized_rows = [
                normalize_news_record(row, settings.dingtalk_ai_table.field_mapping, operator)
                for row in new_rows
            ]
            existing_news = append_created_news_records(existing_news, normalized_rows, result.record_ids)
        else:
            message = f"signals={len(signals)}; new_news=0; events=0; new_events=0; alerts=0; fast_path=no_change"
            metadata = {"adapter_attempts": attempts, "adapter_successes": successes, "adapter_errors": errors, "freshness_excluded": freshness_excluded, "api_optimization": "skip_event_tables_when_no_new_news"}
            runs.finish(run_id, "success", result_count=0, message=message, metadata=metadata)
            audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="success", result_count=0, output_summary=message, metadata=metadata)
            print(f"critical_event_scan success: {message}")
            return 0
        news = recent_news_records(existing_news, settings.event_intelligence.critical_scan_lookback_days, settings.system.timezone)
        events = eventize_records(news, catalog, settings)
        new_events = [event for event in events if any(source.news_record_id in new_record_ids for source in event.sources)]
        if settings.openai_service.enabled:
            service = LLMService(settings.openai_service, BudgetController(settings.openai_service, usage_ledger, settings.system.timezone), usage_ledger, audit)
            new_events = enrich_events_with_llm(new_events, service, settings, run_id)
        count = persist_event_candidates(settings, tables, new_events)
        alerts = send_event_alerts(settings, tables, new_events)
        message = f"signals={len(signals)}; new_news={len(new_rows)}; events={count}; new_events={len(new_events)}; alerts={alerts}"
        metadata = {"adapter_attempts": attempts, "adapter_successes": successes, "adapter_errors": errors, "freshness_excluded": freshness_excluded}
        runs.finish(run_id, "success", result_count=count, message=message, metadata=metadata)
        audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="success", result_count=count, output_summary=message, metadata=metadata)
        print(f"critical_event_scan success: {message}")
        return 0
    except Exception as exc:
        runs.finish(run_id, "failed", message="critical scan failed", error=str(exc), metadata={"adapter_errors": errors})
        audit.record(run_id=run_id, workflow="critical_event_scan", stage_code="CRITICAL.complete", stage_name="Complete critical event scan", status="failed", error=str(exc), metadata={"adapter_errors": errors})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
```

跟改动前相比的关键差异：
1. 新增 `--mode` 参数与 fast 模式工作时段闸门（非 dry-run 时才生效，dry-run 允许随时预览）。
2. `runs`/`run_id`/`usage_ledger` 的创建从"仅在真正写库前"提前到"collect 之前"，这样 `usage_ledger` 才能传给 `collect_critical_signals` 记录 AlphaVantage 用量；dry-run 分支永远走不到这段代码（在它之前就 `return 0` 了），所以 dry-run 仍然零写入。
3. `if settings.openai_service.enabled:` 分支里不再重新 `DingTalkUsageLedger(settings, tables.api_usage)`，直接复用上面已经创建好的 `usage_ledger`（同一张表，没必要建两个实例）。
4. dry-run 的 JSON 输出多了一个 `"scan_mode"` 字段（不影响原有 `"mode": "dry-run"` 字段，没有测试断言这段 JSON，不存在回归风险——已用 grep 确认过仓库里没有测试或脚本依赖这段 JSON 的具体形状）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 手工验证 `main()` 接线（dry-run，无副作用）**

```bash
.venv/bin/python scripts/critical_event_scan.py --dry-run --mode fast
.venv/bin/python scripts/critical_event_scan.py --dry-run --mode anchor
.venv/bin/python scripts/critical_event_scan.py --dry-run
```

Expected: 三条命令都能正常退出（返回码 0），输出 JSON 里能看到 `"scan_mode"` 分别是 `"fast"`/`"anchor"`/`"anchor"`（第三条不传 `--mode`，验证默认值）。**这一步只读不写**（`--dry-run` 保证），可以直接对生产 DingTalk 表跑，不需要额外确认。

- [ ] **Step 6: Commit**

```bash
git add scripts/critical_event_scan.py tests/test_v3_1_services.py
git commit -m "$(cat <<'EOF'
Add --mode flag and fast-mode work-hours gate to critical_event_scan

fast mode only runs outside 9-18 GMT+8 as a no-op (RunLog-logged);
main() now builds the RunLogStore/DingTalkUsageLedger before collecting
signals so the AlphaVantage daily cap can be tracked, while dry-run
stays a read-only path.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

### Task 4: launchd 双调度 plist 生成（§8）

**Files:**
- Modify: `app/scheduler.py:27,74-105`
- Modify: `app/models.py:82`（`critical_scan_hours` 默认值改为 `[6, 21]`）以及新增 `critical_scan_fast_hours`
- Test: `tests/test_v3_1_services.py`

**Interfaces:**
- Consumes: 无新依赖。
- Produces: `build_critical_scan_plist(project_root, python_path, hours, mode: str = "anchor") -> bytes`；`install_critical_scan(project_root, python_path, hours, enabled, mode: str = "anchor", dry_run: bool = False) -> str`；`EventIntelligenceSettings.critical_scan_fast_hours: List[int]`（默认 `[9, 12, 15, 18]`）。`mode` 默认 `"anchor"`，label 与旧代码完全一致，保证 `test_critical_launchd_plist_has_six_intervals` 不用改就能继续过。

- [ ] **Step 1: 写失败测试**

在 `tests/test_v3_1_services.py` 顶部加 `import plistlib`（跟 `import json`/`import tempfile` 放一起）。

在 `test_critical_launchd_plist_has_six_intervals` 测试后面加：

```python
    def test_critical_launchd_plist_fast_mode_uses_fast_label_and_mode_arg(self):
        payload = plistlib.loads(build_critical_scan_plist(Path("/tmp/project"), "/tmp/python", [9, 12, 15, 18], mode="fast"))
        self.assertEqual(payload["Label"], "com.franco.weekly-headlines.critical_event_scan_fast")
        self.assertIn("--mode", payload["ProgramArguments"])
        self.assertIn("fast", payload["ProgramArguments"])
        self.assertEqual(len(payload["StartCalendarInterval"]), 4)

    def test_critical_launchd_plist_anchor_mode_keeps_existing_label(self):
        payload = plistlib.loads(build_critical_scan_plist(Path("/tmp/project"), "/tmp/python", [6, 21]))
        self.assertEqual(payload["Label"], "com.franco.weekly-headlines.critical_event_scan")
        self.assertIn("--mode", payload["ProgramArguments"])
        self.assertIn("anchor", payload["ProgramArguments"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -k "critical_launchd_plist" -v`
Expected: `test_critical_launchd_plist_fast_mode_uses_fast_label_and_mode_arg` 和 `test_critical_launchd_plist_anchor_mode_keeps_existing_label` FAIL（`TypeError: build_critical_scan_plist() got an unexpected keyword argument 'mode'`），`test_critical_launchd_plist_has_six_intervals` 仍然 PASS。

- [ ] **Step 3: 实现 mode 参数**

把 `app/scheduler.py` 第 27 行的：

```python
CRITICAL_SCAN_LABEL = "com.franco.weekly-headlines.critical_event_scan"
```

改成：

```python
CRITICAL_SCAN_LABEL = "com.franco.weekly-headlines.critical_event_scan"
CRITICAL_SCAN_FAST_LABEL = "com.franco.weekly-headlines.critical_event_scan_fast"


def _critical_scan_label(mode: str) -> str:
    return CRITICAL_SCAN_LABEL if mode == "anchor" else CRITICAL_SCAN_FAST_LABEL
```

把第 74-105 行的 `build_critical_scan_plist`/`install_critical_scan` 改成：

```python
def build_critical_scan_plist(project_root: Path, python_path: str, hours: list[int], mode: str = "anchor") -> bytes:
    script_path = project_root / "scripts" / "critical_event_scan.py"
    label = _critical_scan_label(mode)
    payload = {
        "Label": label,
        "ProgramArguments": [python_path, str(script_path), "--mode", mode],
        "StartCalendarInterval": [{"Hour": hour, "Minute": 0} for hour in hours],
        "RunAtLoad": False,
        "StandardOutPath": str(project_root / "data" / f"{label}.out.log"),
        "StandardErrorPath": str(project_root / "data" / f"{label}.err.log"),
        "WorkingDirectory": str(project_root),
    }
    return plistlib.dumps(payload, sort_keys=False)


def install_critical_scan(project_root: Path, python_path: str, hours: list[int], enabled: bool, mode: str = "anchor", dry_run: bool = False) -> str:
    label = _critical_scan_label(mode)
    path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_bytes = build_critical_scan_plist(project_root, python_path, hours, mode)
    if dry_run:
        return plist_bytes.decode("utf-8") if enabled else f"disabled; would remove {path}"
    domain = f"gui/{subprocess.check_output(['id', '-u'], text=True).strip()}"
    if not enabled:
        if path.exists():
            subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True, text=True)
            path.unlink()
        return f"disabled; removed {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plist_bytes)
    subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True, text=True)
    completed = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return f"installed {path}"
```

在 `app/models.py` 第 82 行，把：

```python
    critical_scan_hours: List[int] = Field(default_factory=lambda: [1, 5, 9, 13, 17, 21])
```

改成：

```python
    critical_scan_hours: List[int] = Field(default_factory=lambda: [6, 21])
    critical_scan_fast_hours: List[int] = Field(default_factory=lambda: [9, 12, 15, 18])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py -k "critical_launchd_plist" -v`
Expected: 三个测试全 PASS。

- [ ] **Step 5: 更新两个安装脚本，装两条 plist**

把 `scripts/install_v3_1_schedule.py` 最后一行：

```python
print(install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_hours, settings.event_intelligence.critical_scan_enabled, dry_run=not args.apply))
```

改成：

```python
print(install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_hours, settings.event_intelligence.critical_scan_enabled, mode="anchor", dry_run=not args.apply))
print(install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_fast_hours, settings.event_intelligence.critical_scan_enabled, mode="fast", dry_run=not args.apply))
```

把 `scripts/cutover_v3_1.py` 第 75-76 行：

```python
    message = install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_hours, settings.event_intelligence.critical_scan_enabled, dry_run=False)
    print(json.dumps({"mode": "rollback" if args.rollback else "apply", "target": target, "schedule": message}, indent=2))
```

改成：

```python
    anchor_message = install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_hours, settings.event_intelligence.critical_scan_enabled, mode="anchor", dry_run=False)
    fast_message = install_critical_scan(ROOT, str(ROOT / ".venv" / "bin" / "python"), settings.event_intelligence.critical_scan_fast_hours, settings.event_intelligence.critical_scan_enabled, mode="fast", dry_run=False)
    print(json.dumps({"mode": "rollback" if args.rollback else "apply", "target": target, "schedule": {"anchor": anchor_message, "fast": fast_message}}, indent=2))
```

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全部 PASS（含 `test_documentation_consistency.py`——这一步不改文档，不该受影响；但顺手跑一遍确认没有间接依赖 `critical_scan_hours` 默认值的隐藏断言）。

- [ ] **Step 7: Commit**

```bash
git add app/scheduler.py app/models.py scripts/install_v3_1_schedule.py scripts/cutover_v3_1.py tests/test_v3_1_services.py
git commit -m "$(cat <<'EOF'
Generalize critical-scan launchd plist for dual fast/anchor schedules

build_critical_scan_plist/install_critical_scan take a mode param that
picks the plist label and passes --mode through to the script; anchor
hours default to [6, 21] and a new critical_scan_fast_hours setting
defaults to [9, 12, 15, 18]. install_v3_1_schedule.py and
cutover_v3_1.py now install both plists. Installing to the live
launchd domain is unchanged (still requires --apply); this commit only
changes what gets generated.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

### Task 5: 文档同步

**Files:**
- Modify: `docs/v3_1_config.example.json`
- Modify: `docs/v3_1_runbook.md`
- Modify: `docs/v3_1_event_intelligence_spec.md`（仅 prose，不改 REQ ID，`tests/test_documentation_consistency.py::test_eval_requirement_references_exist_in_spec` 只检查 REQ ID 存在于 spec 正文，不检查具体措辞，改了不会破坏它）

**Interfaces:**
- Consumes: 无。纯文档任务，无新函数/接口产出。

- [ ] **Step 1: 更新 `docs/v3_1_config.example.json`**

把：

```json
    "critical_scan_hours": [1, 5, 9, 13, 17, 21],
```

改成：

```json
    "critical_scan_hours": [6, 21],
    "critical_scan_fast_hours": [9, 12, 15, 18],
    "alpha_vantage_daily_call_limit": 20,
```

- [ ] **Step 2: 更新 `docs/v3_1_runbook.md`**

在第 22 行 `.venv/bin/python scripts/critical_event_scan.py --dry-run` 后面加一行说明双模用法：

```
.venv/bin/python scripts/critical_event_scan.py --dry-run --mode fast   # 预览 fast 模式（仅官方 IR/RSS）
.venv/bin/python scripts/critical_event_scan.py --dry-run --mode anchor # 预览 anchor 模式（全部源，含 GDELT/marketaux/AlphaVantage）
```

在第 48 行那段关于"四小时关键扫描 SLA"的文字末尾，补一句：

```
2026-07 起关键扫描改为双模：工作时段（GMT+8 9:00–18:00）每 3 小时跑一次 fast 模式（仅官方 IR/RSS，免费、不计费），anchor 模式精简为每天 06/21 两次全量扫描（含 GDELT/marketaux/AlphaVantage，AlphaVantage 有每日调用上限保护）。
```

- [ ] **Step 3: 更新 `docs/v3_1_event_intelligence_spec.md`**

把 REQ-007（第 31 行）：

```
- **REQ-007** — Same-day Strategic/P0 Candidate alerts from the four-hour scan are the only competing review notification exception.
```

改成：

```
- **REQ-007** — Same-day Strategic/P0 Candidate alerts from the critical scan (fast or anchor mode) are the only competing review notification exception.
```

- [ ] **Step 4: 验证文档一致性测试仍然通过**

Run: `.venv/bin/python -m pytest tests/test_documentation_consistency.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add docs/v3_1_config.example.json docs/v3_1_runbook.md docs/v3_1_event_intelligence_spec.md
git commit -m "$(cat <<'EOF'
Sync docs with the dual-mode critical scan schedule

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

### Task 6: 快讯 RSS 覆盖缺口报告（C3 的代码部分）

**说明：** spec §11 明确把"各实体的有效快讯 feed URL"列为**需要人工核对**的依赖——GlobeNewswire/Business Wire/PR Newswire 的公司专属 feed 需要登录官网查到真实 org GUID，编不出来、也不该编。这个任务只做**能自动化的那部分**：一个脚本，读 Entity Catalog，列出哪些 critical/high 级实体还没有看起来像 feed 的 `scan_urls`（`IR URLs`/`Newsroom URLs`/`Regulatory URLs` 三个字段拼起来的），把人工核对的范围缩小到一个明确的清单，而不是要求 Franco 自己去翻 16 个实体逐个查。

**Files:**
- Create: `scripts/list_entity_feed_gaps.py`
- Test: `tests/test_v3_1_services.py`

**Interfaces:**
- Consumes: `app.event_intelligence.EntityRecord`（已有，`scan_urls: List[str]` 字段）。
- Produces: `entities_missing_feed_urls(catalog: Sequence[EntityRecord]) -> List[EntityRecord]`——纯函数，供脚本和测试共用；筛选 `active` 且 `watch_tier in {"critical","high"}` 且 `scan_urls` 为空的实体。

- [ ] **Step 1: 写失败测试**

在 `tests/test_v3_1_services.py` 的 import 区加：

```python
from scripts.list_entity_feed_gaps import entities_missing_feed_urls
```

在 `test_fast_scan_window_is_nine_to_eighteen_local` 测试后面加：

```python
    def test_entities_missing_feed_urls_flags_only_watched_entities_without_scan_urls(self):
        catalog = [
            EntityRecord("payoneer", "Payoneer", [], ["WorldFirst"], ticker="PAYO", watch_tier="critical", scan_urls=["https://payoneer.com/ir/rss"]),
            EntityRecord("bettr", "Bettr", [], ["WorldFirst"], watch_tier="critical", scan_urls=[]),
            EntityRecord("some-low-tier", "Low Tier Co", [], [], watch_tier="standard", scan_urls=[]),
        ]

        gaps = entities_missing_feed_urls(catalog)

        self.assertEqual([entity.entity_id for entity in gaps], ["bettr"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_entities_missing_feed_urls_flags_only_watched_entities_without_scan_urls -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'scripts.list_entity_feed_gaps'`

- [ ] **Step 3: 实现脚本**

创建 `scripts/list_entity_feed_gaps.py`：

```python
"""List watched entities that still need a manually-verified newswire/IR feed URL.

C3 dependency from docs/superpowers/specs/2026-07-12-faster-critical-event-broadcast-design.md:
GlobeNewswire/Business Wire/PR Newswire company feed URLs need human verification
(they require an org-specific GUID looked up on the vendor's site) before they can
be pasted into the Entity Catalog's "Newsroom URLs" field. This script only narrows
down which entities still need that manual step.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dingtalk_ai_table import list_records  # noqa: E402
from app.event_intelligence import EntityRecord, catalog_from_records  # noqa: E402
from app.secrets import SecretStore  # noqa: E402
from app.storage import SettingsStore  # noqa: E402
from scripts.critical_event_scan import tables_from_settings  # noqa: E402


DATA = ROOT / "data"


def entities_missing_feed_urls(catalog: Sequence[EntityRecord]) -> List[EntityRecord]:
    return [
        entity for entity in catalog
        if entity.active and entity.watch_tier in {"critical", "high"} and not entity.scan_urls
    ]


def main() -> int:
    store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))
    settings = store.load(masked=False)
    tables = tables_from_settings(settings)
    catalog = catalog_from_records(list_records(settings.dingtalk, tables.entity_catalog))
    gaps = entities_missing_feed_urls(catalog)
    if not gaps:
        print("list_entity_feed_gaps: no watched entity is missing a scan URL")
        return 0
    print(f"list_entity_feed_gaps: {len(gaps)} watched entity(ies) still need a manually-verified feed URL in Entity Catalog 'Newsroom URLs':")
    for entity in gaps:
        print(f"- {entity.entity_id} ({entity.canonical_name}, watch_tier={entity.watch_tier})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_v3_1_services.py::V31ServiceTests::test_entities_missing_feed_urls_flags_only_watched_entities_without_scan_urls -v`
Expected: PASS

- [ ] **Step 5: 对生产 Entity Catalog 跑一遍，产出真实清单**

```bash
.venv/bin/python scripts/list_entity_feed_gaps.py
```

Expected: 打印出当前 Entity Catalog 里哪些 critical/high 实体还没有任何 `scan_urls`。**这一步只读不写**，可以直接对生产表跑。把输出结果交给 Franco，由他去 GlobeNewswire/Business Wire/各公司 IR 页面手工核对 feed URL、填回 DingTalk Entity Catalog 的 `Newsroom URLs` 字段——这是 spec §11 明确要求人工做的部分，不在本计划自动化范围内。

- [ ] **Step 6: Commit**

```bash
git add scripts/list_entity_feed_gaps.py tests/test_v3_1_services.py
git commit -m "$(cat <<'EOF'
Add script to list watched entities missing newswire/IR feed URLs

Narrows the C3 manual-verification dependency (spec §11) down to a
concrete list instead of requiring a full manual sweep of the Entity
Catalog.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TAgH5sevKDwriDFfiWKicv
EOF
)"
```

---

## 部署（不是一个 task，是完工后的手动步骤）

以上 6 个 task 全部完成、测试全绿之后，代码层面的 Phase 1 就绪，但**新的 launchd 调度还没生效**——production 仍然按旧的 `critical_scan_hours=[1,5,9,13,17,21]`、单一 anchor 模式在跑（because `install_critical_scan` 只在被调用时才会 `launchctl bootstrap`，而不是在 `settings.sqlite3`/`app/models.py` 里改默认值就自动生效）。

要让新调度上线，需要显式跑：

```bash
.venv/bin/python scripts/install_v3_1_schedule.py --dry-run   # 先看一遍两条 plist 的内容
.venv/bin/python scripts/install_v3_1_schedule.py --apply     # 确认无误后再真正装
```

这一步会替换 `~/Library/LaunchAgents/com.franco.weekly-headlines.critical_event_scan.plist` 并新增 `..._fast.plist`，且会执行 `launchctl bootout`/`bootstrap`——**这是有真实副作用、影响生产调度的操作，实现完 6 个 task 后请显式跟我确认要不要现在执行这一步**，不要在 subagent 或批量执行 task 时顺带自动跑掉。

## Self-Review

**1. Spec 覆盖检查**（对照 spec §4/§8，仅 Phase 1 范围）：
- C1（`--mode` + 工作时段闸门）→ Task 3 ✓
- C2（按 mode 过滤源）→ Task 1 ✓
- C3（快讯 RSS，人工核对依赖）→ Task 6（只做能自动化的缺口清单部分，URL 本身按 spec §11 要求留给人工）✓
- C4（AlphaVantage 每日上限，落 API Usage Ledger）→ Task 2 ✓
- §8 调度（fast 9/12/15/18 三小时一次，anchor 精简 06/21，label 沿用现有命名族+新增 `_fast`）→ Task 4 ✓
- §9 测试清单：mode=fast 只调 official（Task 1）、工作时段闸门（Task 3）、RSS 解析（已有 `test_official_adapter_reads_rss` 覆盖，OfficialSourceAdapter 本身未改动，不需要新测试）、AlphaVantage 上限+回退（Task 2）、高频不重复告警（已有 `new_signal_rows`/`existing_urls` 去重逻辑覆盖，未改动，不需要新测试）✓
- C5（财报日历）：明确不在本计划内，属于 Phase 2。

**2. 占位符扫描：** 通读全部 6 个 task，没有 "TODO"/"实现类似逻辑"/"添加合适的错误处理" 这类占位表述；C3 的 URL 内容留白是 spec §11 本身要求的人工步骤，不是本该写代码却偷懒的占位符。

**3. 类型一致性检查：**
- `collect_critical_signals` 签名从 Task 1 的 `(settings, catalog, mode="anchor")` 演进到 Task 2 的 `(settings, catalog, mode="anchor", usage_ledger=None, run_id="")`，Task 3 里 `main()` 调用处的实参名（`mode=args.mode, usage_ledger=usage_ledger, run_id=run_id`）与 Task 2 定义的参数名完全对齐。
- `count_provider_calls_today(ledger, provider, timezone_name, now=None)` 在 Task 2 Step 3 定义、Step 8 在 `collect_critical_signals` 内部调用时的实参顺序（`usage_ledger, "alpha_vantage", settings.system.timezone`）一致。
- `build_critical_scan_plist(project_root, python_path, hours, mode="anchor")` / `install_critical_scan(project_root, python_path, hours, enabled, mode="anchor", dry_run=False)` 在 Task 4 定义，Task 4 Step 5 里 `install_v3_1_schedule.py`/`cutover_v3_1.py` 的调用都用了关键字参数 `mode=`，不依赖位置顺序，不会因为 `mode` 插入位置而错位。
- `entities_missing_feed_urls(catalog)` 在 Task 6 定义和测试里的签名一致。
