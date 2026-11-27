from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from outlook_web.services import mail_fetch as mail_fetch_service
from outlook_web.services import refresh as refresh_service
from tests._import_app import clear_login_attempts, import_web_app_module


class MinimalWorkbenchAndSubtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)

    def test_parallel_dual_protocol_fetch_returns_faster_channel(self):
        """双协议并行竞速应优先采用更快成功返回的通道。"""
        account = {
            "id": 1,
            "email": "fast@outlook.com",
            "account_type": "outlook",
            "client_id": "cid",
            "refresh_token": "rt",
        }

        def slow_graph(*args, **kwargs):
            time.sleep(0.15)
            return {"success": True, "emails": [{"id": "g1", "subject": "From Graph"}]}

        def fast_imap(*args, **kwargs):
            return {"success": True, "emails": [{"id": "i1", "subject": "From IMAP"}]}

        res = mail_fetch_service.fetch_account_emails_with_fallback(
            account,
            email_addr="fast@outlook.com",
            protocols=["graph", "imap"],
            parallel=True,
            graph_fetcher=slow_graph,
            imap_fetcher=fast_imap,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["method"], "IMAP (New)")
        self.assertEqual(res["emails"][0]["id"], "i1")

    def test_single_protocol_selection_respects_requested_channel(self):
        """仅勾选 Graph 或仅勾选 IMAP 时不得越权调用未勾选协议。"""
        account = {
            "id": 2,
            "email": "single@outlook.com",
            "account_type": "outlook",
            "client_id": "cid",
            "refresh_token": "rt",
        }
        calls = []

        def graph_fn(*args, **kwargs):
            calls.append("graph")
            return {"success": False, "error": {"code": "G_ERR"}}

        def imap_fn(*args, **kwargs):
            calls.append("imap")
            return {"success": True, "emails": [{"id": "m1", "subject": "Only IMAP"}]}

        res_graph_only = mail_fetch_service.fetch_account_emails_with_fallback(
            account,
            email_addr="single@outlook.com",
            protocols=["graph"],
            parallel=False,
            graph_fetcher=graph_fn,
            imap_fetcher=imap_fn,
        )
        self.assertFalse(res_graph_only["success"])
        self.assertEqual(calls, ["graph"])

        calls.clear()
        res_imap_only = mail_fetch_service.fetch_account_emails_with_fallback(
            account,
            email_addr="single@outlook.com",
            protocols=["imap"],
            parallel=False,
            graph_fetcher=graph_fn,
            imap_fetcher=imap_fn,
        )
        self.assertTrue(res_imap_only["success"])
        self.assertEqual(calls, ["imap"])

    def test_keyword_and_sender_filter(self):
        """关键词与发件人过滤应大小写不敏感并同时支持主题/摘要匹配。"""
        emails = [
            {"id": "1", "subject": "Your OpenAI code is 123456", "from": "noreply@openai.com", "body_preview": "code"},
            {"id": "2", "subject": "Weekly Newsletter", "from": "news@github.com", "body_preview": "updates"},
            {"id": "3", "subject": "Login Alert", "from": "security@openai.com", "body_preview": "OTP 998877"},
        ]
        res1 = mail_fetch_service.filter_fetched_emails(emails, keyword="otp", sender="OPENAI.COM")
        self.assertEqual([e["id"] for e in res1], ["3"])

        res2 = mail_fetch_service.filter_fetched_emails(emails, sender="github.com")
        self.assertEqual([e["id"] for e in res2], ["2"])

    def test_refresh_cooldown_helper_skips_recent_and_allows_stale(self):
        """10 分钟内已刷新的账号处于冷却期，超过 10 分钟则允许再次刷新。"""
        recent = (datetime.now(timezone.utc) - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
        stale = (datetime.now(timezone.utc) - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")

        self.assertTrue(refresh_service.is_account_in_refresh_cooldown(recent, 10))
        self.assertFalse(refresh_service.is_account_in_refresh_cooldown(stale, 10))
        self.assertFalse(refresh_service.is_account_in_refresh_cooldown(recent, 0))
        self.assertFalse(refresh_service.is_account_in_refresh_cooldown("", 10))

    def test_minimal_workbench_ui_subtraction_and_hover_tooltips(self):
        """验证极简双栏工作台、减法裁剪清单、0 常驻文字墙与悬停注释说明。"""
        index_html = Path("templates/index.html").read_text(encoding="utf-8")
        modals_html = Path("templates/partials/modals.html").read_text(encoding="utf-8")
        scripts_html = Path("templates/partials/scripts.html").read_text(encoding="utf-8")
        main_css = Path("static/css/main.css").read_text(encoding="utf-8")
        help_tip_js = Path("static/js/features/help_tip.js").read_text(encoding="utf-8")

        # 1. 极简工作台核心入口完备
        for token in (
            'id="tabOutlookBtn"',
            'id="tabImapBtn"',
            'id="tabTempBtn"',
            'id="fetchKeywordInput"',
            'id="fetchSenderInput"',
            'id="fetchLimitSelect"',
            'id="protoImapToggle"',
            'id="protoGraphToggle"',
            'id="btnFetchSelected"',
            'id="btnFetchAll"',
            'id="btnRefreshSelected"',
            'id="btnRefreshAll"',
        ):
            self.assertIn(token, index_html)

        # 2. 减法裁剪：旧重型页面/入口已移除
        for removed in (
            'id="page-dashboard"',
            'id="page-pool-admin"',
            'id="page-refresh-log"',
            'id="page-audit"',
            'id="page-diagnostics"',
            'id="mailboxCompactLayout"',
            'id="uiStyleSelect"',
            'id="themeToggleBtn"',
            'id="watchtowerUrl"',
            'id="webhookNotificationEnabled"',
            'id="emailNotificationEnabled"',
            'id="settingsTempMailApiBaseUrl"',
            'id="settingsExternalApiKeysJson"',
            'id="poolExternalEnabled"',
            'id="pluginCustomInstallModal"',
        ):
            self.assertNotIn(removed, index_html + modals_html)

        # 3. 保留的精简 3-Tab 设置项（全局代理 / 验证码 AI / 定时刷新 / Telegram / CF 临时邮箱 / 单 Key API / 数据库备份）
        for kept in (
            'id="settingsModal"',
            'id="settingsGlobalProxyEnabled"',
            'id="settingsGlobalProxyUrl"',
            'id="btnTestGlobalProxy"',
            'id="settingsVerificationAiEnabled"',
            'id="enableScheduledRefresh"',
            'id="telegramBotToken"',
            'id="settingsCfWorkerBaseUrl"',
            'id="settingsExternalApiKey"',
            'id="btnDownloadDatabaseBackup"',
        ):
            self.assertIn(kept, modals_html)

        # 4. 0 常驻 .form-hint 文字墙，全部使用 data-tip 悬停提示（默认不显示，鼠标移入显示）
        self.assertEqual(index_html.count("form-hint"), 0)
        self.assertEqual(modals_html.count("form-hint"), 0)
        self.assertGreaterEqual((index_html + modals_html).count("data-tip="), 35)
        self.assertIn("js/features/help_tip.js", scripts_html)
        self.assertIn(".hover-tooltip", main_css)
        self.assertIn("mouseover", help_tip_js)

        # 5. 已裁剪的前端旧模块文件不存在
        for pruned in (
            "static/js/features/mailbox_compact.js",
            "static/js/features/overview.js",
            "static/js/features/pool_admin.js",
            "static/js/features/plugins.js",
            "static/js/features/poll-engine.js",
        ):
            self.assertFalse(Path(pruned).exists(), f"{pruned} should be deleted")

    def test_api_emails_supports_protocols_and_keyword_sender_filter(self):
        """GET /api/emails/<email> 应正确透传 protocols/parallel 并执行 keyword/sender 过滤。"""
        client = self.app.test_client()
        self._login(client)

        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo

            acc = accounts_repo.get_account_by_email("filtertest@outlook.com")
            if not acc:
                accounts_repo.add_account("filtertest@outlook.com", "pw", "cid", "rt", 1)

        with patch("outlook_web.controllers.emails.graph_service.get_emails_graph") as mock_graph:
            mock_graph.return_value = {
                "success": True,
                "emails": [
                    {
                        "id": "m1",
                        "subject": "Verify your account 654321",
                        "from": {"emailAddress": {"address": "auth@service.io"}},
                        "receivedDateTime": "2026-11-27T10:00:00Z",
                        "isRead": False,
                        "hasAttachments": False,
                        "bodyPreview": "Your code is 654321",
                    },
                    {
                        "id": "m2",
                        "subject": "Promo offer",
                        "from": {"emailAddress": {"address": "ads@shop.com"}},
                        "receivedDateTime": "2026-11-27T09:00:00Z",
                        "isRead": True,
                        "hasAttachments": False,
                        "bodyPreview": "50% off",
                    },
                ],
            }
            resp = client.get("/api/emails/filtertest@outlook.com?protocols=graph&keyword=654321&sender=service.io")
            self.assertEqual(resp.status_code, 200)
            payload = resp.get_json()
            self.assertTrue(payload["success"])
            self.assertEqual(len(payload["emails"]), 1)
            self.assertEqual(payload["emails"][0]["id"], "m1")


if __name__ == "__main__":
    unittest.main()
