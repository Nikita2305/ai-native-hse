"""Read SmartPro entities with an existing HSE SSO session. Never submit applications."""

import argparse
import http.cookiejar
import json
import urllib.parse
import urllib.request
from .common import DATA, emit

ORIGIN = "https://smartpro.hse.ru"


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in (
            "smartpro.hse.ru",
            "saml.hse.ru",
        ):
            raise RuntimeError("SMARTPRO_REDIRECT_REJECTED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def call(path, token=None, *, method="GET"):
    if method != "GET" and (method, path) != (
        "PUT",
        "/api/sso/set_active_role?role=EPP_STUDENT",
    ):
        raise RuntimeError("SMARTPRO_WRITE_DENIED")
    headers = {"system-name": "epp"}
    if token:
        headers["access-token"] = token
    data = b"{}" if method == "PUT" else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        ORIGIN + path, headers=headers, data=data, method=method
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError("SMARTPRO_API_REDIRECT_REJECTED")

    with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
        text = response.read().decode()
        return (
            json.loads(text)
            if response.headers.get_content_type() == "application/json"
            else text
        )


def token(select_role=False):
    jar_path = DATA / "auth/lms/cookies.txt"
    if not jar_path.exists():
        raise RuntimeError("LMS_SSO_LOGIN_REQUIRED")
    jar = http.cookiejar.MozillaCookieJar(str(jar_path))
    jar.load(ignore_discard=True)
    url = call(
        "/api/sso/auth?"
        + urllib.parse.urlencode({"back_url": ORIGIN + "/token", "system-name": "epp"})
    )
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "saml.hse.ru":
        raise RuntimeError("SMARTPRO_AUTH_ORIGIN_REJECTED")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), SafeRedirect()
    )
    with opener.open(url, timeout=45) as response:
        final = urllib.parse.urlsplit(response.url)
    if final.hostname != "smartpro.hse.ru" or final.path != "/token":
        raise RuntimeError("SMARTPRO_SSO_REFRESH_REQUIRED")
    value = dict(urllib.parse.parse_qsl(final.query)).get("token")
    if not value:
        raise RuntimeError("SMARTPRO_CALLBACK_TOKEN_MISSING")
    user = call("/api/sso/user", value)
    value = user["accessToken"]
    if not user.get("activeRole"):
        if not select_role:
            raise RuntimeError("SMARTPRO_ROLE_SELECTION_REQUIRED")
        if [r["name"] for r in user["roles"]] != ["EPP_STUDENT"]:
            raise RuntimeError("SMARTPRO_ROLE_CHOICE_REQUIRED")
        # Explicit login-state exception; never updates academic/project data.
        value = call("/api/sso/set_active_role?role=EPP_STUDENT", value, method="PUT")[
            "accessToken"
        ]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entity", choices=["user", "participant", "vacancy", "project"])
    parser.add_argument("id", nargs="?", type=int)
    parser.add_argument(
        "--select-student-role",
        action="store_true",
        help="Allow selecting sole existing student role as login state",
    )
    args = parser.parse_args()
    if args.entity != "user" and (not args.id or args.id <= 0):
        parser.error("positive entity ID required; discover it in your own account")
    value = token(args.select_student_role)
    path = (
        "/api/sso/user"
        if args.entity == "user"
        else f"/api/gateway/v3/storage/{args.entity}/{args.id}"
    )
    result = call(path, value)
    if args.entity == "user":
        result = {k: v for k, v in result.items() if "token" not in k.lower()}
    emit(result)
