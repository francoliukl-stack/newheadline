from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, Iterable, List, Protocol
from uuid import uuid4

from zoneinfo import ZoneInfo

from .dingtalk_ai_table import add_records, list_records
from .models import AppSettings, DingTalkAITableSettings, OpenAIServiceSettings


MODEL_PRICING_USD_PER_MILLION = {
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-nano-2026-03-17": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-mini-2026-03-17": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-2026-03-05": (2.50, 15.00),
}


@dataclass
class UsageRecord:
    fields: Dict[str, Any]


class UsageLedger(Protocol):
    def records(self) -> List[Dict[str, Any]]:
        ...

    def append(self, fields: Dict[str, Any]) -> None:
        ...


class DingTalkUsageLedger:
    def __init__(self, settings: AppSettings, table: DingTalkAITableSettings) -> None:
        self.settings = settings
        self.table = table

    def records(self) -> List[Dict[str, Any]]:
        return [record.get("fields") or {} for record in list_records(self.settings.dingtalk, self.table)]

    def append(self, fields: Dict[str, Any]) -> None:
        result = add_records(self.settings.dingtalk, self.table, [fields])
        if result.status != "sent":
            raise RuntimeError(result.message)


class MemoryUsageLedger:
    def __init__(self, records: Iterable[Dict[str, Any]] = ()) -> None:
        self.items = [dict(item) for item in records]

    def records(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self.items]

    def append(self, fields: Dict[str, Any]) -> None:
        self.items.append(dict(fields))


@dataclass
class CostEstimate:
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str
    estimate: CostEstimate


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in MODEL_PRICING_USD_PER_MILLION:
        raise ValueError(f"No pricing configured for model: {model}")
    input_rate, output_rate = MODEL_PRICING_USD_PER_MILLION[model]
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)


def estimate_cost(model: str, prompt: str, max_output_tokens: int) -> CostEstimate:
    input_tokens = estimate_tokens(prompt)
    return CostEstimate(input_tokens, max_output_tokens, calculate_cost(model, input_tokens, max_output_tokens))


def _parse_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def count_provider_calls_today(ledger: UsageLedger, provider: str, timezone_name: str, now: datetime = None) -> int:
    current = now or datetime.now(ZoneInfo(timezone_name))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(timezone_name))
    current = current.astimezone(ZoneInfo(timezone_name))
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [row for row in ledger.records() if str(row.get("Provider") or "") == provider]
    return sum(1 for row in rows if _parse_timestamp(row.get("Started At")).astimezone(current.tzinfo) >= day_start)


def _actual_cost(row: Dict[str, Any]) -> float:
    try:
        status = str(row.get("Status") or "").lower()
        if status == "reserved":
            return float(row.get("Estimated Cost USD") or 0)
        return float(row.get("Actual Cost USD") or 0)
    except (TypeError, ValueError):
        return 0.0


def _latest_calls(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse append-only reservation/completion rows to one billable row per call."""
    latest: Dict[str, Dict[str, Any]] = {}
    without_id: List[Dict[str, Any]] = []
    for row in rows:
        call_id = str(row.get("Call ID") or "").strip()
        if not call_id:
            without_id.append(row)
            continue
        current = latest.get(call_id)
        if current is None:
            latest[call_id] = row
            continue
        current_finished = bool(str(current.get("Finished At") or "").strip())
        candidate_finished = bool(str(row.get("Finished At") or "").strip())
        if candidate_finished or not current_finished:
            latest[call_id] = row
    return without_id + list(latest.values())


class BudgetController:
    def __init__(self, config: OpenAIServiceSettings, ledger: UsageLedger, timezone_name: str) -> None:
        self.config = config
        self.ledger = ledger
        self.timezone_name = timezone_name

    def preflight(self, model: str, prompt: str, max_output_tokens: int, scope: str, now: datetime = None) -> BudgetDecision:
        estimate = estimate_cost(model, prompt, max_output_tokens)
        single_cap = self.config.single_insight_cap_usd if scope in {"insight", "research"} else self.config.single_ingest_cap_usd
        if estimate.cost_usd > single_cap:
            return BudgetDecision(False, f"estimated ${estimate.cost_usd:.4f} exceeds single {scope} cap ${single_cap:.2f}", estimate)
        current = now or datetime.now(ZoneInfo(self.timezone_name))
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo(self.timezone_name))
        rows = _latest_calls(self.ledger.records())
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = day_start.replace(day=1)
        day_cost = sum(_actual_cost(row) for row in rows if _parse_timestamp(row.get("Started At")).astimezone(current.tzinfo) >= day_start)
        week_cost = sum(_actual_cost(row) for row in rows if _parse_timestamp(row.get("Started At")).astimezone(current.tzinfo) >= week_start)
        month_cost = sum(_actual_cost(row) for row in rows if _parse_timestamp(row.get("Started At")).astimezone(current.tzinfo) >= month_start)
        for label, used, cap in (("daily", day_cost, self.config.daily_cap_usd), ("weekly", week_cost, self.config.weekly_cap_usd), ("monthly", month_cost, self.config.monthly_cap_usd)):
            if used + estimate.cost_usd > cap:
                return BudgetDecision(False, f"estimated call would exceed {label} cap: used=${used:.4f}, cap=${cap:.2f}", estimate)
        return BudgetDecision(True, "within budget", estimate)

    def circuit_open(self, provider: str, model: str, now: datetime = None) -> bool:
        current = now or datetime.now(timezone.utc)
        rows = [row for row in self.ledger.records() if str(row.get("Provider") or "") == provider and str(row.get("Model") or "") == model]
        rows.sort(key=lambda row: _parse_timestamp(row.get("Started At")), reverse=True)
        latest = rows[:10]
        if not latest:
            return False
        last_time = _parse_timestamp(latest[0].get("Started At"))
        if (current.astimezone(timezone.utc) - last_time.astimezone(timezone.utc)).total_seconds() >= self.config.circuit_open_seconds:
            return False
        statuses = [str(row.get("Status") or "").lower() for row in latest]
        consecutive = 0
        for status in statuses:
            if status != "failed":
                break
            consecutive += 1
        failures = sum(status == "failed" for status in statuses)
        return consecutive >= self.config.circuit_failure_threshold or (len(statuses) >= 10 and failures * 2 >= len(statuses))


def usage_fields(*, run_id: str, event_id: str, provider: str, operation: str, model: str, pricing_version: str, estimate: CostEstimate, status: str, retries: int = 0, skip_reason: str = "", actual_input_tokens: int = 0, actual_output_tokens: int = 0, actual_cost_usd: float = 0.0, started_at: str = "", finished_at: str = "", call_id: str = "") -> Dict[str, str]:
    return {
        "Call ID": call_id or uuid4().hex, "Run ID": run_id, "Event ID": event_id, "Provider": provider, "Operation": operation,
        "Model": model, "Pricing Version": pricing_version, "Estimated Input Tokens": str(estimate.input_tokens),
        "Estimated Output Tokens": str(estimate.output_tokens), "Estimated Cost USD": f"{estimate.cost_usd:.8f}",
        "Actual Input Tokens": str(actual_input_tokens), "Actual Output Tokens": str(actual_output_tokens),
        "Actual Cost USD": f"{actual_cost_usd:.8f}", "Status": status, "Retry Count": str(retries),
        "Skip Reason": skip_reason, "Started At": started_at, "Finished At": finished_at,
    }
