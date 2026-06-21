from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx

from .models import OpenAIResearchSettings


API_URL = "https://api.openai.com/v1/responses"
PHRASE_HEADING = "Deep Insight Phrases"


def _api_key(settings: OpenAIResearchSettings) -> str:
    return settings.api_key.strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def research_prompt(topic: str, question: str, period: str, records: List[Dict[str, Any]]) -> str:
    source_rows = []
    for index, record in enumerate(records, start=1):
        fields = record.get("fields") or {}
        url_value = fields.get("Source URL") or {}
        url = url_value.get("link") if isinstance(url_value, dict) else url_value
        source_rows.append(
            f"{index}. [{fields.get('Section') or 'News'}] {fields.get('Title') or '-'}\n"
            f"   Published: {fields.get('Publish Date') or '-'}\n"
            f"   Source: {url or '-'}"
        )
    sources = "\n".join(source_rows)
    return f"""You are an OpenAI Deep Research analyst preparing a GBSS Weekly AI & Service Intelligence report.

Reporting period: {period}
Research topic: {topic}
Research question: {question}

The following reviewed News records are the starting evidence. Verify material claims using high-quality public sources and cite sources inline. Do not assume the reviewed News records are complete or correct.

{sources}

Return Markdown with these exact sections:
## Research synthesis
Provide a concise but substantive analysis of what changed, why it matters for GBSS, and important boundaries/counter-evidence.
## Implications for GBSS
Give decision-relevant impacts for Merchant Service/ePOS, Antom, WorldFirst, General GBSS Ops, Contact Center, AIQC, Voice AI or OPC only where supported.
## Deep Insight Phrases
Provide exactly 5 to 10 short, decision-oriented phrases. Each phrase must be 2 to 10 words and start with '- '.
## Sources
List the most important sources as Markdown links.
"""


def _output_text(response: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts).strip()


def extract_phrases(content: str) -> List[str]:
    match = re.search(r"^##\s+Deep Insight Phrases\s*$([\s\S]*?)(?=^##\s|\Z)", content, re.MULTILINE)
    block = match.group(1) if match else content
    phrases = []
    for line in block.splitlines():
        text = line.strip()
        if text.startswith("- "):
            phrase = text[2:].strip()
            if phrase and len(phrase.split()) <= 10:
                phrases.append(phrase)
    return phrases[:10]


def run_deep_research(
    settings: OpenAIResearchSettings,
    topic: str,
    question: str,
    period: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    api_key = _api_key(settings)
    if not settings.enabled:
        raise RuntimeError("OpenAI Deep Research is disabled")
    if not api_key:
        raise RuntimeError("OpenAI Deep Research API key is not configured")
    payload = {
        "model": settings.model,
        "input": research_prompt(topic, question, period, records),
        "background": True,
        "max_tool_calls": settings.max_tool_calls,
        "tools": [{"type": "web_search_preview"}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as client:
        response = client.post(API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result: Dict[str, Any] = response.json()
        response_id = str(result.get("id") or "")
        if not response_id:
            raise RuntimeError("OpenAI Deep Research response id is missing")
        deadline = time.monotonic() + settings.timeout_seconds
        while result.get("status") in {"queued", "in_progress"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"OpenAI Deep Research timed out: {response_id}")
            time.sleep(settings.poll_interval_seconds)
            poll = client.get(f"{API_URL}/{response_id}", headers=headers)
            poll.raise_for_status()
            result = poll.json()
    status = str(result.get("status") or "")
    if status != "completed":
        raise RuntimeError(f"OpenAI Deep Research ended with status={status}: {result.get('error') or ''}")
    content = _output_text(result)
    if not content:
        raise RuntimeError("OpenAI Deep Research returned no output text")
    return {
        "status": status,
        "response_id": response_id,
        "model": settings.model,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "content": content,
        "phrases": extract_phrases(content),
    }


def result_path(root: Path, research_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", research_id).strip("-") or "weekly"
    return root / "deep_research" / f"{safe_id}.json"


def save_result(root: Path, research_id: str, result: Dict[str, Any]) -> Path:
    path = result_path(root, research_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_result(root: Path, research_id: str) -> Dict[str, Any]:
    path = result_path(root, research_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
