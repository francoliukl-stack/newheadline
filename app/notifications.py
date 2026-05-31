from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Dict
from urllib.parse import quote_plus

import httpx

from .models import DingTalkSettings


@dataclass
class NotificationResult:
    status: str
    message: str


def dingtalk_signed_url(webhook_url: str, signing_secret: str, timestamp_ms: int) -> str:
    if not signing_secret:
        return webhook_url
    string_to_sign = f"{timestamp_ms}\n{signing_secret}".encode("utf-8")
    digest = hmac.new(signing_secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp_ms}&sign={sign}"


def build_fetch_completion_message(
    status: str,
    result_count: int,
    provider: str,
    message: str,
) -> str:
    title = "新闻抓取完成" if status == "success" else "新闻抓取失败"
    return "\n".join(
        [
            f"【{title}】",
            f"状态：{status}",
            f"来源：{provider or '-'}",
            f"结果数：{result_count}",
            f"说明：{message or '-'}",
        ]
    )


def send_daily_fetch_notification(
    dingtalk: DingTalkSettings,
    status: str,
    result_count: int,
    provider: str,
    message: str,
) -> NotificationResult:
    if dingtalk.delivery_mode == "app":
        return send_dingtalk_app_notification(dingtalk, status, result_count, provider, message)
    if not dingtalk.daily_webhook_url:
        return NotificationResult(status="skipped", message="daily DingTalk webhook is not configured")
    return send_dingtalk_webhook_text(
        dingtalk.daily_webhook_url,
        dingtalk.daily_signing_secret,
        build_fetch_completion_message(status, result_count, provider, message),
    )


def send_dingtalk_webhook_text(webhook_url: str, signing_secret: str, content: str) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    try:
        response = httpx.post(
            url,
            json={"msgtype": "text", "text": {"content": content}},
            timeout=8,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    if response.is_success:
        return NotificationResult(status="sent", message=f"DingTalk responded with HTTP {response.status_code}")
    return NotificationResult(status="failed", message=f"DingTalk responded with HTTP {response.status_code}")


def send_dingtalk_webhook_markdown(
    webhook_url: str,
    signing_secret: str,
    title: str,
    content: str,
) -> NotificationResult:
    if not webhook_url:
        return NotificationResult(status="skipped", message="DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(webhook_url, signing_secret, timestamp_ms)
    try:
        response = httpx.post(
            url,
            json={"msgtype": "markdown", "markdown": {"title": title, "text": content}},
            timeout=8,
        )
    except httpx.HTTPError as exc:
        return NotificationResult(status="failed", message=str(exc))
    if response.is_success:
        return NotificationResult(status="sent", message=f"DingTalk responded with HTTP {response.status_code}")
    return NotificationResult(status="failed", message=f"DingTalk responded with HTTP {response.status_code}")


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
    content = build_fetch_completion_message(status, result_count, provider, message)
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
