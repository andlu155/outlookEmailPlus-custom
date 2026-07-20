from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class WebGraphAuthFallbackTests(unittest.TestCase):
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
        self.assertTrue(resp.get_json().get("success"))

    def _insert_outlook_account(self, email_addr: str):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, status, account_type, provider
                ) VALUES (?, 'pw', 'cid-test', 'rt-test', 1, 'active', 'outlook', 'outlook')
                """,
                (email_addr,),
            )
            db.commit()

    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    @patch("outlook_web.services.graph.get_emails_graph")
    def test_get_emails_graph_401_still_fallback_to_imap(
        self,
        mock_graph_list,
        mock_imap_list,
    ):
        email_addr = "fallback_read@example.com"
        self._insert_outlook_account(email_addr)

        mock_graph_list.return_value = {
            "success": False,
            "auth_expired": True,
            "error": {
                "code": "EMAIL_FETCH_FAILED",
                "type": "GraphAPIError",
                "status": 401,
                "message": "graph unauthorized",
            },
        }
        mock_imap_list.side_effect = [
            {
                "success": True,
                "emails": [
                    {
                        "id": "imap-msg-1",
                        "subject": "via imap",
                        "from": "noreply@example.com",
                        "date": "2030-01-01T00:00:00Z",
                        "is_read": False,
                        "has_attachments": False,
                        "body_preview": "hello",
                    }
                ],
            }
        ]

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("method"), "IMAP (New)")
        self.assertTrue(mock_imap_list.called)

    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    @patch("outlook_web.services.graph.get_emails_graph")
    def test_get_emails_returns_auth_expired_only_after_all_fallbacks_fail(
        self,
        mock_graph_list,
        mock_imap_list,
    ):
        email_addr = "fallback_fail@example.com"
        self._insert_outlook_account(email_addr)

        mock_graph_list.return_value = {
            "success": False,
            "auth_expired": True,
            "error": {
                "code": "EMAIL_FETCH_FAILED",
                "type": "GraphAPIError",
                "status": 401,
                "message": "graph unauthorized",
            },
        }
        mock_imap_list.side_effect = [
            {
                "success": False,
                "error": {"code": "IMAP_AUTH_FAILED", "message": "new fail"},
            },
            {
                "success": False,
                "error": {"code": "IMAP_AUTH_FAILED", "message": "old fail"},
            },
        ]

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")

        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("error", {}).get("code"), "ACCOUNT_AUTH_EXPIRED")
        self.assertEqual(mock_imap_list.call_count, 2)

    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    @patch("outlook_web.services.graph.get_emails_graph")
    def test_auth_expired_response_hides_upstream_oauth_description(
        self,
        mock_graph_list,
        mock_imap_list,
    ):
        email_addr = "fallback_private@example.com"
        self._insert_outlook_account(email_addr)
        mock_graph_list.return_value = {
            "success": False,
            "auth_expired": True,
            "error": {
                "details": "oauth_refresh_diagnostic:{\"oauth_error_description\":\"SECRET_DETAIL\"}",
            },
        }
        mock_imap_list.return_value = {
            "success": False,
            "error": {"code": "IMAP_AUTH_FAILED", "message": "imap failed"},
        }

        client = self.app.test_client()
        self._login(client)
        response = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")

        self.assertEqual(response.status_code, 401)
        body = response.get_json()
        self.assertEqual(body["error"]["code"], "ACCOUNT_AUTH_EXPIRED")
        self.assertNotIn("SECRET_DETAIL", response.get_data(as_text=True))
        self.assertTrue(body["trace_id"])


if __name__ == "__main__":
    unittest.main()
