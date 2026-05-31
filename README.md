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
- Search is configured through a provider abstraction so unattended runs do not depend on Codex. Supported configuration targets are ChatGPT Web, Gemini Web, SerpAPI, Bing Web Search, Serpstack, OpenClaw cache, and manual seed files.

## Workflow Names

| Name | Code | Purpose |
| --- | --- | --- |
| 采编 | `INGEST` | Check providers, collect headlines, write new URLs, backfill publish dates, and merge semantic duplicates |
| 催审 | `REVIEW` | Remind the user to review pending records |
| 出刊 | `PUBLISH` | Publish accepted unsent weekly headlines, then write back the sent state and sent date |
