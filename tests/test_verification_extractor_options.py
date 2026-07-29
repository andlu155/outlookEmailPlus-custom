import unittest

from outlook_web.services import verification_extractor as extractor


class VerificationExtractorOptionsTests(unittest.TestCase):
    def _require_new_api(self):
        func = getattr(extractor, "extract_verification_info_with_options", None)
        self.assertTrue(callable(func), "缺少 extract_verification_info_with_options()")
        return func

    def test_extract_with_default_options_returns_code(self):
        func = self._require_new_api()
        email = {
            "subject": "Your verification code",
            "body": "Your code is 123456",
            "body_html": "<p>Your code is 123456</p>",
        }

        result = func(email)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertIsNone(result.get("verification_link"))

    def test_extract_with_code_length_prefers_specified_length(self):
        func = self._require_new_api()
        email = {
            "subject": "Your code",
            "body": "short 1234 and target 654321",
            "body_html": "",
        }

        result = func(email, code_length="6-6")

        self.assertEqual(result.get("verification_code"), "654321")
        self.assertIsNone(result.get("verification_link"))

    def test_extract_with_code_length_supports_lowercase_alphanumeric_code(self):
        func = self._require_new_api()
        email = {
            "subject": "Your verification code",
            "body": "Your verification code is ab12cd",
            "body_html": "",
        }

        result = func(email, code_length="6-6")

        self.assertEqual(result.get("verification_code"), "ab12cd")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_with_code_length_preserves_mixed_case_alphanumeric_code(self):
        func = self._require_new_api()
        email = {
            "subject": "Your verification code",
            "body": "Your verification code is Ab12Cd",
            "body_html": "",
        }

        result = func(email, code_length="6-6")

        self.assertEqual(result.get("verification_code"), "Ab12Cd")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_with_code_regex_supports_alphanumeric_code(self):
        func = self._require_new_api()
        email = {
            "subject": "OTP",
            "body": "Use AB12CD to continue",
            "body_html": "",
        }

        result = func(email, code_regex=r"\b[A-Z0-9]{6}\b")

        self.assertEqual(result.get("verification_code"), "AB12CD")
        self.assertIsNone(result.get("verification_link"))

    def test_extract_with_code_source_subject_only(self):
        func = self._require_new_api()
        email = {
            "subject": "Code 778899",
            "body": "no code here",
            "body_html": "",
        }

        result = func(email, code_source="subject")

        self.assertEqual(result.get("verification_code"), "778899")
        self.assertIsNone(result.get("verification_link"))

    def test_extract_with_preferred_link_keywords_returns_verify_link_first(self):
        func = self._require_new_api()
        email = {
            "subject": "Please verify your email",
            "body": "Open https://example.com/home or https://example.com/verify?token=abc",
            "body_html": "",
        }

        result = func(email)

        self.assertIn("verify", result.get("verification_link", ""))

    def test_when_code_exists_link_is_mutually_exclusive(self):
        """有验证码时不应返回 verification_link（严格互斥）"""
        func = self._require_new_api()
        email = {
            "subject": "Your verification code",
            "body": "Your code is 123456. Also click https://example.com/verify?token=abc",
            "body_html": "",
        }

        result = func(email)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertIsNone(result.get("verification_link"))
        self.assertEqual(result.get("formatted"), "123456")


class VerificationExtractorEdgeCaseTests(unittest.TestCase):
    """TC-EXT-01 ~ TC-EXT-04: 提取器参数化与边界测试"""

    def _require_new_api(self):
        func = getattr(extractor, "extract_verification_info_with_options", None)
        self.assertTrue(callable(func), "缺少 extract_verification_info_with_options()")
        return func

    def test_code_source_html_only_from_html(self):
        """TC-EXT-01: code_source=html 仅从 HTML 提取"""
        func = self._require_new_api()
        email = {
            "subject": "No code here",
            "body": "No code in plain text either",
            "body_html": "<p>Your verification code is 998877</p>",
        }

        result = func(email, code_source="html")

        self.assertEqual(result.get("verification_code"), "998877")
        self.assertEqual(result.get("match_source"), "html")

    def test_code_source_html_ignores_body(self):
        """TC-EXT-01 补充: code_source=html 不应从 body 提取"""
        func = self._require_new_api()
        email = {
            "subject": "Code 112233",
            "body": "Body code 445566",
            "body_html": "<p>No code here at all just text</p>",
        }

        result = func(email, code_source="html")

        # HTML 里没有验证码，不应从 body 提取
        self.assertIsNone(result.get("verification_code"))

    def test_code_length_format_invalid_abc(self):
        """TC-EXT-02: code_length='abc' 格式非法"""
        func = self._require_new_api()
        email = {"subject": "Code", "body": "123456", "body_html": ""}

        with self.assertRaises(ValueError):
            func(email, code_length="abc")

    def test_code_length_format_invalid_reversed(self):
        """TC-EXT-02: code_length='8-4' 反序非法"""
        func = self._require_new_api()
        email = {"subject": "Code", "body": "123456", "body_html": ""}

        with self.assertRaises(ValueError):
            func(email, code_length="8-4")

    def test_code_length_format_invalid_single_number(self):
        """TC-EXT-02 补充: code_length='6' 格式非法（需要 min-max 格式）"""
        func = self._require_new_api()
        email = {"subject": "Code", "body": "123456", "body_html": ""}

        with self.assertRaises(ValueError):
            func(email, code_length="6")

    def test_multiple_candidates_prefers_keyword_adjacent(self):
        """TC-EXT-03: 多个候选验证码时优先关键词邻近值"""
        func = self._require_new_api()
        email = {
            "subject": "Verify your account",
            "body": (
                "Some unrelated info about your purchase of item number 999999 from our store last week. "
                "Now here is the important part: Your verification code is 123456. "
                "Please ignore reference number 654321 above."
            ),
            "body_html": "",
        }

        result = func(email)

        # 应优先提取靠近 "verification code" 关键词的 123456
        self.assertEqual(result.get("verification_code"), "123456")
        self.assertEqual(result.get("confidence"), "high")

    def test_multiple_links_prefers_verify_confirm(self):
        """TC-EXT-04: 多个链接时优先 verify/confirm"""
        func = self._require_new_api()
        email = {
            "subject": "Action required",
            "body": (
                "Visit https://example.com/unsubscribe for opt-out. "
                "Or click https://example.com/confirm?token=xyz to confirm. "
                "Also see https://example.com/help for support."
            ),
            "body_html": "",
        }

        result = func(email)

        self.assertIn("confirm", result.get("verification_link", ""))

    def test_no_high_priority_link_falls_back_to_first(self):
        """TC-VER-08 补充: 无高优先级关键字时回退首个链接"""
        func = self._require_new_api()
        email = {
            "subject": "Links",
            "body": "See https://example.com/page1 or https://example.com/page2",
            "body_html": "",
        }

        result = func(email)

        # 没有 verify/confirm 类关键字，应返回第一个链接
        self.assertIsNotNone(result.get("verification_link"))
        self.assertIn("example.com", result.get("verification_link", ""))

    def test_code_regex_invalid_raises_valueerror(self):
        """补充: 非法正则直接抛 ValueError"""
        func = self._require_new_api()
        email = {"subject": "Code", "body": "123456", "body_html": ""}

        with self.assertRaises(ValueError):
            func(email, code_regex="[unclosed")

    def test_confidence_high_for_keyword_match(self):
        """补充: 关键词匹配时 confidence=high"""
        func = self._require_new_api()
        email = {
            "subject": "Your OTP code",
            "body": "Your OTP code is 778899",
            "body_html": "",
        }

        result = func(email)

        self.assertEqual(result.get("verification_code"), "778899")
        self.assertEqual(result.get("confidence"), "high")

    def test_confidence_low_for_fallback(self):
        """补充: 无关键词匹配时 confidence=low"""
        func = self._require_new_api()
        email = {
            "subject": "Random email",
            "body": "Some text 445566 end",
            "body_html": "",
        }

        result = func(email)

        if result.get("verification_code"):
            self.assertEqual(result.get("confidence"), "low")


class VerificationExtractorConfidenceTests(unittest.TestCase):
    """BUG-00017 止血：code_confidence / link_confidence 细粒度置信度测试"""

    def _require_new_api(self):
        func = getattr(extractor, "extract_verification_info_with_options", None)
        self.assertTrue(callable(func), "缺少 extract_verification_info_with_options()")
        return func

    # ── code_confidence ──

    def test_code_confidence_high_when_keyword_match(self):
        """关键词命中验证码 → code_confidence=high"""
        func = self._require_new_api()
        email = {
            "subject": "Your verification code",
            "body": "Your verification code is 654321",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["verification_code"], "654321")
        self.assertEqual(result["code_confidence"], "high")

    def test_code_confidence_low_when_fallback_only(self):
        """仅 fallback 命中数字 → code_confidence=low"""
        func = self._require_new_api()
        email = {
            "subject": "Weekly newsletter",
            "body": "We have 1181 new features this month",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_code"), "应命中 1181 作为 fallback 候选")
        self.assertEqual(result["code_confidence"], "low")

    def test_code_confidence_low_for_marketing_numbers(self):
        """营销邮件中的普通数字不应获得 high confidence"""
        func = self._require_new_api()
        email = {
            "subject": "50% OFF - Huge Sale!",
            "body": "Save big! Use discount 2999 for GPU instances. Order #8847 confirmed.",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_code"), "应命中某个数字作为 fallback 候选")
        self.assertEqual(result["code_confidence"], "low", "营销邮件数字不应获得 high confidence")

    # ── link_confidence ──

    def test_link_confidence_high_when_verify_keyword_in_url(self):
        """链接含 verify 关键词 → link_confidence=high"""
        func = self._require_new_api()
        email = {
            "subject": "Verify your email",
            "body": "Click https://example.com/verify?token=abc123 to activate",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["link_confidence"], "high")
        self.assertIn("verify", result["verification_link"])

    def test_link_confidence_high_when_confirm_keyword_in_url(self):
        """链接含 confirm 关键词 → link_confidence=high"""
        func = self._require_new_api()
        email = {
            "subject": "Confirm your account",
            "body": "Please visit https://example.com/confirm?id=xyz",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["link_confidence"], "high")

    def test_link_confidence_low_for_generic_link(self):
        """链接不含验证关键词 → link_confidence=low"""
        func = self._require_new_api()
        email = {
            "subject": "Check out our sale",
            "body": "Visit https://shop.example.com/deals for amazing offers",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(result["link_confidence"], "low", "普通链接不应获得 high link_confidence")

    def test_link_confidence_low_for_marketing_link(self):
        """营销邮件中的普通跳转链接 → link_confidence=low"""
        func = self._require_new_api()
        email = {
            "subject": "Runpod - New GPU Instances Available",
            "body": "Check out https://www.runpod.io/pricing and https://blog.runpod.io/update",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"), "应命中某个链接作为 fallback")
        self.assertEqual(result["link_confidence"], "low", "营销链接不应获得 high link_confidence")

    # ── confidence 总字段向后兼容 ──

    def test_confidence_compat_high_when_code_high(self):
        """code_confidence=high → 总 confidence=high（向后兼容）"""
        func = self._require_new_api()
        email = {
            "subject": "OTP",
            "body": "Your OTP is 998877",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["code_confidence"], "high")
        self.assertEqual(result["confidence"], "high")

    def test_confidence_compat_high_when_link_high(self):
        """link_confidence=high → 总 confidence=high（向后兼容）"""
        func = self._require_new_api()
        email = {
            "subject": "Hello",
            "body": "Random text with https://example.com/verify?t=1",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["link_confidence"], "high")
        self.assertEqual(result["confidence"], "high")

    def test_confidence_compat_low_when_both_low(self):
        """code 和 link 均 low → 总 confidence=low"""
        func = self._require_new_api()
        email = {
            "subject": "Sale alert",
            "body": "Item 5678 at https://shop.example.com/deals",
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result["code_confidence"], "low")
        self.assertEqual(result["link_confidence"], "low")
        self.assertEqual(result["confidence"], "low")

    # ── 审查修复：补充关键场景测试 ──

    def test_code_regex_without_keyword_gets_high_confidence(self):
        """调用方传入 code_regex 精确匹配，即使无关键词上下文也应 high confidence"""
        func = self._require_new_api()
        email = {
            "subject": "Account notice",
            "body": "Use AB1234 within 5 minutes to proceed.",
            "body_html": "",
        }
        result = func(email, code_regex=r"\b[A-Z]{2}\d{4}\b")
        self.assertEqual(result["verification_code"], "AB1234")
        self.assertEqual(
            result["code_confidence"],
            "high",
            "code_regex 精确匹配命中应视为 high confidence",
        )

    def test_code_length_without_keyword_stays_low_confidence(self):
        """code_length 仅限定宽度，不具备判别力 → 无关键词上下文时 code_confidence 仍为 low"""
        func = self._require_new_api()
        email = {
            "subject": "Action required",
            "body": "Enter 887766 to continue your setup process.",
            "body_html": "",
        }
        result = func(email, code_length="6-6")
        self.assertEqual(result["verification_code"], "887766")
        self.assertEqual(
            result["code_confidence"],
            "low",
            "code_length 不应自动提权为 high，避免营销邮件订单号绕过门控",
        )

    def test_link_high_confidence_from_email_context(self):
        """URL 不含验证关键词但邮件正文有强验证语境短语 → link_confidence=high"""
        func = self._require_new_api()
        email = {
            "subject": "Please verify your account",
            "body": "Click the link below to verify your email: https://auth.example.com/t/abc123",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(
            result["link_confidence"],
            "high",
            "邮件正文含强验证语境短语时，即使 URL 不含关键词也应 high",
        )

    # ── G3 反例：宽词语境 + 普通链接不应被提权 ──

    def test_discount_code_email_link_stays_low(self):
        """正文含 'discount code' 但这不是验证语境 → link_confidence 仍为 low"""
        func = self._require_new_api()
        email = {
            "subject": "Your exclusive discount code inside!",
            "body": "Use discount code SAVE20 at https://shop.example.com/checkout",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(result["link_confidence"], "low", "'discount code' 不应触发链接验证语境提权")

    def test_promo_code_email_link_stays_low(self):
        """正文含 'promo code' → link_confidence 仍为 low"""
        func = self._require_new_api()
        email = {
            "subject": "Special promo code for you",
            "body": "Apply promo code SPRING25 here: https://deals.example.com/apply",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(result["link_confidence"], "low", "'promo code' 不应触发链接验证语境提权")

    def test_order_confirmation_link_stays_low(self):
        """正文含 'order confirmation' 但只是交易确认 → link_confidence 仍为 low"""
        func = self._require_new_api()
        email = {
            "subject": "Order confirmation",
            "body": "View your order confirmation at https://store.example.com/orders/status",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(
            result["link_confidence"],
            "low",
            "'order confirmation' 不应触发链接验证语境提权",
        )

    def test_confirm_your_order_link_stays_low(self):
        """正文含 'confirm your order'（非邮箱/账户对象）→ low"""
        func = self._require_new_api()
        email = {
            "subject": "Please confirm your order",
            "body": "Click here to confirm your order: https://shop.example.com/orders/status/789",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(
            result["link_confidence"],
            "low",
            "'confirm your order' 不应触发链接验证语境提权",
        )

    def test_activate_your_subscription_link_stays_low(self):
        """正文含 'activate your subscription'（非邮箱/账户对象）→ low"""
        func = self._require_new_api()
        email = {
            "subject": "Activate your subscription today!",
            "body": "Ready to activate your subscription? Visit https://service.example.com/subscribe/start",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(
            result["link_confidence"],
            "low",
            "'activate your subscription' 不应触发链接验证语境提权",
        )

    def test_verify_your_purchase_link_stays_low(self):
        """正文含 'verify your purchase'（非邮箱/账户对象）→ low"""
        func = self._require_new_api()
        email = {
            "subject": "Verify your purchase details",
            "body": "Please verify your purchase at https://store.example.com/orders/review/456",
            "body_html": "",
        }
        result = func(email)
        self.assertIsNotNone(result.get("verification_link"))
        self.assertEqual(
            result["link_confidence"],
            "low",
            "'verify your purchase' 不应触发链接验证语境提权",
        )

    def test_extract_xai_hyphenated_code_without_ai(self):
        """ZER-57：默认规则路径应识别 x.ai 带连字符验证码，且置信度为 high。"""
        func = self._require_new_api()
        email = {
            "subject": "Validate your email",
            "body": (
                "Thank you for creating an xAI account. "
                "Please use the code below to validate your email address.\n\n"
                "84A-KMN\n\n"
                "© 2026 X.AI LLC"
            ),
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result.get("verification_code"), "84A-KMN")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_apply_confidence_gate_keeps_xai_hyphenated_code(self):
        """门控后 x.ai 带连字符验证码仍应保留。"""
        func = self._require_new_api()
        email = {
            "subject": "Validate your email",
            "body": "Please use the code below to validate your email address.\n\n84A-KMN",
            "body_html": "",
        }
        extracted = func(email)
        gated = extractor.apply_confidence_gate(extracted, enforce_mutual_exclusion=False)
        self.assertEqual(gated.get("verification_code"), "84A-KMN")

    def test_extract_xai_all_letter_hyphenated_code_njf_kuu(self):
        """ZER-57 真实收信样本：全字母验证码 NJF-KUU。"""
        func = self._require_new_api()
        email = {
            "subject": "xAI confirmation",
            "body": (
                "Thank you for creating an xAI account. "
                "Please use the code below to validate your email address.\n\n"
                "NJF-KUU\n\n"
                "if you did not create a new account, please ignore this email.\n"
                "SpaceXAI Team\n"
                "© 2026 X.AI LLC\n"
                "For questions contact support@x.ai"
            ),
            "body_html": "",
        }
        result = func(email)
        self.assertEqual(result.get("verification_code"), "NJF-KUU")
        self.assertEqual(result.get("code_confidence"), "high")
        gated = extractor.apply_confidence_gate(result, enforce_mutual_exclusion=False)
        self.assertEqual(gated.get("verification_code"), "NJF-KUU")

    def test_extract_xai_html_with_css_color_false_positive(self):
        """x.ai HTML 邮件含 #333333 样式色值时，不应误提取为验证码。"""
        func = self._require_new_api()
        email = {
            "subject": "NJF-KUU xAI confirmation code",
            "body": "",
            "body_html": (
                "<html><head><style>.title { color: #333333; }</style></head><body>"
                "<p>Thank you for creating an xAI account. "
                "Please use the code below to validate your email address.</p>"
                "<p>NJF-KUU</p>"
                "<p>For questions contact support@x.ai</p>"
                "</body></html>"
            ),
        }
        result = func(email, code_source="all")
        self.assertEqual(result.get("verification_code"), "NJF-KUU")
        self.assertEqual(result.get("code_confidence"), "high")
        gated = extractor.apply_confidence_gate(result, enforce_mutual_exclusion=False)
        self.assertEqual(gated.get("verification_code"), "NJF-KUU")

    def test_extract_html_ignores_css_color_and_keeps_context_hyphen_code(self):
        """ZER-90: HTML 样式色值 #333333 不应覆盖正文里的 84A-KMN。"""
        func = self._require_new_api()
        email = {
            "subject": "Verification",
            "body": "",
            "body_html": (
                "<html><head><style>.title { color: #333333; }</style></head><body>"
                "<p>Your verification code is 84A-KMN</p>"
                "</body></html>"
            ),
        }

        result = func(email, code_source="all")

        self.assertEqual(result.get("verification_code"), "84A-KMN")
        self.assertEqual(result.get("code_confidence"), "high")


if __name__ == "__main__":
    unittest.main()
