"""Shared browser transport; no persistent source-content files."""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path
from .common import ROOT, DATA, config, emit, workspace, read_json, write_json


def main(source):
    parser = argparse.ArgumentParser(
        description="Read " + source + " using a local browser session"
    )
    actions = (
        ["folders", "sync", "attachment", "login", "import-state"]
        if source == "mail"
        else ["sync", "profile", "refresh-session", "login", "import-state"]
    )
    parser.add_argument("action", choices=actions)
    parser.add_argument("--state-file")
    parser.add_argument(
        "--secret-file", help="login: private JSON with username and password"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="login: explicitly open a browser for MFA/manual authentication",
    )
    parser.add_argument("--since", type=dt.date.fromisoformat)
    parser.add_argument("--until", type=dt.date.fromisoformat)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--folder", default="1")
    for name in ("mid", "hid", "name"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.action == "import-state":
        if not args.state_file:
            parser.error("--state-file required")
        state = read_json(args.state_file)
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("cookies"), list)
            or not isinstance(state.get("origins"), list)
        ):
            parser.error("expected Playwright storage state")
        write_json(DATA / "auth/browser/state.json", state)
        return emit({"session_imported": True, "validated_online": False})
    if (
        not shutil.which("node")
        or not (ROOT / "scripts/browser/node_modules/playwright").exists()
    ):
        raise RuntimeError(
            "BROWSER_DEPENDENCIES_MISSING: run scripts/setup/setup.sh --browser"
        )
    cfg = config()
    if args.action == "login":
        command = ["node", str(ROOT / "scripts/browser/login.mjs"), source]
        if args.secret_file:
            command += [
                "--secret-file",
                str(Path(args.secret_file).expanduser().resolve()),
            ]
        if args.interactive:
            command.append("--interactive")
        result = subprocess.run(
            command,
            capture_output=not args.interactive,
            text=True,
            timeout=300,
            env={**os.environ, "HSE_DATA_DIR": str(DATA)},
        )
        if result.returncode:
            message = (result.stderr or "").strip()
            raise RuntimeError(
                message
                if message.isupper() and message.replace("_", "").isalnum()
                else "BROWSER_LOGIN_FAILED"
            )
        if not args.interactive:
            emit(json.loads(result.stdout))
        return
    cmd = ["node", str(ROOT / "scripts/browser/web-readonly.mjs")]
    cmd += (
        ["refresh-session"]
        if args.action == "refresh-session"
        else [source, args.action]
    )
    if args.action == "sync":
        from .period import resolve_period

        lower, upper, _ = resolve_period(args.since, args.until, cfg)
        cmd += ["--since", str(lower.date())]
        cmd += ["--until", str((upper - dt.timedelta(microseconds=1)).date())]
        if source == "mail":
            cmd += ["--limit", str(args.limit), "--folder", args.folder]
    if args.action == "attachment":
        if not all((args.mid, args.hid, args.name)):
            parser.error("--mid, --hid and --name required")
        for name in ("mid", "hid", "name"):
            cmd += ["--" + name, getattr(args, name)]
    with workspace("browser") as (temp, auth):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "HSE_DATA_DIR": str(DATA), "HSE_WORK_DIR": str(temp)},
        )
        if result.returncode:
            message = result.stderr.strip()
            raise RuntimeError(
                message
                if message.replace("_", "").isalnum() and message.isupper()
                else "BROWSER_REQUEST_FAILED"
            )
        value = json.loads(result.stdout)
        if source == "mail" and "records" in value:
            from .mail_text import normalize

            value["records"] = [normalize(row) for row in value["records"]]
        emit(value)
