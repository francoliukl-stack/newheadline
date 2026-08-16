# Daily Report & Weekly Insight 运营模型

> Version: 1.2
> Last-Updated: 2026-08-16
> Status: active
> Supersedes: Version 1.1 of this document

**版本：** 1.0
**状态：** 已确认的产品合同
**更新时间：** 2026-06-22

## 最终交付

系统对外产出一类日度事实摘要和一类周度分析，均发送至 `AI_Intelligence` 发布群（`weekly_webhook_url`）：

| 产品 | 内容 | 发送条件 |
| --- | --- | --- |
| `Daily Report` | 每天新增、已采纳新闻对应的 Event 管理层摘要 | News 必须被人工显式标记为 `已采纳`；每天 12:00 增量发送，预留一小时人工检查后于 13:00 转发。 |
| `Weekly Insight` | 人工在 ChatGPT Deep Research 完成并保存到钉钉文档的分析报告 | 系统周五提供方向和 Prompt；周日发送报告链接 + 关键 Event/新闻，缺链接失败关闭。 |

`Daily News Review` 只是支持流程，负责每日 News 审核，不是第三个管理层产品。

## 人工与自动边界

| 环节 | 人工责任 | 自动行为 | 未操作规则 |
| --- | --- | --- | --- |
| News 审核 | 必须显式采纳、拒绝或纠正重复 | 采集、日期补齐、去重、催审 | 不默认通过；不进入任何最终交付。 |
| Insight 研究方案 | 从 4 个方向中选择或调整，并在 ChatGPT 发起 Deep Research | 周五根据已采纳 Event 生成方向、来源和可粘贴 Prompt | 不发起项目内付费调用；未操作则等待人工完成。 |
| Evidence / Claim | 在 ChatGPT 报告中核查关键事实、引用、反证和边界 | 提供 Event/News/Source URL/Publish Date 输入，不自动批准 Claim | 不自动通过，不把新闻摘要升级为研究结论。 |
| Insight 成稿 | 将 ChatGPT 结果保存为钉钉文档，并把链接填入 `Research Queue.Research Document URL` | 校验链接并准备“报告链接 + 关键新闻”周日消息 | 缺链接时失败关闭，不发送、不写周报发送标记。 |

项目内不再执行 Weekly Insight `Auto-approved`；人工报告链接是周日发布的必要条件。

## 群路由

| 群 | 接收内容 | 不接收内容 |
| --- | --- | --- |
| `BOT监控审核群` | News 待审、方案待审、Evidence/Claim 待审、草稿待审、超时催办、运行失败 | 正式 Daily Report、正式 Weekly Insight。 |
| `AI_Intelligence` | 正式 Daily Report、正式 Weekly Insight 链接与关键新闻 | 审核催办、草稿、健康检查与采集噪音。 |

审核通知必须包含直达相应 AI 表格记录或钉钉文档的链接，并按已配置的手机号真实 @ Franco。

## 表结构：前台少、后台可追溯

### 日常可见表

| 表 | 怎么用 | 核心字段 |
| --- | --- | --- |
| `News` | 每日审核候选新闻 | No、Title、Source URL、Publish Date、Status、Rejection Reason。 |
| `Weekly Editions` | 每周一条总控记录，查看两个最终产品和所有审核状态 | Week、Headlines Status、Insight Plan Status、Evidence Status、Claim Status、Draft Status、Final Delivery Status、各文档链接。 |
| `Weekly Editorial Inputs` | 随时补充人工材料；没有材料时保持空白 | Week、Target Product、Input Type、Title、Short Summary、Source URL、Document URL、Attachment、Use Status、Notes。 |
| `Detect Sources` | 维护关注公司、主题和来源域名 | Source/Entity、Type、Enabled、Priority。 |
| `Config` | 查看与调整排程、Provider 和发布规则 | Config Key、Value、Description。 |

### 后台保留表

Audit Trail、Research Queue、Evidence Bank、Claim Ledger、Research Results 继续保留，用于审计和研究质量控制；默认从日常导航隐藏，不要求管理层日常浏览。

Daily Headlines Review 为历史表，归档并停止作为自动任务输入。Search Providers 的配置职责迁入 Config，历史质量数据保留只读。

### 长材料规则

- 长报告正文存于钉钉文档/DWS 文档。
- PDF、PPT、外部文件作为 Weekly Editorial Inputs 的附件上传。
- AI 表格只存链接、附件、短摘要与用途；不直接放长正文。
- 每条人工材料必须标明用于 Daily Report、Weekly Insight 或 Reference Only。

## 发布状态机

```text
Accepted News
  -> Event Case auto-classified
  -> Daily Report generated at 12:00 -> Human check -> Manual forward at 13:00

Accepted Event Cases
  -> Friday research directions + paste-ready ChatGPT Prompt
  -> Human runs ChatGPT Deep Research
  -> Human saves DingTalk document
  -> Research Queue.Research Document URL
  -> Sunday link + key Event/news digest
  -> Sent
```

任何 News 未生效采纳时，都不得进入上图。缺少人工研究文档链接时，Weekly Insight 不得继续发送。

## 迁移原则

1. 先创建 Weekly Editions 和 Weekly Editorial Inputs，并把现有报告链接与状态映射进去。
2. 再把后台表从日常视图隐藏，保留数据与脚本兼容性。
3. 连续运行四周后，确认 Weekly Editions 足够承接运营工作，再将 Insights 的前台职责完全迁入。
4. 不删除任何历史表或历史记录；所有归档都保留可回查入口。
