from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import jsonify, request, send_file

from outlook_web import __version__ as APP_VERSION
from outlook_web import config
from outlook_web.audit import log_audit
from outlook_web.db import (
    DB_SCHEMA_LAST_UPGRADE_ERROR_KEY,
    DB_SCHEMA_LAST_UPGRADE_TRACE_ID_KEY,
    DB_SCHEMA_VERSION,
    DB_SCHEMA_VERSION_KEY,
    create_sqlite_connection,
)
from outlook_web.errors import build_error_response
from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import settings as settings_repo
from outlook_web.security.auth import api_key_required, login_required
from outlook_web.security.external_api_guard import external_api_guards
from outlook_web.services import external_api as external_api_service
from outlook_web.services.scheduler import REFRESH_LOCK_NAME

logger = logging.getLogger(__name__)

# ==================== 版本检测缓存（模块级，重启后清空） ====================
_version_cache: dict | None = None
_version_cache_at: float = 0.0
_VERSION_CACHE_TTL = 600  # 10 分钟

# 每次进程启动生成一次，用于前端判断是否发生重启
_HEALTHZ_BOOT_ID = f"{int(time.time() * 1000)}-{os.getpid()}"


def utcnow() -> datetime:
    """返回 naive UTC 时间（等价于旧的 datetime.utcnow()）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@login_required
def api_bootstrap() -> Any:
    """首屏引导接口：仅返回首页初始化必需的最少字段，避免走完整 /api/settings 的重查询链路。

    当前 /api/settings 会执行：解密 Telegram token、解密 Watchtower token、
    查询所有 external_api_keys + usage_summary、解密 verification_ai_api_key 等，
    对于首页只需要布局状态和轮询配置的场景来说过于重。

    本接口只查 6 个 key，不做解密，不做聚合统计。
    """
    ui_layout_raw = settings_repo.get_setting("ui_layout_v2", "")
    ui_layout = None
    if ui_layout_raw:
        try:
            import json as _json

            parsed = _json.loads(ui_layout_raw)
            if isinstance(parsed, dict) and parsed.get("version") == 2:
                ui_layout = parsed
        except Exception:
            pass
    if not ui_layout:
        ui_layout = {
            "version": 2,
            "sidebar": {"collapsed": False},
            "mailbox": {"groupPanelWidth": 220, "accountPanelWidth": 280},
            "tempEmails": {"listPanelWidth": 300},
        }

    return jsonify(
        {
            "success": True,
            "bootstrap": {
                "ui_layout_v2": ui_layout,
                "enable_auto_polling": settings_repo.get_setting("enable_auto_polling", "false") == "true",
                "polling_interval": int(settings_repo.get_setting("polling_interval", "10")),
                "polling_count": int(settings_repo.get_setting("polling_count", "5")),
                "enable_compact_auto_poll": settings_repo.get_setting("enable_compact_auto_poll", "false") == "true",
                "compact_poll_interval": int(settings_repo.get_setting("compact_poll_interval", "10")),
                "compact_poll_max_count": int(settings_repo.get_setting("compact_poll_max_count", "5")),
            },
        }
    )


@login_required
def api_reload_plugins() -> Any:
    from outlook_web.services.temp_mail_provider_factory import reload_plugins

    return jsonify(
        {
            "success": True,
            "code": "OK",
            "message": "插件刷新完成",
            "data": reload_plugins(),
        }
    )


# ==================== 系统 API ====================


def healthz() -> Any:
    """基础健康检查（用于容器/反代探活）"""
    return (
        jsonify(
            {
                "status": "ok",
                "version": APP_VERSION,
                "boot_id": _HEALTHZ_BOOT_ID,
            }
        ),
        200,
    )


@login_required
def api_system_health() -> Any:
    """管理员健康检查：可服务/可刷新状态概览"""
    conn = create_sqlite_connection()
    try:
        # DB 可用性
        db_ok = True
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception:
            db_ok = False

        # Scheduler 心跳
        heartbeat_row = conn.execute("""
            SELECT updated_at
            FROM settings
            WHERE key = 'scheduler_heartbeat'
        """).fetchone()

        heartbeat_age_seconds = None
        if heartbeat_row and heartbeat_row["updated_at"]:
            try:
                hb_time = datetime.fromisoformat(heartbeat_row["updated_at"])
                heartbeat_age_seconds = int((utcnow() - hb_time).total_seconds())
            except Exception:
                heartbeat_age_seconds = None

        scheduler_enabled = settings_repo.get_setting("enable_scheduled_refresh", "true").lower() == "true"
        scheduler_autostart = config.get_scheduler_autostart_default()
        scheduler_healthy = (heartbeat_age_seconds is not None) and (heartbeat_age_seconds <= 120)

        # 刷新锁/运行中
        lock_row = conn.execute(
            """
            SELECT owner_id, expires_at
            FROM distributed_locks
            WHERE name = ?
        """,
            (REFRESH_LOCK_NAME,),
        ).fetchone()
        locked = bool(lock_row and lock_row["expires_at"] and lock_row["expires_at"] > time.time())

        running_run = conn.execute("""
            SELECT id, trigger_source, started_at, trace_id
            FROM refresh_runs
            WHERE status = 'running'
            ORDER BY started_at DESC
            LIMIT 1
        """).fetchone()

        return jsonify(
            {
                "success": True,
                "health": {
                    "service": "ok",
                    "database": "ok" if db_ok else "error",
                    "scheduler": {
                        "enabled": scheduler_enabled,
                        "autostart": scheduler_autostart,
                        "heartbeat_age_seconds": heartbeat_age_seconds,
                        "healthy": scheduler_healthy if scheduler_enabled else True,
                    },
                    "refresh": {
                        "locked": locked,
                        "running": dict(running_run) if running_run else None,
                    },
                    "server_time_utc": utcnow().isoformat() + "Z",
                },
            }
        )
    finally:
        conn.close()


@login_required
def api_system_diagnostics() -> Any:
    """管理员诊断信息：关键状态一致性/过期清理可见性"""
    conn = create_sqlite_connection()
    try:
        now_ts = time.time()

        export_tokens_count = conn.execute(
            """
            SELECT COUNT(*) as c
            FROM export_verify_tokens
            WHERE expires_at > ?
        """,
            (now_ts,),
        ).fetchone()["c"]

        locked_ip_count = conn.execute(
            """
            SELECT COUNT(*) as c
            FROM login_attempts
            WHERE locked_until_at IS NOT NULL AND locked_until_at > ?
        """,
            (now_ts,),
        ).fetchone()["c"]

        running_runs = conn.execute("""
            SELECT id, trigger_source, started_at, trace_id
            FROM refresh_runs
            WHERE status = 'running'
            ORDER BY started_at DESC
            LIMIT 5
        """).fetchall()

        last_runs = conn.execute("""
            SELECT id, trigger_source, status, started_at, finished_at, total, success_count, failed_count, trace_id
            FROM refresh_runs
            ORDER BY started_at DESC
            LIMIT 10
        """).fetchall()

        locks = conn.execute("""
            SELECT name, owner_id, acquired_at, expires_at
            FROM distributed_locks
            ORDER BY name ASC
        """).fetchall()

        # 数据库升级状态（可验证）
        schema_version_row = conn.execute(
            "SELECT value, updated_at FROM settings WHERE key = ?",
            (DB_SCHEMA_VERSION_KEY,),
        ).fetchone()
        schema_version = int(schema_version_row["value"]) if schema_version_row else 0

        last_migration = None
        try:
            mig = conn.execute("""
                SELECT id, from_version, to_version, status, started_at, finished_at, error, trace_id
                FROM schema_migrations
                ORDER BY started_at DESC
                LIMIT 1
            """).fetchone()
            last_migration = dict(mig) if mig else None
        except Exception:
            last_migration = None

        return jsonify(
            {
                "success": True,
                "diagnostics": {
                    "export_verify_tokens_active": export_tokens_count,
                    "login_locked_ip_count": locked_ip_count,
                    "running_runs": [dict(r) for r in running_runs],
                    "last_runs": [dict(r) for r in last_runs],
                    "locks": [dict(r) for r in locks],
                    "schema": {
                        "version": schema_version,
                        "target_version": DB_SCHEMA_VERSION,
                        "up_to_date": schema_version >= DB_SCHEMA_VERSION,
                        "last_migration": last_migration,
                    },
                },
            }
        )
    finally:
        conn.close()


@login_required
def api_system_upgrade_status() -> Any:
    """数据库升级状态（用于验收"升级过程可验证/失败可定位"）"""
    from outlook_web import config as app_config

    conn = create_sqlite_connection()
    try:
        row = conn.execute(
            "SELECT value, updated_at FROM settings WHERE key = ?",
            (DB_SCHEMA_VERSION_KEY,),
        ).fetchone()
        schema_version = int(row["value"]) if row and row["value"] is not None else 0

        last_trace_row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (DB_SCHEMA_LAST_UPGRADE_TRACE_ID_KEY,),
        ).fetchone()
        last_error_row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (DB_SCHEMA_LAST_UPGRADE_ERROR_KEY,),
        ).fetchone()

        last_migration = None
        try:
            mig = conn.execute("""
                SELECT id, from_version, to_version, status, started_at, finished_at, error, trace_id
                FROM schema_migrations
                ORDER BY started_at DESC
                LIMIT 1
            """).fetchone()
            last_migration = dict(mig) if mig else None
        except Exception:
            last_migration = None

        database_path = app_config.get_database_path()
        backup_hint = {
            "database_path": database_path,
            "linux_example": f'cp "{database_path}" "{database_path}.backup"',
            "windows_example": f'copy "{database_path}" "{database_path}.backup"',
        }

        return jsonify(
            {
                "success": True,
                "upgrade": {
                    "schema_version": schema_version,
                    "target_version": DB_SCHEMA_VERSION,
                    "up_to_date": schema_version >= DB_SCHEMA_VERSION,
                    "last_upgrade_trace_id": (last_trace_row["value"] if last_trace_row else ""),
                    "last_upgrade_error": (last_error_row["value"] if last_error_row else ""),
                    "last_migration": last_migration,
                    "backup_hint": backup_hint,
                },
            }
        )
    finally:
        conn.close()


# ==================== External System API ====================


@api_key_required
@external_api_guards()
def api_external_health() -> Any:
    """对外健康检查（不依赖登录态）"""
    conn = create_sqlite_connection()
    try:
        db_ok = True
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception:
            db_ok = False

        probe_summary: dict[str, Any] = {
            "upstream_probe_ok": None,
            "last_probe_at": "",
            "last_probe_error": "",
        }
        if db_ok:
            try:
                probe_summary = external_api_service.probe_instance_upstream(cache_ttl_seconds=60)
            except Exception:
                probe_summary = {
                    "upstream_probe_ok": False,
                    "last_probe_at": utcnow().isoformat() + "Z",
                    "last_probe_error": "实例上游探测执行失败",
                }

        data = {
            "status": "ok",
            "service": "outlook-email-plus",
            "version": APP_VERSION,
            "server_time_utc": utcnow().isoformat() + "Z",
            "database": "ok" if db_ok else "error",
            "upstream_probe_ok": probe_summary.get("upstream_probe_ok"),
            "last_probe_at": probe_summary.get("last_probe_at") or "",
            "last_probe_error": probe_summary.get("last_probe_error") or "",
        }
        external_api_service.audit_external_api_access(
            action="external_api_access",
            email_addr="",
            endpoint="/api/external/health",
            status="ok",
            details={
                "database": data["database"],
                "upstream_probe_ok": data["upstream_probe_ok"],
            },
        )
        return jsonify(external_api_service.ok(data))
    except Exception as exc:
        external_api_service.audit_external_api_access(
            action="external_api_access",
            email_addr="",
            endpoint="/api/external/health",
            status="error",
            details={"code": "INTERNAL_ERROR", "err": type(exc).__name__},
        )
        return jsonify(external_api_service.fail("INTERNAL_ERROR", "服务内部错误")), 500
    finally:
        conn.close()


# ==================== 版本更新检测 ====================


def _version_gt(a: str, b: str) -> bool:
    """判断版本 a 是否严格大于版本 b（支持语义化版本 x.y.z，忽略 pre-release 后缀如 -hotupdate-test）"""
    try:

        def _parse(v: str) -> tuple:
            # 取 '-' 之前的纯数字部分，如 "1.12.1-hotupdate-test" → "1.12.1"
            core = v.split("-", 1)[0]
            return tuple(int(x) for x in core.split("."))

        return _parse(a) > _parse(b)
    except Exception:
        return False


@login_required
def api_version_check() -> Any:
    """检查是否有新版本可用（内存缓存，10 分钟 TTL；可通过 enable_version_check 关闭自动检查）"""
    import json as _json
    import urllib.request

    global _version_cache, _version_cache_at

    # 支持通过 settings 完全关闭版本检查
    if settings_repo.get_setting("enable_version_check", "true").lower() != "true":
        return jsonify(
            {
                "success": True,
                "has_update": False,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "release_url": "",
                "disabled": True,
            }
        )

    now = time.time()
    if _version_cache is not None and (now - _version_cache_at) < _VERSION_CACHE_TTL:
        return jsonify(_version_cache)

    current = APP_VERSION

    try:
        GITHUB_API = "https://api.github.com/repos/ZeroPointSix/outlookEmailPlus/releases/latest"
        req = urllib.request.Request(
            GITHUB_API,
            headers={"User-Agent": "outlook-email-plus"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
        latest = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", "")
        has_update = _version_gt(latest, current)
        result = {
            "success": True,
            "has_update": has_update,
            "current_version": current,
            "latest_version": latest,
            "release_url": release_url,
        }
    except Exception:
        # GitHub API 调用失败：静默降级，返回无更新
        result = {
            "success": True,
            "has_update": False,
            "current_version": current,
            "latest_version": current,
            "release_url": "",
        }

    _version_cache = result
    _version_cache_at = now
    return jsonify(result)


@login_required
def api_trigger_update() -> Any:
    """触发容器更新

    支持两种更新方式（通过 request 参数 method 指定）：
    1. watchtower (默认): 调用 Watchtower HTTP API
    2. docker_api: 使用 Docker API 自更新

    优先从数据库读取配置,如未配置则回退到环境变量。

    请求参数：
        method: str (可选) - 更新方式 (watchtower / docker_api)
        remove_old: bool (可选) - Docker API 模式下是否删除旧容器 (默认 False)
    """
    # 获取更新方式参数
    update_method = request.args.get("method", "watchtower").lower()

    if update_method == "watchtower":
        return _trigger_watchtower_update()
    elif update_method == "docker_api":
        return _trigger_docker_api_update()
    else:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"不支持的更新方式: {update_method} (支持: watchtower / docker_api)",
                }
            ),
            400,
        )


def _trigger_watchtower_update() -> Any:  # noqa: C901
    """通过 Watchtower HTTP API 触发更新"""
    import os
    import urllib.error
    import urllib.request

    from outlook_web.security.crypto import decrypt_data, is_encrypted

    # 优先从数据库读取,回退到环境变量
    wt_url_raw = settings_repo.get_setting("watchtower_url", "")
    wt_token_raw = settings_repo.get_setting("watchtower_token", "")

    watchtower_url = wt_url_raw.strip() if wt_url_raw else os.getenv("WATCHTOWER_API_URL", "http://watchtower:8080")
    watchtower_token = ""
    if wt_token_raw:
        watchtower_token = decrypt_data(wt_token_raw) if is_encrypted(wt_token_raw) else wt_token_raw
    if not watchtower_token:
        watchtower_token = os.getenv("WATCHTOWER_HTTP_API_TOKEN", "")

    if not watchtower_token:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Watchtower Token 未配置,请在系统设置 → 一键更新中配置",
                }
            ),
            500,
        )

    try:
        req = urllib.request.Request(
            f"{watchtower_url}/v1/update",
            method="POST",
            headers={
                "Authorization": f"Bearer {watchtower_token}",
                "Content-Length": "0",
            },
            data=b"",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8", errors="replace").strip()

        if status == 200:
            import logging

            logger = logging.getLogger(__name__)
            logger.info("Watchtower 响应: status=%s body=%r", status, resp_body[:500])
            # Watchtower POST /v1/update 是同步的：完成整个检查+更新周期后才返回。
            # 如果我们的容器需要更新，Watchtower 会先停止旧容器再启动新容器，
            # 此时我们的进程已被 kill，HTTP 请求会失败而不会收到 200。
            # 因此：能收到 200 响应 → 本容器未被更新 → 镜像已是最新。
            return jsonify(
                {
                    "success": True,
                    "already_latest": True,
                    "message": "Watchtower 检查完毕，当前已是最新版本",
                    "message_en": "Watchtower check complete, already up to date",
                    "watchtower_response": resp_body[:500] if resp_body else None,
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"Watchtower 返回状态码 {status}",
                        "detail": resp_body[:500] if resp_body else None,
                    }
                ),
                502,
            )
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace").strip()[:500]
        except Exception:
            pass
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Watchtower 返回错误 (HTTP {e.code})",
                    "detail": body or str(e.reason),
                }
            ),
            502,
        )
    except urllib.error.URLError as e:
        reason_str = str(e.reason) if e.reason else "未知原因"
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"无法连接 Watchtower ({watchtower_url})",
                    "detail": reason_str,
                }
            ),
            503,
        )
    except TimeoutError:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"连接 Watchtower 超时 ({watchtower_url})",
                    "detail": "请求在 30 秒内未收到响应，可能是网络问题或 Watchtower 拉取镜像耗时过长",
                }
            ),
            504,
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"触发更新失败: {type(e).__name__}: {str(e)}"}), 500


def _trigger_docker_api_update() -> Any:  # noqa: C901
    """通过 Docker API 触发容器自更新

    A2（按需 helper job 容器）模式：
    - 主应用容器只负责创建一个短生命周期 updater 容器
    - updater 容器执行真正的更新流程（并在适当时机 stop/rename 旧容器）
    - 主接口尽量快速返回，减少“响应中途被 stop”导致的失败概率
    """
    import json
    import os

    from flask import request, session

    from outlook_web.audit import log_audit
    from outlook_web.services import docker_update

    # 检查是否启用 Docker API 自更新
    if not docker_update.is_docker_api_enabled():
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Docker API 自更新功能未启用 (需设置环境变量 DOCKER_SELF_UPDATE_ALLOW=true)",
                }
            ),
            403,
        )

    # 检查 docker.sock 可访问性
    socket_ok, socket_msg = docker_update.check_docker_socket()
    if not socket_ok:
        return (
            jsonify(
                {
                    "success": False,
                    "message": socket_msg,
                }
            ),
            503,
        )

    # 获取参数
    remove_old = request.args.get("remove_old", "false").lower() == "true"
    username = session.get("username", "unknown")

    # 先在主线程记录一次审计日志（后台线程没有 request context）
    try:
        log_audit(
            "trigger_docker_api_update_start",
            "system",
            "docker_update",
            json.dumps(
                {
                    "method": "docker_api",
                    "remove_old": remove_old,
                    "username": username,
                },
                ensure_ascii=False,
            ),
        )
    except Exception:
        # 审计日志失败不影响主流程
        pass

    # A2: 使用按需 updater 容器执行更新，避免“容器 stop 自己”导致流程中断。
    # 这里尽量快速返回，updater 会延迟几秒再开始 stop。
    try:
        # 当前容器 ID 通常等于 HOSTNAME（短 ID），但 docker SDK 接受短/长 ID
        target_id = os.getenv("HOSTNAME", "").strip()
        if not target_id:
            return jsonify({"success": False, "message": "无法获取当前容器 ID"}), 500

        # 安全：API 层也做镜像白名单/本地构建拦截（策略A），避免等到 spawn 内部才失败。
        try:
            cinfo = docker_update.get_container_info(target_id)
            if not cinfo:
                return (
                    jsonify({"success": False, "message": "无法获取目标容器信息"}),
                    500,
                )

            image_ref = str(cinfo.get("image") or "").strip()
            image_id = str(cinfo.get("image_id") or "").strip()
            ok_img, img_msg = docker_update.validate_image_for_update(
                image_ref,
                image_id=image_id,
            )
            if not ok_img:
                return jsonify({"success": False, "message": img_msg}), 403
        except Exception:
            # 校验异常：不放行（宁可阻止也不冒险更新到未知镜像）
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "镜像安全校验失败，已阻止更新请求（请检查部署镜像与 docker 权限）",
                    }
                ),
                500,
            )

        # Digest 预检查：先 pull 镜像并比较 digest，避免 updater 空跑导致前端等待超时
        try:
            pull_ok, pull_msg, new_digest = docker_update.pull_latest_image(image_ref)
            if pull_ok and new_digest:
                if docker_update.compare_image_digest(image_id, new_digest):
                    return jsonify(
                        {
                            "success": True,
                            "message": "当前已是最新版本，无需更新",
                            "already_latest": True,
                        }
                    )
        except Exception:
            # pull 失败不阻断：交给 updater 容器内部重试
            pass

        ok, msg = docker_update.spawn_update_helper_container(
            target_id,
            remove_old=remove_old,
            start_delay_seconds=2,
            auto_remove=True,
        )
        if not ok:
            return jsonify({"success": False, "message": msg}), 500
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        logger.error(f"启动 updater 容器失败: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": f"启动 updater 失败: {str(e)}"}), 500


@login_required
def api_deployment_info() -> Any:  # noqa: C901
    """获取当前容器的部署信息（用于一键更新功能提示）

    检测内容：
    - 镜像名称和标签
    - 是否为本地构建（检查镜像名中是否包含 'local' / 'dev' / 没有 registry 前缀）
    - 是否使用固定版本标签（非 latest）
    - Watchtower 连通性

    返回示例：
    {
        "success": true,
        "deployment": {
            "image": "guangshanshui/outlook-email-plus:latest",
            "is_local_build": false,
            "uses_fixed_tag": false,
            "update_method": "watchtower",
            "watchtower_reachable": true,
            "can_auto_update": true,
            "warnings": []
        }
    }
    """
    import os

    # 当前选择的更新方式（用于生成更符合语境的提示）
    update_method = settings_repo.get_setting("update_method", "watchtower")
    if update_method not in ("watchtower", "docker_api"):
        update_method = "watchtower"

    deployment_info = {
        "image": "unknown",
        "is_local_build": False,
        "uses_fixed_tag": False,
        "update_method": update_method,
        "watchtower_reachable": None,
        "docker_api_available": False,
        "can_auto_update": False,
        "warnings": [],
    }

    # 1. 检测镜像信息
    # 优先策略（展示用途）：
    # - 只要 docker.sock 可用，就优先通过 Docker API 获取真实镜像名（不依赖 DOCKER_SELF_UPDATE_ALLOW）
    # - 否则回退到环境变量 DOCKER_IMAGE（可选）
    # - 再回退到 cgroup 近似判断
    image_name = os.getenv("DOCKER_IMAGE", "").strip()
    docker_image_id = ""
    docker_image_repo_digests: list[str] = []

    # 尝试通过 Docker API 获取镜像名（更准确；仅用于展示/提示）
    try:
        from outlook_web.services import docker_update

        socket_ok, _ = docker_update.check_docker_socket()
        if socket_ok:
            cinfo = docker_update.get_current_container_info()
            if cinfo:
                if cinfo.get("image"):
                    image_name = str(cinfo.get("image") or "").strip() or image_name
                docker_image_id = str(cinfo.get("image_id") or "").strip()
                repo_digests_raw = cinfo.get("image_repo_digests") or []
                if isinstance(repo_digests_raw, list):
                    docker_image_repo_digests = [str(x) for x in repo_digests_raw if str(x).strip()]
    except Exception:
        pass

    # 如果没有 DOCKER_IMAGE 环境变量，尝试读取 /proc/self/cgroup（仅 Linux）
    if not image_name:
        try:
            with open("/proc/self/cgroup", "r") as f:
                cgroup_content = f.read()
                # 简单判断：如果包含 docker 关键字，说明在容器内运行
                if "docker" in cgroup_content.lower() or "containerd" in cgroup_content.lower():
                    # 无法直接从 cgroup 读取镜像名，使用默认值
                    image_name = "outlook-email-plus:unknown"
        except Exception:
            pass

    # 2. 判断是否为本地构建
    # 注意：此前用 substring 检测 "test" 会误判 "latest"（包含 "test" 子串）。
    # 这里改为：优先用 Docker API 的 RepoDigests 判断（更可靠），并对 tag 做精确判断。
    def _parse_tag(ref: str) -> str:
        ref = (ref or "").strip()
        if not ref:
            return ""
        # digest 形式：repo@sha256:...
        if "@" in ref:
            ref = ref.split("@", 1)[0]
        # tag 形式：repo:tag（仅当最后一个 ':' 之后不包含 '/' 才视为 tag）
        if ":" in ref:
            left, right = ref.rsplit(":", 1)
            if "/" not in right:
                return right
        return ""

    is_local = False
    if image_name:
        deployment_info["image"] = image_name

        # 2.1 若能拿到 RepoDigests：为空通常表示本地 build（或未从 registry pull）
        if docker_image_id and isinstance(docker_image_repo_digests, list):
            if len(docker_image_repo_digests) == 0:
                is_local = True

        # 2.2 兜底：基于镜像名结构判断
        # 无 namespace（如 outlook-email-plus:latest）通常是本地构建或非官方镜像
        if not is_local:
            lower_image = image_name.lower()
            if "/" not in image_name or lower_image.startswith("outlook-email"):
                is_local = True
            else:
                tag = _parse_tag(image_name).lower()
                # 仅对 tag 做精确判断，避免 latest 被误判
                if tag in ("dev", "local", "test") or tag.startswith("dev-") or tag.startswith("local-"):
                    is_local = True

    deployment_info["is_local_build"] = is_local

    # 3. 判断是否使用固定标签
    # 策略：仅当 tag 符合语义化版本（如 v1.2.3、1.2.3）时才视为固定版本。
    # 分支名（如 hotupdate-test）、latest、main 等均视为滚动标签。
    import re

    uses_fixed_tag = False
    tag = _parse_tag(image_name)
    if tag:
        _semver_pattern = re.compile(r"^v?\d+\.\d+(\.\d+)?([._-].*)?$")
        if _semver_pattern.match(tag):
            uses_fixed_tag = True

    deployment_info["uses_fixed_tag"] = uses_fixed_tag

    # 4. 检测 Watchtower 连通性（使用已有配置）
    from outlook_web.security.crypto import decrypt_data, is_encrypted

    wt_url_raw = settings_repo.get_setting("watchtower_url", "")
    wt_token_raw = settings_repo.get_setting("watchtower_token", "")

    watchtower_url = wt_url_raw.strip() if wt_url_raw else os.getenv("WATCHTOWER_API_URL", "http://watchtower:8080")
    watchtower_token = ""
    if wt_token_raw:
        watchtower_token = decrypt_data(wt_token_raw) if is_encrypted(wt_token_raw) else wt_token_raw
    if not watchtower_token:
        watchtower_token = os.getenv("WATCHTOWER_HTTP_API_TOKEN", "")

    watchtower_reachable = False
    # 探测策略：发不带 token 的请求，401 = 服务可达（watchtower 在运行，只是未认证）。
    # 带 token 的请求会触发实际更新（拉镜像），耗时较长，不适合用作探测。
    if watchtower_url:
        try:
            import urllib.error
            import urllib.request

            probe_req = urllib.request.Request(
                f"{watchtower_url}/v1/update",
                method="GET",
            )
            with urllib.request.urlopen(probe_req, timeout=3) as resp:
                watchtower_reachable = resp.status == 200
        except urllib.error.HTTPError as e:
            # 401 Unauthorized = 服务可达，只是未提供 token
            watchtower_reachable = e.code == 401
        except Exception:
            watchtower_reachable = False

    deployment_info["watchtower_reachable"] = watchtower_reachable

    # 5. 检测 Docker API 可用性
    docker_api_available = False
    try:
        from outlook_web.services import docker_update

        if docker_update.is_docker_api_enabled():
            socket_ok, _ = docker_update.check_docker_socket()
            docker_api_available = socket_ok
    except Exception:
        docker_api_available = False

    deployment_info["docker_api_available"] = docker_api_available

    # 6. 生成警告信息
    warnings = []

    if is_local:
        warnings.append(
            {
                "type": "local_build",
                "severity": "warning",
                "message": "当前为本地构建模式，一键更新将无法工作",
                "message_en": "Local build detected. Auto-update is not available",
                "suggestion": "请使用远程镜像部署（如 guangshanshui/outlook-email-plus:latest）以支持一键更新",
                "suggestion_en": (
                    "Please use remote image (e.g., guangshanshui/outlook-email-plus:latest) for auto-update support"
                ),
            }
        )

    if uses_fixed_tag and not is_local:
        warnings.append(
            {
                "type": "fixed_tag",
                "severity": "info",
                "message": "当前使用固定版本标签，一键更新需手动修改 docker-compose.yml 中的版本号",
                "message_en": "Fixed version tag detected. Auto-update requires manual tag change in docker-compose.yml",
                "suggestion": "建议使用 latest 标签以支持自动更新",
                "suggestion_en": "Consider using 'latest' tag for auto-update support",
            }
        )

    # 智能推荐更新方式：根据实际可用性决定
    # 优先级：用户已保存的偏好 > 自动检测
    if update_method == "watchtower" and not watchtower_reachable and docker_api_available:
        recommended_method = "docker_api"
    elif update_method == "docker_api" and not docker_api_available and watchtower_reachable:
        recommended_method = "watchtower"
    else:
        recommended_method = update_method
    deployment_info["recommended_method"] = recommended_method

    # Watchtower 连通性提示：根据推荐方式决定严重级别
    if not watchtower_reachable and not is_local:
        if recommended_method == "watchtower":
            warnings.append(
                {
                    "type": "watchtower_unreachable",
                    "severity": "error",
                    "message": "无法连接 Watchtower 服务",
                    "message_en": "Cannot connect to Watchtower service",
                    "suggestion": "请确保 Watchtower 容器正常运行，并在系统设置中配置正确的 API 地址和 Token",
                    "suggestion_en": (
                        "Please ensure Watchtower container is running and API credentials are configured correctly"
                    ),
                }
            )
        # Docker API 可用时不再显示 Watchtower 不可达提示（避免噪音）

    # Docker API 可用性提示
    if recommended_method == "docker_api" and not is_local:
        if not docker_api_available:
            warnings.append(
                {
                    "type": "docker_api_unavailable",
                    "severity": "error",
                    "message": "Docker API 更新方式不可用（未挂载 docker.sock 或权限不足）",
                    "message_en": "Docker API update is unavailable (docker.sock not mounted or insufficient permissions)",
                    "suggestion": "请在部署时挂载 /var/run/docker.sock 并设置 DOCKER_SELF_UPDATE_ALLOW=true",
                    "suggestion_en": "Mount /var/run/docker.sock and set DOCKER_SELF_UPDATE_ALLOW=true",
                }
            )

    deployment_info["warnings"] = warnings

    # 7. 判断是否可以使用一键更新
    can_auto_update = not is_local and (watchtower_reachable or docker_api_available)

    deployment_info["can_auto_update"] = can_auto_update

    return jsonify({"success": True, "deployment": deployment_info})


@login_required
def api_test_watchtower() -> Any:  # noqa: C901
    """测试 Watchtower 连通性：用配置的 URL + Token 请求 /v1/update (HEAD)"""
    import os
    import urllib.error
    import urllib.request

    from outlook_web.security.crypto import decrypt_data, is_encrypted

    data = request.get_json(silent=True) or {}
    wt_url = str(data.get("url", "")).strip()
    wt_token = str(data.get("token", "")).strip()

    # 如果前端没传值，从数据库 / 环境变量读取
    if not wt_url:
        wt_url_raw = settings_repo.get_setting("watchtower_url", "")
        wt_url = wt_url_raw.strip() if wt_url_raw else os.getenv("WATCHTOWER_API_URL", "http://watchtower:8080")
    if not wt_token:
        wt_token_raw = settings_repo.get_setting("watchtower_token", "")
        if wt_token_raw:
            wt_token = decrypt_data(wt_token_raw) if is_encrypted(wt_token_raw) else wt_token_raw
        if not wt_token:
            wt_token = os.getenv("WATCHTOWER_HTTP_API_TOKEN", "")

    if not wt_url:
        return jsonify({"success": False, "message": "Watchtower URL 未配置"})

    # 先测试连通性（GET /v1/update 返回 200 表示 API 可达）
    # 注意: Watchtower 的 GET /v1/update 也会触发完整的镜像检查流程,
    # 包括从 GHCR 拉取 manifest, 可能需要 20-30 秒才能返回
    try:
        test_req = urllib.request.Request(
            f"{wt_url}/v1/update",
            method="GET",
            headers={
                "Authorization": f"Bearer {wt_token}",
            },
        )
        with urllib.request.urlopen(test_req, timeout=35):
            return jsonify(
                {
                    "success": True,
                    "message": f"Watchtower 连通正常 ({wt_url})",
                    "message_en": f"Watchtower is reachable at {wt_url}",
                }
            )
    except urllib.error.HTTPError as e:
        # 401 说明 API 可达但 Token 错误
        if e.code == 401:
            return jsonify(
                {
                    "success": False,
                    "message": "Watchtower 可达但认证失败，请检查 Token",
                    "message_en": "Watchtower is reachable but authentication failed. Check your token.",
                }
            )
        return jsonify(
            {
                "success": False,
                "message": f"Watchtower 返回状态码 {e.code}",
            }
        )
    except urllib.error.URLError as e:
        return jsonify(
            {
                "success": False,
                "message": f"无法连接 Watchtower ({wt_url}): {e.reason}",
                "message_en": f"Cannot connect to Watchtower ({wt_url}): {e.reason}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"测试失败: {str(e)}"})


@login_required
def api_download_database_backup() -> Any:
    """Download a consistent SQLite snapshot (online backup API).

    Recovery is intentionally out of band: stop the container, replace the DB
    file with the downloaded snapshot, then restart. In-app restore is not
    offered because it would race live writers and risk corrupting production.
    """
    database_path = Path(config.get_database_path()).expanduser()
    if not database_path.is_absolute():
        database_path = (Path.cwd() / database_path).resolve()
    else:
        database_path = database_path.resolve()

    if not database_path.exists() or not database_path.is_file():
        return build_error_response(
            "DATABASE_NOT_FOUND",
            "数据库文件不存在，无法备份",
            message_en="Database file not found",
            status=404,
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    download_name = f"outlook_accounts_backup_{stamp}.db"
    tmp_path: str | None = None
    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None

    try:
        fd, tmp_path = tempfile.mkstemp(prefix="outlook-db-backup-", suffix=".db")
        os.close(fd)

        src = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(tmp_path, timeout=30)
        # Online backup copies a consistent snapshot even while WAL writers are active.
        with dst:
            src.backup(dst)
        dst.close()
        dst = None
        src.close()
        src = None

        size_bytes = os.path.getsize(tmp_path)
        log_audit(
            "backup",
            "database",
            str(database_path),
            f"下载数据库备份 size={size_bytes} name={download_name}",
        )

        response = send_file(
            tmp_path,
            mimetype="application/x-sqlite3",
            as_attachment=True,
            download_name=download_name,
            max_age=0,
        )
        # Best-effort cleanup after the response finishes streaming.
        temporary_path = tmp_path

        @response.call_on_close
        def _cleanup_temp_backup() -> None:
            try:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except Exception:
                pass

        tmp_path = None  # ownership transferred to response cleanup
        return response
    except Exception as exc:
        logger.exception("Database backup failed")
        return build_error_response(
            "DATABASE_BACKUP_FAILED",
            "数据库备份失败，请稍后重试",
            message_en="Database backup failed",
            status=500,
            details=str(exc),
        )
    finally:
        try:
            if dst is not None:
                dst.close()
        except Exception:
            pass
        try:
            if src is not None:
                src.close()
        except Exception:
            pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@api_key_required
@external_api_guards()
def api_external_capabilities() -> Any:
    """对外能力说明接口"""
    public_mode = settings_repo.get_external_api_public_mode()
    restricted = []
    all_features = [
        "message_list",
        "message_detail",
        "raw_content",
        "verification_code",
        "verification_link",
        "wait_message",
    ]
    if public_mode:
        if settings_repo.get_external_api_disable_raw_content():
            restricted.append("raw_content")
        if settings_repo.get_external_api_disable_wait_message():
            restricted.append("wait_message")
    available = [f for f in all_features if f not in restricted]
    data = {
        "service": "outlook-email-plus",
        "version": APP_VERSION,
        "public_mode": public_mode,
        "features": available,
        "restricted_features": restricted,
    }
    external_api_service.audit_external_api_access(
        action="external_api_access",
        email_addr="",
        endpoint="/api/external/capabilities",
        status="ok",
        details={"feature_count": len(data["features"])},
    )
    return jsonify(external_api_service.ok(data))


@api_key_required
@external_api_guards()
def api_external_account_status() -> Any:
    """对外账号状态检查"""
    email_addr = (request.args.get("email") or "").strip()
    if not email_addr or "@" not in email_addr:
        external_api_service.audit_external_api_access(
            action="external_api_access",
            email_addr=email_addr,
            endpoint="/api/external/account-status",
            status="error",
            details={"code": "INVALID_PARAM"},
        )
        return jsonify(external_api_service.fail("INVALID_PARAM", "email 参数不合法")), 400
    try:
        external_api_service.ensure_external_email_scope(email_addr)
    except external_api_service.ExternalApiError as exc:
        external_api_service.audit_external_api_access(
            action="external_api_access",
            email_addr=email_addr,
            endpoint="/api/external/account-status",
            status="error",
            details={"code": exc.code},
        )
        return jsonify(external_api_service.fail(exc.code, exc.message, data=exc.data)), exc.status

    account = accounts_repo.get_account_by_email(email_addr)
    if not account:
        external_api_service.audit_external_api_access(
            action="external_api_access",
            email_addr=email_addr,
            endpoint="/api/external/account-status",
            status="error",
            details={"code": "ACCOUNT_NOT_FOUND"},
        )
        return jsonify(external_api_service.fail("ACCOUNT_NOT_FOUND", "账号不存在", data={"email": email_addr})), 404

    account_type = (account.get("account_type") or "outlook").strip().lower()
    provider = (account.get("provider") or account_type or "outlook").strip().lower()
    preferred_method = "imap_generic" if account_type == "imap" else "graph"
    can_read = external_api_service.can_account_read(account)

    data = {
        "email": email_addr,
        "exists": True,
        "account_type": account_type,
        "provider": provider,
        "email_domain": account.get("email_domain") or "",
        "group_id": account.get("group_id"),
        "status": account.get("status"),
        "last_refresh_at": account.get("last_refresh_at"),
        "preferred_method": preferred_method,
        "can_read": can_read,
        "upstream_probe_ok": None,
        "probe_method": "",
        "last_probe_at": "",
        "last_probe_error": "",
    }
    if can_read:
        probe_summary = external_api_service.probe_account_upstream(account)
        data["upstream_probe_ok"] = probe_summary.get("upstream_probe_ok")
        data["probe_method"] = probe_summary.get("probe_method") or preferred_method
        data["last_probe_at"] = probe_summary.get("last_probe_at") or ""
        data["last_probe_error"] = probe_summary.get("last_probe_error") or ""
    external_api_service.audit_external_api_access(
        action="external_api_access",
        email_addr=email_addr,
        endpoint="/api/external/account-status",
        status="ok",
        details={
            "preferred_method": preferred_method,
            "can_read": can_read,
            "upstream_probe_ok": data["upstream_probe_ok"],
        },
    )
    return jsonify(external_api_service.ok(data))
