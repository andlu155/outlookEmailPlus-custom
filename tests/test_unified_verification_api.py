"""ZER-90: unified /verification API contract tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class UnifiedVerificationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
        self.client = self.app.test_client()

    def _login(self):
        resp = self.client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)

    def _get_with_outlook_account(self, path: str):
        with patch("outlook_web.controllers.emails.accounts_repo.get_account_by_email") as mock_account:
            mock_account.return_value = {
                "id": 1,
                "email": "demo@example.com",
                "account_type": "outlook",
                "client_id": "cid",
                "refresh_token": "rt",
            }
            with patch(
                "outlook_web.controllers.emails.compact_summary_service.update_summary_from_verification"
            ) as mock_summary:
                mock_summary.return_value = {"latest_verification_code": "Ab12Cd"}
                return self.client.get(path)

    @patch("outlook_web.controllers.emails.external_api_service.get_verification_result")
    def test_verification_field_code_passes_expected_field_and_shapes_response(self, mock_get_result):
        self._login()
        mock_get_result.return_value = {
            "verification_code": "Ab12Cd",
            "verification_link": "https://example.com/verify",
            "formatted": "Ab12Cd https://example.com/verify",
            "code_confidence": "high",
            "link_confidence": "high",
            "confidence": "high",
            "folder": "inbox",
            "matched_email_id": "msg-1",
            "subject": "Code",
            "from": "security@example.com",
            "received_at": "2026-03-20T10:00:00Z",
        }

        resp = self._get_with_outlook_account(
            "/api/emails/demo@example.com/verification?field=code&code_length=6-6&code_source=content"
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        data = payload.get("data") or {}
        self.assertTrue(payload.get("success"))
        self.assertEqual(data.get("verification_code"), "Ab12Cd")
        self.assertIsNone(data.get("verification_link"))
        self.assertEqual(data.get("formatted"), "Ab12Cd")
        self.assertEqual(mock_get_result.call_args.kwargs.get("expected_field"), "verification_code")
        self.assertEqual(mock_get_result.call_args.kwargs.get("code_length"), "6-6")
        self.assertEqual(mock_get_result.call_args.kwargs.get("code_source"), "content")

    @patch("outlook_web.controllers.emails.external_api_service.get_verification_result")
    def test_verification_field_code_requires_code_after_shaping(self, mock_get_result):
        self._login()
        mock_get_result.return_value = {
            "verification_code": None,
            "verification_link": "https://example.com/verify",
            "formatted": "https://example.com/verify",
            "code_confidence": "low",
            "link_confidence": "high",
            "confidence": "high",
        }

        resp = self._get_with_outlook_account("/api/emails/demo@example.com/verification?field=code")

        self.assertEqual(resp.status_code, 404)
        payload = resp.get_json() or {}
        self.assertFalse(payload.get("success"))
        self.assertEqual(mock_get_result.call_args.kwargs.get("expected_field"), "verification_code")

    @patch("outlook_web.controllers.emails.external_api_service.get_verification_result")
    def test_verification_field_link_passes_expected_field_and_shapes_response(self, mock_get_result):
        self._login()
        mock_get_result.return_value = {
            "verification_code": "123456",
            "verification_link": "https://example.com/verify",
            "formatted": "123456 https://example.com/verify",
            "code_confidence": "high",
            "link_confidence": "high",
            "confidence": "high",
        }

        resp = self._get_with_outlook_account("/api/emails/demo@example.com/verification?field=link")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        data = payload.get("data") or {}
        self.assertIsNone(data.get("verification_code"))
        self.assertEqual(data.get("verification_link"), "https://example.com/verify")
        self.assertEqual(data.get("formatted"), "https://example.com/verify")
        self.assertEqual(mock_get_result.call_args.kwargs.get("expected_field"), "verification_link")

    @patch("outlook_web.controllers.emails.external_api_service.get_verification_result")
    def test_verification_invalid_field_returns_400_without_extracting(self, mock_get_result):
        self._login()

        resp = self._get_with_outlook_account("/api/emails/demo@example.com/verification?field=otp")

        self.assertEqual(resp.status_code, 400)
        mock_get_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
