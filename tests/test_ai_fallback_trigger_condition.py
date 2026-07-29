"""
AI fallback 触发条件测试

核心规则（方案 A）：code_confidence 或 link_confidence 任一为 high 即跳过 AI。
只有两者均为 low 时才触发 AI 调用。

mock 策略：
- mock `get_verification_ai_runtime_config` → 返回完整 AI 配置
- mock `_call_verification_ai` → 返回固定 AI 结果
- 通过断言 `_call_verification_ai` 的 call_count 判定 AI 是否被触发
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from outlook_web.services import verification_extractor as extractor

_EMAIL_OBJ = {
    "subject": "Test",
    "body": "Test body",
    "body_html": "",
}

_AI_CONFIG = {
    "enabled": True,
    "base_url": "https://api.example.com/v1/chat/completions",
    "api_key": "sk-test",
    "model": "gpt-4.1-mini",
}

_AI_OUTPUT = {
    "schema_version": "verification_ai_v1",
    "verification_code": "AI123",
    "verification_link": "",
    "confidence": "high",
    "reason": "test",
}


def _make_extracted(code_conf: str, link_conf: str, **overrides):
    """构造 extract_verification_info_with_options 的模拟返回值"""
    base = {
        "verification_code": "123456" if code_conf == "high" else "999000",
        "verification_link": "https://example.com/verify" if link_conf == "high" else "https://shop.example.com/deals",
        "links": ["https://example.com/verify", "https://shop.example.com/deals"],
        "formatted": "123456 https://example.com/verify",
        "match_source": "all",
        "confidence": "high" if (code_conf == "high" or link_conf == "high") else "low",
        "code_confidence": code_conf,
        "link_confidence": link_conf,
    }
    base.update(overrides)
    return base


class AiFallbackTriggerConditionTests(unittest.TestCase):
    """方案 A：任一 high 即跳过 AI，仅 both-low 才触发"""

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_high_link_high_skips_ai(self, mock_config, mock_ai_call):
        """code=high + link=high → 不触发 AI"""
        mock_config.return_value = _AI_CONFIG
        extracted = _make_extracted("high", "high")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_high_link_low_skips_ai(self, mock_config, mock_ai_call):
        """code=high + link=low → 不触发 AI（code 已高置信）"""
        mock_config.return_value = _AI_CONFIG
        extracted = _make_extracted("high", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))
        # 规则结果保持不变
        self.assertEqual(result["verification_code"], "123456")
        self.assertEqual(result["code_confidence"], "high")
        self.assertIsNone(result.get("verification_link"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_low_link_high_skips_ai(self, mock_config, mock_ai_call):
        """code=low + link=high → 不触发 AI（link 已高置信）"""
        mock_config.return_value = _AI_CONFIG
        extracted = _make_extracted("low", "high")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))
        # 严格互斥：有 code 时应抑制 link
        self.assertEqual(result["verification_code"], "999000")
        self.assertIsNone(result.get("verification_link"))
        self.assertEqual(result["link_confidence"], "low")

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_low_link_low_triggers_ai(self, mock_config, mock_ai_call):
        """code=low + link=low → 触发 AI"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = _AI_OUTPUT
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_called_once()
        self.assertTrue(result.get("ai_used"))
        self.assertEqual(result["verification_code"], "AI123")

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_low_link_low_ai_returns_none_fallback(self, mock_config, mock_ai_call):
        """code=low + link=low + AI 返回 None → 回退规则结果"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = None
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_called_once()
        # AI 无有效输出，规则结果不变
        self.assertIsNone(result.get("ai_used"))
        self.assertEqual(result["verification_code"], "999000")

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_low_link_low_ai_invalid_json_fallback(self, mock_config, mock_ai_call):
        """code=low + link=low + AI 返回空 code+link → 回退规则结果"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = {
            "verification_code": "",
            "verification_link": "",
            "confidence": "low",
        }
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        # AI 被调用了但结果为空，不设置 ai_used
        mock_ai_call.assert_called_once()
        self.assertIsNone(result.get("ai_used"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_ai_disabled_skips_ai(self, mock_config, mock_ai_call):
        """AI 关闭 → 不触发 AI，即使 both-low"""
        mock_config.return_value = {**_AI_CONFIG, "enabled": False}
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_ai_config_incomplete_skips_ai(self, mock_config, mock_ai_call):
        """AI 开启但配置不完整 → 不触发 AI"""
        mock_config.return_value = {
            "enabled": True,
            "base_url": "",
            "api_key": "",
            "model": "",
        }
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_code_high_link_low_enforces_mutual_exclusion(self, mock_config, mock_ai_call):
        """code=high + link=low → 不触发 AI，且按产品策略抑制 verification_link"""
        mock_config.return_value = _AI_CONFIG
        extracted = _make_extracted("high", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        # 严格互斥：有 code 时不返回 link
        self.assertIsNone(result.get("verification_link"))
        self.assertEqual(result["link_confidence"], "low")


class AiFallbackCasePreservationTests(unittest.TestCase):
    """验证码大小写：AI fallback 返回的验证码必须保持原大小写"""

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_ai_code_case_preserved(self, mock_config, mock_ai_call):
        """AI 返回小写 code → 结果保持小写，不转大写"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = {
            "schema_version": "verification_ai_v1",
            "verification_code": "cbdfdb",
            "verification_link": "",
            "confidence": "high",
            "reason": "test",
        }
        extracted = _make_extracted("low", "low")

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_called_once()
        self.assertTrue(result.get("ai_used"))
        self.assertEqual(result["verification_code"], "cbdfdb")
        self.assertEqual(result["formatted"], "cbdfdb")


class AiFallbackEdgeCaseTests(unittest.TestCase):
    """边界情况：缺失 confidence 字段时默认为 low"""

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_missing_code_confidence_triggers_ai(self, mock_config, mock_ai_call):
        """code_confidence 缺失 → 视为 low → 如果 link 也 low 则触发 AI"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = _AI_OUTPUT
        extracted = _make_extracted("low", "low")
        del extracted["code_confidence"]

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_called_once()

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_missing_link_confidence_with_code_high_skips_ai(self, mock_config, mock_ai_call):
        """link_confidence 缺失但 code=high → 不触发 AI"""
        mock_config.return_value = _AI_CONFIG
        extracted = _make_extracted("high", "low")
        del extracted["link_confidence"]

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted=extracted)

        mock_ai_call.assert_not_called()
        self.assertIsNone(result.get("ai_used"))

    @patch("outlook_web.services.verification_extractor._call_verification_ai")
    @patch("outlook_web.services.verification_extractor.get_verification_ai_runtime_config")
    def test_empty_extracted_triggers_ai(self, mock_config, mock_ai_call):
        """空 extracted（无验证码/链接） → both-low → 触发 AI"""
        mock_config.return_value = _AI_CONFIG
        mock_ai_call.return_value = _AI_OUTPUT

        result = extractor.enhance_verification_with_ai_fallback(email=_EMAIL_OBJ, extracted={})

        mock_ai_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
