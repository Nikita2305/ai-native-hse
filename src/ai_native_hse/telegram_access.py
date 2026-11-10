"""Fail-closed Telegram content access and project-local privacy cleanup."""

import datetime as dt


POLICY = "hse-no-dm-no-self-min-3-v1"


def decision(kind, participants_count, is_self=False):
    if is_self:
        return False, "SAVED_MESSAGES_FORBIDDEN"
    if kind == "user":
        return False, "PRIVATE_DIALOG_FORBIDDEN"
    if kind not in ("group", "channel"):
        return False, "CHAT_TYPE_UNKNOWN"
    if type(participants_count) is not int or participants_count < 1:
        return False, "PARTICIPANTS_COUNT_UNKNOWN"
    if participants_count <= 2:
        return False, "CHAT_WITH_AT_MOST_TWO_PARTICIPANTS_FORBIDDEN"
    return True, "ALLOWED_GROUP_OR_CHANNEL"


async def metadata(client, peer):
    from telethon import functions, types

    entity = (
        peer
        if isinstance(peer, (types.User, types.Chat, types.Channel))
        else await client.get_entity(peer)
    )
    kind = (
        "user"
        if isinstance(entity, types.User)
        else "group"
        if isinstance(entity, types.Chat)
        else "channel"
        if isinstance(entity, types.Channel)
        else "unknown"
    )
    count = None
    if kind == "group":
        full = await client(functions.messages.GetFullChatRequest(entity.id))
        participants = getattr(full.full_chat, "participants", None)
        members = getattr(participants, "participants", None)
        if isinstance(members, list):
            count = len(members)
        else:
            count = getattr(entity, "participants_count", None)
    elif kind == "channel":
        full = await client(functions.channels.GetFullChannelRequest(entity))
        count = getattr(full.full_chat, "participants_count", None)
    allowed, reason = decision(kind, count, getattr(entity, "is_self", False))
    return {
        "kind": kind,
        "participants_count": count,
        "content_allowed": allowed,
        "access_reason": reason,
        "policy": POLICY,
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


async def require_content_access(client, peer):
    info = await metadata(client, peer)
    if not info["content_allowed"]:
        raise RuntimeError("TELEGRAM_ACCESS_DENIED:" + info["access_reason"])
    return info
