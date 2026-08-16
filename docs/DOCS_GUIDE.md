# GBSS 文档体系维护指南

> Version: 1.2
> Last-Updated: 2026-08-16
> Status: active
> Supersedes: Version 1.1 of this document

## 四层文档结构

| 层级 | 权威资产 | 职责边界 |
| --- | --- | --- |
| L1 产品合同 | [`docs/prd_v3_1_event_intelligence.md`](prd_v3_1_event_intelligence.md) | 说明为什么做、产品边界、用户流程和 KPI；不充当实现细则。 |
| L2 可执行规格 | [`docs/v3_1_event_intelligence_spec.md`](v3_1_event_intelligence_spec.md) | 唯一实现依据；维护系统不变量、可测试规则、状态机和失败策略。 |
| L3 验证资产 | [`evals/*`](../evals/) | 通过 INV/REQ 编号追溯 L2；只保存 fixture、评测方法和验收证据，不复述规则全文。 |
| L4 运营文档 | `docs/` 下 Runbook、运营模型、完成审计 | 说明如何运行、观察、恢复和验收；不得改变 L1/L2 合同。 |
| L0 领域语言 | [`CONTEXT.md`](../CONTEXT.md)、[`docs/adr/`](adr/) | `CONTEXT.md` 只做术语表，定义概念"是什么"，不含实现细节；ADR 记录难以回退的架构取舍及其理由。 |

## 冲突裁决

1. 显式层级优先：L2 Spec > L1 PRD v3.1 > L4 运营文档与历史材料。
2. 同一层级发生矛盾时，以文档头部 `Last-Updated` 较新者为准，并在下一次文档变更中消除冲突。
3. [`docs/prd_v2_1_superseded.md`](prd_v2_1_superseded.md) 已整体被 v3.1 PRD + Spec 取代，只保留历史背景，不得作为实现或验收依据。
4. 评测资产发现规则矛盾时不得自行创造产品语义，必须回到 L2 修正并引用编号。

## 文档位置规则

- `docs/` 是所有项目 Markdown 文档的唯一目录。
- 根目录只保留 `README.md`、`CONTEXT.md` 与 agent 指令文件（`AGENTS.md`、`CLAUDE.md`）：README 只作入口索引，`CONTEXT.md` 只作领域术语表，agent 指令文件因工具约定必须位于根目录，只描述如何在本仓库工作，不承载产品规则。
- ADR 放在 `docs/adr/`，一次决策一份，编号后不重写历史；推翻旧决策时新增一份并标注 Supersedes。
- `evals/` 保留被运行脚本引用的 JSON fixture 和评测说明；不得移动整个目录。
- 今后新增项目文档必须放在 `docs/`；新增运行时评测资产必须放在 `evals/`。
- 每份 active 文档头部必须包含 `Version / Last-Updated / Status / Supersedes`。

## 维护流程

1. 先更新 L1/L2，再更新引用其编号的 L3，最后更新 L4 操作说明。
2. 规则只在 Spec 维护一次；PRD 和评测说明仅保留编号、摘要与链接。
3. 每次发布运行完整一致性检查和 release evaluation，禁止手工维护可生成的验收模板。

## 双评测集生长规则

- `evals/v3_1_event_cases.json` 是可见回归 fixture；每条来自真实坏案例或明确边界，要求逐条 100% 通过，不用于证明线上 90%/85% 准确率。
- `evals/v3_1_event_cases_holdout.json` 是隔离 holdout；只从生产 Matched/Overridden 复核数据补充，设计或修改 eventization 规则时禁止参考其中 case。
- 新坏案例按进入顺序交替分配：奇数序号进入回归集，偶数序号进入 holdout；同一事件的改写不得跨两集合复制。
- 规则冻结后才运行 holdout；holdout 失败先记录为生产差异，不得把答案复制进规则后继续用同一 case 宣称泛化成功。
