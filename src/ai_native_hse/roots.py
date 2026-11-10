"""Standalone stdlib Roots client. Only GET requests, no redirects with tokens."""

import argparse
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from .common import DATA, emit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("ROOTS_REDIRECT_REJECTED")


def credentials(profile=None):
    values = {}
    path = Path(profile) if profile else DATA / "auth/roots.env"
    if profile and not path.is_file():
        raise RuntimeError("ROOTS_PROFILE_MISSING")
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in ("ROOTS_BASE_URL", "ROOTS_TOKEN", "ROOTS_PROJECT"):
                values[key] = value.strip().strip("\"'")
    # Explicit profiles are isolated from ambient account credentials.
    if not profile:
        values.update(
            {
                k: v
                for k, v in os.environ.items()
                if k in ("ROOTS_BASE_URL", "ROOTS_TOKEN", "ROOTS_PROJECT")
            }
        )
    return values


def api(values, path, query=None):
    base = values.get("ROOTS_BASE_URL", "https://roots.zapostim.com").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("ROOTS_HTTPS_ORIGIN_REQUIRED")
    token = values.get("ROOTS_TOKEN", "")
    if not token.startswith("ra_"):
        raise RuntimeError("ROOTS_TOKEN_REQUIRED")
    url = base + "/app/api" + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=45) as response:
        return json.load(response)


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("projects")
    items = sub.add_parser("items")
    items.add_argument("--project")
    items.add_argument("--since")
    items.add_argument("--limit", type=positive, default=20)
    items.add_argument("--pages", type=positive, default=1)
    items.add_argument("--q")
    items.add_argument("--tag", action="append", default=[])
    items.add_argument("--cursor")
    item = sub.add_parser("item")
    item.add_argument("id")
    item.add_argument("--transcript", action="store_true")
    item.add_argument("--offset", type=int, default=0)
    item.add_argument("--chars", type=positive, default=8000)
    tags = sub.add_parser("tags")
    tags.add_argument("--project")
    args = parser.parse_args()
    values = credentials(args.env_file)
    if args.command == "projects":
        return emit(api(values, "/projects"))
    if args.command == "tags":
        project = args.project or values.get("ROOTS_PROJECT")
        if not project:
            parser.error("--project required")
        return emit(api(values, "/tags", {"project_id": project}))
    if args.command == "items":
        rows = []
        cursor = args.cursor
        seen = set()
        for _ in range(min(args.pages, 20)):
            query = {"limit": min(args.limit, 100), "tag": args.tag}
            for key, value in [
                ("project_id", args.project or values.get("ROOTS_PROJECT")),
                ("since", args.since),
                ("q", args.q),
                ("cursor", cursor),
            ]:
                if value:
                    query[key] = value
            data = api(values, "/artifacts", query)
            batch = data.get("artifacts", [])
            rows.extend(batch)
            cursor = data.get("next_cursor")
            if not cursor or not batch:
                cursor = None
                break
            if cursor in seen:
                raise RuntimeError("ROOTS_PAGINATION_NOT_ADVANCING")
            seen.add(cursor)
        fields = (
            "id",
            "project_id",
            "title",
            "created_at",
            "source_kind",
            "media_kind",
            "status",
            "duration_ms",
            "tags",
            "transcript_chars",
        )
        return emit(
            {
                "count": len(rows),
                "next_cursor": cursor,
                "artifacts": [
                    {
                        **{k: r.get(k) for k in fields},
                        "summary_preview": str(r.get("summary") or "")[:300],
                    }
                    for r in rows
                ],
            }
        )
    data = api(values, "/artifacts/" + urllib.parse.quote(args.id, safe=""))
    item = data.get("artifact", data)
    text = str(item.get("transcript") or "")
    if args.transcript:
        offset = max(0, args.offset)
        part = text[offset : offset + min(args.chars, 100000)]
        emit(
            {
                "id": item["id"],
                "title": item.get("title"),
                "offset": offset,
                "chars": len(part),
                "next_offset": offset + len(part),
                "has_more": offset + len(part) < len(text),
                "transcript": part,
            }
        )
    else:
        emit(
            {
                **{
                    k: item.get(k)
                    for k in (
                        "id",
                        "title",
                        "created_at",
                        "source_kind",
                        "media_kind",
                        "status",
                        "language",
                        "tags",
                        "summary",
                    )
                },
                "transcript_chars": len(text),
            }
        )
