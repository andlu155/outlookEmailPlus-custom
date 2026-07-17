import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outlook_web import config

ROOT = Path(__file__).resolve().parents[1]


class ProjectHardeningTests(unittest.TestCase):
    def test_login_password_requires_explicit_environment_value(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LOGIN_PASSWORD"):
                config.get_login_password_default()

    def test_compose_requires_explicit_watchtower_token(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("WATCHTOWER_HTTP_API_TOKEN:?", compose)
        self.assertNotIn("outlook-mail-plus-watchtower-default", compose)

    def test_npm_test_is_the_browser_extension_test_command(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["scripts"]["test"], "npm run test:browser-extension")

    def test_gitignore_keeps_node_manifests_trackable(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertNotIn("package.json", ignored)
        self.assertNotIn("package-lock.json", ignored)

    def test_oauth_tool_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(config.get_oauth_tool_enabled())

    def test_temp_mail_api_key_has_no_builtin_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.get_temp_mail_api_key_default(), "")

    def test_custom_plugin_url_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(config.get_custom_plugin_url_enabled())

    def test_plugin_download_size_defaults_to_one_mebibyte(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.get_plugin_download_max_bytes(), 1024 * 1024)

    def test_oauth_routes_are_not_registered_when_disabled(self):
        from outlook_web import app as app_module

        original_app = app_module._APP_INSTANCE
        with tempfile.TemporaryDirectory(prefix="oauth-disabled-tests-") as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "SECRET_KEY": "test-secret-key-32bytes-minimum-0000000000000000",
                    "LOGIN_PASSWORD": "testpass123",
                    "DATABASE_PATH": str(Path(temp_dir) / "test.db"),
                    "SCHEDULER_AUTOSTART": "false",
                    "OAUTH_TOOL_ENABLED": "false",
                },
                clear=False,
            ):
                app_module._APP_INSTANCE = None
                try:
                    app = app_module.create_app(autostart_scheduler=False)
                    routes = {rule.rule for rule in app.url_map.iter_rules()}
                    self.assertNotIn("/token-tool", routes)
                    self.assertNotIn("/api/token-tool/config", routes)
                finally:
                    app_module._APP_INSTANCE = original_app


if __name__ == "__main__":
    unittest.main()
