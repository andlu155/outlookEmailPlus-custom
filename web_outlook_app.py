#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outlook 邮件 Web 应用（兼容入口）

目标：
- 保持部署入口兼容：`web_outlook_app:app`
- 内部实现已迁移到 `outlook_web/` 模块化架构

关联文档：
- PRD：docs/PRD/Outlook邮件管理工具-前后端拆分与模块化PRD.md
- FD：docs/FD/Outlook邮件管理工具-前后端拆分与模块化FD.md
- TDD：docs/TDD/Outlook邮件管理工具-前后端拆分与模块化TDD.md
- DEV：docs/DEV/00002-前后端拆分-开发者指南.md
"""

import os
import sys

try:
    # 兼容直接执行 `python web_outlook_app.py` 的场景：
    # 自动加载当前工作目录下 .env，避免 SECRET_KEY / LOGIN_PASSWORD 未注入导致
    # 启动失败或凭据解密口径不一致。
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # 保持部署兼容：即使未安装 python-dotenv 也不阻断导入。
    pass

from outlook_web.app import create_app
from outlook_web.db import create_sqlite_connection
from outlook_web.errors import build_error_payload, sanitize_error_details
from outlook_web.repositories.distributed_locks import (
    acquire_distributed_lock,
    release_distributed_lock,
)

# 兼容导入：从各模块导出常用函数
from outlook_web.security.auth import MAX_LOGIN_ATTEMPTS
from outlook_web.security.crypto import decrypt_data, encrypt_data
from outlook_web.services import graph as graph_service
from outlook_web.services import scheduler as scheduler_service
from outlook_web.services.temp_mail_plugin_cli import main as temp_mail_plugin_cli_main

# 在脚本运行场景（__main__）中，调度器由 main block 统一控制，
# 避免 debug reloader 父进程误启后台线程。
app = create_app(autostart_scheduler=None if __name__ != "__main__" else False)


__all__ = [
    "app",
    "main",
    "create_sqlite_connection",
    "MAX_LOGIN_ATTEMPTS",
    "sanitize_error_details",
    "build_error_payload",
    "decrypt_data",
    "encrypt_data",
    "acquire_distributed_lock",
    "release_distributed_lock",
]


def main() -> None:
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "0.0.0.0")
    debug = os.getenv("FLASK_ENV", "production") != "production"

    print("=" * 60)
    print("Outlook 邮件 Web 应用")
    print("=" * 60)
    print(f"访问地址: http://{host}:{port}")
    print(f"运行模式: {'开发' if debug else '生产'}")
    print("=" * 60)

    # 初始化定时任务（与旧版行为保持一致）
    if not debug or os.getenv("WERKZEUG_RUN_MAIN") == "true":
        if scheduler_service.should_autostart_scheduler():
            scheduler_service.init_scheduler(app, graph_service.test_refresh_token_with_rotation)
        else:
            print("✓ 已根据配置跳过启动调度器")
    else:
        print("✓ 调试重载器父进程：跳过启动调度器")

    app.run(debug=debug, host=host, port=port)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in {"install-provider", "uninstall-provider", "list-providers"}:
        raise SystemExit(temp_mail_plugin_cli_main(sys.argv[1:]))
    main()
