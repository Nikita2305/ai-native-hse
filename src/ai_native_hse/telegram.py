"""Read Telegram groups; DMs, self and groups with <=2 people are forbidden."""

import argparse
import asyncio
import datetime as dt
import json
import re
import urllib.parse
from .common import emit, secret, workspace, write_json
from .period import resolve_period
from .telegram_access import metadata as telegram_metadata, require_content_access
from .lms import record

BUILD = AUTH = None


def write(name, value):
    target = BUILD / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False))
    return target


def discovery_window(args, settings=None, now=None):
    since, until, _ = resolve_period(args.since, args.until, settings, now)
    return since, until


async def telegram(args):
    from telethon import TelegramClient, functions, types

    creds_path = AUTH / "credentials.json"
    if args.action == "send-code":
        creds = json.loads(secret(args.secret_file))
        write_json(creds_path, creds)
    else:
        creds = json.loads(creds_path.read_text())
    client = TelegramClient(
        str(AUTH / "account"),
        int(creds["api_id"]),
        creds["api_hash"],
        receive_updates=False,
        flood_sleep_threshold=0,
        request_retries=1,
    )
    await client.connect()
    try:
        if args.action == "send-code":
            sent = await client.send_code_request(creds["phone"])
            write_json(AUTH / "login.json", {"phone_code_hash": sent.phone_code_hash})
            print("Telegram login code requested")
            return
        if args.action == "sign-in":
            login = json.loads((AUTH / "login.json").read_text())
            await client.sign_in(
                phone=creds["phone"],
                code=secret(args.secret_file),
                phone_code_hash=login["phone_code_hash"],
            )
            print("Telegram authorized")
            return
        if args.action == "password":
            await client.sign_in(password=secret(args.secret_file))
            print("Telegram 2FA completed")
            return
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram account not authorized")
        if args.action == "invite-metadata":
            link = urllib.parse.urlparse(args.invite_url or "")
            if (
                link.scheme != "https"
                or link.hostname != "t.me"
                or not re.fullmatch(r"/\+[A-Za-z0-9_-]+", link.path)
            ):
                raise RuntimeError("Invalid Telegram invite URL")
            result = await client(
                functions.messages.CheckChatInviteRequest(link.path[2:])
            )
            if isinstance(result, types.ChatInviteAlready):
                from telethon.utils import get_peer_id

                info = await telegram_metadata(client, result.chat)
                print(
                    json.dumps(
                        {
                            "membership": "already_member",
                            "peer_id": str(get_peer_id(result.chat)),
                            "title": result.chat.title,
                            **info,
                        }
                    )
                )
            else:
                print(
                    json.dumps(
                        {
                            "membership": "not_member",
                            "title": getattr(result, "title", None),
                            "participants_count": getattr(
                                result, "participants_count", None
                            ),
                            "content_allowed": False,
                            "access_reason": "NOT_A_MEMBER_NO_JOIN_PERFORMED",
                        }
                    )
                )
        elif args.action == "dialogs":
            rows = []
            since, until = discovery_window(args)
            unknown_dates = 0
            # No folder filter means all folders including archived dialogs.
            async for dialog in client.iter_dialogs():
                if dialog.is_user or not (dialog.is_group or dialog.is_channel):
                    continue
                if since or until:
                    if dialog.date is None:
                        unknown_dates += 1
                        continue
                    activity = dialog.date.astimezone(dt.timezone.utc)
                    if since and activity < since or until and activity >= until:
                        continue
                row = {
                    "peer_id": str(dialog.id),
                    "title": dialog.name,
                    "username": getattr(dialog.entity, "username", None),
                    "is_group": dialog.is_group,
                    "is_channel": dialog.is_channel,
                    "is_user": dialog.is_user,
                    "archived": dialog.archived,
                    "last_activity_at": dialog.date.isoformat()
                    if dialog.date
                    else None,
                }
                # The agent chooses relevant sources; content commands
                # independently verify membership before reading.
                row.update(
                    kind="group" if dialog.is_group else "channel",
                    content_allowed=False,
                    participants_count=getattr(
                        dialog.entity, "participants_count", None
                    ),
                    access_reason="CONTENT_ACCESS_NOT_VERIFIED",
                )
                rows.append(row)
            write(
                "telegram/dialogs.json",
                {
                    "complete": True,
                    "chats": rows,
                    "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
            emit(
                {
                    "chats": rows,
                    "dialogs": len(rows),
                    "complete": True,
                    "activity_window": {
                        "since": since.isoformat() if since else None,
                        "until_exclusive": until.isoformat() if until else None,
                    },
                    "unknown_activity_excluded": unknown_dates,
                }
            )
        elif args.action == "topics":
            if not args.peer:
                raise RuntimeError("peer is required")
            peer = await client.get_input_entity(int(args.peer))
            access = await require_content_access(client, peer)
            entity = await client.get_entity(peer)
            rows = []
            offset_date, offset_id, offset_topic = None, 0, 0
            complete = False
            for _ in range(20):
                result = await client(
                    functions.messages.GetForumTopicsRequest(
                        peer=peer,
                        offset_date=offset_date,
                        offset_id=offset_id,
                        offset_topic=offset_topic,
                        limit=100,
                    )
                )
                topics = [t for t in result.topics if isinstance(t, types.ForumTopic)]
                for topic in topics:
                    rows.append(
                        {
                            "topic_id": topic.id,
                            "title": topic.title,
                            "top_message_id": topic.top_message,
                            "closed": topic.closed,
                        }
                    )
                if len(result.topics) < 100:
                    complete = True
                    break
                last = topics[-1]
                offset_date, offset_id, offset_topic = (
                    last.date,
                    last.top_message,
                    last.id,
                )
            value = {
                "peer_id": args.peer,
                "title": entity.title,
                "topics": rows,
                "complete": complete,
                "telegram_access": access,
            }
            write(f"telegram/topics-{args.peer}.json", value)
            print(json.dumps(value, ensure_ascii=False))
        elif args.action == "metadata":
            if not args.peer:
                raise RuntimeError("peer is required")
            print(json.dumps(await telegram_metadata(client, int(args.peer))))
        elif args.action == "media":
            if not args.peer or not args.message_id:
                raise RuntimeError("peer and message-id are required")
            peer = await client.get_input_entity(int(args.peer))
            await require_content_access(client, peer)
            msg = await client.get_messages(peer, ids=args.message_id)
            if not msg or not msg.file or msg.file.size > 25 * 1024 * 1024:
                raise RuntimeError("No file or file exceeds 25 MiB")
            suffix = (
                ".jpg"
                if msg.file.mime_type == "image/jpeg"
                else ".pdf"
                if msg.file.mime_type == "application/pdf"
                else ".bin"
            )
            target = BUILD / f"telegram/media/{args.peer}-{args.message_id}{suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            await client.download_media(msg, file=str(target))
            import base64

            emit(
                {
                    "message_id": msg.id,
                    "filename": msg.file.name,
                    "mime_type": msg.file.mime_type,
                    "content_base64": base64.b64encode(target.read_bytes()).decode(),
                }
            )
        elif args.action in ("history", "inspect"):
            peer = await client.get_input_entity(int(args.peer))
            access = await require_content_access(client, peer)
            about = None
            if args.action == "inspect":
                if isinstance(peer, types.InputPeerChannel):
                    full = await client(functions.channels.GetFullChannelRequest(peer))
                elif isinstance(peer, types.InputPeerChat):
                    full = await client(
                        functions.messages.GetFullChatRequest(peer.chat_id)
                    )
                else:
                    raise RuntimeError(
                        "Inspect is intended for course/team groups, not personal dialogs"
                    )
                about = {
                    "peer_id": args.peer,
                    "about": getattr(full.full_chat, "about", ""),
                    "pinned_msg_id": getattr(full.full_chat, "pinned_msg_id", None),
                    "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            rows = []
            messages = [
                msg
                async for msg in client.iter_messages(
                    peer,
                    limit=args.limit,
                    offset_id=args.before_id,
                    **({"reply_to": args.topic_id} if args.topic_id else {}),
                )
            ]
            messages_without_pins = list(messages)
            if args.action == "inspect":
                pins = [
                    msg
                    async for msg in client.iter_messages(
                        peer, limit=50, filter=types.InputMessagesFilterPinned()
                    )
                ]
                messages += [
                    msg
                    for msg in pins
                    if not args.topic_id
                    or (
                        getattr(msg.reply_to, "reply_to_top_id", None)
                        or getattr(msg.reply_to, "reply_to_msg_id", None)
                    )
                    == args.topic_id
                ]
            unique = {msg.id: msg for msg in messages}
            for msg in unique.values():
                rows.append(
                    record(
                        "telegram",
                        f"{args.peer}:{msg.id}",
                        f"Chat {args.peer} message {msg.id}",
                        msg.message or "",
                        msg.date.isoformat(),
                        f"telegram:{args.peer}:{msg.id}",
                        peer_id=args.peer,
                        message_id=msg.id,
                        reply_to_message_id=msg.reply_to_msg_id,
                        has_media=bool(msg.media),
                        topic_id=(
                            getattr(msg.reply_to, "reply_to_top_id", None)
                            or (
                                getattr(msg.reply_to, "reply_to_msg_id", None)
                                if getattr(msg.reply_to, "forum_topic", False)
                                else None
                            )
                        ),
                        sender_id=msg.sender_id,
                        sender_name=(
                            " ".join(
                                filter(
                                    None,
                                    [
                                        getattr(msg.sender, "first_name", None),
                                        getattr(msg.sender, "last_name", None),
                                    ],
                                )
                            )
                            or getattr(msg.sender, "title", None)
                        ),
                        media_filename=getattr(msg.file, "name", None),
                        media_mime_type=getattr(msg.file, "mime_type", None),
                        links=sorted(
                            {
                                entity.url
                                for entity in (msg.entities or [])
                                if getattr(entity, "url", None)
                            }
                        ),
                        coverage=f"latest at most {args.limit} messages"
                        + (
                            " plus at most 50 pinned messages"
                            if args.action == "inspect"
                            else ""
                        )
                        + "; media not downloaded",
                    )
                )
            for row in rows:
                row["telegram_access"] = access
            suffix = f"-topic-{args.topic_id}" if args.topic_id else ""
            write(f"telegram/history-{args.peer}{suffix}.json", rows)
            write(
                f"telegram/coverage-{args.peer}{suffix}.json",
                {
                    "peer_id": args.peer,
                    "topic_id": args.topic_id,
                    "requested_limit": args.limit,
                    "retrieved": len(rows),
                    "history_exhausted": len(messages_without_pins) < args.limit,
                    "pins_limit": 50 if args.action == "inspect" else 0,
                    "oldest": min((r["source_date"] for r in rows), default=None),
                    "newest": max((r["source_date"] for r in rows), default=None),
                    "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
            emit(
                {
                    "records": rows,
                    "about": about,
                    "coverage": json.loads(
                        (
                            BUILD / f"telegram/coverage-{args.peer}{suffix}.json"
                        ).read_text()
                    ),
                }
            )
    finally:
        await client.disconnect()


def main():
    global BUILD, AUTH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "send-code",
            "sign-in",
            "password",
            "dialogs",
            "history",
            "inspect",
            "media",
            "metadata",
            "invite-metadata",
            "topics",
        ],
    )
    parser.add_argument("--secret-file")
    parser.add_argument("--peer")
    parser.add_argument("--invite-url")
    parser.add_argument("--message-id", type=int)
    parser.add_argument("--topic-id", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--before-id",
        type=int,
        default=0,
        help="Read history older than this message ID",
    )
    parser.add_argument(
        "--since",
        type=dt.date.fromisoformat,
        help="dialogs: last activity on/after this date in module.timezone",
    )
    parser.add_argument(
        "--until",
        type=dt.date.fromisoformat,
        help="dialogs: last activity through this date in module.timezone (inclusive)",
    )
    args = parser.parse_args()
    if args.action != "dialogs" and (args.since or args.until):
        parser.error("activity window options apply only to dialogs")
    if args.action == "dialogs":
        try:
            discovery_window(args)
        except ValueError as error:
            parser.error(str(error))
    if args.action in ("send-code", "sign-in", "password") and not args.secret_file:
        parser.error("--secret-file required")
    if (
        args.action in ("history", "inspect", "media", "metadata", "topics")
        and not args.peer
    ):
        parser.error("--peer required")
    if args.before_id < 0:
        parser.error("--before-id must be nonnegative")
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be 1..1000")
    with workspace("telegram") as (BUILD, AUTH):
        try:
            asyncio.run(telegram(args))
        except Exception as error:
            if type(error).__name__ == "FloodWaitError":
                raise RuntimeError(
                    f"TELEGRAM_RATE_LIMIT: retry after {error.seconds} seconds"
                ) from None
            raise
