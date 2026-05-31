from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import httpx
import re

from .models import DingTalkAITableSettings, DingTalkSettings
from .notifications import get_dingtalk_access_token


MARKDOWN_LINK_PATTERN = re.compile(r"^\[(?P<text>.+)\]\((?P<link>https?://.+)\)$")


def raise_for_dingtalk_error(response: httpx.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if response.is_error:
        raise RuntimeError(f"DingTalk HTTP {response.status_code}: {payload}")


@dataclass
class AITableResult:
    status: str
    message: str
    record_ids: List[str]


def extract_base_id(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        return candidate
    parsed = urlparse(candidate)
    parts = [part for part in parsed.path.split("/") if part]
    if "nodes" in parts:
        index = parts.index("nodes")
        if index + 1 < len(parts):
            return parts[index + 1]
    return candidate


def resolve_operator_id(dingtalk: DingTalkSettings, ai_table: DingTalkAITableSettings) -> str:
    if ai_table.operator_id:
        return ai_table.operator_id
    if not ai_table.operator_user_id:
        return ""
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    response = httpx.post(
        "https://oapi.dingtalk.com/topapi/v2/user/get",
        params={"access_token": token},
        json={"userid": ai_table.operator_user_id},
        timeout=8,
    )
    response.raise_for_status()
    payload: Dict[str, Any] = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(str(payload))
    result = payload.get("result") or {}
    union_id = result.get("unionid")
    if not isinstance(union_id, str) or not union_id:
        raise RuntimeError("DingTalk unionId missing from user lookup response")
    return union_id


def validate_ai_table_settings(dingtalk: DingTalkSettings, ai_table: DingTalkAITableSettings) -> List[str]:
    missing = []
    for name, value in {
        "dingtalk.client_id": dingtalk.client_id,
        "dingtalk.client_secret": dingtalk.client_secret,
        "dingtalk_ai_table.base_id": ai_table.base_id,
        "dingtalk_ai_table.sheet_id": ai_table.sheet_id,
    }.items():
        if not value:
            missing.append(name)
    if not ai_table.operator_id and not ai_table.operator_user_id:
        missing.append("dingtalk_ai_table.operator_id or operator_user_id")
    return missing


def list_fields(dingtalk: DingTalkSettings, ai_table: DingTalkAITableSettings) -> Dict[str, Any]:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return {"ok": False, "message": f"missing fields: {', '.join(missing)}"}
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.get(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/fields",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        timeout=8,
    )
    raise_for_dingtalk_error(response)
    return {"ok": response.is_success, "message": f"DingTalk AI table responded with HTTP {response.status_code}", "payload": response.json()}


def list_sheets(dingtalk: DingTalkSettings, ai_table: DingTalkAITableSettings) -> Dict[str, Any]:
    missing = []
    for name, value in {
        "dingtalk.client_id": dingtalk.client_id,
        "dingtalk.client_secret": dingtalk.client_secret,
        "dingtalk_ai_table.base_id": ai_table.base_id,
    }.items():
        if not value:
            missing.append(name)
    if not ai_table.operator_id and not ai_table.operator_user_id:
        missing.append("dingtalk_ai_table.operator_id or operator_user_id")
    if missing:
        return {"ok": False, "message": f"missing fields: {', '.join(missing)}"}
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.get(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        timeout=8,
    )
    raise_for_dingtalk_error(response)
    return {"ok": response.is_success, "message": f"DingTalk AI table responded with HTTP {response.status_code}", "payload": response.json()}


def create_sheet(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    name: str,
    fields: List[Dict[str, str]],
) -> Dict[str, Any]:
    missing = []
    for field_name, value in {
        "dingtalk.client_id": dingtalk.client_id,
        "dingtalk.client_secret": dingtalk.client_secret,
        "dingtalk_ai_table.base_id": ai_table.base_id,
    }.items():
        if not value:
            missing.append(field_name)
    if not ai_table.operator_id and not ai_table.operator_user_id:
        missing.append("dingtalk_ai_table.operator_id or operator_user_id")
    if missing:
        return {"ok": False, "message": f"missing fields: {', '.join(missing)}"}
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.post(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"name": name, "fields": fields},
        timeout=12,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    return {
        "ok": response.is_success and bool(payload.get("id")),
        "message": f"DingTalk AI table responded with HTTP {response.status_code}",
        "payload": payload,
    }


def create_field(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    name: str,
    field_type: str = "text",
) -> Dict[str, Any]:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return {"ok": False, "message": f"missing fields: {', '.join(missing)}"}
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.post(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/fields",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"name": name, "type": field_type},
        timeout=8,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    return {
        "ok": response.is_success and bool(payload.get("id")),
        "message": f"DingTalk AI table responded with HTTP {response.status_code}",
        "payload": payload,
    }


def update_field(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    field_id: str,
    name: str,
) -> Dict[str, Any]:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return {"ok": False, "message": f"missing fields: {', '.join(missing)}"}
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.put(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/fields/{field_id}",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"name": name},
        timeout=8,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    return {
        "ok": response.is_success,
        "message": f"DingTalk AI table responded with HTTP {response.status_code}",
        "payload": payload,
    }


def ensure_fields(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    fields: Iterable[Dict[str, str]],
) -> Dict[str, Any]:
    existing = list_fields(dingtalk, ai_table)
    if not existing.get("ok"):
        return existing
    existing_names = {field.get("name") for field in existing.get("payload", {}).get("value", [])}
    created = []
    for field in fields:
        name = field["name"]
        if name in existing_names:
            continue
        result = create_field(dingtalk, ai_table, name, field.get("type", "text"))
        if not result.get("ok"):
            return result
        created.append(result["payload"])
    return {
        "ok": True,
        "message": f"created {len(created)} missing fields",
        "payload": {"created": created},
    }


def normalize_url_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    match = MARKDOWN_LINK_PATTERN.match(candidate)
    if match:
        return {"text": match.group("text"), "link": match.group("link")}
    if candidate.startswith(("http://", "https://")):
        return {"text": candidate, "link": candidate}
    return value


def add_records(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    field_records: Iterable[Dict[str, Any]],
) -> AITableResult:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return AITableResult(status="skipped", message=f"missing fields: {', '.join(missing)}", record_ids=[])
    records = [{"fields": record} for record in field_records if record]
    if not records:
        return AITableResult(status="skipped", message="no records to push", record_ids=[])
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.post(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/records",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"records": records},
        timeout=20,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    values = payload.get("value") or []
    record_ids = [str(item.get("id")) for item in values if isinstance(item, dict) and item.get("id")]
    if response.is_success and record_ids:
        return AITableResult(status="sent", message=f"created {len(record_ids)} DingTalk AI table records", record_ids=record_ids)
    return AITableResult(status="failed", message=str(payload), record_ids=record_ids)


def list_records(dingtalk: DingTalkSettings, ai_table: DingTalkAITableSettings, page_size: int = 100) -> List[Dict[str, Any]]:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        raise RuntimeError(f"missing fields: {', '.join(missing)}")
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    records: List[Dict[str, Any]] = []
    next_token = ""
    while True:
        response = httpx.post(
            f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/records/list",
            params={"operatorId": operator_id},
            headers={"x-acs-dingtalk-access-token": token},
            json={"maxResults": page_size, "nextToken": next_token},
            timeout=12,
        )
        raise_for_dingtalk_error(response)
        payload: Dict[str, Any] = response.json()
        records.extend(payload.get("records") or [])
        if not payload.get("hasMore"):
            break
        next_token = str(payload.get("nextToken") or "")
        if not next_token:
            break
    return records


def update_records(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    records: Iterable[Dict[str, Any]],
) -> AITableResult:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return AITableResult(status="skipped", message=f"missing fields: {', '.join(missing)}", record_ids=[])
    payload_records = [record for record in records if record.get("id") and record.get("fields")]
    if not payload_records:
        return AITableResult(status="skipped", message="no records to update", record_ids=[])
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.put(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/records",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"records": payload_records},
        timeout=20,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    values = payload.get("value") or []
    record_ids = [str(item.get("id")) for item in values if isinstance(item, dict) and item.get("id")]
    if response.is_success:
        return AITableResult(status="sent", message=f"updated {len(record_ids)} DingTalk AI table records", record_ids=record_ids)
    return AITableResult(status="failed", message=str(payload), record_ids=record_ids)


def normalize_news_record(item: Dict[str, Any], mapping: Dict[str, str], operator: str = "") -> Dict[str, Any]:
    release_date = item.get("releaseDate") or item.get("published_at") or item.get("publishedAt") or ""
    if isinstance(release_date, (int, float)):
        release_date = datetime.fromtimestamp(release_date / 1000, timezone.utc).date().isoformat()
    fields = {
        mapping.get("no", "No"): item.get("No") or item.get("id") or item.get("record_id") or "",
        mapping.get("category", "Section"): item.get("Category") or item.get("section") or "",
        mapping.get("subject", "Headline"): item.get("Subject") or item.get("title") or "",
        mapping.get("tag", "Label"): item.get("Tag") or item.get("label") or "",
        mapping.get("link", "Source URL"): normalize_url_cell(item.get("Link") or item.get("url") or ""),
        mapping.get("source", "Source"): item.get("Link_Domain") or item.get("source") or "",
        mapping.get("release_date", "Published At"): release_date,
        mapping.get("status", "Review Status"): item.get("Status") or item.get("status") or "待处理",
        mapping.get("operator", "Operator"): item.get("Operator") or item.get("operator") or operator,
        mapping.get("publish_status", "Publish Status"): item.get("Publish Status")
        or item.get("publish_status")
        or "未发送",
        mapping.get("sent_at", "Sent At"): item.get("Sent At") or item.get("sent_at") or "",
        mapping.get("search_provider", "Search Provider"): item.get("Search Provider")
        or item.get("search_provider")
        or item.get("provider")
        or "",
        mapping.get("search_query", "Search Query"): item.get("Search Query")
        or item.get("search_query")
        or item.get("query")
        or "",
        mapping.get("search_batch", "Search Batch"): item.get("Search Batch")
        or item.get("search_batch")
        or item.get("run_id")
        or "",
        mapping.get("discovery_type", "Discovery Type"): item.get("Discovery Type")
        or item.get("discovery_type")
        or "",
        mapping.get("first_seen_at", "First Seen At"): item.get("First Seen At")
        or item.get("first_seen_at")
        or "",
    }
    return {key: value for key, value in fields.items() if key and value != ""}


def add_news_records(
    dingtalk: DingTalkSettings,
    ai_table: DingTalkAITableSettings,
    items: Iterable[Dict[str, Any]],
) -> AITableResult:
    missing = validate_ai_table_settings(dingtalk, ai_table)
    if missing:
        return AITableResult(status="skipped", message=f"missing fields: {', '.join(missing)}", record_ids=[])
    operator = ai_table.operator_user_id or ai_table.operator_id
    records = [{"fields": normalize_news_record(item, ai_table.field_mapping, operator)} for item in items]
    records = [record for record in records if record["fields"]]
    if not records:
        return AITableResult(status="skipped", message="no records to push", record_ids=[])
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    operator_id = resolve_operator_id(dingtalk, ai_table)
    base_id = extract_base_id(ai_table.base_id)
    response = httpx.post(
        f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{ai_table.sheet_id}/records",
        params={"operatorId": operator_id},
        headers={"x-acs-dingtalk-access-token": token},
        json={"records": records},
        timeout=12,
    )
    raise_for_dingtalk_error(response)
    payload: Dict[str, Any] = response.json()
    values = payload.get("value") or []
    record_ids = [str(item.get("id")) for item in values if isinstance(item, dict) and item.get("id")]
    if response.is_success and record_ids:
        return AITableResult(status="sent", message=f"created {len(record_ids)} DingTalk AI table records", record_ids=record_ids)
    return AITableResult(status="failed", message=str(payload), record_ids=record_ids)
