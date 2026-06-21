# Weekly Headlines & Insight 运营模型

**版本：** 1.0  
**状态：** 已确认的产品合同  
**更新时间：** 2026-06-22

## 最终交付

系统只对外产出两类周度内容，均发送至 `Daily News` 发布群：

| 产品 | 内容 | 发送条件 |
| --- | --- | --- |
| `Weekly Headlines` | 本周已采纳新闻的管理层摘要 | News 必须被人工显式标记为 `已采纳`。 |
| `Weekly Insight` | 有明确研究问题、证据和边界的分析报告 | 经方案、证据/Claim、草稿三个审核阶段；未操作按时限自动通过。 |

`Daily News Review` 只是支持流程，负责每日 News 审核，不是第三个管理层产品。

## 人工与自动边界

| 环节 | 人工责任 | 自动行为 | 未操作规则 |
| --- | --- | --- | --- |
| News 审核 | 必须显式采纳、拒绝或纠正重复 | 采集、日期补齐、去重、催审 | 不默认通过；不进入任何最终交付。 |
| Insight 研究方案 | 可批准、驳回或要求修改 | 生成问题、范围、候选材料与研究计划 | 到正式分析窗口仍未操作时，记为 `Auto-approved` 后继续。 |
| Evidence / Claim | 首阶段逐条审核 | 建议证据、来源等级、Claim、反证与边界 | 到草稿生成窗口仍未操作时，记为 `Auto-approved` 后继续。 |
| Insight 草稿 | 可批准、驳回或要求修改 | 生成文档、摘要、图片和发送素材 | 到正式发送窗口仍未操作时，记为 `Auto-approved` 后发送。 |

每次 `Auto-approved` 都须写明审核阶段、截止时间、自动通过时间和原因，并记录在 Audit Trail。

## 群路由

| 群 | 接收内容 | 不接收内容 |
| --- | --- | --- |
| `BOT监控审核群` | News 待审、方案待审、Evidence/Claim 待审、草稿待审、超时催办、运行失败 | 正式 Weekly Headlines、正式 Weekly Insight。 |
| `Daily News` | 正式 Weekly Headlines、正式 Weekly Insight、发送成功/失败结果 | 审核催办、草稿、健康检查与采集噪音。 |

审核通知必须包含直达相应 AI 表格记录或钉钉文档的链接，并按已配置的手机号真实 @ Franco。

## 表结构：前台少、后台可追溯

### 日常可见表

| 表 | 每周怎么用 | 核心字段 |
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
- 每条人工材料必须标明用于 Weekly Headlines、Weekly Insight 或 Reference Only。

## 每周状态机

```text
Accepted News
  -> Weekly Headlines generated -> Sent

Accepted News + Editorial Inputs
  -> Insight plan pending review
  -> plan approved / auto-approved
  -> evidence and claim pending review
  -> evidence and claim approved / auto-approved
  -> insight draft pending review
  -> draft approved / auto-approved
  -> Sent
```

任何 News 未显式采纳时，都不得进入上图。任何 Insight 审核逾期，系统可以继续发送，但必须留下 Auto-approved 记录并在 BOT监控审核群发送提醒。

## 迁移原则

1. 先创建 Weekly Editions 和 Weekly Editorial Inputs，并把现有报告链接与状态映射进去。
2. 再把后台表从日常视图隐藏，保留数据与脚本兼容性。
3. 连续运行四周后，确认 Weekly Editions 足够承接运营工作，再将 Insights 的前台职责完全迁入。
4. 不删除任何历史表或历史记录；所有归档都保留可回查入口。
