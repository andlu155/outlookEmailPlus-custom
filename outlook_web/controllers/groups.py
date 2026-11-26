from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from flask import Response, jsonify, request

from outlook_web.audit import log_audit
from outlook_web.errors import (
    build_error_response,
    build_export_verify_failure_response,
)
from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import groups as groups_repo
from outlook_web.repositories import temp_emails as temp_emails_repo
from outlook_web.security.auth import (
    consume_export_verify_token,
    get_client_ip,
    get_user_agent,
    login_required,
)
from outlook_web.utils.common import sanitize_input

# ==================== 分组 API ====================


@login_required
def api_get_groups() -> Any:
    """获取所有分组（含各分组邮箱数量，单次 SQL 聚合）"""
    groups = groups_repo.load_groups_with_account_count()
    # 临时邮箱分组的数量需要从 temp_emails 表获取
    temp_group = next((g for g in groups if g["name"] == "临时邮箱"), None)
    if temp_group is not None:
        temp_group["account_count"] = temp_emails_repo.get_temp_email_count()
    return jsonify({"success": True, "groups": groups})


@login_required
def api_get_group(group_id: int) -> Any:
    """获取单个分组"""
    group = groups_repo.get_group_by_id(group_id)
    if not group:
        return build_error_response(
            "GROUP_NOT_FOUND",
            err_type="NotFoundError",
            status=404,
            details=f"group_id={group_id}",
        )
    group["account_count"] = groups_repo.get_group_account_count(group_id)
    return jsonify({"success": True, "group": group})


@login_required
def api_add_group() -> Any:
    """添加分组"""
    data = request.get_json(silent=True) or {}
    name = sanitize_input(str(data.get("name") or "").strip(), max_length=100)
    description = sanitize_input(str(data.get("description") or ""), max_length=500)
    color = str(data.get("color") or "#1a1a1a")
    proxy_url = str(data.get("proxy_url") or "").strip()
    proxy_mode = str(data.get("proxy_mode") or "").strip()

    verification_code_length = data.get("verification_code_length", "6-6")
    verification_code_regex = data.get("verification_code_regex", "")
    # group 侧 AI 配置已迁移到系统设置；对历史字段软兼容（忽略）
    verification_ai_enabled = 0
    verification_ai_model = ""

    if not name:
        return build_error_response(
            "GROUP_NAME_REQUIRED",
            "分组名称不能为空",
            message_en="Group name is required",
        )

    try:
        group_id = groups_repo.add_group(
            name,
            description,
            color,
            proxy_url,
            verification_code_length=verification_code_length,
            verification_code_regex=verification_code_regex,
            verification_ai_enabled=verification_ai_enabled,
            verification_ai_model=verification_ai_model,
            proxy_mode=proxy_mode,
        )
    except groups_repo.GroupPolicyValidationError as exc:
        return build_error_response(exc.code, exc.message, status=400)

    if group_id:
        effective_mode = proxy_mode or ("custom" if proxy_url else "inherit")
        details = json.dumps(
            {
                "name": name,
                "has_description": bool(description),
                "color": color,
                "proxy_mode": effective_mode,
                "proxy_configured": bool(proxy_url) and effective_mode == "custom",
                "verification_code_length": str(verification_code_length or "").strip() or "6-6",
                "verification_regex_configured": bool(str(verification_code_regex or "").strip()),
            },
            ensure_ascii=False,
        )
        log_audit("create", "group", str(group_id), details)
        return jsonify(
            {
                "success": True,
                "message": "分组创建成功",
                "message_en": "Group created successfully",
                "group_id": group_id,
            }
        )
    return build_error_response(
        "GROUP_NAME_DUPLICATED",
        "分组名称已存在",
        message_en="Group name already exists",
    )


@login_required
def api_update_group(group_id: int) -> Any:
    """更新分组"""
    data = request.get_json(silent=True) or {}

    existing = groups_repo.get_group_by_id(group_id)
    if not existing:
        return build_error_response(
            "GROUP_NOT_FOUND",
            err_type="NotFoundError",
            status=404,
            details=f"group_id={group_id}",
        )

    name = sanitize_input(str(data.get("name") or "").strip(), max_length=100)
    description = sanitize_input(str(data.get("description") or ""), max_length=500)
    color = str(data.get("color") or "#1a1a1a")
    proxy_url = str(data.get("proxy_url") or "").strip()
    proxy_mode = str(data.get("proxy_mode") or "").strip()

    verification_code_length = data.get(
        "verification_code_length",
        existing.get("verification_code_length") if existing else "6-6",
    )
    verification_code_regex = data.get(
        "verification_code_regex",
        existing.get("verification_code_regex") if existing else "",
    )
    # group 侧 AI 配置已迁移到系统设置；对历史字段软兼容（忽略）
    verification_ai_enabled = 0
    verification_ai_model = ""

    if not name:
        return build_error_response(
            "GROUP_NAME_REQUIRED",
            "分组名称不能为空",
            message_en="Group name is required",
        )

    # 系统分组保护：不允许重命名（避免破坏系统逻辑）
    if existing.get("is_system") and name != existing.get("name"):
        return build_error_response(
            "SYSTEM_GROUP_PROTECTED",
            "系统分组不允许重命名",
            message_en="System groups cannot be renamed",
            err_type="ForbiddenError",
            status=403,
            details=f"group_id={group_id}",
        )

    try:
        updated = groups_repo.update_group(
            group_id,
            name,
            description,
            color,
            proxy_url,
            verification_code_length=verification_code_length,
            verification_code_regex=verification_code_regex,
            verification_ai_enabled=verification_ai_enabled,
            verification_ai_model=verification_ai_model,
            proxy_mode=proxy_mode,
        )
    except groups_repo.GroupPolicyValidationError as exc:
        return build_error_response(exc.code, exc.message, status=400)

    if updated:
        # 不记录 proxy_url 明文（可能包含代理账号/密码）
        effective_mode = proxy_mode or ("custom" if proxy_url else "inherit")
        details = json.dumps(
            {
                "name": name,
                "has_description": bool(description),
                "color": color,
                "proxy_mode": effective_mode,
                "proxy_configured": bool(proxy_url) and effective_mode == "custom",
                "verification_code_length": str(verification_code_length or "").strip() or "6-6",
                "verification_regex_configured": bool(str(verification_code_regex or "").strip()),
            },
            ensure_ascii=False,
        )
        log_audit("update", "group", str(group_id), details)
        return jsonify(
            {
                "success": True,
                "message": "分组更新成功",
                "message_en": "Group updated successfully",
            }
        )
    return build_error_response(
        "GROUP_UPDATE_FAILED",
        "更新失败",
        message_en="Failed to update group",
        status=500,
    )


@login_required
def api_delete_group(group_id: int) -> Any:
    """删除分组"""
    group = groups_repo.get_group_by_id(group_id)
    if not group:
        return build_error_response(
            "GROUP_NOT_FOUND",
            err_type="NotFoundError",
            status=404,
            details=f"group_id={group_id}",
        )

    if group.get("is_system"):
        return build_error_response(
            "SYSTEM_GROUP_PROTECTED",
            "系统分组不能删除",
            message_en="System groups cannot be deleted",
            err_type="ForbiddenError",
            status=403,
            details=f"group_id={group_id}",
        )

    default_group_id = groups_repo.get_default_group_id()
    if group_id == default_group_id or group.get("name") == "默认分组":
        return build_error_response(
            "DEFAULT_GROUP_PROTECTED",
            "默认分组不能删除",
            message_en="The default group cannot be deleted",
            err_type="ForbiddenError",
            status=403,
            details=f"group_id={group_id}",
        )

    if groups_repo.delete_group(group_id):
        log_audit("delete", "group", str(group_id), "删除分组并迁移账号到默认分组")
        return jsonify(
            {
                "success": True,
                "message": "分组已删除，邮箱已移至默认分组",
                "message_en": "Group deleted and accounts moved to the default group",
            }
        )
    return build_error_response(
        "GROUP_DELETE_FAILED",
        "删除失败",
        message_en="Failed to delete group",
        status=500,
    )


@login_required
def api_export_group(group_id: int) -> Any:
    """导出分组下的所有邮箱账号为 TXT 文件（需要二次验证）"""
    # 从请求头获取二次验证 token（避免 URL 泄露）
    verify_token = request.headers.get("X-Export-Token")
    client_ip = get_client_ip()
    user_agent = get_user_agent()

    ok, error_message = consume_export_verify_token(verify_token, client_ip, user_agent)
    if not ok:
        return build_export_verify_failure_response(error_message)

    group = groups_repo.get_group_by_id(group_id)
    if not group:
        return build_error_response(
            "GROUP_NOT_FOUND",
            err_type="NotFoundError",
            status=404,
            details=f"group_id={group_id}",
        )

    # 使用 load_accounts 获取该分组下的所有账号（自动解密）
    accounts = accounts_repo.load_accounts(group_id)

    if not accounts:
        return build_error_response(
            "GROUP_HAS_NO_ACCOUNTS",
            "该分组下没有邮箱账号",
            message_en="No accounts were found in this group",
            status=404,
        )

    # 记录审计日志
    log_audit(
        "export",
        "group",
        str(group_id),
        f"导出分组 '{group['name']}' 的 {len(accounts)} 个账号",
    )

    # 生成导出内容（复用 accounts._build_export_text，兼容 Outlook 与通用 IMAP 账号）
    from outlook_web.controllers.accounts import _build_export_text

    content = _build_export_text(accounts)

    # 生成文件名（使用 URL 编码处理中文）
    filename = f"{group['name']}_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )
