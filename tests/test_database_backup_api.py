from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from tests._import_app import clear_login_attempts, import_web_app_module


class DatabaseBackupApiTests(unittest.TestCase):
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
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

    def test_database_backup_requires_login(self):
        client = self.app.test_client()
        resp = client.get("/api/system/database-backup")
        self.assertIn(resp.status_code, {401, 403, 302})

    def test_database_backup_downloads_valid_sqlite_snapshot(self):
        client = self.app.test_client()
        self._login(client)

        # Seed a distinctive row so we can prove the snapshot contains live data.
        marker = f"backup_marker_{uuid.uuid4().hex}"
        conn = self.module.create_sqlite_connection()
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) " "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (marker, "present"),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.get("/api/system/database-backup")
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertIn("application/x-sqlite3", (resp.content_type or "").lower())
        disposition = resp.headers.get("Content-Disposition") or ""
        self.assertIn("attachment", disposition.lower())
        self.assertIn("outlook_accounts_backup_", disposition)

        payload = resp.data
        self.assertGreater(len(payload), 1000)

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.db"
            snapshot.write_bytes(payload)
            check = sqlite3.connect(str(snapshot))
            try:
                row = check.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (marker,),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "present")
                # Basic integrity of the backup file.
                integrity = check.execute("PRAGMA integrity_check").fetchone()
                self.assertEqual(integrity[0], "ok")
            finally:
                check.close()

    def test_frontend_exposes_database_backup_controls(self):
        client = self.app.test_client()
        self._login(client)
        index_html = client.get("/").data.decode("utf-8")
        self.assertIn('id="btnDownloadDatabaseBackup"', index_html)
        self.assertIn("downloadDatabaseBackup()", index_html)
        self.assertIn("数据库备份", index_html)

        main_js = client.get("/static/js/main.js").data.decode("utf-8")
        self.assertIn("async function downloadDatabaseBackup", main_js)
        self.assertIn("/api/system/database-backup", main_js)


if __name__ == "__main__":
    unittest.main()
