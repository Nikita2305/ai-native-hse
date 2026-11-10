"""Inspect local setup; optional online probes do not read message bodies."""

import argparse
import asyncio
import importlib.util
import json
import shutil
import subprocess
import time
from .common import DATA, ROOT, emit, read_json


def report(online=False):
    auth = DATA / "auth"
    browser = ROOT / "scripts/browser"
    state = read_json(auth / "browser/state.json", {})
    expiry = [
        c.get("expires", -1)
        for c in state.get("cookies", [])
        if c.get("expires", -1) > 0
    ]
    result = {
        "data_dir": str(DATA),
        "config_present": (DATA / "config.json").exists(),
        "dependencies": {
            "telethon": importlib.util.find_spec("telethon") is not None,
            "curl": bool(shutil.which("curl")),
            "node": bool(shutil.which("node")),
            "playwright": (browser / "node_modules/playwright").exists(),
        },
        "sources": {},
    }
    for source, path in {
        "roots": auth / "roots.env",
        "telegram": auth / "telegram/account.session",
        "lms": auth / "lms/cookies.txt",
        "mail": auth / "browser/state.json",
        "calendar": auth / "browser/state.json",
        "smartpro": auth / "lms/cookies.txt",
    }.items():
        result["sources"][source] = {
            "credentials_or_session_present": path.exists(),
            "online_status": "not_checked",
        }
    result["browser_expired_cookies"] = sum(t < time.time() for t in expiry)
    result["note"] = (
        "File presence does not prove a valid session. No content sync history is stored."
    )
    if online:
        from .roots import api, credentials

        try:
            api(credentials(), "/projects")
            result["sources"]["roots"]["online_status"] = "ok"
        except Exception as e:
            result["sources"]["roots"]["online_status"] = "failed:" + type(e).__name__
        if result["dependencies"]["telethon"]:

            async def probe():
                from telethon import TelegramClient

                creds = read_json(auth / "telegram/credentials.json")
                if not creds or not (auth / "telegram/account.session").exists():
                    return False
                client = TelegramClient(
                    str(auth / "telegram/account"),
                    int(creds["api_id"]),
                    creds["api_hash"],
                    receive_updates=False,
                    flood_sleep_threshold=0,
                    request_retries=0,
                )
                await client.connect()
                try:
                    return await client.is_user_authorized()
                finally:
                    await client.disconnect()

            try:
                result["sources"]["telegram"]["online_status"] = (
                    "ok" if asyncio.run(probe()) else "not_authorized"
                )
            except Exception as e:
                result["sources"]["telegram"]["online_status"] = (
                    "failed:" + type(e).__name__
                )
        if (
            result["dependencies"]["node"]
            and result["dependencies"]["playwright"]
            and state
        ):
            import tempfile, os

            with tempfile.TemporaryDirectory(prefix="hse-doctor-"):
                proc = subprocess.run(
                    ["node", str(browser / "probe.mjs")],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    env={**os.environ, "HSE_DATA_DIR": str(DATA)},
                )
                if proc.returncode == 0:
                    for name, status in json.loads(proc.stdout).items():
                        result["sources"][name]["online_status"] = status
                else:
                    for name in ("mail", "calendar"):
                        result["sources"][name]["online_status"] = "probe_failed"
        if result["dependencies"]["curl"] and (auth / "lms/cookies.txt").exists():
            try:
                proc = subprocess.run(
                    ["bash", str(ROOT / "scripts/lms/lms.sh"), "courses"],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env={**__import__("os").environ, "HSE_DATA_DIR": str(DATA)},
                )
                value = json.loads(proc.stdout) if proc.returncode == 0 else {}
                result["sources"]["lms"]["online_status"] = (
                    "ok" if value.get("complete") else "failed_or_incomplete"
                )
            except Exception as e:
                result["sources"]["lms"]["online_status"] = "failed:" + type(e).__name__
            try:
                from .smartpro import token

                token()
                result["sources"]["smartpro"]["online_status"] = "ok"
            except Exception as e:
                result["sources"]["smartpro"]["online_status"] = (
                    "failed:" + type(e).__name__
                )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    emit(report(parser.parse_args().online))
