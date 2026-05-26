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
    if not dingtalk.daily_webhook_url:
        return NotificationResult(status="skipped", message="daily DingTalk webhook is not configured")
    timestamp_ms = int(time.time() * 1000)
    url = dingtalk_signed_url(dingtalk.daily_webhook_url, dingtalk.daily_signing_secret, timestamp_ms)
    content = build_fetch_completion_message(status, result_count, provider, message)
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
