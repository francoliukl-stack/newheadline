"""Close News that stayed pending past the point where it could still matter.

External event intelligence has a short shelf life: an unreviewed item from five
weeks ago cannot inform anything today, and leaving it pending makes the review
queue unusable. Closing it is an operator policy decision applied in bulk, not a
per-item judgement, and the record says so.

Two consequences are deliberate:

- The decision source is distinct from Human/Human_Override, so these rows are
  excluded from `learn_review_rules`. Recording hundreds of blanket rejections
  as ordinary human decisions would teach the rulebook to reject everything.
- Items already carrying a human decision are never touched.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .dingtalk_ai_table import cell_text, status_name
from .publish_dates import parse_date


BULK_DECISION_SOURCE = "Human_Bulk_Stale_Close"
DEFAULT_MAX_AGE_DAYS = 7


def stale_pending_news(
    records: Iterable[Dict[str, Any]],
    today: date,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    field_mapping: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Pending News whose publish date is older than the retention window.

    Records with no usable publish date are left alone: age is the whole basis
    of this policy, so an item whose age is unknown cannot be judged by it.
    """
    stale = []
    for record in records:
        fields = record.get("fields") or {}
        if not record.get("id"):
            continue
        if status_name(fields, field_mapping or {}) != "待处理":
            continue
        published = parse_date(fields.get("Publish Date"))
        if not published:
            continue
        try:
            age = (today - date.fromisoformat(published)).days
        except ValueError:
            continue
        if age > max_age_days:
            stale.append(record)
    return stale


def stale_close_patch(
    max_age_days: int,
    closed_at: str,
    status_field: str = "Status",
) -> Dict[str, str]:
    return {
        status_field: "已拒绝",
        "Rejection Reason": f"发布超过 {max_age_days} 天仍未审核，按运营策略统一关闭；非逐条判断。",
        "Review Decision Source": BULK_DECISION_SOURCE,
        "Reviewed At": closed_at,
    }


def snapshot_rows(records: Sequence[Dict[str, Any]], field_mapping: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Everything needed to put the affected records back the way they were."""
    return [
        {
            "id": str(record.get("id")),
            "title": cell_text((record.get("fields") or {}).get("Title")),
            "publish_date": parse_date((record.get("fields") or {}).get("Publish Date")) or "",
            "previous_status": status_name(record.get("fields") or {}, field_mapping or {}),
            "previous_decision_source": cell_text((record.get("fields") or {}).get("Review Decision Source")),
            "previous_rejection_reason": cell_text((record.get("fields") or {}).get("Rejection Reason")),
        }
        for record in records
    ]
