# News Source P0 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair trusted-source recall, lane integrity, News lineage persistence, URL dedupe identity, and UnionPay/UPI ambiguity without changing review policy.

**Architecture:** Keep provider queries simple and move trust enforcement to a deterministic post-query boundary. Introduce one shared URL identity module and use it at every ingest and dedupe boundary. Persist existing discovery metadata into News and apply one narrow schema migration.

**Tech Stack:** Python 3, unittest, DingTalk AI Table, existing Brave/GDELT/Marketaux provider adapters.

## Global Constraints

- Do not run live AI Review or change human final statuses.
- Preserve non-tracking URL query parameters.
- Downgrade untrusted results from trusted queries; do not discard them.
- Use `News / oMbefcK`, not `Daily Headlines Review`.
- Write tests before production changes and verify each red-green cycle.

---

### Task 1: Trusted query shape and Lane validation

**Files:**
- Modify: `tests/test_settings.py`
- Modify: `app/detect_sources.py`
- Modify: `scripts/daily_fetch.py`

**Interfaces:**
- Consumes: `build_detect_query_plan(records)`, `trusted_source_domains(records)`
- Produces: `validate_candidate_lanes(records, trusted_domains) -> List[Dict[str, Any]]`

- [ ] Write failing tests asserting trusted queries contain only simple `site:` OR clauses and that non-trusted results are downgraded to `broad_market`.
- [ ] Run the exact tests and confirm failures are caused by the current topic suffix and missing validator.
- [ ] Remove the trusted-query topic suffix and implement `validate_candidate_lanes`.
- [ ] Apply validation after candidate URL dedupe and before balanced selection/counting.
- [ ] Run the exact tests to green.

### Task 2: Shared URL identity and dedupe boundaries

**Files:**
- Create: `app/url_identity.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_news_coverage.py`
- Modify: `app/editorial_intake.py`
- Modify: `app/dingtalk_ai_table.py`
- Modify: `app/dedupe.py`
- Modify: `app/event_intelligence.py`
- Modify: `scripts/daily_fetch.py`
- Modify: `scripts/push_dingtalk_ai_table.py`

**Interfaces:**
- Produces: `canonical_article_url(value, strip_www=True) -> str`
- Produces: `article_url_identity(value) -> str`

- [ ] Write failing tests for `www`, tracking parameters, fragments, trailing slash, and preserved `id` parameters.
- [ ] Write failing duplicate tests proving automatic and editorial variants collapse to one identity.
- [ ] Run exact tests and confirm expected failures.
- [ ] Implement the shared URL functions.
- [ ] Replace raw URL equality at candidate, News push, editorial, semantic dedupe, and event hash boundaries.
- [ ] Run exact tests to green.

### Task 3: Persist Source Lane and Search Group

**Files:**
- Modify: `tests/test_settings.py`
- Modify: `app/dingtalk_ai_table.py`
- Modify: `app/event_tables.py`

**Interfaces:**
- Consumes: daily result keys `Source Lane`, `Search Group`
- Produces: corresponding News fields

- [ ] Add a failing normalization test for both fields.
- [ ] Run it and confirm the fields are missing.
- [ ] Add both fields to `normalize_news_record`; add `Search Group` to `NEWS_LINEAGE_FIELDS`.
- [ ] Run the exact test to green.

### Task 4: UnionPay/UPI source disambiguation

**Files:**
- Modify: `tests/test_settings.py`
- Modify: `app/detect_sources.py`

**Interfaces:**
- Produces: UnionPay Detect Source with no `UPI` alias

- [ ] Add a failing test asserting the UnionPay company query excludes bare `UPI` while India UPI remains in Entity Catalog.
- [ ] Run it and confirm the static Detect Source alias causes failure.
- [ ] Remove `UPI` from the UnionPay Detect Source seed.
- [ ] Run the exact test and existing entity disambiguation tests to green.

### Task 5: Full verification and narrow production migration

**Files:**
- No additional code files.
- Production schema: add `Search Group` to `News / oMbefcK`.
- Production Detect Sources: clear the UnionPay `UPI` alias.

**Interfaces:**
- Consumes: verified code and current live table IDs
- Produces: live schema/config aligned with code

- [ ] Run all unit tests.
- [ ] Run `git diff --check`.
- [ ] Add the missing News `Search Group` field and verify it exists.
- [ ] Update only the `company-unionpay` Detect Source alias and read it back.
- [ ] Run the current query-plan replay/dry-run and verify trusted Lane purity.
- [ ] Run `daily_health_check.py --dry-run`.
- [ ] Inspect `git status --short` and report all local and production changes.
