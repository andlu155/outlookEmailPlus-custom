from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from outlook_web.audit import log_audit
from outlook_web.db import get_db
from outlook_web.errors import build_error_response
from outlook_web.security.auth import login_required
from outlook_web.services.temp_email_content import (
    build_inline_resource_map,
    load_temp_email_payload,
    rewrite_html_with_inline_resources,
)
from outlook_web.services.temp_mail_service import TempMailError, get_temp_mail_service

logger = logging.getLogger(__name__)
temp_mail_service = get_temp_mail_service()


def _parse_bool_flag(value: Any, default: bool = False) -> bool:
    """解析请求中的布尔开关，兼容 bool / 数字 / 字符串。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_TEMP_VERIFICATION_CODE_SOURCES = {"subject", "content", "html", "all"}
_TEMP_VERIFICATION_FIELDS = {"code", "link", "any"}


def _expected_field_for_temp_verification_request(field: str) -> str | None:
    if field == "code":
        return "verification_code"
    if field == "link":
        return "verification_link"
    return None


# ==================== 临时邮箱 API ====================


def _should_refresh_temp_email_detail(msg: dict[str, Any] | None) -> bool:
    # 本地已有记录也可能仍需回源：例如只缓存了简化正文，或 HTML 中存在 cid: 引用但
    # raw_content 里还没有可解析的内联资源映射，此时必须补抓详情才能正确显示图片。
    if not msg:
        return True

    content = str(msg.get("content") or "").strip()
    html_content = str(msg.get("html_content") or "").strip()
    if not content and not html_content:
        return True

    raw_payload = load_temp_email_payload(msg.get("raw_content"))
    inline_resources = build_inline_resource_map(raw_payload)
    if "cid:" in html_content.lower() and not inline_resources:
        return True

    return False


@login_required
def api_get_temp_emails() -> Any:
    """获取所有临时邮箱"""
    emails = temp_mail_service.list_user_mailboxes()
    return jsonify({"success": True, "emails": emails})


@login_required
def api_get_temp_email_options() -> Any:
    try:
        provider_name = str(request.args.get("provider_name") or "").strip() or None
        options = temp_mail_service.get_options(provider_name=provider_name)
        return jsonify({"success": True, "options": options})
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Temp mail options are unavailable",
        )


@login_required
def api_generate_temp_email() -> Any:
    """生成新的临时邮箱"""
    data = request.json or {}
    prefix = data.get("prefix")
    domain = data.get("domain")
    provider_name = str(data.get("provider_name") or "").strip() or None
    try:
        mailbox = temp_mail_service.generate_user_mailbox(prefix=prefix, domain=domain, provider_name=provider_name)
        email_addr = mailbox["email"]
        log_audit("create", "temp_email", email_addr, "生成临时邮箱")
        logger.info(f"临时邮箱生成成功: {email_addr}")
        try:
            from outlook_web.repositories import notification_state as notification_state_repo
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.services import notification_dispatch

            if settings_repo.get_setting("email_notification_enabled", "false").lower() == "true":
                notification_state_cursor = notification_dispatch.utc_now_iso()
                notification_state_repo.upsert_cursor(
                    notification_dispatch.CHANNEL_EMAIL,
                    notification_dispatch.SOURCE_TEMP_EMAIL,
                    notification_dispatch.build_source_key(notification_dispatch.SOURCE_TEMP_EMAIL, email_addr),
                    notification_state_cursor,
                )
        except Exception:
            pass
        return jsonify(
            {
                "success": True,
                "email": email_addr,
                "mailbox": mailbox,
                "message": "临时邮箱创建成功",
                "message_en": "Temp mailbox created successfully",
            }
        )
    except TempMailError as exc:
        logger.error(f"临时邮箱生成失败: {exc.message}, prefix={prefix}, domain={domain}")
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            details=exc.data,
            message_en="Failed to create temp mailbox. Please try again later",
        )


@login_required
def api_delete_temp_email(email_addr: str) -> Any:
    """删除临时邮箱"""
    try:
        temp_mail_service.delete_mailbox(email_addr)
        log_audit("delete", "temp_email", email_addr, "删除临时邮箱")
        return jsonify(
            {
                "success": True,
                "message": "临时邮箱已删除",
                "message_en": "Temp mailbox deleted",
            }
        )
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Failed to delete temp mailbox",
        )


@login_required
def api_get_temp_email_messages(email_addr: str) -> Any:
    """获取临时邮箱的邮件列表"""
    try:
        sync_remote = _parse_bool_flag(request.args.get("sync_remote"), default=True)
        mailbox = temp_mail_service.get_mailbox(email_addr, view="descriptor")
        messages = temp_mail_service.list_messages(mailbox, sync_remote=sync_remote)
        formatted = [
            {
                "id": msg.get("id"),
                "from": msg.get("from_address", "未知"),
                "subject": msg.get("subject", "无主题"),
                "body_preview": msg.get("content_preview", ""),
                "date": msg.get("created_at", ""),
                "timestamp": msg.get("timestamp", 0),
                "has_html": 1 if msg.get("has_html") else 0,
            }
            for msg in messages
        ]
        provider_name = str(mailbox.get("provider_name") or "").strip() or "temp_mail"
        return jsonify(
            {
                "success": True,
                "emails": formatted,
                "count": len(formatted),
                "method": "Temp Mail",
                "provider": provider_name,
            }
        )
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Failed to fetch messages",
        )


@login_required
def api_get_temp_email_message_detail(email_addr: str, message_id: str) -> Any:
    """获取临时邮件详情"""
    try:
        refresh_if_missing = _parse_bool_flag(request.args.get("refresh_if_missing"), default=True)
        msg = temp_mail_service.get_cached_message_row(email_addr, message_id)
        if refresh_if_missing and _should_refresh_temp_email_detail(msg):
            detail = temp_mail_service.refresh_message_detail(email_addr, message_id)
            msg = temp_mail_service.get_cached_message_row(email_addr, message_id)
        else:
            detail = temp_mail_service.get_message_detail(
                email_addr,
                message_id,
                refresh_if_missing=refresh_if_missing,
            )

        raw_payload = load_temp_email_payload((msg or {}).get("raw_content"))
        inline_resources = build_inline_resource_map(raw_payload)
        has_html = bool(detail.get("has_html") or detail.get("html_content"))
        body = detail.get("html_content") if has_html else detail.get("content", "")
        if has_html and inline_resources:
            body = rewrite_html_with_inline_resources(body or "", inline_resources)

        return jsonify(
            {
                "success": True,
                "email": {
                    "id": detail.get("id"),
                    "from": detail.get("from_address", "未知"),
                    "to": email_addr,
                    "subject": detail.get("subject", "无主题"),
                    "body": body,
                    "body_type": "html" if has_html else "text",
                    "date": detail.get("created_at", ""),
                    "timestamp": detail.get("timestamp", 0),
                    "inline_resources": inline_resources,
                },
            }
        )
    except TempMailError as exc:
        message_en = "Message not found" if exc.status == 404 else "Failed to fetch message detail"
        return build_error_response(exc.code, exc.message, status=exc.status, message_en=message_en)


@login_required
def api_extract_temp_email_verification(email_addr: str) -> Any:
    return _api_extract_temp_email_verification_impl(email_addr)


@login_required
def api_get_temp_email_verification(email_addr: str) -> Any:
    return _api_extract_temp_email_verification_impl(email_addr)


def _api_extract_temp_email_verification_impl(email_addr: str) -> Any:
    request_code_length = (request.args.get("code_length") or "").strip() or None
    request_code_regex = (request.args.get("code_regex") or "").strip() or None
    code_source = (request.args.get("code_source") or "all").strip().lower()
    if code_source not in _TEMP_VERIFICATION_CODE_SOURCES:
        return build_error_response(
            "INVALID_PARAM",
            "参数错误",
            status=400,
            message_en="Invalid parameters",
        )

    field = (request.args.get("field") or "any").strip().lower()
    if field not in _TEMP_VERIFICATION_FIELDS:
        return build_error_response(
            "INVALID_PARAM",
            "field 参数无效",
            status=400,
            message_en="Invalid field parameter",
        )
    expected_field = _expected_field_for_temp_verification_request(field)

    try:
        result = temp_mail_service.extract_verification(
            email_addr,
            code_regex=request_code_regex,
            code_length=request_code_length,
            code_source=code_source,
            expected_field=expected_field,
        )
        return jsonify({"success": True, "data": result, "message": "提取成功"})
    except TempMailError as exc:
        message_en = "Verification info not found" if exc.status == 404 else "Failed to extract verification info"
        return build_error_response(exc.code, exc.message, status=exc.status, message_en=message_en)


@login_required
def api_delete_temp_email_message(email_addr: str, message_id: str) -> Any:
    """删除临时邮件"""
    try:
        temp_mail_service.delete_message(email_addr, message_id)
        log_audit(
            "delete",
            "temp_email_message",
            message_id,
            f"删除临时邮件（email={email_addr}）",
        )
        return jsonify({"success": True, "message": "邮件已删除", "message_en": "Message deleted"})
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Failed to delete message",
        )


@login_required
def api_clear_temp_email_messages(email_addr: str) -> Any:
    """清空临时邮箱的所有邮件"""
    try:
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) as c FROM temp_email_messages WHERE email_address = ?",
            (email_addr,),
        ).fetchone()
        deleted_count = row["c"] if row else 0
        temp_mail_service.clear_messages(email_addr)
        log_audit(
            "delete",
            "temp_email_messages",
            email_addr,
            f"清空临时邮箱邮件（count={deleted_count}）",
        )
        return jsonify({"success": True, "message": "邮件已清空", "message_en": "Messages cleared"})
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Failed to clear messages",
        )
    except Exception:
        return build_error_response(
            "TEMP_EMAIL_MESSAGES_CLEAR_FAILED",
            "清空失败",
            status=500,
            message_en="Failed to clear messages",
        )


@login_required
def api_refresh_temp_email_messages(email_addr: str) -> Any:
    """刷新临时邮箱的邮件"""
    try:
        mailbox = temp_mail_service.get_mailbox(email_addr, view="descriptor")
        existing_ids = {item.get("id") for item in temp_mail_service.list_messages(mailbox, sync_remote=False)}
        messages = temp_mail_service.list_messages(mailbox, sync_remote=True)
        formatted = [
            {
                "id": msg.get("id"),
                "from": msg.get("from_address", "未知"),
                "subject": msg.get("subject", "无主题"),
                "body_preview": msg.get("content_preview", ""),
                "date": msg.get("created_at", ""),
                "timestamp": msg.get("timestamp", 0),
                "has_html": 1 if msg.get("has_html") else 0,
            }
            for msg in messages
        ]
        new_count = len([msg for msg in messages if msg.get("id") not in existing_ids])
        provider_name = str(mailbox.get("provider_name") or "").strip() or "temp_mail"
        return jsonify(
            {
                "success": True,
                "emails": formatted,
                "count": len(formatted),
                "new_count": new_count,
                "method": "Temp Mail",
                "provider": provider_name,
            }
        )
    except TempMailError as exc:
        return build_error_response(
            exc.code,
            exc.message,
            status=exc.status,
            message_en="Failed to fetch messages",
        )
