from __future__ import annotations

from typing import Any

from flask import jsonify, request

from outlook_web.audit import query_audit_logs
from outlook_web.security.auth import login_required

# ==================== 审计日志 API ====================


@login_required
def api_get_audit_logs() -> Any:
    """获取审计日志（敏感操作可追溯）"""
    data = query_audit_logs(
        limit=request.args.get("limit", type=int) or 50,
        offset=request.args.get("offset", type=int) or 0,
        action=request.args.get("action") or "",
        resource_type=request.args.get("resource_type") or "",
        trace_id=request.args.get("trace_id") or "",
    )
    return jsonify({"success": True, **data})
