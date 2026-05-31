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

## Notes

- Normal settings are stored in `data/settings.sqlite3`.
- Sensitive values are stored in macOS Keychain when available, with a local `data/secrets.json` fallback using `0600` permissions.
- Scheduler installation targets macOS `launchd`. Daily runs check provider health, collect headlines, write new URLs to DingTalk AI Table, backfill publish dates, and mark semantic duplicates. Reminder runs send the pending-review count. Weekly runs publish accepted unsent headlines and write back the sent state.
- Provider health checks alert DingTalk when an active search provider is unavailable. A working fallback provider can keep the daily collection running.
- Search is configured through a provider abstraction so unattended runs do not depend on Codex. Supported configuration targets are GDELT DOC API, ChatGPT Web, Gemini Web, SerpAPI, Bing Web Search, Serpstack, OpenClaw cache, manual seed files, and Codex Search.
- `gdelt_doc` is the free experimental unattended live-search provider. It uses the public GDELT DOC API without a browser session or API key, but the public endpoint can rate limit requests.
- `serpapi` is the implemented unattended production option when an API key is configured. It queries Google News and returns direct structured results.
- `brave_search` is the implemented unattended Brave News Search API option. It requires an API key and benefits from Brave's monthly free credits.
- `codex_search` is an interactive supplement: a Codex session refreshes `data/codex-search-results.json`, then the normal `INGEST` pipeline writes those results to `News` with `Search Provider = codex_search`. It is not a detached overnight search adapter.

Interactive Codex results can be staged with:

```bash
python scripts/import_codex_search_results.py results.json
```

## Workflow Names

| Name | Code | Purpose |
| --- | --- | --- |
| 采编 | `INGEST` | Check providers, collect headlines, write new URLs, backfill publish dates, and merge semantic duplicates |
| 催审 | `REVIEW` | Remind the user to review pending records |
| 出刊 | `PUBLISH` | Publish accepted unsent weekly headlines, then write back the sent state and sent date |
