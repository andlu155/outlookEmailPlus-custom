"""OAuth Token 获取工具 — 服务层

提供 PKCE 生成、授权 URL 构建、授权码换取 Token、Scope 校验等核心逻辑。
为 controllers/token_tool.py 提供无 Flask 依赖的纯业务服务。

业务背景:
  - PRD: docs/PRD/2026-04-12-OAuth-Token获取工具PRD.md (v1.3)
  - Issue: #38, #34, #26, #20, #18

设计决策:
  - FD: docs/FD/2026-04-12-OAuth-Token获取工具FD.md
  - 内存存储 OAUTH_FLOW_STORE: 单进程安全,20 分钟 TTL 自动清理;
    Docker 部署需 workers=1 (与现有 gunicorn 配置一致)
  - PKCE 强制 S256: 公共客户端安全最佳实践,不依赖 client_secret
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from threading import Lock
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

from outlook_web.services import proxy as proxy_service

logger = logging.getLogger(__name__)

# OAUTH_FLOW_STORE — 模块级内存存储,保存 OAuth 授权流程的中间状态
# 线程安全 (Lock) + 自动过期 (20 分钟 TTL)
# 设计权衡 (FD §5.2): 单进程内安全,多实例部署需迁移 Redis; 当前 Docker workers=1 约束下够用
OAUTH_FLOW_STORE: Dict[str, Dict[str, Any]] = {}
OAUTH_FLOW_LOCK = Lock()
OAUTH_FLOW_TTL = 20 * 60  # 20 分钟 (PRD §5.1 Flow TTL)


def _prune_expired() -> None:
    """清理过期的 flow 条目（必须在 LOCK 内调用）

    惰性清理策略: 每次读写操作触发,而非后台定时线程;
    权衡: 避免额外线程复杂度,OAUTH_FLOW_STORE 条目量极小 (用户交互式操作)
    """
    now = time.time()
    expired = [k for k, v in OAUTH_FLOW_STORE.items() if now - v.get("created_at", 0) > OAUTH_FLOW_TTL]
    for k in expired:
        del OAUTH_FLOW_STORE[k]
    if expired:
        logger.debug("[oauth_tool] 清理 %d 个过期 flow", len(expired))


def store_oauth_flow(state: str, flow_data: Dict[str, Any]) -> None:
    with OAUTH_FLOW_LOCK:
        _prune_expired()
        OAUTH_FLOW_STORE[state] = {"created_at": time.time(), **flow_data}


def get_oauth_flow(state: str) -> Optional[Dict[str, Any]]:
    # 返回浅拷贝,防止调用方意外修改 Store 内部状态
    with OAUTH_FLOW_LOCK:
        _prune_expired()
        data = OAUTH_FLOW_STORE.get(state)
        return dict(data) if data else None


def discard_oauth_flow(state: str) -> None:
    with OAUTH_FLOW_LOCK:
        OAUTH_FLOW_STORE.pop(state, None)


def generate_pkce() -> Tuple[str, str]:
    """生成 PKCE code_verifier + code_challenge (S256)

    RFC 7636 规范实现。verifier 仅存在于服务端内存 (OAUTH_FLOW_STORE),
    不出现在 URL 或 Cookie 中,防止授权码拦截攻击。
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def start_oauth_flow(oauth_config: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """
    生成 Microsoft OAuth 授权 URL

    Returns:
        (authorize_url, state) — 成功
        (None, error_message)  — 失败
    """
    normalized_scope, scope_error = validate_scope(oauth_config.get("scope", ""))
    if scope_error:
        return None, scope_error

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)

    tenant = (oauth_config.get("tenant") or "consumers").strip()
    store_oauth_flow(
        state,
        {
            "client_id": oauth_config["client_id"],
            "client_secret": oauth_config.get("client_secret", ""),
            "redirect_uri": oauth_config["redirect_uri"],
            "scope": normalized_scope,
            "tenant": tenant,
            "verifier": verifier,
        },
    )

    authority = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    params = {
        "client_id": oauth_config["client_id"],
        "response_type": "code",
        "redirect_uri": oauth_config["redirect_uri"],
        "scope": normalized_scope,
        "response_mode": "query",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if oauth_config.get("prompt_consent"):
        params["prompt"] = "consent"

    authorize_url = f"{authority}/authorize?{urlencode(params)}"
    logger.info("[oauth_tool] 授权 URL 已生成 (state=%s...)", state[:8])
    return authorize_url, state


def exchange_code_for_tokens(code: str, oauth_config: Dict[str, Any], verifier: str) -> Tuple[Optional[Dict[str, Any]], Any]:
    """
    用授权码换取 token

    Returns:
        (token_data_dict, None)     — 成功
        (None, error_info)          — 失败
    """
    tenant = oauth_config.get("tenant", "consumers")
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    payload = {
        "client_id": oauth_config["client_id"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": oauth_config["redirect_uri"],
        "code_verifier": verifier,
        "scope": oauth_config["scope"],
    }
    if oauth_config.get("client_secret"):
        payload["client_secret"] = oauth_config["client_secret"]

    proxy_url, force_direct = proxy_service.resolve_system_proxy(target_url=token_url)
    proxy_kwargs = proxy_service.build_requests_proxy_kwargs(proxy_url, force_direct=force_direct)
    try:
        resp = requests.post(token_url, data=payload, timeout=15, **proxy_kwargs)
    except requests.RequestException as exc:
        safe_exc = proxy_service.sanitize_proxy_error(exc, proxy_url)
        logger.error("[oauth_tool] Token 换取网络错误: %s", safe_exc)
        return None, f"无法连接 Microsoft 服务器: {safe_exc}"

    if resp.status_code != 200:
        error_detail = _parse_error_response(resp)
        guidance = map_error_guidance(error_detail)
        logger.warning("[oauth_tool] Token 换取失败: %s", error_detail[:200])
        return None, {"message": error_detail, "guidance": guidance}

    tokens = resp.json()
    result = _extract_token_data(tokens, oauth_config)
    logger.info("[oauth_tool] Token 换取成功 (client_id=%s...)", oauth_config["client_id"][:8])
    return result, None


OIDC_SCOPES = {"openid", "profile", "email", "offline_access"}


def validate_scope(scope_value: str) -> Tuple[str, Optional[str]]:
    """
    校验并标准化 scope

    业务规则 (PRD §2.3 / FD §5.5):
    - 至少需要一个 API scope (OIDC scope 如 offline_access 不算)
    - .default scope 与命名 scope 不可混用 (Microsoft 限制)
    - 一次请求只能对应一个资源 (如 Graph 与 IMAP 不可同时请求)

    Returns:
        (normalized_scope, None)       — 合法
        (scope_value, error_message)   — 不合法
    """
    normalized = normalize_scope(scope_value)
    scopes = normalized.split()
    api_scopes = [s for s in scopes if s not in OIDC_SCOPES]

    if not api_scopes:
        return (
            normalized,
            "至少需要一个 API scope（如 https://graph.microsoft.com/.default）",
        )

    has_default = any(s.endswith("/.default") for s in api_scopes)
    has_named = any(not s.endswith("/.default") for s in api_scopes)
    if has_default and has_named:
        return normalized, "同一次请求里，`.default` scope 不能和命名 scope 混用"

    resources = {_scope_resource(s) for s in api_scopes if _scope_resource(s)}
    if len(resources) > 1:
        return normalized, "一次 OAuth 请求只能对应一个资源，请分开获取"

    return normalized, None


def normalize_scope(scope_value: str) -> str:
    """标准化 scope: 去重、排序、确保包含 offline_access"""
    scopes = set(scope_value.strip().split())
    scopes.add("offline_access")
    return " ".join(sorted(scopes))


def _scope_resource(scope: str) -> Optional[str]:
    """提取 scope 的资源前缀: https://graph.microsoft.com/Mail.Read → https://graph.microsoft.com"""
    if scope.startswith("https://"):
        parts = scope.split("/")
        if len(parts) >= 4:
            return "/".join(parts[:3])
    return None


# PRD §2.7: 常见错误中文引导映射 — 将 Microsoft OAuth 错误码转为用户可操作的排查建议
# 键名匹配 error_description 中的子串 (不区分大小写)
ERROR_GUIDANCE_MAP = {
    "unauthorized_client": "请到 Azure 门户确认应用注册已支持个人 Microsoft 账号（Supported account types 必须包含 Personal Microsoft accounts / consumers），并在『身份验证 → 高级设置』中开启『允许公共客户端流』",
    "invalid_grant": "授权码已过期或已使用，请重新点击『登录 Microsoft』",
    "invalid_scope": "请到 Azure 门户 → API 权限 → 添加对应的 Microsoft Graph 委托权限",
    "redirect_uri_mismatch": "回调地址不匹配，请确认 Azure 门户中注册的重定向 URI 与当前填写的一致",
    "interaction_required": "请勾选『强制 Consent』后重新授权",
    "consent_required": "此权限需要组织管理员同意，请联系 IT 管理员或切换为个人账号",
    "invalid_client": "Azure 仍将当前应用视为需要 client_secret 的机密客户端；请确认已开启『允许公共客户端流』，若仍报错请改用 Mobile and desktop applications 平台的 public redirect URI（如 http://localhost）并走手动粘贴回调 URL",
    "access_denied": "用户拒绝了授权请求，请重新点击『登录 Microsoft』",
}


def map_error_guidance(error_detail: str) -> str:
    """根据错误信息匹配中文引导建议"""
    detail_lower = error_detail.lower() if isinstance(error_detail, str) else ""
    for key, guidance in ERROR_GUIDANCE_MAP.items():
        if key in detail_lower:
            return guidance
    return "请检查配置后重试，如持续失败请参考 Azure 注册指引"


def decode_jwt_payload(token: str) -> Optional[dict]:
    """不验签解码 JWT payload（纯展示用途）

    从 access_token 中提取 audience / scp / roles 等诊断信息,
    帮助用户确认实际授权范围。不需要签名验证,因为仅用于页面展示。
    """
    import json as json_mod

    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(payload_b64)
        return json_mod.loads(decoded)
    except Exception:
        return None


def _parse_error_response(resp) -> str:
    try:
        err = resp.json()
        error_code = err.get("error") or ""
        error_description = err.get("error_description") or ""
        if error_code and error_description:
            return f"{error_code}: {error_description}"
        return error_description or error_code or resp.text[:500]
    except Exception:
        return resp.text[:500]


def _extract_token_data(tokens: dict, oauth_config: dict) -> dict:
    access_token = tokens.get("access_token", "")
    result = {
        "refresh_token": tokens.get("refresh_token", ""),
        "access_token": access_token,
        "expires_in": tokens.get("expires_in", 0),
        "token_type": tokens.get("token_type", "Bearer"),
        "requested_scope": oauth_config.get("scope", ""),
        "granted_scope": tokens.get("scope", ""),
        "client_id": oauth_config["client_id"],
        "redirect_uri": oauth_config["redirect_uri"],
    }

    if access_token:
        jwt_payload = decode_jwt_payload(access_token)
        if jwt_payload:
            result["audience"] = jwt_payload.get("aud", "")
            result["scope_claim"] = jwt_payload.get("scp", "")
            result["roles_claim"] = " ".join(jwt_payload.get("roles", []))
    return result
