from __future__ import annotations

from typing import Optional

from outlook_web.db import get_db


def log_refresh_result(
    account_id: int,
    account_email: str,
    refresh_type: str,
    status: str,
    error_message: str = None,
    run_id: str = None,
) -> bool:
    """记录刷新结果到数据库"""
    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message, run_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (account_id, account_email, refresh_type, status, error_message, run_id),
        )

        if status == "success":
            db.execute(
                """
                UPDATE accounts
                SET last_refresh_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    status = CASE WHEN status = 'inactive' THEN 'active' ELSE status END
                WHERE id = ?
                """,
                (account_id,),
            )

        db.commit()
        return True
    except Exception:
        return False
