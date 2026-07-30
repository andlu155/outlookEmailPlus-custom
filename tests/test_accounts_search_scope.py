from __future__ import annotations

import unittest
import uuid

from tests._import_app import clear_login_attempts, import_web_app_module


class AccountsSearchScopeTests(unittest.TestCase):
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

    def _db(self):
        return self.module.create_sqlite_connection()

    def _create_group(self, name: str | None = None) -> int:
        unique = uuid.uuid4().hex
        group_name = name or f"search_scope_group_{unique}"
        conn = self._db()
        try:
            cur = conn.execute(
                """
                INSERT INTO groups (name, description, color, proxy_url, is_system)
                VALUES (?, ?, ?, ?, 0)
                """,
                (group_name, "search scope test group", "#2E6B8A", ""),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _create_account(
        self,
        *,
        group_id: int,
        email_addr: str,
        remark: str = "",
        email_domain: str | None = None,
    ) -> int:
        unique = uuid.uuid4().hex
        domain = email_domain
        if domain is None and "@" in email_addr:
            domain = email_addr.rsplit("@", 1)[-1].strip().lower()
        domain = domain or ""
        conn = self._db()
        try:
            cur = conn.execute(
                """
                INSERT INTO accounts (
                    email, password, client_id, refresh_token, group_id, remark, status, email_domain
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (email_addr, "", f"cid_{unique}", f"rt_{unique}", group_id, remark, domain),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _create_tag(self, name: str | None = None) -> int:
        unique = uuid.uuid4().hex
        tag_name = name or f"search_scope_tag_{unique}"
        conn = self._db()
        try:
            cur = conn.execute("INSERT INTO tags (name, color) VALUES (?, ?)", (tag_name, "#B85C38"))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _attach_tag(self, account_id: int, tag_id: int) -> None:
        conn = self._db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO account_tags (account_id, tag_id) VALUES (?, ?)",
                (account_id, tag_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_accounts_api_search_without_group_id_is_cross_group(self):
        client = self.app.test_client()
        self._login(client)
        group_a = self._create_group(name="scope_all_a")
        group_b = self._create_group(name="scope_all_b")
        marker = f"cross_{uuid.uuid4().hex[:8]}"
        email_a = f"{marker}_a@example.com"
        email_b = f"{marker}_b@example.com"
        self._create_account(group_id=group_a, email_addr=email_a, remark=f"note-{marker}")
        self._create_account(group_id=group_b, email_addr=email_b, remark="other")

        resp = client.get(f"/api/accounts?search={marker}&page=1&page_size=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)
        emails = {acc.get("email") for acc in (data.get("accounts") or [])}
        self.assertIn(email_a, emails)
        self.assertIn(email_b, emails)
        self.assertEqual((data.get("pagination") or {}).get("total_count"), 2)
        group_ids = {acc.get("group_id") for acc in (data.get("accounts") or [])}
        self.assertEqual(group_ids, {group_a, group_b})

    def test_accounts_api_search_with_group_id_does_not_leak(self):
        client = self.app.test_client()
        self._login(client)
        group_a = self._create_group(name="scope_group_a")
        group_b = self._create_group(name="scope_group_b")
        marker = f"leak_{uuid.uuid4().hex[:8]}"
        email_a = f"{marker}_a@example.com"
        email_b = f"{marker}_b@example.com"
        self._create_account(group_id=group_a, email_addr=email_a)
        self._create_account(group_id=group_b, email_addr=email_b)

        resp = client.get(f"/api/accounts?group_id={group_a}&search={marker}&page=1&page_size=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        accounts = data.get("accounts") or []
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].get("email"), email_a)
        self.assertEqual(accounts[0].get("group_id"), group_a)
        self.assertEqual((data.get("pagination") or {}).get("total_count"), 1)

    def test_accounts_api_search_matches_email_domain_and_tag(self):
        client = self.app.test_client()
        self._login(client)
        group_id = self._create_group()
        tag_id = self._create_tag(name=f"domain-tag-{uuid.uuid4().hex[:6]}")
        domain_email = f"user_{uuid.uuid4().hex[:6]}@special-domain.test"
        tagged_email = f"tagged_{uuid.uuid4().hex[:6]}@example.com"
        account_domain = self._create_account(group_id=group_id, email_addr=domain_email)
        account_tagged = self._create_account(group_id=group_id, email_addr=tagged_email)
        self._attach_tag(account_tagged, tag_id)
        self.assertIsNotNone(account_domain)

        domain_resp = client.get("/api/accounts?search=special-domain.test&page=1&page_size=50")
        self.assertEqual(domain_resp.status_code, 200)
        domain_data = domain_resp.get_json() or {}
        domain_emails = {acc.get("email") for acc in (domain_data.get("accounts") or [])}
        self.assertIn(domain_email, domain_emails)

        tag_resp = client.get(f"/api/accounts?search=domain-tag-&page=1&page_size=50")
        self.assertEqual(tag_resp.status_code, 200)
        tag_data = tag_resp.get_json() or {}
        tag_emails = {acc.get("email") for acc in (tag_data.get("accounts") or [])}
        self.assertIn(tagged_email, tag_emails)

    def test_legacy_accounts_search_endpoint_delegates_to_paginated_loader(self):
        client = self.app.test_client()
        self._login(client)
        group_a = self._create_group()
        group_b = self._create_group()
        marker = f"legacy_{uuid.uuid4().hex[:8]}"
        email_a = f"{marker}_a@example.com"
        email_b = f"{marker}_b@example.com"
        self._create_account(group_id=group_a, email_addr=email_a, remark=marker)
        self._create_account(group_id=group_b, email_addr=email_b)

        resp = client.get(f"/api/accounts/search?q={marker}&page=1&page_size=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("success"), True)
        emails = {acc.get("email") for acc in (data.get("accounts") or [])}
        self.assertIn(email_a, emails)
        self.assertIn(email_b, emails)
        pagination = data.get("pagination") or {}
        self.assertEqual(pagination.get("total_count"), 2)
        self.assertIn("page", pagination)
        self.assertIn("page_size", pagination)


if __name__ == "__main__":
    unittest.main()
