from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dingtalk_ai_table import cell_text


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULEBOOK_PATH = ROOT / "docs" / "ai_review_labeling_rules.md"


@dataclass(frozen=True)
class RulebookRule:
    rule_id: str
    status: str
    confidence: float
    reason: str
    title_any: List[str] = field(default_factory=list)
    title_all: List[str] = field(default_factory=list)
    event_type_any: List[str] = field(default_factory=list)
    business_line_any: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AIReviewRulebook:
    version: str
    path: str
    signature: str
    rules: List[RulebookRule]


def _extract_json_block(content: str) -> Dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if not match:
        return {}
    return json.loads(match.group(1))


def load_ai_review_rulebook(path: Path = DEFAULT_RULEBOOK_PATH) -> AIReviewRulebook:
    if not path.exists():
        return AIReviewRulebook("none", str(path), "missing", [])
    content = path.read_text(encoding="utf-8")
    payload = _extract_json_block(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    rules = [
        RulebookRule(
            rule_id=str(item.get("id") or ""),
            status=str(item.get("status") or ""),
            confidence=float(item.get("confidence") or 0),
            reason=str(item.get("reason") or ""),
            title_any=[str(value).lower() for value in item.get("title_any") or []],
            title_all=[str(value).lower() for value in item.get("title_all") or []],
            event_type_any=[str(value) for value in item.get("event_type_any") or []],
            business_line_any=[str(value) for value in item.get("business_line_any") or []],
        )
        for item in payload.get("rules") or []
        if item.get("id") and item.get("status")
    ]
    return AIReviewRulebook(str(payload.get("version") or "unversioned"), str(path), digest, rules)


def _business_lines(event: Optional[Dict[str, Any]]) -> List[str]:
    raw = cell_text((event or {}).get("Business Lines"))
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def match_rulebook_rule(
    fields: Dict[str, Any],
    event: Optional[Dict[str, Any]],
    rulebook: Optional[AIReviewRulebook],
) -> Optional[RulebookRule]:
    if not rulebook:
        return None
    title = cell_text(fields.get("Title") or fields.get("Subject")).lower()
    event_type = cell_text((event or {}).get("Event Type"))
    business_lines = set(_business_lines(event))
    for rule in rulebook.rules:
        if rule.title_any and not any(token in title for token in rule.title_any):
            continue
        if rule.title_all and not all(token in title for token in rule.title_all):
            continue
        if rule.event_type_any and event_type not in rule.event_type_any:
            continue
        if rule.business_line_any and not business_lines.intersection(rule.business_line_any):
            continue
        return rule
    return None
