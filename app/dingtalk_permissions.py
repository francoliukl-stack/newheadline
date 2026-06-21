from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from .dingtalk_ai_table import resolve_operator_id, retryable_request
from .dingtalk_docs import API_BASE, DingTalkDocument
from .models import AppSettings
from .notifications import get_dingtalk_access_token


@dataclass
class PermissionResult:
    status: str
    message: str


def _headers(token: str) -> Dict[str, str]:
    return {"x-acs-dingtalk-access-token": token}


def _json_snippet(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text[:500]
    return str(payload)[:800]


def _url_node_id(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if "nodes" in parts:
        index = parts.index("nodes")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _candidate_ids(document: DingTalkDocument) -> List[str]:
    values = [document.node_id, document.doc_key, _url_node_id(document.url)]
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _current_app_corp_id(token: str, operator_id: str) -> str:
    response = retryable_request(
        "POST",
        f"{API_BASE}/v1.0/storage/currentApps/query",
        headers=_headers(token),
        params={"unionId": operator_id},
        timeout=12,
    )
    if response.is_error:
        raise RuntimeError(f"current app lookup failed: HTTP {response.status_code}: {_json_snippet(response)}")
    payload = response.json()
    app = payload.get("app") or {}
    corp_id = app.get("corpId") if isinstance(app, dict) else ""
    if not isinstance(corp_id, str) or not corp_id:
        raise RuntimeError(f"current app lookup returned no corpId: {payload}")
    return corp_id


def _set_storage_share_scope(token: str, operator_id: str, dentry_id: str) -> PermissionResult:
    response = retryable_request(
        "PUT",
        f"{API_BASE}/v2.0/storage/spaces/dentries/{dentry_id}/permissions/scopes",
        headers=_headers(token),
        params={"unionId": operator_id},
        json={"scope": "ORG_READ", "option": {"canSearch": True}},
        timeout=12,
    )
    if response.is_success:
        return PermissionResult("sent", f"storage share scope ORG_READ applied to {dentry_id}")
    return PermissionResult("failed", f"storage share scope failed for {dentry_id}: HTTP {response.status_code}: {_json_snippet(response)}")


def _add_workspace_doc_org_reader(
    token: str,
    workspace_id: str,
    node_id: str,
    operator_id: str,
    corp_id: str,
) -> PermissionResult:
    response = retryable_request(
        "POST",
        f"{API_BASE}/v1.0/doc/workspaces/{workspace_id}/docs/{node_id}/members",
        headers=_headers(token),
        json={
            "operatorId": operator_id,
            "members": [{"memberId": corp_id, "memberType": "ORG", "roleType": "VIEWER"}],
        },
        timeout=12,
    )
    if response.is_success:
        return PermissionResult("sent", f"workspace doc ORG VIEWER applied to {node_id}")
    return PermissionResult("failed", f"workspace doc org reader failed for {node_id}: HTTP {response.status_code}: {_json_snippet(response)}")


def make_document_org_readable(settings: AppSettings, document: DingTalkDocument) -> PermissionResult:
    """Best effort: make one generated report document readable by org-link recipients."""
    if not document.workspace_id:
        return PermissionResult("skipped", "document workspace id is missing")
    token = get_dingtalk_access_token(settings.dingtalk.client_id, settings.dingtalk.client_secret)
    operator_id = resolve_operator_id(settings.dingtalk, settings.dingtalk_ai_table)
    if not operator_id:
        return PermissionResult("skipped", "operator_id is missing")

    attempts: List[str] = []
    for candidate_id in _candidate_ids(document):
        storage_result = _set_storage_share_scope(token, operator_id, candidate_id)
        if storage_result.status == "sent":
            return storage_result
        attempts.append(storage_result.message)

    try:
        corp_id = _current_app_corp_id(token, operator_id)
    except Exception as exc:
        attempts.append(str(exc))
        return PermissionResult("failed", "; ".join(attempts))

    for candidate_id in _candidate_ids(document):
        doc_result = _add_workspace_doc_org_reader(token, document.workspace_id, candidate_id, operator_id, corp_id)
        if doc_result.status == "sent":
            return doc_result
        attempts.append(doc_result.message)
    return PermissionResult("failed", "; ".join(attempts))
