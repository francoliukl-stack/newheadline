from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .models import AppSettings
from .scheduler import install_launchd, schedule_status
from .secrets import SecretStore
from .storage import SettingsStore


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
store = SettingsStore(DATA / "settings.sqlite3", SecretStore(DATA / "secrets.json"))

app = FastAPI(title="Weekly Headlines Settings", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return store.load(masked=True)


@app.put("/settings", response_model=AppSettings)
def put_settings(settings: AppSettings) -> AppSettings:
    return store.save(settings)


@app.post("/settings/reset", response_model=AppSettings)
def reset_settings() -> AppSettings:
    return store.reset()


@app.post("/settings/export")
def export_settings() -> Dict[str, Any]:
    return store.export_public()


@app.post("/settings/import", response_model=AppSettings)
def import_settings(payload: Dict[str, Any]) -> AppSettings:
    return store.save(AppSettings.model_validate(payload))


@app.post("/settings/test/chatgpt")
def test_chatgpt() -> Dict[str, Any]:
    settings = store.load(masked=False).chatgpt
    profile_path = Path(settings.browser_profile_path).expanduser() if settings.browser_profile_path else None
    return {
        "ok": bool(profile_path and profile_path.exists()),
        "message": "Browser profile found" if profile_path and profile_path.exists() else "Set an existing browser profile path first.",
    }


@app.post("/settings/test/lark")
def test_lark() -> Dict[str, Any]:
    settings = store.load(masked=False).lark
    missing = [
        name for name in ("app_id", "app_secret", "app_token", "table_id")
        if not getattr(settings, name)
    ]
    if missing:
        return {"ok": False, "message": f"Missing fields: {', '.join(missing)}"}
    return {"ok": True, "message": "Credentials are present. Full Lark API validation is reserved for the fetch/remind modules."}


@app.post("/settings/test/dingtalk")
def test_dingtalk(payload: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    settings = store.load(masked=False).dingtalk
    target = (payload or {}).get("target", "daily")
    webhook = settings.weekly_webhook_url if target == "weekly" else settings.daily_webhook_url
    if not webhook:
        return {"ok": False, "message": f"Missing {target} webhook URL"}
    try:
        response = httpx.post(
            webhook,
            json={"msgtype": "text", "text": {"content": "Weekly Headlines settings test message."}},
            timeout=8,
        )
        return {"ok": response.is_success, "message": f"DingTalk responded with HTTP {response.status_code}"}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/scheduler/status")
def get_scheduler_status() -> Dict[str, Any]:
    settings = store.load(masked=False)
    return schedule_status(settings.schedule, settings.system.timezone)


@app.post("/scheduler/install")
def scheduler_install(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dry_run = bool((payload or {}).get("dry_run", False))
    settings = store.load(masked=False)
    plists = install_launchd(settings.schedule, ROOT, sys.executable, dry_run=dry_run)
    return {"ok": True, "dry_run": dry_run, "plists": plists}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
