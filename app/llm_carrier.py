"""Run a prompt through a locally installed subscription CLI, with failover.

Analysis work (Recall Sweep, Claim synthesis) runs on subscription-billed CLIs
rather than the metered OpenAI layer; see docs/adr/0001. Subscription quota is a
real and observed failure mode -- Codex hit its limit on the first production
call -- so the carrier order is a chain, not a single choice, and every attempt
is recorded rather than silently swallowed.

The carriers consume subscription tokens. This is zero marginal cash, not zero
tokens, and nothing here is measured by the API Usage cost ledger.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple


ALL_CARRIERS: Tuple[str, ...] = ("codex", "claude")

DEFAULT_TIMEOUT_SECONDS = 900

# Substrings that mean "this carrier cannot serve us right now" rather than
# "the model answered badly". Kept specific enough to stay correct even if
# applied to arbitrary text: a candidate headline about rate limits or quotas
# must not read as an exhausted subscription.
_QUOTA_MARKERS = (
    "usage limit",
    "usage_limit",
    "rate limit exceeded",
    "rate_limit",
    "429 too many requests",
    "quota exceeded",
    "out of credits",
    "credit balance is too low",
    "/login",
    "not authenticated",
    "please log in",
)


@dataclass
class CarrierAttempt:
    carrier: str
    status: str
    reason: str = ""
    detail: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"carrier": self.carrier, "status": self.status, "reason": self.reason, "detail": self.detail}


@dataclass
class CarrierResponse:
    text: str
    carrier: str
    attempts: List[CarrierAttempt]

    @property
    def degraded(self) -> bool:
        """True when the primary carrier could not serve the request."""
        return bool(self.attempts) and self.attempts[0].status != "success"

    def as_metadata(self) -> Dict[str, object]:
        return {"carrier": self.carrier, "degraded": self.degraded, "attempts": [a.as_dict() for a in self.attempts]}


class CarrierUnavailable(RuntimeError):
    """Every configured carrier refused or failed."""


def is_quota_exhausted(output: str) -> bool:
    text = str(output or "").lower()
    return any(marker in text for marker in _QUOTA_MARKERS)


def _default_runner(carrier: str, prompt: str, timeout: int) -> Tuple[int, str, str]:
    if carrier == "codex":
        command = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", prompt]
    elif carrier == "claude":
        command = ["claude", "-p", prompt]
    else:
        raise ValueError(f"unknown carrier: {carrier}")
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    return completed.returncode, completed.stdout, completed.stderr


def run_prompt(
    prompt: str,
    carriers: Sequence[str] = ALL_CARRIERS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    runner: Optional[Callable[[str, str, int], Tuple[int, str, str]]] = None,
) -> CarrierResponse:
    """Send `prompt` to the first carrier that can answer, in order.

    Raises CarrierUnavailable if none can, so a caller can never mistake an
    exhausted subscription for an empty result.
    """
    invoke = runner or _default_runner
    attempts: List[CarrierAttempt] = []
    for carrier in carriers:
        try:
            returncode, stdout, stderr = invoke(carrier, prompt, timeout)
        except subprocess.TimeoutExpired:
            attempts.append(CarrierAttempt(carrier, "failed", "timeout", f"exceeded {timeout}s"))
            continue
        except Exception as exc:  # missing binary, permission error, ...
            attempts.append(CarrierAttempt(carrier, "failed", "unavailable", str(exc)[:400]))
            continue
        combined = f"{stdout}\n{stderr}"
        if returncode != 0:
            reason = "quota_exhausted" if is_quota_exhausted(combined) else "error"
            attempts.append(CarrierAttempt(carrier, "failed", reason, combined.strip()[:400]))
            continue
        if not stdout.strip():
            attempts.append(CarrierAttempt(carrier, "failed", "empty_output", stderr.strip()[:400]))
            continue
        attempts.append(CarrierAttempt(carrier, "success"))
        return CarrierResponse(text=stdout.strip(), carrier=carrier, attempts=attempts)

    detail = "; ".join(f"{a.carrier}={a.reason}" for a in attempts) or "no carriers configured"
    raise CarrierUnavailable(f"no analysis carrier available ({detail})")
