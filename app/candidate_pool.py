"""Local durable store for every deduplicated search candidate, selected or not.

Daily ingest keeps only `max_candidates_per_daily_fetch` candidates so that manual
review stays bounded; the remaining several hundred per day used to be discarded at
the end of the run. They are already paid for and already deduplicated, so this store
retains them for the weekly Recall Sweep and for ranking feedback into future ingests.

This is a local-only asset: it never writes to the DingTalk AI table, which is under
call-quota pressure and remains the sole business datastore.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .url_identity import article_url_identity


RETENTION_DAYS = 90

_COLUMNS = (
    "url_identity", "url", "title", "source_domain", "publish_date", "source_excerpt",
    "search_query", "search_group", "source_lane", "section", "search_provider",
    "first_seen_date", "last_seen_date", "times_seen", "selected",
    "sweep_score", "sweep_verdict", "sweep_reason", "sweep_at",
)


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("link") or value.get("text") or ""
    return str(value or "").strip()


class CandidatePoolStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                create table if not exists candidate_pool (
                    url_identity text primary key,
                    url text not null,
                    title text,
                    source_domain text,
                    publish_date text,
                    source_excerpt text,
                    search_query text,
                    search_group text,
                    source_lane text,
                    section text,
                    search_provider text,
                    first_seen_date text not null,
                    last_seen_date text not null,
                    times_seen integer not null default 1,
                    selected integer not null default 0,
                    sweep_score real,
                    sweep_verdict text,
                    sweep_reason text,
                    sweep_at text
                )
                """
            )
            conn.execute("create index if not exists candidate_pool_last_seen on candidate_pool (last_seen_date)")
            conn.execute("create index if not exists candidate_pool_unselected on candidate_pool (selected, last_seen_date)")

    def record_daily_candidates(
        self,
        unique_records: Sequence[Dict[str, Any]],
        selected_records: Sequence[Dict[str, Any]],
        collected_date: date,
    ) -> Dict[str, int]:
        """Persist one ingest run's deduplicated candidates.

        Raises before writing anything if any candidate lacks a resolvable URL, so a
        malformed provider response cannot leave a half-recorded day behind.
        """
        day = collected_date.isoformat()
        selected_ids = {article_url_identity(_text(record.get("url"))) for record in selected_records}
        selected_ids.discard("")

        rows = []
        for record in unique_records:
            url = _text(record.get("url"))
            identity = article_url_identity(url)
            if not identity:
                raise ValueError(f"candidate has no resolvable article URL: {record.get('title') or url or record!r}")
            rows.append((
                identity,
                url,
                _text(record.get("title")),
                _text(record.get("source")),
                _text(record.get("published_at")),
                _text(record.get("source_excerpt"))[:2000],
                _text(record.get("search_query")),
                _text(record.get("search_group")),
                _text(record.get("source_lane")),
                _text(record.get("section")),
                _text(record.get("search_provider")),
                day,
                1 if identity in selected_ids else 0,
            ))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                insert into candidate_pool (
                    url_identity, url, title, source_domain, publish_date, source_excerpt,
                    search_query, search_group, source_lane, section, search_provider,
                    first_seen_date, last_seen_date, times_seen, selected
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                on conflict(url_identity) do update set
                    last_seen_date = excluded.last_seen_date,
                    times_seen = candidate_pool.times_seen + 1,
                    -- promotion into News is terminal: a later unselected sighting must not undo it
                    selected = max(candidate_pool.selected, excluded.selected),
                    title = case when candidate_pool.title = '' then excluded.title else candidate_pool.title end,
                    publish_date = case when candidate_pool.publish_date = '' then excluded.publish_date else candidate_pool.publish_date end
                """,
                [(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[11], row[12]) for row in rows],
            )
        stored = len({row[0] for row in rows})
        selected = len({row[0] for row in rows if row[12]})
        return {"stored": stored, "selected": selected, "unselected": stored - selected}

    def list_unselected(
        self,
        since: Optional[date] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Candidates never promoted into News, highest sweep score first."""
        query = f"select {', '.join(_COLUMNS)} from candidate_pool where selected = 0"
        params: List[Any] = []
        if since is not None:
            query += " and last_seen_date >= ?"
            params.append(since.isoformat())
        query += " order by sweep_score desc nulls last, last_seen_date desc, url_identity"
        if limit is not None:
            query += " limit ?"
            params.append(int(limit))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(zip(_COLUMNS, row)) for row in rows]

    def apply_sweep_results(self, results: Iterable[Dict[str, Any]], swept_at: str = "") -> int:
        """Write Recall Sweep verdicts back so future ingests can rank on them."""
        updates = []
        for item in results:
            identity = article_url_identity(_text(item.get("url")))
            if not identity:
                continue
            score = item.get("score")
            updates.append((
                float(score) if score is not None else None,
                _text(item.get("verdict")),
                _text(item.get("reason")),
                swept_at,
                identity,
            ))
        if not updates:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.executemany(
                """
                update candidate_pool
                set sweep_score = ?, sweep_verdict = ?, sweep_reason = ?, sweep_at = ?
                where url_identity = ?
                """,
                updates,
            )
            return cursor.rowcount

    def prune(self, retention_days: int = RETENTION_DAYS, today: Optional[date] = None) -> int:
        cutoff = (today or date.today()) - timedelta(days=retention_days)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("delete from candidate_pool where last_seen_date < ?", (cutoff.isoformat(),))
            return cursor.rowcount

    def stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            total, selected, swept = conn.execute(
                "select count(*), sum(selected), sum(case when sweep_score is not null then 1 else 0 end) from candidate_pool"
            ).fetchone()
        return {"total": total or 0, "selected": selected or 0, "unselected": (total or 0) - (selected or 0), "swept": swept or 0}
