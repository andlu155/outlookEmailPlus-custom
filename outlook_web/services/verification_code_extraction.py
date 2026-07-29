"""
统一验证码提取模块（ZER-90）

将验证码候选生成、评分、门控收敛为单一服务，供 Web API、External API、
简洁模式摘要及旧版 verification_extractor 兼容层共用。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

# 验证码关键词列表（支持中英文）
VERIFICATION_KEYWORDS = [
    "验证码",
    "code",
    "验证",
    "verification",
    "OTP",
    "动态码",
    "校验码",
    "verify code",
    "confirmation code",
    "security code",
    "验证码是",
    "your code",
    "code is",
    "激活码",
    "短信验证码",
]

VERIFICATION_PATTERN = r"\b[A-Z0-9]{4,8}\b"

# 带连字符字母数字验证码，例如 x.ai 的 84A-KMN
HYPHENATED_VERIFICATION_PATTERN = r"(?<![A-Z0-9])([A-Z0-9]{2,4}-[A-Z0-9]{2,4})(?=$|[^A-Z0-9-]|[A-Z][a-z])"

CODE_CONTEXT_PHRASES = [
    "validate your email",
    "validate your email address",
    "code below",
    "xai account",
    "x.ai",
    "support@x.ai",
    "verification code",
    "confirm your email",
    "verify your email",
    "your code",
    "the code below",
]

LINK_PATTERN = r'https?://[^\s<>"{}|\\^`\[\]]+'

DEFAULT_LINK_KEYWORDS = [
    "verify",
    "confirmation",
    "confirm",
    "activate",
    "validation",
]

LINK_CONTEXT_PHRASES = [
    "verify your email",
    "verify your account",
    "verify your address",
    "confirm your email",
    "confirm your account",
    "confirm your address",
    "activate your email",
    "activate your account",
    "email verification",
    "account verification",
    "验证您的邮箱",
    "验证你的邮箱",
    "验证您的账户",
    "验证你的账户",
    "验证您的账号",
    "验证你的账号",
    "确认您的邮箱",
    "确认你的邮箱",
    "确认您的账户",
    "确认你的账户",
    "激活您的账户",
    "激活你的账户",
    "激活您的邮箱",
    "激活你的邮箱",
    "邮箱验证",
    "账号验证",
    "账户验证",
]


@dataclass
class VerificationPolicy:
    """验证码提取策略。"""

    code_regex: str | None = None
    code_length: str | None = None
    code_source: str = "all"
    prefer_link_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_LINK_KEYWORDS))
    enforce_mutual_exclusion: bool = True
    apply_confidence_gate: bool = False
    expected_field: str | None = None  # code | link | any


@dataclass
class VerificationInput:
    """统一邮件输入：subject / 正文 / HTML 分离，避免直接扫描原始 HTML 样式。"""

    subject: str = ""
    body: str = ""
    body_preview: str = ""
    body_html: str = ""
    html_content: str = ""
    body_content: str = ""
    body_content_type: str = ""

    @classmethod
    def from_email_dict(cls, email: Dict[str, Any]) -> VerificationInput:
        payload = email or {}
        return cls(
            subject=str(payload.get("subject") or "").strip(),
            body=str(payload.get("body") or "").strip(),
            body_preview=str(payload.get("body_preview") or "").strip(),
            body_html=str(payload.get("body_html") or payload.get("html_content") or "").strip(),
            html_content=str(payload.get("html_content") or "").strip(),
            body_content=str(payload.get("bodyContent") or "").strip(),
            body_content_type=str(payload.get("bodyContentType") or "").strip(),
        )

    def as_legacy_email_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "body_preview": self.body_preview,
            "body_html": self.body_html or self.html_content,
            "html_content": self.html_content,
            "bodyContent": self.body_content,
            "bodyContentType": self.body_content_type,
        }


class HTMLTextExtractor(HTMLParser):
    """HTML 转纯文本提取器（跳过 style/script 等不可见节点）。"""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: List[str] = []
        self._skip_tags = {"style", "script", "head", "meta", "link"}
        self._current_skip = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in self._skip_tags:
            self._current_skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags:
            self._current_skip = False

    def handle_data(self, data: str) -> None:
        if not self._current_skip and data.strip():
            self.text_parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self.text_parts)


def html_to_visible_text(html_content: str) -> str:
    if not html_content:
        return ""
    parser = HTMLTextExtractor()
    try:
        parser.feed(html_content)
        return html.unescape(parser.get_text() or "").strip()
    except Exception:
        return html_content.strip()


def extract_content_text_without_subject(email_input: VerificationInput) -> str:
    if email_input.body:
        return email_input.body

    html_raw = email_input.body_html or email_input.html_content
    if html_raw:
        return html_to_visible_text(html_raw)

    if email_input.body_content:
        if email_input.body_content_type.lower() == "html":
            return html_to_visible_text(email_input.body_content)
        return email_input.body_content

    if email_input.body_preview:
        return email_input.body_preview

    return ""


def extract_email_text(email: Dict[str, Any]) -> str:
    email_input = VerificationInput.from_email_dict(email)
    content = extract_content_text_without_subject(email_input)
    if content:
        return content
    if email_input.subject:
        return email_input.subject
    return ""


def _parse_code_length(code_length: str) -> tuple[int, int]:
    m = re.match(r"^(\d+)-(\d+)$", str(code_length or "").strip())
    if not m:
        raise ValueError("code_length 参数无效")
    min_len = int(m.group(1))
    max_len = int(m.group(2))
    if min_len <= 0 or max_len <= 0 or min_len > max_len:
        raise ValueError("code_length 参数无效")
    return min_len, max_len


def build_code_regex(*, code_regex: str | None, code_length: str | None) -> re.Pattern[str]:
    if code_regex:
        try:
            return re.compile(code_regex)
        except re.error as exc:
            raise ValueError("code_regex 参数无效") from exc

    if code_length:
        min_len, max_len = _parse_code_length(code_length)
        return re.compile(rf"\b[A-Za-z0-9]{{{min_len},{max_len}}}\b")

    return re.compile(r"\b\d{4,8}\b")


def _is_valid_hyphenated_code(code: str) -> bool:
    if not code or "-" not in code:
        return False

    parts = code.split("-")
    if len(parts) != 2:
        return False
    if not all(part.isalnum() for part in parts):
        return False

    alnum = "".join(parts)
    if not (4 <= len(alnum) <= 10):
        return False
    if any(c.isdigit() for c in alnum):
        return True
    return len(alnum) >= 6 and all(len(part) >= 3 for part in parts) and alnum.isalpha()


def _has_code_context(email_content: str) -> bool:
    content_lower = email_content.lower()
    return any(phrase.lower() in content_lower for phrase in CODE_CONTEXT_PHRASES)


def _find_hyphenated_code_in_text(text: str) -> Optional[str]:
    if not text:
        return None

    for match in re.finditer(HYPHENATED_VERIFICATION_PATTERN, text, re.IGNORECASE):
        code = match.group(1)
        if _is_valid_hyphenated_code(code):
            return code
    return None


def smart_extract_hyphenated_verification_code(email_content: str) -> Optional[str]:
    if not email_content:
        return None

    content_lower = email_content.lower()
    for keyword in VERIFICATION_KEYWORDS:
        keyword_lower = keyword.lower()
        pos = content_lower.find(keyword_lower)
        if pos == -1:
            continue

        start = max(0, pos - 50)
        end = min(len(email_content), pos + len(keyword) + 50)
        code = _find_hyphenated_code_in_text(email_content[start:end])
        if code:
            return code
    return None


def fallback_extract_hyphenated_verification_code(email_content: str) -> Optional[str]:
    if not email_content or not _has_code_context(email_content):
        return None
    return _find_hyphenated_code_in_text(email_content)


def smart_extract_verification_code(email_content: str) -> Optional[str]:
    if not email_content:
        return None

    content_lower = email_content.lower()
    for keyword in VERIFICATION_KEYWORDS:
        keyword_lower = keyword.lower()
        pos = content_lower.find(keyword_lower)
        if pos == -1:
            continue

        start = max(0, pos - 50)
        end = min(len(email_content), pos + len(keyword) + 50)
        context = email_content[start:end]
        matches = re.findall(VERIFICATION_PATTERN, context, re.IGNORECASE)
        for match in matches:
            if any(c.isdigit() for c in match):
                return match

    return smart_extract_hyphenated_verification_code(email_content)


def fallback_extract_verification_code(email_content: str) -> Optional[str]:
    if not email_content:
        return None

    filtered: List[str] = []
    for match in re.findall(VERIFICATION_PATTERN, email_content, re.IGNORECASE):
        if not any(c.isdigit() for c in match):
            continue

        if match.isdigit() and len(match) == 4:
            year = int(match)
            if 1900 <= year <= 2100:
                continue
            hour = int(match[:2])
            minute = int(match[2:])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                continue
            if 2020 <= year <= 2030:
                continue

        filtered.append(match)

    if filtered:
        return filtered[0]

    return fallback_extract_hyphenated_verification_code(email_content)


def smart_extract_code_by_keywords(email_content: str, code_re: re.Pattern[str]) -> Optional[str]:
    if not email_content:
        return None

    content_lower = email_content.lower()
    for keyword in VERIFICATION_KEYWORDS:
        keyword_lower = keyword.lower()
        pos = content_lower.find(keyword_lower)
        if pos == -1:
            continue

        start = max(0, pos - 50)
        end = min(len(email_content), pos + len(keyword) + 50)
        context = email_content[start:end]
        for match in code_re.finditer(context):
            value = match.group(0)
            if value and any(c.isdigit() for c in value):
                return value
    return None


def fallback_extract_code(email_content: str, code_re: re.Pattern[str]) -> Optional[str]:
    if not email_content:
        return None

    candidates: List[str] = []
    for match in code_re.finditer(email_content):
        value = match.group(0) or ""
        if not value or not any(c.isdigit() for c in value):
            continue

        if value.isdigit() and len(value) == 4:
            year = int(value)
            if 1900 <= year <= 2100:
                continue
            hour = int(value[:2])
            minute = int(value[2:])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                continue
            if 2020 <= year <= 2030:
                continue

        candidates.append(value)

    return candidates[0] if candidates else None


def extract_links(email_content: str) -> List[str]:
    if not email_content:
        return []

    cleaned_links = [link.rstrip(".,;:!?)>'\"") for link in re.findall(LINK_PATTERN, email_content, re.IGNORECASE)]
    seen: set[str] = set()
    unique_links: List[str] = []
    for link in cleaned_links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    return unique_links


def pick_preferred_link(links: List[str], prefer_link_keywords: List[str]) -> Optional[str]:
    if not links:
        return None

    keywords = [keyword.lower() for keyword in (prefer_link_keywords or []) if keyword]
    if keywords:
        for keyword in keywords:
            for link in links:
                if keyword in (link or "").lower():
                    return link
    return links[0]


def build_source_text(email_input: VerificationInput, *, code_source: str) -> tuple[str, str]:
    subject = email_input.subject
    content = extract_content_text_without_subject(email_input)
    html_raw = email_input.body_html or email_input.html_content

    source = str(code_source or "all").strip().lower()
    if source == "subject":
        return subject, "subject"
    if source == "content":
        return content, "content"
    if source == "html":
        return (html_to_visible_text(html_raw) if html_raw else ""), "html"
    return f"{subject} {content}".strip(), "all"


def extract_verification_code_from_text(
    source_text: str,
    *,
    code_regex: str | None,
    code_length: str | None,
) -> tuple[Optional[str], str]:
    code_re = build_code_regex(code_regex=code_regex, code_length=code_length)
    caller_directed_code = bool(code_regex)

    verification_code = smart_extract_code_by_keywords(source_text, code_re)
    code_confidence = "high" if verification_code else "low"

    if not verification_code:
        verification_code = fallback_extract_code(source_text, code_re)
        if verification_code and caller_directed_code:
            code_confidence = "high"

    if not verification_code:
        verification_code = smart_extract_hyphenated_verification_code(source_text)
        if verification_code:
            code_confidence = "high"

    if not verification_code:
        verification_code = fallback_extract_hyphenated_verification_code(source_text)
        if verification_code:
            code_confidence = "high"

    return verification_code, code_confidence


def extract_verification(
    email_input: VerificationInput,
    policy: VerificationPolicy | None = None,
) -> Dict[str, Any]:
    """
    统一验证码/链接提取入口。

    返回字段与 extract_verification_info_with_options 兼容。
    """
    active_policy = policy or VerificationPolicy()
    source_text, match_source = build_source_text(email_input, code_source=active_policy.code_source)
    subject = email_input.subject
    content = extract_content_text_without_subject(email_input)
    html_raw = email_input.body_html or email_input.html_content

    verification_code, code_confidence = extract_verification_code_from_text(
        source_text,
        code_regex=active_policy.code_regex,
        code_length=active_policy.code_length,
    )

    links = extract_links(f"{subject} {content} {html_raw}".strip())
    prefer_keywords = active_policy.prefer_link_keywords or DEFAULT_LINK_KEYWORDS

    verification_link = None
    link_confidence = "low"
    should_pick_link = (not active_policy.enforce_mutual_exclusion) or (not verification_code)
    if should_pick_link:
        verification_link = pick_preferred_link(links, prefer_keywords)
        if verification_link:
            for keyword in prefer_keywords:
                if keyword and keyword.lower() in verification_link.lower():
                    link_confidence = "high"
                    break
            if link_confidence != "high":
                full_text_lower = f"{subject} {content}".lower()
                for phrase in LINK_CONTEXT_PHRASES:
                    if phrase.lower() in full_text_lower:
                        link_confidence = "high"
                        break

    confidence = "high" if code_confidence == "high" or link_confidence == "high" else "low"

    parts: List[str] = []
    if verification_code:
        parts.append(verification_code)
    if verification_link:
        parts.append(verification_link)
    formatted = " ".join(parts) if parts else None

    result = {
        "verification_code": verification_code,
        "verification_link": verification_link,
        "links": links,
        "formatted": formatted,
        "match_source": match_source,
        "confidence": confidence,
        "code_confidence": code_confidence,
        "link_confidence": link_confidence,
    }

    if active_policy.apply_confidence_gate:
        result = apply_confidence_gate(result, enforce_mutual_exclusion=active_policy.enforce_mutual_exclusion)

    expected_field = str(active_policy.expected_field or "").strip().lower()
    if expected_field == "code":
        result["verification_link"] = None
        result["link_confidence"] = "low"
        result["formatted"] = result.get("verification_code") or None
    elif expected_field == "link":
        result["verification_code"] = None
        result["code_confidence"] = "low"
        result["formatted"] = result.get("verification_link") or None

    return result


def apply_confidence_gate(extracted: Dict[str, Any], *, enforce_mutual_exclusion: bool = True) -> Dict[str, Any]:
    result = dict(extracted)

    if result.get("code_confidence") != "high":
        result["verification_code"] = None
    if result.get("link_confidence") != "high":
        result["verification_link"] = None

    if enforce_mutual_exclusion and result.get("verification_code"):
        result["verification_link"] = None
        result["link_confidence"] = "low"

    parts = [value for value in (result.get("verification_code"), result.get("verification_link")) if value]
    result["formatted"] = " ".join(parts) if parts else None
    result["confidence"] = (
        "high" if result.get("code_confidence") == "high" or result.get("link_confidence") == "high" else "low"
    )
    return result


def policy_from_resolved(
    resolved: Dict[str, Any] | None,
    *,
    code_source: str = "all",
    enforce_mutual_exclusion: bool = True,
    apply_confidence_gate: bool = False,
    expected_field: str | None = None,
) -> VerificationPolicy:
    payload = resolved or {}
    return VerificationPolicy(
        code_regex=payload.get("code_regex"),
        code_length=payload.get("code_length"),
        code_source=code_source,
        enforce_mutual_exclusion=enforce_mutual_exclusion,
        apply_confidence_gate=apply_confidence_gate,
        expected_field=expected_field,
    )


def extract_verification_from_email_dict(
    email: Dict[str, Any],
    *,
    code_regex: str | None = None,
    code_length: str | None = None,
    code_source: str = "all",
    prefer_link_keywords: list[str] | None = None,
    enforce_mutual_exclusion: bool = True,
    apply_confidence_gate_after: bool = False,
) -> Dict[str, Any]:
    """兼容旧 extract_verification_info_with_options 签名的薄封装。"""
    policy = VerificationPolicy(
        code_regex=code_regex,
        code_length=code_length,
        code_source=code_source,
        prefer_link_keywords=list(prefer_link_keywords or DEFAULT_LINK_KEYWORDS),
        enforce_mutual_exclusion=enforce_mutual_exclusion,
        apply_confidence_gate=apply_confidence_gate_after,
    )
    return extract_verification(VerificationInput.from_email_dict(email), policy)
