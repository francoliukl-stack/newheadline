# GBSS External Event Intelligence v3.1 — Executable Specification

Status: implementation contract  
Product source: `GBSS_Intelligence_PRD_v3_1_Codex_OpenAI.md`  
Canonical timezone: `Asia/Kuala_Lumpur`

## 1. Invariants

1. `News` (`oMbefcK`) remains the source-signal and first human-review table.
2. Event intelligence is additive. Existing News, Insights, research, document, robot and launchd paths are never deleted by a migration.
3. Formal output requires an accepted Event Case, at least one accepted linked News row, Source URL, Publish Date, Evidence ID and Claim ID.
4. Automation may assign only `P0 Candidate`, `P1`, `P2` or `Watch`. Final `P0` requires reviewer, approval status and approval timestamp.
5. A paid call is made only after a conservative preflight cost estimate passes the single-run, daily, weekly and monthly caps. Research with web search additionally requires an approved Research Queue plan.
6. If Event Case, API Usage or Audit Trail storage is unavailable, paid/event-native work fails closed. It never silently publishes from News.
7. A report that fails the research quality gate is labelled `Signal Brief` and contains no deterministic strategic conclusion.

## 2. State machines

### News

`待处理 -> 已采纳 | 已拒绝 | 已重复`

Eventization may inspect non-rejected candidates, but publication requires at least one linked `已采纳` News record.

### Event Case

`待处理 -> 已采纳 | 已拒绝 | 已重复 -> 已归档`

- Machine priority: `P0 Candidate | P1 | P2 | Watch`.
- Human final priority: `P0 | P1 | P2 | Watch | None`.
- `Final Priority=P0` is valid only when `P0 Approval Status=Approved`, `Reviewer` and `Reviewed At` are present.

### Alert

`pending -> sent | failed -> acknowledged | ignored`

`Dedupe Key` makes delivery idempotent for an Event version and alert level.

## 3. DingTalk data contract

| Sheet | Primary key | Required fields |
| --- | --- | --- |
| Event Cases | Event ID | Event Title, Event Type, Business Lines, Primary Entity IDs, Strategic Candidate, First Seen At, Event Date, Status, Priority Candidate, Final Priority, P0 Approval Status, Confidence, Relevance Score, Summary, GBSS Impact Hypothesis, Limitations, Primary Source URL, Publish Date, Source Count, Accepted News Count, Reviewer, Reviewed At, Weekly Headlines Sent At, Weekly Intelligence Sent At, Event Version |
| Event Entities | Event Entity ID | Event ID, Entity ID, Role, Match Method, Confidence |
| Event Sources | Event Source ID | Event ID, News Record ID, Source URL, Source Domain, Publish Date, Source Grade, Is Primary Source, Evidence Value, Provider, Duplicate Of |
| Event Scores | Event Score ID | Event ID, Source Grade Score, Entity Match Score, Event Severity Score, Business Line Fit Score, Novelty Score, Market Confirmation Score, Overall Score, Scoring Reason, Scoring Version, Model, Prompt Version, Scored At, Human Override |
| Entity Catalog | Entity ID | Canonical Name, Aliases, Entity Type, Business Lines, Ticker, Official URLs, IR URLs, Newsroom URLs, Regulatory URLs, Source Grade Default, Watch Tier, Critical Event Types, Scan Cadence Hours, Active, Notes, Updated At |
| Alert Log | Alert ID | Event ID, Alert Level, Sent To, Message, Dedupe Key, Sent At, Ack Status, Ack By, Ack At, Error |
| API Usage | Call ID | Run ID, Event ID, Provider, Operation, Model, Pricing Version, Estimated Input Tokens, Estimated Output Tokens, Estimated Cost USD, Actual Input Tokens, Actual Output Tokens, Actual Cost USD, Status, Retry Count, Skip Reason, Started At, Finished At |

Existing sheets gain lineage fields:

- News: `Entity Candidates`, `Event Case ID`, `Provider Score`, `Date Confidence`, `Original Language`, `LLM Processed At`.
- Evidence Bank: `Event ID`, `Event Source IDs`.
- Claim Ledger: `Event ID`, `Impact Level`.
- Insights: `Event IDs`, `Event Source IDs`.

For review efficiency, `News.Source Excerpt` and `Event Sources.Source Excerpt` retain at most 1,800 characters from provider snippets, official RSS descriptions or a best-effort official-page `<article>/<main>` extraction. Extraction is performed only for a newly discovered official critical signal, uses no paid model and never changes reviewer state. Pending Event Evidence uses this excerpt as a candidate fact; Verified Evidence remains immutable to automated reruns.

When OpenAI enrichment is disabled or skipped, `GBSS Impact Hypothesis` uses deterministic Event Type × Business Line review prompts. These prompts identify what the reviewer should compare (for example WorldFirst volume/take-rate guidance or Antom merchant operations) but are explicitly hypotheses, never approved Claims or final strategy conclusions.

The Config sheet stores all new sheet IDs, adapter switches, budget caps, model IDs, prompt versions, `event_intelligence_enabled`, `critical_scan_enabled`, `weekly_input_mode` and `schema.event_intelligence.version`.

## 4. Adapter and LLM interfaces

```text
SourceAdapter.collect(AdapterRequest) -> list[SourceSignal]
SourceAdapter.healthcheck() -> ProviderHealth
ContentAdapter.extract(url) -> ExtractedContent
MarketAdapter.snapshot(EntityRecord) -> list[MarketSignal]
LLMService.execute(task, schema, context, budget_scope, event_id) -> LLMResult[T]
```

All normalized signals contain provider, query, title, source URL/domain, publish date, first-seen timestamp, language and provider metadata. Official/RSS, GDELT and yfinance are first-wave adapters; Marketaux and Firecrawl are second-wave; Alpha Vantage is present but disabled by default.

LLM tasks use Responses API Structured Outputs. Default snapshots are `gpt-5.4-nano-2026-03-17`, `gpt-5.4-mini-2026-03-17` and approval-gated `gpt-5.4-2026-03-05` with web search. Model IDs and pricing remain configuration, never business-code literals.

## 5. Eventization

1. Normalize URL and content hash; merge exact duplicates.
2. Match Entity Catalog aliases, official domains and tickers deterministically.
3. Infer candidate event type from controlled keywords; block candidates by primary entity, event type and a three-day window.
4. Merge high-confidence deterministic candidates. Use LLM only for ambiguous blocked pairs.
5. Persist Event Case, source and entity relations idempotently.
6. Store six component scores in `[0,1]`; code recomputes the PRD weighted total and rejects invalid model output.
7. Mark Earnings, Product Launch, M&A/Strategic Partnership, major Regulatory and Ops Incident events for critical review independently of score.

Critical scan runs at 01:00, 05:00, 09:00, 13:00, 17:00 and 21:00. The full daily ingest remains at 02:00.

## 6. Cost, resilience and audit

- Caps: ingest `$0.30`, insight `$1.50`, daily `$1.00`, weekly `$5.00`, monthly `$25.00`.
- Preflight tokens use conservative UTF-8 byte estimation plus configured maximum output; actual usage comes from the API response.
- Retry only 408/409/429/5xx, at most three attempts with exponential jitter. Validation, authentication and budget errors are not retried.
- The circuit opens for 15 minutes after five consecutive retryable failures or at least half of the latest ten calls fail.
- Every completed, failed or skipped logical call creates API Usage and Audit Trail records. If DingTalk audit writing fails, the payload is retained in `job_runs.metadata.pending_audit_events` and flushed by health check.
- Webhook URLs and all provider keys live in SecretStore/environment only and are always masked in settings exports.

## 7. Weekly and rollback behavior

`weekly_input_mode=event_cases` selects accepted, unsent Event Cases that satisfy the dual-review and lineage gate. After successful delivery it writes sent markers to Event Cases and all linked News rows, and saves Event/Evidence/Claim lineage in Insights. A runtime failure does not fall back.

Rollback is non-destructive: set `weekly_input_mode=news`, disable critical/event feature flags and uninstall only the new critical-scan launchd job. New sheets and fields remain for diagnosis and later re-enable.

## 8. Acceptance thresholds

- Event clustering precision and recall: `>= 0.90`.
- Business-line accuracy: `>= 0.90`; event-type accuracy: `>= 0.85`.
- Critical-event golden-set recall: `1.00`; automatic final-P0 violations: `0`.
- Published lineage completeness and budget-gate compliance: `1.00`.
- Existing regression suite, adapter mocks, dry-runs, live-safe migration checks and manual One Pager review all pass before cutover.
