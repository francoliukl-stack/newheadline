# Weekly Headlines Settings

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
- Scheduler installation targets macOS `launchd` and points at the placeholder task scripts in `scripts/`.
