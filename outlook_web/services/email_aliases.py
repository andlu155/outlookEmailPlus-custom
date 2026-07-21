"""Discover Outlook-style plus-address aliases from received mail recipients.

Only aliases that have already received mail (appear in To/Cc) can be found.
Unused plus-tags never show up here.
"""

from __future__ import annotations

from typing import Any, Iterable

# Soft operational cap shown in UI; Outlook does not hard-limit to this.
DEFAULT_SOFT_LIMIT = 5


def extract_plus_aliases(primary_email: str, recipient_addresses: Iterable[str]) -> list[str]:
    """Return unique plus-aliases that belong to primary_email (case-insensitive)."""
    primary = str(primary_email or "").strip().lower()
    if not primary or "@" not in primary:
        return []

    local, domain = primary.rsplit("@", 1)
    if not local or not domain:
        return []

    found: set[str] = set()
    for raw in recipient_addresses:
        addr = str(raw or "").strip().lower()
        if not addr or "@" not in addr:
            continue
        a_local, a_domain = addr.rsplit("@", 1)
        if a_domain != domain or "+" not in a_local:
            continue
        base = a_local[: a_local.index("+")]
        if base == local and a_local != local:
            found.add(f"{a_local}@{a_domain}")

    return sorted(found)


def _recipient_addresses_from_graph_message(message: dict[str, Any]) -> list[str]:
    addresses: list[str] = []
    for field in ("toRecipients", "ccRecipients"):
        for item in message.get(field) or []:
            if not isinstance(item, dict):
                continue
            email_obj = item.get("emailAddress") or {}
            if isinstance(email_obj, dict):
                addr = str(email_obj.get("address") or "").strip()
                if addr:
                    addresses.append(addr)
    return addresses


def collect_aliases_from_graph_messages(
    primary_email: str,
    messages: Iterable[dict[str, Any]],
) -> tuple[list[str], int]:
    """Scan Graph message objects; return (aliases, scanned_count)."""
    recipients: list[str] = []
    scanned = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        scanned += 1
        recipients.extend(_recipient_addresses_from_graph_message(message))
    return extract_plus_aliases(primary_email, recipients), scanned


def build_alias_summary(
    *,
    primary_email: str,
    aliases: list[str],
    scanned_messages: int,
    soft_limit: int = DEFAULT_SOFT_LIMIT,
    source: str = "graph",
) -> dict[str, Any]:
    limit = max(1, int(soft_limit or DEFAULT_SOFT_LIMIT))
    unique = list(aliases)
    return {
        "primary_email": primary_email,
        "aliases": unique,
        "used": len(unique),
        "soft_limit": limit,
        "remaining": max(0, limit - len(unique)),
        "scanned_messages": int(scanned_messages or 0),
        "source": source,
        "note": "仅统计已收到邮件的 + 子地址；未使用过的分裂地址不会出现。建议关注 5 个以内，避免混淆。",
    }
