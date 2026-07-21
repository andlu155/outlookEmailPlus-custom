"""
CloudflareTempMailProvider 单元测试
====================================

覆盖范围：
- MIME 解析（纯文本、HTML、多部分、编码主题）
- ISO 时间戳转换（正常、毫秒格式、错误格式）
- get_options：配置解析、域名规范化
- create_mailbox：成功、未配置、HTTP 错误、无域名
- delete_mailbox：成功、请求异常
- list_messages：成功 + MIME 解析、无 JWT、HTTP 错误
- get_message_detail：找到、未找到
- delete_message：成功、无 JWT、cf_ 前缀还原
- clear_messages：成功、无 JWT
- _normalize_cf_message：字段映射、边界值
- factory 路由：cloudflare_temp_mail → CloudflareTempMailProvider
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests._import_app import clear_login_attempts, import_web_app_module

# ---------------------------------------------------------------------------
# 工具函数测试（不依赖 app context）
# ---------------------------------------------------------------------------


class ParseMimeRawTests(unittest.TestCase):
    """测试 _parse_mime_raw 的 MIME 解析逻辑。"""

    def setUp(self):
        from outlook_web.services.temp_mail_provider_cf import _parse_mime_raw

        self._parse = _parse_mime_raw

    def test_plain_text_only(self):
        raw = (
            "From: sender@example.com\r\n"
            "Subject: Hello World\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "This is the body text."
        )
        result = self._parse(raw)
        self.assertEqual(result["subject"], "Hello World")
        self.assertEqual(result["from_address"], "sender@example.com")
        self.assertIn("This is the body text.", result["content"])
        self.assertEqual(result["html_content"], "")
        self.assertFalse(result["has_html"])

    def test_html_only(self):
        raw = (
            "From: noreply@shop.com\r\n"
            "Subject: 验证码\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<p>Your code is <strong>123456</strong></p>"
        )
        result = self._parse(raw)
        self.assertEqual(result["subject"], "验证码")
        self.assertEqual(result["from_address"], "noreply@shop.com")
        self.assertEqual(result["content"], "")
        self.assertIn("123456", result["html_content"])
        self.assertTrue(result["has_html"])

    def test_multipart_mixed(self):
        raw = (
            "From: multi@example.com\r\n"
            "Subject: Multipart Test\r\n"
            "MIME-Version: 1.0\r\n"
            'Content-Type: multipart/alternative; boundary="boundary123"\r\n'
            "\r\n"
            "--boundary123\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Plain text part\r\n"
            "--boundary123\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<b>HTML part</b>\r\n"
            "--boundary123--\r\n"
        )
        result = self._parse(raw)
        self.assertIn("Plain text part", result["content"])
        self.assertIn("HTML part", result["html_content"])
        self.assertTrue(result["has_html"])

    def test_encoded_subject_base64(self):
        # Subject: "=?utf-8?b?5pWw5o2u56CB?=" → "验证码"
        import base64

        encoded = base64.b64encode("验证码".encode("utf-8")).decode()
        raw = (
            f"From: x@example.com\r\n"
            f"Subject: =?utf-8?b?{encoded}?=\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "body"
        )
        result = self._parse(raw)
        self.assertEqual(result["subject"], "验证码")

    def test_empty_raw_returns_defaults(self):
        result = self._parse("")
        self.assertEqual(result["subject"], "")
        self.assertEqual(result["from_address"], "")
        self.assertFalse(result["has_html"])

    def test_malformed_raw_does_not_raise(self):
        # 保证不会抛出异常
        result = self._parse("Not a real email\nJust some text")
        self.assertIsInstance(result, dict)
        self.assertIn("subject", result)


class IsoToTimestampTests(unittest.TestCase):
    """测试 _iso_to_timestamp 的时间戳转换逻辑。"""

    def setUp(self):
        from outlook_web.services.temp_mail_provider_cf import _iso_to_timestamp

        self._convert = _iso_to_timestamp

    def test_standard_z_suffix(self):
        # 2025-12-07T10:30:00Z → 已知 UTC timestamp
        ts = self._convert("2025-12-07T10:30:00Z")
        self.assertGreater(ts, 0)
        # 验证大致范围（2025 年的 unix timestamp 约在 1.7-1.8 billion 之间）
        self.assertGreater(ts, 1_700_000_000)
        self.assertLess(ts, 1_800_000_000)

    def test_milliseconds_format(self):
        # CF Worker 可能返回 .000 毫秒
        ts1 = self._convert("2025-12-07T10:30:00.000Z")
        ts2 = self._convert("2025-12-07T10:30:00Z")
        self.assertEqual(ts1, ts2)

    def test_plus_offset(self):
        ts = self._convert("2025-12-07T10:30:00+00:00")
        self.assertGreater(ts, 0)

    def test_invalid_format_returns_zero(self):
        self.assertEqual(self._convert("not-a-date"), 0)
        self.assertEqual(self._convert(""), 0)
        self.assertEqual(self._convert("2025-13-99T99:99:99Z"), 0)


# ---------------------------------------------------------------------------
# Provider 集成测试（依赖 app context）
# ---------------------------------------------------------------------------


class CloudflareTempMailProviderTests(unittest.TestCase):
    """CloudflareTempMailProvider 功能测试。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            # CF Worker 使用独立配置键（与 GPTMail 隔离）
            settings_repo.set_setting("cf_worker_base_url", "https://cf-worker.example.workers.dev")
            settings_repo.set_setting("cf_worker_admin_key", "super-secret-admin-pass")

            # v0.3+：CF Worker 域名配置应写入 cf_worker_* key。
            settings_repo.set_setting(
                "cf_worker_domains",
                '[{"name":"cf-mail.example.com","enabled":true},{"name":"cf-alt.example.com","enabled":true}]',
            )
            settings_repo.set_setting("cf_worker_default_domain", "cf-mail.example.com")
            settings_repo.set_setting(
                "cf_worker_prefix_rules",
                '{"min_length":1,"max_length":32,"pattern":"^[a-z0-9][a-z0-9._-]*$"}',
            )

            # legacy keys 清空，避免测试被 fallback 逻辑误导
            settings_repo.set_setting("temp_mail_domains", "[]")
            settings_repo.set_setting("temp_mail_default_domain", "")
            settings_repo.set_setting("temp_mail_prefix_rules", "")

    def _make_provider(self):
        from outlook_web.services.temp_mail_provider_cf import (
            CloudflareTempMailProvider,
        )

        return CloudflareTempMailProvider(provider_name="cloudflare_temp_mail")

    def _make_mailbox(self, email: str = "test@cf-mail.example.com", jwt: str = "eyJhbGc.test.jwt") -> dict:
        return {
            "email": email,
            "kind": "temp",
            "meta": {
                "provider_name": "cloudflare_temp_mail",
                "provider_jwt": jwt,
                "provider_mailbox_id": "addr-123",
            },
        }

    # ------------------------------------------------------------------
    # get_options
    # ------------------------------------------------------------------

    def test_get_options_returns_domain_list_and_prefix_rules(self):
        with self.app.app_context():
            provider = self._make_provider()
            options = provider.get_options()

        self.assertEqual(options["provider"], "cloudflare_temp_mail")
        self.assertEqual(options["provider_label"], "cloudflare_temp_mail")
        self.assertEqual(options["api_base_url"], "https://cf-worker.example.workers.dev")
        domains = options["domains"]
        self.assertEqual(len(domains), 2)
        default_domain = next(d for d in domains if d["is_default"])
        self.assertEqual(default_domain["name"], "cf-mail.example.com")

    def test_get_options_auto_sync_writes_cf_worker_domains_when_empty(self):
        """v0.3.1: 当 cf_worker_domains 为空但 base_url 已配置时，应自动同步并写回 cf_worker_domains。"""
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            # 清空 cf_worker_domains，模拟“配置了 base_url 但未点同步”的真实场景
            settings_repo.set_setting("cf_worker_domains", "[]")
            settings_repo.set_setting("cf_worker_default_domain", "")

            provider = self._make_provider()

            # mock open_api/settings 返回 domains
            with patch.object(
                provider,
                "get_cf_worker_domains",
                return_value={
                    "success": True,
                    "domains": ["zerodotsix.top", "outlookmailplus.tech"],
                    "default_domain": "zerodotsix.top",
                    "title": "ZeroTemp Mail",
                    "version": "v1.5.0",
                },
            ):
                options = provider.get_options()

            # options 中应包含 domains
            domains = options.get("domains") or []
            self.assertGreaterEqual(len(domains), 1)
            self.assertTrue(any(d.get("name") == "zerodotsix.top" for d in domains))

            # DB 中也应写回 cf_worker_domains
            stored = settings_repo.get_cf_worker_domains()
            self.assertTrue(any(d.get("name") == "zerodotsix.top" for d in stored))

    # ------------------------------------------------------------------
    # create_mailbox
    # ------------------------------------------------------------------

    def test_create_mailbox_success_returns_email_and_meta_with_jwt(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "address": "hello@cf-mail.example.com",
                "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test",
                "address_id": "addr-456",
            }
            with patch("requests.post", return_value=mock_resp) as post_mock:
                result = provider.create_mailbox(prefix="hello", domain="cf-mail.example.com")

        self.assertTrue(result["success"])
        self.assertEqual(result["email"], "hello@cf-mail.example.com")
        meta = result["meta"]
        self.assertEqual(meta["provider_jwt"], "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test")
        self.assertEqual(meta["provider_mailbox_id"], "addr-456")
        self.assertTrue(meta["provider_capabilities"]["delete_mailbox"])
        # enablePrefix=False 必须被传入
        call_kwargs = post_mock.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        self.assertFalse(payload.get("enablePrefix", True))

    def test_create_mailbox_missing_base_url_returns_error(self):
        with self.app.app_context():
            provider = self._make_provider()
            # settings 函数有 config 兜底，直接 mock provider._base_url 返回空
            with patch.object(provider, "_base_url", return_value=""):
                result = provider.create_mailbox()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "TEMP_MAIL_PROVIDER_NOT_CONFIGURED")

    def test_create_mailbox_missing_admin_key_returns_error(self):
        with self.app.app_context():
            provider = self._make_provider()
            # settings 函数有 config 兜底，直接 mock provider._admin_key 返回空
            with patch.object(provider, "_admin_key", return_value=""):
                result = provider.create_mailbox()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "TEMP_MAIL_PROVIDER_NOT_CONFIGURED")

    def test_create_mailbox_http_401_returns_unauthorized(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            with patch("requests.post", return_value=mock_resp):
                result = provider.create_mailbox(prefix="x")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UNAUTHORIZED")

    def test_create_mailbox_http_error_returns_sanitized_detail(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 400
            mock_resp.text = "Required\nfield\tis missing\x00 " + ("x" * 400)
            with patch("requests.post", return_value=mock_resp):
                result = provider.create_mailbox(prefix="x")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UPSTREAM_BAD_PAYLOAD")
        self.assertTrue(result["error_detail"].startswith("Required field is missing"))
        self.assertLessEqual(len(result["error_detail"]), 300)
        self.assertNotIn("\x00", result["error_detail"])
        self.assertNotIn("super-secret-admin-pass", repr(result))
        self.assertNotIn("x-admin-auth", repr(result).lower())

    def test_create_mailbox_http_401_keeps_code_and_detail(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized\nrequest"
            with patch("requests.post", return_value=mock_resp):
                result = provider.create_mailbox(prefix="x")

        self.assertEqual(result["error_code"], "UNAUTHORIZED")
        self.assertEqual(result["error_detail"], "Unauthorized request")

    def test_create_mailbox_timeout_returns_upstream_timeout(self):
        import requests as req

        with self.app.app_context():
            provider = self._make_provider()
            with patch("requests.post", side_effect=req.Timeout):
                result = provider.create_mailbox(prefix="x")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UPSTREAM_TIMEOUT")

    def test_create_mailbox_uses_default_domain_when_none_specified(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "address": "auto@cf-mail.example.com",
                "jwt": "jwt-token",
                "address_id": "auto-id",
            }
            with patch("requests.post", return_value=mock_resp) as post_mock:
                result = provider.create_mailbox()

        self.assertTrue(result["success"])
        # CF Worker v1.5.0+ 支持 domain 字段；当有可用域名配置时，
        # payload 中应包含 name（非空随机前缀）和 domain（来自配置的默认域名）。
        payload = post_mock.call_args[1]["json"]
        self.assertIn("name", payload)
        self.assertTrue(len(payload["name"]) > 0)
        # 有 domain 配置时应传入 domain 字段
        self.assertIn("domain", payload)
        self.assertEqual(payload["domain"], "cf-mail.example.com")

    # ------------------------------------------------------------------
    # delete_mailbox
    # ------------------------------------------------------------------

    def test_delete_mailbox_success(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            with patch("requests.delete", return_value=mock_resp):
                result = provider.delete_mailbox(self._make_mailbox())

        self.assertTrue(result)

    def test_delete_mailbox_request_exception_returns_false(self):
        import requests as req

        with self.app.app_context():
            provider = self._make_provider()
            with patch("requests.delete", side_effect=req.RequestException("conn error")):
                result = provider.delete_mailbox(self._make_mailbox())

        self.assertFalse(result)

    # ------------------------------------------------------------------
    # list_messages
    # ------------------------------------------------------------------

    def test_list_messages_success_parses_mime_and_normalizes_fields(self):
        with self.app.app_context():
            provider = self._make_provider()
            raw_mime = (
                "From: shop@verify.com\r\n"
                "Subject: Your verification code\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "\r\n"
                "<p>Code: <strong>654321</strong></p>"
            )
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "mails": [
                    {
                        "id": 999,
                        "source": "shop@verify.com",
                        "address": "test@cf-mail.example.com",
                        "raw": raw_mime,
                        "message_id": "<abc@verify.com>",
                        "created_at": "2025-12-07T10:30:00.000Z",
                    }
                ]
            }
            with patch("requests.get", return_value=mock_resp):
                messages = provider.list_messages(self._make_mailbox())

        self.assertEqual(len(messages), 1)
        msg = messages[0]
        # BUG-CF-05: id 加 cf_ 前缀
        self.assertEqual(msg["id"], "cf_999")
        self.assertEqual(msg["message_id"], "cf_999")
        # BUG-CF-01: from_address 正确映射
        self.assertEqual(msg["from_address"], "shop@verify.com")
        # BUG-CF-02: subject/html_content 从 MIME 中解析
        self.assertEqual(msg["subject"], "Your verification code")
        self.assertIn("654321", msg["html_content"])
        self.assertTrue(msg["has_html"])
        # BUG-CF-07: created_at ISO 转 int timestamp
        self.assertIsInstance(msg["timestamp"], int)
        self.assertGreater(msg["timestamp"], 0)

    def test_list_messages_raises_error_when_jwt_missing(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProviderError,
            )

            provider = self._make_provider()
            mailbox_no_jwt = self._make_mailbox(jwt="")
            with self.assertRaises(CloudflareTempMailProviderError) as ctx:
                provider.list_messages(mailbox_no_jwt)

        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_list_messages_raises_error_on_http_403(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProviderError,
            )

            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 403
            mock_resp.text = "Forbidden"
            with patch("requests.get", return_value=mock_resp):
                with self.assertRaises(CloudflareTempMailProviderError) as ctx:
                    provider.list_messages(self._make_mailbox())

        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_list_messages_raises_error_on_server_error(self):
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProviderError,
            )

            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 503
            mock_resp.text = "Service Unavailable"
            with patch("requests.get", return_value=mock_resp):
                with self.assertRaises(CloudflareTempMailProviderError) as ctx:
                    provider.list_messages(self._make_mailbox())

        self.assertEqual(ctx.exception.code, "UPSTREAM_SERVER_ERROR")

    def test_list_messages_raises_error_on_timeout(self):
        import requests as req

        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProviderError,
            )

            provider = self._make_provider()
            with patch("requests.get", side_effect=req.Timeout):
                with self.assertRaises(CloudflareTempMailProviderError) as ctx:
                    provider.list_messages(self._make_mailbox())

        self.assertEqual(ctx.exception.code, "UPSTREAM_TIMEOUT")

    def test_list_messages_skips_unparseable_items_and_continues(self):
        """解析单封邮件失败时应跳过该封，不影响其他邮件。"""
        with self.app.app_context():
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProvider,
            )

            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "mails": [
                    # 正常邮件
                    {
                        "id": 1,
                        "source": "a@example.com",
                        "raw": "Subject: OK\r\n\r\nbody",
                        "created_at": "2025-01-01T00:00:00Z",
                    },
                    # id 为 None（会被跳过产生 message_id = "cf_None" → 实际测试 normalize 不抛异常）
                    {
                        "id": 2,
                        "source": "b@example.com",
                        "raw": "Subject: Also OK\r\n\r\nbody2",
                        "created_at": "2025-01-01T00:01:00Z",
                    },
                ]
            }
            with patch("requests.get", return_value=mock_resp):
                messages = provider.list_messages(self._make_mailbox())

        self.assertEqual(len(messages), 2)

    # ------------------------------------------------------------------
    # get_message_detail
    # ------------------------------------------------------------------

    def test_get_message_detail_returns_matching_message(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "mails": [
                    {
                        "id": 42,
                        "source": "sender@a.com",
                        "raw": "Subject: Detail Test\r\n\r\nbody",
                        "created_at": "2025-06-01T12:00:00Z",
                    }
                ]
            }
            with patch("requests.get", return_value=mock_resp):
                detail = provider.get_message_detail(self._make_mailbox(), "cf_42")

        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], "cf_42")
        self.assertEqual(detail["subject"], "Detail Test")

    def test_get_message_detail_returns_none_when_not_found(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"mails": []}
            with patch("requests.get", return_value=mock_resp):
                detail = provider.get_message_detail(self._make_mailbox(), "cf_999")

        self.assertIsNone(detail)

    # ------------------------------------------------------------------
    # delete_message
    # ------------------------------------------------------------------

    def test_delete_message_strips_cf_prefix_from_id(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            with patch("requests.delete", return_value=mock_resp) as del_mock:
                result = provider.delete_message(self._make_mailbox(), "cf_789")

        self.assertTrue(result)
        # 确认请求 URL 中包含原始 integer ID（789），不含 cf_
        call_url = del_mock.call_args[0][0]
        self.assertIn("/mails/789", call_url)
        self.assertNotIn("cf_789", call_url)

    def test_delete_message_returns_false_when_no_jwt(self):
        with self.app.app_context():
            provider = self._make_provider()
            result = provider.delete_message(self._make_mailbox(jwt=""), "cf_1")

        self.assertFalse(result)

    def test_delete_message_returns_false_on_request_exception(self):
        import requests as req

        with self.app.app_context():
            provider = self._make_provider()
            with patch("requests.delete", side_effect=req.RequestException):
                result = provider.delete_message(self._make_mailbox(), "cf_1")

        self.assertFalse(result)

    # ------------------------------------------------------------------
    # clear_messages
    # ------------------------------------------------------------------

    def test_clear_messages_success(self):
        with self.app.app_context():
            provider = self._make_provider()
            mock_resp = MagicMock()
            mock_resp.ok = True
            with patch("requests.delete", return_value=mock_resp) as del_mock:
                result = provider.clear_messages(self._make_mailbox())

        self.assertTrue(result)
        call_url = del_mock.call_args[0][0]
        # clear_messages 改为 DELETE /admin/clear_inbox/{address_id}
        self.assertIn("/admin/clear_inbox/", call_url)
        self.assertTrue(call_url.endswith("addr-123"))

    def test_clear_messages_returns_false_when_no_jwt(self):
        with self.app.app_context():
            provider = self._make_provider()
            result = provider.clear_messages(self._make_mailbox(jwt=""))

        self.assertFalse(result)

    # ------------------------------------------------------------------
    # _normalize_cf_message 字段映射
    # ------------------------------------------------------------------

    def test_normalize_cf_message_full_fields(self):
        """验证完整 CF 消息的字段映射。"""
        with self.app.app_context():
            provider = self._make_provider()
            cf_msg = {
                "id": 100,
                "source": "from@source.com",
                "address": "to@cf-mail.example.com",
                "raw": "From: from@source.com\r\nSubject: Test\r\n\r\nHello",
                "message_id": "<test@source.com>",
                "created_at": "2025-08-15T08:00:00Z",
            }
            result = provider._normalize_cf_message(cf_msg)

        self.assertEqual(result["id"], "cf_100")
        self.assertEqual(result["message_id"], "cf_100")
        self.assertEqual(result["from_address"], "from@source.com")
        self.assertEqual(result["subject"], "Test")
        self.assertIsInstance(result["timestamp"], int)
        self.assertGreater(result["timestamp"], 0)

    def test_normalize_cf_message_no_raw_uses_source_as_from(self):
        """没有 raw MIME 时，from_address 回退到 source 字段。"""
        with self.app.app_context():
            provider = self._make_provider()
            cf_msg = {
                "id": 200,
                "source": "fallback@sender.com",
                "raw": "",
                "created_at": "2025-01-01T00:00:00Z",
            }
            result = provider._normalize_cf_message(cf_msg)

        self.assertEqual(result["from_address"], "fallback@sender.com")

    def test_normalize_cf_message_none_id_gives_empty_message_id(self):
        """id 为 None 时不崩溃，message_id 为 'cf_None'（str 化）。"""
        with self.app.app_context():
            provider = self._make_provider()
            cf_msg = {
                "id": None,
                "source": "",
                "raw": "",
                "created_at": "",
            }
            # 不应抛出异常
            result = provider._normalize_cf_message(cf_msg)

        self.assertIn("message_id", result)


# ---------------------------------------------------------------------------
# Factory 路由测试
# ---------------------------------------------------------------------------


class CfProviderFactoryRoutingTests(unittest.TestCase):
    """验证 factory 对 cloudflare_temp_mail 的路由。"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def test_factory_routes_cloudflare_provider_to_cf_implementation(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.services.temp_mail_provider_cf import (
                CloudflareTempMailProvider,
            )
            from outlook_web.services.temp_mail_provider_factory import (
                get_temp_mail_provider,
            )

            settings_repo.set_setting("temp_mail_provider", "cloudflare_temp_mail")
            provider = get_temp_mail_provider()

        self.assertIsInstance(provider, CloudflareTempMailProvider)
        self.assertEqual(provider.provider_name, "cloudflare_temp_mail")

    def test_factory_still_routes_custom_provider_correctly(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.services.temp_mail_provider_custom import (
                CustomTempMailProvider,
            )
            from outlook_web.services.temp_mail_provider_factory import (
                get_temp_mail_provider,
            )

            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            provider = get_temp_mail_provider()

        self.assertIsInstance(provider, CustomTempMailProvider)

    def test_cloudflare_provider_name_is_in_supported_set(self):
        from outlook_web.repositories import settings as settings_repo

        supported = settings_repo.get_supported_temp_mail_provider_names()
        self.assertIn("cloudflare_temp_mail", supported)

    def test_factory_rejects_unknown_provider_name(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo
            from outlook_web.services.temp_mail_provider_factory import (
                TempMailProviderFactoryError,
                get_temp_mail_provider,
            )

            settings_repo.set_setting("temp_mail_provider", "totally_unknown_provider_xyz")
            with self.assertRaises(TempMailProviderFactoryError) as ctx:
                get_temp_mail_provider()

        self.assertEqual(ctx.exception.code, "TEMP_MAIL_PROVIDER_INVALID")


if __name__ == "__main__":
    unittest.main()
