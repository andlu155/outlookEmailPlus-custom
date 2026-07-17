import importlib
import os
import sys
import tempfile
from pathlib import Path

_TEMP_DIR = tempfile.TemporaryDirectory(prefix="outlookEmail-tests-")
_DB_PATH = Path(_TEMP_DIR.name) / "test.db"


def import_web_app_module():
    """
    以"可测试"的方式导入 web_outlook_app：
    - 注入必要环境变量（SECRET_KEY / DATABASE_PATH 等）
    - 禁用调度器自启动，避免测试期间启动后台线程
    - 将 DB 指向临时文件，避免污染本地 data/
    """
    os.environ["SECRET_KEY"] = "test-secret-key-32bytes-minimum-0000000000000000"
    os.environ["LOGIN_PASSWORD"] = "testpass123"  # >= 8
    os.environ["SCHEDULER_AUTOSTART"] = "false"
    os.environ["OAUTH_TOOL_ENABLED"] = "true"
    os.environ["DATABASE_PATH"] = str(_DB_PATH)

    if "web_outlook_app" in sys.modules:
        return sys.modules["web_outlook_app"]

    module = importlib.import_module("web_outlook_app")

    # 测试配置：禁用 CSRF（避免额外 token 依赖），开启 TESTING
    module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        WTF_CSRF_CHECK_DEFAULT=False,
    )
    return module


def clear_login_attempts():
    """清理登录限制记录，避免测试间互相影响"""
    from outlook_web.db import get_db

    try:
        db = get_db()
        db.execute("DELETE FROM login_attempts")
        db.commit()
    except Exception:
        pass
