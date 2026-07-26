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
            row = conn.execute("select metadata from job_runs where run_id = ?", (run_id,)).fetchone()
            merged_metadata = json.loads((row or ["{}"]) [0] or "{}")
            merged_metadata.update(metadata or {})
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
                    json.dumps(merged_metadata, ensure_ascii=False),
                    run_id,
                ),
            )

    def append_pending_audit(self, run_id: str, event: Dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("select metadata from job_runs where run_id = ?", (run_id,)).fetchone()
            if not row:
                return
            metadata = json.loads(row[0] or "{}")
            pending = list(metadata.get("pending_audit_events") or [])
            pending.append(event)
            metadata["pending_audit_events"] = pending[-100:]
            conn.execute("update job_runs set metadata = ? where run_id = ?", (json.dumps(metadata, ensure_ascii=False, default=str), run_id))

    def list_pending_audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.list_recent(limit=limit)
        result = []
        for row in rows:
            events = list((row.get("metadata") or {}).get("pending_audit_events") or [])
            if events:
                result.append({"run_id": row["run_id"], "events": events})
        return result

    def clear_pending_audit(self, run_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("select metadata from job_runs where run_id = ?", (run_id,)).fetchone()
            if not row:
                return
            metadata = json.loads(row[0] or "{}")
            metadata.pop("pending_audit_events", None)
            conn.execute("update job_runs set metadata = ? where run_id = ?", (json.dumps(metadata, ensure_ascii=False), run_id))

    def recover_stale_runs(self, older_than_seconds: int = 21600) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        recovered = 0
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("select run_id, started_at, metadata from job_runs where status = 'running'").fetchall()
            for run_id, started_at, metadata_text in rows:
                try:
                    started_ts = datetime.fromisoformat(started_at).timestamp()
                except (TypeError, ValueError):
                    started_ts = 0
                if started_ts >= cutoff:
                    continue
                metadata = json.loads(metadata_text or "{}")
                pending = list(metadata.get("pending_audit_events") or [])
                pending.append({
                    "run_id": run_id, "workflow": "run_recovery", "stage_code": "RECOVERY.stale_run",
                    "stage_name": "Recover stale running job", "status": "failed", "error": "Run remained in running state beyond recovery threshold",
                })
                metadata["pending_audit_events"] = pending[-100:]
                conn.execute(
                    "update job_runs set status = 'failed', finished_at = ?, error = ?, metadata = ? where run_id = ?",
                    (utc_now(), "stale running job recovered", json.dumps(metadata, ensure_ascii=False), run_id),
                )
                recovered += 1
        return recovered

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

    def first_success_started_at(self, job_name: str) -> Optional[str]:
        """Return the first successful production run timestamp for an observation boundary."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "select min(started_at) from job_runs where job_name = ? and status = 'success'",
                (job_name,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def count(self, job_name: str) -> int:
        """Total recorded runs for a job, used to advance rotating work windows."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("select count(*) from job_runs where job_name = ?", (job_name,)).fetchone()
        return int(row[0]) if row and row[0] else 0

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
