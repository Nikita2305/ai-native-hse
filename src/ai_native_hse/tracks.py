"""Maintain navigation metadata, not copied source content or extracted homework."""

import argparse
import datetime as dt
import fcntl
import re
import urllib.parse
from .common import DATA, SOURCES, emit, read_json, write_json

INDEX = DATA / "tracks.json"


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise RuntimeError("INVALID_TRACKS_VERSION")
    tracks = value.get("tracks")
    sources = value.get("sources")
    links = value.get("links")
    if not all(isinstance(x, list) for x in (tracks, sources, links)):
        raise RuntimeError("INVALID_MAP_LISTS")
    for collection in (tracks, sources):
        ids = []
        for row in collection:
            if not isinstance(row, dict) or not re.fullmatch(
                r"[a-z0-9][a-z0-9_-]{0,79}", str(row.get("id", ""))
            ):
                raise RuntimeError("INVALID_MAP_ID")
            if not isinstance(row.get("title"), str) or not row["title"].strip():
                raise RuntimeError("INVALID_MAP_TITLE")
            ids.append(row["id"])
        if len(set(ids)) != len(ids):
            raise RuntimeError("DUPLICATE_MAP_ID")
    if set(value) != {"version", "tracks", "sources", "links"}:
        raise RuntimeError("UNKNOWN_MAP_FIELDS")
    for track in tracks:
        if set(track) - {"id", "title", "status"}:
            raise RuntimeError("UNKNOWN_TRACK_FIELDS")
        if track.get("status") not in ("active", "planned", "completed", "review"):
            raise RuntimeError("INVALID_TRACK_STATUS")
    for source in sources:
        if source.get("kind") not in SOURCES or not isinstance(
            source.get("locator"), dict
        ):
            raise RuntimeError("INVALID_SOURCE")
        if set(source) - {"id", "title", "kind", "locator"}:
            raise RuntimeError("UNKNOWN_SOURCE_FIELDS")
        allowed = {
            "roots": {"project_id"},
            "telegram": {"peer_id", "topic_id"},
            "lms": {"course_id"},
            "mail": {"folder", "subject_terms", "body_terms"},
            "calendar": {"titles"},
            "smartpro": {"entity", "id"},
            "external": {"url"},
        }[source["kind"]]
        if not source["locator"] or set(source["locator"]) - allowed:
            raise RuntimeError("INVALID_SOURCE_LOCATOR")
        locator = source["locator"]
        kind = source["kind"]

        def number(value):
            return (
                type(value) is int
                and value > 0
                or isinstance(value, str)
                and value.isdigit()
                and int(value) > 0
            )

        required = {
            "roots": {"project_id"},
            "telegram": {"peer_id"},
            "lms": {"course_id"},
            "mail": set(),
            "calendar": {"titles"},
            "smartpro": {"entity", "id"},
            "external": {"url"},
        }[kind]
        if not required <= set(locator):
            raise RuntimeError("SOURCE_LOCATOR_FIELDS_MISSING")
        if kind == "telegram" and (
            not re.fullmatch(r"-?\d+", str(locator["peer_id"]))
            or "topic_id" in locator
            and not number(locator["topic_id"])
        ):
            raise RuntimeError("INVALID_TELEGRAM_LOCATOR")
        if kind == "lms" and not number(locator["course_id"]):
            raise RuntimeError("INVALID_LMS_LOCATOR")
        if kind == "roots" and (
            not isinstance(locator["project_id"], str)
            or not locator["project_id"].strip()
        ):
            raise RuntimeError("INVALID_ROOTS_LOCATOR")
        if kind == "smartpro" and (
            locator["entity"] not in ("participant", "vacancy", "project")
            or not number(locator["id"])
        ):
            raise RuntimeError("INVALID_SMARTPRO_LOCATOR")
        if kind == "external":
            url = urllib.parse.urlsplit(locator["url"])
            if (
                url.scheme not in ("http", "https")
                or not url.netloc
                or url.username
                or url.password
            ):
                raise RuntimeError("INVALID_EXTERNAL_LOCATOR")
        for key in ("subject_terms", "body_terms", "titles"):
            if key in locator and (
                not isinstance(locator[key], list)
                or not all(isinstance(v, str) and v for v in locator[key])
            ):
                raise RuntimeError("INVALID_SOURCE_TERMS")

    track_ids = {t["id"] for t in tracks}
    source_ids = {s["id"] for s in sources}
    pairs = set()
    for link in links:
        if set(link) - {"track_id", "source_id", "status", "basis", "checked_at"}:
            raise RuntimeError("UNKNOWN_LINK_FIELDS")
        if not isinstance(link.get("basis", ""), str):
            raise RuntimeError("INVALID_LINK_BASIS")
        try:
            dt.date.fromisoformat(link["checked_at"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("LINK_CHECK_DATE_REQUIRED") from None
        pair = (link.get("track_id"), link.get("source_id"))
        if pair[0] not in track_ids or pair[1] not in source_ids:
            raise RuntimeError("DANGLING_SOURCE_LINK")
        if pair in pairs:
            raise RuntimeError("DUPLICATE_SOURCE_LINK")
        pairs.add(pair)
        if link.get("status") not in ("candidate", "confirmed"):
            raise RuntimeError("INVALID_LINK_STATUS")
        if link["status"] == "confirmed" and not link.get("basis"):
            raise RuntimeError("CONFIRMED_LINK_NEEDS_BASIS")
    return value


def load():
    return validate(
        read_json(INDEX, {"version": 1, "tracks": [], "sources": [], "links": []})
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    show = sub.add_parser("show")
    show.add_argument("id")
    replace = sub.add_parser("replace")
    replace.add_argument(
        "--file", required=True, help="Reviewed metadata map, never source bodies"
    )
    args = parser.parse_args()
    if args.action == "replace":
        value = validate(read_json(args.file))
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / "tracks.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            write_json(INDEX, value)
        return emit(
            {
                "tracks": len(value["tracks"]),
                "sources": len(value["sources"]),
                "links": len(value["links"]),
            }
        )
    value = load()
    if args.action == "validate":
        return emit({"valid": True, "tracks": len(value["tracks"])})
    if args.action == "list":
        return emit(value)
    track = next((t for t in value["tracks"] if t["id"] == args.id), None)
    if track is None:
        parser.error("unknown track")
    links = [link for link in value["links"] if link["track_id"] == args.id]
    emit(
        {
            "track": track,
            "sources": [
                {
                    **s,
                    "association": next(
                        link for link in links if link["source_id"] == s["id"]
                    ),
                }
                for s in value["sources"]
                if any(link["source_id"] == s["id"] for link in links)
            ],
        }
    )
