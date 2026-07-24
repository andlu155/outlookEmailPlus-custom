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
            db.execute(
                """
                INSERT OR REPLACE INTO groups (id, name, description, color, is_system)
                VALUES (1, 'Test Group', '', '#666666', 0)
                """
            )
            db.execute(
                """
                INSERT OR IGNORE INTO groups (name, description, color)
                VALUES ('默认分组', '未分组的邮箱', '#666666')
                """
            )
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

            row = get_db().execute(
                """
                SELECT status FROM account_refresh_logs
                WHERE account_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (account_id,),
            ).fetchone()
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
