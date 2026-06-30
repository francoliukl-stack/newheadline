from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import httpx

from .models import DingTalkSettings


@dataclass
class NotificationResult:
    status: str
    message: str


def _dingtalk_webhook_result(response: httpx.Response) -> NotificationResult:
    message = f"DingTalk responded with HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not response.is_success:
        return NotificationResult(status="failed", message=f"{message}: {payload}" if payload else message)
    if isinstance(payload, dict):
        errcode = payload.get("errcode")
        if errcode not in (None, 0, "0"):
            return NotificationResult(status="failed", message=f"{message}: {payload}")
    return NotificationResult(status="sent", message=message)


def build_dingtalk_ai_table_url(base_id: str) -> str:
    candidate = base_id.strip()
    if not candidate:
        return ""
    if candidate.startswith(("http://", "https://")):
        return candidate
    return f"https://alidocs.dingtalk.com/i/nodes/{quote(candidate, safe='')}"


def build_dingtalk_approval_url(base_id: str, approval_view_url: str = "") -> str:
    return approval_view_url.strip() or build_dingtalk_ai_table_url(base_id)


def dingtalk_signed_url(webhook_url: str, signing_secret: str, timestamp_ms: int) -> str:
    if not signing_secret:
        return webhook_url
    string_to_sign = f"{timestamp_ms}\n{signing_secret}".encode("utf-8")
    digest = hmac.new(signing_secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp_ms}&sign={sign}"


def parse_at_mobiles(value: str) -> List[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def with_mobile_mentions(content: str, at_mobiles: str = "") -> tuple[str, Dict[str, object]]:
    mobiles = parse_at_mobiles(at_mobiles)
    if not mobiles:
        return content, {"atMobiles": [], "isAtAll": False}
    prefix = " ".join(f"@{mobile}" for mobile in mobiles)
    if prefix not in content:
        content = f"{prefix}\n{content}"
    return content, {"atMobiles": mobiles, "isAtAll": False}


def build_fetch_completion_message(
    status: str,
    result_count: int,
    provider: str,
    message: str,
    approval_url: str = "",
) -> str:
    titles = {
        "success": "新闻采编完成",
        "degraded": "新闻采编部分完成",
        "failed": "新闻采编异常",
    }
    title = titles.get(status, "新闻采编状态更新")
    detail = summarize_ingest_message(message)
    lines = [
        f"【{title}】",
        f"状态：{'核心流程完成，附加步骤延后' if status == 'degraded' else status}",
        f"搜索来源：{provider or '-'}",
        f"候选新闻：{result_count}",
        f"说明：{detail}",
    ]
    if approval_url:
        lines.extend(["", "点击进入 News 表审核：", approval_url])
    return "\n".join(lines)


def summarize_ingest_message(message: str) -> str:
    raw = str(message or "").strip()
    if "Forbidden.AccessDenied.QpsLimitForApi" in raw or "QpsLimit" in raw:
        if "eventize_news.py" in raw:
            return "新闻搜索和 News 入库已完成；钉钉 AI 表格临时限流，Event Cases 聚合延后。系统会在后续任务重试，无需手工重新抓取。"
        return "钉钉 AI 表格临时限流；系统已自动退避重试。若后续仍失败，将保留缓存并再次同步。"
    if "eventize_news.py failed" in raw:
        return "新闻搜索和 News 入库已完成；Event Cases 聚合延后。系统会在后续任务重试，详细错误已记录在运行日志。"
    first_line = raw.split("Traceback", 1)[0].strip().replace("unexpected error:", "").strip()
    if not first_line:
        first_line = "详细错误已记录在运行日志。"
    if len(first_line) > 240:
        first_line = f"{first_line[:237]}..."
    return first_line


def send_daily_fetch_notification(
    dingtalk: DingTalkSettings,
    status: str,
    result_count: int,
    provider: str,
    message: str,
    approval_url: str = "",
) -> NotificationResult:
    if dingtalk.delivery_mode == "app":
        return send_dingtalk_app_notification(dingtalk, status, result_count, provider, message, approval_url)
    if not dingtalk.daily_webhook_url:
        return NotificationResult(status="skipped", message="daily DingTalk webhook is not configured")
    return send_dingtalk_webhook_text(
        dingtalk.daily_webhook_url,
        dingtalk.daily_signing_secret,
        build_fetch_completion_message(status, result_count, provider, message, approval_url),
        dingtalk.at_mobiles,
    )


def send_ingest_completion_notification(
    dingtalk: DingTalkSettings,
    status: str,
    result_count: int,
    provider: str,
    message: str,
    approval_url: str = "",
) -> NotificationResult:
    """Keep successful ingest audit-only; notify operations only on failure."""
    if status == "success":
        return NotificationResult(status="skipped", message="successful ingest is recorded in RunLog/Audit Trail only")
    return send_daily_fetch_notification(dingtalk, status, result_count, provider, message, approval_url)


def send_dingtalk_webhook_text(
    webhook_url: str,
    signing_secret: str,
    content: str,
    at_mobiles: str = "",
) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    content, at_payload = with_mobile_mentions(content, at_mobiles)
    try:
        response = httpx.post(
            url,
            json={"msgtype": "text", "text": {"content": content}, "at": at_payload},
            timeout=8,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    return _dingtalk_webhook_result(response)


def send_dingtalk_webhook_markdown(
    webhook_url: str,
    signing_secret: str,
    title: str,
    content: str,
    at_mobiles: str = "",
) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    content, at_payload = with_mobile_mentions(content, at_mobiles)
    try:
        response = httpx.post(
            url,
            json={"msgtype": "markdown", "markdown": {"title": title, "text": content}, "at": at_payload},
            timeout=8,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    return _dingtalk_webhook_result(response)


def send_dingtalk_action_card(
    webhook_url: str,
    signing_secret: str,
    title: str,
    content: str,
    button_title: str,
    button_url: str,
    at_mobiles: str = "",
) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    content, at_payload = with_mobile_mentions(content, at_mobiles)
    payload = {
        "msgtype": "actionCard",
        "actionCard": {
            "title": title,
            "text": content,
            "singleTitle": button_title,
            "singleURL": button_url,
            "btnOrientation": "0",
        },
        "at": at_payload,
    }
    try:
        response = httpx.post(url, json=payload, timeout=8)
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    return _dingtalk_webhook_result(response)


def upload_dingtalk_media(dingtalk: DingTalkSettings, file_path: Path, media_type: str = "image") -> str:
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    with file_path.open("rb") as file_obj:
        response = httpx.post(
            "https://oapi.dingtalk.com/media/upload",
            params={"access_token": token, "type": media_type},
            files={"media": (file_path.name, file_obj, "image/png")},
            timeout=20,
        )
    response.raise_for_status()
    payload: Dict[str, Any] = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(str(payload))
    media_id = payload.get("media_id")
    if not isinstance(media_id, str) or not media_id:
        raise RuntimeError("DingTalk media_id missing from upload response")
    return media_id


def build_dingtalk_media_download_url(dingtalk: DingTalkSettings, media_id: str) -> str:
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    return f"https://oapi.dingtalk.com/media/downloadFile?access_token={quote(token, safe='')}&media_id={quote(media_id, safe='')}"


def send_dingtalk_webhook_image(
    webhook_url: str,
    signing_secret: str,
    pic_url: str,
    at_mobiles: str = "",
) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    _, at_payload = with_mobile_mentions("", at_mobiles)
    try:
        response = httpx.post(
            url,
            json={"msgtype": "image", "image": {"picURL": pic_url}, "at": at_payload},
            timeout=8,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    message = f"DingTalk responded with HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.is_success and payload.get("errcode", 0) == 0:
        return NotificationResult(status="sent", message=message)
    if payload:
        message = f"{message}: {payload}"
    return NotificationResult(status="failed", message=message)


def send_dingtalk_robot_group_image(
    dingtalk: DingTalkSettings,
    webhook_url: str,
    image_url: str,
) -> NotificationResult:
    robot_token = parse_qs(urlparse(webhook_url).query).get("access_token", [""])[0]
    if not robot_token:
        return NotificationResult(status="skipped", message="DingTalk robot token is missing from webhook URL")
    token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
    try:
        response = httpx.post(
            "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
            headers={"x-acs-dingtalk-access-token": token},
            json={
                "token": robot_token,
                "msgKey": "sampleImageMsg",
                "msgParam": json.dumps({"photoURL": image_url}, ensure_ascii=False),
            },
            timeout=12,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    message = f"DingTalk robot group image responded with HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.is_success and payload.get("processQueryKey"):
        return NotificationResult(status="sent", message=f"{message}: processQueryKey={payload.get('processQueryKey')}")
    if payload:
        message = f"{message}: {payload}"
    return NotificationResult(status="failed", message=message)


def get_dingtalk_access_token(client_id: str, client_secret: str) -> str:
    response = httpx.get(
        "https://oapi.dingtalk.com/gettoken",
        params={"appkey": client_id, "appsecret": client_secret},
        timeout=8,
    )
    response.raise_for_status()
    payload: Dict[str, object] = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(str(payload))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("DingTalk access_token missing from response")
    return token


def send_dingtalk_app_notification(
    dingtalk: DingTalkSettings,
    status: str,
    result_count: int,
    provider: str,
    message: str,
    approval_url: str = "",
) -> NotificationResult:
    missing = [
        name
        for name, value in {
            "agent_id": dingtalk.agent_id,
            "client_id": dingtalk.client_id,
            "client_secret": dingtalk.client_secret,
            "user_ids": dingtalk.user_ids,
        }.items()
        if not value
    ]
    if missing:
        return NotificationResult(status="skipped", message=f"missing DingTalk app fields: {', '.join(missing)}")
    content = build_fetch_completion_message(status, result_count, provider, message, approval_url)
    try:
        token = get_dingtalk_access_token(dingtalk.client_id, dingtalk.client_secret)
        response = httpx.post(
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": token},
            json={
                "agent_id": dingtalk.agent_id,
                "userid_list": dingtalk.user_ids,
                "msg": {"msgtype": "text", "text": {"content": content}},
            },
            timeout=8,
        )
        response.raise_for_status()
        payload: Dict[str, object] = response.json()
    except Exception as exc:
        return NotificationResult(status="failed", message=str(exc))
    if payload.get("errcode") == 0:
        return NotificationResult(status="sent", message=f"DingTalk app task created: {payload.get('task_id', '-')}")
    return NotificationResult(status="failed", message=str(payload))
