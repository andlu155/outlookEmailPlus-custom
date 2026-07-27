from __future__ import annotations

import unittest

from tests._import_app import import_web_app_module


class AccountsSearchScopeFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = import_web_app_module()
        cls.app = cls.module.app

    def _login(self, client):
        resp = client.post("/login", json={"password": "testpass123"})
        self.assertEqual(resp.status_code, 200)

    def _get_text(self, client, path: str) -> str:
        resp = client.get(path)
        try:
            return resp.data.decode("utf-8")
        finally:
            resp.close()

    def test_index_exposes_account_search_scope_controls(self):
        client = self.app.test_client()
        self._login(client)
        html = self._get_text(client, "/")
        self.assertIn('id="globalSearch"', html)
        self.assertIn('id="accountSearchScope"', html)
        self.assertIn('id="accountSearchClearBtn"', html)
        self.assertIn("搜索邮箱 / 备注 / 标签", html)
        self.assertIn("当前分组", html)
        self.assertIn("全部账号", html)
        self.assertIn('onchange="setAccountSearchScope(this.value)"', html)
        self.assertIn('onclick="clearAccountSearch()"', html)

    def test_groups_js_supports_global_and_group_search_scope(self):
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/groups.js")
        self.assertIn("accountSearchScope", js)
        self.assertIn("GLOBAL_ACCOUNT_CACHE_KEY", js)
        self.assertIn("__all__", js)
        self.assertIn("function setAccountSearchScope", js)
        self.assertIn("function clearAccountSearch", js)
        self.assertIn("function loadAccountList", js)
        self.assertIn("function getAccountListCacheKey", js)
        self.assertIn("account-group-badge", js)
        # Group switch keeps global search, clears only in group scope.
        self.assertIn("accountSearchScope !== 'all'", js)
        self.assertIn("accountSearchScope === 'all'", js)

    def test_compact_mode_reads_shared_search_scope_cache(self):
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/features/mailbox_compact.js")
        self.assertIn("getAccountListCacheKey", js)
        self.assertIn("function renderCompactEmptyState", js)
        self.assertIn("function resolveCompactEmptyMessage", js)
        self.assertIn("accountSearchScope", js)

    def test_search_scope_i18n_keys_exist(self):
        client = self.app.test_client()
        js = self._get_text(client, "/static/js/i18n.js")
        for text in [
            "搜索邮箱 / 备注 / 标签…",
            "当前分组",
            "全部账号",
            "请先选择分组",
            "请从左侧选择一个分组",
            "未找到匹配账号，试试切换到「全部账号」或清空筛选",
            "搜索中…",
            "未分组",
            "Current group",
            "All accounts",
            "Searching…",
        ]:
            self.assertIn(text, js)
