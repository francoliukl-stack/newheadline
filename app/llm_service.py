from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import random
import time
from typing import Any, Dict, Generic, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .audit_trail import AuditTrailWriter
from .cost_control import BudgetController, UsageLedger, calculate_cost, usage_fields
from .models import OpenAIServiceSettings


T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult(Generic[T]):
    status: str
    value: Optional[T]
    model: str
    response_id: str = ""
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    message: str = ""


def _output_text(response: Dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    parts = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


class LLMService:
    def __init__(self, config: OpenAIServiceSettings, budget: BudgetController, ledger: UsageLedger, audit: Optional[AuditTrailWriter] = None, client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self.budget = budget
        self.ledger = ledger
        self.audit = audit
        self.client = client

    def execute(self, *, task: str, schema: Type[T], context: Dict[str, Any], budget_scope: str, event_id: str = "", run_id: str = "", model: str = "", max_output_tokens: int = 1200, use_web_search: bool = False, approval_granted: bool = False) -> LLMResult[T]:
        selected_model = model or self.config.classification_model
        prompt = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.config.enabled:
            return LLMResult("skipped", None, selected_model, message="OpenAI service disabled")
        if use_web_search and not approval_granted:
            return self._skip(task, selected_model, prompt, budget_scope, event_id, run_id, max_output_tokens, "explicit research approval required", started)
        if self.budget.circuit_open("openai", selected_model):
            return self._skip(task, selected_model, prompt, budget_scope, event_id, run_id, max_output_tokens, "circuit open", started)
        decision = self.budget.preflight(selected_model, prompt, max_output_tokens, budget_scope)
        if not decision.allowed:
            return self._skip(task, selected_model, prompt, budget_scope, event_id, run_id, max_output_tokens, decision.reason, started)
        api_key = self.config.api_key.strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return self._skip(task, selected_model, prompt, budget_scope, event_id, run_id, max_output_tokens, "OpenAI API key missing", started)
        payload: Dict[str, Any] = {
            "model": selected_model,
            "input": [{"role": "system", "content": "Return only the requested structured GBSS event intelligence result. Never assert final P0."}, {"role": "user", "content": prompt}],
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": schema.__name__, "schema": schema.model_json_schema(), "strict": True}},
        }
        if use_web_search:
            payload["tools"] = [{"type": "web_search"}]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response_data: Dict[str, Any] = {}
        retries = 0
        try:
            for attempt in range(self.config.max_retries + 1):
                try:
                    if self.client:
                        response = self.client.post(self.config.api_url, headers=headers, json=payload)
                    else:
                        response = httpx.post(self.config.api_url, headers=headers, json=payload, timeout=self.config.request_timeout_seconds)
                    if response.status_code in {408, 409, 429} or response.status_code >= 500:
                        if attempt < self.config.max_retries:
                            retries += 1
                            time.sleep((2 ** attempt) + random.random())
                            continue
                    response.raise_for_status()
                    response_data = response.json()
                    break
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt >= self.config.max_retries:
                        raise
                    retries += 1
                    time.sleep((2 ** attempt) + random.random())
            raw = _output_text(response_data)
            value = schema.model_validate_json(raw)
            usage = response_data.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            actual_cost = calculate_cost(selected_model, input_tokens, output_tokens)
            self.ledger.append(usage_fields(run_id=run_id, event_id=event_id, provider="openai", operation=task, model=selected_model, pricing_version=self.config.pricing_version, estimate=decision.estimate, status="completed", retries=retries, actual_input_tokens=input_tokens, actual_output_tokens=output_tokens, actual_cost_usd=actual_cost, started_at=started, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
            self._audit(run_id, task, event_id, "success", selected_model, actual_cost, "")
            return LLMResult("completed", value, selected_model, str(response_data.get("id") or ""), decision.estimate.cost_usd, actual_cost)
        except (httpx.HTTPError, ValidationError, ValueError, KeyError) as exc:
            self.ledger.append(usage_fields(run_id=run_id, event_id=event_id, provider="openai", operation=task, model=selected_model, pricing_version=self.config.pricing_version, estimate=decision.estimate, status="failed", retries=retries, skip_reason=str(exc), started_at=started, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
            self._audit(run_id, task, event_id, "failed", selected_model, 0.0, str(exc))
            return LLMResult("failed", None, selected_model, estimated_cost_usd=decision.estimate.cost_usd, message=str(exc))

    def _skip(self, task: str, model: str, prompt: str, scope: str, event_id: str, run_id: str, max_output_tokens: int, reason: str, started: str) -> LLMResult[T]:
        estimate = self.budget.preflight(model, prompt, max_output_tokens, scope).estimate
        self.ledger.append(usage_fields(run_id=run_id, event_id=event_id, provider="openai", operation=task, model=model, pricing_version=self.config.pricing_version, estimate=estimate, status="skipped", skip_reason=reason, started_at=started, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self._audit(run_id, task, event_id, "skipped", model, 0.0, reason)
        return LLMResult("skipped", None, model, estimated_cost_usd=estimate.cost_usd, message=reason)

    def _audit(self, run_id: str, task: str, event_id: str, status: str, model: str, cost: float, error: str) -> None:
        if self.audit and run_id:
            self.audit.record(run_id=run_id, workflow="llm_service", stage_code=f"LLM.{task}", stage_name=f"OpenAI {task}", status=status, report_id=event_id, output_summary=f"model={model}; actual_cost_usd={cost:.8f}", error=error, metadata={"model": model, "prompt_version": self.config.prompt_version})
