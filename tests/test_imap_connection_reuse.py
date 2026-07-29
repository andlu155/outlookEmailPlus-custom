"""
C 层：IMAP 连接复用测试

验证 imap.py 新增的 fetch_and_detail_imap_with_server() 组合函数
能在一次 IMAP 会话中完成 fetch + detail。
对应 TDD 矩阵 R-01 ~ R-06。

注意：组合函数尚未实现，本测试先行编写（TDD 红灯阶段）。
"""

import email as email_lib
import unittest
from email.mime.text import MIMEText
from unittest.mock import MagicMock, call, patch


def _build_rfc822_bytes(subject: str = "Test Subject", body: str = "Hello World", sender: str = "test@example.com"):
    """构造一封简单的 RFC822 邮件 bytes"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Date"] = "Mon, 11 Apr 2026 10:00:00 +0800"
    return msg.as_bytes()


_MOCK_ACCESS_TOKEN = "mock-access-token-xyz"


class TestImapConnectionReuse(unittest.TestCase):
    """IMAP 连接复用测试"""

    def _mock_token_result(self, success=True):
        if success:
            return {"success": True, "access_token": _MOCK_ACCESS_TOKEN}
        return {
            "success": False,
            "error": {"code": "IMAP_TOKEN_FAILED", "message": "获取访问令牌失败"},
        }

    def _setup_imap_mock(self, mock_imap_cls, search_ids=None, fetch_data=None, auth_fail=False):
        """配置 IMAP4_SSL mock 实例"""
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn

        if auth_fail:
            mock_conn.authenticate.side_effect = Exception("AUTHENTICATE failed")
            return mock_conn

        mock_conn.authenticate.return_value = ("OK", [b"Success"])
        mock_conn.select.return_value = ("OK", [b"3"])

        if search_ids is None:
            search_ids = []

        if not search_ids:
            mock_conn.search.return_value = ("OK", [b""])
        else:
            mock_conn.search.return_value = ("OK", [b" ".join(search_ids)])

        if fetch_data is not None:
            mock_conn.fetch.return_value = fetch_data
        else:
            # 默认：为每个 search_id 构造一封邮件
            results = []
            for i, mid in enumerate(search_ids):
                raw = _build_rfc822_bytes(f"Subject {i+1}", f"Body {i+1}", f"sender{i+1}@test.com")
                results.append(((mid + b" (RFC822)", raw), b")"))
            mock_conn.fetch.return_value = ("OK", [item for pair in results for item in pair] if results else [])

        return mock_conn

    # R-01: 有邮件 → 返回 emails + detail，IMAP 连接仅 1 次
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_fetch_and_detail_returns_both(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)

        raw = _build_rfc822_bytes("验证码 123456", "Your code is 123456")
        mock_conn = self._setup_imap_mock(
            mock_imap_cls,
            search_ids=[b"1", b"2", b"3"],
        )
        # 重新配置 fetch：摘要 fetch + detail fetch
        mock_conn.fetch.return_value = (
            "OK",
            [((b"3 (RFC822)", raw), b")")],
        )

        result = fetch_and_detail_imap_with_server(
            "user@test.com", "cid", "rt", folder="inbox", top=1, server="outlook.live.com"
        )

        self.assertTrue(result.get("success"))
        self.assertIsInstance(result.get("emails"), list)
        self.assertGreater(len(result.get("emails", [])), 0)
        self.assertIsNotNone(result.get("detail"))
        # IMAP4_SSL 只创建了一个实例
        self.assertEqual(mock_imap_cls.call_count, 1)

    # R-02: 空信箱 → emails=[], detail=None
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_empty_mailbox_returns_empty_with_no_detail(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)
        self._setup_imap_mock(mock_imap_cls, search_ids=[])

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=1)

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("emails"), [])
        self.assertIsNone(result.get("detail"))

    # R-03: 认证失败 → error
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_auth_failure_returns_error(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)
        self._setup_imap_mock(mock_imap_cls, auth_fail=True)

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=1)

        self.assertFalse(result.get("success"))
        self.assertIsNotNone(result.get("error"))

    # R-04: token 获取失败 → error（不建立 IMAP 连接）
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_token_failure_no_connection(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(False)

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=1)

        self.assertFalse(result.get("success"))
        mock_imap_cls.assert_not_called()

    # R-05: top=1 → 摘要和详情来自同一次 FETCH
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_top_one_single_fetch(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)

        raw = _build_rfc822_bytes("Code: 654321", "Your verification code is 654321")
        mock_conn = self._setup_imap_mock(mock_imap_cls, search_ids=[b"1"])
        mock_conn.fetch.return_value = ("OK", [((b"1 (RFC822)", raw), b")")])

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=1)

        self.assertTrue(result.get("success"))
        # fetch 只调用一次（摘要和详情共用一次 FETCH）
        self.assertEqual(mock_conn.fetch.call_count, 1)

    # R-06: 连接异常断开 → 资源正确释放
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_connection_reset_releases_resources(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.authenticate.return_value = ("OK", [b"Success"])
        mock_conn.select.return_value = ("OK", [b"3"])
        mock_conn.search.side_effect = ConnectionResetError("Connection reset by peer")

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=1)

        self.assertFalse(result.get("success"))
        # logout 应该被尝试调用
        mock_conn.logout.assert_called()

    # 额外：验证 authenticate 只调用 1 次
    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_imap_connection_created_only_once(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)
        raw = _build_rfc822_bytes("Test", "Body text")
        mock_conn = self._setup_imap_mock(mock_imap_cls, search_ids=[b"1", b"2"])
        mock_conn.fetch.return_value = ("OK", [((b"2 (RFC822)", raw), b")")])

        fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=2)

        self.assertEqual(mock_imap_cls.call_count, 1)
        self.assertEqual(mock_conn.authenticate.call_count, 1)

    @patch("outlook_web.services.imap.imaplib.IMAP4_SSL")
    @patch("outlook_web.services.imap.get_access_token_imap_result")
    def test_batch_fetch_response_is_reordered_to_requested_latest_first(self, mock_token, mock_imap_cls):
        from outlook_web.services.imap import fetch_and_detail_imap_with_server

        mock_token.return_value = self._mock_token_result(True)
        raw_old = _build_rfc822_bytes("Old code", "Your code is 990595")
        raw_middle = _build_rfc822_bytes("Middle code", "Your code is 118658")
        raw_new = _build_rfc822_bytes("New code", "Your code is 701280")
        mock_conn = self._setup_imap_mock(mock_imap_cls, search_ids=[b"1", b"2", b"3", b"4", b"5"])
        mock_conn.fetch.return_value = (
            "OK",
            [
                ((b"3 (RFC822)", raw_old), b")"),
                ((b"4 (RFC822)", raw_middle), b")"),
                ((b"5 (RFC822)", raw_new), b")"),
            ],
        )

        result = fetch_and_detail_imap_with_server("user@test.com", "cid", "rt", folder="inbox", top=3)

        self.assertTrue(result.get("success"))
        self.assertEqual([item["id"] for item in result.get("emails", [])], ["5", "4", "3"])
        self.assertEqual(result.get("detail", {}).get("id"), "5")
        self.assertIn("701280", result.get("detail", {}).get("body", ""))


if __name__ == "__main__":
    unittest.main()
