from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from outlook_web.services import graph as graph_service
from outlook_web.services import imap as imap_service
from outlook_web.services import imap_generic as imap_generic_service

IMAP_SERVER_NEW = "outlook.live.com"
IMAP_SERVER_OLD = "outlook.office365.com"

_LOGGER = logging.getLogger(__name__)


def format_graph_email_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 Graph API 返回的邮件列表标准化为前端展示结构。"""
    formatted: List[Dict[str, Any]] = []
    for item in emails or []:
        formatted.append(
            {
                "id": item.get("id"),
                "subject": item.get("subject", "无主题"),
                "from": item.get("from", {}).get("emailAddress", {}).get("address", "未知"),
                "date": item.get("receivedDateTime", ""),
                "is_read": item.get("isRead", False),
                "has_attachments": item.get("hasAttachments", False),
                "body_preview": item.get("bodyPreview", ""),
            }
        )
    return formatted


def _is_proxy_or_connection_error(err: Any) -> bool:
    return isinstance(err, dict) and err.get("type") in ("ProxyError", "ConnectionError")


def fetch_account_emails_with_fallback(
    account: Dict[str, Any],
    *,
    email_addr: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
    stop_on_proxy_error: bool = True,
    graph_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
    imap_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
    imap_generic_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """统一的账号邮件拉取回退链路：IMAP 通用账号直连；Outlook 按 Graph -> IMAP(New) -> IMAP(Old) 回退。"""
    _graph_fetch = graph_fetcher or graph_service.get_emails_graph
    _imap_fetch = imap_fetcher or imap_service.get_emails_imap_with_server
    _imap_generic_fetch = imap_generic_fetcher or imap_generic_service.get_emails_imap_generic

    imap_proxy_kwargs: Dict[str, Any] = {"proxy_url": proxy_url} if proxy_url else {}
    account_type = (account.get("account_type") or "outlook").strip().lower()

    if account_type == "imap":
        t0 = time.monotonic()
        result = _imap_generic_fetch(
            email_addr=email_addr,
            imap_password=account.get("imap_password", "") or "",
            imap_host=account.get("imap_host", "") or "",
            imap_port=account.get("imap_port", 993) or 993,
            folder=folder,
            provider=account.get("provider", "_default") or "_default",
            skip=skip,
            top=top,
            **imap_proxy_kwargs,
        )
        _LOGGER.debug(
            "[PERF] fetch_emails | email=%s | imap_generic | %dms | success=%s",
            email_addr,
            (time.monotonic() - t0) * 1000,
            result.get("success"),
        )
        if result.get("success"):
            return {
                "success": True,
                "account_type": "imap",
                "emails": result.get("emails") or [],
                "method": str(result.get("method") or "IMAP (Generic)"),
                "has_more": bool(result.get("has_more", False)),
                "raw_result": result,
            }
        return {
            "success": False,
            "account_type": "imap",
            "proxy_error": False,
            "auth_expired": False,
            "errors": {"imap_generic": result.get("error")},
            "raw_result": result,
        }

    all_errors: Dict[str, Any] = {}
    client_id = account.get("client_id") or ""
    refresh_token = account.get("refresh_token") or ""

    t_graph = time.monotonic()
    graph_result = _graph_fetch(
        client_id,
        refresh_token,
        folder=folder,
        skip=skip,
        top=top,
        proxy_url=proxy_url,
    )
    _LOGGER.debug(
        "[PERF] fetch_emails | email=%s | graph_api | %dms | success=%s",
        email_addr,
        (time.monotonic() - t_graph) * 1000,
        graph_result.get("success"),
    )
    if graph_result.get("success"):
        emails = graph_result.get("emails", []) or []
        return {
            "success": True,
            "account_type": account_type,
            "emails": emails,
            "method": "Graph API",
            "has_more": len(emails) >= top,
            "new_refresh_token": graph_result.get("new_refresh_token"),
            "raw_result": graph_result,
        }

    graph_error = graph_result.get("error")
    all_errors["graph"] = graph_error
    if stop_on_proxy_error and _is_proxy_or_connection_error(graph_error):
        return {
            "success": False,
            "account_type": account_type,
            "proxy_error": True,
            "auth_expired": False,
            "errors": all_errors,
            "graph_error": graph_error,
        }

    for key, server, method_label in (
        ("imap_new", IMAP_SERVER_NEW, "IMAP (New)"),
        ("imap_old", IMAP_SERVER_OLD, "IMAP (Old)"),
    ):
        t_imap = time.monotonic()
        imap_result = _imap_fetch(
            email_addr,
            client_id,
            refresh_token,
            folder,
            skip,
            top,
            server,
            **imap_proxy_kwargs,
        )
        _LOGGER.debug(
            "[PERF] fetch_emails | email=%s | %s | %dms | success=%s",
            email_addr,
            key,
            (time.monotonic() - t_imap) * 1000,
            imap_result.get("success"),
        )
        if imap_result.get("success"):
            return {
                "success": True,
                "account_type": account_type,
                "emails": imap_result.get("emails", []) or [],
                "method": method_label,
                "has_more": False,
                "raw_result": imap_result,
            }
        all_errors[key] = imap_result.get("error")

    return {
        "success": False,
        "account_type": account_type,
        "proxy_error": False,
        "auth_expired": bool(graph_result.get("auth_expired")),
        "errors": all_errors,
        "graph_error": graph_error,
    }
