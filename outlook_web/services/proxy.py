from __future__ import annotations

import imaplib
import ipaddress
import re
import ssl
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit, urlunsplit

import requests

from outlook_web.utils.common import (
    ALLOWED_PROXY_SCHEMES,
    VALID_GROUP_PROXY_MODES,
    normalize_group_proxy_mode,
    validate_proxy_url,
)

DEFAULT_PROXY_TEST_URL = "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
DEFAULT_IMAP_TIMEOUT = 30

_CREDENTIAL_URL_RE = re.compile(
    r"((?:https?|socks(?:4a?|5h?))://)([^/\s@]+)@",
    flags=re.IGNORECASE,
)


def mask_proxy_url(url: Any) -> str:
    """脱敏代理地址中的用户名和密码，仅保留协议、主机与端口。"""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        if not parsed.scheme or not parsed.hostname:
            return _CREDENTIAL_URL_RE.sub(r"\1***@", raw)
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port_part = f":{parsed.port}" if parsed.port else ""
        auth_part = "***@" if (parsed.username is not None or parsed.password is not None) else ""
        netloc = f"{auth_part}{host}{port_part}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except Exception:
        return _CREDENTIAL_URL_RE.sub(r"\1***@", raw)


def sanitize_proxy_error(message: Any, proxy_url: str = "") -> str:
    """净化错误信息，避免泄漏代理账号密码。"""
    text = str(message or "")
    raw_proxy = str(proxy_url or "").strip()
    if raw_proxy and raw_proxy in text:
        text = text.replace(raw_proxy, mask_proxy_url(raw_proxy))
    return _CREDENTIAL_URL_RE.sub(r"\1***@", text)


def is_local_or_private_url(target_url: str) -> bool:
    """判断目标 URL 是否为本地、私网或单标签容器内网地址（此类目标默认绕过全局代理）。"""
    raw = str(target_url or "").strip()
    if not raw:
        return False
    try:
        hostname = (urlsplit(raw).hostname or "").strip().lower()
    except Exception:
        return False
    if not hostname:
        return False

    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        return True

    try:
        ip_obj = ipaddress.ip_address(hostname)
        return ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_unspecified or ip_obj.is_reserved
    except ValueError:
        # 单标签主机名（如 Docker 服务名 watchtower / ollama）属于内网地址
        return "." not in hostname


def get_effective_global_proxy_url() -> str:
    """安全读取当前生效的系统全局代理 URL（未启用或未配置则返回空字符串）。"""
    try:
        from outlook_web.repositories import settings as settings_repo

        return settings_repo.get_effective_global_proxy_url()
    except Exception:
        return ""


def _lookup_group_proxy(group_id: Optional[int]) -> Tuple[str, str]:
    if not group_id:
        return "", "inherit"
    try:
        from outlook_web.repositories import groups as groups_repo

        group = groups_repo.get_group_by_id(int(group_id))
        if not group:
            return "", "inherit"
        proxy_url = str(group.get("proxy_url") or "").strip()
        proxy_mode = str(group.get("proxy_mode") or "").strip().lower()
        if proxy_mode not in VALID_GROUP_PROXY_MODES:
            proxy_mode = "custom" if proxy_url else "inherit"
        return proxy_url, proxy_mode
    except Exception:
        return "", "inherit"


def resolve_proxy_url(
    *,
    group_proxy_url: Optional[str] = None,
    group_proxy_mode: Optional[str] = None,
    group_id: Optional[int] = None,
    override_url: Optional[str] = None,
    target_url: str = "",
    allow_global: bool = True,
) -> Tuple[str, bool]:
    """
    统一解析最终代理 URL 与是否强制直连。

    优先级：
    1. override_url（显式模块级覆盖，如 Telegram 专属代理）
    2. 分组策略：
       - direct: 强制直连（绕过全局与环境变量代理）
       - custom: 使用分组 proxy_url
       - inherit: 跟随全局代理
    3. 全局代理（若 allow_global=True 且目标非本地/私网地址）
    """
    override_clean = str(override_url or "").strip()
    if override_clean:
        return override_clean, False

    resolved_group_url = group_proxy_url
    resolved_group_mode = group_proxy_mode
    if resolved_group_url is None and resolved_group_mode is None and group_id is not None:
        resolved_group_url, resolved_group_mode = _lookup_group_proxy(group_id)

    clean_group_url = str(resolved_group_url or "").strip()
    clean_mode = str(resolved_group_mode or "").strip().lower()

    if clean_mode == "direct":
        return "", True
    if clean_mode == "custom":
        if clean_group_url:
            return clean_group_url, False
    elif not clean_mode and clean_group_url:
        # 兼容未显式传 proxy_mode 的历史调用方
        return clean_group_url, False

    if allow_global:
        if target_url and is_local_or_private_url(target_url):
            return "", False
        global_url = get_effective_global_proxy_url()
        if global_url:
            return global_url, False

    return "", False


def resolve_account_proxy(
    account: Optional[Dict[str, Any]] = None,
    *,
    group_id: Optional[int] = None,
    group_proxy_url: Optional[str] = None,
    group_proxy_mode: Optional[str] = None,
    target_url: str = "",
) -> Tuple[str, bool]:
    """从账号记录或分组信息解析有效代理。"""
    if account is not None:
        if group_proxy_url is None and ("proxy_url" in account or "group_proxy_url" in account):
            group_proxy_url = account.get("proxy_url") if "proxy_url" in account else account.get("group_proxy_url")
        if group_proxy_mode is None and ("proxy_mode" in account or "group_proxy_mode" in account):
            group_proxy_mode = account.get("proxy_mode") if "proxy_mode" in account else account.get("group_proxy_mode")
        if group_id is None:
            group_id = account.get("group_id")

    return resolve_proxy_url(
        group_proxy_url=group_proxy_url,
        group_proxy_mode=group_proxy_mode,
        group_id=group_id,
        target_url=target_url,
    )


def resolve_system_proxy(
    *,
    override_url: Optional[str] = None,
    target_url: str = "",
) -> Tuple[str, bool]:
    """解析系统级外网服务（OAuth 工具 / 临时邮箱 / AI / Telegram / Webhook / 版本检查）代理。"""
    return resolve_proxy_url(
        override_url=override_url,
        target_url=target_url,
        allow_global=True,
    )


def build_requests_proxies(
    proxy_url: Optional[str],
    *,
    force_direct: bool = False,
) -> Optional[Dict[str, Any]]:
    """构建 requests 所需的 proxies 字典。"""
    if force_direct:
        return {"http": None, "https": None}
    clean = str(proxy_url or "").strip()
    if not clean:
        return None
    return {"http": clean, "https": clean}


def build_requests_proxy_kwargs(
    proxy_url: Optional[str],
    *,
    force_direct: bool = False,
) -> Dict[str, Any]:
    """仅当存在有效代理或强制直连时返回 {'proxies': ...}，保持默认调用参数零侵入。"""
    proxies = build_requests_proxies(proxy_url, force_direct=force_direct)
    if proxies is None:
        return {}
    return {"proxies": proxies}


class _ProxiedIMAP4_SSL(imaplib.IMAP4_SSL):
    """通过 PySocks (SOCKS5/SOCKS4/HTTP CONNECT) 建立隧道后再进行 TLS 握手的 IMAP4_SSL 客户端。"""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        proxy_url: str,
        ssl_context: Optional[ssl.SSLContext] = None,
        timeout: int = DEFAULT_IMAP_TIMEOUT,
    ) -> None:
        self._proxy_url = proxy_url
        super().__init__(host=host, port=port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout: Optional[float] = None):
        import socks

        parsed = urlsplit(self._proxy_url)
        scheme = (parsed.scheme or "").lower()
        proxy_type_map = {
            "socks5": (socks.SOCKS5, False),
            "socks5h": (socks.SOCKS5, True),
            "socks4": (socks.SOCKS4, False),
            "socks4a": (socks.SOCKS4, True),
            "http": (socks.HTTP, True),
            "https": (socks.HTTP, True),
        }
        if scheme not in proxy_type_map:
            raise ValueError(f"IMAP 暂不支持该代理协议: {scheme}")

        proxy_type, rdns = proxy_type_map[scheme]
        default_port = 1080 if scheme.startswith("socks") else 8080
        proxy_host = parsed.hostname
        proxy_port = parsed.port or default_port
        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None

        raw_sock = socks.socksocket()
        raw_sock.settimeout(timeout if timeout is not None else DEFAULT_IMAP_TIMEOUT)
        raw_sock.set_proxy(
            proxy_type=proxy_type,
            addr=proxy_host,
            port=proxy_port,
            rdns=rdns,
            username=username,
            password=password,
        )
        try:
            raw_sock.connect((self.host, self.port))
            return self.ssl_context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            try:
                raw_sock.close()
            except Exception:
                pass
            raise


def create_imap_ssl_connection(
    host: str,
    port: int = 993,
    *,
    proxy_url: str = "",
    timeout: int = DEFAULT_IMAP_TIMEOUT,
) -> imaplib.IMAP4_SSL:
    """
    创建 IMAP4_SSL 连接：
    - 无代理时直接调用标准 imaplib.IMAP4_SSL（保持与既有单测 mock 完全兼容）
    - 配置代理时走 PySocks 代理隧道并执行 TLS 握手
    """
    clean_proxy = str(proxy_url or "").strip()
    if not clean_proxy:
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    return _ProxiedIMAP4_SSL(host, port, proxy_url=clean_proxy, timeout=timeout)


def test_proxy_connectivity(
    proxy_url: str,
    *,
    target_url: str = DEFAULT_PROXY_TEST_URL,
    timeout: int = 10,
) -> Dict[str, Any]:
    """实测代理 HTTPS 连通性与延迟（ms）。"""
    clean_proxy = str(proxy_url or "").strip()
    if not clean_proxy:
        return {
            "ok": False,
            "latency_ms": 0,
            "message": "请先输入代理地址",
            "message_en": "Please enter a proxy URL first",
        }

    valid, err_msg = validate_proxy_url(clean_proxy)
    if not valid:
        return {
            "ok": False,
            "latency_ms": 0,
            "message": err_msg,
            "message_en": "Invalid proxy URL format",
        }

    proxies = build_requests_proxies(clean_proxy)
    t0 = time.monotonic()
    try:
        resp = requests.get(target_url, proxies=proxies, timeout=timeout)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if 200 <= resp.status_code < 400:
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "status_code": resp.status_code,
                "proxy_masked": mask_proxy_url(clean_proxy),
                "message": f"代理连通成功（HTTP {resp.status_code}，延迟 {latency_ms} ms）",
                "message_en": f"Proxy connected (HTTP {resp.status_code}, {latency_ms} ms)",
            }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "status_code": resp.status_code,
            "proxy_masked": mask_proxy_url(clean_proxy),
            "message": f"代理可达但目标返回 HTTP {resp.status_code}",
            "message_en": f"Proxy reachable but target returned HTTP {resp.status_code}",
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        safe_err = sanitize_proxy_error(exc, clean_proxy)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "proxy_masked": mask_proxy_url(clean_proxy),
            "message": f"代理连接失败：{safe_err}",
            "message_en": f"Proxy connection failed: {safe_err}",
        }
