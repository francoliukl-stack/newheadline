# newheadline

Local settings center for the high-signal industry headline workflow described in `prd.md`.

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

## Test

```bash
python3 -m unittest discover -s tests
```

## Release Evaluation

Before shipping a new feature, run the release evaluation set in `evals/release_evaluation_set.md`.
The structured cases live in `evals/release_evaluation_set.json` and cover the PRD-critical workflow:
provider fallback, News ingestion, accepted-only daily/weekly publishing, research evidence and claims, Insights storage,
DingTalk routing, report rendering, and launchd schedule persistence.

## Notes

- Normal settings are stored in `data/settings.sqlite3`.
- Sensitive values are stored in macOS Keychain when available, with a local `data/secrets.json` fallback using `0600` permissions.
- Scheduler installation targets macOS `launchd`. Daily runs check provider health, collect headlines, write new URLs to DingTalk AI Table, backfill publish dates, and mark semantic duplicates. Daily News Review reminders send the pending-review count only to reviewers. Sunday 11:00 `Weekly Headlines` sends management the accepted-news digest and writes `Weekly Headlines Sent At`; it contains no research analysis. Friday 09:00 creates the next weekly OpenAI Deep Research proposal without calling a paid API. Saturday 14:00 can run Deep Research only after explicit approval; otherwise it exits without a paid call. Saturday noon Weekly Intelligence draft prepares the analysis report without marking records sent. Sunday noon `GBSS Weekly AI & Service Intelligence` sends the independent management analysis report and writes `Weekly Intelligence Sent At`.
- Provider health checks alert DingTalk when an active search provider is unavailable. Daily health checks alert DingTalk only when an operational check fails. A working fallback provider can keep the daily collection running.
- Search is configured through a provider abstraction so unattended runs do not depend on Codex. Supported configuration targets are GDELT DOC API, ChatGPT Web, Gemini Web, SerpAPI, Bing Web Search, Serpstack, OpenClaw cache, manual seed files, and Codex Search.
- `gdelt_doc` is the free experimental unattended live-search provider. It uses the public GDELT DOC API without a browser session or API key, but the public endpoint can rate limit requests.
- `serpapi` is the implemented unattended production option when an API key is configured. It queries Google News and returns direct structured results.
- `brave_search` is the implemented unattended Brave News Search API option. It requires an API key and benefits from Brave's monthly free credits.
- `codex_search` is an interactive supplement: a Codex session refreshes `data/codex-search-results.json`, then the normal `INGEST` pipeline writes those results to `News` with `Search Provider = codex_search`. It is not a detached overnight search adapter.
- `News` stores source headlines and review state only. Weekly GBSS insight drafts and final analysis reports are stored separately in the `Insights` sheet, with source News record IDs retained for traceability.
- `Config` stores workflow configuration values for review and adjustment, including Daily News Review, Weekly Headlines, Weekly Intelligence schedules, source/output sheet IDs, item limits, and report prompts.
- `Detect Sources` stores the companies, competitor benchmarks, topics, aliases, and source domains used to build the daily collection query. Maintain this sheet when adding, disabling, or reprioritizing targets to watch.
- `Research Topics` stores the rolling research roadmap: one locked topic for the weekly pulse plus the next four planned topics. Weekly reports read this sheet so management sees both the current deep-dive and the forward research direction.
- `Research Queue`, `Evidence Bank`, `Claim Ledger` and `Research Results` are the weekly research control plane. `Research Results` holds each provider-generated external research output: the full Markdown in `Research Content`, provider/model/response metadata, source/evidence IDs, a local artifact path and the DingTalk document link. `Research Queue` retains the result record ID and document URL for the weekly topic. This keeps full external research separate from `News`, `Insights` and the one-page brief.
- `Audit Trail` is an append-only DingTalk AI Table sheet for workflow and step-level lineage. It links each run to its inputs, outputs, source record IDs, report/document artifacts, delivery result, errors and machine-readable metadata. Run `./.venv/bin/python scripts/ensure_audit_trail.py` once to create or validate the sheet.

## GBSS Weekly AI & Service Intelligence

The weekly report workflow now produces `GBSS Weekly AI & Service Intelligence` for Ant International GBSS management and AI Enablement review. It is no longer a generic AI/news digest. The report converts accepted `News` rows into a GBSS-facing strategy brief covering:

- `Business Support`: ePOS / Antom / WorldFirst / General GBSS Ops.
- `Organization Transformation`: AI impact on service, QA, training and operations roles.
- `OPC & Operating Model`: One Person Company-style small operating units, 1-3 person ownership, human + AI workforce and A2A readiness.
- `Internal Efficiency`: AICC, AIQC, Voice AI, Service Automation and Process Optimization.
- `Contact Center Insight`: CCaaS, Agent Assist, Voice AI, WEM, conversation intelligence and AI-native orchestration.
- `Governance & Vendor Strategy`: AI governance, compliance, authorization, auditability, supplier capability and procurement model.

The full text report has five fixed sections:

1. `Executive Summary / 本周关键结论与主题判断`
2. `External Signal Radar / 外部动态雷达`
3. `Priority News Cards / 本周重点动态卡片`
4. `GBSS Impact Analysis / GBSS 影响分析`
5. `Watchlist & Deep Dive / 下周观察与深度分析`

The image report is a mobile-first `One-page Brief`, generated from the same report data. It is designed for DingTalk group sync, management review, forwarding, and quick scanning. It contains Weekly Theme, Business & Signal Radar, Top Priorities, GBSS Strategic Impact, Weekly Deep Insight and QR access to the full report / controlled group.

Weekly group delivery is image-only. If image upload or robot delivery fails, the workflow records a failed delivery in `Insights` and `Audit Trail`; it does not fall back to a text message.

Implementation note: this repository's production path is Python + Markdown + SVG/PNG + DingTalk Docs, not a React/Vite frontend. The data contract, scoring model, full report, and one-page rendering are implemented in `app/gbss_report.py`, `app/publish_format.py`, and `app/report_visual.py` so the existing scheduler, DingTalk push, Insights storage, and DWS document workflow keep working. A React/Tailwind renderer can be added later against the same `build_report_data(...)` output if needed.

### Scoring Model

Weekly priority is calculated from seven dimensions:

| Dimension | Weight |
| --- | --- |
| Business Criticality | 25% |
| GBSS Strategic Relevance | 20% |
| Contact Center Relevance | 15% |
| Actionability | 15% |
| Operating Model Impact | 10% |
| Risk / Compliance Impact | 10% |
| Industry Signal Strength | 5% |

Priority rules:

| Score | Priority | Meaning |
| --- | --- | --- |
| 85+ | P0 | Needs immediate management attention |
| 70-84 | P1 | Should enter research, PoC, benchmarking, or process optimization |
| 50-69 | P2 | Keep observing |
| <50 | Watch | Record trend only |

### Weekly Generation Flow

Monday to Wednesday: collect news signals around AI Agent, Payment, Voice AI, Contact Center, AIQA / AIQC, Risk & Compliance, Merchant Ops, OPC Model, A2A readiness, and Vendor Strategy. Each source row should keep title, URL, publish date, company/domain, section, and review status.

Thursday: classify signals, calculate P0 / P1 / P2 / Watch, select 3-5 Priority News Cards, generate GBSS Impact Analysis, and choose the Weekly Deep Dive. Review coverage against Business Support, Contact Center Insight, OPC Model, Organization Transformation, Internal Efficiency, and Governance / Vendor Strategy.

Before rendering a strategic Deep Dive, prepare `Research Queue` and `Evidence Bank` with:

```bash
.venv/bin/python scripts/prepare_weekly_research.py --recent-count 5
```

Only evidence marked `Verified` and claims marked `Approved` can pass the Deep Research gate: at least six verified evidence records, including three T1/T2 sources, at least three approved claims, and a boundary/counter-evidence statement on at least one approved claim. Until then, the report is labelled `Signal Brief` and can only make bounded monitoring statements. Import a model-assisted synthesis through the reviewed JSON contract:

```bash
.venv/bin/python scripts/import_deep_research_synthesis.py synthesis.json --research-id research-...
```

OpenAI / ChatGPT Deep Research runs through the same result layer after approval. It creates a DingTalk research document and writes the complete external report to `Research Results.Research Content`:

```bash
.venv/bin/python scripts/run_openai_deep_research.py --recent-count 5 --approve
```

Gemini can use the same `Research Results` contract once its provider adapter and API key are configured; the downstream AI Table fields, document link and audit lineage remain unchanged.

Friday or scheduled review time: generate the full text report and One-page Brief, review action owners and timelines, then use the One-page Brief for group sync or management meeting discussion. Full documents are stored in DingTalk Docs/DWS and linked back into `Insights`.

### OpenAI Deep Research Approval

Every OpenAI Deep Research run is approval-gated because it can incur API cost. The Friday 09:00 job creates a plan in `Research Queue` from accepted News only: the period, topic, question, selected source count and candidate headlines. It sets `Approval Status` to `Pending Approval` and does not call OpenAI. Only after the plan has been explicitly approved may the Saturday 14:00 job call the Deep Research API. Without approval, it records a skipped run and exits safely. Completed output stores the response ID and 5-10 concise Deep Insight phrases in `Research Queue`, and is included in the weekly report.

Interactive Codex results can be staged with:

```bash
python scripts/import_codex_search_results.py results.json
```

## Workflow Names

| Name | Code | Purpose |
| --- | --- | --- |
| 采编 | `INGEST` | Check providers, collect headlines, write new URLs, backfill publish dates, and merge semantic duplicates |
| 催审 | `REVIEW` | Remind the user to review pending records |
| Daily News Review | `REVIEW` | Remind reviewers about pending News; it does not publish management content |
| Weekly Headlines | `PUBLISH` | Send the Sunday 11:00 management digest, then write back `Weekly Headlines Sent At` |
| Weekly Intelligence 草稿 | `REVIEW` | Prepare the Saturday noon `GBSS Weekly AI & Service Intelligence` draft without writeback |
| Weekly Intelligence | `PUBLISH` | Publish the Sunday noon management analysis report, then write back `Weekly Intelligence Sent At` |
