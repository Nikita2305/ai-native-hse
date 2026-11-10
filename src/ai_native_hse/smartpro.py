"""Read SmartPro entities with an existing HSE SSO session. Never submit applications."""

import argparse
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from .common import DATA, emit, workspace

ORIGIN = "https://smartpro.hse.ru"


def sso_callback(url, jar_path):
    """Use curl for HSE SSO: its edge rejects urllib even with a valid cookie."""
    if not shutil.which("curl"):
        raise RuntimeError("CURL_REQUIRED")
    with workspace("smartpro") as (temp, auth):
        cookies = temp / "cookies.txt"
        shutil.copyfile(jar_path, cookies)
        for _ in range(20):
            url = urllib.parse.quote(url, safe=":/?&=%")
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname
                not in ("smartpro.hse.ru", "saml.hse.ru", "idm.hse.ru")
                or parsed.username
                or parsed.password
            ):
                raise RuntimeError("SMARTPRO_REDIRECT_REJECTED")
            if parsed.hostname == "smartpro.hse.ru" and parsed.path == "/token":
                value = dict(urllib.parse.parse_qsl(parsed.query)).get("token")
                if not value:
                    raise RuntimeError("SMARTPRO_CALLBACK_TOKEN_MISSING")
                return value
            headers = temp / "headers.txt"
            response = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "30",
                    "--proto",
                    "=https",
                    "--cookie",
                    str(cookies),
                    "--cookie-jar",
                    str(cookies),
                    "--dump-header",
                    str(headers),
                    "--output",
                    str(temp / "response.html"),
                    "--write-out",
                    "%{http_code}",
                    "--config",
                    "-",
                ],
                input="url = " + json.dumps(url) + "\n",
                capture_output=True,
                text=True,
                timeout=40,
            )
            if response.returncode:
                raise RuntimeError("SMARTPRO_SSO_TRANSPORT_FAILED")
            status = int(response.stdout)
            if status not in (301, 302, 303, 307, 308):
                raise RuntimeError("SMARTPRO_SSO_REFRESH_REQUIRED")
            locations = re.findall(
                r"^location:\s*(.*?)\r?$", headers.read_text(), re.I | re.M
            )
            if not locations:
                raise RuntimeError("SMARTPRO_SSO_REDIRECT_MISSING")
            url = urllib.parse.urljoin(url, locations[-1].strip())
        raise RuntimeError("SMARTPRO_SSO_TOO_MANY_REDIRECTS")


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


def token(select_role=False, *, require_role=True):
    jar_path = DATA / "auth/lms/cookies.txt"
    if not jar_path.exists():
        raise RuntimeError("LMS_SSO_LOGIN_REQUIRED")
    url = call(
        "/api/sso/auth?"
        + urllib.parse.urlencode({"back_url": ORIGIN + "/token", "system-name": "epp"})
    )
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "saml.hse.ru":
        raise RuntimeError("SMARTPRO_AUTH_ORIGIN_REJECTED")
    value = sso_callback(url, jar_path)
    user = call("/api/sso/user", value)
    value = user["accessToken"]
    if require_role and not user.get("activeRole"):
        if not select_role:
            raise RuntimeError("SMARTPRO_ROLE_SELECTION_REQUIRED")
        if [r["name"] for r in user["roles"]] != ["EPP_STUDENT"]:
            raise RuntimeError("SMARTPRO_ROLE_CHOICE_REQUIRED")
        # Explicit login-state exception; never updates academic/project data.
        value = call("/api/sso/set_active_role?role=EPP_STUDENT", value, method="PUT")[
            "accessToken"
        ]
    return value


def read_vacancy(value, participant_id, vacancy_id=None):
    participant = call(f"/api/gateway/v3/storage/participant/{participant_id}", value)
    linked = participant.get("vacancyId")
    if not linked or vacancy_id is not None and str(vacancy_id) != str(linked):
        raise RuntimeError("SMARTPRO_PARTICIPANT_VACANCY_MISMATCH")
    fields = (
        "student_filial",
        "student_faculty",
        "student_learn_program",
        "student_edu_level",
        "student_course",
    )
    attrs = {a["code"]: a.get("valueBigint") for a in participant.get("attrs", [])}
    if any(attrs.get(field) is None for field in fields):
        raise RuntimeError("SMARTPRO_STUDENT_CONTEXT_MISSING")
    query = urllib.parse.urlencode({field + "_id": attrs[field] for field in fields})
    return call(f"/api/gateway/v3/storage/vacancy/{linked}?{query}", value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entity", choices=["user", "participant", "vacancy", "project"])
    parser.add_argument("id", nargs="?", type=int)
    parser.add_argument(
        "--select-student-role",
        action="store_true",
        help="Allow selecting sole existing student role as login state",
    )
    parser.add_argument(
        "--participant-id",
        type=int,
        help="vacancy: your participant record supplies student context",
    )
    args = parser.parse_args()
    if args.entity == "vacancy" and (
        not args.participant_id or args.participant_id <= 0
    ):
        parser.error("vacancy requires a positive --participant-id for student context")
    if args.participant_id is not None and args.entity != "vacancy":
        parser.error("--participant-id applies only to vacancy")
    if args.entity not in ("user", "vacancy") and (not args.id or args.id <= 0):
        parser.error("positive entity ID required; discover it in your own account")
    value = token(args.select_student_role, require_role=args.entity != "user")
    if args.entity == "vacancy":
        if args.id is not None and args.id <= 0:
            parser.error("positive vacancy ID required")
        return emit(read_vacancy(value, args.participant_id, args.id))
    path = (
        "/api/sso/user"
        if args.entity == "user"
        else f"/api/gateway/v3/storage/{args.entity}/{args.id}"
    )
    result = call(path, value)
    if args.entity == "user":
        result = {k: v for k, v in result.items() if "token" not in k.lower()}
    emit(result)
