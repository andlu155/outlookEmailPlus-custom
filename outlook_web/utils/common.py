from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

ALLOWED_PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
VALID_GROUP_PROXY_MODES = {"inherit", "custom", "direct"}

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", flags=re.IGNORECASE | re.DOTALL)
_BLOCK_TAG_RE = re.compile(r"<(?:br|p|div|li|tr|h[1-6])[^>]*>", flags=re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def utcnow() -> datetime:
    """返回不带时区信息的 UTC 当前时间（与 SQLite CURRENT_TIMESTAMP 语义一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sanitize_input(text: Any, max_length: int = 500) -> str:
    """
    净化用户输入，防止 XSS 攻击：
    - 限制长度
    - 移除不可打印控制字符（保留换行和制表符）
    - 转义 HTML 特殊字符
    """
    if not text:
        return ""

    raw = str(text)[:max_length]
    cleaned = "".join(char for char in raw if char.isprintable() or char in "\n\t")
    return html.escape(cleaned, quote=True)


def parse_bool_flag(value: Any, default: bool = False) -> bool:
    """统一解析布尔标记（兼容 bool / int / 常见字符串）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def mask_secret_value(secret: Any, head: int = 4, tail: int = 4) -> str:
    """脱敏展示密钥/令牌：前 N 位 + 若干 * + 后 N 位。"""
    if not secret:
        return ""
    safe_value = str(secret)
    if len(safe_value) <= head + tail:
        return "*" * len(safe_value)
    return safe_value[:head] + ("*" * (len(safe_value) - head - tail)) + safe_value[-tail:]


def decode_mime_header(header: Optional[str]) -> str:
    """解码 MIME 邮件头（兼容未知编码与损坏字节）。"""
    if not header:
        return ""
    try:
        decoded_parts = decode_header(header)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                enc = charset or "utf-8"
                try:
                    result.append(part.decode(enc, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result)
    except Exception:
        return str(header)


def html_to_plain_text(html_content: str) -> str:
    """将 HTML 片段转为易读纯文本（移除 script/style 与标签，还原实体）。"""
    if not html_content:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", html_content)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return _MULTI_NEWLINE_RE.sub("\n\n", text).strip()


def normalize_group_proxy_mode(proxy_mode: Any, proxy_url: str = "") -> str:
    """
    标准化分组代理模式：
    - 显式传入 proxy_mode 时校验必须为 inherit / custom / direct
    - 未传（旧 API 兼容）时，根据 proxy_url 是否非空自动推导为 custom / inherit
    """
    raw_mode = str(proxy_mode or "").strip().lower()
    if raw_mode:
        if raw_mode not in VALID_GROUP_PROXY_MODES:
            raise ValueError("分组代理模式无效，仅支持 inherit / custom / direct")
        return raw_mode
    return "custom" if str(proxy_url or "").strip() else "inherit"


def validate_proxy_url(url: Any) -> Tuple[bool, str]:
    """校验代理 URL 合法性（空字符串视为未配置，返回 True）。"""
    raw = str(url or "").strip()
    if not raw:
        return True, ""

    if any(ch.isspace() for ch in raw):
        return False, "代理地址不能包含空格或换行符"

    try:
        parsed = urlsplit(raw)
    except Exception:
        return False, "代理地址格式无效"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_PROXY_SCHEMES:
        return (
            False,
            "代理协议不支持，请使用 http://、https://、socks4://、socks5:// 或 socks5h://",
        )

    if not parsed.hostname:
        return False, "代理地址缺少主机名或 IP"

    try:
        port = parsed.port
    except ValueError:
        return False, "代理端口无效，需为 1-65535 之间的整数"

    if port is not None and not (1 <= port <= 65535):
        return False, "代理端口无效，需为 1-65535 之间的整数"

    return True, ""
