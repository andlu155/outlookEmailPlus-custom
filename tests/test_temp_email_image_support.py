from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TempEmailImageSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.db import get_db

            db = get_db()
            db.execute("DELETE FROM temp_email_messages")
            db.execute("DELETE FROM temp_emails")
            db.commit()

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _insert_temp_email(self, email_addr: str) -> None:
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            db.execute("INSERT INTO temp_emails (email, status) VALUES (?, 'active')", (email_addr,))
            db.commit()

    def test_save_temp_email_messages_preserves_raw_payload_for_inline_images(self):
        self._insert_temp_email("inline@test.example")
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                "inline@test.example",
                [
                    {
                        "id": "temp-inline-1",
                        "from_address": "sender@example.com",
                        "subject": "inline",
                        "html_content": '<p><img src="cid:captcha-1"></p>',
                        "has_html": True,
                        "attachments": [
                            {
                                "content_id": "captcha-1",
                                "content_type": "image/png",
                                "content_base64": "QUJDRA==",
                                "is_inline": True,
                            }
                        ],
                    }
                ],
            )

            row = temp_emails_repo.get_temp_email_message_by_id("temp-inline-1")
            self.assertIsNotNone(row)
            payload = json.loads(row["raw_content"])
            self.assertIn("attachments", payload)
            self.assertEqual(payload["attachments"][0]["content_id"], "captcha-1")
            self.assertEqual(row["html_content"], '<p><img src="cid:captcha-1"></p>')

    def test_save_temp_email_messages_does_not_downgrade_detail_payload_with_list_payload(self):
        self._insert_temp_email("merge@test.example")
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                "merge@test.example",
                [
                    {
                        "id": "temp-merge-1",
                        "from_address": "sender@example.com",
                        "subject": "detail",
                        "content": "plain body",
                        "html_content": '<div><img src="cid:<captcha-1>" alt="captcha"></div>',
                        "has_html": True,
                        "timestamp": 1772407200,
                        "attachments": [
                            {
                                "content_id": "captcha-1",
                                "content_type": "image/png",
                                "content_base64": "QUJDRA==",
                                "is_inline": True,
                            }
                        ],
                    }
                ],
            )
            temp_emails_repo.save_temp_email_messages(
                "merge@test.example",
                [
                    {
                        "id": "temp-merge-1",
                        "from_address": "sender@example.com",
                        "subject": "detail",
                        "content": "plain body",
                        "html_content": "",
                        "has_html": False,
                        "timestamp": 1772407200,
                    }
                ],
            )

            row = temp_emails_repo.get_temp_email_message_by_id("temp-merge-1")
            self.assertEqual(row["html_content"], '<div><img src="cid:<captcha-1>" alt="captcha"></div>')
            payload = json.loads(row["raw_content"])
            self.assertIn("attachments", payload)
            self.assertEqual(payload["attachments"][0]["content_id"], "captcha-1")

    def test_temp_email_detail_keeps_remote_image_url(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "remote-image@test.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-remote-1",
                "from_address": "sender@example.com",
                "subject": "remote image",
                "html_content": '<div><img src="https://cdn.example.com/captcha.png" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407200,
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-remote-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["email"]["body_type"], "html")
        self.assertIn("https://cdn.example.com/captcha.png", data["email"]["body"])
        self.assertEqual(data["email"]["inline_resources"], {})

    def test_temp_email_detail_keeps_data_image_uri(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "data-image@test.example"
        self._insert_temp_email(email_addr)

        data_image = "data:image/png;base64,QUJDRA=="
        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-data-1",
                "from_address": "sender@example.com",
                "subject": "data image",
                "html_content": f'<div><img src="{data_image}" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407201,
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-data-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body_type"], "html")
        self.assertIn(data_image, data["email"]["body"])

    def test_temp_email_detail_rewrites_cid_image_when_inline_resource_exists(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "cid-image@test.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-cid-1",
                "from_address": "sender@example.com",
                "subject": "cid image",
                "html_content": '<div><img src="cid:captcha-1" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407202,
                "attachments": [
                    {
                        "content_id": "captcha-1",
                        "content_type": "image/png",
                        "content_base64": "QUJDRA==",
                        "is_inline": True,
                    }
                ],
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-cid-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body_type"], "html")
        self.assertIn("data:image/png;base64,QUJDRA==", data["email"]["body"])
        self.assertEqual(data["email"]["inline_resources"]["captcha-1"], "data:image/png;base64,QUJDRA==")

    def test_temp_email_detail_rewrites_cid_image_with_angle_brackets(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "cid-angle@test.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-cid-angle-1",
                "from_address": "sender@example.com",
                "subject": "cid angle image",
                "html_content": '<div><img src="cid:<captcha-1>" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407204,
                "attachments": [
                    {
                        "content_id": "<captcha-1>",
                        "content_type": "image/png",
                        "content_base64": "QUJDRA==",
                        "is_inline": True,
                    }
                ],
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-cid-angle-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("data:image/png;base64,QUJDRA==", data["email"]["body"])

    def test_temp_email_detail_preserves_original_cid_html_when_mapping_missing(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "cid-raw@test.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-cid-raw-1",
                "from_address": "sender@example.com",
                "subject": "raw cid image",
                "html_content": '<div><img src="cid:<captcha-raw>" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407205,
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-cid-raw-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('src="cid:<captcha-raw>"', data["email"]["body"])

    def test_temp_email_detail_keeps_plain_text_mail_unchanged(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "plain-text@test.example"
        self._insert_temp_email(email_addr)

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-text-1",
                "from_address": "sender@example.com",
                "subject": "plain text",
                "content": "Your verification code is 123456",
                "html_content": "",
                "has_html": False,
                "timestamp": 1772407203,
            },
        ):
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-text-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body_type"], "text")
        self.assertEqual(data["email"]["body"], "Your verification code is 123456")

    def test_temp_email_detail_uses_cached_detail_without_calling_remote_api(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "cached-detail@test.example"
        self._insert_temp_email(email_addr)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                email_addr,
                [
                    {
                        "id": "temp-cached-1",
                        "from_address": "sender@example.com",
                        "subject": "cached",
                        "content": "cached body",
                        "html_content": "",
                        "has_html": False,
                        "timestamp": 1772407210,
                    }
                ],
            )

        with patch("outlook_web.services.gptmail.get_temp_email_detail_from_api") as detail_mock:
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-cached-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body"], "cached body")
        detail_mock.assert_not_called()

    def test_temp_email_detail_refreshes_sparse_local_html_marker_payload(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "sparse-html@test.example"
        self._insert_temp_email(email_addr)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                email_addr,
                [
                    {
                        "id": "temp-sparse-1",
                        "from_address": "sender@example.com",
                        "subject": "sparse",
                        "content": "",
                        "html_content": "",
                        "has_html": True,
                        "timestamp": 1772407211,
                    }
                ],
            )

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-sparse-1",
                "from_address": "sender@example.com",
                "subject": "sparse",
                "html_content": "<div>remote html</div>",
                "has_html": True,
                "timestamp": 1772407211,
            },
        ) as detail_mock:
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-sparse-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body"], "<div>remote html</div>")
        self.assertEqual(data["email"]["body_type"], "html")
        detail_mock.assert_called_once()

    def test_temp_email_detail_refreshes_cached_cid_html_without_inline_resource_mapping(self):
        client = self.app.test_client()
        self._login(client)
        email_addr = "cid-refresh@test.example"
        self._insert_temp_email(email_addr)

        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.save_temp_email_messages(
                email_addr,
                [
                    {
                        "id": "temp-cid-refresh-1",
                        "from_address": "sender@example.com",
                        "subject": "cid refresh",
                        "html_content": '<div><img src="cid:captcha-refresh" alt="captcha"></div>',
                        "has_html": True,
                        "timestamp": 1772407212,
                    }
                ],
            )

        with patch(
            "outlook_web.services.gptmail.get_temp_email_detail_from_api",
            return_value={
                "id": "temp-cid-refresh-1",
                "from_address": "sender@example.com",
                "subject": "cid refresh",
                "html_content": '<div><img src="cid:captcha-refresh" alt="captcha"></div>',
                "has_html": True,
                "timestamp": 1772407212,
                "attachments": [
                    {
                        "content_id": "captcha-refresh",
                        "content_type": "image/png",
                        "content_base64": "QUJDRA==",
                        "is_inline": True,
                    }
                ],
            },
        ) as detail_mock:
            resp = client.get(f"/api/temp-emails/{email_addr}/messages/temp-cid-refresh-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["email"]["body_type"], "html")
        self.assertIn("data:image/png;base64,QUJDRA==", data["email"]["body"])
        detail_mock.assert_called_once()


class TempEmailImageFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _get_text(self, client, path):
        resp = client.get(path)
        try:
            return resp.data.decode("utf-8")
        finally:
            resp.close()

    def test_email_renderer_supports_cid_rewrite_and_safe_data_images(self):
        client = self.app.test_client()
        main_js = self._get_text(client, "/static/js/main.js")
        temp_js = self._get_text(client, "/static/js/features/temp_emails.js")

        self.assertIn("DOMPurify.sanitize", main_js)
        self.assertIn("DOMPurify.sanitize", temp_js)
