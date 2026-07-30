from __future__ import annotations

import unittest

from tests._import_app import clear_login_attempts, import_web_app_module


class AccountImportChunkFrontendContractTests(unittest.TestCase):
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

    def _get_text(self, client, path: str) -> str:
        resp = client.get(path)
        try:
            return resp.data.decode("utf-8")
        finally:
            resp.close()

    def test_import_modal_exposes_progress_ui(self):
        client = self.app.test_client()
        self._login(client)
        html = self._get_text(client, "/")
        self.assertIn('id="importProgressBar"', html)
        self.assertIn('id="importProgressFill"', html)
        self.assertIn('id="importProgressText"', html)
        self.assertIn('id="btnImportAccounts"', html)
        self.assertIn("分片", html)

    def test_accounts_js_chunks_large_imports_with_progress(self):
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/accounts.js")
        self.assertIn("IMPORT_CHUNK_SIZE", js)
        self.assertIn("const IMPORT_CHUNK_SIZE = 100", js)
        self.assertIn("useChunked", js)
        self.assertIn("importProgressBar", js)
        self.assertIn("importProgressFill", js)
        self.assertIn("processedLines", js)
        self.assertIn("chunkLines", js)
        # Still posts to the existing accounts import endpoint per chunk.
        self.assertIn("fetch('/api/accounts'", js)

    def test_deploy_defaults_enable_standalone_multi_worker(self):
        client = self.app.test_client()
        # Static contract via filesystem is enough; hit compose through app static is N/A.
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (root / ".env.example").read_text(encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        start = (root / "scripts/start-gunicorn.sh").read_text(encoding="utf-8")

        self.assertIn('GUNICORN_WORKERS: "${GUNICORN_WORKERS:-2}"', compose)
        self.assertIn('SCHEDULER_STANDALONE: "${SCHEDULER_STANDALONE:-true}"', compose)
        self.assertIn("SCHEDULER_STANDALONE=true", env_example)
        self.assertIn("GUNICORN_WORKERS=2", env_example)
        self.assertIn("GUNICORN_WORKERS=2", dockerfile)
        self.assertIn("SCHEDULER_STANDALONE=true", dockerfile)
        self.assertIn(': "${GUNICORN_WORKERS:=2}"', start)
        self.assertIn(': "${SCHEDULER_STANDALONE:=true}"', start)


if __name__ == "__main__":
    unittest.main()
