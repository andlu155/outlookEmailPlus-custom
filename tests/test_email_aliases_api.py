from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class EmailAliasesApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM accounts WHERE email LIKE '%@aliasscan.test'")
            db.commit()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _insert_account(self, email_addr: str, *, account_type: str = "outlook") -> None:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "pw",
                    "cid-test",
                    "rt-test",
                    1,
                    "active",
                    account_type,
                    "outlook" if account_type == "outlook" else "imap",
                ),
            )
            db.commit()

    def test_aliases_endpoint_not_found(self):
        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/emails/missing@aliasscan.test/aliases")
        self.assertEqual(resp.status_code, 404)

    def test_aliases_endpoint_unsupported_for_imap(self):
        self._insert_account("imapuser@aliasscan.test", account_type="imap")
        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/emails/imapuser@aliasscan.test/aliases")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("supported"))
        self.assertEqual(data.get("aliases"), [])

    @patch("outlook_web.services.graph.get_emails_graph")
    def test_aliases_endpoint_discovers_plus_addresses(self, mock_get_emails_graph):
        self._insert_account("main@aliasscan.test")

        def _side_effect(*_args, **kwargs):
            folder = kwargs.get("folder") or "inbox"
            if folder == "inbox":
                return {
                    "success": True,
                    "emails": [
                        {
                            "toRecipients": [
                                {"emailAddress": {"address": "main+78588@aliasscan.test"}},
                            ],
                            "ccRecipients": [],
                        },
                        {
                            "toRecipients": [
                                {"emailAddress": {"address": "main@aliasscan.test"}},
                            ],
                            "ccRecipients": [
                                {"emailAddress": {"address": "main+shop@aliasscan.test"}},
                            ],
                        },
                    ],
                }
            return {"success": True, "emails": []}

        mock_get_emails_graph.side_effect = _side_effect

        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/emails/main@aliasscan.test/aliases")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("supported"))
        self.assertEqual(data.get("used"), 2)
        self.assertEqual(data.get("soft_limit"), 5)
        self.assertEqual(data.get("remaining"), 3)
        self.assertEqual(
            data.get("aliases"),
            ["main+78588@aliasscan.test", "main+shop@aliasscan.test"],
        )
        self.assertGreaterEqual(data.get("scanned_messages"), 2)
        self.assertTrue(mock_get_emails_graph.called)
        kwargs = mock_get_emails_graph.call_args.kwargs
        self.assertTrue(kwargs.get("include_recipients"))

    def test_frontend_contains_alias_entry_points(self):
        client = self.app.test_client()
        self._login(client)
        for path in (
            "/static/js/features/accounts.js",
            "/static/js/features/groups.js",
            "/static/js/features/mailbox_compact.js",
        ):
            resp = client.get(path)
            self.assertEqual(resp.status_code, 200, path)
            text = resp.data.decode("utf-8")
            self.assertIn("showEmailAliasesModal", text, path)

        html = client.get("/").data.decode("utf-8")
        self.assertIn("emailAliasesModal", html)
        self.assertIn("分裂邮箱", html)
        self.assertIn("状态刷新", html)
        self.assertIn("添加时间", html)
        self.assertIn("有分裂", html)
        self.assertIn("无分裂", html)
        self.assertIn("已刷新", html)
        self.assertIn("未刷新", html)
        self.assertIn("失效", html)
        self.assertIn("account-toolbar", html)
        self.assertIn("aliasSyncProgressBar", html)
        self.assertIn("cancelAliasSync()", html)
        self.assertIn("toolbarAliasSyncBtn", html)

        groups_js = client.get("/static/js/features/groups.js").data.decode("utf-8")
        self.assertIn("batchSyncEmailAliases", groups_js)
        self.assertIn("buildAccountAliasCountBadge", groups_js)
        self.assertIn("created_at", groups_js)
        self.assertIn("ALIAS_BATCH_CHUNK_SIZE", groups_js)
        # Progress freezes if a whole page is one request; keep per-account chunks.
        self.assertIn("const ALIAS_BATCH_CHUNK_SIZE = 1", groups_js)
        self.assertIn("findAccountEmailById", groups_js)
        self.assertIn("refreshAliasSyncAccountViews", groups_js)
        self.assertIn("alias_filter", groups_js)
        self.assertIn("alias_filter', 'synced'", groups_js)
        self.assertIn("alias_filter', 'unsynced'", groups_js)
        self.assertIn("last_refresh_at", groups_js)
        self.assertIn("状态刷新", groups_js)
        self.assertIn("cancelAliasSync", groups_js)
        self.assertIn("AbortController", groups_js)
        self.assertIn("setAliasSyncProgressVisible", groups_js)
        self.assertIn("resolveAliasSyncTargets", groups_js)
        self.assertNotIn("单次最多同步 20 个账号的分裂地址", groups_js)

    @patch("outlook_web.services.graph.get_emails_graph")
    def test_single_alias_scan_persists_count_cache(self, mock_get_emails_graph):
        self._insert_account("cache@aliasscan.test")

        def _side_effect(*_args, **kwargs):
            folder = kwargs.get("folder") or "inbox"
            if folder == "inbox":
                return {
                    "success": True,
                    "emails": [
                        {
                            "toRecipients": [
                                {"emailAddress": {"address": "cache+one@aliasscan.test"}},
                            ],
                            "ccRecipients": [],
                        }
                    ],
                }
            return {"success": True, "emails": []}

        mock_get_emails_graph.side_effect = _side_effect

        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/emails/cache@aliasscan.test/aliases")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("used"), 1)

        with self.app.app_context():
            from outlook_web.db import get_db

            row = (
                get_db()
                .execute(
                    "SELECT alias_used_count, alias_soft_limit, alias_scanned_at FROM accounts WHERE email = ?",
                    ("cache@aliasscan.test",),
                )
                .fetchone()
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row["alias_used_count"]), 1)
            self.assertEqual(int(row["alias_soft_limit"]), 5)
            self.assertTrue(row["alias_scanned_at"])

    def test_batch_alias_scan_endpoint(self):
        self._insert_account("batch1@aliasscan.test")
        self._insert_account("batch2@aliasscan.test", account_type="imap")

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            rows = db.execute(
                "SELECT id, email FROM accounts WHERE email IN (?, ?)",
                ("batch1@aliasscan.test", "batch2@aliasscan.test"),
            ).fetchall()
            id_by_email = {row["email"]: int(row["id"]) for row in rows}

        client = self.app.test_client()
        self._login(client)
        resp = client.post(
            "/api/emails/aliases/batch",
            json={
                "account_ids": [
                    id_by_email["batch1@aliasscan.test"],
                    id_by_email["batch2@aliasscan.test"],
                ]
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        summary = data.get("summary") or {}
        self.assertEqual(summary.get("total_accounts"), 2)
        self.assertEqual(summary.get("success_accounts"), 1)
        self.assertEqual(summary.get("unsupported_accounts"), 1)

        with self.app.app_context():
            from outlook_web.db import get_db

            row = (
                get_db()
                .execute(
                    "SELECT alias_used_count, alias_soft_limit FROM accounts WHERE email = ?",
                    ("batch1@aliasscan.test",),
                )
                .fetchone()
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row["alias_used_count"]), 0)
            self.assertEqual(int(row["alias_soft_limit"]), 5)


if __name__ == "__main__":
    unittest.main()
