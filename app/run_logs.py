from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLogStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def start(
        self,
        job_name: str,
        provider: str = "",
        fallback_provider: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                insert into job_runs
                (run_id, job_name, status, started_at, provider, fallback_provider, metadata)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    job_name,
                    "running",
                    utc_now(),
                    provider,
                    fallback_provider,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return run_id

    def finish(
        self,
        run_id: str,
        status: str,
        result_count: int = 0,
        message: str = "",
        error: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                update job_runs
                set status = ?, finished_at = ?, result_count = ?, message = ?,
                    error = ?, metadata = ?
                where run_id = ?
                """,
                (
                    status,
                    utc_now(),
                    result_count,
                    message,
                    error,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    run_id,
                ),
            )

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select run_id, job_name, status, started_at, finished_at, provider,
                       fallback_provider, result_count, message, error, metadata
                from job_runs
                order by started_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item["metadata"] or "{}")
            items.append(item)
        return items

    def summary(self) -> Dict[str, Any]:
        recent = self.list_recent(limit=1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select status, count(*) as count
                from job_runs
                group by status
                """
            ).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {
            "last_run": recent[0] if recent else None,
            "counts": {
                "running": counts.get("running", 0),
                "success": counts.get("success", 0),
                "failed": counts.get("failed", 0),
            },
        }

    @contextmanager
    def track(
        self,
        job_name: str,
        provider: str = "",
        fallback_provider: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        run_id = self.start(job_name, provider, fallback_provider, metadata)
        try:
            yield run_id
        except Exception as exc:
            self.finish(run_id, "failed", error=str(exc), metadata=metadata)
            raise

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                create table if not exists job_runs (
                    run_id text primary key,
                    job_name text not null,
                    status text not null,
                    started_at text not null,
                    finished_at text,
                    provider text,
                    fallback_provider text,
                    result_count integer not null default 0,
                    message text not null default '',
                    error text not null default '',
                    metadata text not null default '{}'
                )
                """
            )
