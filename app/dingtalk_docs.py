from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .dingtalk_ai_table import raise_for_dingtalk_error, resolve_operator_id, retryable_request
from .models import AppSettings
from .notifications import get_dingtalk_access_token
from .storage import SettingsStore


API_BASE = "https://api.dingtalk.com"


@dataclass
class DingTalkDocument:
    title: str
    url: str
    node_id: str
    doc_key: str
    workspace_id: str
    folder_node_id: str


def _headers(token: str) -> Dict[str, str]:
    return {"x-acs-dingtalk-access-token": token}


def _value(payload: Dict[str, Any]) -> Any:
    return payload.get("result") or payload.get("workspace") or payload.get("node") or payload


def _node_id(payload: Dict[str, Any]) -> str:
    value = _value(payload)
    if not isinstance(value, dict):
        return ""
    return str(value.get("nodeId") or value.get("id") or value.get("node_id") or "")


def _doc_key(payload: Dict[str, Any]) -> str:
    value = _value(payload)
    if not isinstance(value, dict):
        return ""
    return str(value.get("docKey") or value.get("documentId") or value.get("resourceId") or _node_id(payload))


def _doc_url(payload: Dict[str, Any]) -> str:
    value = _value(payload)
    if not isinstance(value, dict):
        return ""
    return str(value.get("url") or value.get("link") or "")


def _is_folder(node: Dict[str, Any]) -> bool:
    text = " ".join(str(node.get(key) or "") for key in ("nodeType", "docType", "type", "resourceType")).upper()
    return "FOLDER" in text or "DIR" in text


def _node_title(node: Dict[str, Any]) -> str:
    return str(node.get("title") or node.get("name") or "").strip()


def extract_folder_node_id(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        return candidate
    parsed = urlparse(candidate)
    parts = [part for part in parsed.path.split("/") if part]
    if "folders" in parts:
        index = parts.index("folders")
        if index + 1 < len(parts):
            return parts[index + 1]
    if "nodes" in parts:
        index = parts.index("nodes")
        if index + 1 < len(parts):
            return parts[index + 1]
    return candidate


def _request_json(method: str, url: str, token: str, **kwargs: Any) -> Dict[str, Any]:
    response = retryable_request(method, url, headers=_headers(token), timeout=12, **kwargs)
    raise_for_dingtalk_error(response)
    try:
        payload: Dict[str, Any] = response.json()
    except ValueError as exc:
        raise RuntimeError(f"DingTalk returned non-JSON response: HTTP {response.status_code}") from exc
    return payload


def _operator_and_token(settings: AppSettings) -> Tuple[str, str]:
    token = get_dingtalk_access_token(settings.dingtalk.client_id, settings.dingtalk.client_secret)
    operator_id = resolve_operator_id(settings.dingtalk, settings.dingtalk_ai_table)
    if not operator_id:
        raise RuntimeError("DingTalk operator_id is missing")
    return operator_id, token


def _mine_workspace(settings: AppSettings, operator_id: str, token: str) -> Dict[str, Any]:
    payload = _request_json(
        "GET",
        f"{API_BASE}/v2.0/wiki/mineWorkspaces",
        token,
        params={"operatorId": operator_id},
    )
    workspace = payload.get("workspace") or payload.get("result") or {}
    if not isinstance(workspace, dict) or not workspace.get("workspaceId"):
        raise RuntimeError("DingTalk mine workspace is missing from response")
    return workspace


def _workspace_root(settings: AppSettings, operator_id: str, token: str) -> Tuple[str, str]:
    ai_table = settings.dingtalk_ai_table
    workspace_id = ai_table.report_docs_workspace_id.strip()
    root_node_id = ai_table.report_docs_root_node_id.strip()
    if workspace_id and root_node_id:
        return workspace_id, root_node_id

    workspace = _mine_workspace(settings, operator_id, token)
    return str(workspace.get("workspaceId") or ""), str(workspace.get("rootNodeId") or "")


def list_workspace_nodes(workspace_id: str, parent_node_id: str, operator_id: str, token: str) -> List[Dict[str, Any]]:
    response = _request_json(
        "GET",
        f"{API_BASE}/v2.0/wiki/nodes",
        token,
        params={"operatorId": operator_id, "parentNodeId": parent_node_id, "maxResults": 100},
    )
    nodes = response.get("nodes") or response.get("value") or response.get("result") or []
    return nodes if isinstance(nodes, list) else []


def create_workspace_node(
    workspace_id: str,
    parent_node_id: str,
    title: str,
    doc_type: str,
    operator_id: str,
    token: str,
) -> Dict[str, Any]:
    payload = {"name": title, "docType": doc_type, "operatorId": operator_id}
    if parent_node_id:
        payload["parentNodeId"] = parent_node_id
    return _request_json(
        "POST",
        f"{API_BASE}/v1.0/doc/workspaces/{workspace_id}/docs",
        token,
        json=payload,
    )


def ensure_report_folder(settings: AppSettings, store: Optional[SettingsStore] = None) -> Tuple[str, str]:
    operator_id, token = _operator_and_token(settings)
    workspace_id, root_node_id = _workspace_root(settings, operator_id, token)
    if not workspace_id or not root_node_id:
        raise RuntimeError("DingTalk report workspace or root node is missing")

    folder_name = settings.dingtalk_ai_table.report_docs_folder_name.strip() or "GBSS Research Reports"
    folder_url = settings.dingtalk_ai_table.report_docs_folder_url.strip()
    folder_node_id = settings.dingtalk_ai_table.report_docs_folder_node_id.strip() or extract_folder_node_id(folder_url)
    if not folder_node_id:
        try:
            nodes = list_workspace_nodes(workspace_id, root_node_id, operator_id, token)
        except RuntimeError:
            nodes = []
        for node in nodes:
            if _node_title(node) == folder_name and _is_folder(node):
                folder_node_id = _node_id(node)
                break

    if not folder_node_id:
        payload = create_workspace_node(workspace_id, root_node_id, folder_name, "FOLDER", operator_id, token)
        folder_node_id = _node_id(payload)
    if not folder_node_id:
        raise RuntimeError("DingTalk report folder node id is missing")

    ai_table = settings.dingtalk_ai_table
    if (
        ai_table.report_docs_workspace_id != workspace_id
        or ai_table.report_docs_root_node_id != root_node_id
        or ai_table.report_docs_folder_node_id != folder_node_id
        or ai_table.report_docs_folder_url != folder_url
        or ai_table.report_docs_folder_name != folder_name
    ):
        ai_table.report_docs_workspace_id = workspace_id
        ai_table.report_docs_root_node_id = root_node_id
        ai_table.report_docs_folder_node_id = folder_node_id
        ai_table.report_docs_folder_url = folder_url
        ai_table.report_docs_folder_name = folder_name
        if store:
            store.save(settings)
    return workspace_id, folder_node_id


def overwrite_document_content(doc_key: str, markdown: str, operator_id: str, token: str) -> None:
    url = f"{API_BASE}/v1.0/doc/suites/documents/{doc_key}/overwriteContent"
    try:
        _request_json(
            "POST",
            url,
            token,
            params={"operatorId": operator_id},
            json={"content": markdown, "dataType": "markdown"},
        )
        return
    except Exception as first_error:
        try:
            _request_json(
                "POST",
                url,
                token,
                json={"operatorId": operator_id, "docContent": markdown, "contentType": "markdown"},
            )
            return
        except Exception:
            raise first_error


def create_report_document(
    settings: AppSettings,
    store: Optional[SettingsStore],
    title: str,
    markdown: str,
) -> DingTalkDocument:
    operator_id, token = _operator_and_token(settings)
    workspace_id, folder_node_id = ensure_report_folder(settings, store)
    settings = store.load(masked=False) if store else settings
    payload = create_workspace_node(workspace_id, folder_node_id, title, "DOC", operator_id, token)
    node_id = _node_id(payload)
    doc_key = _doc_key(payload)
    url = _doc_url(payload)
    if not doc_key:
        raise RuntimeError(f"DingTalk document key is missing from response: {payload}")
    overwrite_document_content(doc_key, markdown, operator_id, token)
    if not url and node_id:
        url = f"https://alidocs.dingtalk.com/i/nodes/{node_id}"
    return DingTalkDocument(
        title=title,
        url=url,
        node_id=node_id,
        doc_key=doc_key,
        workspace_id=workspace_id,
        folder_node_id=folder_node_id,
    )
