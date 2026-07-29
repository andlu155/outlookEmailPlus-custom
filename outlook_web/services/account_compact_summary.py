from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from outlook_web.repositories import accounts as accounts_repo
from outlook_web.repositories import groups as groups_repo
from outlook_web.services.verification_code_extraction import (
    VerificationInput,
    apply_confidence_gate,
    extract_verification,
    policy_from_resolved,
)

COMPACT_SUMMARY_FIELDS = (
    "latest_email_subject",
    "latest_email_from",
    "latest_email_folder",
    "latest_email_received_at",
    "latest_verification_code",
    "latest_verification_folder",
    "latest_verification_received_at",
)


def empty_compact_summary() -> Dict[str, str]:
    return {field: "" for field in COMPACT_SUMMARY_FIELDS}


def parse_received_at(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return datetime.min.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_summary_from_account_row(account: Optional[Dict[str, Any]]) -> Dict[str, str]:
    summary = empty_compact_summary()
    if not account:
        return summary
    for field in COMPACT_SUMMARY_FIELDS:
        summary[field] = str(account.get(field) or "")
    return summary


def normalize_message_summary(message: Optional[Dict[str, Any]], *, folder: str = "") -> Dict[str, str]:
    payload = message or {}

    sender = payload.get("from")
    if isinstance(sender, dict):
        sender = sender.get("emailAddress", {}).get("address") or sender.get("address") or sender.get("email") or ""

    received_at = (
        payload.get("received_at") or payload.get("receivedDateTime") or payload.get("date") or payload.get("created_at") or ""
    )

    return {
        "message_id": str(payload.get("message_id") or payload.get("id") or ""),
        "subject": str(payload.get("subject") or ""),
        "from": str(sender or payload.get("from_address") or payload.get("sender") or ""),
        "folder": str(payload.get("folder") or folder or ""),
        "received_at": str(received_at or ""),
        "body_preview": str(payload.get("body_preview") or payload.get("bodyPreview") or payload.get("content_preview") or ""),
    }


def _pick_latest_message(messages: Iterable[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    normalized = [item for item in messages if item]
    if not normalized:
        return None
    return max(normalized, key=lambda item: parse_received_at(item.get("received_at")))


def _resolve_compact_verification_policy(account_id: int):
    account = accounts_repo.get_account_by_id(account_id)
    group = None
    if account and account.get("group_id"):
        try:
            group_id = int(account.get("group_id"))
        except (TypeError, ValueError):
            group_id = 0
        if group_id > 0:
            group = groups_repo.get_group_by_id(group_id)

    resolved = groups_repo.resolve_group_verification_policy(
        group=group,
        default_code_length="6-6",
        apply_default=True,
    )
    return policy_from_resolved(
        resolved,
        code_source="all",
        enforce_mutual_exclusion=False,
        apply_confidence_gate=True,
    )


def _pick_latest_verification_message(
    messages: Iterable[Dict[str, Any]],
    *,
    verification_policy,
) -> Optional[Dict[str, str]]:
    latest_match: Optional[Dict[str, str]] = None

    for message in messages:
        if not message:
            continue

        candidate_payload = VerificationInput(
            subject=str(message.get("subject") or ""),
            body=str(message.get("body_preview") or ""),
            body_preview=str(message.get("body_preview") or ""),
        )

        result = extract_verification(candidate_payload, verification_policy)
        result = apply_confidence_gate(result, enforce_mutual_exclusion=False)

        verification_code = str(result.get("verification_code") or "").strip()
        if not verification_code:
            continue

        candidate = dict(message)
        candidate["verification_code"] = verification_code

        if latest_match is None:
            latest_match = candidate
            continue

        if parse_received_at(candidate.get("received_at")) >= parse_received_at(latest_match.get("received_at")):
            latest_match = candidate

    return latest_match


def _merge_latest_email(summary: Dict[str, str], message: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not message:
        return summary

    candidate_time = parse_received_at(message.get("received_at"))
    current_time = parse_received_at(summary.get("latest_email_received_at"))
    if candidate_time < current_time:
        return summary

    merged = dict(summary)
    merged.update(
        {
            "latest_email_subject": str(message.get("subject") or ""),
            "latest_email_from": str(message.get("from") or ""),
            "latest_email_folder": str(message.get("folder") or ""),
            "latest_email_received_at": str(message.get("received_at") or ""),
        }
    )
    return merged


def _merge_latest_verification(
    summary: Dict[str, str],
    *,
    verification_code: str,
    folder: str,
    received_at: str,
) -> Dict[str, str]:
    code = str(verification_code or "").strip()
    if not code:
        return summary

    candidate_time = parse_received_at(received_at)
    current_time = parse_received_at(summary.get("latest_verification_received_at"))
    if candidate_time < current_time:
        return summary

    merged = dict(summary)
    merged.update(
        {
            "latest_verification_code": code,
            "latest_verification_folder": str(folder or ""),
            "latest_verification_received_at": str(received_at or ""),
        }
    )
    return merged


def update_summary_from_message_list(
    account_id: int, messages: Iterable[Dict[str, Any]], *, folder: str = ""
) -> Dict[str, str]:
    current = accounts_repo.get_account_compact_summary(account_id) or empty_compact_summary()
    normalized_messages = [normalize_message_summary(message, folder=folder) for message in messages or []]
    verification_policy = _resolve_compact_verification_policy(account_id)
    latest = _pick_latest_message(normalized_messages)
    latest_verification = _pick_latest_verification_message(normalized_messages, verification_policy=verification_policy)
    updated = _merge_latest_email(current, latest)
    if latest_verification:
        updated = _merge_latest_verification(
            updated,
            verification_code=str(latest_verification.get("verification_code") or ""),
            folder=str(latest_verification.get("folder") or folder or ""),
            received_at=str(latest_verification.get("received_at") or ""),
        )
    accounts_repo.update_account_compact_summary(account_id, updated)
    return updated


def update_summary_from_verification(
    account_id: int,
    *,
    message: Optional[Dict[str, Any]],
    verification_code: str,
    folder: str = "",
) -> Dict[str, str]:
    current = accounts_repo.get_account_compact_summary(account_id) or empty_compact_summary()
    normalized = normalize_message_summary(message, folder=folder)
    updated = _merge_latest_email(current, normalized)
    updated = _merge_latest_verification(
        updated,
        verification_code=verification_code,
        folder=normalized.get("folder") or folder,
        received_at=normalized.get("received_at") or "",
    )
    accounts_repo.update_account_compact_summary(account_id, updated)
    return updated
