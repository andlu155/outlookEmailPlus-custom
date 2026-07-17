from __future__ import annotations

import unittest

from tests._import_app import import_web_app_module


class CfWorkerErrorGuidanceFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def test_main_js_contains_cf_worker_guidance_and_safe_detail_rendering(self):
        client = self.app.test_client()
        response = client.get("/static/js/main.js")
        js_text = response.data.decode("utf-8")

        self.assertIn("function getCfWorkerErrorGuidance", js_text)
        for code in (
            "UNAUTHORIZED",
            "UPSTREAM_BAD_PAYLOAD",
            "UPSTREAM_RATE_LIMITED",
            "UPSTREAM_SERVER_ERROR",
            "UPSTREAM_TIMEOUT",
        ):
            self.assertIn(code, js_text)
        self.assertIn("error.error_detail || error.details", js_text)
        self.assertIn("detailsEl.textContent", js_text)
        self.assertNotIn("x-admin-auth", js_text)
        self.assertNotIn("provider_jwt", js_text)


if __name__ == "__main__":
    unittest.main()
