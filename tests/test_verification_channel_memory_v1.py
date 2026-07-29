import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class VerificationChannelMemoryV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db
            from outlook_web.repositories import settings as settings_repo

            db = get_db()
            db.execute("DELETE FROM accounts WHERE email LIKE '%@vcm.test'")
            db.execute("DELETE FROM external_api_keys")
            db.execute("DELETE FROM external_api_consumer_usage_daily")
            db.execute("DELETE FROM external_upstream_probes")
            db.execute("DELETE FROM external_probe_cache")
            db.commit()
            settings_repo.set_setting("external_api_key", "")

    @staticmethod
    def _auth_headers(value: str = "abc123"):
        return {"X-API-Key": value}

    @staticmethod
    def _utc_iso(minutes_delta: int = 0) -> str:
        dt = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=minutes_delta)
        return dt.isoformat().replace("+00:00", "Z")

    def _insert_outlook_account(self, *, preferred_channel: str | None = None) -> str:
        email_addr = f"{uuid.uuid4().hex}@vcm.test"
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, group_id, status,
                    account_type, provider, preferred_verification_channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "pw",
                    "cid-test",
                    "rt-test",
                    1,
                    "active",
                    "outlook",
                    "outlook",
                    preferred_channel,
                ),
            )
            db.commit()
        return email_addr

    def _insert_imap_account(self, *, preferred_channel: str | None = None) -> str:
        email_addr = f"{uuid.uuid4().hex}@vcm.test"
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, group_id, status,
                    account_type, provider, imap_host, imap_port, imap_password,
                    preferred_verification_channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_addr,
                    "pw",
                    "cid-test",
                    "rt-test",
                    1,
                    "active",
                    "imap",
                    "custom",
                    "imap.test.com",
                    993,
                    "imap-pass",
                    preferred_channel,
                ),
            )
            db.commit()
        return email_addr

    def _get_preferred_channel(self, email_addr: str) -> str | None:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            row = db.execute(
                "SELECT preferred_verification_channel FROM accounts WHERE email = ?",
                (email_addr,),
            ).fetchone()
            if not row:
                return None
            value = row["preferred_verification_channel"]
            return str(value) if value is not None else None

    def _set_external_api_key(self, value: str):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("external_api_key", value)

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    @classmethod
    def _graph_email(
        cls,
        *,
        message_id: str = "msg-1",
        subject: str = "Your verification code",
        sender: str = "noreply@example.com",
        received_at: str | None = None,
    ):
        return {
            "id": message_id,
            "subject": subject,
            "from": {"emailAddress": {"address": sender}},
            "receivedDateTime": received_at or cls._utc_iso(),
            "isRead": False,
            "hasAttachments": False,
            "bodyPreview": "Your code is 123456",
        }

    @classmethod
    def _graph_detail(cls, *, body_text: str = "Your code is 123456"):
        return {
            "id": "msg-1",
            "subject": "Your verification code",
            "from": {"emailAddress": {"address": "noreply@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "user@outlook.com"}}],
            "receivedDateTime": cls._utc_iso(),
            "body": {"content": body_text, "contentType": "text"},
        }

    def test_expected_field_code_skips_newer_link_only_message(self):
        with self.app.app_context():
            from outlook_web.services import verification_channel_routing as vcr

            fake_account = {
                "id": 10,
                "email": "expected@outlook.com",
                "account_type": "outlook",
                "provider": "outlook",
                "group_id": None,
                "preferred_verification_channel": None,
                "client_id": "cid",
                "refresh_token": "rt",
            }
            emails = [
                {
                    "id": "link-msg",
                    "subject": "Verify with link",
                    "date": "2026-04-19T10:01:00Z",
                    "receivedDateTime": "2026-04-19T10:01:00Z",
                    "folder": "inbox",
                    "_verification_channel": "graph_inbox",
                    "body_preview": "Click the verification link",
                },
                {
                    "id": "code-msg",
                    "subject": "Your code",
                    "date": "2026-04-19T10:00:00Z",
                    "receivedDateTime": "2026-04-19T10:00:00Z",
                    "folder": "inbox",
                    "_verification_channel": "graph_inbox",
                    "body_preview": "Your code is 123456",
                },
            ]

            def detail_for_message(*, message_id: str, **_kwargs):
                body_text = (
                    "Use this verification link: https://verify.example/link"
                    if message_id == "link-msg"
                    else "Your verification code is 123456"
                )
                return {
                    "id": message_id,
                    "subject": "Verification",
                    "from": {"emailAddress": {"address": "noreply@example.com"}},
                    "receivedDateTime": "2026-04-19T10:00:00Z",
                    "body": {"content": body_text, "contentType": "text"},
                }

            with (
                patch.object(vcr, "build_verification_channel_plan", return_value=["graph_inbox"]),
                patch.object(vcr.channel_capability_cache, "filter_channel_plan", return_value=["graph_inbox"]),
                patch.object(
                    vcr,
                    "fetch_emails_for_channel",
                    return_value={"success": True, "emails": emails},
                ),
                patch.object(vcr, "fetch_email_detail_for_channel", side_effect=detail_for_message) as mock_detail,
                patch(
                    "outlook_web.services.graph.get_access_token_graph_result",
                    return_value={"success": True, "scope": "Mail.Read"},
                ),
                patch("outlook_web.services.graph.has_mail_read_permission", return_value=True),
            ):
                result = vcr.extract_verification_for_outlook(
                    account=fake_account,
                    resolved_policy={"code_regex": None, "code_length": "6-6"},
                    code_source="all",
                    expected_field="verification_code",
                )

            self.assertTrue(result.get("success"))
            self.assertEqual((result.get("data") or {}).get("matched_email_id"), "code-msg")
            self.assertEqual((result.get("data") or {}).get("verification_code"), "123456")
            self.assertEqual(mock_detail.call_count, 2)

    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_external_prefers_remembered_channel(
        self,
        mock_imap_fetch,
        mock_graph_list,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")
        self._set_external_api_key("abc123")

        imap_detail = {
            "id": "imap-msg-1",
            "subject": "Verify now",
            "from": "noreply@example.com",
            "date": self._utc_iso(),
            "body": "Your code is 654321",
        }
        imap_result = {
            "success": True,
            "emails": [
                {
                    "id": "imap-msg-1",
                    "subject": "Verify now",
                    "from": "noreply@example.com",
                    "date": self._utc_iso(),
                    "folder": "inbox",
                    "_verification_channel": "imap_new",
                    "body_preview": "code 654321",
                }
            ],
            "detail": imap_detail,
        }
        mock_imap_fetch.side_effect = [imap_result, {"success": True, "emails": []}]

        client = self.app.test_client()
        resp = client.get(
            f"/api/external/verification-code?email={email_addr}",
            headers=self._auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "654321")
        self.assertNotIn("_matched_channel", resp.get_json().get("data", {}))
        mock_graph_list.assert_not_called()
        self.assertEqual([call.kwargs.get("folder") for call in mock_imap_fetch.call_args_list], ["inbox", "junkemail"])
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_new")

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    def test_external_empty_or_invalid_preferred_checks_graph_folders(
        self,
        mock_imap_list,
        mock_graph_list,
        mock_graph_detail,
    ):
        self._set_external_api_key("abc123")
        client = self.app.test_client()

        for preferred in (None, "unknown_channel"):
            with self.subTest(preferred=preferred):
                email_addr = self._insert_outlook_account(preferred_channel=preferred)

                mock_graph_list.reset_mock()
                mock_graph_detail.reset_mock()
                mock_imap_list.reset_mock()

                mock_graph_list.side_effect = [
                    {
                        "success": True,
                        "emails": [
                            self._graph_email(
                                message_id=f"msg-inbox-{preferred or 'none'}",
                                received_at=self._utc_iso(minutes_delta=-1),
                            )
                        ],
                    },
                    {
                        "success": True,
                        "emails": [
                            self._graph_email(
                                message_id=f"msg-junk-{preferred or 'none'}",
                                received_at=self._utc_iso(),
                            )
                        ],
                    },
                ]
                mock_graph_detail.return_value = self._graph_detail(body_text="Your code is 321654")
                mock_imap_list.return_value = {"success": False, "error": {"message": "imap unavailable"}}

                resp = client.get(
                    f"/api/external/verification-code?email={email_addr}",
                    headers=self._auth_headers(),
                )

                self.assertEqual(resp.status_code, 200)
                data = resp.get_json().get("data", {})
                self.assertEqual(data.get("verification_code"), "321654")
                self.assertNotIn("_matched_channel", data)

                self.assertEqual(
                    [call.kwargs.get("folder") for call in mock_graph_list.call_args_list],
                    ["inbox", "junkemail"],
                )
                self.assertEqual(self._get_preferred_channel(email_addr), "graph_junk")

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_external_fallback_overwrites_channel(
        self,
        mock_imap_fetch,
        mock_graph_list,
        _mock_graph_detail,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="graph_junk")
        self._set_external_api_key("abc123")

        mock_graph_list.side_effect = [
            {"success": False, "error": {"message": "graph junk failed"}},
            {"success": False, "error": {"message": "graph inbox failed"}},
        ]

        imap_old_detail = {
            "id": "imap-old-1",
            "subject": "Legacy code",
            "from": "legacy@example.com",
            "date": self._utc_iso(),
            "body": "Use code 987654",
        }

        def _imap_side_effect(*_args, **kwargs):
            if kwargs.get("channel") == "imap_new":
                return {"success": False, "error": {"message": "imap new failed"}}
            if kwargs.get("folder") == "junkemail":
                return {"success": True, "emails": []}
            return {
                "success": True,
                "emails": [
                    {
                        "id": "imap-old-1",
                        "subject": "Legacy code",
                        "from": "legacy@example.com",
                        "date": self._utc_iso(),
                        "folder": "inbox",
                        "_verification_channel": "imap_old",
                        "body_preview": "old server code",
                    }
                ],
                "detail": imap_old_detail,
            }

        mock_imap_fetch.side_effect = _imap_side_effect

        client = self.app.test_client()
        resp = client.get(
            f"/api/external/verification-code?email={email_addr}",
            headers=self._auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "987654")
        self.assertNotIn("_matched_channel", resp.get_json().get("data", {}))
        self.assertEqual(
            [(call.kwargs.get("channel"), call.kwargs.get("folder")) for call in mock_imap_fetch.call_args_list],
            [("imap_new", "inbox"), ("imap_new", "junkemail"), ("imap_old", "inbox"), ("imap_old", "junkemail")],
        )
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_old")

    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_external_failure_keeps_channel(
        self,
        mock_imap_fetch,
        mock_graph_list,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")
        self._set_external_api_key("abc123")

        mock_graph_list.return_value = {
            "success": False,
            "error": {"message": "graph failed"},
        }
        mock_imap_fetch.return_value = {
            "success": False,
            "error": {"message": "imap failed"},
        }

        client = self.app.test_client()
        resp = client.get(
            f"/api/external/verification-code?email={email_addr}",
            headers=self._auth_headers(),
        )

        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.get_json().get("code"), "UPSTREAM_READ_FAILED")
        self.assertEqual([call.kwargs.get("folder") for call in mock_imap_fetch.call_args_list], ["inbox", "junkemail"])
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_new")

    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_web_prefers_remembered_channel(
        self,
        mock_imap_fetch,
        mock_graph_list,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")

        imap_detail = {
            "id": "imap-web-1",
            "subject": "Web verify",
            "from": "web@example.com",
            "date": self._utc_iso(),
            "body": "Your verification code is 112233",
        }
        imap_result = {
            "success": True,
            "emails": [
                {
                    "id": "imap-web-1",
                    "subject": "Web verify",
                    "from": "web@example.com",
                    "date": self._utc_iso(),
                    "folder": "inbox",
                    "_verification_channel": "imap_new",
                    "body_preview": "web code",
                }
            ],
            "detail": imap_detail,
        }
        mock_imap_fetch.side_effect = [imap_result, {"success": True, "emails": []}]

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}/extract-verification")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "112233")
        mock_graph_list.assert_not_called()
        self.assertEqual([call.kwargs.get("folder") for call in mock_imap_fetch.call_args_list], ["inbox", "junkemail"])
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_new")

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_web_fallback_overwrites_channel(
        self,
        mock_imap_fetch,
        mock_graph_list,
        _mock_graph_detail,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="graph_junk")
        _mock_graph_detail.return_value = self._graph_detail(body_text="Use code 778899")

        mock_graph_list.side_effect = [
            {"success": False, "error": {"message": "graph junk failed"}},
            {"success": False, "error": {"message": "graph inbox failed"}},
        ]

        imap_old_detail = {
            "id": "imap-old-web-1",
            "subject": "Legacy web code",
            "from": "legacy@example.com",
            "date": self._utc_iso(),
            "body": "Use code 778899",
        }

        def _imap_side_effect(*_args, **kwargs):
            if kwargs.get("channel") == "imap_new":
                return {"success": False, "error": {"message": "imap new failed"}}
            if kwargs.get("folder") == "junkemail":
                return {"success": True, "emails": []}
            return {
                "success": True,
                "emails": [
                    {
                        "id": "imap-old-web-1",
                        "subject": "Legacy web code",
                        "from": "legacy@example.com",
                        "date": self._utc_iso(),
                        "folder": "inbox",
                        "_verification_channel": "imap_old",
                        "body_preview": "old server code",
                    }
                ],
                "detail": imap_old_detail,
            }

        mock_imap_fetch.side_effect = _imap_side_effect

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}/extract-verification")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "778899")
        self.assertEqual(
            [(call.kwargs.get("channel"), call.kwargs.get("folder")) for call in mock_imap_fetch.call_args_list],
            [("imap_new", "inbox"), ("imap_new", "junkemail"), ("imap_old", "inbox"), ("imap_old", "junkemail")],
        )
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_old")

    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_web_failure_keeps_channel(self, mock_imap_fetch, mock_graph_list):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")

        mock_graph_list.return_value = {
            "success": False,
            "error": {"message": "graph failed"},
        }
        mock_imap_fetch.return_value = {
            "success": False,
            "error": {"message": "imap failed"},
        }

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}/extract-verification")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json().get("error", {}).get("code"), "EMAIL_NOT_FOUND")
        self.assertEqual([call.kwargs.get("folder") for call in mock_imap_fetch.call_args_list], ["inbox", "junkemail"])
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_new")

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.verification_channel_routing.fetch_emails_and_detail_for_channel")
    def test_external_verification_link_prefers_memory_and_no_private_field(
        self,
        mock_imap_fetch,
        mock_graph_list,
        _mock_graph_detail,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")
        self._set_external_api_key("abc123")

        imap_detail = {
            "id": "imap-link-1",
            "subject": "Please verify your account",
            "from": "noreply@example.com",
            "date": self._utc_iso(),
            "body": "Click https://example.com/verify?token=abc",
        }
        imap_result = {
            "success": True,
            "emails": [
                {
                    "id": "imap-link-1",
                    "subject": "Please verify your account",
                    "from": "noreply@example.com",
                    "date": self._utc_iso(),
                    "folder": "inbox",
                    "_verification_channel": "imap_new",
                    "body_preview": "verify link",
                }
            ],
            "detail": imap_detail,
        }
        mock_imap_fetch.side_effect = [imap_result, {"success": True, "emails": []}]

        client = self.app.test_client()
        resp = client.get(
            f"/api/external/verification-link?email={email_addr}",
            headers=self._auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json().get("data", {})
        self.assertIn("verify", data.get("verification_link", ""))
        self.assertNotIn("_matched_channel", data)
        mock_graph_list.assert_not_called()
        self.assertEqual([call.kwargs.get("folder") for call in mock_imap_fetch.call_args_list], ["inbox", "junkemail"])

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    def test_external_folder_explicit_bypasses_memory(
        self,
        mock_imap_list,
        mock_graph_list,
        mock_graph_detail,
    ):
        email_addr = self._insert_outlook_account(preferred_channel="imap_new")
        self._set_external_api_key("abc123")

        mock_graph_list.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "graph-deleted-1",
                    "subject": "Deleted folder code",
                    "from": {"emailAddress": {"address": "noreply@example.com"}},
                    "receivedDateTime": self._utc_iso(),
                    "isRead": False,
                    "hasAttachments": False,
                    "bodyPreview": "code 445566",
                }
            ],
        }
        mock_graph_detail.return_value = {
            "id": "graph-deleted-1",
            "subject": "Deleted folder code",
            "from": {"emailAddress": {"address": "noreply@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "user@outlook.com"}}],
            "receivedDateTime": self._utc_iso(),
            "body": {"content": "Your code is 445566", "contentType": "text"},
        }

        client = self.app.test_client()
        resp = client.get(
            f"/api/external/verification-code?email={email_addr}&folder=deleteditems",
            headers=self._auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "445566")
        # 显式 folder 时应走旧逻辑，仍会调用 graph，且不走 imap memory 快路径
        self.assertTrue(mock_graph_list.called)
        mock_imap_list.assert_not_called()

    @patch("outlook_web.services.graph.get_email_detail_graph")
    @patch("outlook_web.services.graph.get_emails_graph")
    def test_web_empty_preferred_keeps_existing_behavior(self, mock_graph_list, mock_graph_detail):
        email_addr = self._insert_outlook_account(preferred_channel=None)

        mock_graph_list.return_value = {
            "success": True,
            "emails": [self._graph_email()],
        }
        mock_graph_detail.return_value = self._graph_detail(body_text="Your code is 123456")

        client = self.app.test_client()
        self._login(client)
        resp = client.get(f"/api/emails/{email_addr}/extract-verification")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("data", {}).get("verification_code"), "123456")
        self.assertEqual(self._get_preferred_channel(email_addr), "graph_inbox")

    @patch("outlook_web.services.graph.get_emails_graph")
    @patch("outlook_web.services.imap.get_email_detail_imap_with_server")
    @patch("outlook_web.services.imap.get_emails_imap_with_server")
    def test_imap_generic_account_not_using_channel_memory(
        self,
        mock_imap_list,
        _mock_imap_detail,
        mock_graph_list,
    ):
        email_addr = self._insert_imap_account(preferred_channel="imap_old")

        mock_imap_list.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "imap-1",
                    "subject": "Generic IMAP",
                    "from": "imap@example.com",
                    "date": self._utc_iso(),
                    "body_preview": "noop",
                }
            ],
        }

        client = self.app.test_client()
        self._set_external_api_key("abc123")
        resp = client.get(
            f"/api/external/verification-code?email={email_addr}",
            headers=self._auth_headers(),
        )

        self.assertIn(resp.status_code, (200, 404, 502))
        mock_graph_list.assert_not_called()
        # generic imap 路径不应改写此字段
        self.assertEqual(self._get_preferred_channel(email_addr), "imap_old")


if __name__ == "__main__":
    unittest.main()
