"""ZER-90：统一验证码提取模块测试。"""

from __future__ import annotations

import unittest

from outlook_web.services.verification_code_extraction import (
    VerificationInput,
    VerificationPolicy,
    apply_confidence_gate,
    extract_verification,
    extract_verification_from_email_dict,
)


class VerificationCodeExtractionModuleTests(unittest.TestCase):
    def test_extract_lowercase_alphanumeric_code_with_policy_length(self):
        email = VerificationInput(subject="Your verification code", body="Your verification code is ab12cd")
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "ab12cd")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_extract_preserves_mixed_case(self):
        email = VerificationInput(body="Your verification code is Ab12Cd")
        policy = VerificationPolicy(code_length="6-6")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "Ab12Cd")

    def test_extract_html_ignores_css_color_and_keeps_hyphen_code(self):
        email = VerificationInput(
            subject="Verification",
            body_html=(
                "<html><head><style>.title { color: #333333; }</style></head><body>"
                "<p>Your verification code is 84A-KMN</p>"
                "</body></html>"
            ),
        )
        policy = VerificationPolicy(code_length="6-6", code_source="all")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "84A-KMN")
        self.assertEqual(result.get("code_confidence"), "high")

    def test_apply_confidence_gate_strips_low_confidence_code(self):
        raw = {
            "verification_code": "123456",
            "verification_link": None,
            "code_confidence": "low",
            "link_confidence": "low",
        }
        gated = apply_confidence_gate(raw, enforce_mutual_exclusion=False)
        self.assertIsNone(gated.get("verification_code"))

    def test_expected_field_code_filters_link(self):
        email = VerificationInput(
            body="Your verification code is 123456 https://example.com/verify",
        )
        policy = VerificationPolicy(code_length="6-6", expected_field="code")

        result = extract_verification(email, policy)

        self.assertEqual(result.get("verification_code"), "123456")
        self.assertIsNone(result.get("verification_link"))
        self.assertEqual(result.get("formatted"), "123456")

    def test_legacy_wrapper_matches_unified_extractor(self):
        email = {
            "subject": "Validate your email",
            "body": "Please use the code below to validate your email address.\n\n84A-KMN",
        }

        unified = extract_verification(VerificationInput.from_email_dict(email), VerificationPolicy())
        legacy = extract_verification_from_email_dict(email)

        self.assertEqual(legacy.get("verification_code"), unified.get("verification_code"))
        self.assertEqual(legacy.get("code_confidence"), unified.get("code_confidence"))


if __name__ == "__main__":
    unittest.main()
