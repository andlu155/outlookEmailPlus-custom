import unittest

from tests._import_app import import_web_app_module


class ExternalApiKeySettingsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))
        resp.close()

    def _get_text(self, client, path):
        resp = client.get(path)
        try:
            return resp.status_code, resp.data.decode("utf-8")
        finally:
            resp.close()

    def test_settings_page_has_external_api_key_input(self):
        client = self.app.test_client()
        self._login(client)

        status_code, html = self._get_text(client, "/")
        self.assertEqual(status_code, 200)
        self.assertIn('id="settingsExternalApiKey"', html)
        self.assertIn('id="settingsExternalApiKeysJson"', html)
        self.assertIn('id="poolExternalEnabled"', html)
        self.assertIn('id="externalApiDisablePoolClaimRandom"', html)
        self.assertIn('id="externalApiDisablePoolClaimRelease"', html)
        self.assertIn('id="externalApiDisablePoolClaimComplete"', html)
        self.assertIn('id="externalApiDisablePoolStats"', html)

    def test_main_js_loads_masked_external_api_key_fields(self):
        client = self.app.test_client()
        self._login(client)

        status_code, js = self._get_text(client, "/static/js/features/settings.js")
        self.assertEqual(status_code, 200)
        self.assertIn("external_api_key_masked", js)
        self.assertIn("external_api_keys", js)
        self.assertIn("settingsExternalApiKey", js)
        self.assertIn("settingsExternalApiKeysJson", js)
        self.assertIn("dataset.maskedValue", js)
        self.assertIn("data.settings.pool_external_enabled === true", js)
        self.assertIn("settings.pool_external_enabled = poolExternalEnabledEl.checked", js)
        self.assertIn("settings.external_api_disable_pool_claim_random = disablePoolClaimRandomEl.checked", js)
        self.assertIn("settings.external_api_disable_pool_claim_release = disablePoolClaimReleaseEl.checked", js)
        self.assertIn("settings.external_api_disable_pool_claim_complete = disablePoolClaimCompleteEl.checked", js)
        self.assertIn("settings.external_api_disable_pool_stats = disablePoolStatsEl.checked", js)

    def test_main_js_preserves_pool_access_and_telegram_poll_interval_contract(self):
        client = self.app.test_client()
        self._login(client)

        _, js = self._get_text(client, "/static/js/features/settings.js")
        _, html = self._get_text(client, "/")
        self.assertIn("pool_access:", js)
        self.assertIn("item.pool_access === true", js)
        self.assertIn("Telegram 轮询间隔必须在 10-86400 秒之间", js)
        self.assertIn('id="telegramPollInterval" min="10" max="86400"', html)


if __name__ == "__main__":
    unittest.main()
