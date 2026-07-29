from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from outlook_web.services import channel_capability_cache
from outlook_web.services import graph as graph_service
from outlook_web.services import imap as imap_service

CHANNEL_GRAPH_INBOX = "graph_inbox"
CHANNEL_GRAPH_JUNK = "graph_junk"
CHANNEL_IMAP_NEW = "imap_new"
CHANNEL_IMAP_OLD = "imap_old"

DEFAULT_VERIFICATION_CHANNEL_CHAIN = (
    CHANNEL_GRAPH_INBOX,
    CHANNEL_GRAPH_JUNK,
    CHANNEL_IMAP_NEW,
    CHANNEL_IMAP_OLD,
)
VALID_VERIFICATION_CHANNELS = set(DEFAULT_VERIFICATION_CHANNEL_CHAIN)

IMAP_SERVER_NEW = "outlook.live.com"
IMAP_SERVER_OLD = "outlook.office365.com"

# 验证码提取场景默认拉取最近 3 封，优先降低列表拉取开销。
VERIFICATION_FETCH_TOP = 3
IMAP_VERIFICATION_FOLDERS = ("inbox", "junkemail")


def _parse_message_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except Exception:
            return None

    text = str(value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromtimestamp(float(text), timezone.utc)
    except Exception:
        pass

    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _message_received_timestamp(message: Dict[str, Any]) -> int:
    for key in ("timestamp", "receivedDateTime", "date", "created_at", "received_at"):
        dt = _parse_message_datetime(message.get(key))
        if dt:
            return int(dt.timestamp())
    return 0


def _enrich_verification_message(item: Dict[str, Any], *, folder: str, channel: str) -> Dict[str, Any]:
    enriched = dict(item)
    enriched["folder"] = folder
    enriched["_verification_channel"] = channel

    timestamp = _message_received_timestamp(enriched)
    enriched["_received_timestamp"] = timestamp

    try:
        current_timestamp = int(enriched.get("timestamp") or 0)
    except Exception:
        current_timestamp = 0
    if timestamp > 0 and current_timestamp <= 0:
        enriched["timestamp"] = timestamp
    return enriched


def _message_sort_key(message: Dict[str, Any]) -> tuple:
    timestamp = int(message.get("_received_timestamp") or 0) or _message_received_timestamp(message)
    return (timestamp, str(message.get("id") or ""))


def _candidate_folders_for_channel(channel: str) -> List[str]:
    normalized = normalize_verification_channel(channel)
    if normalized == CHANNEL_GRAPH_INBOX:
        return ["inbox"]
    if normalized == CHANNEL_GRAPH_JUNK:
        return ["junkemail"]
    if normalized in (CHANNEL_IMAP_NEW, CHANNEL_IMAP_OLD):
        return list(IMAP_VERIFICATION_FOLDERS)
    return []


def _channel_group(channel: str) -> str:
    normalized = normalize_verification_channel(channel)
    if normalized in (CHANNEL_GRAPH_INBOX, CHANNEL_GRAPH_JUNK):
        return "graph"
    if normalized in (CHANNEL_IMAP_NEW, CHANNEL_IMAP_OLD):
        return "imap"
    return ""


def _verification_channel_phases(channel_plan: List[str]) -> List[List[str]]:
    groups: List[str] = []
    for channel in channel_plan:
        group = _channel_group(channel)
        if group and group not in groups:
            groups.append(group)

    phases: List[List[str]] = []
    for group in groups:
        phase = [channel for channel in channel_plan if _channel_group(channel) == group]
        if phase:
            phases.append(phase)
    return phases


def normalize_verification_channel(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in VALID_VERIFICATION_CHANNELS:
        return text
    return None


def build_verification_channel_plan(preferred_channel: Any) -> List[str]:
    preferred = normalize_verification_channel(preferred_channel)
    if not preferred:
        return list(DEFAULT_VERIFICATION_CHANNEL_CHAIN)
    return [preferred] + [channel for channel in DEFAULT_VERIFICATION_CHANNEL_CHAIN if channel != preferred]


def map_method_to_verification_channel(method: str, *, folder: str = "inbox") -> Optional[str]:
    method_text = str(method or "").strip().lower()
    folder_text = str(folder or "inbox").strip().lower()
    if method_text == "graph api":
        return CHANNEL_GRAPH_JUNK if folder_text == "junkemail" else CHANNEL_GRAPH_INBOX
    if method_text == "imap (new)":
        return CHANNEL_IMAP_NEW
    if method_text == "imap (old)":
        return CHANNEL_IMAP_OLD
    return None


def channel_method_label(channel: str) -> str:
    normalized = normalize_verification_channel(channel)
    if normalized == CHANNEL_GRAPH_INBOX:
        return "Graph API (Inbox)"
    if normalized == CHANNEL_GRAPH_JUNK:
        return "Graph API (Junk)"
    if normalized == CHANNEL_IMAP_NEW:
        return "IMAP (New)"
    if normalized == CHANNEL_IMAP_OLD:
        return "IMAP (Old)"
    return ""


def is_outlook_oauth_account(account: Dict[str, Any]) -> bool:
    account_type = str(account.get("account_type") or "outlook").strip().lower()
    if account_type != "outlook":
        return False
    return bool(str(account.get("client_id") or "").strip()) and bool(str(account.get("refresh_token") or "").strip())


def fetch_emails_for_channel(
    *,
    account: Dict[str, Any],
    channel: str,
    proxy_url: str = "",
    folder: str = "",
    skip: int = 0,
    top: int = 20,
) -> Dict[str, Any]:
    normalized = normalize_verification_channel(channel)
    if not normalized:
        return {
            "success": False,
            "error": {
                "code": "INVALID_CHANNEL",
                "message": "invalid verification channel",
            },
        }

    if normalized in (CHANNEL_GRAPH_INBOX, CHANNEL_GRAPH_JUNK):
        folder_name = "junkemail" if normalized == CHANNEL_GRAPH_JUNK else "inbox"
        graph_result = graph_service.get_emails_graph(
            str(account.get("client_id") or ""),
            str(account.get("refresh_token") or ""),
            folder=folder_name,
            skip=int(skip or 0),
            top=int(top or 20),
            proxy_url=proxy_url,
        )
        if not graph_result.get("success"):
            return {
                "success": False,
                "auth_expired": bool(graph_result.get("auth_expired")),
                "error": graph_result.get("error"),
                "channel": normalized,
            }

        emails = []
        for item in graph_result.get("emails", []) or []:
            emails.append(_enrich_verification_message(item, folder=folder_name, channel=normalized))
        return {
            "success": True,
            "emails": emails,
            "new_refresh_token": graph_result.get("new_refresh_token"),
            "channel": normalized,
        }

    imap_server = IMAP_SERVER_NEW if normalized == CHANNEL_IMAP_NEW else IMAP_SERVER_OLD
    folder_name = str(folder or "inbox").strip().lower() or "inbox"
    imap_result = imap_service.get_emails_imap_with_server(
        str(account.get("email") or ""),
        str(account.get("client_id") or ""),
        str(account.get("refresh_token") or ""),
        folder=folder_name,
        skip=int(skip or 0),
        top=int(top or 20),
        server=imap_server,
    )
    if not imap_result.get("success"):
        return {
            "success": False,
            "error": imap_result.get("error"),
            "channel": normalized,
        }

    emails = []
    for item in imap_result.get("emails", []) or []:
        emails.append(_enrich_verification_message(item, folder=folder_name, channel=normalized))
    return {"success": True, "emails": emails, "channel": normalized}


def fetch_email_detail_for_channel(
    *,
    account: Dict[str, Any],
    channel: str,
    message_id: str,
    proxy_url: str = "",
    folder: str = "",
) -> Optional[Dict[str, Any]]:
    normalized = normalize_verification_channel(channel)
    if not normalized or not message_id:
        return None

    if normalized in (CHANNEL_GRAPH_INBOX, CHANNEL_GRAPH_JUNK):
        return graph_service.get_email_detail_graph(
            str(account.get("client_id") or ""),
            str(account.get("refresh_token") or ""),
            str(message_id),
            proxy_url,
        )

    folder_name = str(folder or "inbox").strip().lower() or "inbox"
    if normalized == CHANNEL_IMAP_NEW:
        return imap_service.get_email_detail_imap_with_server(
            str(account.get("email") or ""),
            str(account.get("client_id") or ""),
            str(account.get("refresh_token") or ""),
            str(message_id),
            folder_name,
            IMAP_SERVER_NEW,
        )

    return imap_service.get_email_detail_imap_with_server(
        str(account.get("email") or ""),
        str(account.get("client_id") or ""),
        str(account.get("refresh_token") or ""),
        str(message_id),
        folder_name,
        IMAP_SERVER_OLD,
    )


def fetch_emails_and_detail_for_channel(
    *,
    account: Dict[str, Any],
    channel: str,
    proxy_url: str = "",
    folder: str = "",
    skip: int = 0,
    top: int = 20,
) -> Dict[str, Any]:
    """IMAP 渠道返回 emails+detail（连接复用），Graph 只返回 emails。"""
    normalized = normalize_verification_channel(channel)
    if not normalized:
        return {
            "success": False,
            "error": {
                "code": "INVALID_CHANNEL",
                "message": "invalid verification channel",
            },
            "channel": "",
        }

    if normalized in (CHANNEL_GRAPH_INBOX, CHANNEL_GRAPH_JUNK):
        return fetch_emails_for_channel(
            account=account,
            channel=normalized,
            proxy_url=proxy_url,
            folder=folder,
            skip=skip,
            top=top,
        )

    server = IMAP_SERVER_NEW if normalized == CHANNEL_IMAP_NEW else IMAP_SERVER_OLD
    folder_name = str(folder or "inbox").strip().lower() or "inbox"
    result = imap_service.fetch_and_detail_imap_with_server(
        str(account.get("email") or ""),
        str(account.get("client_id") or ""),
        str(account.get("refresh_token") or ""),
        folder=folder_name,
        skip=int(skip or 0),
        top=int(top or 20),
        server=server,
    )

    # 兼容回退：当连接复用路径失败时，降级到原 list + detail 两次调用。
    if not result.get("success"):
        legacy_list = imap_service.get_emails_imap_with_server(
            str(account.get("email") or ""),
            str(account.get("client_id") or ""),
            str(account.get("refresh_token") or ""),
            folder=folder_name,
            skip=int(skip or 0),
            top=int(top or 20),
            server=server,
        )
        if not legacy_list.get("success"):
            return {
                "success": False,
                "error": legacy_list.get("error") or result.get("error"),
                "channel": normalized,
            }

        legacy_emails = [
            _enrich_verification_message(item, folder=folder_name, channel=normalized)
            for item in (legacy_list.get("emails") or [])
        ]

        legacy_detail = None
        if legacy_emails:
            latest_id = str((legacy_emails[0] or {}).get("id") or "")
            if latest_id:
                legacy_detail = imap_service.get_email_detail_imap_with_server(
                    str(account.get("email") or ""),
                    str(account.get("client_id") or ""),
                    str(account.get("refresh_token") or ""),
                    latest_id,
                    folder_name,
                    server,
                )

        return {
            "success": True,
            "emails": legacy_emails,
            "detail": legacy_detail,
            "channel": normalized,
        }

    emails = [
        _enrich_verification_message(item, folder=folder_name, channel=normalized) for item in (result.get("emails") or [])
    ]
    return {
        "success": True,
        "emails": emails,
        "detail": result.get("detail"),
        "channel": normalized,
    }


def _get_channel_display_name(channel: str) -> str:
    return {
        "graph_inbox": "Graph (Inbox)",
        "graph_junk": "Graph (Junk)",
        "imap_new": "IMAP (New)",
        "imap_old": "IMAP (Old)",
    }.get(channel, channel)


def _is_extraction_success(extracted: Dict[str, Any], expected_field: Any) -> bool:
    if expected_field:
        return bool(extracted.get(expected_field))
    return bool(extracted.get("verification_code") or extracted.get("verification_link"))


def _should_try_older_email_after_failed_extraction(
    extracted: Dict[str, Any],
    expected_field: Any,
) -> bool:
    """当指定 expected_field 时，仅允许在较新邮件为「仅链接/仅验证码」时继续尝试更早邮件。"""
    if not expected_field:
        return True

    field = str(expected_field).strip()
    has_code = bool(extracted.get("verification_code"))
    has_link = bool(extracted.get("verification_link"))

    if field == "verification_code":
        return has_link and not has_code
    if field == "verification_link":
        return has_code and not has_link
    return False


def _build_email_obj_from_channel_detail(*, detail: Dict[str, Any], latest: Dict[str, Any]) -> Dict[str, Any]:
    # Graph 详情
    if "body" in detail and isinstance(detail.get("body"), dict):
        body_content = detail.get("body") or {}
        content_type = str(body_content.get("contentType") or "text").lower()
        body_content_text = str(body_content.get("content") or "")

        from_obj = detail.get("from") or {}
        if isinstance(from_obj, dict):
            from_addr = (from_obj.get("emailAddress") or {}).get("address") or from_obj.get("address") or ""
        else:
            from_addr = str(from_obj or "")

        return {
            "subject": str(detail.get("subject") or latest.get("subject") or ""),
            "body": body_content_text if content_type == "text" else "",
            "body_html": body_content_text if content_type == "html" else "",
            "raw_content": str(detail.get("raw_content") or ""),
            "from": str(from_addr or latest.get("from") or ""),
            "date": str(detail.get("receivedDateTime") or latest.get("date") or ""),
        }

    return {
        "subject": str(detail.get("subject") or latest.get("subject") or ""),
        "body": str(detail.get("body") or ""),
        "body_html": str(detail.get("body_html") or ""),
        "raw_content": str(detail.get("raw_content") or ""),
        "from": str(detail.get("from") or latest.get("from") or ""),
        "date": str(detail.get("date") or latest.get("date") or ""),
    }


def extract_verification_for_outlook(
    *,
    account: Dict[str, Any],
    proxy_url: str = "",
    resolved_policy: Dict[str, Any],
    code_source: str = "all",
    expected_field: Any = None,
    from_contains: str = "",
    subject_contains: str = "",
    since_minutes: Any = None,
    baseline_timestamp: Any = None,
) -> Dict[str, Any]:
    """Outlook OAuth 账号验证码提取统一入口（Web 端和 External API 均调用此函数）。"""
    account_email = str(account.get("email") or "")
    preferred = normalize_verification_channel(account.get("preferred_verification_channel"))
    channel_plan = build_verification_channel_plan(preferred)
    channel_plan = channel_capability_cache.filter_channel_plan(account_email, channel_plan)

    if preferred in (CHANNEL_IMAP_NEW, CHANNEL_IMAP_OLD):
        channel_plan = [preferred] if preferred in channel_plan else []

    # Graph 权限预检：无 Mail.Read 权限时直接跳过 Graph 渠道。
    if any(ch.startswith("graph_") for ch in channel_plan):
        try:
            precheck = graph_service.get_access_token_graph_result(
                str(account.get("client_id") or ""),
                str(account.get("refresh_token") or ""),
                proxy_url or None,
            )
            if precheck.get("new_refresh_token"):
                account["refresh_token"] = str(precheck.get("new_refresh_token") or "")
            if precheck.get("success") and not graph_service.has_mail_read_permission(precheck.get("scope", "")):
                channel_plan = [ch for ch in channel_plan if not ch.startswith("graph_")]
        except Exception:
            pass

    any_channel_read_success = False
    graph_auth_expired = False
    upstream_errors: Dict[str, Any] = {}
    last_extracted = None
    precheck_obj = locals().get("precheck")
    new_refresh_token = str((precheck_obj or {}).get("new_refresh_token") or "")
    verification_attempted = False
    last_log_channel = "unknown"
    emails: List[Dict[str, Any]] = []
    detail_cache: Dict[tuple, Dict[str, Any]] = {}

    for channel_phase in _verification_channel_phases(channel_plan):
        candidate_emails: List[Dict[str, Any]] = []
        for channel in channel_phase:
            last_log_channel = channel or last_log_channel
            channel_available = False
            channel_folders = _candidate_folders_for_channel(channel) or ["inbox"]
            for folder in channel_folders:
                if _channel_group(channel) == "imap":
                    channel_result = fetch_emails_and_detail_for_channel(
                        account=account,
                        channel=channel,
                        proxy_url=proxy_url,
                        folder=folder,
                        top=VERIFICATION_FETCH_TOP,
                    )
                else:
                    channel_result = fetch_emails_for_channel(
                        account=account,
                        channel=channel,
                        proxy_url=proxy_url,
                        folder=folder,
                        top=VERIFICATION_FETCH_TOP,
                    )

                if not channel_result.get("success"):
                    error_key = channel if len(channel_folders) == 1 else f"{channel}:{folder}"
                    upstream_errors[error_key] = channel_result.get("error")
                    if channel.startswith("graph_") and channel_result.get("auth_expired"):
                        graph_auth_expired = True
                    continue

                channel_available = True
                any_channel_read_success = True

                if channel_result.get("new_refresh_token"):
                    new_refresh_token = str(channel_result.get("new_refresh_token") or "")
                    account["refresh_token"] = new_refresh_token

                channel_emails = channel_result.get("emails", []) or []
                candidate_emails.extend(channel_emails)

                detail = channel_result.get("detail")
                if detail:
                    detail_id = str(detail.get("id") or "")
                    if not detail_id and channel_emails:
                        detail_id = str((channel_emails[0] or {}).get("id") or "")
                    if detail_id:
                        folder_key = str(folder or "inbox").strip().lower() or "inbox"
                        detail_cache[(channel, folder_key, detail_id)] = detail

            if normalize_verification_channel(channel):
                channel_capability_cache.set_status(account_email, channel, available=channel_available)

        phase_emails = candidate_emails
        if from_contains or subject_contains or since_minutes or baseline_timestamp:
            from outlook_web.services.external_api import filter_messages

            phase_emails = filter_messages(
                phase_emails,
                from_contains=from_contains,
                subject_contains=subject_contains,
                since_minutes=since_minutes,
                baseline_timestamp=baseline_timestamp,
            )

        if phase_emails:
            emails = phase_emails
            break

    if emails:
        sorted_emails = sorted(emails, key=_message_sort_key, reverse=True)

        for latest in sorted_emails:
            channel = str(latest.get("_verification_channel") or "")
            folder = str(latest.get("folder") or "inbox").strip().lower() or "inbox"
            latest_id = str(latest.get("id") or "")
            last_log_channel = channel or last_log_channel

            detail = detail_cache.get((channel, folder, latest_id))
            if detail is None:
                detail = fetch_email_detail_for_channel(
                    account=account,
                    channel=channel,
                    message_id=latest_id,
                    proxy_url=proxy_url,
                    folder=folder,
                )

            if not detail:
                continue

            verification_attempted = True

            email_obj = _build_email_obj_from_channel_detail(detail=detail, latest=latest)

            from outlook_web.services.verification_extractor import (
                apply_confidence_gate,
                enhance_verification_with_ai_fallback,
                extract_verification_info_with_options,
            )

            extracted = extract_verification_info_with_options(
                email_obj,
                code_regex=resolved_policy.get("code_regex"),
                code_length=resolved_policy.get("code_length"),
                code_source=code_source,
                enforce_mutual_exclusion=False,
            )
            extracted = enhance_verification_with_ai_fallback(
                email=email_obj,
                extracted=extracted,
                code_regex=resolved_policy.get("code_regex"),
                code_length=resolved_policy.get("code_length"),
                code_source=code_source,
                enforce_mutual_exclusion=False,
            )
            extracted = apply_confidence_gate(extracted, enforce_mutual_exclusion=False)

            extracted.update(
                {
                    "email": account.get("email", ""),
                    "matched_email_id": latest.get("id", ""),
                    "from": email_obj["from"],
                    "subject": email_obj["subject"],
                    "received_at": email_obj["date"],
                    "folder": folder,
                    "method": _get_channel_display_name(channel),
                }
            )
            extracted["_log_channel"] = (
                "ai_fallback" if extracted.get("_used_ai") and _is_extraction_success(extracted, expected_field) else channel
            )
            extracted["_log_used_ai"] = bool(extracted.get("_used_ai"))
            last_extracted = extracted

            if _is_extraction_success(extracted, expected_field):
                try:
                    from outlook_web.repositories import accounts as accounts_repo

                    accounts_repo.update_preferred_verification_channel(int(account["id"]), channel)
                except Exception:
                    pass

                return {
                    "success": True,
                    "data": extracted,
                    "channel_used": channel,
                    "_log_channel": extracted.get("_log_channel") or channel,
                    "_log_used_ai": bool(extracted.get("_used_ai")),
                    "new_refresh_token": new_refresh_token,
                }

            if expected_field and not _should_try_older_email_after_failed_extraction(
                extracted,
                expected_field,
            ):
                break

    if not any_channel_read_success:
        return {
            "success": False,
            "error_code": "ACCOUNT_AUTH_EXPIRED",
            "error_message": "所有渠道认证失败",
            "error_status": 401,
            "upstream_errors": upstream_errors,
            "graph_auth_expired": graph_auth_expired,
            "_log_channel": last_log_channel,
            "_log_used_ai": False,
        }

    if last_extracted or verification_attempted:
        return {
            "success": False,
            "error_code": "VERIFICATION_NOT_FOUND",
            "error_message": "未找到验证码或验证链接",
            "error_status": 404,
            "upstream_errors": upstream_errors,
            "new_refresh_token": new_refresh_token,
            "_log_channel": (last_extracted or {}).get("_log_channel") or last_log_channel,
            "_log_used_ai": bool((last_extracted or {}).get("_used_ai")),
        }

    return {
        "success": False,
        "error_code": "EMAIL_NOT_FOUND",
        "error_message": "未找到匹配邮件",
        "error_status": 404,
        "upstream_errors": upstream_errors,
        "new_refresh_token": new_refresh_token,
        "_log_channel": last_log_channel,
        "_log_used_ai": False,
    }
