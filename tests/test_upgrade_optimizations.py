from __future__ import annotations

import unittest
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._import_app import clear_login_attempts, import_web_app_module


class BackendOptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        return resp

    @patch("outlook_web.services.verification_channel_routing.graph_service.get_email_detail_graph")
    @patch("outlook_web.services.verification_channel_routing.graph_service.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.graph_service.get_access_token_graph_result")
    @patch("outlook_web.services.verification_extractor.enhance_verification_with_ai_fallback")
    def test_verification_reuses_graph_token_and_records_ai_used(
        self,
        mock_ai_fallback,
        mock_token,
        mock_get_emails,
        mock_get_detail,
    ):
        from outlook_web.services import verification_channel_routing as vcr

        mock_token.return_value = {
            "success": True,
            "access_token": "reused-token-xyz",
            "scope": "Mail.Read",
        }
        mock_get_emails.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "msg-1",
                    "subject": "Verify",
                    "from": {"emailAddress": {"address": "no-reply@example.com"}},
                    "receivedDateTime": "2026-11-26T10:00:00Z",
                    "bodyPreview": "hello",
                }
            ],
        }
        mock_get_detail.return_value = {
            "id": "msg-1",
            "subject": "Verify",
            "from": {"emailAddress": {"address": "no-reply@example.com"}},
            "receivedDateTime": "2026-11-26T10:00:00Z",
            "body": {"content": "Your code is hidden", "contentType": "text"},
        }
        mock_ai_fallback.return_value = {
            "verification_code": "654321",
            "verification_link": None,
            "formatted": "654321",
            "confidence": "high",
            "code_confidence": "high",
            "ai_used": True,
        }

        with self.app.app_context():
            res = vcr.extract_verification_for_outlook(
                account={
                    "id": 999,
                    "email": "reuse@outlook.com",
                    "client_id": "cid",
                    "refresh_token": "rt",
                    "preferred_verification_channel": "graph_inbox",
                },
                proxy_url="",
                resolved_policy={"code_length": "6-6", "code_regex": ""},
            )

        self.assertTrue(res["success"])
        self.assertEqual(mock_token.call_count, 1)
        self.assertEqual(mock_get_emails.call_args.kwargs.get("access_token"), "reused-token-xyz")
        self.assertEqual(mock_get_detail.call_args.kwargs.get("access_token"), "reused-token-xyz")
        self.assertTrue(res["_log_used_ai"])
        self.assertEqual(res["_log_channel"], "ai_fallback")

    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_imap_batch_fetch_preserves_newest_first_order(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import get_emails_imap_with_server

        mock_token.return_value = {"success": True, "access_token": "mock-at"}
        conn = MagicMock()
        mock_imap_cls.return_value = conn
        conn.authenticate.return_value = ("OK", [b"Success"])
        conn.select.return_value = ("OK", [b"3"])
        conn.search.return_value = ("OK", [b"1 2 3"])

        def _msg(subj: str) -> bytes:
            m = MIMEText("body", "plain", "utf-8")
            m["Subject"] = subj
            m["From"] = "a@b.com"
            return m.as_bytes()

        # IMAP 服务端通常按序列号升序返回 (1, 2, 3)
        conn.fetch.return_value = (
            "OK",
            [
                (b"1 (RFC822)", _msg("oldest")),
                b")",
                (b"2 (RFC822)", _msg("middle")),
                b")",
                (b"3 (RFC822)", _msg("newest")),
                b")",
            ],
        )

        res = get_emails_imap_with_server("u@outlook.com", "cid", "rt", top=3)
        self.assertTrue(res["success"])
        subjects = [e["subject"] for e in res["emails"]]
        self.assertEqual(subjects, ["newest", "middle", "oldest"])

    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    def test_delete_emails_imap_fast_fails_without_opening_socket(self, mock_imap_cls):
        from outlook_web.services.imap import delete_emails_imap

        res = delete_emails_imap("u@outlook.com", "cid", "rt", ["1"], "outlook.live.com")
        self.assertFalse(res["success"])
        mock_imap_cls.assert_not_called()

    def test_watchtower_test_rejects_non_http_scheme(self):
        client = self.app.test_client()
        self._login(client)
        resp = client.post(
            "/api/system/test-watchtower",
            json={"url": "file:///etc/passwd", "token": "abc"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["success"])

    def test_web_outlook_app_passes_rotation_refresh_fn(self):
        source = Path("web_outlook_app.py").read_text(encoding="utf-8")
        self.assertIn("graph_service.test_refresh_token_with_rotation", source)

    def test_frontend_contract_for_global_proxy_and_bugfixes(self):
        index_html = Path("templates/index.html").read_text(encoding="utf-8")
        modals_html = Path("templates/partials/modals.html").read_text(encoding="utf-8")
        main_css = Path("static/css/main.css").read_text(encoding="utf-8")
        settings_js = Path("static/js/features/settings.js").read_text(encoding="utf-8")

        # 唯一 #refreshProgressText（修复重复 ID Bug）
        total_progress_id_count = index_html.count('id="refreshProgressText"') + modals_html.count('id="refreshProgressText"')
        self.assertEqual(total_progress_id_count, 1)

        # 全局代理 UI 与分组三态控件（已收敛进精简设置弹窗 modals.html）
        self.assertIn('id="settingsGlobalProxyEnabled"', modals_html)
        self.assertIn('id="settingsGlobalProxyUrl"', modals_html)
        self.assertIn('id="btnTestGlobalProxy"', modals_html)
        self.assertIn('name="groupProxyMode"', modals_html)
        self.assertIn('id="btnTestGroupProxy"', modals_html)

        # .toast.warning 样式与作用域限定的 switchSettingsTab
        self.assertIn(".toast.warning", main_css)
        self.assertIn("#settingsTabNav .settings-tab", settings_js)

        # 旧死文件已清理
        for dead_path in (
            "static/js/layout-manager.js",
            "static/js/layout-bootstrap.js",
            "static/js/state-manager.js",
            "static/css/layout.css",
        ):
            self.assertFalse(Path(dead_path).exists(), f"{dead_path} should be removed")


if __name__ == "__main__":
    unittest.main()
