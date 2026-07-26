# 设计：新闻来源 P1/P2 完整性与可观测性升级

> Date: 2026-07-26
> Status: approved in conversation

## P1：补召回能力，但不扩大每日全表读取

1. `Detect Sources` 增加显式 `Collection Mode`：
   - `entity_query`：实体词查询；
   - `topic_query`：主题词查询；
   - `direct_site`：独立站点查询；
   - `rank_only`：只参与来源排序，不产生额外查询。
2. Reuters 等一级可信媒体继续走 `trusted_media`；PYMNTS、UC Today 作为二级专业媒体走
   `specialist_media`，独立召回但不自动获得一级可信来源配额。
3. 为支付基础设施、监管与 CX 平台补官方入口；四小时快扫只运行
   `Scan Cadence Hours <= 4` 的实体，24 小时锚点扫描全部高优先级实体。
4. AI Review 更新支持小批次、批间等待和最大更新数，避免单次大批写触发 QPS。
5. 历史可信来源待处理项使用既有 AI 规则回填，只写 AI 辅助字段，不覆盖人工最终状态。

## P2：把漏报从偶发问题变成可回归、可量化问题

1. 五条已批准高价值新闻固定为回归集，继续验证 URL、实体、事件类型、业务线和发布资格。
2. 新增周度本地快照，输出：
   - Known Important Recall；
   - Official Source Coverage / Freshness；
   - Trusted Lane Purity；
   - News → Event → Accepted 转化；
   - Time-to-detect。
3. 快照每周运行一次，读取现有 News / Event / Source / Entity 表，不增加每日任务的全表读取。
4. 空日报 RunLog 和 Audit Trail 输出稳定原因码，例如：
   - `no_formally_accepted_news`
   - `accepted_news_missing_event`
   - `no_publication_eligible_event`
   - `all_eligible_already_sent`
   - `no_events_in_report_window`

## 验收

- `source_domain` 的采集行为由 `Collection Mode` 决定，不再隐式或惰性。
- 专业媒体独立查询不能被标成 `trusted_media`。
- 快扫不会因 24 小时来源扩容而按四小时频率扫描全部页面。
- AI Review 可分批写入且保留人工状态。
- 周度快照可在无写操作的 dry-run 中生成，并纳入 scheduler。
- 空日报能在现有读取结果内给出原因，不增加额外远程读。
