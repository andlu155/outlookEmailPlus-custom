from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, List, Optional, Sequence

from outlook_web.services import graph as graph_service
from outlook_web.services import imap as imap_service
from outlook_web.services import imap_generic as imap_generic_service

IMAP_SERVER_NEW = "outlook.live.com"
IMAP_SERVER_OLD = "outlook.office365.com"

_LOGGER = logging.getLogger(__name__)


def normalize_protocols(raw: Any) -> List[str]:
    """标准化取件协议列表，仅允许 'graph' 与 'imap'，缺省返回两者。"""
    if raw is None:
        return ["graph", "imap"]
    items: List[str] = []
    if isinstance(raw, str):
        items = [part.strip().lower() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(part or "").strip().lower() for part in raw if str(part or "").strip()]
    valid: List[str] = []
    for item in items:
        if item in ("graph", "imap") and item not in valid:
            valid.append(item)
    return valid or ["graph", "imap"]


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


def filter_fetched_emails(
    emails: List[Dict[str, Any]],
    *,
    keyword: str = "",
    sender: str = "",
) -> List[Dict[str, Any]]:
    """按主题/摘要关键词与发件人子串过滤邮件列表（大小写不敏感）。"""
    kw = (keyword or "").strip().lower()
    snd = (sender or "").strip().lower()
    if not kw and not snd:
        return emails
    filtered: List[Dict[str, Any]] = []
    for item in emails or []:
        subject = str(item.get("subject") or "").lower()
        preview = str(item.get("body_preview") or item.get("bodyPreview") or "").lower()
        sender_raw = item.get("from")
        if isinstance(sender_raw, dict):
            sender_val = str(sender_raw.get("emailAddress", {}).get("address") or "").lower()
        else:
            sender_val = str(sender_raw or "").lower()
        if kw and kw not in subject and kw not in preview:
            continue
        if snd and snd not in sender_val:
            continue
        filtered.append(item)
    return filtered


def _is_proxy_or_connection_error(err: Any) -> bool:
    return isinstance(err, dict) and err.get("type") in ("ProxyError", "ConnectionError")


def _try_graph(
    graph_fetch: Callable[..., Dict[str, Any]],
    *,
    email_addr: str,
    account_type: str,
    client_id: str,
    refresh_token: str,
    folder: str,
    skip: int,
    top: int,
    proxy_url: str,
) -> Dict[str, Any]:
    t_graph = time.monotonic()
    graph_result = graph_fetch(
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
    return {
        "success": False,
        "account_type": account_type,
        "proxy_error": _is_proxy_or_connection_error(graph_error),
        "auth_expired": bool(graph_result.get("auth_expired")),
        "errors": {"graph": graph_error},
        "graph_error": graph_error,
    }


def _try_imap_servers(
    imap_fetch: Callable[..., Dict[str, Any]],
    *,
    email_addr: str,
    account_type: str,
    client_id: str,
    refresh_token: str,
    folder: str,
    skip: int,
    top: int,
    imap_proxy_kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    imap_errors: Dict[str, Any] = {}
    for key, server, method_label in (
        ("imap_new", IMAP_SERVER_NEW, "IMAP (New)"),
        ("imap_old", IMAP_SERVER_OLD, "IMAP (Old)"),
    ):
        t_imap = time.monotonic()
        imap_result = imap_fetch(
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
        imap_errors[key] = imap_result.get("error")

    return {
        "success": False,
        "account_type": account_type,
        "proxy_error": False,
        "auth_expired": False,
        "errors": imap_errors,
    }


def fetch_account_emails_with_fallback(
    account: Dict[str, Any],
    *,
    email_addr: str,
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
    stop_on_proxy_error: bool = True,
    protocols: Optional[Sequence[str]] = None,
    parallel: bool = False,
    graph_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
    imap_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
    imap_generic_fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """统一的账号邮件拉取链路：IMAP 通用账号直连；Outlook 支持 Graph/IMAP 单选、串行回退或双协议并行竞速。"""
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

    enabled = normalize_protocols(protocols)
    want_graph = "graph" in enabled
    want_imap = "imap" in enabled
    client_id = account.get("client_id") or ""
    refresh_token = account.get("refresh_token") or ""

    # 双协议并行竞速：优先采用最先成功返回的通道，显著降低单通道波动等待
    if parallel and want_graph and want_imap:
        all_errors: Dict[str, Any] = {}
        graph_error: Any = None
        auth_expired = False
        proxy_error = False

        executor = ThreadPoolExecutor(max_workers=2)
        try:
            f_graph = executor.submit(
                _try_graph,
                _graph_fetch,
                email_addr=email_addr,
                account_type=account_type,
                client_id=client_id,
                refresh_token=refresh_token,
                folder=folder,
                skip=skip,
                top=top,
                proxy_url=proxy_url,
            )
            f_imap = executor.submit(
                _try_imap_servers,
                _imap_fetch,
                email_addr=email_addr,
                account_type=account_type,
                client_id=client_id,
                refresh_token=refresh_token,
                folder=folder,
                skip=skip,
                top=top,
                imap_proxy_kwargs=imap_proxy_kwargs,
            )
            pending = {f_graph, f_imap}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    try:
                        res = fut.result()
                    except Exception as exc:
                        key = "graph" if fut is f_graph else "imap"
                        all_errors[key] = {"code": "EMAIL_FETCH_EXCEPTION", "details": str(exc)}
                        continue
                    if res.get("success"):
                        for other in pending:
                            other.cancel()
                        return res
                    all_errors.update(res.get("errors") or {})
                    if fut is f_graph:
                        graph_error = res.get("graph_error")
                        auth_expired = bool(res.get("auth_expired"))
                        proxy_error = bool(res.get("proxy_error"))
        finally:
            executor.shutdown(wait=False)

        return {
            "success": False,
            "account_type": account_type,
            "proxy_error": stop_on_proxy_error and proxy_error,
            "auth_expired": auth_expired,
            "errors": all_errors,
            "graph_error": graph_error,
        }

    # 串行模式（默认，兼容全部既有单测与调用方）
    all_errors = {}
    graph_error = None
    auth_expired = False

    if want_graph:
        graph_res = _try_graph(
            _graph_fetch,
            email_addr=email_addr,
            account_type=account_type,
            client_id=client_id,
            refresh_token=refresh_token,
            folder=folder,
            skip=skip,
            top=top,
            proxy_url=proxy_url,
        )
        if graph_res.get("success"):
            return graph_res
        graph_error = graph_res.get("graph_error")
        auth_expired = bool(graph_res.get("auth_expired"))
        all_errors.update(graph_res.get("errors") or {})
        if stop_on_proxy_error and graph_res.get("proxy_error"):
            return {
                "success": False,
                "account_type": account_type,
                "proxy_error": True,
                "auth_expired": False,
                "errors": all_errors,
                "graph_error": graph_error,
            }

    if want_imap:
        imap_res = _try_imap_servers(
            _imap_fetch,
            email_addr=email_addr,
            account_type=account_type,
            client_id=client_id,
            refresh_token=refresh_token,
            folder=folder,
            skip=skip,
            top=top,
            imap_proxy_kwargs=imap_proxy_kwargs,
        )
        if imap_res.get("success"):
            return imap_res
        all_errors.update(imap_res.get("errors") or {})

    return {
        "success": False,
        "account_type": account_type,
        "proxy_error": False,
        "auth_expired": auth_expired,
        "errors": all_errors,
        "graph_error": graph_error,
    }
