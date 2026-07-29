from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class TempMailTargetContractTests(unittest.TestCase):
    """
    这组测试用于固定 TDD 中的目标契约。
    已落地的契约应直接转成正式通过，剩余未完成项再继续补。
    """

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
            db.execute("DELETE FROM external_probe_cache")
            db.execute("DELETE FROM external_api_keys")
            db.execute("DELETE FROM temp_email_messages WHERE email_address LIKE '%@test.example'")
            db.execute("DELETE FROM temp_emails WHERE email LIKE '%@test.example'")
            db.commit()
            settings_repo.set_setting("external_api_key", "contract-key")
            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_api_base_url", "")
            settings_repo.set_setting("temp_mail_api_key", "")
            settings_repo.set_setting("gptmail_api_key", "")
            settings_repo.set_setting("temp_mail_domains", "[]")
            settings_repo.set_setting("temp_mail_default_domain", "")
            settings_repo.set_setting("temp_mail_prefix_rules", "{}")

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))

    def _get_text(self, client, path: str) -> str:
        resp = client.get(path)
        try:
            self.assertEqual(resp.status_code, 200)
            return resp.data.decode("utf-8")
        finally:
            resp.close()

    def _create_temp_mail_message(
        self,
        email_addr: str,
        content: str,
        *,
        message_id: str = "msg-1",
        subject: str = "Verify your account",
    ) -> None:
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr=email_addr,
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )
            temp_emails_repo.save_temp_email_messages(
                email_addr,
                [
                    {
                        "id": message_id,
                        "from_address": "noreply@example.com",
                        "subject": subject,
                        "content": content,
                        "html_content": "",
                        "timestamp": 1711111111,
                    }
                ],
            )

    def _gptmail_message_side_effect(
        self,
        content: str,
        *,
        message_id: str = "msg-1",
        subject: str = "Verify your account",
    ) -> list[dict[str, object]]:
        message = {
            "id": message_id,
            "from_address": "noreply@example.com",
            "subject": subject,
            "content": content,
            "html_content": "",
            "timestamp": 1711111111,
        }
        return [
            {"success": True, "data": {"emails": [message]}},
            {"success": True, "data": message},
        ]

    def test_temp_email_options_endpoint_returns_domain_and_prefix_rules(self):
        client = self.app.test_client()
        self._login(client)

        resp = client.get("/api/temp-emails/options")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("options", data)
        self.assertEqual(data["options"]["domain_strategy"], "auto_or_manual")
        self.assertIn("domains", data["options"])
        self.assertIn("prefix_rules", data["options"])

    def test_temp_email_extract_verification_endpoint_returns_code_and_link(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="demo123@test.example",
                mailbox_type="user",
                visible_in_ui=True,
                source="custom_domain_temp_mail",
            )
            temp_emails_repo.save_temp_email_messages(
                "demo123@test.example",
                [
                    {
                        "id": "msg-1",
                        "from_address": "noreply@example.com",
                        "subject": "Verify your account",
                        "content": "Code: 123456 https://verify.example/link",
                        "html_content": "",
                        "timestamp": 1711111111,
                    }
                ],
            )

        client = self.app.test_client()
        self._login(client)
        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            side_effect=[
                {
                    "success": True,
                    "data": {
                        "emails": [
                            {
                                "id": "msg-1",
                                "from_address": "noreply@example.com",
                                "subject": "Verify your account",
                                "content": "Code: 123456 https://verify.example/link",
                                "html_content": "",
                                "timestamp": 1711111111,
                            }
                        ]
                    },
                },
                {
                    "success": True,
                    "data": {
                        "id": "msg-1",
                        "from_address": "noreply@example.com",
                        "subject": "Verify your account",
                        "content": "Code: 123456 https://verify.example/link",
                        "html_content": "",
                        "timestamp": 1711111111,
                    },
                },
            ],
        ):
            resp = client.get("/api/temp-emails/demo123@test.example/extract-verification")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("data", data)
        self.assertIn("verification_code", data["data"])
        self.assertIn("verification_link", data["data"])
        self.assertIn("formatted", data["data"])

    def test_temp_email_verification_field_code_returns_code_only(self):
        content = "Code: 123456 https://verify.example/link"
        self._create_temp_mail_message("codeonly@test.example", content)

        client = self.app.test_client()
        self._login(client)
        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            side_effect=self._gptmail_message_side_effect(content),
        ):
            resp = client.get(
                "/api/temp-emails/codeonly@test.example/verification?field=code&code_length=6-6&code_source=content"
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        data = payload.get("data") or {}
        self.assertTrue(payload.get("success"))
        self.assertEqual(data.get("verification_code"), "123456")
        self.assertIsNone(data.get("verification_link"))
        self.assertEqual(data.get("formatted"), "123456")

    def test_temp_email_verification_field_code_404s_for_link_only_message(self):
        content = "Use this verification link: https://verify.example/link"
        self._create_temp_mail_message("linkonly@test.example", content)

        client = self.app.test_client()
        self._login(client)
        with patch(
            "outlook_web.services.gptmail.gptmail_request",
            side_effect=self._gptmail_message_side_effect(content),
        ):
            resp = client.get("/api/temp-emails/linkonly@test.example/verification?field=code&code_source=content")

        self.assertEqual(resp.status_code, 404)
        payload = resp.get_json() or {}
        self.assertFalse(payload.get("success"))

    def test_external_apply_endpoint_returns_hidden_task_mailbox(self):
        client = self.app.test_client()

        with patch("outlook_web.services.gptmail.generate_temp_email", return_value=("demo123@test.example", None)):
            resp = client.post(
                "/api/external/temp-emails/apply",
                headers={"X-API-Key": "contract-key"},
                json={
                    "caller_id": "register-worker-1",
                    "task_id": "job-001",
                    "prefix": "demo123",
                    "domain": "test.example",
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["code"], "OK")
        self.assertIn("data", data)
        self.assertIn("email", data["data"])
        self.assertIn("task_token", data["data"])
        self.assertEqual(data["data"]["visible_in_ui"], False)

    def test_external_finish_endpoint_marks_task_mailbox_finished(self):
        with self.app.app_context():
            from outlook_web.repositories import temp_emails as temp_emails_repo

            temp_emails_repo.create_temp_email(
                email_addr="finish@test.example",
                mailbox_type="task",
                visible_in_ui=False,
                source="custom_domain_temp_mail",
                task_token="tmptask_demo",
                consumer_key="legacy:settings.external_api_key",
                caller_id="worker",
                task_id="job-001",
            )

        client = self.app.test_client()

        resp = client.post(
            "/api/external/temp-emails/tmptask_demo/finish",
            headers={"X-API-Key": "contract-key"},
            json={"result": "success", "detail": "done"},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["task_token"], "tmptask_demo")
        self.assertEqual(data["data"]["status"], "finished")

    def test_settings_get_returns_temp_mail_contract_fields(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_provider", "custom_domain_temp_mail")
            settings_repo.set_setting("temp_mail_api_base_url", "https://temp.example")
            settings_repo.set_setting("temp_mail_api_key", "temp-mail-secret")
            settings_repo.set_setting(
                "temp_mail_domains",
                '[{"name":"mail.example.com","enabled":true},{"name":"temp.example.net","enabled":true}]',
            )
            settings_repo.set_setting("temp_mail_default_domain", "mail.example.com")
            settings_repo.set_setting(
                "temp_mail_prefix_rules",
                '{"min_length":2,"max_length":24,"pattern":"^[a-z0-9-]+$"}',
            )

        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/settings")

        self.assertEqual(resp.status_code, 200)
        settings = resp.get_json()["settings"]
        self.assertEqual(settings["temp_mail_provider"], "custom_domain_temp_mail")
        self.assertEqual(settings["temp_mail_api_base_url"], "https://temp.example")
        self.assertTrue(settings["temp_mail_api_key_set"])
        self.assertTrue(settings["temp_mail_api_key_masked"])
        self.assertNotIn("gptmail_api_key_set", settings)
        self.assertNotIn("gptmail_api_key_masked", settings)
        self.assertNotEqual(settings["temp_mail_api_key_masked"], "temp-mail-secret")
        self.assertEqual(
            settings["temp_mail_domains"],
            [
                {"name": "mail.example.com", "enabled": True},
                {"name": "temp.example.net", "enabled": True},
            ],
        )
        self.assertEqual(settings["temp_mail_default_domain"], "mail.example.com")
        self.assertEqual(
            settings["temp_mail_prefix_rules"],
            {"min_length": 2, "max_length": 24, "pattern": "^[a-z0-9-]+$"},
        )

    def test_settings_put_persists_temp_mail_contract_fields(self):
        client = self.app.test_client()
        self._login(client)

        resp = client.put(
            "/api/settings",
            json={
                "temp_mail_provider": "custom_domain_temp_mail",
                "temp_mail_api_base_url": "https://bridge.example",
                "temp_mail_api_key": "new-temp-secret",
                "temp_mail_domains": [
                    {"name": "mail.example.com", "enabled": True},
                    {"name": "temp.example.net", "enabled": False},
                ],
                "temp_mail_default_domain": "mail.example.com",
                "temp_mail_prefix_rules": {
                    "min_length": 3,
                    "max_length": 18,
                    "pattern": "^[a-z][a-z0-9._-]*$",
                },
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            self.assertEqual(settings_repo.get_setting("temp_mail_provider"), "custom_domain_temp_mail")
            self.assertEqual(settings_repo.get_setting("temp_mail_api_base_url"), "https://bridge.example")
            self.assertEqual(settings_repo.get_setting("temp_mail_api_key"), "new-temp-secret")
            self.assertEqual(settings_repo.get_setting("gptmail_api_key"), "new-temp-secret")
            self.assertEqual(
                settings_repo.get_temp_mail_domains(),
                [
                    {"name": "mail.example.com", "enabled": True},
                    {"name": "temp.example.net", "enabled": False},
                ],
            )
            self.assertEqual(settings_repo.get_temp_mail_default_domain(), "mail.example.com")
            self.assertEqual(
                settings_repo.get_temp_mail_prefix_rules(),
                {"min_length": 3, "max_length": 18, "pattern": "^[a-z][a-z0-9._-]*$"},
            )

    def test_settings_masked_temp_mail_api_key_placeholder_does_not_overwrite(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_api_key", "keep-this-secret")

        client = self.app.test_client()
        self._login(client)
        masked = client.get("/api/settings").get_json()["settings"]["temp_mail_api_key_masked"]

        resp = client.put("/api/settings", json={"temp_mail_api_key": masked, "temp_mail_provider": "custom_domain_temp_mail"})
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            self.assertEqual(settings_repo.get_setting("temp_mail_api_key"), "keep-this-secret")

    def test_settings_legacy_gptmail_api_key_still_reads_into_temp_contract_fields(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_api_key", "")
            settings_repo.set_setting("gptmail_api_key", "legacy-only-secret")

        client = self.app.test_client()
        self._login(client)
        resp = client.get("/api/settings")

        self.assertEqual(resp.status_code, 200)
        settings = resp.get_json()["settings"]
        self.assertTrue(settings["temp_mail_api_key_set"])
        self.assertTrue(settings["temp_mail_api_key_masked"])
        self.assertNotEqual(settings["temp_mail_api_key_masked"], "legacy-only-secret")

    def test_settings_legacy_gptmail_api_key_put_does_not_reverse_pollute_temp_mail_api_key(self):
        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            settings_repo.set_setting("temp_mail_api_key", "formal-secret")
            settings_repo.set_setting("gptmail_api_key", "legacy-secret")

        client = self.app.test_client()
        self._login(client)
        resp = client.put("/api/settings", json={"gptmail_api_key": "legacy-updated"})

        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            from outlook_web.repositories import settings as settings_repo

            self.assertEqual(settings_repo.get_setting("temp_mail_api_key"), "formal-secret")
            self.assertEqual(settings_repo.get_setting("gptmail_api_key"), "legacy-updated")

    def test_temp_emails_schema_supports_visibility_and_task_ownership_fields(self):
        with self.app.app_context():
            from outlook_web.db import get_db

            db = get_db()
            rows = db.execute("PRAGMA table_info(temp_emails)").fetchall()

        columns = {row["name"] for row in rows}
        self.assertIn("mailbox_type", columns)
        self.assertIn("visible_in_ui", columns)
        self.assertIn("source", columns)
        self.assertIn("prefix", columns)
        self.assertIn("domain", columns)
        self.assertIn("task_token", columns)
        self.assertIn("consumer_key", columns)
        self.assertIn("caller_id", columns)
        self.assertIn("task_id", columns)
        self.assertIn("finished_at", columns)

    def test_temp_email_frontend_references_options_endpoint(self):
        client = self.app.test_client()
        self._login(client)
        js = self._get_text(client, "/static/js/features/temp_emails.js")
        self.assertIn("/api/temp-emails/options", js)
        self.assertIn("tempEmailOptionsStatus", self._get_text(client, "/"))
        self.assertIn("域名配置加载失败", js)
        self.assertIn("status: 'error'", js)

    def test_settings_page_does_not_expose_legacy_gptmail_field_name(self):
        client = self.app.test_client()
        self._login(client)
        index_html = self._get_text(client, "/")

        self.assertNotIn("gptmail_api_key", index_html)
        self.assertIn("旧版临时邮箱 API Key 字段", index_html)

    def test_temp_email_frontend_uses_temp_email_extract_endpoint(self):
        client = self.app.test_client()
        groups_js = self._get_text(client, "/static/js/features/groups.js")
        temp_js = self._get_text(client, "/static/js/features/temp_emails.js")
        emails_js = self._get_text(client, "/static/js/features/emails.js")
        combined = groups_js + "\n" + temp_js + "\n" + emails_js

        self.assertIn("/api/temp-emails/", combined)
        self.assertIn("/verification", combined)
        self.assertIn("buildVerificationExtractEndpoint", groups_js)
        self.assertIn("source: 'temp'", temp_js)
        self.assertIn("copyVerificationInfo(currentAccount, buttonElement", emails_js)
        self.assertIn("fallbackExtractor", groups_js)

    def test_temp_email_page_has_visible_detail_panel_contract(self):
        client = self.app.test_client()
        self._login(client)
        index_html = self._get_text(client, "/")
        temp_section = re.search(r'id="page-temp-emails".*?(?=id="page-refresh-log")', index_html, re.DOTALL)

        self.assertIsNotNone(temp_section)
        section_html = temp_section.group(0)
        self.assertIn('id="tempEmailDetailSection"', section_html)
        self.assertIn('id="tempEmailDetailToolbar"', section_html)
        self.assertIn('id="tempEmailDetail"', section_html)

    def test_temp_email_detail_handler_targets_temp_detail_panel(self):
        client = self.app.test_client()
        temp_js = self._get_text(client, "/static/js/features/temp_emails.js")

        self.assertIn("showEmailDetailContainer({ source: 'temp' })", temp_js)
        self.assertIn("setEmailDetailToolbarVisibility(true, { source: 'temp' })", temp_js)
        self.assertIn("getEmailDetailRefs({ source: 'temp' })", temp_js)
        self.assertIn("renderEmailDetail(data.email, { source: 'temp' })", temp_js)

    def test_normal_mailbox_selection_resets_method_and_temp_page_no_longer_mutates_it(self):
        client = self.app.test_client()
        accounts_js = self._get_text(client, "/static/js/features/accounts.js")
        temp_js = self._get_text(client, "/static/js/features/temp_emails.js")

        self.assertIn("currentMethod = 'graph';", accounts_js)
        self.assertNotIn("currentMethod = 'temp-mail'", temp_js)

    def test_temp_email_frontend_removes_gptmail_branding_from_temp_email_page(self):
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/temp_emails.js")
        self.assertNotIn("currentMethod = 'gptmail'", js)
        self.assertNotIn("methodTag.textContent = 'GPTMail'", js)


class TempMailFrontendHelperBehaviorTests(unittest.TestCase):
    def test_build_verification_extract_endpoint_routes_temp_and_normal_mailboxes(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed")

        repo_root = Path(__file__).resolve().parents[1]
        groups_js_path = repo_root / "static" / "js" / "features" / "groups.js"
        self.assertTrue(groups_js_path.exists(), f"missing {groups_js_path}")

        node_script = r"""
const fs = require('fs');
const vm = require('vm');

const filePath = process.argv[2] || process.argv[1];
const code = fs.readFileSync(filePath, 'utf8');
const match = code.match(/function buildVerificationExtractEndpoint\(email, options = \{\}\) \{[\s\S]*?\n        \}/);
if (!match) {
  throw new Error('buildVerificationExtractEndpoint definition not found');
}

const context = {};
vm.createContext(context);
vm.runInContext(`${match[0]}\nthis.buildVerificationExtractEndpoint = buildVerificationExtractEndpoint;`, context, { filename: filePath });

if (typeof context.buildVerificationExtractEndpoint !== 'function') {
  throw new Error('buildVerificationExtractEndpoint is not executable');
}

const tempResult = context.buildVerificationExtractEndpoint('demo+1@test.example', { source: 'temp-mail' });
if (tempResult !== '/api/temp-emails/demo%2B1%40test.example/verification') {
  throw new Error(`unexpected temp endpoint: ${tempResult}`);
}

const normalResult = context.buildVerificationExtractEndpoint('demo+1@test.example', { source: 'outlook' });
if (normalResult !== '/api/emails/demo%2B1%40test.example/verification') {
  throw new Error(`unexpected normal endpoint: ${normalResult}`);
}

const defaultResult = context.buildVerificationExtractEndpoint('demo+1@test.example');
if (defaultResult !== '/api/emails/demo%2B1%40test.example/verification') {
  throw new Error(`unexpected default endpoint: ${defaultResult}`);
}

process.stdout.write('OK');
"""

        result = subprocess.run(
            ["node", "-e", node_script, "--", str(groups_js_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=f"node stdout:\n{result.stdout}\nnode stderr:\n{result.stderr}",
        )
