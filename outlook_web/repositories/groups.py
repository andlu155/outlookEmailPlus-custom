from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from outlook_web.db import get_db
from outlook_web.utils.common import (
    normalize_group_proxy_mode,
    parse_bool_flag,
    validate_proxy_url,
)


class GroupPolicyValidationError(ValueError):
    """分组提取策略校验错误（供 Controller 映射错误码）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_CODE_LENGTH_RE = re.compile(r"^(\d+)-(\d+)$")
_SINGLE_CODE_LENGTH_RE = re.compile(r"^\d+$")
_CODE_LENGTH_SUFFIX_RE = re.compile(r"(位数?|码|digits?)$", re.IGNORECASE)
_CODE_LENGTH_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_bool_flag(value: Any, default: bool = False) -> bool:
    return parse_bool_flag(value, default=default)


def normalize_group_proxy_config(proxy_url: Any = "", proxy_mode: Any = "") -> tuple[str, str]:
    """标准化并校验分组代理策略，返回 (normalized_proxy_mode, normalized_proxy_url)。"""
    clean_url = _normalize_str(proxy_url)
    try:
        mode = normalize_group_proxy_mode(proxy_mode, clean_url)
    except ValueError as exc:
        raise GroupPolicyValidationError("GROUP_PROXY_MODE_INVALID", str(exc)) from exc

    if mode in {"inherit", "direct"}:
        return mode, ""

    if not clean_url:
        raise GroupPolicyValidationError("GROUP_PROXY_REQUIRED", "选择自定义代理时必须填写代理地址")

    valid, err_msg = validate_proxy_url(clean_url)
    if not valid:
        raise GroupPolicyValidationError("GROUP_PROXY_INVALID", err_msg)

    return "custom", clean_url


def _validate_code_length(value: str) -> str:
    raw_text = _normalize_str(value)
    if not raw_text:
        return "6-6"

    text = _CODE_LENGTH_WHITESPACE_RE.sub("", raw_text)
    for separator in ("~", "～", "至", "到", "－", "—", "–", "_"):
        text = text.replace(separator, "-")
    text = _CODE_LENGTH_SUFFIX_RE.sub("", text)

    if _SINGLE_CODE_LENGTH_RE.match(text):
        text = f"{int(text)}-{int(text)}"

    match = _CODE_LENGTH_RE.match(text)
    if not match:
        raise GroupPolicyValidationError("GROUP_VERIFICATION_LENGTH_INVALID", "验证码长度范围格式无效")
    min_len = int(match.group(1))
    max_len = int(match.group(2))
    if min_len <= 0 or max_len <= 0 or min_len > max_len:
        raise GroupPolicyValidationError("GROUP_VERIFICATION_LENGTH_INVALID", "验证码长度范围格式无效")
    return f"{min_len}-{max_len}"


def _validate_code_regex(value: str) -> str:
    text = _normalize_str(value)
    if not text:
        return ""
    try:
        re.compile(text)
    except re.error as exc:
        raise GroupPolicyValidationError("GROUP_VERIFICATION_REGEX_INVALID", "验证码正则表达式无效") from exc
    return text


def normalize_group_verification_policy(
    *,
    verification_code_length: Any = "6-6",
    verification_code_regex: Any = "",
    verification_ai_enabled: Any = 0,
    verification_ai_model: Any = "",
) -> Dict[str, Any]:
    """标准化并校验分组验证码提取策略。"""

    normalized_length = _validate_code_length(_normalize_str(verification_code_length) or "6-6")
    normalized_regex = _validate_code_regex(_normalize_str(verification_code_regex))
    # 历史兼容字段：group 侧 AI 配置已下沉到系统级 settings。
    # 这里不再使用传入值，统一写入默认值，确保旧 payload 不报错（软兼容）。
    normalized_ai_enabled = 0
    normalized_ai_model = ""

    return {
        "verification_code_length": normalized_length,
        "verification_code_regex": normalized_regex,
        "verification_ai_enabled": normalized_ai_enabled,
        "verification_ai_model": normalized_ai_model,
    }


def load_groups() -> List[Dict]:
    """加载所有分组（临时邮箱分组排在最前面）"""
    db = get_db()
    cursor = db.execute("""
        SELECT * FROM groups
        ORDER BY
            CASE WHEN name = '临时邮箱' THEN 0 ELSE 1 END,
            id
    """)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_group_by_id(group_id: int) -> Optional[Dict]:
    """根据 ID 获取分组"""
    db = get_db()
    cursor = db.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def add_group(
    name: str,
    description: str = "",
    color: str = "#1a1a1a",
    proxy_url: str = "",
    verification_code_length: Any = "6-6",
    verification_code_regex: Any = "",
    verification_ai_enabled: Any = 0,
    verification_ai_model: Any = "",
    proxy_mode: Any = "",
) -> Optional[int]:
    """添加分组"""
    db = get_db()
    normalized_proxy_mode, normalized_proxy_url = normalize_group_proxy_config(
        proxy_url=proxy_url,
        proxy_mode=proxy_mode,
    )
    policy = normalize_group_verification_policy(
        verification_code_length=verification_code_length,
        verification_code_regex=verification_code_regex,
        verification_ai_enabled=verification_ai_enabled,
        verification_ai_model=verification_ai_model,
    )
    try:
        cursor = db.execute(
            """
            INSERT INTO groups (
                name,
                description,
                color,
                proxy_url,
                proxy_mode,
                verification_code_length,
                verification_code_regex,
                verification_ai_enabled,
                verification_ai_model
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                name,
                description,
                color,
                normalized_proxy_url,
                normalized_proxy_mode,
                policy["verification_code_length"],
                policy["verification_code_regex"],
                policy["verification_ai_enabled"],
                policy["verification_ai_model"],
            ),
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def update_group(
    group_id: int,
    name: str,
    description: str,
    color: str,
    proxy_url: str = "",
    verification_code_length: Any = "6-6",
    verification_code_regex: Any = "",
    verification_ai_enabled: Any = 0,
    verification_ai_model: Any = "",
    proxy_mode: Any = "",
) -> bool:
    """更新分组"""
    db = get_db()
    normalized_proxy_mode, normalized_proxy_url = normalize_group_proxy_config(
        proxy_url=proxy_url,
        proxy_mode=proxy_mode,
    )
    policy = normalize_group_verification_policy(
        verification_code_length=verification_code_length,
        verification_code_regex=verification_code_regex,
        verification_ai_enabled=verification_ai_enabled,
        verification_ai_model=verification_ai_model,
    )
    try:
        db.execute(
            """
            UPDATE groups
            SET
                name = ?,
                description = ?,
                color = ?,
                proxy_url = ?,
                proxy_mode = ?,
                verification_code_length = ?,
                verification_code_regex = ?,
                verification_ai_enabled = ?,
                verification_ai_model = ?
            WHERE id = ?
        """,
            (
                name,
                description,
                color,
                normalized_proxy_url,
                normalized_proxy_mode,
                policy["verification_code_length"],
                policy["verification_code_regex"],
                policy["verification_ai_enabled"],
                policy["verification_ai_model"],
                group_id,
            ),
        )
        db.commit()
        return True
    except Exception:
        return False


def get_default_group_id() -> int:
    """获取默认分组 ID（不依赖固定 id=1，增强兼容性）"""
    db = get_db()
    try:
        row = db.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
        return row["id"] if row else 1
    except Exception:
        return 1


def delete_group(group_id: int) -> bool:
    """删除分组（将该分组下的邮箱移到默认分组）"""
    db = get_db()
    try:
        row = db.execute("SELECT id, name, is_system FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return False
        if row["is_system"]:
            return False

        default_group_id = get_default_group_id()
        if group_id == default_group_id or row["name"] == "默认分组":
            return False

        db.execute(
            "UPDATE accounts SET group_id = ?, updated_at = CURRENT_TIMESTAMP WHERE group_id = ?",
            (default_group_id, group_id),
        )
        db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        db.commit()
        return True
    except Exception:
        return False


def get_group_account_count(group_id: int) -> int:
    """获取分组下的邮箱数量"""
    db = get_db()
    cursor = db.execute("SELECT COUNT(*) as count FROM accounts WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    return row["count"] if row else 0


def load_groups_with_account_count() -> List[Dict]:
    """加载所有分组并附带各分组的邮箱数量（单次 SQL 聚合，消除 N+1）"""
    db = get_db()
    cursor = db.execute("""
        SELECT g.*,
               COALESCE(a.cnt, 0) AS account_count
        FROM groups g
        LEFT JOIN (
            SELECT group_id, COUNT(*) AS cnt
            FROM accounts
            GROUP BY group_id
        ) a ON a.group_id = g.id
        ORDER BY
            CASE WHEN g.name = '临时邮箱' THEN 0 ELSE 1 END,
            g.id
    """)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_group_by_name(name: str) -> Optional[Dict]:
    """按名称查找分组（精确匹配，不区分大小写）"""
    db = get_db()
    cursor = db.execute("SELECT * FROM groups WHERE LOWER(name) = LOWER(?)", (name,))
    row = cursor.fetchone()
    return dict(row) if row else None


def resolve_group_verification_policy(
    *,
    request_code_length: Any = None,
    request_code_regex: Any = None,
    group: Optional[Dict[str, Any]] = None,
    default_code_length: str = "6-6",
    apply_default: bool = True,
    request_error_code: str = "INVALID_PARAM",
) -> Dict[str, Any]:
    """
    统一策略解析：request > group > default；group 内 regex > length。
    返回字段：code_length/code_regex/ai_enabled/ai_model。
    """

    req_length = _normalize_str(request_code_length)
    req_regex = _normalize_str(request_code_regex)

    # 1) request 参数优先
    if req_regex:
        try:
            resolved_regex = _validate_code_regex(req_regex)
        except GroupPolicyValidationError as exc:
            raise GroupPolicyValidationError(request_error_code, "参数错误") from exc
        resolved_length = None
    elif req_length:
        resolved_regex = None
        try:
            resolved_length = _validate_code_length(req_length)
        except GroupPolicyValidationError as exc:
            raise GroupPolicyValidationError(request_error_code, "参数错误") from exc
    else:
        # 2) group 配置
        grp_length = _normalize_str((group or {}).get("verification_code_length"))
        grp_regex = _normalize_str((group or {}).get("verification_code_regex"))
        if grp_regex:
            resolved_regex = _validate_code_regex(grp_regex)
            resolved_length = None
        elif grp_length:
            resolved_regex = None
            resolved_length = _validate_code_length(grp_length)
        else:
            # 3) default（仅在调用方允许时应用，避免影响链接提取）
            resolved_regex = None
            resolved_length = _validate_code_length(default_code_length) if apply_default else None

    # 兼容返回字段：运行期不再从 group 读取 AI 配置。
    ai_enabled = 0
    ai_model = ""

    return {
        "code_length": resolved_length,
        "code_regex": resolved_regex,
        "ai_enabled": ai_enabled,
        "ai_model": ai_model,
    }
