# GBSS External Event Intelligence v3.1 — Executable Specification

> Version: 3.1
> Last-Updated: 2026-07-11
> Status: active
> Supersedes: none

Product source: [`docs/prd_v3_1_event_intelligence.md`](prd_v3_1_event_intelligence.md)
Canonical timezone: `Asia/Kuala_Lumpur`

## 1. Invariants

- **INV-01** — `News` (`oMbefcK`) remains the source-signal and first human-review table.
- **INV-02** — The system runs from the current workspace and uses existing DingTalk AI Tables as the business datastore. It does not require a database migration or a second local business database.
- **INV-03** — `News=已采纳` is the single publication gate. Event classification is automatic; formal output requires Source URL, Publish Date and Event/Evidence/Claim lineage, while Evidence/Claim approval is required only for strategic conclusions.
- **INV-04** — Automation may assign only `P0 Candidate`, `P1`, `P2` or `Watch`. Final `P0` requires reviewer, approval status and approval timestamp.
- **INV-05** — A paid call requires conservative preflight approval against single-run, daily, weekly and monthly caps. Research with web search additionally requires an approved Research Queue plan.
- **INV-06** — If Event Case, API Usage or Audit Trail storage is unavailable, paid/event-native work fails closed and never silently publishes from News.
- **INV-07** — A report that fails the research quality gate is labelled `Signal Brief` and contains no deterministic strategic conclusion.

## 2. State machines

### News

- **REQ-001** — News follows `待处理 -> 已采纳 | 已拒绝 | 已重复`.
- **REQ-002** — Eventization may inspect non-rejected candidates; publication requires at least one linked `已采纳` News record and no second Event approval.
- **REQ-003** — The operations review batch uses `Asia/Kuala_Lumpur` and includes only `Status=待处理`, previous-calendar-day `Publish Date`, and a non-empty Event Case ID.
- **REQ-004** — Missing-date, older and unmatched News remain auditable but are excluded from that reminder.
- **REQ-005** — The reminder runs seven days a week and states the exact review date.
- **REQ-006** — Successful 02:00 ingest is RunLog/Audit-only; ingest failure alerts the operations group.
- **REQ-007** — Same-day Strategic/P0 Candidate alerts from the four-hour scan are the only competing review notification exception.

### AI-assisted News review

- **REQ-008** — `Status` is effective; `AI Status` is advisory and never overwrites an existing human decision.
- **REQ-009** — `AI Status` must be exactly `已采纳 | 已拒绝 | 已重复`; `待处理` and separate “建议” labels are forbidden.
- **REQ-010** — At 08:50 every News row has AI Status; the initial run backfills all rows and later runs update only missing or fingerprint-changed rows.
- **REQ-011** — Default recommendations are deterministic, auditable and require no paid model.
- **REQ-012** — The 09:00 reminder fails closed and audits the failure if any eligible row lacks a valid AI Status; it must not send a misleading zero summary.
- **REQ-013** — The 09:00 card links to the same News rows for human use or override.
- **REQ-014** — Human Status before 11:50 wins and records `Review Decision Source=Human` plus Matched/Overridden.
- **REQ-015** — 11:50 fallback requires pending human Status, `AI Status=已采纳`, confidence `>=0.85`, complete Publish Date/Source URL/Event Case ID, mapped business line and non-General Event Type.
- **REQ-016** — Deadline writes record `AI_Deadline`, applied status and timestamp; AI rejection remains human-pending.
- **REQ-017** — Missed-deadline recovery uses the preceding seven-day window.
- **REQ-018** — Recovery admits only pending, high-confidence, traceable AI accepts linked to active non-archived Events, newest first, at most five rows per run.
- **REQ-019** — Recovery records `AI_Deadline_Recovery` and excludes human terminal decisions, AI rejects/duplicates, low confidence, merged/archived/rejected Events and older rows.
- **REQ-020** — Accepted News synchronizes linked active Events to accepted without reopening terminal Events; the 12:00 guard repairs partial writes.
- **REQ-021** — Unchanged recommendations remain plannable; RunLog/Audit starts before DingTalk reads so read/planning failures remain visible.
- **REQ-022** — The 12:00 guard reruns only the previous-day high-confidence deadline plan idempotently.
- **REQ-023** — The 12:00 guard never performs overdue recovery or consumes a second five-row batch.
- **REQ-024** — Guard failure fails Daily Report closed, audits failure, and never broadens eligibility or auto-rejects.
- **REQ-025** — Deadline acceptance is factual-only and cannot set final P0, approve Claims, pass Deep Research or assert strategy.
- **REQ-026** — Later human changes record overridden outcome, human status and timestamp; every processed human decision is Matched or Overridden.
- **REQ-027** — Learned policy groups reviewed history by Event Type × Business Line and applies only with at least five examples and at least 80% agreement.
- **REQ-028** — Duplicate and missing URL/date gates cannot be overruled by learning.
- **REQ-029** — The 09:00 card shows prior agreement, override direction and top reasons; overridden rows retain normalized category and explanation.
- **REQ-030** — Override categories cover duplicate, entity, unavailable/thin/promotional content, market commentary, tangential relevance, eventization gap and under-classification without discarding original text.
- **REQ-031** — Reconciliation clears stale difference fields when AI and human decisions later match.
- **REQ-032** — Every AI review run stores a reproducible, no-paid-call learning snapshot in RunLog and Audit Trail.
- **REQ-033** — Learned rules recalculate from DingTalk history, are fingerprint-versioned, and remain observation-only below thresholds.
- **REQ-034** — Static fixtures require 100% hard-gate compliance and non-decreasing held-out agreement; production rules never self-modify code or thresholds.
- **REQ-035** — Within each 02:00 query group, previous-day candidates rank before same-day, older and missing-date candidates; trust breaks same-date ties.
- **REQ-036** — Cross-group round-robin prevents one source from consuming the cap.
- **REQ-037** — Missing-date candidates cannot enter the 09:00 review until resolved.
- **REQ-038** — Provider-relative timestamps resolve at collection time in the canonical timezone with method `provider_relative`; metadata/URL may later confirm or replace them.
- **REQ-039** — Relative-date conversion is deterministic under injected time and never guesses unparseable values.
- **REQ-040** — `First Seen At` is never a Publish Date fallback or proof of previous-day eligibility.

### Event Case

- **REQ-041** — At least one accepted linked News produces accepted Event status; otherwise it remains pending unless rejected or archived.
- **REQ-042** — Full eventization reconciles every non-archived Event from all linked News, including rows outside the active candidate pass.
- **REQ-043** — Any accepted source keeps Event accepted; all-terminal duplicate-only sources archive it; any human rejection yields rejected when no source is accepted or pending.
- **REQ-044** — Event Cases have no separate duplicate status; source-level News retains duplicate identity and linkage.
- **REQ-045** — Merged archives remain terminal; ordinary active candidates may reopen rule/staleness archives.
- **REQ-046** — After the review day, a non-strategic General/Market_Context Event with all human-pending News and all AI rejects is archived without changing News Status or feedback.
- **REQ-047** — Strategic/P0 Candidate and specifically typed Events are exempt; later human acceptance reopens the ordinary archived Event.
- **REQ-048** — Machine priority is `P0 Candidate | P1 | P2 | Watch`; human final priority is `P0 | P1 | P2 | Watch | None`.
- **REQ-049** — Final P0 is valid only with approved status, reviewer and reviewed timestamp.

### Alert

- **REQ-050** — Alert follows `pending -> sent | failed -> acknowledged | ignored`.
- **REQ-051** — Dedupe Key makes delivery idempotent by Event version and alert level.

## 3. DingTalk data contract

| Requirement | Sheet | Primary key | Required fields |
| --- | --- | --- | --- |
| REQ-052 | Event Cases | Event ID | Event Title, Event Type, Business Lines, Primary Entity IDs, Strategic Candidate, First Seen At, Event Date, Status, Priority Candidate, Final Priority, P0 Approval Status, Confidence, Relevance Score, Summary, GBSS Impact Hypothesis, Limitations, Primary Source URL, Publish Date, Source Count, Accepted News Count, Reviewer, Reviewed At, Daily Report Sent At, Weekly Headlines Sent At, Weekly Intelligence Sent At, Event Version |
| REQ-053 | Event Entities | Event Entity ID | Event ID, Entity ID, Role, Match Method, Confidence |
| REQ-054 | Event Sources | Event Source ID | Event ID, News Record ID, Source URL, Source Domain, Publish Date, Source Grade, Is Primary Source, Evidence Value, Provider, Duplicate Of |
| REQ-055 | Event Scores | Event Score ID | Event ID, Source Grade Score, Entity Match Score, Event Severity Score, Business Line Fit Score, Novelty Score, Market Confirmation Score, Overall Score, Scoring Reason, Scoring Version, Model, Prompt Version, Scored At, Human Override |
| REQ-056 | Entity Catalog | Entity ID | Canonical Name, Aliases, Entity Type, Business Lines, Ticker, Official URLs, IR URLs, Newsroom URLs, Regulatory URLs, Source Grade Default, Watch Tier, Critical Event Types, Scan Cadence Hours, Active, Notes, Updated At |
| REQ-057 | Alert Log | Alert ID | Event ID, Alert Level, Sent To, Message, Dedupe Key, Sent At, Ack Status, Ack By, Ack At, Error |
| REQ-058 | API Usage | Call ID | Run ID, Event ID, Provider, Operation, Model, Pricing Version, Estimated Input Tokens, Estimated Output Tokens, Estimated Cost USD, Actual Input Tokens, Actual Output Tokens, Actual Cost USD, Status, Retry Count, Skip Reason, Started At, Finished At |

Existing sheets gain lineage fields:

- **REQ-059** — `News` stores AI recommendation, version/fingerprint, application, decision-source and feedback fields.
- **REQ-130** — News writes resolve the effective human-status field against existing table fields and may use `Manual Status`, `Review Status` or `Status`; compatibility cannot create a second status source, overwrite human decisions or weaken the publication gate.

- **REQ-060** — News stores Entity Candidates, Event Case ID, Provider Score, Date Confidence, Original Language and LLM Processed At.
- **REQ-061** — Evidence Bank, Claim Ledger and Insights store the specified Event lineage fields.

- **REQ-062** — News/Event Source excerpts retain at most 1,800 characters from provider, RSS or best-effort article/main extraction.
- **REQ-063** — Extraction runs only for newly discovered official critical signals, uses no paid model and never changes reviewer state.
- **REQ-064** — Pending Evidence may use the excerpt as a candidate fact; Verified Evidence is immutable to automation.

- **REQ-065** — Without OpenAI enrichment, impact uses deterministic Event Type × Business Line review prompts that remain hypotheses, never approved Claims or final conclusions.

- **REQ-066** — Config stores sheet IDs, switches, caps, model/prompt versions and schema flags; SQLite stores only settings and RunLog.

## 4. Adapter and LLM interfaces

```text
SourceAdapter.collect(AdapterRequest) -> list[SourceSignal]
SourceAdapter.healthcheck() -> ProviderHealth
ContentAdapter.extract(url) -> ExtractedContent
MarketAdapter.snapshot(EntityRecord) -> list[MarketSignal]
LLMService.execute(task, schema, context, budget_scope, event_id) -> LLMResult[T]
```

- **REQ-067** — Normalized signals contain provider, query, title, URL/domain, Publish Date, First Seen, language and provider metadata.
- **REQ-068** — Official/RSS, GDELT and yfinance are first-wave; Marketaux/Firecrawl second-wave; Alpha Vantage defaults disabled.

- **REQ-069** — Official HTML extraction returns article-body links and excludes navigation, locale, product-menu, CSS and generic CTA anchors.
- **REQ-070** — Candidates rank by article-like path, parsed date newest first, then meaningful anchor/page order; same-domain absolute and relative links are supported.
- **REQ-071** — ISO, RFC822, month-name and common numeric listing dates normalize without using collection time as publication time.
- **REQ-072** — Adapter limit applies after ranking/de-duplication; zero article candidates is visible and never proves coverage.

- **REQ-073** — Daily Brave uses bounded topic, five-entity watchlist and curated site-query families; configured domains are not assumed queried.
- **REQ-074** — Detect Sources covers critical/core entities and selected high-watch competitors.
- **REQ-075** — Round-robin admission enforces a 30-candidate cap without starving later groups; the plan remains below 16 requests per full ingest and external billing stays capped.
- **REQ-131** — `search_provider.supplemental_providers` defaults to `["gdelt_doc"]` and runs alongside the primary/fallback provider against the same Detect Sources query plan; supplemental results retain provider/discovery lineage but do not bypass URL dedupe, candidate caps, Publish Date gates, Eventize or News review.
- **REQ-132** — GDELT DOC translates `site:` filters to `domain:`, adds an English-language filter when absent, normalizes `seendate` to ISO UTC when possible and uses bounded retry for HTTP 429.
- **REQ-133** — Provider health distinguishes `primary`, `fallback` and `supplemental`; primary/fallback availability determines health-check success, while supplemental outages are logged as degraded recall and do not page the operations group or fail ingest.
- **REQ-134** — Critical scans run in dual mode: `fast` mode only queries official IR/RSS sources during local work hours, while `anchor` mode runs the full source set on a sparse schedule; AlphaVantage calls are capped per local day and recorded in API Usage.

- **REQ-076** — LLM tasks use Responses API Structured Outputs and configured model/pricing snapshots; strong-model web search is approval-gated and model IDs are not business-code literals.

## 5. Eventization

- **REQ-077** — Normalize URL/content hash and merge exact duplicates.
- **REQ-078** — Match Entity Catalog aliases, official domains and tickers deterministically.
- **REQ-079** — Visa in immigration/passport/consular/H-1B context is not the payment entity without official-domain or explicit payment context; explicit brand casing remains positive outside negative contexts.
- **REQ-080** — UPI maps to Unified Payments Interface under India/NPCI/instant-transfer context and to UnionPay International under UnionPay wording/domain; a bare acronym never creates both.
- **REQ-081** — Candidate blocking uses primary entity, Event Type and a three-day window.
- **REQ-082** — International UPI or named-country QRIS rollout is Market_Expansion; adoption growth without rollout is Market_Context; payment-council seat is Channel_Partner.
- **REQ-083** — Concrete capital raise language is Strategic_MA even without “funding”; a distinctive same-entity/type/amount transaction may use a seven-day evidence window.
- **REQ-084** — High-confidence deterministic candidates merge; generic shared expansion wording without geography/distinctive subject does not merge, and LLM is reserved for ambiguous blocked pairs.
- **REQ-085** — Event, source and entity persistence is idempotent; merge retains one stable Event ID, relinks sources and archives superseded Events with merge target.
- **REQ-086** — Archived merged Events are excluded from management outputs; a split allows at most one candidate to inherit the old ID and assigns deterministic unique IDs to the rest.
- **REQ-087** — Merge archives remain terminal; ordinary rule/staleness archives may reopen when active again.
- **REQ-088** — Entity correction updates active primary relations while obsolete relations remain auditable as superseded/catalog_reconciliation/0.
- **REQ-089** — Six component scores are in `[0,1]`; code recomputes weighted total and rejects invalid model output.
- **REQ-090** — Earnings, Market Expansion, Product Launch, Strategic_MA, major Regulatory and Ops Incident receive critical review independently of score.
- **REQ-091** — Concrete funding is Strategic_MA; valuation-only commentary is Market_Context.
- **REQ-092** — Market_Context is non-transactional and never raises Strategic/P0 Candidate.
- **REQ-093** — Named-destination payment rollout is Market_Expansion and equivalent entity/destination/date coverage merges; local adoption anecdotes remain Market_Context.
- **REQ-094** — Partner certification is Channel_Partner, not Product_Launch/P0; listing CTA suffixes are removed.
- **REQ-095** — Definitive named acquisition is Strategic_MA and prefers official buyer/target evidence; later law-firm alerts are duplicate/supporting noise.
- **REQ-096** — HKMA multi-point bank strategy is Regulatory; major Voice AI builders map to GBSS_Service for concrete launches.
- **REQ-097** — Named CEO/CFO/CPO changes are Leadership_Change, reviewable but non-critical absent another critical trigger.
- **REQ-098** — Critical scan runs at 01/05/09/13/17/21 and full ingest at 02:00.
- **REQ-099** — Critical scan reads Catalog and News once; `new_news=0` records no-change and skips all downstream Event/Evidence/Claim/Alert reads and writes.
- **REQ-100** — Created News is normalized and merged into the initial snapshot using returned IDs; second News read is forbidden and ID-count mismatch fails closed.
- **REQ-101** — Empty generic Event upsert returns before `list_records`.
- **REQ-102** — After extraction, undated or out-of-window critical candidates cannot write News or alert; they may enter later full-ingest reconciliation but cannot create fresh critical alerts.
- **REQ-128** — Regulatory candidates with the same entity, type and nearby dates merge only when their normalized policy-subject tokens overlap; regulator boilerplate alone cannot merge unrelated policy themes.

## 6. Cost, resilience and audit

- **REQ-103** — Caps are ingest `$0.30`, insight `$1.50`, daily `$1.00`, weekly `$5.00`, monthly `$25.00`.
- **REQ-104** — Preflight uses conservative UTF-8 estimation plus max output; actual usage comes from provider response.
- **REQ-105** — Only 408/409/429/5xx retry, at most three attempts with exponential jitter; validation/auth/budget errors do not retry.
- **REQ-106** — DingTalk transient transport/timeout retries are bounded; operator union ID is process-cached; failed writes are never assumed successful.
- **REQ-107** — Workflows reuse in-memory sheet snapshots; empty upserts make zero reads; configured Audit Trail append skips field enumeration and failures enter pending RunLog audit.
- **REQ-108** — Webhook delivery requires successful transport and zero/missing errcode; robot rejection under HTTP 200 is failed and audited.
- **REQ-109** — Circuit opens 15 minutes after five consecutive retryable failures or at least half of the latest ten calls fail.
- **REQ-110** — Every completed/failed/skipped logical call records API Usage and Audit; pending audit flushes through health check.
- **REQ-111** — Webhooks and provider keys live only in SecretStore/environment and remain masked.

## 7. Daily report, weekly insight and rollback behavior

- **REQ-112** — Friday selects accepted Events and writes 3–4 research directions plus paste-ready Prompt to Research Queue without a project OpenAI call.
- **REQ-113** — The owner runs ChatGPT Deep Research, saves a DingTalk document and fills `Research Document URL`.
- **REQ-114** — Sunday 12:00 sends that link plus deduplicated weekly Event/news titles, source URLs and Publish Dates.
- **REQ-115** — DingTalk link cells normalize to HTTP(S); exact period wins, otherwise only the newest manual plan requested within three days may be reused.
- **REQ-116** — A short English access hint and join-group link appears below the report link and above `Weekly Key Events & News`.
- **REQ-117** — Weekly link mode creates no image One Pager, image upload or duplicate long-form document; missing/stale/invalid URL fails closed without sent marker.
- **REQ-118** — For mobile display, a non-Latin short first title segment may use a later segment with at least five Latin words; ordinary title/publisher keeps the title and identity/lineage never changes.
- **REQ-119** — Daily footer claims manual verification only when all sources are human-reviewed; any deadline source triggers explicit AI-fallback disclosure.
- **REQ-120** — Event mode Daily Report runs at 12:00 and selects unsent Events backed by live accepted News, displaying business line, Event Type, title, source URL and Publish Date.
- **REQ-121** — Chat omits internal IDs while DingTalk tables, marker relations and Audit retain lineage.
- **REQ-122** — AI_Intelligence delivery has empty mention payload; the system never performs the owner's manual 13:00 forwarding.
- **REQ-123** — Publication reads live News Status; any linked legacy sent marker proves Event delivery, and added sources alone never trigger duplicate resend.
- **REQ-124** — Pending Evidence/Claims allow factual Daily/Signal Brief but cannot support strategic conclusions or Deep Research.
- **REQ-125** — Successful Daily writes Daily markers to Event and linked accepted News; Weekly uses independent Weekly marker; runtime failure never falls back.
- **REQ-126** — After a successful guard, zero Daily items sends a no-mention heartbeat and no markers; guard/read/webhook failure cannot masquerade as empty day.
- **REQ-127** — Rollback sets News input, disables Event/critical flags and removes only the critical launchd job while retaining sheets and history.
- **REQ-129** — Publication and sent-marker dedupe use only current relations where `News.Event Case ID` equals `Event Source.Event ID`; stale source relations remain auditable but cannot suppress or enter a report.

## 8. Acceptance thresholds

- Event clustering precision and recall: `>= 0.90`.
- Business-line accuracy: `>= 0.90`; event-type accuracy: `>= 0.85`.
- Critical-event golden-set recall: `1.00`; automatic final-P0 violations: `0`.
- Published lineage completeness and budget-gate compliance: `1.00`.
- Empty critical scans read no downstream Event/Evidence/Claim/Alert tables; empty Event upserts make zero DingTalk reads; configured Audit Trail appends do not enumerate fields.
- Existing regression suite, adapter mocks, dry-runs, read-only workspace/table checks and manual One Pager review all pass before cutover.

## 9. Operating observation

`high_relevance_signals_7d` counts only non-rejected/non-duplicate News linked to an active Event. News that still points to an archived/rejected Event remains visible in raw throughput and `archived_event_linked_signals_excluded_7d`, but cannot inflate the high-relevance operating band.

The KPI snapshot uses `Asia/Kuala_Lumpur` and reports candidate lineage, Event Cases awaiting News review, zero automatic final-P0 violations, rolling 28-day API cost, weekly throughput and the previous day's review workload. Review workload includes batch size, completed/pending rows and AI-aligned/overridden decisions. Until a true review-session timer exists, `estimated_review_minutes` is explicitly calculated as 15 seconds per aligned decision, 60 seconds per override and 45 seconds per unfinished row. It must remain labelled as an estimate; the `<=10 minutes` product outcome requires at least one manually timed sample each week and cannot be declared met from the estimate alone. The CLI report remains read-only. The scheduled live daily health check stores the complete snapshot in both local RunLog metadata and DingTalk Audit Trail (`HEALTH.v3_1_kpi`); dry-runs are marked as such and do not count as production observation evidence. No additional business table is introduced. The initial `10-30` linked signals and `5-10` Event Cases per week are operating bands for calibration, not substitutes for the PRD accuracy gates. A weekly Event is counted only when a linked News row was first seen in the same window, excluding historical backfills.

Actual review time is recorded through `record_review_timing.py` as a manual timed sample in the existing local RunLog and DingTalk Audit Trail; it creates no new business table. Each sample includes review date, elapsed minutes, reviewed row count, target status, notes and recorded timestamp. DingTalk `lastModifiedTime` is not accepted as actual review duration because automated Event/AI writes also update it and may use the same operator identity.

Four-week success remains `observation_incomplete` until at least 28 calendar days have elapsed since the first successful production critical scan. Pre-observation critical backfills remain visible but do not count toward the production detection SLA. Source Publish Date is currently date-only, so the KPI labels publish-to-Event lag accordingly; the four-hour critical-scan SLA is proven from scheduler/job-run timestamps or a controlled fixture.
