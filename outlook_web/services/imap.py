from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.header import decode_header
from typing import Any, Dict, List, Optional

import requests

from outlook_web.errors import build_error_payload
from outlook_web.services import proxy as proxy_service
from outlook_web.services.graph import get_access_token_graph
from outlook_web.services.http import get_response_details
from outlook_web.utils.common import decode_mime_header

_LOGGER = logging.getLogger(__name__)

# Token 端点
TOKEN_URL_IMAP = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"

# IMAP 服务器配置
IMAP_SERVER_NEW = "outlook.live.com"
IMAP_PORT = 993
IMAP_SOCKET_TIMEOUT = 30
_TOKEN_CACHE_MAX_SIZE = 512

_token_cache: Dict[str, tuple] = {}
_token_cache_lock = threading.Lock()


def _open_imap_connection(server: str, proxy_url: str = "") -> imaplib.IMAP4_SSL:
    clean_proxy = str(proxy_url or "").strip()
    if clean_proxy:
        return proxy_service.create_imap_ssl_connection(
            server,
            IMAP_PORT,
            proxy_url=clean_proxy,
            timeout=IMAP_SOCKET_TIMEOUT,
        )
    return imaplib.IMAP4_SSL(server, IMAP_PORT, timeout=IMAP_SOCKET_TIMEOUT)


def decode_header_value(header_value: str) -> str:
    """解码邮件头字段"""
    return decode_mime_header(header_value)


def get_email_body(msg) -> str:
    """提取邮件正文

    优先返回 text/plain，但如果内容太短（<20字符），则回退到 text/html。
    这解决了 Figma 等服务的邮件问题：它们的 text/plain 部分可能几乎为空，
    而正文内容都在 text/html 部分。
    """
    plain_text = ""
    html_text = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain" and not plain_text:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    plain_text = payload.decode(charset, errors="replace")
                except Exception:
                    continue
            elif content_type == "text/html" and not html_text:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html_text = payload.decode(charset, errors="replace")
                except Exception:
                    continue

            if plain_text and html_text:
                break
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_text = content
            else:
                plain_text = content
        except Exception:
            plain_text = str(msg.get_payload())

    # 如果 text/plain 太短（<20字符），回退到 text/html
    # 这解决了 Figma 等服务的邮件问题
    if len(plain_text.strip()) >= 20:
        return plain_text
    return html_text or plain_text


def get_email_body_and_type(msg) -> tuple:
    """提取邮件正文和类型（用于需要区分 HTML/Text 的场景）

    返回 (body, body_type) 元组：
    - body: 邮件正文内容
    - body_type: "html" 或 "text"
    """
    plain_text = ""
    html_text = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain" and not plain_text:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    plain_text = payload.decode(charset, errors="replace")
                except Exception:
                    continue
            elif content_type == "text/html" and not html_text:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html_text = payload.decode(charset, errors="replace")
                except Exception:
                    continue

            if plain_text and html_text:
                break
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_text = content
            else:
                plain_text = content
        except Exception:
            plain_text = str(msg.get_payload())

    # 如果 text/plain 太短（<20字符），回退到 text/html
    if len(plain_text.strip()) >= 20:
        return plain_text, "text"
    return html_text or plain_text, "html" if html_text else "text"


def _select_folder(connection, folder: str) -> Optional[str]:
    folder_map = {
        "inbox": ["INBOX"],
        "junk": ["Junk", "Junk Email", "Spam", "垃圾邮件"],
        "junkemail": ["Junk", "Junk Email", "Spam", "垃圾邮件"],
        "deleteditems": ["Deleted", "Deleted Items", "Trash", "已删除邮件"],
        "trash": ["Deleted", "Deleted Items", "Trash", "已删除邮件"],
    }
    candidates = folder_map.get((folder or "").lower(), [folder or "INBOX"])
    for candidate in candidates:
        for select_target in (f'"{candidate}"', candidate):
            try:
                status, _ = connection.select(select_target, readonly=True)
                if status == "OK":
                    return candidate
            except Exception:
                continue
    return None


def _get_html_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


def _parse_batch_fetch_response(all_data: list) -> List[tuple]:
    results = []
    for item in all_data:
        header = None
        raw_email = None

        if isinstance(item, tuple) and len(item) == 2:
            first, second = item
            if isinstance(first, (bytes, bytearray)) and isinstance(second, (bytes, bytearray)):
                header = bytes(first)
                raw_email = bytes(second)
            elif isinstance(first, tuple) and len(first) == 2:
                nested_header, nested_raw = first
                if isinstance(nested_header, (bytes, bytearray)) and isinstance(nested_raw, (bytes, bytearray)):
                    header = bytes(nested_header)
                    raw_email = bytes(nested_raw)

        if not isinstance(header, (bytes, bytearray)) or not isinstance(raw_email, (bytes, bytearray)):
            continue

        msg_id_str = header.split(b" ", 1)[0].decode("ascii", errors="ignore").strip()
        if not msg_id_str:
            continue
        results.append((msg_id_str, raw_email))
    return results


def _make_cache_key(client_id: str, refresh_token: str) -> str:
    rt_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()[:16]
    return f"{client_id}:{rt_hash}"


def clear_imap_token_cache(client_id: str = None) -> None:
    with _token_cache_lock:
        if client_id is None:
            _token_cache.clear()
        else:
            keys_to_remove = [k for k in _token_cache if k.startswith(f"{client_id}:")]
            for key in keys_to_remove:
                del _token_cache[key]


def get_access_token_imap_result(
    client_id: str,
    refresh_token: str,
    proxy_url: str = "",
) -> Dict[str, Any]:
    """获取 IMAP access_token（包含错误详情，支持代理与有界缓存）。"""
    cache_key = _make_cache_key(client_id, refresh_token)
    now = time.monotonic()
    with _token_cache_lock:
        cached = _token_cache.get(cache_key)
        if cached:
            access_token, expires_at = cached
            if now < expires_at:
                return {"success": True, "access_token": access_token}
            _token_cache.pop(cache_key, None)

    try:
        proxy_kwargs = proxy_service.build_requests_proxy_kwargs(proxy_url)
        res = requests.post(
            TOKEN_URL_IMAP,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
            },
            timeout=30,
            **proxy_kwargs,
        )

        if res.status_code != 200:
            details = get_response_details(res)
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_TOKEN_FAILED",
                    "获取访问令牌失败",
                    "IMAPError",
                    res.status_code,
                    details,
                ),
            }

        payload = res.json()
        access_token = payload.get("access_token")
        if not access_token:
            return {
                "success": False,
                "error": build_error_payload(
                    "IMAP_TOKEN_MISSING",
                    "获取访问令牌失败",
                    "IMAPError",
                    res.status_code,
                    payload,
                ),
            }

        expires_in = int(payload.get("expires_in", 3599))
        ttl = max(0, expires_in - 60)
        now = time.monotonic()
        with _token_cache_lock:
            if len(_token_cache) >= _TOKEN_CACHE_MAX_SIZE:
                expired_keys = [k for k, (_, exp) in _token_cache.items() if exp <= now]
                for k in expired_keys:
                    _token_cache.pop(k, None)
                if len(_token_cache) >= _TOKEN_CACHE_MAX_SIZE:
                    oldest_key = min(_token_cache, key=lambda k: _token_cache[k][1])
                    _token_cache.pop(oldest_key, None)
            _token_cache[cache_key] = (access_token, now + ttl)

        return {"success": True, "access_token": access_token}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "IMAP_TOKEN_EXCEPTION",
                "获取访问令牌失败",
                type(exc).__name__,
                500,
                proxy_service.sanitize_proxy_error(exc, proxy_url),
            ),
        }


def get_access_token_imap(client_id: str, refresh_token: str, proxy_url: str = "") -> Optional[str]:
    """获取 IMAP access_token"""
    result = (
        get_access_token_imap_result(client_id, refresh_token, proxy_url=proxy_url)
        if proxy_url
        else get_access_token_imap_result(client_id, refresh_token)
    )
    if result.get("success"):
        return result.get("access_token")
    return None


def get_emails_imap(
    account: str,
    client_id: str,
    refresh_token: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页和文件夹选择）- 默认使用新版服务器"""
    if proxy_url:
        return get_emails_imap_with_server(
            account, client_id, refresh_token, folder, skip, top, IMAP_SERVER_NEW, proxy_url=proxy_url
        )
    return get_emails_imap_with_server(account, client_id, refresh_token, folder, skip, top, IMAP_SERVER_NEW)


def get_emails_imap_with_server(
    account: str,
    client_id: str,
    refresh_token: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    server: str = IMAP_SERVER_NEW,
    proxy_url: str = "",
) -> Dict[str, Any]:
    """使用 IMAP 获取邮件列表（支持分页、文件夹选择、服务器选择与代理）。"""
    token_result = (
        get_access_token_imap_result(client_id, refresh_token, proxy_url=proxy_url)
        if proxy_url
        else get_access_token_imap_result(client_id, refresh_token)
    )
    if not token_result.get("success"):
        return {"success": False, "error": token_result.get("error")}

    access_token = token_result.get("access_token")

    connection = None
    try:
        connection = _open_imap_connection(server, proxy_url=proxy_url)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode("utf-8")
        connection.authenticate("XOAUTH2", lambda x: auth_string)

        selected_folder = _select_folder(connection, folder)

        if not selected_folder:
            try:
                status, folder_list = connection.list()
                available_folders = []
                if status == "OK" and folder_list:
                    for folder_item in folder_list:
                        if isinstance(folder_item, bytes):
                            available_folders.append(folder_item.decode("utf-8", errors="ignore"))
                        else:
                            available_folders.append(str(folder_item))

                error_details = {
                    "last_error": "select folder failed",
                    "tried_folder": folder,
                    "available_folders": available_folders[:10],
                }
            except Exception:
                error_details = {
                    "last_error": "select folder failed",
                    "tried_folder": folder,
                }

            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    "无法访问文件夹，请检查账号配置",
                    "IMAPSelectError",
                    500,
                    error_details,
                ),
            }

        status, messages = connection.search(None, "ALL")
        if status != "OK":
            _LOGGER.debug(
                "[PERF] imap_search | account=%s | server=%s | folder=%s | status=%s (非OK)",
                account,
                server,
                selected_folder,
                status,
            )
            return {
                "success": False,
                "error": build_error_payload(
                    "EMAIL_FETCH_FAILED",
                    "获取邮件失败，请检查账号配置",
                    "IMAPSearchError",
                    500,
                    f"search status={status}",
                ),
            }
        if not messages or not messages[0]:
            _LOGGER.debug(
                "[PERF] imap_search | account=%s | server=%s | folder=%s | total=0 (空信箱)",
                account,
                server,
                selected_folder,
            )
            return {"success": True, "emails": []}

        message_ids = messages[0].split()
        total = len(message_ids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip

        _LOGGER.debug(
            "[PERF] imap_search | account=%s | server=%s | folder=%s | total=%d | skip=%d | top=%d | slice=[%d:%d]",
            account,
            server,
            selected_folder,
            total,
            skip,
            top,
            start_idx,
            end_idx,
        )

        if start_idx >= end_idx:
            return {"success": True, "emails": []}

        paged_ids = message_ids[start_idx:end_idx][::-1]
        emails_data = []

        ids_str = b",".join(paged_ids)
        status, all_data = connection.fetch(ids_str, "(RFC822)")
        if status != "OK":
            _LOGGER.debug(
                "[PERF] imap_fetch | account=%s | batch fetch失败 status=%s",
                account,
                status,
            )
            return {"success": True, "emails": emails_data}

        parsed_items = _parse_batch_fetch_response(all_data or [])
        raw_by_id = {msg_id_str: raw_email for msg_id_str, raw_email in parsed_items}
        ordered_pairs = []
        for msg_id in paged_ids:
            msg_id_str = msg_id.decode("ascii", errors="ignore").strip()
            raw_email = raw_by_id.get(msg_id_str)
            if raw_email is not None:
                ordered_pairs.append((msg_id_str, raw_email))
        # 若服务端返回的序列号与 paged_ids 不匹配，回退按解析顺序输出，避免丢失邮件
        if not ordered_pairs and parsed_items:
            ordered_pairs = parsed_items

        for msg_id_str, raw_email in ordered_pairs:
            try:
                msg = email.message_from_bytes(raw_email)
                body_preview = get_email_body(msg)
                emails_data.append(
                    {
                        "id": msg_id_str,
                        "subject": decode_header_value(msg.get("Subject", "无主题")),
                        "from": decode_header_value(msg.get("From", "未知发件人")),
                        "date": msg.get("Date", "未知时间"),
                        "body_preview": (body_preview[:200] + "..." if len(body_preview) > 200 else body_preview),
                    }
                )
            except Exception as fetch_err:
                _LOGGER.debug(
                    "[PERF] imap_fetch | account=%s | msg_id=%s | 解析失败: %s",
                    account,
                    msg_id_str,
                    fetch_err,
                )
                continue

        _LOGGER.debug(
            "[PERF] imap_result | account=%s | server=%s | fetched=%d / requested=%d",
            account,
            server,
            len(emails_data),
            len(paged_ids),
        )
        return {"success": True, "emails": emails_data}
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "EMAIL_FETCH_FAILED",
                "获取邮件失败，请检查账号配置",
                type(exc).__name__,
                500,
                proxy_service.sanitize_proxy_error(exc, proxy_url),
            ),
        }
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def fetch_and_detail_imap_with_server(
    account: str,
    client_id: str,
    refresh_token: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 1,
    server: str = IMAP_SERVER_NEW,
    proxy_url: str = "",
) -> Dict[str, Any]:
    """一次 IMAP 连接完成邮件列表 + 最新一封详情。"""
    token_result = (
        get_access_token_imap_result(client_id, refresh_token, proxy_url=proxy_url)
        if proxy_url
        else get_access_token_imap_result(client_id, refresh_token)
    )
    if not token_result.get("success"):
        return {
            "success": False,
            "error": token_result.get("error"),
            "emails": [],
            "detail": None,
        }

    access_token = token_result["access_token"]
    connection = None

    try:
        connection = _open_imap_connection(server, proxy_url=proxy_url)
        auth_string = f"user={account}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")
        connection.authenticate("XOAUTH2", lambda x: auth_string)

        selected = _select_folder(connection, folder)
        if not selected:
            return {
                "success": False,
                "error": build_error_payload("FOLDER_NOT_FOUND", "文件夹选择失败", "IMAPError", 500, ""),
                "emails": [],
                "detail": None,
            }

        status, messages = connection.search(None, "ALL")
        if status != "OK" or not messages or not messages[0]:
            return {"success": True, "emails": [], "detail": None}

        message_ids = messages[0].split()
        total = len(message_ids)
        start_idx = max(0, total - skip - top)
        end_idx = total - skip
        if start_idx >= end_idx:
            return {"success": True, "emails": [], "detail": None}

        paged_ids = message_ids[start_idx:end_idx][::-1]
        emails_data: List[Dict[str, Any]] = []
        detail = None

        ids_str = b",".join(paged_ids)
        status, all_data = connection.fetch(ids_str, "(RFC822)")
        if status != "OK":
            return {"success": True, "emails": [], "detail": None}

        raw_by_id = {msg_id_str: raw_email for msg_id_str, raw_email in _parse_batch_fetch_response(all_data or [])}

        for i, msg_id in enumerate(paged_ids):
            msg_id_str = msg_id.decode("ascii", errors="ignore").strip()
            raw_email = raw_by_id.get(msg_id_str)
            if raw_email is None:
                continue

            msg = email.message_from_bytes(raw_email)
            body_preview = get_email_body(msg)
            email_item = {
                "id": msg_id_str,
                "subject": decode_header_value(msg.get("Subject", "无主题")),
                "from": decode_header_value(msg.get("From", "未知发件人")),
                "date": msg.get("Date", "未知时间"),
                "body_preview": body_preview[:200] + "..." if len(body_preview) > 200 else body_preview,
            }
            emails_data.append(email_item)

            if i == 0:
                raw_text = raw_email.decode("utf-8", errors="replace") if isinstance(raw_email, (bytes, bytearray)) else ""
                detail = {
                    "id": email_item["id"],
                    "subject": email_item["subject"],
                    "from": email_item["from"],
                    "to": decode_header_value(msg.get("To", "")),
                    "cc": decode_header_value(msg.get("Cc", "")),
                    "date": email_item["date"],
                    "body": get_email_body(msg),
                    "body_html": _get_html_body(msg),
                    "raw_content": raw_text,
                }

        return {"success": True, "emails": emails_data, "detail": detail}
    except imaplib.IMAP4.error as exc:
        return {
            "success": False,
            "error": build_error_payload("AUTH_FAILED", "IMAP认证失败", "IMAP4Error", 401, str(exc)),
            "emails": [],
            "detail": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": build_error_payload(
                "EMAIL_FETCH_FAILED",
                "获取邮件失败",
                type(exc).__name__,
                500,
                str(exc),
            ),
            "emails": [],
            "detail": None,
        }
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def get_emails_imap_concurrent(
    account: str,
    client_id: str,
    refresh_token: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    servers: tuple = (IMAP_SERVER_NEW, "outlook.office365.com"),
) -> Dict[str, Any]:
    """并发连接多台 IMAP 服务器，返回第一个成功结果。"""
    if len(servers) <= 1:
        return get_emails_imap_with_server(
            account,
            client_id,
            refresh_token,
            folder,
            skip,
            top,
            servers[0] if servers else IMAP_SERVER_NEW,
        )

    last_error = None
    with ThreadPoolExecutor(max_workers=len(servers)) as executor:
        futures = {
            executor.submit(
                get_emails_imap_with_server,
                account,
                client_id,
                refresh_token,
                folder,
                skip,
                top,
                server,
            ): server
            for server in servers
        }
        for future in as_completed(futures):
            result = future.result()
            if result.get("success"):
                return result
            last_error = result

    return last_error or {
        "success": False,
        "error": {"code": "ALL_SERVERS_FAILED", "message": "所有服务器连接失败"},
    }


def get_email_detail_imap(
    account: str,
    client_id: str,
    refresh_token: str,
    message_id: str,
    folder: str = "inbox",
    proxy_url: str = "",
) -> Optional[Dict]:
    """使用 IMAP 获取邮件详情（默认使用新版服务器）。"""
    if proxy_url:
        return get_email_detail_imap_with_server(
            account, client_id, refresh_token, message_id, folder, IMAP_SERVER_NEW, proxy_url=proxy_url
        )
    return get_email_detail_imap_with_server(account, client_id, refresh_token, message_id, folder, IMAP_SERVER_NEW)


def get_email_detail_imap_with_server(
    account: str,
    client_id: str,
    refresh_token: str,
    message_id: str,
    folder: str = "inbox",
    server: str = IMAP_SERVER_NEW,
    proxy_url: str = "",
) -> Optional[Dict]:
    """使用 IMAP 获取邮件详情（支持指定服务器与代理）。"""
    access_token = (
        get_access_token_imap(client_id, refresh_token, proxy_url=proxy_url)
        if proxy_url
        else get_access_token_imap(client_id, refresh_token)
    )
    if not access_token:
        return None

    connection = None
    try:
        connection = _open_imap_connection(server, proxy_url=proxy_url)
        auth_string = f"user={account}\1auth=Bearer {access_token}\1\1".encode("utf-8")
        connection.authenticate("XOAUTH2", lambda x: auth_string)

        selected_folder = _select_folder(connection, folder)
        if not selected_folder:
            return None

        fetch_id = message_id.encode() if isinstance(message_id, str) else message_id
        status, msg_data = connection.fetch(fetch_id, "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            return None

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        raw_text = ""
        try:
            raw_text = raw_email.decode("utf-8", errors="replace") if isinstance(raw_email, (bytes, bytearray)) else ""
        except Exception:
            raw_text = ""

        body, body_type = get_email_body_and_type(msg)
        return {
            "id": message_id,
            "subject": decode_header_value(msg.get("Subject", "无主题")),
            "from": decode_header_value(msg.get("From", "未知发件人")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "date": msg.get("Date", "未知时间"),
            "body": body,
            "body_type": body_type,
            "raw_content": raw_text,
        }
    except Exception:
        return None
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


def delete_emails_imap(
    email_addr: str,
    client_id: str,
    refresh_token: str,
    message_ids: List[str],
    server: str,
) -> Dict[str, Any]:
    """通过 IMAP 删除邮件（Graph message id 与 IMAP UID 不兼容，直接快速返回避免无谓登录与连接泄漏）。"""
    _ = (email_addr, client_id, refresh_token, message_ids, server)
    return {"success": False, "error": "IMAP 删除暂不支持 (ID 格式不兼容)"}
