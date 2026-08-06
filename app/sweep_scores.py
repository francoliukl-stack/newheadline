"""Read Recall Sweep verdicts for use as a second opinion during News review.

Kept separate from candidate_pool so review code depends on a tiny read-only
surface, and so a missing or unreadable pool degrades to "no second opinion"
rather than failing the review job. The sweep can only ever add a suggestion,
so its absence is safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "settings.sqlite3"


def load_sweep_scores(db_path: Optional[Path] = None) -> Dict[str, float]:
    path = Path(db_path or DEFAULT_DB)
    if not path.exists():
        return {}
    try:
        from .candidate_pool import CandidatePoolStore

        return CandidatePoolStore(path).sweep_score_index()
    except Exception:
        return {}
