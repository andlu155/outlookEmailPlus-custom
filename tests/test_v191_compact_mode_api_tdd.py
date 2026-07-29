"""tests/test_v191_compact_mode_api_tdd.py — TDD-00011 RED 契约测试

目标：
1. 固定账号管理简洁模式第一阶段的 API 契约
2. 让 `/api/accounts` 摘要字段缺口直接体现在测试结果里
3. 固定功能便签 `remark` 轻量更新接口的目标行为
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from tests._import_app import clear_login_attempts, import_web_app_module


class V191CompactModeApiRedTests(unittest.TestCase):
    """TDD-00011 §5 后端 RED 契约测试"""

    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def setUp(self):
        with self.app.app_context():
            clear_login_attempts()

    def _login(self, client, password: str = "testpass123"):
        resp = client.post("/login", json={"password": password})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

    def _db(self):
        return self.module.create_sqlite_connection()

    def _create_group(self, name: str | None = None) -> int:
        unique = uuid.uuid4().hex
        group_name = name or f"compact_group_{unique}"
        conn = self._db()
        try:
            cur = conn.execute(
                """
                INSERT INTO groups (name, description, color, proxy_url, is_system)
                VALUES (?, ?, ?, ?, 0)
                """,
                (group_name, "compact mode test group", "#B85C38", ""),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _create_account(
        self,
        *,
        group_id: int,
        email_addr: str | None = None,
        remark: str = "",
        status: str = "active",
    ) -> int:
        unique = uuid.uuid4().hex
        email_addr = email_addr or f"compact_{unique}@example.com"
        conn = self._db()
        try:
            cur = conn.execute(
                """
                INSERT INTO accounts (email, password, client_id, refresh_token, group_id, remark, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (email_addr, "", f"cid_{unique}", f"rt_{unique}", group_id, remark, status),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _create_tag(self, name: str | None = None) -> int:
        unique = uuid.uuid4().hex
        tag_name = name or f"compact_tag_{unique}"
        conn = self._db()
        try:
            cur = conn.execute(
                "INSERT INTO tags (name, color) VALUES (?, ?)",
                (tag_name, "#1a1a1a"),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _update_account_summary(self, account_id: int, **fields) -> None:
        summary_defaults = {
            "latest_email_subject": "",
            "latest_email_from": "",
            "latest_email_folder": "",
            "latest_email_received_at": "",
            "latest_verification_code": "",
            "latest_verification_folder": "",
            "latest_verification_received_at": "",
        }
        summary_defaults.update(fields)

        conn = self._db()
        try:
            conn.execute(
                """
                UPDATE accounts
                SET latest_email_subject = ?,
                    latest_email_from = ?,
                    latest_email_folder = ?,
                    latest_email_received_at = ?,
                    latest_verification_code = ?,
                    latest_verification_folder = ?,
                    latest_verification_received_at = ?
                WHERE id = ?
                """,
                (
                    summary_defaults["latest_email_subject"],
                    summary_defaults["latest_email_from"],
                    summary_defaults["latest_email_folder"],
                    summary_defaults["latest_email_received_at"],
                    summary_defaults["latest_verification_code"],
                    summary_defaults["latest_verification_folder"],
                    summary_defaults["latest_verification_received_at"],
                    account_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_t_api_001_accounts_api_exposes_compact_summary_fields(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        self._create_account(group_id=group_id)

        resp = client.get(f"/api/accounts?group_id={group_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

        accounts = data.get("accounts") or []
        self.assertGreaterEqual(len(accounts), 1)
        account = accounts[0]

        for field in [
            "latest_email_subject",
            "latest_email_from",
            "latest_email_folder",
            "latest_email_received_at",
            "latest_verification_code",
            "latest_verification_folder",
            "latest_verification_received_at",
        ]:
            self.assertIn(field, account, f"TDD-00011 要求 `/api/accounts` 返回字段 `{field}`")

    def test_t_api_002_accounts_api_returns_empty_verification_code_instead_of_missing_field(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        self._create_account(group_id=group_id)

        resp = client.get(f"/api/accounts?group_id={group_id}")
        self.assertEqual(resp.status_code, 200)
        account = (resp.get_json() or {}).get("accounts", [{}])[0]

        self.assertIn(
            "latest_verification_code",
            account,
            "TDD-00011 要求无验证码场景也必须稳定返回 latest_verification_code 字段",
        )
        self.assertEqual(
            account.get("latest_verification_code"),
            "",
            "TDD-00011 要求无验证码场景返回空字符串，由前端展示“暂无”",
        )

    def test_t_api_003_latest_email_and_latest_verification_may_come_from_different_messages(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)
        self._update_account_summary(
            account_id,
            latest_email_subject="Welcome update",
            latest_email_from="ops@example.com",
            latest_email_folder="inbox",
            latest_email_received_at="2026-03-20T10:00:00Z",
            latest_verification_code="428931",
            latest_verification_folder="inbox",
            latest_verification_received_at="2026-03-20T09:58:00Z",
        )

        resp = client.get(f"/api/accounts?group_id={group_id}")

        self.assertEqual(resp.status_code, 200)
        account = (resp.get_json() or {}).get("accounts", [{}])[0]
        self.assertEqual(account.get("latest_email_subject"), "Welcome update")
        self.assertEqual(account.get("latest_email_from"), "ops@example.com")
        self.assertEqual(account.get("latest_email_folder"), "inbox")
        self.assertEqual(account.get("latest_email_received_at"), "2026-03-20T10:00:00Z")
        self.assertEqual(account.get("latest_verification_code"), "428931")
        self.assertEqual(account.get("latest_verification_folder"), "inbox")
        self.assertEqual(account.get("latest_verification_received_at"), "2026-03-20T09:58:00Z")

    def test_t_api_004_latest_verification_searches_inbox_and_junkemail(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)
        self._update_account_summary(
            account_id,
            latest_email_subject="Inbox digest",
            latest_email_from="news@example.com",
            latest_email_folder="inbox",
            latest_email_received_at="2026-03-20T10:00:00Z",
            latest_verification_code="663421",
            latest_verification_folder="junkemail",
            latest_verification_received_at="2026-03-20T09:59:00Z",
        )

        resp = client.get(f"/api/accounts?group_id={group_id}")

        self.assertEqual(resp.status_code, 200)
        account = (resp.get_json() or {}).get("accounts", [{}])[0]
        self.assertEqual(account.get("latest_verification_code"), "663421")
        self.assertEqual(account.get("latest_verification_folder"), "junkemail")
        self.assertEqual(account.get("latest_verification_received_at"), "2026-03-20T09:59:00Z")

    def test_t_api_005_latest_verification_uses_most_recent_matching_message(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)
        self._update_account_summary(
            account_id,
            latest_email_subject="Verification",
            latest_email_from="security@example.com",
            latest_email_folder="inbox",
            latest_email_received_at="2026-03-20T10:00:00Z",
            latest_verification_code="777888",
            latest_verification_folder="inbox",
            latest_verification_received_at="2026-03-20T10:00:00Z",
        )

        resp = client.get(f"/api/accounts?group_id={group_id}")

        self.assertEqual(resp.status_code, 200)
        account = (resp.get_json() or {}).get("accounts", [{}])[0]
        self.assertEqual(account.get("latest_verification_code"), "777888")
        self.assertEqual(account.get("latest_verification_received_at"), "2026-03-20T10:00:00Z")

    @patch("outlook_web.controllers.emails.graph_service.get_emails_graph")
    def test_t_api_005c_fetch_emails_updates_latest_verification_from_message_preview(self, mock_get_emails_graph):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        unique = uuid.uuid4().hex
        email_addr = f"fetch_preview_{unique}@example.com"
        account_id = self._create_account(group_id=group_id, email_addr=email_addr)

        mock_get_emails_graph.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "msg-latest",
                    "subject": "Daily digest",
                    "from": {"emailAddress": {"address": "news@example.com"}},
                    "receivedDateTime": "2026-03-20T10:00:00Z",
                    "bodyPreview": "No verification code in this digest.",
                    "isRead": False,
                    "hasAttachments": False,
                },
                {
                    "id": "msg-code",
                    "subject": "Security alert",
                    "from": {"emailAddress": {"address": "security@example.com"}},
                    "receivedDateTime": "2026-03-20T09:58:00Z",
                    "bodyPreview": "Your verification code is 663421. It expires in 10 minutes.",
                    "isRead": False,
                    "hasAttachments": False,
                },
            ],
        }

        resp = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        self.assertEqual(payload.get("success"), True)
        account_summary = payload.get("account_summary") or {}
        self.assertEqual(account_summary.get("latest_email_subject"), "Daily digest")
        self.assertEqual(account_summary.get("latest_verification_code"), "663421")
        self.assertEqual(account_summary.get("latest_verification_folder"), "inbox")
        self.assertEqual(account_summary.get("latest_verification_received_at"), "2026-03-20T09:58:00Z")

        conn = self._db()
        try:
            row = conn.execute(
                """
                SELECT latest_email_subject, latest_verification_code, latest_verification_folder, latest_verification_received_at
                FROM accounts
                WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["latest_email_subject"], "Daily digest")
        self.assertEqual(row["latest_verification_code"], "663421")
        self.assertEqual(row["latest_verification_folder"], "inbox")
        self.assertEqual(row["latest_verification_received_at"], "2026-03-20T09:58:00Z")

    @patch("outlook_web.controllers.emails.graph_service.get_emails_graph")
    def test_t_api_005d_fetch_emails_updates_latest_verification_with_mixed_case_code(self, mock_get_emails_graph):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        unique = uuid.uuid4().hex
        email_addr = f"fetch_mixed_case_{unique}@example.com"
        account_id = self._create_account(group_id=group_id, email_addr=email_addr)

        mock_get_emails_graph.return_value = {
            "success": True,
            "emails": [
                {
                    "id": "msg-code",
                    "subject": "Your verification code",
                    "from": {"emailAddress": {"address": "security@example.com"}},
                    "receivedDateTime": "2026-03-20T10:01:00Z",
                    "bodyPreview": "Your verification code is Ab12Cd. It expires in 10 minutes.",
                    "isRead": False,
                    "hasAttachments": False,
                }
            ],
        }

        resp = client.get(f"/api/emails/{email_addr}?folder=inbox&skip=0&top=20")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        self.assertEqual(payload.get("success"), True)
        account_summary = payload.get("account_summary") or {}
        self.assertEqual(account_summary.get("latest_verification_code"), "Ab12Cd")

        conn = self._db()
        try:
            row = conn.execute(
                "SELECT latest_verification_code FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["latest_verification_code"], "Ab12Cd")

    def test_t_api_005b_accounts_api_does_not_fetch_remote_mail_during_list_render(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        self._create_account(group_id=group_id)

        with patch(
            "outlook_web.services.external_api.list_messages_for_external", side_effect=AssertionError("should not fetch")
        ):
            resp = client.get(f"/api/accounts?group_id={group_id}")

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json() or {}
        self.assertEqual(payload.get("success"), True)

    def test_t_api_006_single_account_tagging_reuses_batch_tags_endpoint(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)
        tag_id = self._create_tag()

        resp = client.post(
            "/api/accounts/tags",
            json={"account_ids": [account_id], "tag_id": tag_id, "action": "add"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

        conn = self._db()
        try:
            row = conn.execute(
                "SELECT 1 FROM account_tags WHERE account_id = ? AND tag_id = ?",
                (account_id, tag_id),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)

    def test_t_api_007_batch_tagging_keeps_existing_contract(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_ids = [self._create_account(group_id=group_id) for _ in range(3)]
        tag_id = self._create_tag()

        resp = client.post(
            "/api/accounts/tags",
            json={"account_ids": account_ids, "tag_id": tag_id, "action": "add"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

        conn = self._db()
        try:
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM account_tags
                WHERE tag_id = ? AND account_id IN ({",".join("?" * len(account_ids))})
                """,
                [tag_id] + account_ids,
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(count_row)
        self.assertEqual(int(count_row["cnt"]), len(account_ids))

    def test_t_api_009_remark_patch_endpoint_exists(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)

        resp = client.open(
            f"/api/accounts/{account_id}/remark",
            method="PATCH",
            json={"remark": "高优先级账号"},
        )
        self.assertNotEqual(
            resp.status_code,
            404,
            "TDD-00011 要求新增 PATCH /api/accounts/{account_id}/remark；当前返回 404 说明接口尚未实现",
        )

    def test_t_api_010_remark_patch_updates_only_remark(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        unique = uuid.uuid4().hex
        email_addr = f"remark_{unique}@example.com"
        account_id = self._create_account(group_id=group_id, email_addr=email_addr, remark="")

        conn = self._db()
        try:
            before = conn.execute(
                "SELECT email, client_id, refresh_token, group_id, status, remark FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(before)

        resp = client.open(
            f"/api/accounts/{account_id}/remark",
            method="PATCH",
            json={"remark": "高优先级账号"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

        conn = self._db()
        try:
            after = conn.execute(
                "SELECT email, client_id, refresh_token, group_id, status, remark FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(after)

        self.assertEqual(after["remark"], "高优先级账号")
        self.assertEqual(after["email"], before["email"])
        self.assertEqual(after["client_id"], before["client_id"])
        self.assertEqual(after["refresh_token"], before["refresh_token"])
        self.assertEqual(after["group_id"], before["group_id"])
        self.assertEqual(after["status"], before["status"])

    def test_t_api_011_remark_patch_supports_clear(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id, remark="旧备注")

        resp = client.open(
            f"/api/accounts/{account_id}/remark",
            method="PATCH",
            json={"remark": ""},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

        conn = self._db()
        try:
            row = conn.execute("SELECT remark FROM accounts WHERE id = ?", (account_id,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["remark"] or "", "")

    def test_t_api_012_remark_patch_does_not_require_unrelated_fields(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        account_id = self._create_account(group_id=group_id)

        resp = client.open(
            f"/api/accounts/{account_id}/remark",
            method="PATCH",
            json={"remark": "仅更新备注"},
        )
        self.assertEqual(
            resp.status_code,
            200,
            "TDD-00011 要求备注更新仅提交 remark 即可成功，不应要求 email/client_id/refresh_token",
        )
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)

    def test_t_api_013_remark_patch_account_not_found_returns_structured_error(self):
        client = self.app.test_client()
        self._login(client)

        resp = client.open(
            "/api/accounts/999999/remark",
            method="PATCH",
            json={"remark": "不存在账号"},
        )
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), False)
        self.assertIsInstance(data.get("error"), dict)
        self.assertEqual(data["error"].get("code"), "ACCOUNT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
