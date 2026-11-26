from __future__ import annotations

import email
import imaplib
import logging
import re
import socket
from email.header import decode_header
from typing import Any, Dict, List, Optional, Tuple

from outlook_web.errors import build_error_payload, sanitize_error_details
from outlook_web.services import proxy as proxy_service
from outlook_web.services.providers import get_imap_folder_candidates
from outlook_web.utils.common import decode_mime_header, html_to_plain_text

_LOGGER = logging.getLogger("outlook_web.imap_generic")
_UID_TOKEN_RE = re.compile(rb"UID\s+(\d+)", re.IGNORECASE)


def decode_header_value(header_value: str) -> str:
    """解码邮件头字段（兼容多段编码）"""
    return decode_mime_header(header_value)


def _strip_html(html_text: str) -> str:
    if not html_text:
        return ""
    try:
        return html_to_plain_text(html_text)
    except Exception:
        return html_text


def _extract_text_and_html(msg: email.message.Message) -> Tuple[str, str]:
    """提取 text/plain 与 text/html（不含附件 part）。"""
    text_part = ""
    html_part = ""

    def _decode_payload(part: email.message.Message) -> str:
        try:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            if isinstance(payload, (bytes, bytearray)):
                return payload.decode(charset, errors="replace")
            return str(payload) if payload is not None else ""
        except Exception:
            try:
                return str(part.get_payload())
            except Exception:
                return ""

    if msg.is_multipart():
        for part in msg.walk():
            try:
                content_disposition = str(part.get("Content-Disposition", "") or "")
            except Exception:
                content_disposition = ""
            if "attachment" in content_disposition.lower():
                continue

            content_type = (part.get_content_type() or "").lower()
            if content_type == "text/plain" and not text_part:
                text_part = _decode_payload(part)
            elif content_type == "text/html" and not html_part:
                html_part = _decode_payload(part)

            if text_part and html_part:
                break
    else:
        content_type = (msg.get_content_type() or "").lower()
        if content_type == "text/html":
            html_part = _decode_payload(msg)
        else:
            text_part = _decode_payload(msg)

    return text_part or "", html_part or ""


def _has_attachments(msg: email.message.Message) -> bool:
    try:
        if not msg.is_multipart():
            return False
        for part in msg.walk():
            try:
                disp = str(part.get("Content-Disposition", "") or "").lower()
            except Exception:
                disp = ""
            if "attachment" in disp:
                return True
        return False
    except Exception:
        return False


def _extract_flags_from_fetch(fetch_item: Any) -> str:
    try:
        if isinstance(fetch_item, tuple) and fetch_item:
            meta = fetch_item[0]
            if isinstance(meta, (bytes, bytearray)):
                return meta.decode("utf-8", errors="ignore")
            return str(meta)
        if isinstance(fetch_item, (bytes, bytearray)):
            return fetch_item.decode("utf-8", errors="ignore")
        return str(fetch_item)
    except Exception:
        return ""


def _quote_if_needed(folder_name: str) -> List[str]:
    name = (folder_name or "").strip()
    if not name:
        return []
    if name.startswith('"') and name.endswith('"'):
        return [name]
    if " " in name:
        return [name, f'"{name}"']
    return [name]


def _is_outlook_imap_target(provider: str, imap_host: str) -> bool:
    provider_key = (provider or "").strip().lower()
    host = (imap_host or "").strip().lower()
    return provider_key == "outlook" or host in {"outlook.live.com", "outlook.office365.com"}


def _normalize_imap_auth_error_message(raw_message: str, *, provider: str, imap_host: str) -> str:
    message = sanitize_error_details(str(raw_message or "")).strip() or "IMAP 认证失败"
    provider_key = (provider or "").strip().lower()
    if provider_key == "gmail":
        return "IMAP 认证失败：Gmail 通常需要“应用专用密码”（非登录密码），并在 Gmail 设置中开启 IMAP"
    lowered = message.lower()
    if _is_outlook_imap_target(provider, imap_host) and "basicauthblocked" in lowered:
        return "IMAP 认证失败：Outlook.com 已阻止 Basic Auth（账号密码直连），请改用 Outlook OAuth 导入（client_id + refresh_token）"
    return message


def _resolve_imap_folder(
    mail: imaplib.IMAP4_SSL,
    candidates: List[str],
) -> Optional[str]:
    """按优先级 SELECT 文件夹，返回第一个成功的文件夹名。"""
    for folder_name in candidates or []:
        for try_name in _quote_if_needed(folder_name):
            try:
                status, resp = mail.select(try_name, readonly=True)
                _LOGGER.debug("imap_select try=%s status=%s resp=%s", try_name, status, resp)
                if status == "OK":
                    return try_name
            except Exception as exc:
                _LOGGER.debug("imap_select_exception try=%s err=%s", try_name, exc)
                continue
    return None


def _create_imap_connection(
    imap_host: str,
    imap_port: int,
    proxy_url: str = "",
) -> imaplib.IMAP4_SSL:
    host = (imap_host or "").strip()
    port = int(imap_port) if imap_port else 993
    if not host:
        raise ValueError("IMAP host 不能为空")

    _LOGGER.info("imap_connect host=%s port=%s proxied=%s", host, port, bool(str(proxy_url or "").strip()))

    clean_proxy = str(proxy_url or "").strip()
    if clean_proxy:
        mail = proxy_service.create_imap_ssl_connection(host, port, proxy_url=clean_proxy, timeout=30)
    else:
        # 优先使用 imaplib 的 timeout 参数（低风险；旧版本 Python 可能不支持）
        try:
            mail = imaplib.IMAP4_SSL(host, port, timeout=30)
        except TypeError:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(30)
            try:
                mail = imaplib.IMAP4_SSL(host, port)
            finally:
                socket.setdefaulttimeout(old_timeout)

    # 发送 IMAP ID 命令（163/126 等网易邮箱要求此命令，否则报 Unsafe Login）
    try:
        imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED")
        mail._simple_command(
            "ID",
            '("name" "outlookmail" "version" "1.0" "vendor" "outlookmail")',
        )
        _LOGGER.debug("imap_id_sent host=%s", host)
    except Exception as exc:
        _LOGGER.debug("imap_id_skipped host=%s reason=%s", host, exc)

    return mail


def _parse_batch_uid_fetch(fetch_data: List[Any]) -> Dict[str, Tuple[str, bytes]]:
    """解析批量 UID FETCH 返回，映射为 {uid_str: (flags_text, raw_bytes)}。"""
    result: Dict[str, Tuple[str, bytes]] = {}
    for item in fetch_data or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        header_bytes, raw_email = item[0], item[1]
        if not raw_email or not isinstance(header_bytes, (bytes, bytearray)):
            continue
        match = _UID_TOKEN_RE.search(bytes(header_bytes))
        if not match:
            continue
        uid_str = match.group(1).decode("ascii", errors="ignore")
        if uid_str:
            result[uid_str] = (_extract_flags_from_fetch(item), raw_email)
    return result


def get_emails_imap_generic(
    email_addr: str,
    imap_password: str,
    imap_host: str,
    imap_port: int = 993,
    folder: str = "inbox",
    provider: str = "_default",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
) -> Dict[str, Any]:
    """
    标准 IMAP 邮件列表（LOGIN 认证）。

    返回格式：
    {
      "success": True,
      "emails": [...],
      "method": "IMAP (Generic)",
      "has_more": False
    }

    错误时返回：
    {
      "success": False,
      "error": {
        "code": "IMAP_AUTH_FAILED|IMAP_CONNECT_FAILED|IMAP_FOLDER_NOT_FOUND|IMAP_SEARCH_FAILED",
        "message": "...",
        "status": 400|401|502,
        ...
      },
      "error_code": "IMAP_AUTH_FAILED|IMAP_CONNECT_FAILED|IMAP_FOLDER_NOT_FOUND|IMAP_CONNECT_FAILED(兼容字段)"
    }
    """
    mail = None
    try:
        skip = max(0, int(skip or 0))
        top = max(1, int(top or 20))

        mail = _create_imap_connection(imap_host, imap_port, proxy_url=proxy_url)
        try:
            mail.login(email_addr, imap_password)
            _LOGGER.info("imap_login_ok email=%s provider=%s", email_addr, provider)
        except imaplib.IMAP4.error as e:
            message = _normalize_imap_auth_error_message(str(e), provider=provider, imap_host=imap_host)
            _LOGGER.warning("imap_login_failed email=%s provider=%s err=%s", email_addr, provider, message)
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_AUTH_FAILED",
                    message,
                    "IMAPAuthError",
                    401,
                    "",
                ),
                "error_code": "IMAP_AUTH_FAILED",
            }

        candidates = get_imap_folder_candidates(provider, folder)
        selected = _resolve_imap_folder(mail, candidates)
        if not selected:
            _LOGGER.warning(
                "imap_folder_not_found email=%s provider=%s folder=%s candidates=%s",
                email_addr,
                provider,
                folder,
                candidates,
            )
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_FOLDER_NOT_FOUND",
                    "IMAP 文件夹不存在或无权限访问",
                    "IMAPFolderError",
                    400,
                    {"provider": provider, "folder": folder, "candidates": candidates},
                ),
                "error_code": "IMAP_FOLDER_NOT_FOUND",
            }

        status, data = mail.uid("SEARCH", None, "ALL")
        if status != "OK":
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_SEARCH_FAILED",
                    "IMAP 搜索邮件失败",
                    "IMAPSearchError",
                    502,
                    f"status={status}",
                ),
                "error_code": "IMAP_CONNECT_FAILED",
            }

        uid_bytes = data[0] if data else b""
        if not uid_bytes:
            return {"success": True, "emails": [], "method": "IMAP (Generic)", "has_more": False}

        uids = uid_bytes.split()
        total = len(uids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip
        if start_idx >= end_idx:
            return {"success": True, "emails": [], "method": "IMAP (Generic)", "has_more": False}

        paged_uids = uids[start_idx:end_idx][::-1]

        fetched_by_uid: Dict[str, Tuple[str, bytes]] = {}
        try:
            uid_csv = b",".join(paged_uids)
            b_status, b_data = mail.uid("FETCH", uid_csv, "(UID FLAGS RFC822)")
            if b_status == "OK" and b_data:
                fetched_by_uid = _parse_batch_uid_fetch(b_data)
        except Exception:
            fetched_by_uid = {}

        emails_data: List[Dict[str, Any]] = []
        for uid in paged_uids:
            try:
                uid_str = uid.decode("utf-8", errors="ignore") if isinstance(uid, (bytes, bytearray)) else str(uid)
                cached_entry = fetched_by_uid.get(uid_str)
                if cached_entry is not None:
                    flags_text, raw_email = cached_entry
                else:
                    f_status, f_data = mail.uid("FETCH", uid, "(FLAGS RFC822)")
                    if f_status != "OK" or not f_data:
                        continue
                    raw_email = None
                    flags_text = ""
                    for item in f_data:
                        if not item:
                            continue
                        if isinstance(item, tuple) and len(item) >= 2:
                            flags_text = _extract_flags_from_fetch(item)
                            raw_email = item[1]
                            break

                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = decode_header_value(msg.get("Subject", "无主题"))
                from_text = decode_header_value(msg.get("From", "未知发件人"))
                date_text = msg.get("Date", "未知时间")

                body_text, body_html = _extract_text_and_html(msg)
                plain_body = body_text or _strip_html(body_html)
                preview = plain_body[:200] + ("..." if len(plain_body) > 200 else "")

                emails_data.append(
                    {
                        "id": uid_str,
                        "subject": subject,
                        "from": from_text,
                        "date": date_text,
                        "is_read": "\\Seen" in (flags_text or ""),
                        "has_attachments": _has_attachments(msg),
                        "body_preview": preview,
                    }
                )
            except Exception:
                continue

        return {
            "success": True,
            "emails": emails_data,
            "method": "IMAP (Generic)",
            "has_more": False,
        }
    except Exception as exc:
        safe_exc = proxy_service.sanitize_proxy_error(exc, proxy_url)
        try:
            _LOGGER.warning(
                "imap_generic_failed provider=%s host=%s port=%s email=%s err=%s",
                (provider or "").strip().lower(),
                (imap_host or "").strip(),
                imap_port,
                (email_addr or "").strip(),
                sanitize_error_details(safe_exc),
            )
        except Exception:
            pass
        return {
            "success": False,
            "error": build_error_payload(
                "IMAP_CONNECT_FAILED",
                sanitize_error_details(safe_exc) or "IMAP 连接失败",
                "IMAPConnectError",
                502,
                "",
            ),
            "error_code": "IMAP_CONNECT_FAILED",
        }
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def get_email_detail_imap_generic_result(
    email_addr: str,
    imap_password: str,
    imap_host: str,
    imap_port: int = 993,
    message_id: str = "",
    folder: str = "inbox",
    provider: str = "_default",
    proxy_url: str = "",
) -> Dict[str, Any]:
    """标准 IMAP 邮件详情（按 UID fetch），失败返回结构化错误。"""
    if not message_id:
        return {
            "success": False,
            "error": build_error_payload(
                "EMAIL_DETAIL_INVALID",
                "message_id 不能为空",
                "ValidationError",
                400,
                "",
            ),
        }

    mail = None
    try:
        mail = _create_imap_connection(imap_host, imap_port, proxy_url=proxy_url)
        try:
            mail.login(email_addr, imap_password)
            _LOGGER.info("imap_detail_login_ok email=%s uid=%s", email_addr, message_id)
        except imaplib.IMAP4.error as e:
            message = _normalize_imap_auth_error_message(str(e), provider=provider, imap_host=imap_host)
            _LOGGER.warning("imap_detail_login_failed email=%s err=%s", email_addr, message)
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_AUTH_FAILED",
                    message,
                    "IMAPAuthError",
                    401,
                    "",
                ),
                "error_code": "IMAP_AUTH_FAILED",
            }

        candidates = get_imap_folder_candidates(provider, folder)
        selected = _resolve_imap_folder(mail, candidates)
        if not selected:
            _LOGGER.warning("imap_detail_folder_not_found email=%s folder=%s", email_addr, folder)
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_FOLDER_NOT_FOUND",
                    "IMAP 文件夹不存在或无权限访问",
                    "IMAPFolderError",
                    400,
                    {"provider": provider, "folder": folder, "candidates": candidates},
                ),
                "error_code": "IMAP_FOLDER_NOT_FOUND",
            }

        uid = message_id.encode("utf-8") if isinstance(message_id, str) else message_id
        status, data = mail.uid("FETCH", uid, "(FLAGS BODY[])")
        if status != "OK" or not data:
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_DETAIL_FETCH_FAILED",
                    "获取邮件详情失败",
                    "IMAPFetchError",
                    502,
                    f"status={status}",
                ),
                "error_code": "EMAIL_DETAIL_FETCH_FAILED",
            }

        raw_email = None
        flags_text = ""
        for item in data:
            if not item:
                continue
            if isinstance(item, tuple) and len(item) >= 2:
                flags_text = _extract_flags_from_fetch(item)
                raw_email = item[1]
                break

        if not raw_email:
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_DETAIL_FETCH_FAILED",
                    "获取邮件详情失败",
                    "IMAPFetchError",
                    502,
                    "raw_email_missing",
                ),
                "error_code": "EMAIL_DETAIL_FETCH_FAILED",
            }

        msg = email.message_from_bytes(raw_email)
        body_text, body_html = _extract_text_and_html(msg)

        raw_content = ""
        try:
            if isinstance(raw_email, (bytes, bytearray)):
                raw_content = raw_email.decode("utf-8", errors="replace")
            else:
                raw_content = str(raw_email)
        except Exception:
            raw_content = ""

        detail: Dict[str, Any] = {
            "id": message_id,
            "subject": decode_header_value(msg.get("Subject", "无主题")),
            "from": decode_header_value(msg.get("From", "未知发件人")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "date": msg.get("Date", "未知时间"),
            "is_read": "\\Seen" in (flags_text or ""),
            "has_attachments": _has_attachments(msg),
            "body_text": body_text or "",
            "body_html": body_html or "",
            "raw_content": raw_content,
        }

        if detail["body_html"]:
            detail["body"] = detail["body_html"]
            detail["body_type"] = "html"
        else:
            detail["body"] = detail["body_text"]
            detail["body_type"] = "text"

        return {"success": True, "email": detail, "method": "IMAP (Generic)"}
    except Exception as exc:
        safe_exc = proxy_service.sanitize_proxy_error(exc, proxy_url)
        return {
            "success": False,
            "error": build_error_payload(
                "IMAP_CONNECT_FAILED",
                sanitize_error_details(safe_exc) or "IMAP 连接失败",
                "IMAPConnectError",
                502,
                "",
            ),
            "error_code": "IMAP_CONNECT_FAILED",
        }
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def get_email_detail_imap_generic(
    email_addr: str,
    imap_password: str,
    imap_host: str,
    imap_port: int = 993,
    message_id: str = "",
    folder: str = "inbox",
    provider: str = "_default",
    proxy_url: str = "",
) -> Optional[Dict[str, Any]]:
    """兼容旧调用：成功返回详情，失败返回 None。"""
    result = get_email_detail_imap_generic_result(
        email_addr=email_addr,
        imap_password=imap_password,
        imap_host=imap_host,
        imap_port=imap_port,
        message_id=message_id,
        folder=folder,
        provider=provider,
        proxy_url=proxy_url,
    )
    if result.get("success"):
        return result.get("email")
    return None
