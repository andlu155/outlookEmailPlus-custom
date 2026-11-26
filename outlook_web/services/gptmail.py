from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from outlook_web import config
from outlook_web.repositories.settings import (
    get_temp_mail_api_base_url,
)
from outlook_web.repositories.settings import get_temp_mail_api_key as _get_temp_mail_api_key
from outlook_web.services import proxy as proxy_service


def get_temp_mail_api_key() -> str:
    """正式临时邮箱 API Key getter，供 bridge 统一调用。"""
    return _get_temp_mail_api_key()


def get_gptmail_api_key() -> str:
    """legacy alias，仅供兼容 bridge 与旧测试 patch 使用。"""
    return get_temp_mail_api_key()


def gptmail_request(
    method: str,
    endpoint: str,
    params: dict = None,
    json_data: dict = None,
) -> Optional[Dict]:
    """
    发送 legacy 临时邮箱 bridge API 请求

    返回格式：
    - 成功：{"success": True, "data": {...}}
    - 失败：{"success": False, "error": "错误信息", "error_type": "错误类型", "details": "详细信息"}
    """
    try:
        try:
            base_url = get_temp_mail_api_base_url() or config.get_temp_mail_base_url()
        except Exception:
            base_url = config.get_temp_mail_base_url()
        url = f"{base_url}{endpoint}"
        api_key = get_gptmail_api_key()

        # 检查 API Key 是否配置
        if not api_key:
            return {
                "success": False,
                "error": "临时邮箱 API Key 未配置",
                "error_type": "CONFIG_ERROR",
                "details": "请在系统设置中配置临时邮箱 API Key",
            }

        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

        proxy_url, force_direct = proxy_service.resolve_system_proxy(target_url=url)
        proxy_kwargs = proxy_service.build_requests_proxy_kwargs(proxy_url, force_direct=force_direct)

        # 发送请求
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30, **proxy_kwargs)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data, timeout=30, **proxy_kwargs)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, params=params, timeout=30, **proxy_kwargs)
        else:
            return {
                "success": False,
                "error": f"不支持的请求方法: {method}",
                "error_type": "METHOD_ERROR",
                "details": "仅支持 GET、POST、DELETE 方法",
            }

        # 处理响应
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            return {
                "success": False,
                "error": "API Key 无效或已过期",
                "error_type": "AUTH_ERROR",
                "details": f"HTTP {response.status_code}: 请检查 API Key 是否正确",
            }
        elif response.status_code == 403:
            return {
                "success": False,
                "error": "API 访问被拒绝",
                "error_type": "PERMISSION_ERROR",
                "details": f"HTTP {response.status_code}: 请检查 API Key 权限",
            }
        elif response.status_code == 429:
            return {
                "success": False,
                "error": "API 请求频率超限",
                "error_type": "RATE_LIMIT_ERROR",
                "details": f"HTTP {response.status_code}: 请稍后重试",
            }
        elif response.status_code >= 500:
            return {
                "success": False,
                "error": "临时邮箱服务暂时不可用",
                "error_type": "SERVER_ERROR",
                "details": f"HTTP {response.status_code}: 服务器错误，请稍后重试",
            }
        else:
            return {
                "success": False,
                "error": f"API 请求失败",
                "error_type": "HTTP_ERROR",
                "details": f"HTTP {response.status_code}: {response.text[:200]}",
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "API 请求超时",
            "error_type": "TIMEOUT_ERROR",
            "details": "请求超过 30 秒未响应，请检查网络连接或稍后重试",
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error": "无法连接到临时邮箱服务",
            "error_type": "CONNECTION_ERROR",
            "details": f"网络连接失败: {str(e)[:200]}",
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": "网络请求异常",
            "error_type": "REQUEST_ERROR",
            "details": f"请求失败: {str(e)[:200]}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": "未知错误",
            "error_type": "UNKNOWN_ERROR",
            "details": f"异常: {str(e)[:200]}",
        }


def generate_temp_email(prefix: str = None, domain: str = None) -> Tuple[Optional[str], Optional[str]]:
    """
    生成临时邮箱地址

    返回：
    - (email_addr, None) - 成功
    - (None, error_message) - 失败，包含详细错误信息
    """
    json_data = {}
    if prefix:
        json_data["prefix"] = prefix
    if domain:
        json_data["domain"] = domain

    if json_data:
        result = gptmail_request("POST", "/api/generate-email", json_data=json_data)
    else:
        result = gptmail_request("GET", "/api/generate-email")

    if not result:
        return None, "临时邮箱 API 请求失败"

    if result.get("success"):
        email = result.get("data", {}).get("email")
        if email:
            return email, None
        else:
            return None, "API 返回数据格式错误：缺少 email 字段"
    else:
        # 返回详细的错误信息
        error = result.get("error", "未知错误")
        error_type = result.get("error_type", "UNKNOWN")
        details = result.get("details", "")

        # 组合错误信息
        if details:
            error_message = f"{error}（{details}）"
        else:
            error_message = error

        return None, error_message


def _normalize_bridge_failure_result(result: Optional[Dict], *, default_error: str) -> Dict[str, Any]:
    payload = dict(result or {})
    payload["success"] = False
    payload["error"] = str(payload.get("error") or default_error)
    payload["error_type"] = str(payload.get("error_type") or "UNKNOWN_ERROR")
    payload["details"] = str(payload.get("details") or "")
    return payload


def _fetch_temp_emails_bridge_result(email_addr: str) -> Dict[str, Any]:
    result = gptmail_request("GET", "/api/emails", params={"email": email_addr})
    if result and result.get("success"):
        emails = (result.get("data") or {}).get("emails", [])
        return {"success": True, "emails": emails}
    return _normalize_bridge_failure_result(result, default_error="临时邮箱邮件列表读取失败")


def _fetch_temp_email_detail_bridge_result(email_addr: str, message_id: str) -> Dict[str, Any]:
    params = {"email": email_addr} if email_addr else None
    result = gptmail_request("GET", f"/api/email/{message_id}", params=params)
    if result and result.get("success"):
        return {"success": True, "data": result.get("data")}
    return _normalize_bridge_failure_result(result, default_error="临时邮箱邮件详情读取失败")


def get_temp_emails_from_api(email_addr: str) -> Optional[List[Dict]]:
    """从 legacy 临时邮箱 bridge 获取邮件列表"""
    result = _fetch_temp_emails_bridge_result(email_addr)
    if result.get("success"):
        return result.get("emails", [])
    return None


def get_temp_email_detail_from_api(email_addr: str, message_id: str) -> Optional[Dict]:
    """
    从 legacy 临时邮箱 bridge 获取邮件详情。

    当前 legacy bridge 仍主要依赖全局 message_id；这里保留 mailbox-scoped 签名，
    让上层 service/provider 始终显式携带 email_addr，避免把“全局唯一”假设继续向
    本地缓存层扩散。若上游支持邮箱作用域过滤，会优先附带 email 参数。
    """
    result = _fetch_temp_email_detail_bridge_result(email_addr, message_id)
    if result.get("success"):
        return result.get("data")
    return None


_ORIGINAL_GET_TEMP_EMAILS_FROM_API = get_temp_emails_from_api
_ORIGINAL_GET_TEMP_EMAIL_DETAIL_FROM_API = get_temp_email_detail_from_api


def list_temp_emails_result_from_api(email_addr: str) -> Dict[str, Any]:
    """
    提供给 provider/service 的结构化结果，显式区分：
    - success=True + emails=[]
    - success=False 上游读取失败

    若测试或兼容层 patch 了 legacy helper，则优先复用该 patch 行为，避免把既有
    provider/controller regression 全部强制改写。
    """
    if get_temp_emails_from_api is not _ORIGINAL_GET_TEMP_EMAILS_FROM_API:
        legacy_result = get_temp_emails_from_api(email_addr)
        if legacy_result is not None:
            return {"success": True, "emails": legacy_result}
        return {
            "success": False,
            "error": "临时邮箱邮件列表读取失败",
            "error_type": "LEGACY_BRIDGE_ERROR",
            "details": "legacy helper returned None",
        }
    return _fetch_temp_emails_bridge_result(email_addr)


def get_temp_email_detail_result_from_api(email_addr: str, message_id: str) -> Dict[str, Any]:
    """
    提供给 provider/service 的结构化结果，显式区分：
    - success=True + data=None: 真正未找到该邮件
    - success=False: 上游读取失败
    """
    if get_temp_email_detail_from_api is not _ORIGINAL_GET_TEMP_EMAIL_DETAIL_FROM_API:
        legacy_result = get_temp_email_detail_from_api(email_addr, message_id)
        if legacy_result is not None:
            return {"success": True, "data": legacy_result}
        return {
            "success": False,
            "error": "临时邮箱邮件详情读取失败",
            "error_type": "LEGACY_BRIDGE_ERROR",
            "details": "legacy helper returned None",
        }
    return _fetch_temp_email_detail_bridge_result(email_addr, message_id)


def delete_temp_email_from_api(email_addr: str, message_id: str) -> bool:
    """
    从 legacy 临时邮箱 bridge 删除邮件。

    legacy upstream 可能仍只按全局 message_id 删除；email_addr 作为显式上下文保留，
    用于尽量贴近 mailbox-scoped 契约，并为未来上游补齐邮箱作用域预留参数。
    """
    params = {"email": email_addr} if email_addr else None
    result = gptmail_request("DELETE", f"/api/email/{message_id}", params=params)
    return bool(result and result.get("success", False))


def clear_temp_emails_from_api(email_addr: str) -> bool:
    """清空 legacy 临时邮箱 bridge 邮箱的所有邮件"""
    result = gptmail_request("DELETE", "/api/emails/clear", params={"email": email_addr})
    return bool(result and result.get("success", False))
