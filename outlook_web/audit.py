from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import g

from outlook_web.db import get_db
from outlook_web.security.auth import get_client_ip


def log_audit(action: str, resource_type: str, resource_id: str = None, details: str = None):
    """
    记录审计日志
    :param action: 操作类型（如 'export', 'delete', 'update'）
    :param resource_type: 资源类型（如 'account', 'group'）
    :param resource_id: 资源ID
    :param details: 详细信息
    """
    try:
        db = get_db()
        user_ip = get_client_ip()
        trace_id_value = None
        try:
            trace_id_value = getattr(g, "trace_id", None)
        except Exception:
            trace_id_value = None
        db.execute(
            """
            INSERT INTO audit_logs (action, resource_type, resource_id, user_ip, details, trace_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (action, resource_type, resource_id, user_ip, details, trace_id_value),
        )
        db.commit()
    except Exception:
        # 审计日志失败不应影响主流程
        pass


def query_audit_logs(
    *,
    limit: int,
    offset: int,
    action: str,
    resource_type: str,
    trace_id: str = "",
) -> Dict[str, Any]:
    db = get_db()
    limit = max(1, min(limit or 50, 200))
    offset = max(0, offset or 0)

    action = (action or "").strip()
    resource_type = (resource_type or "").strip()
    trace_id = (trace_id or "").strip()

    where_clauses: List[str] = []
    params: List[Any] = []
    if action:
        where_clauses.append("action = ?")
        params.append(action)
    if resource_type:
        where_clauses.append("resource_type = ?")
        params.append(resource_type)
    if trace_id:
        where_clauses.append("trace_id = ?")
        params.append(trace_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total_row = db.execute(f"SELECT COUNT(*) as c FROM audit_logs {where_sql}", params).fetchone()
    total = total_row["c"] if total_row else 0

    rows = db.execute(
        f"""
        SELECT id, action, resource_type, resource_id, user_ip, details, trace_id, created_at
        FROM audit_logs
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    logs: List[Dict[str, Any]] = []
    for r in rows:
        details_text: Optional[str] = r["details"] or ""
        if isinstance(details_text, str) and len(details_text) > 800:
            details_text = details_text[:800] + "..."
        logs.append(
            {
                "id": r["id"],
                "action": r["action"],
                "resource_type": r["resource_type"],
                "resource_id": r["resource_id"],
                "user_ip": r["user_ip"],
                "details": details_text,
                "trace_id": r["trace_id"],
                "created_at": r["created_at"],
            }
        )

    return {
        "logs": logs,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
