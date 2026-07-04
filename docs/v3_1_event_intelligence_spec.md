# GBSS External Event Intelligence v3.1 — Executable Specification

Status: implementation contract  
Product source: `GBSS_Intelligence_PRD_v3_1_Codex_OpenAI.md`  
Canonical timezone: `Asia/Kuala_Lumpur`

## 1. Invariants

1. `News` (`oMbefcK`) remains the source-signal and first human-review table.
2. The system runs from the current workspace and uses existing DingTalk AI Tables as the business datastore. It does not require a database migration or a second local business database.
3. `News=已采纳` is the single human publication gate. The linked Event Case, business line, event type, score and impact hypothesis are generated automatically. Formal output still requires Source URL, Publish Date and generated Event/Evidence/Claim lineage, but Evidence/Claim approval is required only for strategic conclusions.
4. Automation may assign only `P0 Candidate`, `P1`, `P2` or `Watch`. Final `P0` requires reviewer, approval status and approval timestamp.
5. A paid call is made only after a conservative preflight cost estimate passes the single-run, daily, weekly and monthly caps. Research with web search additionally requires an approved Research Queue plan.
6. If Event Case, API Usage or Audit Trail storage is unavailable, paid/event-native work fails closed. It never silently publishes from News.
7. A report that fails the research quality gate is labelled `Signal Brief` and contains no deterministic strategic conclusion.

## 2. State machines

### News

`待处理 -> 已采纳 | 已拒绝 | 已重复`

Eventization may inspect non-rejected candidates. Publication requires at least one linked `已采纳` News record; no second Event approval is required.

The scheduled operations-group review batch is date-gated in `Asia/Kuala_Lumpur`: it contains only News with `Status=待处理`, `Publish Date=the previous calendar day`, and a non-empty Event Case ID. Missing-date, older and unmatched News remain available for audit/reconciliation but are excluded from the daily review reminder. The reminder runs seven days a week and states the exact review date. Successful 02:00 ingest completion is Audit/RunLog-only and does not send a competing review link to the operations group; ingest failures still alert there. Same-day Strategic/P0 Candidate alerts from the four-hour critical scan are a deliberate exception because delaying them would violate the timeliness objective.

### AI-assisted News review

`Status` remains the effective review decision. A separate `AI Status` is a pre-review recommendation and never hides or overwrites an existing human decision. `AI Status` uses the same decision labels as `Status` but must always make a recommendation: `已采纳 | 已拒绝 | 已重复`. `待处理` is reserved for the human `Status` and is forbidden in `AI Status`; no separate “建议” labels are allowed.

- At 08:50, the system guarantees that every News row has an `AI Status`. The first run performs a full-table backfill; later runs update only missing rows or rows whose versioned input fingerprint changed because source, duplicate or Event data changed. Recommendations are deterministic and auditable by default; they do not require a paid model call.
- The 09:00 review reminder treats the 08:50 AI review as a prerequisite. If any previous-day pending News row in the reminder batch lacks one of `已采纳 | 已拒绝 | 已重复`, the reminder fails closed, records the failure in RunLog/Audit and does not send a misleading `0 / 0 / 0` pre-review summary.
- At 09:00, the operations card links to the same News rows so the reviewer can use or override the recommendation.
- Human `Status` changes made before 11:50 always win. The system records `Review Decision Source=Human` plus whether the human result matched or overrode `AI Status`.
- At 11:50, a still-pending News row may be changed to `Status=已采纳` only when `AI Status=已采纳`, confidence is at least `0.85`, Publish Date/Source URL/Event Case ID are complete, and the linked Event has a mapped business line and non-General event type. The write records `Review Decision Source=AI_Deadline`, `AI Applied Status`, and `AI Applied At`. AI `已拒绝` remains human-pending; the deadline never silently discards a source.
- The same 11:50 run performs bounded missed-deadline recovery for the preceding seven-day window: only still-pending, high-confidence, fully traceable AI-accepted News linked to an active non-archived Event may recover, newest first, with a maximum of five rows per run. These writes use `Review Decision Source=AI_Deadline_Recovery`. Human terminal decisions, AI rejects/duplicates, low-confidence recommendations, merged/archived/rejected Events and older rows are never changed. This prevents a failed historical deadline from creating permanent orphan Events without turning recovery into a broad auto-approval path.
- Deadline planning must work when the AI recommendation is unchanged and therefore has no pre-existing update patch in the current run. The workflow RunLog/Audit record is created before DingTalk reads and recommendation planning, so read/planning exceptions are visible and cannot disappear into launchd stderr only.
- At 12:00, Daily Report performs the same deadline plan once more as an idempotent pre-selection guard. A healthy 11:50 run yields zero guard updates; a missed/failed 11:50 run applies only the same high-confidence, traceable AI-accepted rows before report selection. Guard failure makes Daily Report fail closed and is recorded in the Daily Report Audit stage; it never broadens eligibility or auto-rejects News.
- AI deadline acceptance is a factual-publication fallback only. It cannot set `Final Priority=P0`, approve a Claim, pass Deep Research, or generate a deterministic strategic conclusion.
- If a human later changes an AI-applied decision, reconciliation records `AI Feedback Outcome=Overridden`, the observed human status and timestamp. Every processed human decision is compared with the explicit AI decision and recorded as `Matched` or `Overridden`.
- Before the next 08:50 recommendation run, reviewed history is converted into a deterministic feedback policy. It groups human decisions by Event Type and Business Line, selects a learned recommendation only when at least five human-reviewed examples exist and one status accounts for at least 80%, and records support, agreement and rule version. Duplicate evidence and missing URL/date remain hard gates and cannot be overruled by learning.
- The 09:00 operations card includes the previous completed review day's agreement rate, override direction and top difference reasons. Every overridden News row stores a normalized difference category and a readable explanation. This makes the daily bad-case review visible without adding another group notification.
- Normalized override reasons distinguish at least duplicate misses, entity false positives, unavailable source content, thin content, promotional content, market commentary, tangential relevance, eventization gaps and event-type under-classification. Human `Rejection Reason` and the headline provide the deterministic evidence for the category; the original text is never discarded.
- When a later rule or Event correction makes AI and human status match, the previous difference category and summary must be cleared in the same reconciliation update; matched rows can never contribute stale override reasons to the daily summary.
- Every AI review run stores an auditable learning snapshot in RunLog and Audit Trail metadata: rule version, exact Event Type × Business Line segment, recommended status, support, agreement, daily reviewed/matched/overridden counts, top categories and top override directions. The snapshot is computed without a paid call and must be reproducible from News and Event Cases.
- Learned rules are recalculated from DingTalk News history on every run; they are not opaque model fine-tuning and require no paid API. A versioned fingerprint includes the applied rule so a policy change causes deterministic re-review. Rules with insufficient support remain observation-only and never affect recommendations.
- Release quality is measured against a static feedback-learning fixture: hard duplicate/traceability gates must remain 100%, learned-rule application must satisfy its support and agreement gates, and the rule must improve or preserve agreement on held-out examples. Production rules never modify their own code or thresholds online.

The 02:00 full-ingest candidate cap must not let older results crowd out the review date. Within every query group, candidates whose resolved `Publish Date` equals the previous calendar day are ranked first, followed by same-day and then progressively older dated results; source trust breaks ties within the same date priority. The cross-group round-robin remains in place so a high-volume company or topic cannot consume the whole batch. Missing-date results are retained only after dated candidates and cannot qualify for the 09:00 review until their publication date is resolved.

Provider-relative timestamps such as `2 hours ago`, `1 day ago` or `yesterday` are resolved at collection time against `Asia/Kuala_Lumpur` and stored as an initial Publish Date with method `provider_relative`. Page metadata/URL extraction may later replace or confirm that value. The conversion is deterministic under an injected collection timestamp and never guesses an unparseable date. `First Seen At` is never used as a Publish Date fallback: discovery time cannot prove publication time and therefore cannot qualify a News row for the previous-day review batch.

### Event Case

Event status is derived from linked News review: at least one accepted News source produces `已采纳`; otherwise the Event remains `待处理` unless it is rejected, duplicated or archived by system rules.

After every full eventization run, each non-archived Event status is reconciled from all linked News, including rows excluded from the active candidate pass. If any linked News is accepted, the Event remains `已采纳`; if none is accepted or pending and every linked News is terminal, all-duplicate sources produce Event `已归档` while the News rows retain `已重复` and `Duplicate Of`, and any human rejection produces Event `已拒绝`. Event Cases intentionally do not use a separate `已重复` option because duplicate identity belongs to source-level lineage. Every archived Event remains archived; only the active eventization path may deliberately recreate or update a current candidate.

To prevent an ever-growing review backlog without fabricating a human decision, a non-strategic `General` or `Market_Context` Event is archived after its News review day has fully passed when every linked News remains human-pending and every AI Status is `已拒绝`. News Status remains `待处理` and all feedback fields remain available. Strategic/P0 Candidate or specifically typed Events are never auto-archived by this rule. A later human acceptance causes active eventization to reopen the Event.

- Machine priority: `P0 Candidate | P1 | P2 | Watch`.
- Human final priority: `P0 | P1 | P2 | Watch | None`.
- `Final Priority=P0` is valid only when `P0 Approval Status=Approved`, `Reviewer` and `Reviewed At` are present.

### Alert

`pending -> sent | failed -> acknowledged | ignored`

`Dedupe Key` makes delivery idempotent for an Event version and alert level.

## 3. DingTalk data contract

| Sheet | Primary key | Required fields |
| --- | --- | --- |
| Event Cases | Event ID | Event Title, Event Type, Business Lines, Primary Entity IDs, Strategic Candidate, First Seen At, Event Date, Status, Priority Candidate, Final Priority, P0 Approval Status, Confidence, Relevance Score, Summary, GBSS Impact Hypothesis, Limitations, Primary Source URL, Publish Date, Source Count, Accepted News Count, Reviewer, Reviewed At, Daily Report Sent At, Weekly Headlines Sent At, Weekly Intelligence Sent At, Event Version |
| Event Entities | Event Entity ID | Event ID, Entity ID, Role, Match Method, Confidence |
| Event Sources | Event Source ID | Event ID, News Record ID, Source URL, Source Domain, Publish Date, Source Grade, Is Primary Source, Evidence Value, Provider, Duplicate Of |
| Event Scores | Event Score ID | Event ID, Source Grade Score, Entity Match Score, Event Severity Score, Business Line Fit Score, Novelty Score, Market Confirmation Score, Overall Score, Scoring Reason, Scoring Version, Model, Prompt Version, Scored At, Human Override |
| Entity Catalog | Entity ID | Canonical Name, Aliases, Entity Type, Business Lines, Ticker, Official URLs, IR URLs, Newsroom URLs, Regulatory URLs, Source Grade Default, Watch Tier, Critical Event Types, Scan Cadence Hours, Active, Notes, Updated At |
| Alert Log | Alert ID | Event ID, Alert Level, Sent To, Message, Dedupe Key, Sent At, Ack Status, Ack By, Ack At, Error |
| API Usage | Call ID | Run ID, Event ID, Provider, Operation, Model, Pricing Version, Estimated Input Tokens, Estimated Output Tokens, Estimated Cost USD, Actual Input Tokens, Actual Output Tokens, Actual Cost USD, Status, Retry Count, Skip Reason, Started At, Finished At |

Existing sheets gain lineage fields:

`News` additionally stores `AI Status`, `AI Confidence`, `AI Review Reason`, `AI Review Version`, `AI Review Fingerprint`, `AI Reviewed At`, `Review Decision Source`, `AI Applied Status`, `AI Applied At`, `AI Feedback Outcome`, `Human Override Status`, and `AI Feedback At`.

- News: `Entity Candidates`, `Event Case ID`, `Provider Score`, `Date Confidence`, `Original Language`, `LLM Processed At`.
- Evidence Bank: `Event ID`, `Event Source IDs`.
- Claim Ledger: `Event ID`, `Impact Level`.
- Insights: `Event IDs`, `Event Source IDs`.

For review efficiency, `News.Source Excerpt` and `Event Sources.Source Excerpt` retain at most 1,800 characters from provider snippets, official RSS descriptions or a best-effort official-page `<article>/<main>` extraction. Extraction is performed only for a newly discovered official critical signal, uses no paid model and never changes reviewer state. Pending Event Evidence uses this excerpt as a candidate fact; Verified Evidence remains immutable to automated reruns.

When OpenAI enrichment is disabled or skipped, `GBSS Impact Hypothesis` uses deterministic Event Type × Business Line review prompts. These prompts identify what the reviewer should compare (for example WorldFirst volume/take-rate guidance or Antom merchant operations) but are explicitly hypotheses, never approved Claims or final strategy conclusions.

The Config sheet stores all sheet IDs, adapter switches, budget caps, model IDs, prompt versions, `event_intelligence_enabled`, `critical_scan_enabled`, `weekly_input_mode` and `schema.event_intelligence.version`. Local SQLite stores settings and RunLog only.

## 4. Adapter and LLM interfaces

```text
SourceAdapter.collect(AdapterRequest) -> list[SourceSignal]
SourceAdapter.healthcheck() -> ProviderHealth
ContentAdapter.extract(url) -> ExtractedContent
MarketAdapter.snapshot(EntityRecord) -> list[MarketSignal]
LLMService.execute(task, schema, context, budget_scope, event_id) -> LLMResult[T]
```

All normalized signals contain provider, query, title, source URL/domain, publish date, first-seen timestamp, language and provider metadata. Official/RSS, GDELT and yfinance are first-wave adapters; Marketaux and Firecrawl are second-wave; Alpha Vantage is present but disabled by default.

For an official HTML listing page, `OfficialSourceAdapter` extracts article links from the page body rather than returning navigation, locale, product-menu, CSS or generic call-to-action anchors. Candidate links are ranked by article-like paths (`news`, `newsroom`, `press`, `release`, `announcement`, `stories`, `investor`), then by a parsed listing date with newer dated articles first, and finally by meaningful anchor text/page order; same-domain absolute and relative links are supported. ISO, RFC822, month-name and common numeric listing dates are normalized without using collection time as publication time. The adapter limit applies only after ranking and de-duplication. A configured official URL that yields no article-like candidate is a visible adapter outcome, not proof that the entity is covered.

The daily Brave plan must not confuse a configured domain with an actively queried source. It contains three bounded query families: topic queries, five-entity watchlist chunks, and curated `site:` queries for specialist Finance/Payments and Contact Center publications. Detect Sources includes every critical/core GBSS entity plus selected high-watch competitors from Entity Catalog. Results are admitted with round-robin query-group allocation under the existing 30-candidate daily cap, so adding sources cannot starve later groups or inflate the News review queue. The expected plan remains below 16 requests per full ingest; at six full ingests per week this stays inside the configured low-cost envelope, while actual provider billing remains externally capped.

LLM tasks use Responses API Structured Outputs. Default snapshots are `gpt-5.4-nano-2026-03-17`, `gpt-5.4-mini-2026-03-17` and approval-gated `gpt-5.4-2026-03-05` with web search. Model IDs and pricing remain configuration, never business-code literals.

## 5. Eventization

1. Normalize URL and content hash; merge exact duplicates.
2. Match Entity Catalog aliases, official domains and tickers deterministically.
   Ambiguous common-language brands require context disambiguation. In particular, `Visa` in immigration, passport, consular or H-1B language is not the payment-network entity unless the official Visa domain or explicit payment/card/merchant context is also present; explicit brand casing remains a positive signal outside those negative contexts.
   `UPI` is also ambiguous: India/NPCI/instant bank-transfer context maps to `Unified Payments Interface`, while `UnionPay` wording or the UnionPay International official domain maps to `UnionPay International`. A bare acronym without either context must not create both entities.
3. Infer candidate event type from controlled keywords; block candidates by primary entity, event type and a three-day window. International UPI expansion wording such as `NPCI expands UPI for international payments` and concrete QRIS availability in named foreign countries are `Market_Expansion`; QRIS transaction/adoption growth without a new geography or launch is `Market_Context`; obtaining a named payment-council seat is `Channel_Partner`, not a regulatory conclusion. Capital-raise wording such as `raises/raised $ amount` is a `Strategic_MA` financing event even when the word “funding” is omitted. For a distinctive transaction signature (same primary entity, same event type and same normalized monetary amount), allow a seven-day evidence window so an official announcement and later trade-press coverage remain one Event Case.
4. Merge high-confidence deterministic candidates. A shared broad entity/action phrase such as `UPI expands` is insufficient by itself: when two Market Expansion titles share only generic expansion words and no common geography or distinctive subject, they remain separate Events. Use LLM only for ambiguous blocked pairs.
5. Persist Event Case, source and entity relations idempotently. When new evidence causes two previously separate Event Cases to merge, one stable Event ID survives, all sources are re-linked to it, and every superseded Event Case is retained as `已归档` with `Merged Into Event ID`; archived Events are excluded from Daily Report, Weekly Headlines, Weekly Insight and One Pager selection. Conversely, when corrected rules split one old broad Event into multiple candidates, at most one candidate may inherit the old stable ID; every other candidate keeps a distinct deterministic split ID so concurrent upserts cannot overwrite classification or lineage. An archived Event with `Merged Into Event ID` remains terminal, while an ordinary rule/staleness archive reopens to `待处理` when active eventization identifies it again as a current candidate.
   When Entity Catalog correction changes the entities of a stable Event ID, the current `Primary Entity IDs` and active relations must reflect the corrected entities. Obsolete Event Entity rows are retained for audit but marked `Role=superseded`, `Match Method=catalog_reconciliation` and `Confidence=0`; they must not be interpreted as current participants.
6. Store six component scores in `[0,1]`; code recomputes the PRD weighted total and rejects invalid model output.
7. Mark Earnings, Market Expansion, Product Launch, M&A/Strategic Partnership/Funding, major Regulatory and Ops Incident events for critical review independently of score. A concrete financing action such as a named funding round, `raises/raised` amount or `secures funding` is `Strategic_MA` even if the stated use of proceeds mentions expansion; valuation-only commentary without a financing transaction remains `Market_Context`.
8. Use `Market_Context` only for valuation commentary, company profiles, industry comparisons, strategic narratives and non-transactional initiatives that do not describe a concrete launch, deal, regulatory action or incident. It is always non-critical and cannot raise a Strategic/P0 Candidate flag.
9. Payment-network geographic rollout wording such as `expands to <country>` or `goes global` with a named destination is `Market_Expansion`; differently worded coverage of the same entity/destination/date must merge. A local merchant adoption anecdote that describes convenience but no new rollout, product, deal or policy is `Market_Context`, not a critical launch.
10. A partner certification/specialization program is `Channel_Partner`, even when the headline uses “launches”; it is not a major `Product_Launch` and cannot become Strategic/P0 Candidate solely from that verb. Official listing CTA suffixes such as `view`, `view more`, `read more` or `learn more` are removed from retained titles.
11. A named definitive acquisition agreement with buyer, target and transaction value is `Strategic_MA` and must prefer the target/buyer official announcement. Later shareholder-law-firm “fair price” alerts are supporting/duplicate noise, not a new strategic Event. HKMA wording that calls on banks and announces a multi-point cross-border-currency strategy is `Regulatory`. Major Voice AI builders such as xAI/Grok are tracked under `GBSS_Service` so concrete agent-builder launches are not lost merely because they are not legacy contact-center vendors.
12. Named CEO/CFO/CPO appointments, departures or interim replacements are `Leadership_Change`. They are specifically typed and remain reviewable, but are non-critical by default and cannot become Strategic/P0 Candidate without a separate transaction, regulatory or incident trigger.

Critical scan runs at 01:00, 05:00, 09:00, 13:00, 17:00 and 21:00. The full daily ingest remains at 02:00.

Critical-scan immediacy never treats an undated official-listing link as fresh. After article extraction, every new critical candidate is date-gated again against `critical_scan_lookback_days`; an out-of-window or still-missing Publish Date is excluded from News writes and alerts. Such links may still be discovered later by the full ingest and its publish-date reconciliation, but they cannot create a same-day Strategic/P0 Candidate alert without publication-time evidence.

## 6. Cost, resilience and audit

- Caps: ingest `$0.30`, insight `$1.50`, daily `$1.00`, weekly `$5.00`, monthly `$25.00`.
- Preflight tokens use conservative UTF-8 byte estimation plus configured maximum output; actual usage comes from the API response.
- Retry only 408/409/429/5xx, at most three attempts with exponential jitter. Validation, authentication and budget errors are not retried.
- DingTalk AI Table access separately retries transient HTTP/transport failures and DingTalk remote-timeout responses with bounded exponential backoff. A successfully resolved operator union ID is cached for the current process so a multi-table workflow does not repeat the fragile operator lookup. Retries never cover validation/authentication errors and never turn a failed write into an assumed success.
- A DingTalk custom-robot webhook is considered delivered only when both HTTP transport succeeds and the JSON response body has no non-zero `errcode`. HTTP 200 with a robot-level rejection is recorded as failed with the returned error body; it must never produce a successful RunLog/Audit delivery record.
- The circuit opens for 15 minutes after five consecutive retryable failures or at least half of the latest ten calls fail.
- Every completed, failed or skipped logical call creates API Usage and Audit Trail records. If DingTalk audit writing fails, the payload is retained in `job_runs.metadata.pending_audit_events` and flushed by health check.
- Webhook URLs and all provider keys live in SecretStore/environment only and are always masked in settings exports.

## 7. Daily report, weekly insight and rollback behavior

`weekly_input_mode=event_cases` is the legacy-compatible input switch used by both Daily Report and Weekly Insight. Daily Report runs every day at 12:00 and selects unsent Event Cases backed by at least one live `News=已采纳` source. Every item displays business line, event type, title, source link and source Publish Date. The chat-facing Daily Report omits Event / Event Source / Evidence / Claim internal IDs for mobile readability; the complete lineage remains in DingTalk business tables, sent-marker relations and Audit Trail. Delivery to `AI_Intelligence` has an empty DingTalk `at` payload and never mentions a reviewer. The 12:00 delivery creates a one-hour human-check window before the owner manually forwards it to another internal group at 13:00; the system never performs that forwarding. It reads News status directly rather than trusting a cached Event counter. During the News-to-Event transition, an Event is also treated as already delivered when any accepted linked News row carries the relevant legacy sent marker. Adding another source is not a material Event update and cannot trigger a duplicate management report; a future resend requires an explicit material Event version policy. Pending Evidence/Claims do not block the factual Daily Report or a bounded Signal Brief; Verified Evidence and Approved Claims remain mandatory for evidence-backed strategic conclusions and Deep Research. After successful delivery it writes `Daily Report Sent At` to Event Cases and accepted linked News rows. Weekly Insight keeps its independent weekly schedule and `Weekly Intelligence Sent At` marker. A runtime failure does not fall back.

Daily Report is never silent: after a successful deadline guard, zero selected items sends a concise no-mention heartbeat stating that there are no newly accepted external events today. It writes no News/Event sent markers. A failed guard, read or webhook is still a failed run and must not be disguised as an empty-day heartbeat.

Rollback is non-destructive: set `weekly_input_mode=news`, disable critical/event feature flags and uninstall only the new critical-scan launchd job. New sheets and fields remain for diagnosis and later re-enable.

## 8. Acceptance thresholds

- Event clustering precision and recall: `>= 0.90`.
- Business-line accuracy: `>= 0.90`; event-type accuracy: `>= 0.85`.
- Critical-event golden-set recall: `1.00`; automatic final-P0 violations: `0`.
- Published lineage completeness and budget-gate compliance: `1.00`.
- Existing regression suite, adapter mocks, dry-runs, read-only workspace/table checks and manual One Pager review all pass before cutover.

## 9. Operating observation

The KPI snapshot uses `Asia/Kuala_Lumpur` and reports candidate lineage, Event Cases awaiting News review, zero automatic final-P0 violations, rolling 28-day API cost, weekly throughput and the previous day's review workload. Review workload includes batch size, completed/pending rows and AI-aligned/overridden decisions. Until a true review-session timer exists, `estimated_review_minutes` is explicitly calculated as 15 seconds per aligned decision, 60 seconds per override and 45 seconds per unfinished row. It must remain labelled as an estimate; the `<=10 minutes` product outcome requires at least one manually timed sample each week and cannot be declared met from the estimate alone. The CLI report remains read-only. The scheduled live daily health check stores the complete snapshot in both local RunLog metadata and DingTalk Audit Trail (`HEALTH.v3_1_kpi`); dry-runs are marked as such and do not count as production observation evidence. No additional business table is introduced. The initial `10-30` linked signals and `5-10` Event Cases per week are operating bands for calibration, not substitutes for the PRD accuracy gates. A weekly Event is counted only when a linked News row was first seen in the same window, excluding historical backfills.

Actual review time is recorded through `record_review_timing.py` as a manual timed sample in the existing local RunLog and DingTalk Audit Trail; it creates no new business table. Each sample includes review date, elapsed minutes, reviewed row count, target status, notes and recorded timestamp. DingTalk `lastModifiedTime` is not accepted as actual review duration because automated Event/AI writes also update it and may use the same operator identity.

Four-week success remains `observation_incomplete` until at least 28 calendar days have elapsed since the first successful production critical scan. Pre-observation critical backfills remain visible but do not count toward the production detection SLA. Source Publish Date is currently date-only, so the KPI labels publish-to-Event lag accordingly; the four-hour critical-scan SLA is proven from scheduler/job-run timestamps or a controlled fixture.
