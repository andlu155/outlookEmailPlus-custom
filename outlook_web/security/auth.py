from __future__ import annotations

import secrets
import time
from functools import wraps
from typing import Optional

from flask import g, jsonify, redirect, request, session, url_for

from outlook_web.db import get_db
from outlook_web.errors import build_error_payload

# 速率限制配置
MAX_LOGIN_ATTEMPTS = 5  # 最大失败次数
LOCKOUT_DURATION = 300  # 锁定时长（秒）- 5分钟
ATTEMPT_WINDOW = 600  # 失败计数窗口（秒）- 10分钟

# 导出二次验证 Token（持久化存储，支持重启/多进程）
EXPORT_VERIFY_TOKEN_TTL_SECONDS = 300  # 5 分钟有效期


def check_rate_limit(ip: str) -> tuple[bool, Optional[int]]:
    """
    检查 IP 是否被速率限制
    返回: (是否允许登录, 剩余锁定秒数)
    """
    current_time = time.time()
    db = get_db()

    try:
        row = db.execute(
            """
            SELECT count, last_attempt_at, locked_until_at
            FROM login_attempts
            WHERE ip = ?
            """,
            (ip,),
        ).fetchone()

        if not row:
            return True, None

        locked_until_at = row["locked_until_at"]
        if locked_until_at and current_time < locked_until_at:
            remaining = int(locked_until_at - current_time)
            return False, remaining

        last_attempt_at = row["last_attempt_at"]
        if last_attempt_at and (current_time - last_attempt_at > ATTEMPT_WINDOW):
            db.execute(
                """
                UPDATE login_attempts
                SET count = 0, last_attempt_at = ?, locked_until_at = NULL
                WHERE ip = ?
                """,
                (current_time, ip),
            )
            db.commit()
            return True, None

        count = row["count"] or 0
        if count >= MAX_LOGIN_ATTEMPTS:
            locked_until_at = current_time + LOCKOUT_DURATION
            db.execute(
                """
                UPDATE login_attempts
                SET locked_until_at = ?
                WHERE ip = ?
                """,
                (locked_until_at, ip),
            )
            db.commit()
            return False, LOCKOUT_DURATION

        return True, None
    except Exception:
        # 速率限制出错时，为避免误拒绝，默认放行
        return True, None


def record_login_failure(ip: str):
    """记录登录失败"""
    current_time = time.time()
    db = get_db()

    try:
        # 清理过期记录，避免无限增长
        db.execute(
            """
            DELETE FROM login_attempts
            WHERE last_attempt_at < ?
            """,
            (current_time - (ATTEMPT_WINDOW * 2),),
        )

        row = db.execute(
            """
            SELECT count, last_attempt_at
            FROM login_attempts
            WHERE ip = ?
            """,
            (ip,),
        ).fetchone()

        if not row:
            db.execute(
                """
                INSERT INTO login_attempts (ip, count, last_attempt_at, locked_until_at)
                VALUES (?, ?, ?, NULL)
                """,
                (ip, 1, current_time),
            )
        else:
            last_attempt_at = row["last_attempt_at"] or 0
            count = row["count"] or 0
            if current_time - last_attempt_at <= ATTEMPT_WINDOW:
                new_count = count + 1
            else:
                new_count = 1

            db.execute(
                """
                UPDATE login_attempts
                SET count = ?, last_attempt_at = ?
                WHERE ip = ?
                """,
                (new_count, current_time, ip),
            )

        db.commit()
    except Exception:
        pass


def reset_login_attempts(ip: str):
    """重置登录失败记录（登录成功时调用）"""
    db = get_db()
    try:
        db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
        db.commit()
    except Exception:
        pass


def login_required(f):
    """登录验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_logged_in = bool(session.get("logged_in") or session.get("user_id"))
        if not is_logged_in:
            if request.is_json or request.path.startswith("/api/"):
                trace_id_value = None
                try:
                    trace_id_value = getattr(g, "trace_id", None)
                except Exception:
                    trace_id_value = None
                error_payload = build_error_payload(
                    code="AUTH_REQUIRED",
                    message="请先登录",
                    err_type="AuthError",
                    status=401,
                    details="need_login",
                    trace_id=trace_id_value,
                )
                return (
                    jsonify({"success": False, "error": error_payload, "need_login": True}),
                    401,
                )
            return redirect(url_for("pages.login"))
        return f(*args, **kwargs)

    return decorated_function


def api_key_required(f):
    """
    对外开放 API 的 API Key 校验装饰器。

    规则：
    1. 仅接受 Header 中的 `X-API-Key`
    2. 未配置 legacy key 且没有任何启用中的多 Key 时返回 403（API_KEY_NOT_CONFIGURED）
    3. 缺少或错误时返回 401（UNAUTHORIZED）
    4. 不依赖 session，不触发登录跳转
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        from outlook_web.repositories import external_api_keys as external_api_keys_repo
        from outlook_web.repositories import settings as settings_repo

        g.external_api_consumer = None
        provided_key = (request.headers.get("X-API-Key") or "").strip()
        if not provided_key:
            return (
                jsonify(
                    {
                        "success": False,
                        "code": "UNAUTHORIZED",
                        "message": "API Key 缺失或无效",
                        "data": None,
                    }
                ),
                401,
            )

        configured_key = settings_repo.get_external_api_key()
        any_enabled_multi_key_configured = external_api_keys_repo.has_any_external_api_key_configured(enabled_only=True)
        if configured_key and secrets.compare_digest(str(provided_key), str(configured_key)):
            g.external_api_consumer = {
                "id": "legacy-settings",
                "consumer_key": "legacy:settings.external_api_key",
                "name": "legacy-external-api-key",
                "source": "settings.external_api_key",
                "allowed_emails": [],
                "pool_access": True,
                "enabled": True,
                "is_legacy": True,
            }
            return f(*args, **kwargs)

        matched_consumer = external_api_keys_repo.find_external_api_key_by_plaintext(provided_key)
        if not matched_consumer and not configured_key and not any_enabled_multi_key_configured:
            return (
                jsonify(
                    {
                        "success": False,
                        "code": "API_KEY_NOT_CONFIGURED",
                        "message": "系统未配置对外 API Key",
                        "data": None,
                    }
                ),
                403,
            )

        if matched_consumer:
            external_api_keys_repo.mark_external_api_key_used(int(matched_consumer["id"]))
            g.external_api_consumer = {
                "id": matched_consumer["id"],
                "consumer_key": matched_consumer.get("consumer_key") or f"key:{matched_consumer['id']}",
                "name": matched_consumer.get("name") or f"key-{matched_consumer['id']}",
                "source": "external_api_keys",
                "allowed_emails": matched_consumer.get("allowed_emails") or [],
                "pool_access": bool(matched_consumer.get("pool_access", False)),
                "enabled": bool(matched_consumer.get("enabled", True)),
                "is_legacy": False,
            }
            return f(*args, **kwargs)

        return (
            jsonify(
                {
                    "success": False,
                    "code": "UNAUTHORIZED",
                    "message": "API Key 缺失或无效",
                    "data": None,
                }
            ),
            401,
        )

    return decorated_function


def get_external_api_consumer() -> dict | None:
    try:
        return getattr(g, "external_api_consumer", None)
    except Exception:
        return None


def get_client_ip() -> str:
    """
    获取客户端 IP（安全实现）

    只有当请求来自受信任的代理时，才信任 X-Forwarded-For 头。
    否则直接使用 remote_addr，防止 IP 伪造攻击。

    受信任代理通过环境变量 TRUSTED_PROXIES 配置。
    """
    from outlook_web import config

    try:
        # 获取受信任代理列表
        trusted_proxies = config.get_trusted_proxies()

        # 检查直接连接方是否为受信任代理
        remote_addr = request.remote_addr or ""
        is_trusted_proxy = _ip_in_trusted_proxies(remote_addr, trusted_proxies)

        if is_trusted_proxy and trusted_proxies:
            # 请求来自受信任代理，可以信任 X-Forwarded-For
            client_ip = request.headers.get("X-Forwarded-For") or remote_addr
            if client_ip:
                client_ip = client_ip.split(",")[0].strip()
            return client_ip or "unknown"
        else:
            # 请求不��来自受信任代理，使用 remote_addr 防止伪造
            return remote_addr or "unknown"
    except Exception:
        return "unknown"


def _ip_in_trusted_proxies(ip: str, trusted_proxies: list[str]) -> bool:
    """
    检查 IP 是否在受信任代理列表中。

    支持：
    - 单个 IP：127.0.0.1
    - CIDR 表示法：10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    """
    if not trusted_proxies or not ip:
        return False

    import ipaddress

    for proxy in trusted_proxies:
        try:
            if "/" in proxy:
                # CIDR 表示法
                network = ipaddress.ip_network(proxy, strict=False)
                if ipaddress.ip_address(ip) in network:
                    return True
            else:
                # 单个 IP
                if ip == proxy:
                    return True
        except ValueError:
            # 无效的 IP 或 CIDR，跳过
            continue
    return False


def get_user_agent() -> str:
    try:
        return (request.headers.get("User-Agent") or "")[:300]
    except Exception:
        return ""


def issue_export_verify_token(client_ip: str, user_agent: str) -> str:
    """生成并持久化一次性导出验证 token"""
    db = get_db()
    now_ts = time.time()
    verify_token = secrets.token_urlsafe(32)
    expires_at = now_ts + EXPORT_VERIFY_TOKEN_TTL_SECONDS

    db.execute(
        """
        INSERT INTO export_verify_tokens (token, ip, user_agent, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (verify_token, client_ip, user_agent, expires_at, now_ts),
    )
    db.execute("DELETE FROM export_verify_tokens WHERE expires_at < ?", (now_ts,))
    db.commit()
    return verify_token


def consume_export_verify_token(verify_token: str, client_ip: str = "", user_agent: str = "") -> tuple[bool, str]:
    """
    校验并消费一次性导出验证 token（成功则删除）

    安全增强：
    - 验证 IP 绑定：token 生成时记录的 IP 必须与消费时一致
    - 验证 User-Agent 绑定：增加 token 被盗用的难度
    """
    if not verify_token:
        return False, "需要二次验证"

    db = get_db()
    now_ts = time.time()

    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT expires_at, ip, user_agent
            FROM export_verify_tokens
            WHERE token = ?
            """,
            (verify_token,),
        ).fetchone()

        if not row:
            db.rollback()
            return False, "需要二次验证"

        expires_at = row["expires_at"] or 0
        if float(expires_at) < now_ts:
            db.execute("DELETE FROM export_verify_tokens WHERE token = ?", (verify_token,))
            db.commit()
            return False, "验证已过期，请重新验证"

        # 验证 IP 绑定（如果生成时记录了 IP）
        stored_ip = row["ip"] or ""
        if stored_ip and client_ip and stored_ip != client_ip:
            db.rollback()
            return False, "验证失败：IP 不匹配"

        # 验证 User-Agent 绑定（如果生成时记录了）
        stored_ua = row["user_agent"] or ""
        if stored_ua and user_agent and stored_ua != user_agent:
            db.rollback()
            return False, "验证失败：客户端不匹配"

        db.execute("DELETE FROM export_verify_tokens WHERE token = ?", (verify_token,))
        db.commit()
        return True, ""
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False, "验证失败，请重试"
