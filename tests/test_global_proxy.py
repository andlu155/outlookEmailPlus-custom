from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch

from outlook_web.db import DB_SCHEMA_VERSION, init_db
from outlook_web.repositories import settings as settings_repo
from outlook_web.security.crypto import is_encrypted
from outlook_web.services import proxy as proxy_service
from tests._import_app import clear_login_attempts, import_web_app_module


class ProxyUnitTests(unittest.TestCase):
    def test_validate_proxy_url(self):
        self.assertEqual(proxy_service.validate_proxy_url(""), (True, ""))
        self.assertEqual(proxy_service.validate_proxy_url("http://127.0.0.1:7890")[0], True)
        self.assertEqual(proxy_service.validate_proxy_url("socks5://user:pass@proxy.example.com:1080")[0], True)
        self.assertEqual(proxy_service.validate_proxy_url("socks5h://10.0.0.1:1080")[0], True)

        self.assertEqual(proxy_service.validate_proxy_url("ftp://proxy.example.com:21")[0], False)
        self.assertEqual(proxy_service.validate_proxy_url("http://proxy.example.com:99999")[0], False)
        self.assertEqual(proxy_service.validate_proxy_url("http://has space:8080")[0], False)
        self.assertEqual(proxy_service.validate_proxy_url("http://:8080")[0], False)

    def test_mask_and_sanitize_proxy_credentials(self):
        raw = "socks5://alice:super_secret@proxy.example.com:1080"
        masked = proxy_service.mask_proxy_url(raw)
        self.assertEqual(masked, "socks5://***@proxy.example.com:1080")
        self.assertNotIn("super_secret", masked)
        self.assertNotIn("alice", masked)

        err = f"Connection failed via {raw}: timeout"
        sanitized = proxy_service.sanitize_proxy_error(err, raw)
        self.assertNotIn("super_secret", sanitized)
        self.assertIn("socks5://***@proxy.example.com:1080", sanitized)

    def test_local_or_private_url_detection(self):
        self.assertTrue(proxy_service.is_local_or_private_url("http://localhost:8080/v1/update"))
        self.assertTrue(proxy_service.is_local_or_private_url("http://127.0.0.1:11434/v1"))
        self.assertTrue(proxy_service.is_local_or_private_url("http://192.168.1.20:8080/hook"))
        self.assertTrue(proxy_service.is_local_or_private_url("http://watchtower:8080/v1/update"))
        self.assertFalse(proxy_service.is_local_or_private_url("https://api.github.com/repos/a/b"))
        self.assertFalse(proxy_service.is_local_or_private_url("https://graph.microsoft.com/v1.0/me"))

    def test_db_migration_v25_to_v26_backfills_group_proxy_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "legacy_v25.db")
            init_db(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                # 模拟 v25 存量状态：有自定义 proxy_url 的分组与空代理分组
                conn.execute("UPDATE settings SET value = '25' WHERE key = 'db_schema_version'")
                conn.execute(
                    "INSERT INTO groups (name, description, color, proxy_url, proxy_mode) VALUES (?, '', '#111', ?, 'inherit')",
                    ("has_proxy_group", "http://127.0.0.1:7890"),
                )
                conn.execute(
                    "INSERT INTO groups (name, description, color, proxy_url, proxy_mode) VALUES (?, '', '#222', '', 'inherit')",
                    ("no_proxy_group",),
                )
                conn.commit()
            finally:
                conn.close()

            init_db(db_path)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                version = conn.execute("SELECT value FROM settings WHERE key = 'db_schema_version'").fetchone()["value"]
                self.assertEqual(str(version), str(DB_SCHEMA_VERSION))
                g1 = conn.execute("SELECT proxy_mode, proxy_url FROM groups WHERE name = 'has_proxy_group'").fetchone()
                g2 = conn.execute("SELECT proxy_mode, proxy_url FROM groups WHERE name = 'no_proxy_group'").fetchone()
                self.assertEqual(g1["proxy_mode"], "custom")
                self.assertEqual(g1["proxy_url"], "http://127.0.0.1:7890")
                self.assertEqual(g2["proxy_mode"], "inherit")
            finally:
                conn.close()


class GlobalProxyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            settings_repo.set_setting("global_proxy_enabled", "false")
            settings_repo.set_setting("global_proxy_url", "")
            settings_repo.set_setting("telegram_proxy_url", "")

    def tearDown(self):
        with self.app.app_context():
            settings_repo.set_setting("global_proxy_enabled", "false")
            settings_repo.set_setting("global_proxy_url", "")
            settings_repo.set_setting("telegram_proxy_url", "")

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_settings_global_proxy_save_encrypt_and_precedence(self):
        client = self.app.test_client()
        self._login(client)

        # 未填地址时不能开启全局代理
        bad_enable = client.put(
            "/api/settings",
            json={"global_proxy_enabled": True, "global_proxy_url": ""},
        )
        self.assertEqual(bad_enable.status_code, 400)

        # 非法协议校验
        bad_scheme = client.put(
            "/api/settings",
            json={"global_proxy_enabled": True, "global_proxy_url": "ftp://127.0.0.1:21"},
        )
        self.assertEqual(bad_scheme.status_code, 400)

        # 正常保存并验证数据库加密存储与 GET 回读脱敏字段
        proxy_url = "socks5://alice:secret123@proxy.example.com:1080"
        ok_resp = client.put(
            "/api/settings",
            json={"global_proxy_enabled": True, "global_proxy_url": proxy_url},
        )
        self.assertEqual(ok_resp.status_code, 200)

        with self.app.app_context():
            raw_db_val = settings_repo.get_setting("global_proxy_url", "")
            self.assertTrue(is_encrypted(raw_db_val))
            self.assertEqual(settings_repo.get_effective_global_proxy_url(), proxy_url)

        get_resp = client.get("/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        s = get_resp.get_json()["settings"]
        self.assertTrue(s["global_proxy_enabled"])
        self.assertEqual(s["global_proxy_url"], proxy_url)
        self.assertEqual(s["global_proxy_url_masked"], "socks5://***@proxy.example.com:1080")

        # 创建三个分组验证 inherit / custom / direct 优先级
        suffix = uuid.uuid4().hex[:6]
        g_inherit = client.post(
            "/api/groups",
            json={"name": f"inherit_{suffix}", "proxy_mode": "inherit"},
        ).get_json()["group_id"]
        g_custom = client.post(
            "/api/groups",
            json={
                "name": f"custom_{suffix}",
                "proxy_mode": "custom",
                "proxy_url": "http://10.1.2.3:8080",
            },
        ).get_json()["group_id"]
        g_direct = client.post(
            "/api/groups",
            json={"name": f"direct_{suffix}", "proxy_mode": "direct"},
        ).get_json()["group_id"]

        with self.app.app_context():
            self.assertEqual(proxy_service.resolve_account_proxy(group_id=g_inherit), (proxy_url, False))
            self.assertEqual(
                proxy_service.resolve_account_proxy(group_id=g_custom),
                ("http://10.1.2.3:8080", False),
            )
            self.assertEqual(proxy_service.resolve_account_proxy(group_id=g_direct), ("", True))

            # Telegram 留空继承全局代理；非空优先使用 Telegram 专属代理
            self.assertEqual(
                proxy_service.resolve_system_proxy(override_url="", target_url="https://api.telegram.org"),
                (proxy_url, False),
            )
            self.assertEqual(
                proxy_service.resolve_system_proxy(
                    override_url="http://127.0.0.1:7891", target_url="https://api.telegram.org"
                ),
                ("http://127.0.0.1:7891", False),
            )
            # 本地 Webhook 自动绕过全局代理
            self.assertEqual(
                proxy_service.resolve_system_proxy(target_url="http://127.0.0.1:9000/hook"),
                ("", False),
            )

    @patch("outlook_web.services.proxy.requests.get")
    def test_api_test_proxy_endpoint(self, mock_get):
        client = self.app.test_client()
        self._login(client)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        resp = client.post(
            "/api/settings/test-proxy",
            json={"proxy_url": "http://user:pw@127.0.0.1:7890"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertTrue(body["ok"])
        self.assertEqual(body["proxy_masked"], "http://***@127.0.0.1:7890")
        self.assertEqual(
            mock_get.call_args.kwargs["proxies"],
            {"http": "http://user:pw@127.0.0.1:7890", "https": "http://user:pw@127.0.0.1:7890"},
        )

    @patch("outlook_web.services.oauth_tool.requests.post")
    def test_oauth_tool_uses_global_proxy_when_enabled(self, mock_post):
        from outlook_web.services import oauth_tool

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "at", "refresh_token": "rt", "scope": "IMAP.AccessAsUser.All"}
        mock_post.return_value = mock_resp

        with self.app.app_context():
            settings_repo.set_setting("global_proxy_enabled", "true")
            settings_repo.set_setting("global_proxy_url", "http://127.0.0.1:7890")
            oauth_tool.exchange_code_for_tokens(
                "code123",
                {
                    "client_id": "cid-12345678",
                    "redirect_uri": "http://localhost:5000/cb",
                    "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
                    "tenant": "consumers",
                },
                "verifier",
            )
            self.assertEqual(
                mock_post.call_args.kwargs["proxies"],
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            )


if __name__ == "__main__":
    unittest.main()
