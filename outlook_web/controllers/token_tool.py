"""OAuth Token 获取工具 — 控制器层

编排 OAuth 授权流程、Token 换取、账号写入等业务操作。
被 routes/token_tool.py 的 Blueprint 路由直接调用。

业务背景:
  - PRD: docs/PRD/2026-04-12-OAuth-Token获取工具PRD.md (v1.3)
  - 收口范围: "兼容账号导入模式" — tenant 固定 consumers, 禁用 client_secret

设计决策 (FD v1.0 §收口说明):
  - prepare / config / save 接口均拒绝不兼容输入 (client_secret / 非 consumers tenant)
  - save_to_account 使用 test_refresh_token_with_rotation 验证后再写入
  - 回调页 (popup_result.html) 不直接换取 token, 统一走手动粘贴 exchange 接口
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from flask import abort, jsonify, render_template, request, session

from outlook_web import config as app_config
from outlook_web.audit import log_audit
from outlook_web.errors import build_error_response
from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import settings as settings_repo
from outlook_web.security.auth import login_required
from outlook_web.services import graph as graph_service
from outlook_web.services import oauth_tool as oauth_tool_service

# 兼容模式常量 — 当前仅支持个人 Microsoft 账号导入 (FD 收口说明)
COMPATIBLE_TENANT = "consumers"
LEGACY_GRAPH_SCOPE = "offline_access https://graph.microsoft.com/.default"
COMPATIBLE_SCOPE = app_config.get_oauth_scope_default()


def _ensure_oauth_tool_enabled() -> None:
    """功能开关守卫: OAUTH_TOOL_ENABLED=false 时返回 404 (PRD §2.8)"""
    if not app_config.get_oauth_tool_enabled():
        abort(404)


def _compatibility_mode_error(client_secret: str, tenant: str) -> str | None:
    """兼容模式校验: 拒绝 client_secret 和非 consumers tenant (FD 收口说明)"""
    normalized_tenant = (tenant or COMPATIBLE_TENANT).strip() or COMPATIBLE_TENANT
    if client_secret:
        return "兼容账号导入模式不支持 Client Secret，请使用公共客户端并保持 Client Secret 为空"
    if normalized_tenant != COMPATIBLE_TENANT:
        return "兼容账号导入模式仅支持 tenant=consumers，请使用与购买账号一致的个人 Microsoft 账号配置"
    return None


def _save_validation_guidance(error_msg: str) -> str | None:
    """针对特定 Azure 错误码返回修复指引 (AADSTS9002331 — 仅个人账号与 /common 冲突)"""
    detail = (error_msg or "").lower()
    if "aadsts9002331" in detail or "/consumers endpoint" in detail:
        return "当前 Azure 应用被配置为仅 Personal Microsoft accounts，这会与系统现有的 /common 验证与运行模型冲突。请将 Supported account types 改为“Accounts in any identity provider or organizational directory and personal Microsoft accounts”。"
    return None


@login_required
def render_page() -> Any:
    _ensure_oauth_tool_enabled()
    return render_template("token_tool.html")


@login_required
def prepare_oauth() -> Any:
    _ensure_oauth_tool_enabled()
    data = request.get_json(silent=True) or {}

    client_id = (data.get("client_id") or "").strip()
    if not client_id:
        return build_error_response("OAUTH_CONFIG_INVALID", "Client ID 不能为空", status=400)

    redirect_uri = (data.get("redirect_uri") or "").strip()
    if not redirect_uri or not redirect_uri.startswith(("http://", "https://")):
        return build_error_response("OAUTH_CONFIG_INVALID", "Redirect URI 格式无效", status=400)

    client_secret = (data.get("client_secret") or "").strip()
    tenant = (data.get("tenant") or COMPATIBLE_TENANT).strip() or COMPATIBLE_TENANT
    compatibility_error = _compatibility_mode_error(client_secret, tenant)
    if compatibility_error:
        return build_error_response("OAUTH_CONFIG_INVALID", compatibility_error, status=400)

    oauth_config = {
        "client_id": client_id,
        "client_secret": "",
        "redirect_uri": redirect_uri,
        "scope": (data.get("scope") or "").strip(),
        "tenant": COMPATIBLE_TENANT,
        "prompt_consent": bool(data.get("prompt_consent")),
    }

    authorize_url, state_or_error = oauth_tool_service.start_oauth_flow(oauth_config)
    if authorize_url is None:
        return build_error_response("OAUTH_CONFIG_INVALID", state_or_error, status=400)

    session["oauth_state"] = state_or_error
    return jsonify({"success": True, "data": {"authorize_url": authorize_url}})


def handle_callback() -> Any:
    _ensure_oauth_tool_enabled()
    error = request.args.get("error")
    error_description = request.args.get("error_description", "")

    if error:
        guidance = oauth_tool_service.map_error_guidance(error)
        return render_template(
            "popup_result.html",
            error=True,
            error_code=error,
            error_description=error_description,
            guidance=guidance,
        )

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        return render_template(
            "popup_result.html",
            error=True,
            error_code="missing_params",
            error_description="回调缺少 code 或 state 参数",
            guidance="请重新点击『登录 Microsoft』",
        )

    return render_template("popup_result.html", error=False)


@login_required
def exchange_token() -> Any:
    _ensure_oauth_tool_enabled()
    data = request.get_json(silent=True) or {}
    callback_url = (data.get("callback_url") or "").strip()
    if not callback_url:
        return build_error_response("OAUTH_CODE_PARSE_FAILED", "请粘贴回调 URL", status=400)

    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]

    if not code:
        return build_error_response("OAUTH_CODE_PARSE_FAILED", "URL 中未包含 code 参数", status=400)
    if not state:
        return build_error_response("OAUTH_CODE_PARSE_FAILED", "URL 中未包含 state 参数", status=400)

    # 双层 state 校验 (FD §5.3): Session cookie 防 CSRF + 内存 Store 携带 PKCE verifier
    session_state = session.get("oauth_state")
    if not session_state or session_state != state:
        return build_error_response(
            "OAUTH_MICROSOFT_AUTH_FAILED",
            "state 校验失败，请重新发起授权",
            status=400,
        )

    flow_data = oauth_tool_service.get_oauth_flow(state)
    if not flow_data:
        return build_error_response(
            "OAUTH_CODE_INVALID",
            "授权流程已过期（超过 20 分钟），请重新发起",
            status=400,
        )

    # 换取成功后立即清除 flow 数据,防止授权码重放攻击
    token_data, error_info = oauth_tool_service.exchange_code_for_tokens(
        code=code,
        oauth_config={
            "client_id": flow_data["client_id"],
            "client_secret": flow_data.get("client_secret", ""),
            "redirect_uri": flow_data["redirect_uri"],
            "scope": flow_data["scope"],
            "tenant": flow_data.get("tenant", "consumers"),
        },
        verifier=flow_data["verifier"],
    )

    oauth_tool_service.discard_oauth_flow(state)
    session.pop("oauth_state", None)

    if token_data is None:
        if isinstance(error_info, dict):
            return build_error_response(
                "OAUTH_MICROSOFT_REQUEST_FAILED",
                error_info.get("message", "换取 Token 失败"),
                status=400,
                details=error_info.get("guidance"),
            )
        return build_error_response("OAUTH_MICROSOFT_REQUEST_FAILED", str(error_info), status=400)

    log_audit("create", "oauth_token", flow_data["client_id"], "Token 获取成功")
    return jsonify({"success": True, "data": token_data})


@login_required
def save_to_account() -> Any:
    _ensure_oauth_tool_enabled()
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip()
    client_id = (data.get("client_id") or "").strip()

    if not refresh_token:
        return build_error_response("OAUTH_REFRESH_TOKEN_MISSING", "refresh_token 不能为空", status=400)
    if not client_id:
        return build_error_response("OAUTH_CONFIG_INVALID", "client_id 不能为空", status=400)

    compatibility_error = _compatibility_mode_error(
        (data.get("client_secret") or "").strip(),
        (data.get("tenant") or COMPATIBLE_TENANT).strip() or COMPATIBLE_TENANT,
    )
    if compatibility_error:
        return build_error_response("OAUTH_CONFIG_INVALID", compatibility_error, status=400)

    explicit_scope = (data.get("scope") or data.get("requested_scope") or data.get("granted_scope") or "").strip()
    validation_scope = explicit_scope or COMPATIBLE_SCOPE
    if not explicit_scope and validation_scope == LEGACY_GRAPH_SCOPE:
        validation_scope = COMPATIBLE_SCOPE

    valid, error_msg, new_rt = graph_service.test_refresh_token_with_rotation(
        client_id,
        refresh_token,
        tenant=COMPATIBLE_TENANT,
        scope=validation_scope,
    )
    if not valid:
        guidance = _save_validation_guidance(error_msg or "")
        return build_error_response(
            "OAUTH_MICROSOFT_REQUEST_FAILED",
            f"Token 验证失败: {error_msg}",
            status=400,
            details=guidance,
        )
    if new_rt:
        refresh_token = new_rt

    if mode == "update":
        account_id = data.get("account_id")
        if not account_id:
            return build_error_response("OAUTH_CONFIG_INVALID", "account_id 不能为空", status=400)
        try:
            account_id_int = int(account_id)
        except (TypeError, ValueError):
            return build_error_response("OAUTH_CONFIG_INVALID", "account_id 格式无效", status=400)

        existing = accounts_repo.get_account_by_id(account_id_int)
        if not existing:
            return build_error_response("ACCOUNT_NOT_FOUND", "账号不存在", status=404)

        success = accounts_repo.update_account_credentials(
            account_id_int,
            client_id=client_id,
            refresh_token=refresh_token,
        )
        if not success:
            return build_error_response("INTERNAL_ERROR", "更新账号失败", status=500)

        success = accounts_repo.update_account(
            account_id=account_id_int,
            email_addr=existing["email"],
            password=None,
            client_id=client_id,
            refresh_token=refresh_token,
            group_id=existing.get("group_id") or 1,
            remark=existing.get("remark") or "",
            status="active",
        )
        if not success:
            return build_error_response("INTERNAL_ERROR", "更新账号失败", status=500)

        log_audit(
            "update",
            "account",
            str(account_id_int),
            f"Token 工具写入 (client_id={client_id[:8]}...)",
        )
        return jsonify(
            {
                "success": True,
                "data": {
                    "account_id": account_id_int,
                    "email": existing["email"],
                    "status": "active",
                    "token_valid": True,
                },
            }
        )

    if mode == "create":
        email = (data.get("email") or "").strip()
        if not email or "@" not in email:
            return build_error_response("OAUTH_CONFIG_INVALID", "邮箱格式无效", status=400)

        success = accounts_repo.add_account(
            email_addr=email,
            password="",
            client_id=client_id,
            refresh_token=refresh_token,
            account_type="outlook",
            provider="outlook",
        )
        if not success:
            return build_error_response("INTERNAL_ERROR", "创建账号失败（邮箱可能已存在）", status=400)

        created = accounts_repo.get_account_by_email(email)
        log_audit("create", "account", email, f"Token 工具新建 (client_id={client_id[:8]}...)")
        return jsonify(
            {
                "success": True,
                "data": {
                    "account_id": created["id"] if created else None,
                    "email": email,
                    "status": "active",
                    "token_valid": True,
                },
            }
        )

    return build_error_response("OAUTH_CONFIG_INVALID", "mode 必须是 update 或 create", status=400)


@login_required
def get_account_list() -> Any:
    _ensure_oauth_tool_enabled()
    accounts = accounts_repo.load_accounts()
    result = [
        {
            "id": account["id"],
            "email": account["email"],
            "status": account.get("status", "active"),
            "account_type": account.get("account_type", "outlook"),
        }
        for account in accounts
        if account.get("account_type") in ("outlook", None)
    ]
    return jsonify({"success": True, "data": result})


@login_required
def get_config() -> Any:
    _ensure_oauth_tool_enabled()
    scope_value = settings_repo.get_oauth_tool_scope()
    if scope_value == LEGACY_GRAPH_SCOPE:
        scope_value = app_config.get_oauth_scope_default()
    return jsonify(
        {
            "success": True,
            "data": {
                "client_id": settings_repo.get_oauth_tool_client_id(),
                "client_secret": "",
                "redirect_uri": settings_repo.get_oauth_tool_redirect_uri(),
                "scope": scope_value,
                "tenant": COMPATIBLE_TENANT,
                "prompt_consent": settings_repo.get_oauth_tool_prompt_consent(),
            },
        }
    )


@login_required
def save_config() -> Any:
    _ensure_oauth_tool_enabled()
    data = request.get_json(silent=True) or {}
    client_secret = (data.get("client_secret") or "").strip()
    tenant = (data.get("tenant") or COMPATIBLE_TENANT).strip() or COMPATIBLE_TENANT
    compatibility_error = _compatibility_mode_error(client_secret, tenant)
    if compatibility_error:
        return build_error_response("OAUTH_CONFIG_INVALID", compatibility_error, status=400)

    settings_repo.set_setting("oauth_tool_client_id", (data.get("client_id") or "").strip())
    settings_repo.set_setting("oauth_tool_client_secret", "")
    settings_repo.set_setting("oauth_tool_redirect_uri", (data.get("redirect_uri") or "").strip())
    settings_repo.set_setting("oauth_tool_scope", (data.get("scope") or "").strip())
    settings_repo.set_setting("oauth_tool_tenant", COMPATIBLE_TENANT)
    settings_repo.set_setting("oauth_tool_prompt_consent", "true" if data.get("prompt_consent") else "false")

    log_audit("update", "oauth_tool_config", "settings", "保存 OAuth 工具配置")
    return jsonify({"success": True, "message": "配置已保存"})
