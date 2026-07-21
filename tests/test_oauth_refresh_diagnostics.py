from __future__ import annotations

import json
import unittest
import uuid
from unittest.mock import Mock, patch

from outlook_web.services.graph import test_refresh_token_with_rotation
from tests._import_app import clear_login_attempts, import_web_app_module


class OAuthRefreshDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        self.client = self.app.test_client()
        login = self.client.post("/login", json={"password": "testpass123"})
        self.assertEqual(login.status_code, 200)
        self.account_id = self._insert_account()

    def _insert_account(self) -> int:
        self.account_email = f"diagnostic-{uuid.uuid4().hex}@example.com"
        conn = self.module.create_sqlite_connection()
        try:
            row = conn.execute("SELECT id FROM groups WHERE name = '默认分组' LIMIT 1").fetchone()
            cursor = conn.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    account_type, provider, group_id, remark, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.account_email,
                    "",
                    "12345678-1234-1234-1234-123456789abc",
                    self.module.encrypt_data("refresh-token-for-test"),
                    "outlook",
                    "outlook",
                    row["id"],
                    "",
                    "active",
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _insert_refresh_run(self, *, run_id: str, trace_id: str):
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO refresh_runs (
                    id, trigger_source, status, total, success_count, failed_count, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, "manual_all", "failed", 1, 0, 1, trace_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _insert_refresh_log(self, *, run_id: str, error_message: str):
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                """
                INSERT INTO account_refresh_logs (
                    account_id, account_email, refresh_type, status, error_message, run_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (self.account_id, self.account_email, "manual_all", "failed", error_message, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_refresh_failure_returns_sanitized_structured_diagnostic(self):
        response = Mock(status_code=400)
        response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "refresh_token=SECRET_TOKEN was revoked",
        }

        with patch("outlook_web.services.graph.requests.post", return_value=response):
            ok, error_message, new_token = test_refresh_token_with_rotation(
                "12345678-1234-1234-1234-123456789abc",
                "SECRET_TOKEN",
            )

        self.assertFalse(ok)
        self.assertIsNone(new_token)
        self.assertTrue(error_message.startswith("oauth_refresh_diagnostic:"))
        diagnostic = json.loads(error_message.split(":", 1)[1])
        self.assertEqual(diagnostic["http_status"], 400)
        self.assertEqual(diagnostic["oauth_error"], "invalid_grant")
        self.assertEqual(diagnostic["tenant"], "common")
        self.assertEqual(diagnostic["client_id_hint"], "12345678...")
        self.assertNotIn("SECRET_TOKEN", error_message)
        self.assertNotIn("12345678-1234-1234-1234-123456789abc", error_message)

    def test_account_refresh_logs_include_trace_id_from_refresh_run(self):
        self._insert_refresh_run(run_id="run-oauth-diagnostic", trace_id="trace-oauth-diagnostic")
        self._insert_refresh_log(run_id="run-oauth-diagnostic", error_message="oauth_refresh_diagnostic:{}")

        response = self.client.get(f"/api/accounts/{self.account_id}/refresh-logs")

        self.assertEqual(response.status_code, 200)
        log = response.get_json()["logs"][0]
        self.assertEqual(log["run_id"], "run-oauth-diagnostic")
        self.assertEqual(log["trace_id"], "trace-oauth-diagnostic")
