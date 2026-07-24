"""
定时任务调度器服务

功能：
- 初始化调度器
- 配置定时任务
- 心跳任务
- 定时刷新任务
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from outlook_web import config
from outlook_web.db import create_sqlite_connection
from outlook_web.errors import generate_trace_id
from outlook_web.repositories import settings as settings_repo
from outlook_web.repositories.distributed_locks import (
    acquire_distributed_lock,
    release_distributed_lock,
)
from outlook_web.repositories.refresh_runs import create_refresh_run, finish_refresh_run
from outlook_web.security.crypto import decrypt_data, encrypt_data

# 调度器实例
_scheduler_instance = None

# 刷新锁名称
REFRESH_LOCK_NAME = "refresh_all_tokens"


def utcnow() -> datetime:
    """返回 naive UTC 时间（等价于旧的 datetime.utcnow()）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scheduler_heartbeat_task():
    """调度器心跳，用于验证后台任务是否真实运行"""
    try:
        payload = {"at": utcnow().isoformat() + "Z", "pid": os.getpid()}
        conn = create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES ('scheduler_heartbeat', ?, CURRENT_TIMESTAMP)
            """,
                (json.dumps(payload, ensure_ascii=False),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _get_telegram_interval(app) -> int:
    """读取 telegram_poll_interval 设置，默认 600 秒，最小 10 秒。"""
    try:
        with app.app_context():
            val = settings_repo.get_setting("telegram_poll_interval", "600")
        return max(10, int(val or "600"))
    except Exception:
        return 600


def _get_email_notification_interval(app) -> int:
    """读取邮件通知轮询间隔，默认 60 秒，最小 15 秒。"""
    try:
        with app.app_context():
            value = settings_repo.get_setting("telegram_poll_interval", "600")
        fallback = max(15, min(int(value or "600"), 600))
    except Exception:
        fallback = 60
    try:
        override = int(str(os.getenv("EMAIL_NOTIFICATION_POLL_INTERVAL", "")).strip() or "0")
        if override > 0:
            return max(15, override)
    except Exception:
        pass
    return min(fallback, 60) if fallback else 60


def _get_notification_dispatch_interval(app) -> int:
    """统一通知调度间隔。

    邮件通知启用时优先采用更快的邮件轮询；否则退回 Telegram 轮询间隔。
    """
    try:
        with app.app_context():
            email_enabled = settings_repo.get_setting("email_notification_enabled", "false").lower() == "true"
            recipient = settings_repo.get_setting("email_notification_recipient", "").strip()
    except Exception:
        email_enabled = False
        recipient = ""

    if email_enabled and recipient:
        return min(_get_email_notification_interval(app), _get_telegram_interval(app))
    return _get_telegram_interval(app)


def _configure_telegram_push_job(scheduler, app) -> None:
    """注册/更新旧版 Telegram 推送 Job。"""
    from outlook_web.services.telegram_push import run_telegram_push_job

    try:
        scheduler.remove_job("telegram_push_job")
    except Exception:
        pass

    interval = _get_telegram_interval(app)
    scheduler.add_job(
        func=run_telegram_push_job,
        args=[app],
        trigger="interval",
        seconds=interval,
        id="telegram_push_job",
        name="Telegram 推送",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=interval,
    )
    print(f"✓ Telegram 推送 Job 已配置（轮询间隔：{interval} 秒）")


def _configure_email_notification_job(scheduler, app) -> None:
    """注册/更新统一通知分发 Job。"""
    from outlook_web.services.notification_dispatch import run_notification_dispatch_job

    try:
        scheduler.remove_job("email_notification_job")
    except Exception:
        pass

    interval = _get_notification_dispatch_interval(app)
    scheduler.add_job(
        func=run_notification_dispatch_job,
        args=[app],
        trigger="interval",
        seconds=interval,
        id="email_notification_job",
        name="统一通知分发",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=interval,
    )
    print(f"✓ 统一通知分发 Job 已配置（轮询间隔：{interval} 秒）")


def _configure_probe_poll_job(scheduler, app) -> None:
    """P2: 注册异步探测轮询 Job。每 5 秒执行一次，处理 pending 探测并清理过期记录。"""
    from outlook_web.services.external_api import (
        cleanup_expired_probes,
        poll_pending_probes,
    )

    try:
        scheduler.remove_job("external_probe_poll")
    except Exception:
        pass

    def _probe_poll_task():
        try:
            poll_pending_probes(app)
            cleanup_expired_probes(app, max_age_minutes=30)
        except Exception:
            pass

    scheduler.add_job(
        func=_probe_poll_task,
        trigger="interval",
        seconds=5,
        id="external_probe_poll",
        name="对外 API 异步探测",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=10,
    )
    print("✓ 对外 API 异步探测 Job 已配置（轮询间隔：5 秒）")


def _configure_pool_maintenance_jobs(scheduler) -> None:
    try:
        scheduler.remove_job("pool_expire_stale_claims")
    except Exception:
        pass
    try:
        scheduler.remove_job("pool_recover_cooldown")
    except Exception:
        pass

    def _expire_task():
        try:
            from outlook_web.db import create_sqlite_connection
            from outlook_web.repositories import pool as pool_repo

            conn = create_sqlite_connection()
            try:
                expired = pool_repo.expire_stale_claims(conn)
                if expired:
                    print(f"[pool] 过期 claims 回收：{expired} 条")
                expired_temp = pool_repo.expire_stale_temp_claims(conn)
                if expired_temp:
                    print(f"[pool] 过期临时邮箱 claims 回收：{expired_temp} 条")
            finally:
                conn.close()
        except Exception:
            pass

    def _recover_task():
        try:
            from outlook_web.db import create_sqlite_connection
            from outlook_web.repositories import pool as pool_repo

            conn = create_sqlite_connection()
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = 'pool_cooldown_seconds'").fetchone()
                cooldown_seconds = int(row["value"]) if row and row["value"] else 86400
                recovered = pool_repo.recover_cooldown(conn, cooldown_seconds)
                if recovered:
                    print(f"[pool] cooldown 恢复：{recovered} 条")
                recovered_temp = pool_repo.recover_cooldown_temp(conn, cooldown_seconds)
                if recovered_temp:
                    print(f"[pool] 临时邮箱 cooldown 恢复：{recovered_temp} 条")
            finally:
                conn.close()
        except Exception:
            pass

    scheduler.add_job(
        func=_expire_task,
        trigger="interval",
        seconds=60,
        id="pool_expire_stale_claims",
        name="邮箱池过期 Claim 回收",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        func=_recover_task,
        trigger="interval",
        seconds=300,
        id="pool_recover_cooldown",
        name="邮箱池 Cooldown 恢复",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    print("✓ 邮箱池维护 Job 已配置（expire: 60s，recover: 300s）")


def configure_scheduler_jobs(scheduler, app, test_refresh_token) -> None:
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception:
        return

    with app.app_context():
        enable_scheduled = settings_repo.get_setting("enable_scheduled_refresh", "true").lower() == "true"
        use_cron = settings_repo.get_setting("use_cron_schedule", "false").lower() == "true"
        refresh_interval_days = int(settings_repo.get_setting("refresh_interval_days", "30"))
        cron_expr = settings_repo.get_setting("refresh_cron", "0 2 * * *")

    try:
        scheduler.remove_job("scheduler_heartbeat")
    except Exception:
        pass
    scheduler.add_job(
        func=scheduler_heartbeat_task,
        trigger="interval",
        seconds=60,
        id="scheduler_heartbeat",
        name="Scheduler Heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    _configure_email_notification_job(scheduler, app)
    _configure_probe_poll_job(scheduler, app)
    _configure_pool_maintenance_jobs(scheduler)

    # 刷新 Job：根据 enable_scheduled 决定是否启用
    try:
        scheduler.remove_job("token_refresh")
    except Exception:
        pass

    if not enable_scheduled:
        print("✓ 定时刷新已禁用（调度器仍运行心跳）")
        return

    # 创建一个包含 app 和 test_refresh_token 的闭包
    def scheduled_task():
        scheduled_refresh_task(app, test_refresh_token)

    if use_cron:
        try:
            from croniter import croniter

            croniter(cron_expr, datetime.now())
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError("Cron 表达式格式错误，应为 5 段")
            minute, hour, day, month, day_of_week = parts
            trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)
            scheduler.add_job(
                func=scheduled_task,
                trigger=trigger,
                id="token_refresh",
                name="Token 定时刷新",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
            )
            print(f"✓ 定时任务已配置：Cron 表达式 '{cron_expr}'")
            return
        except Exception as e:
            print(f"⚠ Cron 配置无效：{str(e)}，回退到默认配置")

    scheduler.add_job(
        func=scheduled_task,
        trigger=CronTrigger(hour=2, minute=0),
        id="token_refresh",
        name="Token 定时刷新",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    print(f"✓ 定时任务已配置：每天凌晨 2:00 检查刷新（周期：{refresh_interval_days} 天）")


def init_scheduler(app, test_refresh_token):
    """初始化定时任务调度器"""
    global _scheduler_instance

    if _scheduler_instance is not None:
        return _scheduler_instance

    try:
        import atexit

        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()
        configure_scheduler_jobs(scheduler, app, test_refresh_token)
        atexit.register(lambda: scheduler.shutdown())

        scheduler.start()
        _scheduler_instance = scheduler
        print("✓ 调度器已启动")
        return scheduler
    except ImportError:
        print("⚠ APScheduler 未安装，定时任务功能不可用")
        print("  安装命令：pip install APScheduler>=3.10.0")
        return None
    except Exception as e:
        print(f"⚠ 定时任务初始化失败：{str(e)}")
        return None


def scheduled_refresh_task(app, test_refresh_token):
    """定时刷新任务（由调度器调用）"""
    trace_id = generate_trace_id()
    run_id = None
    lock_owner_id = uuid.uuid4().hex
    lock_acquired = False

    conn = create_sqlite_connection()

    try:
        with app.app_context():
            enable_scheduled = settings_repo.get_setting("enable_scheduled_refresh", "true").lower() == "true"
            use_cron = settings_repo.get_setting("use_cron_schedule", "false").lower() == "true"
            refresh_interval_days = int(settings_repo.get_setting("refresh_interval_days", "30"))
            delay_seconds = int(settings_repo.get_setting("refresh_delay_seconds", "5"))

        run_id = create_refresh_run(conn, "scheduled", trace_id, total=0)

        if not enable_scheduled:
            finish_refresh_run(conn, run_id, "skipped", 0, 0, 0, "定时刷新已禁用")
            return

        # 按天数策略：未到周期则跳过（不产生账号级刷新日志）
        if not use_cron:
            row = conn.execute("""
                SELECT finished_at
                FROM refresh_runs
                WHERE trigger_source = 'scheduled'
                  AND status IN ('completed', 'failed')
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
            """).fetchone()

            if row and row["finished_at"]:
                try:
                    last_time = datetime.fromisoformat(row["finished_at"])
                except Exception:
                    last_time = None

                if last_time:
                    next_due = last_time + timedelta(days=refresh_interval_days)
                    if utcnow() < next_due:
                        finish_refresh_run(
                            conn,
                            run_id,
                            "skipped",
                            0,
                            0,
                            0,
                            f"距离上次刷新未满 {refresh_interval_days} 天，下次最早：{next_due.strftime('%Y-%m-%d %H:%M:%S')}",
                        )
                        return

        # 获取刷新间隔配置
        delay_row = conn.execute("SELECT value FROM settings WHERE key = 'refresh_delay_seconds'").fetchone()
        delay_seconds = int(delay_row["value"]) if delay_row else 5

        # 清理超过半年的刷新记录
        try:
            conn.execute("DELETE FROM account_refresh_logs WHERE created_at < datetime('now', '-6 months')")
            conn.execute("DELETE FROM distributed_locks WHERE expires_at < ?", (time.time(),))
            conn.commit()
        except Exception:
            pass

        # PRD-00005 / TDD-00005：定时刷新只处理 Outlook 账号（IMAP 账号无 OAuth token 刷新语义）
        accounts = conn.execute("""
            SELECT id, email, client_id, refresh_token, group_id
            FROM accounts
            WHERE status = 'active'
              AND (account_type = 'outlook' OR account_type IS NULL)
        """).fetchall()
        total = len(accounts)

        # 更新 run_id 的 total
        conn.execute("UPDATE refresh_runs SET total = ? WHERE id = ?", (total, run_id))
        conn.commit()

        # 计算锁 TTL
        estimated = int(total * (max(delay_seconds, 0) + 2) + 600)
        ttl_seconds = max(60 * 60 * 2, estimated)
        ttl_seconds = min(ttl_seconds, 60 * 60 * 24)

        ok, lock_info = acquire_distributed_lock(conn, REFRESH_LOCK_NAME, lock_owner_id, ttl_seconds)
        if not ok:
            finish_refresh_run(conn, run_id, "skipped", total, 0, 0, "刷新任务冲突：已有刷新在执行")
            return
        lock_acquired = True

        success_count = 0
        failed_count = 0

        for index, account in enumerate(accounts, 1):
            account_id = account["id"]
            account_email = account["email"]
            client_id = account["client_id"]
            encrypted_refresh_token = account["refresh_token"]

            # 解密 refresh_token
            try:
                refresh_token = decrypt_data(encrypted_refresh_token) if encrypted_refresh_token else encrypted_refresh_token
            except Exception as e:
                failed_count += 1
                error_msg = f"解密 token 失败: {str(e)}"
                try:
                    conn.execute(
                        """
                        INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message, run_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            account_id,
                            account_email,
                            "scheduled",
                            "failed",
                            error_msg,
                            run_id,
                        ),
                    )
                    conn.commit()
                except Exception:
                    pass
                continue

            # 获取分组代理设置
            proxy_url = ""
            group_id = account["group_id"]
            if group_id:
                try:
                    group_row = conn.execute("SELECT proxy_url FROM groups WHERE id = ?", (group_id,)).fetchone()
                    if group_row:
                        proxy_url = group_row["proxy_url"] or ""
                except Exception:
                    proxy_url = ""

            success, error_msg, new_refresh_token = test_refresh_token(client_id, refresh_token, proxy_url)

            try:
                conn.execute(
                    """
                    INSERT INTO account_refresh_logs (account_id, account_email, refresh_type, status, error_message, run_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        account_id,
                        account_email,
                        "scheduled",
                        "success" if success else "failed",
                        error_msg,
                        run_id,
                    ),
                )

                if success:
                    # refresh token 可能滚动更新：保存新的 refresh_token（加密存储）
                    if isinstance(new_refresh_token, str) and new_refresh_token.strip() and new_refresh_token != refresh_token:
                        conn.execute(
                            """
                            UPDATE accounts
                            SET refresh_token = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """,
                            (encrypt_data(new_refresh_token), account_id),
                        )
                    conn.execute(
                        """
                        UPDATE accounts
                        SET last_refresh_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            status = CASE WHEN status = 'inactive' THEN 'active' ELSE status END
                        WHERE id = ?
                    """,
                        (account_id,),
                    )

                conn.commit()
            except Exception:
                pass

            if success:
                success_count += 1
            else:
                failed_count += 1

            if index < total and delay_seconds > 0:
                time.sleep(delay_seconds)

        finish_refresh_run(
            conn,
            run_id,
            "completed",
            total,
            success_count,
            failed_count,
            f"完成：成功 {success_count}，失败 {failed_count}",
        )

    except Exception as e:
        try:
            if run_id:
                finish_refresh_run(conn, run_id, "failed", 0, 0, 0, str(e))
        except Exception:
            pass
        try:
            app.logger.exception("Scheduled refresh task failed trace_id=%s", trace_id)
        except Exception:
            pass
    finally:
        if lock_acquired:
            release_distributed_lock(conn, REFRESH_LOCK_NAME, lock_owner_id)
        conn.close()


def should_autostart_scheduler() -> bool:
    """在 WSGI/Gunicorn 场景下自动启动调度器；避免 Flask CLI/重载器导致重复启动"""
    autostart = config.get_scheduler_autostart_default()
    if not autostart:
        return False

    # Flask CLI (flask run) + reloader：父进程不启动
    if config.env_true("FLASK_RUN_FROM_CLI", False) and not config.env_true("WERKZEUG_RUN_MAIN", False):
        return False

    return True


def get_scheduler_instance():
    """获取调度器实例"""
    return _scheduler_instance
