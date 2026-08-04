# GBSS External Event Intelligence

本仓库运行 GBSS 外部事件情报工作流：以钉钉 AI 表格中的 News 为信号与审核入口，自动形成 Event Case、Daily Report 和人工 ChatGPT Deep Research 驱动的 Weekly Insight。

文档入口：

- [文档体系与维护规则](docs/DOCS_GUIDE.md)
- [领域术语表](CONTEXT.md)
- [架构决策记录](docs/adr/)
- [v3.1 产品合同](docs/prd_v3_1_event_intelligence.md)
- [v3.1 可执行规格](docs/v3_1_event_intelligence_spec.md)
- [运行手册](docs/v3_1_runbook.md)
- [运营模型](docs/weekly_operating_model.md)
- [发布评测集](evals/release_evaluation_set.md)
- [生产完成度审计](docs/v3_1_completion_audit.md)

快速验证：

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_v3_1_evaluation.py
```
