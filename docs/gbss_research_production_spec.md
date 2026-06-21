# GBSS Research Production Specification

**Status:** Implemented foundation; evidence-gated report path
**Date:** 2026-06-20
**Applies to:** `GBSS Weekly AI & Service Intelligence`
**Implementation rule:** A weekly report may use `Deep Research` only when the evidence and claim gates in this specification pass. Otherwise it is explicitly labelled `Signal Brief`.

## 1. Purpose

Convert the weekly output from a news-driven template into an evidence-driven strategic research product for GBSS leadership. The external push remains one mobile-readable image per week. The full DingTalk document remains the evidence-backed detail layer reached by QR code.

## 2. Product Contract

### Inputs

- Accepted `News` signals collected during the reporting period.
- One locked weekly topic and its research question from `Research Queue`.
- A curated, frozen `Evidence Pack` containing source material relevant to that topic.
- Existing GBSS strategic context: Merchant Service / ePOS, Antom, WorldFirst, General GBSS Ops, OPC Model, AICC, AIQC, Voice AI, Contact Center and governance.

### Outputs

- A CEO-ready One-page Brief image, optimized for mobile reading and sent as the only group message.
- A full DingTalk research document with citations/source IDs and a QR destination.
- Structured report data in `Insights`, including source News IDs, evidence IDs, claim IDs, quality results and publish status.

### Non-goals

- Do not treat every weekly signal as a Deep Dive candidate.
- Do not manufacture recommendations, P0 labels, metrics or company-specific impacts when evidence is weak.
- Do not expose research-process tables in the CEO image.
- Do not send a second text message to the group.

## 3. Required Data Model

### 3.1 News (existing signal pool)

Retains candidate events. Required fields remain: title, source URL, source, publish date, review status, discovery metadata and send markers.

New optional fields:

| Field | Meaning |
| --- | --- |
| Research Candidate | `Yes/No`; eligible for topical research |
| Initial Relevance | Initial GBSS mapping; never treated as final analytical judgement |
| Source Tier | Preliminary source quality classification |
| Research Notes | Human annotation or question to verify |

### 3.2 Research Queue (new)

One active topic per weekly report.

| Field | Requirement |
| --- | --- |
| Research ID | Stable identifier, e.g. `research-2026-W26` |
| Topic | Specific, decision-relevant topic |
| Primary Question | One answerable management question |
| Sub-questions | Maximum three |
| Hypothesis | Optional, explicitly labelled hypothesis |
| Priority Entities | Companies, regulators or benchmarks to research |
| GBSS Scope | Relevant businesses/capabilities |
| Research Status | Planned / Locked / Collecting / Evidence Frozen / Drafted / Approved / Published |
| Evidence Freeze At | Cutoff timestamp |
| Owner | Research owner |

### 3.3 Evidence Bank (new)

One row is one usable piece of evidence, not one vague article summary.

| Field | Requirement |
| --- | --- |
| Evidence ID | Stable identifier |
| Research ID | Parent topic |
| Source URL / Title / Publisher / Published Date | Mandatory |
| Source Tier | `T1`, `T2` or `T3` |
| Source Type | Company, filing, regulator, earnings call, product doc, credible media, analyst, vendor, etc. |
| Extracted Fact | Atomic statement directly supported by the source |
| Metric | Exact metric, currency/unit and period where present |
| Relevance | Business/capability mapping |
| Supports / Challenges | Claim IDs or hypotheses it supports/challenges |
| Confidence | High / Medium / Low |
| Reviewer Status | Pending / Verified / Rejected |

Source tiers:

- `T1`: company announcement, product documentation, financial filing/earnings call, regulator, official partner announcement or verified customer case.
- `T2`: reputable independent reporting or research that identifies its sources.
- `T3`: vendor marketing, funding database, blog or unverified secondary material. T3 may discover a lead but cannot independently support P0 or a material management claim.

### 3.4 Claim Ledger (new)

Every material statement in the final report must be represented here.

| Field | Requirement |
| --- | --- |
| Claim ID | Stable identifier |
| Research ID | Parent topic |
| Claim Text | Concise statement used in report |
| Claim Type | `Fact`, `Inference`, `Hypothesis` |
| Evidence IDs | One or more supporting evidence IDs |
| Counter-evidence / Boundary | Required for material inference |
| GBSS Relevance | Specific business/capability or `No direct relevance` |
| Confidence | High / Medium / Low |
| Report Placement | Key Takeaway, priority card, impact, Deep Dive, or excluded |
| Reviewer Status | Draft / Verified / Approved / Rejected |

### 3.5 Audit Trail (new)

`Audit Trail` is the append-only operational lineage for the system. It is separate from `News`, research tables and `Insights`, and is required for both process review and research-quality improvement.

Each event records: Audit Event ID, Run ID, workflow, stage code/name, status, live/dry-run mode, timestamps, duration, input/output summary, result count, related sheet, source record IDs, report ID, artifact URL/path, error and metadata JSON.

Required coverage:

- Daily ingest: start, provider result collection, provider health, News write, title refresh, publish-date backfill, semantic dedupe and completion/failure.
- Daily operations: health checks, pending-review count, notification, daily selection, rendering, DingTalk delivery and writeback.
- Weekly draft/final: source selection, topic sync, report rendering, full-document creation, image creation, permissions, Insights persistence, image delivery, weekly writeback and completion/failure.
- Research vNext: topic lock, retrieval plan, each evidence verification result, claim approval/rejection, quality-gate result and report approval.

Audit storage is best-effort: inability to write the audit table must be captured in local RunLog metadata but must not prevent a scheduled business workflow from completing. A final report may not be marked audit-complete unless its core workflow events were persisted.

## 4. Weekly Operating Workflow

Only image messages are distributed to DingTalk groups. A draft image may be sent to the review/operations group; the final image is sent to the intended publication group. No text-version group message is sent. The following work is otherwise internal.

1. **Saturday topic selection:** lock one Research Queue item for the following report cycle, with one primary question and source plan.
2. **Monday to Wednesday signal collection:** collect broad signals into `News`; reviewers mark research candidates without converting them into conclusions.
3. **Thursday evidence build:** retrieve and extract T1/T2 evidence for the locked topic. Build an Evidence Pack with a minimum of six verified items for a Deep Dive.
4. **Friday Deep Research synthesis:** generate a fact table, competing explanations, claim ledger and report draft from the frozen Evidence Pack only.
5. **Saturday quality gate:** validate source coverage, P0 eligibility, claim traceability, bilingual completeness and mobile layout.
6. **Sunday finalization:** create the full document and One-page Brief from the approved report data; send the image only and archive all identifiers in `Insights`.

## 5. Research and Model Contract

### 5.1 Retrieval plan

For each topic, generate 6-10 targeted queries covering:

- direct company/product/financial events;
- sector benchmarks and customer deployments;
- risk, regulatory or governance constraints where relevant;
- counter-evidence or failed/limited deployment cases.

Topic selection must drive those queries. A generic Detect Sources query alone is insufficient.

### 5.2 Evidence extraction

The research stage must produce structured facts, not prose-only summaries. It must preserve original source URL, published date, company/entity, figures and the exact scope of any claimed deployment or capability.

### 5.3 Deep Research synthesis prompt contract

The model receives only the locked research question, GBSS context and verified Evidence Pack. It must:

1. Separate facts from inferences and hypotheses.
2. Cite evidence IDs next to every material statement.
3. State uncertainty, missing data and counterarguments.
4. Map relevance separately to Merchant Service / ePOS, Antom, WorldFirst and General GBSS Ops; `No direct relevance` is a valid result.
5. Produce no P0, action, metric or company-specific impact not supported by the evidence.
6. Return structured JSON conforming to the report schema before any Markdown, document or image is rendered.

### 5.4 Editorial rules

- Every priority card states `What changed`, `Evidence`, `Why it matters`, `GBSS relevance`, `Confidence`, and `Source`.
- Use direct, decision-oriented language. Avoid generic wording such as “may improve” unless explicitly labelled as a hypothesis.
- English precedes Chinese for management-facing content. Both languages are mandatory for each visible major section.
- The Deep Dive may conclude that the current evidence is insufficient. This is preferable to a confident but unsupported claim.

## 6. Priority Rules

### P0 gate

P0 requires all of the following:

1. Confirmed event with date and source;
2. At least one verified T1 source;
3. Material, specific GBSS impact on business support, risk, budget, organization or operating model;
4. A management decision, risk response or resource choice likely within 30 days;
5. An approved Claim Ledger entry with High or Medium confidence.

If any condition fails, the item cannot be P0. A weekly report may legitimately have zero P0 items. The system must never insert a synthetic P0 item from a generic impact template.

### P1, P2 and Watch

- `P1`: evidence-backed topic worth benchmark, research, PoC design or capability assessment.
- `P2`: relevant trend requiring observation but no near-term research action.
- `Watch`: weak or early signal; retain in the signal pool only.

## 7. Report Contract

### 7.1 One-page Brief

The image contains only:

1. Weekly theme and management takeaway.
2. Signal radar with actual counts.
3. Up to three evidence-backed priority events with publish dates.
4. Up to four GBSS strategic implications, each linked to an approved claim.
5. One Weekly Deep Insight: `Insight`, `Why now`, `What to monitor next`.
6. Two QR codes: full report and group-access route.

No static action list, no synthetic P0, no ellipsis used to conceal missing text, and no unfilled layout area created by fixed-height placeholders.

### 7.2 Full research document

The document contains the same executive conclusion plus:

- evidence table with source IDs and links;
- priority cards with fact/inference/confidence;
- GBSS impact analysis that cites claim IDs;
- a Deep Dive with background, evidence, competing explanations, risks, opportunities and unresolved questions;
- source note and method statement.

## 8. Quality Gates

The report cannot publish as final unless all applicable gates pass:

| Gate | Pass criterion |
| --- | --- |
| Traceability | 100% of priority cards have source URL and publish date |
| P0 integrity | 100% of P0s meet all five P0 conditions |
| Deep Dive evidence | At least six verified evidence items and at least three T1/T2 items |
| Claim integrity | 100% of material conclusions map to Claim Ledger evidence IDs |
| No template fabrication | No static impact, action, Deep Dive or synthetic P0 is inserted |
| Language | All visible management-facing sections contain English then Chinese |
| Relevance | Each mapped business relevance is specific or explicitly `No direct relevance` |
| Layout | One-page image is rendered and visually checked on mobile dimensions without clipping/ellipsis |

If the Deep Dive evidence gate fails, the report may publish only as a `Signal Brief`, with the missing evidence explicitly disclosed. It may not claim to be a Deep Research report.

## 9. Implementation Plan and Acceptance

### Phase 1: Integrity correction

- Remove static Impact Analysis, actions, watchlist and Deep Dive content from the generated report path.
- Remove automatic insertion of P0 strategy rows into Top Priorities.
- Preserve actual source dates and show `P0 = 0` when applicable.

**Acceptance:** no report field can present a material conclusion without a linked News/Evidence record; no generated Top Priority has a synthetic date.

### Phase 2: Research data layer

- Create and synchronize `Research Queue`, `Evidence Bank` and `Claim Ledger` sheets.
- Extend `Insights` with research/evidence/claim references and quality-gate status.
- Make the locked topic generate retrieval plans and candidate-source requirements.

**Acceptance:** a researcher can trace any final claim to a source and see its review state.

### Phase 3: Deep Research orchestration

- Implement structured retrieval, evidence extraction, verification workflow and JSON-first synthesis.
- Require the model to use only the frozen Evidence Pack for report conclusions.
- Add review states and human approval before final publish.

**Acceptance:** a sample weekly Deep Dive passes all quality gates and is materially different when the underlying evidence changes.

### Phase 4: Rendering and release evaluation

- Render One-page and full document only from approved structured report data.
- Add automated and manual release-evaluation cases for evidence coverage, P0 integrity, claim traceability and mobile visual QA.

**Acceptance:** one controlled end-to-end run generates a traceable report, passes the quality gate and sends image-only to the intended DingTalk group.

## 10. Migration and Compatibility

- Existing `News`, `Insights`, `Config` and `Research Topics` records remain valid and are not rewritten destructively.
- Current daily headline workflow remains signal-based and accepted-only.
- The existing weekly template can remain available as an internal `Signal Brief` fallback while vNext research data is incomplete.
- The new final-report path activates only after a controlled trial and the release evaluation set is extended and passed.

## 11. Current Implementation Boundary

The implemented evidence-production foundation consists of:

- `Research Queue`: one locked weekly question, decision context, evidence plan and scope.
- `Evidence Bank`: atomic source evidence, tier, extracted fact, metric, boundary, reviewer state and source News lineage.
- `Claim Ledger`: fact, inference and hypothesis statements with evidence IDs, confidence, boundary and reviewer approval.
- `Research Results`: one row per provider-generated external research result. The complete Markdown is stored in `Research Content`; provider/model/response metadata, source/evidence IDs, local artifact and DingTalk document link are stored beside it.
- `prepare_weekly_research.py`: seeds research and candidate evidence from accepted `News` records, without treating a headline as verified evidence.
- `import_deep_research_synthesis.py`: imports a structured synthesis only when every claim cites known evidence and every inference contains a counter-evidence or boundary statement. Imported claims remain `Draft` until a reviewer approves them.
- Weekly draft/final renderers: use research context from the same tables. They render `Signal Brief` until the gate passes, and never fabricate P0 urgency or a strategic conclusion from unreviewed inputs.

The implementation deliberately does not call an external LLM or browsing provider on its own. A model-backed Deep Research worker can be connected later through the structured synthesis payload below, while keeping the human approval and audit controls unchanged.

## 12. Structured Synthesis Contract

The Deep Research worker must return JSON with the following minimum shape:

```json
{
  "research_id": "research-...",
  "claims": [
    {
      "claim_type": "Fact | Inference | Hypothesis",
      "claim_text": "A bounded, decision-relevant statement.",
      "evidence_ids": ["evidence-..."],
      "counter_evidence_or_boundary": "Required for Inference; recommended otherwise.",
      "gbss_relevance": "Specific impact and scope.",
      "strategic_theme": "One of the six GBSS strategic themes.",
      "confidence": "High | Medium | Low",
      "report_placement": "Signal Radar | Priority Card | Impact Analysis | Deep Dive"
    }
  ]
}
```

Validation rejects an incorrect `research_id`, unknown evidence IDs, empty claims, invalid claim type/confidence, or any inference without a boundary. Reviewer approval is still required before those claims can be rendered as Deep Research.
