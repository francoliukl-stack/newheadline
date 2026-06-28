# GBSS Event Intelligence v3.1 Runbook

## Safety defaults

- New installations start with `event_intelligence.enabled=false`, `critical_scan_enabled=false` and `weekly_input_mode=news`.
- Migration creates or extends DingTalk sheets only. It never deletes a sheet, field or record.
- Unit/golden evaluations never call OpenAI or an external provider.
- OpenAI classification stays disabled until a key and the API Usage sheet are configured. Approved research additionally requires `Research Queue.Approval Status=Approved`.

## Install and migrate

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/migrate_v3_1_event_intelligence.py --dry-run
.venv/bin/python scripts/migrate_v3_1_event_intelligence.py --apply
.venv/bin/python scripts/eventize_news.py --dry-run --days 14
.venv/bin/python scripts/eventize_news.py --apply --days 14
```

The migration creates `Event Cases`, `Event Entities`, `Event Sources`, `Event Scores`, `Entity Catalog`, `Alert Log` and `API Usage`, extends News/Evidence/Claim/Insights lineage, seeds the PRD entity set and writes sheet IDs to Settings/Config.

## Human review before cutover

For at least one recent Event Case:

1. Accept one linked News row.
2. Review the Event Case source, type, business line, score and limitations; set Event `Status=已采纳`.
3. Set its Event Evidence row to `Reviewer Status=Verified` after checking the source text and date.
4. Set its Event Claim row to `Reviewer Status=Approved`; retain a scope/boundary.
5. If final priority is P0, also set `P0 Approval Status=Approved`, `Reviewer` and `Reviewed At`. Automation never fills these fields.

Set `event.review_view_url` in Config to the dedicated Event Cases review view before enabling reminders; until then cards open the AI Table base instead of the historical News approval view.

## Release gate and cutover

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_v3_1_evaluation.py
.venv/bin/python scripts/migrate_v3_1_event_intelligence.py --dry-run
.venv/bin/python scripts/cutover_v3_1.py --dry-run
.venv/bin/python scripts/cutover_v3_1.py --apply
```

`cutover_v3_1.py --dry-run` reruns automated gates and the live, read-only Event/Evidence/Claim readiness check; it exits blocked without changing settings when review is incomplete. `--apply` enforces the same gates before enabling Eventize and the six-times-daily critical scan, switching Weekly inputs to Event Cases and installing only the new critical launchd task.

## Rollback

```bash
.venv/bin/python scripts/cutover_v3_1.py --rollback
```

Rollback immediately sets `weekly_input_mode=news`, disables Eventize/critical scan and removes the critical-scan launchd task. Event sheets, News lineage and audit history remain untouched.

## Provider and secret configuration

Secrets belong in the Settings UI/SecretStore or process environment. Never put values in this document, Config sheet or source control.

- OpenAI: `openai_service.api_key` or `OPENAI_API_KEY`.
- Marketaux: `event_intelligence.marketaux_api_key`.
- Firecrawl: `event_intelligence.firecrawl_api_key`.
- Alpha Vantage: `event_intelligence.alpha_vantage_api_key`.
- DingTalk review: daily webhook/signing secret and `at_mobiles` for real mentions.
- DingTalk publish: weekly webhook/signing secret.

Official, GDELT and yfinance adapters can run without commercial API keys. Marketaux, Firecrawl and Alpha Vantage remain disabled until explicitly enabled.

## Cost control

Application caps are `$0.30` per ingest call, `$1.50` per insight/research call, `$1/day`, `$5/week` and `$25/month`. Before a paid call, the service must successfully append an Audit Trail preflight event and an `API Usage` reservation row. The completion/failure row reuses the same Call ID, so append-only accounting counts the call once. Budget, circuit, audit or approval failure causes a skip/failure before provider execution. Configure the OpenAI project-level monthly budget separately as an external hard stop.

## Operations

- Full ingest: Monday–Saturday 02:00.
- Critical scan: daily 01:00, 05:00, 09:00, 13:00, 17:00 and 21:00, `Asia/Kuala_Lumpur`.
- Review reminder: `BOT监控审核群`; formal outputs: `Daily News`.
- `daily_health_check.py` marks stale local runs failed and flushes deferred Audit Trail records.
- If Event mode cannot read Event/Evidence/Claim lineage, Weekly fails closed and alerts; it does not silently use News.

## Acceptance checklist

- Seven v3.1 sheets exist and a repeated migration reports no missing fields.
- Entity Catalog includes every PRD core business, competitor, regulator and capability entity required for the pilot.
- Static evaluation thresholds pass and automatic final P0 violations remain zero.
- Event reminder reaches only the review group and contains a real webhook mention.
- Weekly Headlines, Weekly Insight and One Pager show Event, Evidence, Claim, Source URL and Publish Date lineage.
- Signal Brief is rendered whenever the independent-source/claim gate is not met.
- Rollback restores News input without deleting new data.
