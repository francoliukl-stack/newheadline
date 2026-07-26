# 设计：新闻来源 P0 召回与链路加固

> Date: 2026-07-26
> Status: approved by the user's request to implement the P0 recommendations
> Scope: trusted-source recall, lane integrity, lineage persistence, URL identity, UnionPay/UPI disambiguation

## 1. 目标

在不扩大普通关键词、不改变 News 人工审批边界、不触发历史 AI Review 批量重算的前提下，修复本次来源体检确认的五个 P0 缺陷：

1. 可信媒体查询恢复为搜索服务已验证可工作的简单 `site:` OR 查询，不再叠加主题后缀。
2. `trusted_media` 只保留真实结果域名属于可信清单的候选；不匹配结果降级为 `broad_market`，不静默丢弃。
3. `Source Lane` 与 `Search Group` 从抓取结果持续写入 News，保留可审计链路。
4. 候选去重、News 写入前去重、人工输入和事件内容哈希使用统一 URL identity：协议和主机小写、忽略 `www.`、移除 fragment、移除 tracking 参数、保留业务参数、移除多余尾斜杠。
5. UnionPay International 不再使用 `UPI` 别名；印度 UPI 继续由独立实体和 NPCI 语境识别。

## 2. 数据流

```text
Detect Sources
  → simple trusted site query
  → provider results
  → canonical URL identity dedupe
  → actual-domain lane validation
  → balanced selection
  → News normalization with Source Lane/Search Group
  → semantic duplicate detection with the same URL identity
```

## 3. 组件边界

### 3.1 统一 URL identity

新增纯函数模块 `app/url_identity.py`：

- `canonical_article_url(value, strip_www=True) -> str`
- `article_url_identity(value) -> str`

它只移除明确的 tracking 参数，例如 `utm_*`、`fbclid`、`gclid`、`mc_cid`、`mc_eid`；像 Ant International `detail/?id=...` 这样的业务参数必须保留。

### 3.2 查询与 Lane

`build_detect_query_plan` 保持每三个可信来源一组，但查询文本只包含：

```text
site:domain-a OR site:domain-b OR site:domain-c
```

不加括号，不拼主题后缀。主题相关召回继续由独立 `strategic_theme` Lane 承担。

新增纯函数 `validate_candidate_lanes(records, trusted_domains)`。如果候选原始 Lane 是 `trusted_media`，但实际 URL/source 域名不在可信清单中，则将它的 `source_lane` 和 `Source Lane` 都改为 `broad_market`。

### 3.3 News 链路字段

`normalize_news_record` 增加：

- `Source Lane`
- `Search Group`

`NEWS_LINEAGE_FIELDS` 增加 `Search Group`。生产迁移只创建这个缺失字段，不修改其他表结构。

### 3.4 URL 去重

以下边界改用同一 identity：

- `scripts/daily_fetch.py::dedupe_candidates`
- `scripts/push_dingtalk_ai_table.py` 的现有 News URL 集合
- `app/dedupe.py::duplicate_reason`
- `app/editorial_intake.py`
- `app/event_intelligence.py::normalize_url`

存储链接使用清理后的 canonical URL；比较使用忽略 `www.` 的 identity。

## 4. 错误处理与兼容性

- 无效或非 HTTP(S) URL 返回空 identity，并沿用现有 invalid URL 处理。
- 非 tracking 查询参数保留，避免破坏依赖 `id` 等参数的官方新闻链接。
- 非可信结果不丢弃，只失去可信 Lane 配额。
- 旧记录不做全表 URL 重写；新的写入和后续 dedupe 会按新 identity 识别。
- 不运行 `ai_review_suggest.py` live，不改变最终人工审批状态。

## 5. 测试与完成标准

- 简单可信查询不包含主题后缀或外层括号。
- 非可信域名不能占用 `trusted_media` 六条保留配额。
- News 规范化结果包含 `Source Lane` 和 `Search Group`。
- `nojitter.com` 与 `www.nojitter.com`、tracking 参数和 fragment 被识别为同一 URL；`?id=...` 保留并区分。
- UnionPay 查询不包含裸 `UPI`，India UPI 实体识别测试保持通过。
- 定向测试、完整单元测试、`git diff --check` 和生产 dry-run 均通过。
