"""Domain-level relevance priors learned from Recall Sweep verdicts.

Daily selection cannot know whether a brand-new URL is relevant, so it ranks on
freshness and source trust. That leaves a specific hole: within the same
freshness bucket, a junk article published yesterday outranks a genuine one
published yesterday, because nothing distinguishes them.

Sweep verdicts accumulated in the candidate pool close that hole. A domain that
has repeatedly produced noise sinks within its freshness bucket; a domain that
has repeatedly produced real events rises. Freshness still dominates, so the
previous-day priority rule is untouched.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence


MIN_SUPPORT = 3

_VERDICT_WEIGHT = {"likely_missed": 1.0, "borderline": 0.0, "noise": -1.0}


def domain_relevance_priors(
    pool_rows: Iterable[Dict[str, Any]],
    min_support: int = MIN_SUPPORT,
) -> Dict[str, float]:
    """Mean verdict weight per domain, for domains seen at least `min_support` times.

    Domains below the support threshold are omitted entirely rather than given a
    weak score, so one unlucky article cannot bury a domain.
    """
    totals: Dict[str, list] = {}
    for row in pool_rows:
        verdict = str(row.get("sweep_verdict") or "")
        if verdict not in _VERDICT_WEIGHT:
            continue
        domain = _normalise(row.get("source_domain"))
        if not domain:
            continue
        bucket = totals.setdefault(domain, [0.0, 0])
        bucket[0] += _VERDICT_WEIGHT[verdict]
        bucket[1] += 1
    return {
        domain: total / count
        for domain, (total, count) in totals.items()
        if count >= min_support
    }


def prior_for(record: Dict[str, Any], priors: Dict[str, float]) -> float:
    """Prior for a candidate's domain; 0.0 when the domain has no history."""
    domain = _normalise(record.get("source") or record.get("source_domain"))
    if not domain:
        return 0.0
    if domain in priors:
        return priors[domain]
    # A subdomain inherits its parent's history when it has none of its own.
    for known, value in priors.items():
        if domain.endswith("." + known):
            return value
    return 0.0


def _normalise(value: Any) -> str:
    domain = str(value or "").strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://").split("/")[0]
    return domain.removeprefix("www.")


def rank_penalty(record: Dict[str, Any], priors: Dict[str, float]) -> float:
    """Sort key fragment: lower is better, so a positive prior sorts first."""
    return -prior_for(record, priors)


def summarise(priors: Dict[str, float], limit: int = 5) -> Dict[str, Sequence]:
    ordered = sorted(priors.items(), key=lambda item: item[1])
    return {
        "domains": len(priors),
        "worst": ordered[:limit],
        "best": list(reversed(ordered[-limit:])),
    }
