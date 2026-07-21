from __future__ import annotations

import unittest

from outlook_web.services.email_aliases import (
    build_alias_summary,
    collect_aliases_from_graph_messages,
    extract_plus_aliases,
)


class EmailAliasesServiceTests(unittest.TestCase):
    def test_extract_plus_aliases_unique_and_scoped(self):
        aliases = extract_plus_aliases(
            "User@Outlook.com",
            [
                "user+shop@outlook.com",
                "user+SHOP@outlook.com",
                "user+ai@outlook.com",
                "other+tag@outlook.com",
                "user@outlook.com",
                "user+ai@gmail.com",
                "",
                None,
            ],
        )
        self.assertEqual(aliases, ["user+ai@outlook.com", "user+shop@outlook.com"])

    def test_collect_aliases_from_graph_messages(self):
        messages = [
            {
                "toRecipients": [
                    {"emailAddress": {"address": "main+78588@outlook.com"}},
                ],
                "ccRecipients": [
                    {"emailAddress": {"address": "main+backup@outlook.com"}},
                ],
            },
            {
                "toRecipients": [
                    {"emailAddress": {"address": "main@outlook.com"}},
                ],
            },
        ]
        aliases, scanned = collect_aliases_from_graph_messages("main@outlook.com", messages)
        self.assertEqual(scanned, 2)
        self.assertEqual(aliases, ["main+78588@outlook.com", "main+backup@outlook.com"])

    def test_build_alias_summary_remaining(self):
        summary = build_alias_summary(
            primary_email="a@b.com",
            aliases=["a+1@b.com", "a+2@b.com", "a+3@b.com"],
            scanned_messages=40,
            soft_limit=5,
        )
        self.assertEqual(summary["used"], 3)
        self.assertEqual(summary["soft_limit"], 5)
        self.assertEqual(summary["remaining"], 2)
        self.assertEqual(summary["scanned_messages"], 40)


if __name__ == "__main__":
    unittest.main()
