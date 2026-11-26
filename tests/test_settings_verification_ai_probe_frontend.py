from __future__ import annotations

import unittest

from tests._import_app import import_web_app_module


class SettingsVerificationAiProbeFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def test_settings_page_contains_verification_ai_test_button(self):
        client = self.app.test_client()
        self._login(client)

        resp = client.get("/")
        html = resp.data.decode("utf-8")

        self.assertIn('id="btnTestVerificationAi"', html)
        self.assertIn('id="verificationAiTestResult"', html)
        self.assertIn("测试 AI 配置", html)

    def test_main_js_contains_verification_ai_test_function_and_endpoint(self):
        client = self.app.test_client()
        resp = client.get("/static/js/features/settings.js")
        js = resp.data.decode("utf-8")

        self.assertIn("function testVerificationAiConfig", js)
        self.assertIn("/api/settings/verification-ai-test", js)


if __name__ == "__main__":
    unittest.main()
