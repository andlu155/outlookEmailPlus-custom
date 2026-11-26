from __future__ import annotations

import json
from typing import Any, Dict, Optional

from outlook_web import config
from outlook_web.db import create_sqlite_connection, get_db
from outlook_web.security.crypto import decrypt_data, is_encrypted
from outlook_web.utils.common import mask_secret_value

DEFAULT_TEMP_MAIL_PROVIDER = "custom_domain_temp_mail"
LEGACY_TEMP_MAIL_PROVIDER = "legacy_bridge"
CLOUDFLARE_TEMP_MAIL_PROVIDER = "cloudflare_temp_mail"
LEGACY_TEMP_MAIL_PROVIDER_NAMES = {"legacy_bridge", "legacy_gptmail", "gptmail"}


def get_setting(key: str, default: str = "") -> str:
    """获取设置值"""
    db = None
    temp_conn = False
    try:
        db = get_db()
    except RuntimeError:
        db = create_sqlite_connection()
        temp_conn = True

    try:
        cursor = db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    finally:
        if temp_conn and db is not None:
            db.close()


def set_setting(key: str, value: str, *, commit: bool = True) -> bool:
    """设置值"""
    db = None
    temp_conn = False
    try:
        db = get_db()
    except RuntimeError:
        db = create_sqlite_connection()
        temp_conn = True

    try:
        db.execute(
            """
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (key, value),
        )
        if commit:
            db.commit()
        return True
    except Exception:
        return False
    finally:
        if temp_conn and db is not None:
            db.close()


def get_all_settings() -> Dict[str, str]:
    """获取所有设置"""
    db = None
    temp_conn = False
    try:
        db = get_db()
    except RuntimeError:
        db = create_sqlite_connection()
        temp_conn = True

    try:
        cursor = db.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        if temp_conn and db is not None:
            db.close()


def _read_setting(
    key: str,
    default: str = "",
    all_settings: Optional[Dict[str, str]] = None,
) -> str:
    if all_settings is not None:
        val = all_settings.get(key)
        return default if val is None else str(val)
    return get_setting(key, default)


def _get_encrypted_setting(
    key: str,
    *,
    allow_plaintext: bool = True,
    all_settings: Optional[Dict[str, str]] = None,
) -> str:
    """统一读取可加密配置：enc: 格式自动解密，解密失败统一返回空字符串（绝不返回密文）。"""
    raw = _read_setting(key, "", all_settings).strip()
    if not raw:
        return ""
    if is_encrypted(raw):
        try:
            return decrypt_data(raw)
        except Exception:
            return ""
    return raw if allow_plaintext else ""


def get_login_password() -> str:
    """获取登录密码（优先从数据库读取）"""
    password = get_setting("login_password")
    return password if password else config.get_login_password_default()


def get_legacy_gptmail_api_key() -> str:
    """兼容读取 legacy gptmail_api_key。"""
    return get_setting("gptmail_api_key")


def get_temp_mail_api_key() -> str:
    """获取正式临时邮箱 API Key，并兼容 legacy gptmail_api_key 回退。"""
    api_key = get_setting("temp_mail_api_key")
    if api_key:
        return api_key
    legacy_api_key = get_legacy_gptmail_api_key()
    if legacy_api_key:
        return legacy_api_key
    return config.get_temp_mail_api_key_default()


def get_gptmail_api_key() -> str:
    """legacy bridge 兼容入口。"""
    return get_temp_mail_api_key()


def normalize_temp_mail_provider_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return DEFAULT_TEMP_MAIL_PROVIDER
    if normalized.lower() in LEGACY_TEMP_MAIL_PROVIDER_NAMES:
        return LEGACY_TEMP_MAIL_PROVIDER
    return normalized


def get_supported_temp_mail_provider_names() -> set[str]:
    from outlook_web.temp_mail_registry import _REGISTRY

    return set(_REGISTRY.keys())


def is_supported_temp_mail_provider_name(value: str | None) -> bool:
    return normalize_temp_mail_provider_name(value) in get_supported_temp_mail_provider_names()


def validate_temp_mail_provider_name(value: str | None) -> str:
    normalized = normalize_temp_mail_provider_name(value)
    if normalized not in get_supported_temp_mail_provider_names():
        raise ValueError("临时邮箱 Provider 配置无效")
    return normalized


def get_temp_mail_provider() -> str:
    return normalize_temp_mail_provider_name(get_setting("temp_mail_provider", DEFAULT_TEMP_MAIL_PROVIDER))


def get_temp_mail_runtime_provider_name(provider_name: str | None = None) -> str:
    if provider_name is not None:
        return normalize_temp_mail_provider_name(provider_name)
    return get_temp_mail_provider()


def get_temp_mail_api_base_url() -> str:
    base_url = get_setting("temp_mail_api_base_url")
    return base_url if base_url else config.get_temp_mail_base_url()


def get_cf_worker_base_url() -> str:
    """获取 Cloudflare Temp Email Worker 独立部署地址（与 GPTMail 设置完全隔离）。"""
    return get_setting("cf_worker_base_url", "").strip()


def get_cf_worker_admin_key(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取 Cloudflare Worker ADMIN_PASSWORDS 中的密码值（自动解密 enc: 格式）。"""
    return _get_encrypted_setting("cf_worker_admin_key", allow_plaintext=True, all_settings=all_settings)


def get_temp_mail_domains() -> list[dict[str, Any]]:
    raw = get_setting("temp_mail_domains", "[]")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def get_temp_mail_default_domain() -> str:
    return get_setting("temp_mail_default_domain", "").strip()


def get_temp_mail_prefix_rules() -> dict[str, Any]:
    raw = get_setting("temp_mail_prefix_rules", "{}")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_cf_worker_domains() -> list[dict[str, Any]]:
    """获取 CF Worker 独立域名列表（v0.3 Tab 重构）。"""
    raw = get_setting("cf_worker_domains", "[]")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def get_cf_worker_default_domain() -> str:
    """获取 CF Worker 默认域名（v0.3 Tab 重构）。"""
    return get_setting("cf_worker_default_domain", "").strip()


def get_cf_worker_prefix_rules() -> dict[str, Any]:
    """获取 CF Worker 前缀规则（v0.3 Tab 重构）。"""
    _default_rules: dict[str, Any] = {
        "min_length": 1,
        "max_length": 32,
        "pattern": "^[a-z0-9][a-z0-9._-]*$",
    }
    raw = get_setting("cf_worker_prefix_rules", "{}")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _default_rules
    if not isinstance(value, dict) or not value:
        return _default_rules
    return value


def get_external_api_key(all_settings: Optional[Dict[str, str]] = None) -> str:
    """
    获取对外开放 API Key（自动解密 enc: 格式，兼容历史明文，解密失败返回空字符串）。
    """
    return _get_encrypted_setting("external_api_key", allow_plaintext=True, all_settings=all_settings)


def get_webhook_notification_enabled(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("webhook_notification_enabled", "false", all_settings).lower() == "true"


def get_webhook_notification_url(all_settings: Optional[Dict[str, str]] = None) -> str:
    return _read_setting("webhook_notification_url", "", all_settings).strip()


def get_webhook_notification_token(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取 Webhook Token（自动解密 enc: 格式，解密失败返回空字符串）。"""
    return _get_encrypted_setting("webhook_notification_token", allow_plaintext=True, all_settings=all_settings)


def get_webhook_notification_token_masked(
    head: int = 4,
    tail: int = 4,
    all_settings: Optional[Dict[str, str]] = None,
) -> str:
    """Webhook Token 脱敏展示：前 N 位 + 若干 * + 后 N 位。"""
    return mask_secret_value(get_webhook_notification_token(all_settings=all_settings), head=head, tail=tail)


def get_verification_ai_enabled(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("verification_ai_enabled", "false", all_settings).lower() == "true"


def get_verification_ai_base_url(all_settings: Optional[Dict[str, str]] = None) -> str:
    return _read_setting("verification_ai_base_url", "", all_settings).strip()


def get_verification_ai_model(all_settings: Optional[Dict[str, str]] = None) -> str:
    return _read_setting("verification_ai_model", "", all_settings).strip()


def get_verification_ai_api_key(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取验证码 AI API Key（自动解密 enc: 格式，兼容历史明文，解密失败返回空字符串）。"""
    return _get_encrypted_setting("verification_ai_api_key", allow_plaintext=True, all_settings=all_settings)


def get_external_api_key_masked(
    head: int = 4,
    tail: int = 4,
    all_settings: Optional[Dict[str, str]] = None,
) -> str:
    """对外 API Key 脱敏展示：前 N 位 + 若干 * + 后 N 位。"""
    return mask_secret_value(get_external_api_key(all_settings=all_settings), head=head, tail=tail)


# ── P1：公网模式安全配置 ──────────────────────────────


def get_external_api_public_mode(all_settings: Optional[Dict[str, str]] = None) -> bool:
    """公网模式是否开启（默认关闭，保持 P0 受控私有行为）。"""
    return _read_setting("external_api_public_mode", "false", all_settings).lower() == "true"


def get_external_api_ip_whitelist(all_settings: Optional[Dict[str, str]] = None) -> list:
    """IP 白名单列表（JSON 数组，支持 CIDR 如 '192.168.1.0/24'）。"""
    raw = _read_setting("external_api_ip_whitelist", "[]", all_settings)
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_external_api_rate_limit(all_settings: Optional[Dict[str, str]] = None) -> int:
    """每分钟每 IP 最大请求数（默认 60）。"""
    try:
        val = int(_read_setting("external_api_rate_limit_per_minute", "60", all_settings))
        return max(1, val)
    except (ValueError, TypeError):
        return 60


def get_external_api_disable_wait_message(all_settings: Optional[Dict[str, str]] = None) -> bool:
    """是否禁用 wait-message 端点（默认不禁用）。"""
    return _read_setting("external_api_disable_wait_message", "false", all_settings).lower() == "true"


def get_external_api_disable_raw_content(all_settings: Optional[Dict[str, str]] = None) -> bool:
    """是否禁用 raw 端点（默认不禁用）。"""
    return _read_setting("external_api_disable_raw_content", "false", all_settings).lower() == "true"


def get_pool_external_enabled(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("pool_external_enabled", "false", all_settings).lower() == "true"


def get_external_api_disable_pool_claim_random(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("external_api_disable_pool_claim_random", "false", all_settings).lower() == "true"


def get_external_api_disable_pool_claim_release(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("external_api_disable_pool_claim_release", "false", all_settings).lower() == "true"


def get_external_api_disable_pool_claim_complete(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("external_api_disable_pool_claim_complete", "false", all_settings).lower() == "true"


def get_external_api_disable_pool_stats(all_settings: Optional[Dict[str, str]] = None) -> bool:
    return _read_setting("external_api_disable_pool_stats", "false", all_settings).lower() == "true"


def get_ui_layout_v2(all_settings: Optional[Dict[str, str]] = None) -> dict:
    """读取前端布局状态"""
    raw = _read_setting("ui_layout_v2", "{}", all_settings)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def set_ui_layout_v2(layout: dict) -> None:
    """写入前端布局状态"""
    set_setting("ui_layout_v2", json.dumps(layout, ensure_ascii=False))


# ── 全局代理 & Telegram 代理配置 ──────────────────────────────


def get_global_proxy_enabled(all_settings: Optional[Dict[str, str]] = None) -> bool:
    """全局代理开关是否启用（默认关闭）。"""
    return _read_setting("global_proxy_enabled", "false", all_settings).lower() == "true"


def get_global_proxy_url(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取系统全局代理 URL（支持 enc: 加密存储与历史明文兼容）。"""
    return _get_encrypted_setting("global_proxy_url", allow_plaintext=True, all_settings=all_settings)


def get_effective_global_proxy_url(all_settings: Optional[Dict[str, str]] = None) -> str:
    """仅当全局代理已开启且地址非空时返回生效的全局代理 URL。"""
    if not get_global_proxy_enabled(all_settings=all_settings):
        return ""
    return get_global_proxy_url(all_settings=all_settings)


def get_telegram_proxy_url(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取 Telegram 推送使用的专属代理 URL（留空时可由代理引擎回退全局代理）。"""
    return _read_setting("telegram_proxy_url", "", all_settings).strip()


def set_telegram_proxy_url(url: str) -> bool:
    """保存 Telegram 代理 URL。"""
    return set_setting("telegram_proxy_url", url.strip())


def get_telegram_bot_token(all_settings: Optional[Dict[str, str]] = None) -> str:
    """获取 Telegram Bot Token（支持 enc: 加密格式）。"""
    return _get_encrypted_setting("telegram_bot_token", allow_plaintext=True, all_settings=all_settings)


# ---- OAuth Token 工具配置 ----


def get_oauth_tool_client_id() -> str:
    """Settings 表 → 环境变量 → 空字符串"""
    value = get_setting("oauth_tool_client_id")
    if value:
        return value
    return config.get_oauth_client_id_default()


def get_oauth_tool_client_secret() -> str:
    """Settings 表（自动解密/兼容历史明文） → 环境变量 → 空字符串"""
    value = _get_encrypted_setting("oauth_tool_client_secret", allow_plaintext=True)
    if value:
        return value
    return config.get_oauth_client_secret_default()


def get_oauth_tool_redirect_uri() -> str:
    """Settings 表 → 环境变量 → 空字符串"""
    value = get_setting("oauth_tool_redirect_uri")
    if value:
        return value
    return config.get_oauth_redirect_uri_default()


def get_oauth_tool_scope() -> str:
    """Settings 表 → 环境变量 → 默认 IMAP 兼容 scope"""
    value = get_setting("oauth_tool_scope")
    if value:
        return value
    return config.get_oauth_scope_default()


def get_oauth_tool_tenant() -> str:
    """Settings 表 → 环境变量 → 'consumers'"""
    value = get_setting("oauth_tool_tenant")
    if value:
        return value
    return config.get_oauth_tenant_default()


def get_oauth_tool_prompt_consent() -> bool:
    """Settings 表 → False"""
    value = get_setting("oauth_tool_prompt_consent", "false")
    return value.lower() == "true"
