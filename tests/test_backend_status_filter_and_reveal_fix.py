import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class BackendStatusFilterAndRevealFixTests(unittest.TestCase):
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
            # Shared temp DB: wipe non-system groups, then restore seeds other suites expect.
            db.execute("DELETE FROM groups WHERE COALESCE(is_system, 0) = 0")
            db.execute("""
                INSERT OR REPLACE INTO groups (id, name, description, color, is_system)
                VALUES (1, 'Test Group', '', '#666666', 0)
                """)
            # Match outlook_web.db.init_db seeds (name-based uniqueness).
            db.execute("""
                INSERT OR IGNORE INTO groups (name, description, color)
                VALUES ('默认分组', '未分组的邮箱', '#666666')
                """)
            db.execute("""
                INSERT OR IGNORE INTO groups (name, description, color, is_system)
                VALUES ('临时邮箱', '自建临时邮箱服务', '#00bcf2', 1)
                """)
            system_row = db.execute("SELECT id FROM groups WHERE is_system = 1 LIMIT 1").fetchone()
            if not system_row:
                db.execute("""
                    INSERT INTO groups (name, description, color, is_system)
                    VALUES ('临时邮箱', '自建临时邮箱服务', '#00bcf2', 1)
                    """)
            db.commit()

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _insert_account(self, email: str, status: str, password: str = "", imap_password: str = "") -> int:
        with self.app.app_context():
            from outlook_web.db import get_db
            from outlook_web.security.crypto import encrypt_data

            enc_pwd = encrypt_data(password) if password else ""
            enc_imap = encrypt_data(imap_password) if imap_password else ""

            db = get_db()
            cur = db.execute(
                """
                INSERT INTO accounts (email, password, imap_password, client_id, refresh_token, group_id, status, account_type, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (email, enc_pwd, enc_imap, "cid", "rt", 1, status, "outlook", "outlook"),
            )
            db.commit()
            return int(cur.lastrowid)

    def _insert_refresh_log(self, account_id: int, account_email: str, status: str):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                "INSERT INTO account_refresh_logs (account_id, account_email, status, error_message) VALUES (?, ?, ?, ?)",
                (account_id, account_email, status, "error" if status == "failed" else ""),
            )
            db.commit()

    def test_reveal_password(self):
        client = self.app.test_client()
        self._login(client)

        acc_pwd = self._insert_account("has-pwd@test.com", "active", password="secret_pwd")
        acc_imap = self._insert_account("has-imap@test.com", "active", password="", imap_password="secret_imap")
        acc_none = self._insert_account("no-pwd@test.com", "active", password="", imap_password="")

        # Test Outlook password
        resp = client.post(f"/api/accounts/{acc_pwd}/reveal-password")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["password"], "secret_pwd")

        # Test IMAP password fallback
        resp = client.post(f"/api/accounts/{acc_imap}/reveal-password")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["password"], "secret_imap")

        # Test no password
        resp = client.post(f"/api/accounts/{acc_none}/reveal-password")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["error"]["code"], "NO_PASSWORD")

    def test_list_accounts_refresh_status_filter(self):
        client = self.app.test_client()
        self._login(client)

        acc1 = self._insert_account("success@test.com", "active")
        self._insert_refresh_log(acc1, "success@test.com", "success")

        acc2 = self._insert_account("failed@test.com", "active")
        self._insert_refresh_log(acc2, "failed@test.com", "failed")

        acc3 = self._insert_account("no-log@test.com", "active")

        # Test failed filter
        resp = client.get("/api/accounts?group_id=1&refresh_status=failed")
        accounts = resp.get_json()["accounts"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["email"], "failed@test.com")
        self.assertEqual(accounts[0]["last_refresh_status"], "failed")

    def test_list_accounts_alias_filter(self):
        client = self.app.test_client()
        self._login(client)

        has_alias_id = self._insert_account("has-alias@test.com", "active")
        no_alias_id = self._insert_account("no-alias@test.com", "active")
        never_scanned_id = self._insert_account("never-scanned@test.com", "active")

        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                "UPDATE accounts SET alias_used_count = ?, alias_soft_limit = 5, alias_scanned_at = ? WHERE id = ?",
                (3, "2026-07-01 10:00:00", has_alias_id),
            )
            db.execute(
                "UPDATE accounts SET alias_used_count = ?, alias_soft_limit = 5, alias_scanned_at = ? WHERE id = ?",
                (0, "2026-07-01 10:00:00", no_alias_id),
            )
            db.execute(
                "UPDATE accounts SET alias_used_count = NULL, alias_scanned_at = NULL WHERE id = ?",
                (never_scanned_id,),
            )
            db.commit()

        resp = client.get("/api/accounts?group_id=1&alias_filter=has")
        self.assertEqual(resp.status_code, 200)
        has_accounts = resp.get_json()["accounts"]
        self.assertEqual(len(has_accounts), 1)
        self.assertEqual(has_accounts[0]["email"], "has-alias@test.com")

        # "none" = scanned with zero aliases (+0), not never-scanned.
        resp = client.get("/api/accounts?group_id=1&alias_filter=none")
        self.assertEqual(resp.status_code, 200)
        none_accounts = resp.get_json()["accounts"]
        self.assertEqual([account["email"] for account in none_accounts], ["no-alias@test.com"])

        # "synced" = any scanned account (numeric badge: +0 or +N).
        resp = client.get("/api/accounts?group_id=1&alias_filter=synced")
        self.assertEqual(resp.status_code, 200)
        synced_emails = sorted(account["email"] for account in resp.get_json()["accounts"])
        self.assertEqual(synced_emails, ["has-alias@test.com", "no-alias@test.com"])

        # "unsynced" = never scanned (bare + badge).
        resp = client.get("/api/accounts?group_id=1&alias_filter=unsynced")
        self.assertEqual(resp.status_code, 200)
        unsynced_accounts = resp.get_json()["accounts"]
        self.assertEqual([account["email"] for account in unsynced_accounts], ["never-scanned@test.com"])


if __name__ == "__main__":
    unittest.main()
