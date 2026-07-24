"""失效账号在成功读信 / 成功刷新后应自动恢复为 active。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class AccountStatusHealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM account_refresh_logs")
            db.execute("DELETE FROM accounts")
            db.execute("DELETE FROM groups WHERE COALESCE(is_system, 0) = 0")
            db.execute("""
                INSERT OR REPLACE INTO groups (id, name, description, color, is_system)
                VALUES (1, 'Test Group', '', '#666666', 0)
                """)
            db.execute("""
                INSERT OR IGNORE INTO groups (name, description, color)
                VALUES ('默认分组', '未分组的邮箱', '#666666')
                """)
            db.commit()

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _insert_account(self, email: str, status: str = "inactive") -> int:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            cur = db.execute(
                """
                INSERT INTO accounts
                    (email, password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (email, "pw", "cid-test", "rt-test", 1, status, "outlook", "outlook"),
            )
            db.commit()
            return int(cur.lastrowid)

    def _insert_refresh_log(self, account_id: int, email: str, status: str) -> None:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO account_refresh_logs
                    (account_id, account_email, refresh_type, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, email, "manual", status, "token expired" if status == "failed" else None),
            )
            db.commit()

    def _account_status(self, account_id: int) -> str:
        with self.app.app_context():
            from outlook_web.db import get_db

            row = get_db().execute("SELECT status FROM accounts WHERE id = ?", (account_id,)).fetchone()
            return str(row["status"])

    def _latest_refresh_status(self, account_id: int) -> str:
        with self.app.app_context():
            from outlook_web.db import get_db

            row = (
                get_db()
                .execute(
                    """
                SELECT status FROM account_refresh_logs
                WHERE account_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                    (account_id,),
                )
                .fetchone()
            )
            return str(row["status"]) if row else ""

    def test_touch_last_refresh_at_heals_inactive_and_clears_failed_log(self):
        email = "heal-mail@test.example"
        account_id = self._insert_account(email, status="inactive")
        self._insert_refresh_log(account_id, email, "failed")

        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo

            ok = accounts_repo.touch_last_refresh_at(account_id, account_email=email)
            self.assertTrue(ok)

        self.assertEqual(self._account_status(account_id), "active")
        self.assertEqual(self._latest_refresh_status(account_id), "success")

    def test_touch_last_refresh_at_does_not_heal_disabled(self):
        email = "heal-disabled@test.example"
        account_id = self._insert_account(email, status="disabled")

        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo

            ok = accounts_repo.touch_last_refresh_at(account_id, account_email=email)
            self.assertTrue(ok)

        self.assertEqual(self._account_status(account_id), "disabled")

    def test_log_refresh_result_success_heals_inactive(self):
        email = "heal-refresh@test.example"
        account_id = self._insert_account(email, status="inactive")

        with self.app.app_context():
            from outlook_web.repositories.refresh_logs import log_refresh_result

            ok = log_refresh_result(account_id, email, "manual", "success")
            self.assertTrue(ok)

        self.assertEqual(self._account_status(account_id), "active")

    def test_mark_status_refresh_failed_sets_inactive_and_last_refresh_at(self):
        email = "status-refresh-fail@test.example"
        account_id = self._insert_account(email, status="active")

        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.repositories import accounts as accounts_repo

            ok = accounts_repo.mark_status_refresh_failed(
                account_id,
                account_email=email,
                error_message="graph denied",
            )
            self.assertTrue(ok)
            row = (
                get_db()
                .execute(
                    "SELECT status, last_refresh_at FROM accounts WHERE id = ?",
                    (account_id,),
                )
                .fetchone()
            )
            self.assertEqual(str(row["status"]), "inactive")
            self.assertTrue(row["last_refresh_at"])

        self.assertEqual(self._latest_refresh_status(account_id), "failed")

    def test_mark_status_refresh_failed_leaves_disabled(self):
        email = "status-refresh-disabled@test.example"
        account_id = self._insert_account(email, status="disabled")

        with self.app.app_context():
            from outlook_web.repositories import accounts as accounts_repo

            ok = accounts_repo.mark_status_refresh_failed(
                account_id,
                account_email=email,
                error_message="graph denied",
            )
            self.assertTrue(ok)

        self.assertEqual(self._account_status(account_id), "disabled")

    @patch(
        "outlook_web.controllers.emails.graph_service.get_access_token_graph_result",
        return_value={
            "success": True,
            "access_token": "tok-test",
            "refresh_token": None,
            "scope": "Mail.Read offline_access",
        },
    )
    @patch(
        "outlook_web.controllers.emails.graph_service.get_emails_graph",
        return_value={
            "success": False,
            "error": {"code": "TOKEN_EXPIRED", "message": "token expired"},
        },
    )
    def test_status_refresh_batch_failure_marks_inactive(self, _mock_graph, _mock_token):
        email = "batch-status-fail@test.example"
        account_id = self._insert_account(email, status="active")

        client = self.app.test_client()
        self._login(client)

        # Force non-TESTING path for real scan failure handling.
        with self.app.app_context():
            prev_testing = self.app.config.get("TESTING")
            self.app.config["TESTING"] = False
            try:
                resp = client.post(
                    "/api/emails/aliases/batch",
                    json={"account_ids": [account_id], "top": 10},
                )
            finally:
                self.app.config["TESTING"] = prev_testing

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("success"))
        result = payload["results"][0]
        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("status"), "inactive")
        self.assertEqual(self._account_status(account_id), "inactive")

        with self.app.app_context():
            from outlook_web.db import get_db

            row = (
                get_db()
                .execute(
                    "SELECT last_refresh_at, alias_used_count FROM accounts WHERE id = ?",
                    (account_id,),
                )
                .fetchone()
            )
            self.assertTrue(row["last_refresh_at"])
            self.assertIsNone(row["alias_used_count"])

        # Failure marks inactive + last_refresh_at, but without alias scan it stays 未刷新.
        list_resp = client.get("/api/accounts?group_id=1&alias_filter=unsynced")
        self.assertEqual(list_resp.status_code, 200)
        emails = [a["email"] for a in list_resp.get_json().get("accounts", [])]
        self.assertIn(email, emails)

        synced_resp = client.get("/api/accounts?group_id=1&alias_filter=synced")
        self.assertEqual(synced_resp.status_code, 200)
        synced_emails = [a["email"] for a in synced_resp.get_json().get("accounts", [])]
        self.assertNotIn(email, synced_emails)

        inactive_resp = client.get("/api/accounts?group_id=1&status=inactive")
        self.assertEqual(inactive_resp.status_code, 200)
        inactive_emails = [a["email"] for a in inactive_resp.get_json().get("accounts", [])]
        self.assertIn(email, inactive_emails)

    @patch(
        "outlook_web.controllers.emails.compact_summary_service.update_summary_from_message_list",
        return_value={},
    )
    @patch(
        "outlook_web.controllers.emails.graph_service.get_emails_graph",
        return_value={
            "success": True,
            "emails": [
                {
                    "id": "msg-1",
                    "subject": "ok",
                    "from": {"emailAddress": {"address": "noreply@example.com"}},
                    "receivedDateTime": "2030-01-01T00:00:00Z",
                    "isRead": False,
                    "hasAttachments": False,
                    "bodyPreview": "preview",
                }
            ],
        },
    )
    def test_get_emails_success_reactivates_inactive_account(
        self,
        _mock_graph,
        _mock_summary,
    ):
        email = "CardovaKaili45@outlook.com"
        account_id = self._insert_account(email, status="inactive")
        self._insert_refresh_log(account_id, email, "failed")

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email}?folder=inbox&skip=0&top=10")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))
        self.assertEqual(self._account_status(account_id), "active")
        self.assertEqual(self._latest_refresh_status(account_id), "success")

        # 失效过滤器不应再命中该账号
        list_resp = client.get("/api/accounts?group_id=1&status=inactive")
        self.assertEqual(list_resp.status_code, 200)
        inactive_emails = [a["email"] for a in list_resp.get_json().get("accounts", [])]
        self.assertNotIn(email, inactive_emails)


if __name__ == "__main__":
    unittest.main()
