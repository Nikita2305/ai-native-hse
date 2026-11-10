import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from ai_native_hse import common, roots, tracks, telegram_access, lms, hse
from ai_native_hse.mail_text import normalize


def example():
    return {
        "version": 1,
        "tracks": [{"id": "sample", "title": "Example course", "status": "active"}],
        "sources": [
            {
                "id": "folder",
                "title": "Materials",
                "kind": "external",
                "locator": {"url": "https://example.org/materials"},
            }
        ],
        "links": [
            {
                "track_id": "sample",
                "source_id": "folder",
                "status": "confirmed",
                "basis": "User confirmed",
                "checked_at": "2030-09-01",
            }
        ],
    }


class MapTests(unittest.TestCase):
    def test_shared_source_and_candidate_supported(self):
        value = example()
        value["tracks"].append(
            {"id": "other", "title": "Other course", "status": "planned"}
        )
        value["links"].append(
            {
                "track_id": "other",
                "source_id": "folder",
                "status": "candidate",
                "checked_at": "2030-09-02",
            }
        )
        self.assertEqual(tracks.validate(value), value)

    def test_reject_invalid_maps(self):
        edits = [
            lambda v: v["links"][0].update(source_id="missing"),
            lambda v: v["links"][0].update(basis=""),
            lambda v: v["links"][0].update(checked_at="tomorrow"),
            lambda v: v["tracks"].append(v["tracks"][0]),
            lambda v: v["sources"][0]["locator"].update(messages=["body"]),
            lambda v: v["tracks"][0].update(requirements=["homework"]),
            lambda v: v["links"].append(v["links"][0]),
        ]
        for edit in edits:
            with self.subTest(edit=edit):
                value = example()
                edit(value)
                with self.assertRaises(RuntimeError):
                    tracks.validate(value)

    def test_init_preserves_existing_map(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(hse, "DATA", Path(folder)),
            patch("sys.argv", ["hse", "init"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            hse.main()
            path = Path(folder) / "tracks.json"
            common.write_json(path, example())
            hse.main()
            self.assertEqual(json.loads(path.read_text()), example())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class StateTests(unittest.TestCase):
    def test_source_content_cleaned_auth_survives_failure(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(common, "DATA", Path(folder)),
        ):
            with self.assertRaises(ValueError):
                with common.workspace("telegram") as (temp, auth):
                    (temp / "body.json").write_text("temporary message")
                    common.write_json(auth / "credentials.json", {"api_id": 1})
                    raise ValueError("network failure")
            self.assertFalse(temp.exists())
            self.assertTrue((auth / "credentials.json").exists())
            self.assertEqual(
                [str(p.relative_to(folder)) for p in Path(folder).rglob("*.json")],
                ["auth/telegram/credentials.json"],
            )

    def test_denied_and_unknown_never_authorize(self):
        for kind, count, is_self in [
            ("user", 10, False),
            ("channel", 2, False),
            ("group", None, False),
            ("group", True, False),
            ("group", 4, True),
        ]:
            self.assertFalse(telegram_access.decision(kind, count, is_self)[0])
        self.assertTrue(telegram_access.decision("group", 3)[0])

        async def check():
            with patch.object(
                telegram_access,
                "metadata",
                AsyncMock(
                    return_value={
                        "content_allowed": False,
                        "access_reason": "PARTICIPANTS_COUNT_UNKNOWN",
                    }
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "TELEGRAM_ACCESS_DENIED"):
                    await telegram_access.require_content_access(None, None)
            with patch.object(
                telegram_access, "metadata", AsyncMock(side_effect=TimeoutError)
            ):
                with self.assertRaises(TimeoutError):
                    await telegram_access.require_content_access(None, None)

        asyncio.run(check())

    def test_mail_normalization_never_executes_or_follows_links(self):
        row = {
            "source": "mail",
            "body_parts": [
                {
                    "type": "text",
                    "subtype": "html",
                    "content": '<p>Hello<script>secret()</script><a href="https://example.org">source</a></p>',
                }
            ],
        }
        result = normalize(row)
        self.assertIn("Hello", result["text"])
        self.assertIn("https://example.org", result["text"])
        self.assertNotIn("secret()", result["text"])


class RootsTests(unittest.TestCase):
    def run_cli(self, args, responses):
        output = io.StringIO()
        calls = []

        def fake(values, path, query=None):
            calls.append((path, query))
            return responses.pop(0)

        with (
            patch("sys.argv", ["roots", *args]),
            patch.object(roots, "credentials", return_value={}),
            patch.object(roots, "api", side_effect=fake),
            contextlib.redirect_stdout(output),
        ):
            roots.main()
        return json.loads(output.getvalue()), calls

    def test_pagination_and_repeated_tags(self):
        value, calls = self.run_cli(
            [
                "items",
                "--project",
                "sample",
                "--pages",
                "2",
                "--tag",
                "a",
                "--tag",
                "b",
            ],
            [
                {
                    "artifacts": [{"id": "one", "summary": "text"}],
                    "next_cursor": "cursor-2",
                },
                {"artifacts": [{"id": "two"}], "next_cursor": None},
            ],
        )
        self.assertEqual(value["count"], 2)
        self.assertIsNone(value["next_cursor"])
        self.assertEqual(calls[1][1]["cursor"], "cursor-2")
        self.assertEqual(calls[0][1]["tag"], ["a", "b"])
        self.assertEqual(value["artifacts"][0]["summary_preview"], "text")

    def test_transcript_slicing_and_path_encoding(self):
        value, calls = self.run_cli(
            ["item", "a/b", "--transcript", "--offset", "2", "--chars", "3"],
            [{"artifact": {"id": "a/b", "transcript": "abcdef"}}],
        )
        self.assertEqual(calls[0][0], "/artifacts/a%2Fb")
        self.assertEqual(value["transcript"], "cde")
        self.assertTrue(value["has_more"])
        self.assertEqual(value["next_offset"], 5)

    def test_explicit_profile_does_not_inherit_ambient_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile"
            path.write_text("ROOTS_TOKEN=ra_fixture\n")
            with patch.dict(os.environ, {"ROOTS_TOKEN": "ra_other"}):
                self.assertEqual(roots.credentials(path)["ROOTS_TOKEN"], "ra_fixture")

    def test_redirect_rejected_and_insecure_origin_denied(self):
        with self.assertRaises(RuntimeError):
            roots.NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://example.org"
            )
        with self.assertRaises(RuntimeError):
            roots.api(
                {"ROOTS_BASE_URL": "http://example.org", "ROOTS_TOKEN": "ra_fixture"},
                "/projects",
            )


class LmsTests(unittest.TestCase):
    def test_login_requires_explicit_username_and_password_before_network(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            secret = Path(folder) / "login.json"
            for value in (
                "password-only",
                '{"password":"fixture"}',
                '{"username":"student"}',
                "[]",
            ):
                secret.write_text(value)
                with (
                    patch.object(lms.subprocess, "run") as network,
                    patch.object(lms, "AUTH", Path(folder)),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "LMS_CREDENTIALS_JSON_REQUIRED|LMS_USERNAME_AND_PASSWORD_REQUIRED",
                    ):
                        lms.lms(SimpleNamespace(action="login", secret_file=secret))
                    network.assert_not_called()

    def test_sso_form_post_and_temporary_responses(self):
        from types import SimpleNamespace

        responses = [
            (302, "Location: https://saml.hse.ru/login\r\n", ""),
            (
                200,
                "",
                '<form id="kc-form-login" action="https://saml.hse.ru/authenticate"><input name="username"><input name="password"></form>',
            ),
            (
                200,
                "",
                '<form action="https://edu.hse.ru/auth/oidckc/"><input name="code" value="code"><input name="state" value="state"></form>',
            ),
            (302, "Location: /my/courses.php\r\n", ""),
            (200, "", "<html>Courses</html>"),
            (200, "", "<html>Courses</html>"),
        ]
        posts = []

        def fake(cmd, input=None, **kwargs):
            url = cmd[cmd.index("--write-out") + 2]
            if input:
                posts.append((url, input.decode()))
            status, headers, body = responses.pop(0)
            Path(cmd[cmd.index("--dump-header") + 1]).write_text(headers)
            Path(cmd[cmd.index("--output") + 1]).write_text(body)
            Path(cmd[cmd.index("--cookie-jar") + 1]).write_text(
                "# Netscape HTTP Cookie File\n"
            )
            return SimpleNamespace(returncode=0, stdout=str(status).encode())

        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            (temp / "lms").mkdir()
            auth = temp / "auth"
            auth.mkdir()
            credentials = temp / "credentials.json"
            credentials.write_text('{"username":"test","password":"fixture"}')
            with (
                patch.object(lms, "BUILD", temp),
                patch.object(lms, "AUTH", auth),
                patch.object(lms.subprocess, "run", side_effect=fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                lms.lms(SimpleNamespace(action="login", secret_file=credentials))
            self.assertEqual(len(posts), 2)
            self.assertEqual(posts[0][0], "https://saml.hse.ru/authenticate")
            self.assertIn("password=fixture", posts[0][1])
            self.assertEqual(
                posts[1], ("https://edu.hse.ru/auth/oidckc/", "code=code&state=state")
            )
            self.assertFalse(responses)


class SmartProTests(unittest.TestCase):
    def test_sso_encodes_url_and_keeps_callback_token_out_of_process_args(self):
        from ai_native_hse import smartpro
        from types import SimpleNamespace

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(common, "DATA", Path(folder)),
        ):
            jar = Path(folder) / "cookies.txt"
            jar.write_text("# synthetic cookie jar\n")
            calls = []

            def curl(command, input, **kwargs):
                calls.append(command)
                url = json.loads(input.partition(" = ")[2])
                if len(calls) == 1:
                    self.assertIn("scope=openid%20profile", url)
                    location = "https://idm.hse.ru/continue"
                else:
                    self.assertEqual(url, "https://idm.hse.ru/continue")
                    location = "https://smartpro.hse.ru/token?token=fixture"
                self.assertNotIn(url, command)
                Path(command[command.index("--dump-header") + 1]).write_text(
                    "Location: " + location + "\r\n"
                )
                return SimpleNamespace(returncode=0, stdout="302")

            with patch.object(smartpro.subprocess, "run", side_effect=curl):
                self.assertEqual(
                    smartpro.sso_callback(
                        "https://saml.hse.ru/auth?scope=openid profile", jar
                    ),
                    "fixture",
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(jar.read_text(), "# synthetic cookie jar\n")
            self.assertFalse(
                any(p.name == "response.html" for p in Path(folder).rglob("*"))
            )

    def test_profile_login_does_not_select_role_implicitly(self):
        from ai_native_hse import smartpro

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(smartpro, "DATA", Path(folder)),
        ):
            jar = Path(folder) / "auth/lms/cookies.txt"
            jar.parent.mkdir(parents=True)
            jar.touch()

            def read(path, value=None, **kwargs):
                if path.startswith("/api/sso/auth?"):
                    return "https://saml.hse.ru/auth"
                self.assertEqual(path, "/api/sso/user")
                return {
                    "accessToken": "fixture",
                    "activeRole": None,
                    "roles": [{"name": "EPP_STUDENT"}],
                }

            with (
                patch.object(smartpro, "call", side_effect=read) as api,
                patch.object(smartpro, "sso_callback", return_value="fixture"),
            ):
                self.assertEqual(smartpro.token(require_role=False), "fixture")
                with self.assertRaisesRegex(
                    RuntimeError, "SMARTPRO_ROLE_SELECTION_REQUIRED"
                ):
                    smartpro.token()
                self.assertTrue(
                    all(
                        call.kwargs.get("method", "GET") == "GET"
                        for call in api.call_args_list
                    )
                )

    def test_sso_rejects_redirect_outside_hse_before_next_request(self):
        from ai_native_hse import smartpro
        from types import SimpleNamespace

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(common, "DATA", Path(folder)),
        ):
            jar = Path(folder) / "cookies.txt"
            jar.write_text("# synthetic\n")

            def curl(command, **kwargs):
                Path(command[command.index("--dump-header") + 1]).write_text(
                    "Location: https://example.org/callback\r\n"
                )
                return SimpleNamespace(returncode=0, stdout="302")

            with patch.object(smartpro.subprocess, "run", side_effect=curl) as request:
                with self.assertRaisesRegex(RuntimeError, "SMARTPRO_REDIRECT_REJECTED"):
                    smartpro.sso_callback("https://saml.hse.ru/auth", jar)
                self.assertEqual(request.call_count, 1)


class TelegramDiscoveryTests(unittest.TestCase):
    def test_required_period_config_defaults_and_independent_overrides(self):
        import datetime as dt
        from types import SimpleNamespace
        from ai_native_hse.telegram import discovery_window

        settings = {
            "module": {
                "start": "2030-09-01",
                "end": "2030-09-30",
                "timezone": "Europe/Moscow",
            }
        }
        since, until = discovery_window(
            SimpleNamespace(since=None, until=None), settings
        )
        self.assertEqual(since.isoformat(), "2030-09-01T00:00:00+03:00")
        self.assertEqual(until.isoformat(), "2030-10-01T00:00:00+03:00")
        since, until = discovery_window(
            SimpleNamespace(since=dt.date(2030, 9, 3), until=None), settings
        )
        self.assertEqual(since.day, 3)
        self.assertEqual(until.month, 10)
        since, until = discovery_window(
            SimpleNamespace(since=None, until=dt.date(2030, 9, 5)), settings
        )
        self.assertEqual(since.day, 1)
        self.assertEqual(until.day, 6)
        for settings in (
            {},
            {"module": {"start": "2030-09-01"}},
            {"module": {"start": "bad", "end": "2030-09-03"}},
            {"module": {"start": "2030-09-10", "end": "2030-09-01"}},
        ):
            with self.assertRaises(ValueError):
                discovery_window(SimpleNamespace(since=None, until=None), settings)
        since, until = discovery_window(
            SimpleNamespace(since=dt.date(2030, 9, 1), until=dt.date(2030, 9, 2)), {}
        )
        self.assertEqual(until.day, 3)

    def test_groups_and_channels_only_without_content_or_membership_requests(self):
        import datetime as dt
        from types import SimpleNamespace
        from ai_native_hse import telegram

        class Dialog:
            def __init__(
                self, identifier, title, date, archived=False, user=False, channel=False
            ):
                self.id = identifier
                self.name = title
                self.date = date
                self.archived = archived
                self.is_group = not user and not channel
                self.is_channel = channel
                self.is_user = user
                self.entity = SimpleNamespace(
                    username=None, participants_count=None, is_self=False
                )

            @property
            def message(self):
                raise AssertionError("Discovery must not inspect message content")

        dialogs = [
            Dialog(
                1,
                "Example unrelated group",
                dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc),
                True,
            ),
            Dialog(2, "Another group", dt.datetime(2000, 1, 2, tzinfo=dt.timezone.utc)),
            Dialog(3, "Private contact", None, user=True),
            Dialog(4, "Bot", None, user=True),
            Dialog(5, "Saved Messages", None, user=True),
            Dialog(
                7, "Outside period", dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
            ),
            Dialog(8, "Unknown activity", None),
            Dialog(
                6,
                "Example channel",
                dt.datetime(2000, 1, 3, tzinfo=dt.timezone.utc),
                channel=True,
            ),
        ]

        class Client:
            async def connect(self):
                pass

            async def disconnect(self):
                pass

            async def is_user_authorized(self):
                return True

            async def iter_dialogs(self):
                for dialog in dialogs:
                    yield dialog

        fake = SimpleNamespace(
            TelegramClient=lambda *a, **kw: Client(),
            functions=SimpleNamespace(),
            types=SimpleNamespace(),
        )
        with tempfile.TemporaryDirectory() as folder:
            auth = Path(folder)
            (auth / "credentials.json").write_text('{"api_id":1,"api_hash":"fixture"}')
            output = io.StringIO()
            with (
                patch.dict("sys.modules", {"telethon": fake}),
                patch.object(telegram, "AUTH", auth),
                patch.object(telegram, "write"),
                patch.object(telegram, "telegram_metadata", AsyncMock()) as metadata,
                contextlib.redirect_stdout(output),
            ):
                asyncio.run(
                    telegram.telegram(
                        SimpleNamespace(
                            action="dialogs",
                            since=dt.date(2000, 1, 1),
                            until=dt.date(2000, 1, 3),
                        )
                    )
                )
            value = json.loads(output.getvalue())
            self.assertEqual(
                [row["peer_id"] for row in value["chats"]], ["1", "2", "6"]
            )
            self.assertTrue(value["complete"])
            self.assertEqual(value["unknown_activity_excluded"], 1)
            self.assertTrue(value["chats"][0]["archived"])
            self.assertEqual(
                value["chats"][1]["access_reason"], "CONTENT_ACCESS_NOT_VERIFIED"
            )
            self.assertEqual(value["chats"][2]["kind"], "channel")
            self.assertTrue(all(not row["content_allowed"] for row in value["chats"]))
            metadata.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
