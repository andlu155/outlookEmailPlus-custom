import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class PluginDownloadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory(prefix="plugin-download-tests-")
        self._old_database_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(Path(self._temp_dir.name) / "test.db")

    def tearDown(self):
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def test_rejects_plugin_path_traversal_before_download(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
            with self.assertRaises(PluginManagerError) as ctx:
                install_plugin("../outside", url="https://example.com/plugin.py")

        self.assertEqual(ctx.exception.code, "INVALID_PLUGIN_NAME")
        mock_get.assert_not_called()

    def test_rejects_private_download_host_before_request(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        with patch.dict(os.environ, {"CUSTOM_PLUGIN_URL_ENABLED": "true"}):
            with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
                with self.assertRaises(PluginManagerError) as ctx:
                    install_plugin("private_plugin", url="https://127.0.0.1/plugin.py", sha256="a" * 64)

        self.assertEqual(ctx.exception.code, "PLUGIN_INVALID_URL")
        mock_get.assert_not_called()

    def test_disables_redirects_for_plugin_download(self):
        from outlook_web.services.temp_mail_plugin_manager import install_plugin

        with patch.dict(os.environ, {"CUSTOM_PLUGIN_URL_ENABLED": "true"}):
            with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
                response = mock_get.return_value
                response.status_code = 200
                response.headers = {}
                response.content = b"plugin-content"
                response.iter_content.return_value = [b"plugin-content"]
                response.raise_for_status.return_value = None
                install_plugin(
                    "redirect_plugin",
                    url="https://example.com/plugin.py",
                    sha256=hashlib.sha256(b"plugin-content").hexdigest(),
                )

        self.assertEqual(mock_get.call_args.kwargs["allow_redirects"], False)

    def test_custom_url_requires_explicit_enablement(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
            with self.assertRaises(PluginManagerError) as ctx:
                install_plugin("custom_plugin", url="https://example.com/plugin.py", sha256="a" * 64)

        self.assertEqual(ctx.exception.code, "CUSTOM_PLUGIN_URL_DISABLED")
        mock_get.assert_not_called()

    def test_rejects_hostname_resolved_to_private_address(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        with patch.dict(os.environ, {"CUSTOM_PLUGIN_URL_ENABLED": "true"}):
            with patch("outlook_web.services.temp_mail_plugin_manager.socket.getaddrinfo") as getaddrinfo:
                getaddrinfo.return_value = [(None, None, None, None, ("10.0.0.8", 443))]
                with self.assertRaises(PluginManagerError) as ctx:
                    install_plugin("private_dns", url="https://plugins.example/plugin.py", sha256="a" * 64)

        self.assertEqual(ctx.exception.code, "PLUGIN_INVALID_URL")

    def test_rejects_non_success_download_status(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        with patch.dict(os.environ, {"CUSTOM_PLUGIN_URL_ENABLED": "true"}):
            with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
                response = mock_get.return_value
                response.status_code = 302
                response.headers = {}
                with self.assertRaises(PluginManagerError) as ctx:
                    install_plugin("redirect_status", url="https://example.com/plugin.py", sha256="a" * 64)

        self.assertEqual(ctx.exception.code, "PLUGIN_DOWNLOAD_FAILED")

    def test_rejects_download_larger_than_configured_limit(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        content = b"plugin-content"
        with patch.dict(
            os.environ,
            {"CUSTOM_PLUGIN_URL_ENABLED": "true", "PLUGIN_DOWNLOAD_MAX_BYTES": "4"},
        ):
            with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
                response = mock_get.return_value
                response.status_code = 200
                response.headers = {"Content-Length": str(len(content))}
                response.iter_content.return_value = [content]
                with self.assertRaises(PluginManagerError) as ctx:
                    install_plugin(
                        "too_large",
                        url="https://example.com/plugin.py",
                        sha256=hashlib.sha256(content).hexdigest(),
                    )

        self.assertEqual(ctx.exception.code, "PLUGIN_DOWNLOAD_TOO_LARGE")

    def test_atomic_replace_failure_keeps_existing_plugin(self):
        from outlook_web.services.temp_mail_plugin_manager import PluginManagerError, install_plugin

        content = b"new-plugin"
        plugin_dir = Path(os.environ["DATABASE_PATH"]).parent / "plugins" / "temp_mail_providers"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        target = plugin_dir / "atomic_plugin.py"
        target.write_bytes(b"old-plugin")

        with patch.dict(os.environ, {"CUSTOM_PLUGIN_URL_ENABLED": "true"}):
            with patch("outlook_web.services.temp_mail_plugin_manager.requests.get") as mock_get:
                response = mock_get.return_value
                response.status_code = 200
                response.headers = {}
                response.iter_content.return_value = [content]
                with patch("outlook_web.services.temp_mail_plugin_manager.os.replace", side_effect=OSError("replace failed")):
                    with self.assertRaises(PluginManagerError) as ctx:
                        install_plugin(
                            "atomic_plugin",
                            url="https://example.com/plugin.py",
                            sha256=hashlib.sha256(content).hexdigest(),
                        )

        self.assertEqual(ctx.exception.code, "PLUGIN_INSTALL_FAILED")
        self.assertEqual(target.read_bytes(), b"old-plugin")
        self.assertEqual(list(plugin_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
