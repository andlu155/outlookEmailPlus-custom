"""号池管理内部服务层（Issue #60）

职责：
- 承载内部管理动作规则
- 定义允许状态集合
- 对 claimed 做保护
- 强制释放时复用 repository 原子操作
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from outlook_web.db import create_sqlite_connection
from outlook_web.repositories import pool_admin as pool_admin_repo

logger = logging.getLogger(__name__)

# 动作 → 允许的起始状态集合 → 目标状态
ACTION_RULES: Dict[str, Dict[str, Optional[str]]] = {
    "move_into_pool": {
        "from_states": {None},
        "to_state": "available",
    },
    "move_out_of_pool": {
        "from_states": {"available", "cooldown", "used", "frozen", "retired"},
        "to_state": None,
    },
    "restore_available": {
        "from_states": {"cooldown", "used", "frozen", "retired"},
        "to_state": "available",
    },
    "freeze": {
        "from_states": {"available", "cooldown", "used"},
        "to_state": "frozen",
    },
    "retire": {
        "from_states": {"available", "cooldown", "used", "frozen"},
        "to_state": "retired",
    },
}

# 强制释放是独立动作，不放在 ACTION_RULES 中，避免被通用逻辑误用


def apply_action(
    account_id: int,
    action: str,
    *,
    operator: Optional[str] = None,
) -> Dict[str, any]:
    """对单个账号执行号池管理动作。

    返回统一结构：{"success": bool, "message": str, "error_code": str, "data": dict}
    """
    conn = create_sqlite_connection()
    try:
        # 使用 BEGIN IMMEDIATE 防止与并发 claim-random 产生 TOCTOU 状态竞态
        conn.execute("BEGIN IMMEDIATE")
        current_status = pool_admin_repo.get_account_pool_status(conn, account_id)

        # 1. 校验账号是否存在
        row = conn.execute("SELECT id, email FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            conn.rollback()
            return {"success": False, "message": "账号不存在", "error_code": "ACCOUNT_NOT_FOUND", "data": {}}

        # 2. 强制释放：独立路径
        if action == "force_release":
            if current_status != "claimed":
                conn.rollback()
                return {
                    "success": False,
                    "message": f"账号当前状态为 '{current_status or 'NULL'}'，无法强制释放",
                    "error_code": "NOT_CLAIMED",
                    "data": {},
                }
            pool_admin_repo.force_release(conn, account_id=account_id)
            logger.info("[pool_admin] force_release account_id=%s by operator=%s", account_id, operator)
            return {
                "success": True,
                "message": "强制释放成功",
                "data": {"account_id": account_id, "previous_status": "claimed", "new_status": "available"},
            }

        # 3. 通用动作校验
        rule = ACTION_RULES.get(action)
        if rule is None:
            conn.rollback()
            return {"success": False, "message": f"未知动作: {action}", "error_code": "INVALID_ACTION", "data": {}}

        # claimed 保护：通用动作一律不允许在 claimed 上执行
        if current_status == "claimed":
            conn.rollback()
            return {
                "success": False,
                "message": "账号当前处于占用中（claimed），请先强制释放后再执行此操作",
                "error_code": "CLAIMED_PROTECTED",
                "data": {},
            }

        if current_status not in rule["from_states"]:
            conn.rollback()
            readable_from = ", ".join(str(s or "NULL") for s in rule["from_states"])
            return {
                "success": False,
                "message": f"当前状态 '{current_status or 'NULL'}' 不允许执行 {action}，允许的状态: {readable_from}",
                "error_code": "INVALID_STATE_TRANSITION",
                "data": {},
            }

        # 4. 执行更新
        new_status = rule["to_state"]
        pool_admin_repo.update_pool_status(conn, account_id=account_id, new_pool_status=new_status)

        logger.info(
            "[pool_admin] action=%s account_id=%s prev=%s new=%s operator=%s",
            action,
            account_id,
            current_status,
            new_status,
            operator,
        )

        return {
            "success": True,
            "message": "操作成功",
            "data": {"account_id": account_id, "previous_status": current_status, "new_status": new_status},
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def list_accounts(
    *,
    in_pool: str = "all",
    pool_status: Optional[str] = None,
    provider: Optional[str] = None,
    group_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, any]:
    """号池管理列表查询（Service 层透传）。"""
    conn = create_sqlite_connection()
    try:
        return pool_admin_repo.list_accounts(
            conn,
            in_pool=in_pool,
            pool_status=pool_status,
            provider=provider,
            group_id=group_id,
            search=search,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()
