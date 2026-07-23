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
            db.execute("DELETE FROM groups")
            db.execute("INSERT INTO groups (id, name) VALUES (1, 'Test Group')")
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


if __name__ == "__main__":
    unittest.main()
