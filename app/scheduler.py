from __future__ import annotations

import plistlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict
from zoneinfo import ZoneInfo

from .models import ScheduleSettings, TaskSchedule


TASKS = {
    "daily_fetch": "daily_fetch.py",
    "daily_remind": "daily_remind.py",
    "weekly_publish": "weekly_publish.py",
}


def next_run(schedule: TaskSchedule, timezone_name: str, now: datetime | None = None) -> str | None:
    if not schedule.enabled:
        return None
    tz = ZoneInfo(timezone_name)
    cursor = now.astimezone(tz) if now else datetime.now(tz)
    for day_offset in range(0, 15):
        candidate_date = cursor.date() + timedelta(days=day_offset)
        candidate = datetime.combine(candidate_date, datetime.min.time(), tzinfo=tz).replace(
            hour=schedule.hour,
            minute=schedule.minute,
        )
        launchd_weekday = int(candidate.strftime("%w"))
        if launchd_weekday in schedule.weekdays and candidate > cursor:
            return candidate.isoformat(timespec="minutes")
    return None


def schedule_status(settings: ScheduleSettings, timezone_name: str) -> Dict[str, Dict[str, str | bool | None]]:
    return {
        name: {
            "enabled": getattr(settings, name).enabled,
            "next_run": next_run(getattr(settings, name), timezone_name),
        }
        for name in TASKS
    }


def build_launchd_plist(label: str, script_path: Path, schedule: TaskSchedule, python_path: str) -> bytes:
    calendar_intervals = [
        {"Weekday": weekday, "Hour": schedule.hour, "Minute": schedule.minute}
        for weekday in schedule.weekdays
    ]
    payload = {
        "Label": label,
        "ProgramArguments": [python_path, str(script_path)],
        "StartCalendarInterval": calendar_intervals,
        "RunAtLoad": False,
        "StandardOutPath": str(script_path.parent.parent / "data" / f"{label}.out.log"),
        "StandardErrorPath": str(script_path.parent.parent / "data" / f"{label}.err.log"),
        "WorkingDirectory": str(script_path.parent.parent),
    }
    return plistlib.dumps(payload, sort_keys=False)


def install_launchd(settings: ScheduleSettings, project_root: Path, python_path: str, dry_run: bool = False) -> Dict[str, str]:
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    (project_root / "data").mkdir(parents=True, exist_ok=True)
    output: Dict[str, str] = {}
    for task_name, script in TASKS.items():
        schedule = getattr(settings, task_name)
        label = f"com.franco.weekly-headlines.{task_name}"
        plist_bytes = build_launchd_plist(label, project_root / "scripts" / script, schedule, python_path)
        path = launch_agents / f"{label}.plist"
        if schedule.enabled:
            output[task_name] = plist_bytes.decode("utf-8")
            if not dry_run:
                launch_agents.mkdir(parents=True, exist_ok=True)
                path.write_bytes(plist_bytes)
        else:
            output[task_name] = f"disabled; would remove {path}"
            if not dry_run and path.exists():
                path.unlink()
    return output
