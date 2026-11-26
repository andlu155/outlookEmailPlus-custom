from __future__ import annotations

import unittest

from tests._import_app import import_web_app_module


class SettingsWebhookFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _get_text(self, client, path):
        resp = client.get(path)
        try:
            return resp.status_code, resp.data.decode("utf-8")
        finally:
            resp.close()

    def test_index_html_contains_webhook_fields(self):
        client = self.app.test_client()
        self._login(client)
        status, html = self._get_text(client, "/")
        self.assertEqual(status, 200)

        self.assertIn('id="webhookNotificationEnabled"', html)
        self.assertIn('id="webhookNotificationUrl"', html)
        self.assertIn('id="webhookNotificationToken"', html)
        self.assertIn('id="btnTestWebhookNotification"', html)

    def test_main_js_contains_webhook_load_save_autosave_and_test(self):
        client = self.app.test_client()
        self._login(client)
        status, js = self._get_text(client, "/static/js/features/settings.js")
        self.assertEqual(status, 200)

        self.assertIn("webhook_notification_enabled", js)
        self.assertIn("webhook_notification_url", js)
        self.assertIn("webhook_notification_token", js)
        self.assertIn("webhookNotificationEnabled", js)
        self.assertIn("webhookNotificationUrl", js)
        self.assertIn("webhookNotificationToken", js)
        self.assertIn("settings.webhook_notification_enabled", js)
        self.assertIn("settings.webhook_notification_url", js)
        self.assertIn("settings.webhook_notification_token", js)
        self.assertIn("async function testWebhookNotification()", js)
        self.assertIn("/api/settings/webhook-test", js)

    def test_main_js_contains_external_api_key_generate_and_copy(self):
        client = self.app.test_client()
        self._login(client)
        status, js = self._get_text(client, "/static/js/features/settings.js")
        self.assertEqual(status, 200)

        self.assertIn("function generateExternalApiKey()", js)
        self.assertIn("function copyExternalApiKey()", js)
        self.assertIn("window.crypto.getRandomValues", js)
        self.assertIn("const bytes = new Uint8Array(64)", js)
        self.assertIn("当前已存在 API Key，是否覆盖？", js)

    def test_i18n_contains_webhook_and_api_key_entries(self):
        client = self.app.test_client()
        self._login(client)
        status, js = self._get_text(client, "/static/js/i18n.js")
        self.assertEqual(status, 200)

        for token in [
            "Webhook 通知",
            "📡 Webhook 通知",
            "启用 Webhook 通知",
            "Webhook URL",
            "Webhook Token（可选）",
            "测试 Webhook",
            "Webhook 测试成功",
            "Webhook 测试失败",
            "随机生成",
            "当前已存在 API Key，是否覆盖？",
        ]:
            self.assertIn(token, js)


if __name__ == "__main__":
    unittest.main()
