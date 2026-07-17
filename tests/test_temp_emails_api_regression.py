from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TempEmailsApiRegressionTests(unittest.TestCase):
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
            db.execute("DELETE FROM temp_email_messages")
            db.execute("DELETE FROM temp_emails")
            db.commit()
            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_domains", "[]")
            settings_repo.set_setting("temp_mail_default_domain", "")
            settings_repo.set_setting(
                "temp_mail_prefix_rules",
                '{"min_length":1,"max_length":32,"pattern":"^[a-z0-9][a-z0-9._-]*$"}',
            )

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _insert_temp_email(self, email_addr: str):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                "INSERT INTO temp_emails (email, status) VALUES (?, 'active')",
                (email_addr,),
            )
            db.commit()

    def _insert_temp_email_message(
        self,
        *,
        email_addr: str,
        message_id: str,
        subject: str = "Your verification code",
        content: str = "Your code is 123456",
        timestamp: int = 1772407200,
    ):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute(
                """
                INSERT INTO temp_email_messages
                (message_id, email_address, from_address, subject, content, html_content, has_html, timestamp, raw_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    email_addr,
                    "sender@example.com",
                    subject,
                    content,
                    "",
                    0,
                    timestamp,
                    "{}",
                ),
            )
            db.commit()

    def test_generate_temp_email_forwards_prefix_and_domain_and_persists_mailbox(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"temp_{uuid.uuid4().hex}@temp.example"

        with patch(
            "outlook_web.services.gptmail.generate_temp_email",
            return_value=(email_addr, None),
        ) as generate_mock:
            resp = client.post(
                "/api/temp-emails/generate",
                json={"prefix": "alpha", "domain": "temp.example"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["email"], email_addr)
        generate_mock.assert_called_once_with("alpha", "temp.example")

        listing = client.get("/api/temp-emails")
        self.assertEqual(listing.status_code, 200)
        emails = listing.get_json()["emails"]
        self.assertIn(email_addr, [item["email"] for item in emails])

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            mailbox = temp_emails_repo.get_temp_email_by_address(email_addr)
            self.assertIsNotNone(mailbox)
            assert mailbox is not None
            self.assertEqual(mailbox["source"], "custom_domain_temp_mail")

    def test_generate_temp_email_returns_structured_error_when_provider_fails(self):
        client = self.app.test_client()
        self._login(client)

        with patch(
            "outlook_web.services.gptmail.generate_temp_email",
            return_value=(None, "domain unavailable"),
        ):
            resp = client.post(
                "/api/temp-emails/generate",
                json={"prefix": "alpha", "domain": "bad.example"},
            )

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_CREATE_FAILED")
        self.assertIn("domain unavailable", data["error"]["message"])

    def test_generate_temp_email_includes_sanitized_provider_error_detail(self):
        client = self.app.test_client()
        self._login(client)

        from outlook_web.services.temp_mail_service import TempMailError

        with patch(
            "outlook_web.controllers.temp_emails.temp_mail_service.generate_user_mailbox",
            side_effect=TempMailError(
                "UPSTREAM_BAD_PAYLOAD",
                "CF Worker 创建邮箱失败 HTTP 400",
                status=502,
                data={"error_detail": "Required field is missing"},
            ),
        ):
            resp = client.post("/api/temp-emails/generate", json={"prefix": "alpha"})

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertEqual(data["error"]["code"], "UPSTREAM_BAD_PAYLOAD")
        self.assertIn("Required field is missing", data["error"]["details"])
        self.assertTrue(data["error"]["trace_id"])

    def test_get_temp_email_messages_formats_remote_payload_and_caches_it(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"inbox_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        api_messages = [
            {
                "id": "msg-1",
                "from_address": "noreply@example.com",
                "subject": "Verify account",
                "content": "Code 123456",
                "timestamp": 1772407200,
                "has_html": False,
            }
        ]

        with patch(
            "outlook_web.services.gptmail.get_temp_emails_from_api",
            return_value=api_messages,
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["provider"], "custom_domain_temp_mail")
        self.assertEqual(data["method"], "Temp Mail")
        self.assertEqual(data["emails"][0]["id"], "msg-1")
        self.assertEqual(data["emails"][0]["from"], "noreply@example.com")
        self.assertEqual(data["emails"][0]["subject"], "Verify account")
        self.assertEqual(data["emails"][0]["body_preview"], "Code 123456")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            rows = temp_emails_repo.get_temp_email_messages(email_addr)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["message_id"], "msg-1")

    def test_get_temp_email_messages_returns_real_provider_name_from_mailbox(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"legacy_{uuid.uuid4().hex}@temp.example"
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                mailbox_type="user",
                visible_in_ui=True,
                source="legacy_gptmail",
            )

        with patch("outlook_web.services.gptmail.get_temp_emails_from_api", return_value=[]):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["provider"], "legacy_bridge")

    def test_get_temp_email_messages_returns_502_when_upstream_read_fails(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"listfail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            return_value={
                "success": False,
                "error": "API 请求超时",
                "error_type": "TIMEOUT_ERROR",
                "details": "request timed out",
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages")

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_UPSTREAM_READ_FAILED")

    def test_get_temp_email_messages_supports_cache_only_when_sync_remote_is_false(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"cacheonly_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(
            email_addr=email_addr,
            message_id="msg-cache-1",
            subject="Cached subject",
            content="Cached body",
            timestamp=1772407202,
        )

        # 强制把 provider 配置改成无效，确保若发生回源会直接失败。
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "unknown-provider")

        # 若实现正确（sync_remote=0），应仅返回本地缓存，不初始化 provider。
        resp = client.get(f"/api/temp-emails/{email_addr}/messages?sync_remote=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["emails"][0]["id"], "msg-cache-1")
        self.assertEqual(data["emails"][0]["subject"], "Cached subject")

    def test_get_temp_email_message_detail_returns_404_when_refresh_if_missing_is_false_and_cache_miss(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"detail_cacheonly_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        # refresh_if_missing=0：不允许回源补抓，缓存缺失必须返回 404。
        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            side_effect=Exception("should not call upstream when refresh_if_missing=0"),
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/msg-missing?refresh_if_missing=0")

        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_MESSAGE_NOT_FOUND")

    def test_get_temp_email_message_detail_refreshes_missing_cache_from_remote_api(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"detail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "msg-detail-1",
                "from_address": "sender@example.com",
                "subject": "Detail subject",
                "content": "Remote detail body",
                "html_content": "",
                "has_html": False,
                "timestamp": 1772407201,
            },
        ) as detail_mock:
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/msg-detail-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["email"]["id"], "msg-detail-1")
        self.assertEqual(data["email"]["body_type"], "text")
        self.assertEqual(data["email"]["body"], "Remote detail body")
        detail_mock.assert_called_once_with(email_addr, "msg-detail-1")

    def test_get_temp_email_message_detail_returns_502_when_upstream_read_fails(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"detailfail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            return_value={
                "success": False,
                "error": "临时邮箱服务暂时不可用",
                "error_type": "SERVER_ERROR",
                "details": "HTTP 503",
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/msg-detail-fail")

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_UPSTREAM_READ_FAILED")

    def test_delete_temp_email_message_removes_local_copy_after_remote_delete(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"delete_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-delete-1")

        with patch("outlook_web.services.gptmail.delete_temp_email_from_api", return_value=True) as delete_mock:
            resp = client.delete(f"/api/temp-emails/{email_addr}/messages/msg-delete-1")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        delete_mock.assert_called_once_with(email_addr, "msg-delete-1")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertIsNone(temp_emails_repo.get_temp_email_message_by_id("msg-delete-1"))

    def test_clear_temp_email_messages_clears_local_cache_and_returns_success(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"clear_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-clear-1")
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-clear-2")

        with patch("outlook_web.services.gptmail.clear_temp_emails_from_api", return_value=True) as clear_mock:
            resp = client.delete(f"/api/temp-emails/{email_addr}/clear")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        clear_mock.assert_called_once_with(email_addr)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertEqual(temp_emails_repo.get_temp_email_messages(email_addr), [])

    def test_refresh_temp_email_messages_returns_new_count_and_cached_messages(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"refresh_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        api_messages = [
            {
                "id": "msg-refresh-1",
                "from_address": "refresh@example.com",
                "subject": "Refresh subject",
                "content": "Refresh body",
                "timestamp": 1772407210,
                "has_html": False,
            }
        ]

        with patch(
            "outlook_web.services.gptmail.get_temp_emails_from_api",
            return_value=api_messages,
        ):
            resp = client.post(f"/api/temp-emails/{email_addr}/refresh")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["new_count"], 1)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["emails"][0]["id"], "msg-refresh-1")
        self.assertEqual(data["provider"], "custom_domain_temp_mail")
        self.assertEqual(data["method"], "Temp Mail")

    def test_refresh_temp_email_messages_returns_mailbox_provider_name(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"refresh_legacy_{uuid.uuid4().hex}@temp.example"
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                mailbox_type="user",
                visible_in_ui=True,
                source="legacy_gptmail",
            )

        with patch("outlook_web.services.gptmail.get_temp_emails_from_api", return_value=[]):
            resp = client.post(f"/api/temp-emails/{email_addr}/refresh")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["provider"], "legacy_bridge")

    def test_refresh_temp_email_messages_returns_502_when_upstream_read_fails(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"refreshfail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            return_value={
                "success": False,
                "error": "API 请求超时",
                "error_type": "TIMEOUT_ERROR",
                "details": "request timed out",
            },
        ):
            resp = client.post(f"/api/temp-emails/{email_addr}/refresh")

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_UPSTREAM_READ_FAILED")

    def test_temp_email_options_returns_structured_error_when_provider_options_unavailable(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "unknown-provider")

        resp = client.get("/api/temp-emails/options")

        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_MAIL_OPTIONS_UNAVAILABLE")

    def test_temp_email_options_supports_provider_name_query_param(self):
        """回归：/api/temp-emails/options 应支持按 provider_name 返回 options。"""
        client = self.app.test_client()
        self._login(client)

        # cloudflare_temp_mail provider 不依赖 temp_mail_provider 全局设置
        # 这里不要求 domains 一定非空，只验证接口能返回 success/options 结构。
        resp = client.get("/api/temp-emails/options?provider_name=cloudflare_temp_mail")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("options", data)
        self.assertEqual(data["options"].get("provider_name"), "cloudflare_temp_mail")

    def test_get_temp_emails_only_returns_visible_user_mailboxes(self):
        client = self.app.test_client()
        self._login(client)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="visible@temp.example",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )
            temp_emails_repo.create_temp_email(
                email_addr="hidden@temp.example",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token="tmptask_hidden",
                consumer_key="key:hidden",
                caller_id="worker-1",
                task_id="job-hidden",
            )

        resp = client.get("/api/temp-emails")

        self.assertEqual(resp.status_code, 200)
        emails = resp.get_json()["emails"]
        self.assertEqual([item["email"] for item in emails], ["visible@temp.example"])
        self.assertTrue(emails[0]["visible_in_ui"])

    def test_same_message_id_is_isolated_per_mailbox_for_detail_and_delete(self):
        client = self.app.test_client()
        self._login(client)

        email_a = "mailbox-a@temp.example"
        email_b = "mailbox-b@temp.example"
        self._insert_temp_email(email_a)
        self._insert_temp_email(email_b)
        self._insert_temp_email_message(
            email_addr=email_a,
            message_id="msg-shared",
            content="Mailbox A code 111111",
        )
        self._insert_temp_email_message(
            email_addr=email_b,
            message_id="msg-shared",
            content="Mailbox B code 222222",
        )

        detail_a = client.get(f"/api/temp-emails/{email_a}/messages/msg-shared")
        detail_b = client.get(f"/api/temp-emails/{email_b}/messages/msg-shared")
        self.assertEqual(detail_a.status_code, 200)
        self.assertEqual(detail_b.status_code, 200)
        self.assertIn("111111", detail_a.get_json()["email"]["body"])
        self.assertIn("222222", detail_b.get_json()["email"]["body"])

        with patch("outlook_web.services.gptmail.delete_temp_email_from_api", return_value=True):
            delete_resp = client.delete(f"/api/temp-emails/{email_a}/messages/msg-shared")

        self.assertEqual(delete_resp.status_code, 200)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertIsNone(temp_emails_repo.get_temp_email_message_by_id("msg-shared", email_addr=email_a))
            remaining = temp_emails_repo.get_temp_email_message_by_id("msg-shared", email_addr=email_b)

        self.assertIsNotNone(remaining)
        assert remaining is not None
        self.assertIn("222222", remaining["content"])

    def test_delete_temp_email_success_removes_mailbox_and_cached_messages(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"mailbox_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-mailbox-1")

        resp = client.delete(f"/api/temp-emails/{email_addr}")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertIsNone(temp_emails_repo.get_temp_email_by_address(email_addr))
            self.assertEqual(temp_emails_repo.get_temp_email_messages(email_addr), [])

    def test_delete_temp_email_message_keeps_local_copy_when_remote_delete_fails(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"deletefail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-delete-fail-1")

        with patch(
            "outlook_web.services.gptmail.delete_temp_email_from_api",
            return_value=False,
        ):
            resp = client.delete(f"/api/temp-emails/{email_addr}/messages/msg-delete-fail-1")

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_MESSAGE_DELETE_FAILED")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertIsNotNone(temp_emails_repo.get_temp_email_message_by_id("msg-delete-fail-1", email_addr=email_addr))

    def test_clear_temp_email_messages_keeps_local_cache_when_remote_clear_fails(self):
        client = self.app.test_client()
        self._login(client)

        email_addr = f"clearfail_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(email_addr)
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-clear-fail-1")
        self._insert_temp_email_message(email_addr=email_addr, message_id="msg-clear-fail-2")

        with patch(
            "outlook_web.services.gptmail.clear_temp_emails_from_api",
            return_value=False,
        ):
            resp = client.delete(f"/api/temp-emails/{email_addr}/clear")

        self.assertEqual(resp.status_code, 502)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMP_EMAIL_MESSAGES_CLEAR_FAILED")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertEqual(len(temp_emails_repo.get_temp_email_messages(email_addr)), 2)

    def test_message_detail_and_delete_are_scoped_by_mailbox_when_message_ids_collide(
        self,
    ):
        client = self.app.test_client()
        self._login(client)

        first_email = f"scope1_{uuid.uuid4().hex}@temp.example"
        second_email = f"scope2_{uuid.uuid4().hex}@temp.example"
        self._insert_temp_email(first_email)
        self._insert_temp_email(second_email)
        self._insert_temp_email_message(email_addr=first_email, message_id="shared-id", content="Body A")
        self._insert_temp_email_message(email_addr=second_email, message_id="shared-id", content="Body B")

        detail_resp = client.get(f"/api/temp-emails/{second_email}/messages/shared-id")
        self.assertEqual(detail_resp.status_code, 200)
        detail_data = detail_resp.get_json()
        self.assertEqual(detail_data["email"]["body"], "Body B")

        with patch("outlook_web.services.gptmail.delete_temp_email_from_api", return_value=True) as delete_mock:
            delete_resp = client.delete(f"/api/temp-emails/{first_email}/messages/shared-id")

        self.assertEqual(delete_resp.status_code, 200)
        delete_mock.assert_called_once_with(first_email, "shared-id")

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            self.assertIsNone(temp_emails_repo.get_temp_email_message_by_id("shared-id", email_addr=first_email))
            self.assertIsNotNone(temp_emails_repo.get_temp_email_message_by_id("shared-id", email_addr=second_email))
