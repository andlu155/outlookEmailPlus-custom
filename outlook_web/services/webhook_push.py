from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from outlook_web.repositories import settings as settings_repo
from outlook_web.services import proxy as proxy_service

logger = logging.getLogger(__name__)

MAX_WEBHOOK_BODY_LENGTH = 4000


class WebhookPushError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        message_en: str,
        status: int = 502,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.message_en = message_en
        self.status = status
        self.details = details


def validate_webhook_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        raise WebhookPushError(
            "WEBHOOK_URL_REQUIRED",
            "启用 Webhook 通知时必须填写 Webhook URL",
            message_en="Webhook URL is required when webhook notification is enabled",
            status=400,
        )

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebhookPushError(
            "WEBHOOK_URL_INVALID",
            "Webhook URL 必须以 http:// 或 https:// 开头",
            message_en="Webhook URL must start with http:// or https://",
            status=400,
            details=normalized,
        )
    return normalized


def _stringify(value: Any, default: str = "-") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_received_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if raw.endswith("Z"):
        raw = raw[:-1]
    return raw.split(".")[0]


def _build_body_excerpt(message: dict[str, Any]) -> str:
    text = str(message.get("content") or message.get("preview") or "").strip()
    if not text:
        return "(正文为空)"
    if len(text) > MAX_WEBHOOK_BODY_LENGTH:
        return text[:MAX_WEBHOOK_BODY_LENGTH].rstrip() + "\n\n...[truncated]"
    return text


def build_business_webhook_text(source: dict[str, Any], message: dict[str, Any]) -> str:
    source_type_text = "普通邮箱" if source.get("source_type") == "account" else "临时邮箱"
    return (
        f"来源邮箱: {_stringify(source.get('label') or source.get('email'))}\n"
        f"来源类型: {source_type_text}\n"
        f"文件夹: {_stringify(message.get('folder'), default='inbox')}\n"
        f"发件人: {_stringify(message.get('sender'))}\n"
        f"主题: {_stringify(message.get('subject'), default='无主题')}\n"
        f"时间: {_normalize_received_time(message.get('received_at'))}\n"
        f"正文摘要:\n{_build_body_excerpt(message)}"
    )


def _safe_url_for_log(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"


def send_webhook_message(
    *,
    url: str,
    token: str,
    text_body: str,
    timeout_sec: int = 10,
    retry: int = 1,
) -> None:
    target_url = validate_webhook_url(url)
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
    }
    if str(token or "").strip():
        headers["X-Webhook-Token"] = str(token).strip()

    proxy_url, force_direct = proxy_service.resolve_system_proxy(target_url=target_url)
    proxy_kwargs = proxy_service.build_requests_proxy_kwargs(proxy_url, force_direct=force_direct)
    attempts = max(0, int(retry)) + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            response = requests.post(
                target_url,
                data=text_body.encode("utf-8"),
                headers=headers,
                timeout=timeout_sec,
                **proxy_kwargs,
            )
            if 200 <= response.status_code < 300:
                return
            last_error = WebhookPushError(
                "WEBHOOK_SEND_FAILED",
                "Webhook 发送失败",
                message_en="Failed to send webhook message",
                status=502,
                details=f"status={response.status_code} body={(response.text or '')[:200]}",
            )
        except requests.RequestException as exc:
            last_error = WebhookPushError(
                "WEBHOOK_SEND_FAILED",
                "Webhook 发送失败",
                message_en="Failed to send webhook message",
                status=502,
                details=str(exc),
            )

    logger.warning(
        "[webhook_push] send failed url=%s attempts=%s err=%s",
        _safe_url_for_log(target_url),
        attempts,
        getattr(last_error, "details", str(last_error) if last_error else "unknown"),
    )
    if isinstance(last_error, WebhookPushError):
        raise last_error
    raise WebhookPushError(
        "WEBHOOK_SEND_FAILED",
        "Webhook 发送失败",
        message_en="Failed to send webhook message",
        status=502,
    )


def send_business_webhook_notification(
    source: dict[str, Any],
    message: dict[str, Any],
    *,
    url: str,
    token: str,
) -> None:
    text_body = build_business_webhook_text(source, message)
    send_webhook_message(url=url, token=token, text_body=text_body, timeout_sec=10, retry=1)


def send_test_webhook_message() -> dict[str, Any]:
    enabled = settings_repo.get_webhook_notification_enabled()
    url = settings_repo.get_webhook_notification_url()
    token = settings_repo.get_webhook_notification_token()

    if (not enabled) or (not url):
        raise WebhookPushError(
            "WEBHOOK_NOT_CONFIGURED",
            "请先完成 Webhook 配置并保存",
            message_en="Webhook notification is not configured",
            status=400,
        )

    validate_webhook_url(url)
    test_source = {
        "source_type": "account",
        "source_key": "account:webhook-test@example.com",
        "email": "webhook-test@example.com",
        "label": "webhook-test@example.com",
    }
    test_message = {
        "message_id": "webhook-test-message",
        "subject": "[Outlook Email Plus] Webhook 测试消息",
        "sender": "system@outlook-email-plus.local",
        "received_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "preview": "如果你收到这条消息，说明 Webhook 通知配置正确。",
        "content": "如果你收到这条消息，说明 Webhook 通知配置正确。",
        "folder": "inbox",
    }
    text_body = build_business_webhook_text(test_source, test_message)

    try:
        send_webhook_message(url=url, token=token, text_body=text_body, timeout_sec=10, retry=1)
    except WebhookPushError as exc:
        raise WebhookPushError(
            "WEBHOOK_TEST_SEND_FAILED",
            "Webhook 测试发送失败",
            message_en="Failed to send webhook test message",
            status=exc.status,
            details=exc.details,
        ) from exc

    return {
        "url": _safe_url_for_log(url),
    }
