"""HSE Moodle SSO and allowlisted reads. Temporary responses are cleaned on exit."""

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import re
import subprocess
import urllib.parse
import urllib.request
from .common import config, emit, secret, workspace

BUILD = AUTH = None
CONFIG = {}


def write(name, value):
    target = BUILD / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False))
    return target


def record(source, key, title, text, date, url, **extra):
    return dict(
        id=f"{source}:{key}",
        source=source,
        title=title,
        text=text,
        source_date=date,
        url=url,
        **extra,
    )


def save(rows):
    emit({"records": rows})


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form = None
        self.inputs = {}
        self.links = []
        self.text = []
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden = True
        attrs = dict(attrs)
        if tag == "form" and (not self.form or attrs.get("id") == "kc-form-login"):
            self.form = attrs.get("action")
        if tag == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs.get("value", "")
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, value):
        if not self.hidden:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = False


def hse_origin(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("edu.hse.ru", "saml.hse.ru"):
        raise RuntimeError("Unexpected SSO origin")
    return parsed


class HseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hse_origin(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def lms(args):
    cookies_path = AUTH / "cookies.txt"
    cookies_path.parent.mkdir(parents=True, exist_ok=True)
    trace = []

    def get(url, data=None, content_type="application/x-www-form-urlencoded"):
        # The HSE edge rejects urllib's transport before authentication. curl
        # reaches the official login. Follow redirects ourselves to check each origin.
        for _ in range(10):
            parsed = hse_origin(url)
            body_path = BUILD / "lms/response.html"
            header_path = BUILD / "lms/response.headers"
            cmd = [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "30",
                "--proto",
                "=https",
                "--header",
                "Cache-Control: no-cache",
                "--header",
                "Pragma: no-cache",
                "--cookie",
                str(cookies_path),
                "--cookie-jar",
                str(cookies_path),
                "--dump-header",
                str(header_path),
                "--output",
                str(body_path),
                "--write-out",
                "%{http_code}",
                url,
            ]
            if data is not None:
                cmd.extend(
                    ["--data-binary", "@-", "--header", "Content-Type: " + content_type]
                )
            response = subprocess.run(cmd, input=data, capture_output=True, timeout=40)
            if response.returncode:
                raise RuntimeError("SSO transport failed")
            status = int(response.stdout)
            trace.append(
                {"host": parsed.hostname, "path": parsed.path, "status": status}
            )
            write("lms/trace.json", trace)
            if status in (301, 302, 303, 307, 308):
                locations = re.findall(
                    r"^location:\s*(.*?)\r?$", header_path.read_text(), re.I | re.M
                )
                if not locations:
                    raise RuntimeError("SSO redirect without location")
                next_url = urllib.parse.urljoin(url, locations[-1].strip())
                if (
                    status in (307, 308)
                    and data is not None
                    and urllib.parse.urlsplit(next_url).hostname != parsed.hostname
                ):
                    raise RuntimeError("SSO_CROSS_ORIGIN_POST_REJECTED")
                url = next_url
                if status in (301, 302, 303):
                    data = None
                continue
            if status != 200:
                raise RuntimeError(f"SSO HTTP status {status}")
            return url, body_path.read_text()
        raise RuntimeError("Too many SSO redirects")

    def complete_form_post(url, html):
        continuation = Page()
        continuation.feed(html)
        if continuation.form and {"code", "state"} <= continuation.inputs.keys():
            callback = urllib.parse.urljoin(url, continuation.form)
            destination = urllib.parse.urlparse(callback)
            if (
                destination.scheme != "https"
                or destination.hostname != "edu.hse.ru"
                or destination.path.rstrip("/") != "/auth/oidckc"
            ):
                raise RuntimeError("Unexpected OIDC form-post callback")
            return get(callback, urllib.parse.urlencode(continuation.inputs).encode())
        return url, html

    if args.action == "login":
        value = secret(args.secret_file)
        try:
            creds = json.loads(value)
        except json.JSONDecodeError:
            creds = {"username": CONFIG["mail"]["address"], "password": value}
        nonce = str(dt.datetime.now(dt.timezone.utc).timestamp())
        url, html = get("https://edu.hse.ru/auth/oidckc/?hse_client_nonce=" + nonce)
        url, html = complete_form_post(url, html)
        if urllib.parse.urlparse(url).hostname == "edu.hse.ru":
            args.action = "courses"
            return lms(args)
        parser = Page()
        parser.feed(html)
        if not parser.form:
            raise RuntimeError("SSO form missing; login may already be active")
        target = urllib.parse.urljoin(url, parser.form)
        if urllib.parse.urlparse(target).hostname != "saml.hse.ru":
            raise RuntimeError("Unexpected SSO form origin")
        parser.inputs.update(username=creds["username"], password=creds["password"])
        url, html = get(target, urllib.parse.urlencode(parser.inputs).encode())
        url, html = complete_form_post(url, html)
        cookies_path.chmod(0o600)
        write(
            "lms/auth-result.json",
            {
                "origin": urllib.parse.urlparse(url).hostname,
                "path": urllib.parse.urlparse(url).path,
                "authenticated": urllib.parse.urlparse(url).hostname == "edu.hse.ru",
            },
        )
        if urllib.parse.urlparse(url).hostname != "edu.hse.ru":
            # Preserve page privately for diagnosing MFA/errors without printing credentials.
            (BUILD / "lms/auth-result.html").write_text(html)
            raise RuntimeError("LMS_SSO_NOT_COMPLETED")
            return
    url, html = get("https://edu.hse.ru/my/courses.php")
    if "/login/" in url or urllib.parse.urlparse(url).hostname != "edu.hse.ru":
        # Refresh Moodle from the existing HSE SSO session without asking for
        # another password. Only the official OIDC callback receives code/state.
        nonce = str(dt.datetime.now(dt.timezone.utc).timestamp())
        url, html = get("https://edu.hse.ru/auth/oidckc/?hse_client_nonce=" + nonce)
        url, html = complete_form_post(url, html)
        if urllib.parse.urlparse(url).hostname == "edu.hse.ru":
            url, html = get("https://edu.hse.ru/my/courses.php")
    if "/login/" in url or urllib.parse.urlparse(url).hostname != "edu.hse.ru":
        raise RuntimeError("LMS session not authenticated")
    path = BUILD / "lms/courses.html"
    path.write_text(html)
    parser = Page()
    parser.feed(html)
    if args.action in ("page", "grades"):
        if not args.course_id or args.course_id <= 0:
            raise RuntimeError("Valid course-id is required")
        prefix = (
            "/grade/report/user/index.php"
            if args.action == "grades"
            else "/course/view.php"
        )
        course_url = "https://edu.hse.ru" + prefix + "?id=" + str(args.course_id)
        final, course_html = get(course_url)
        if urllib.parse.urlparse(final).path != prefix:
            raise RuntimeError("Course page unavailable")
        (BUILD / f"lms/{args.action}-{args.course_id}.html").write_text(course_html)
        course_page = Page()
        course_page.feed(course_html)
        write(f"lms/course-{args.course_id}-links.json", sorted(set(course_page.links)))
        key = (
            str(args.course_id) if args.action == "page" else f"grades:{args.course_id}"
        )
        save(
            [
                record(
                    "lms",
                    key,
                    f"{args.action} course {args.course_id}",
                    "\n".join(v.strip() for v in course_page.text if v.strip()),
                    "unknown",
                    course_url,
                    coverage="course listing and inline text only; no activity modules opened",
                    lms_course_id=args.course_id,
                    links=sorted(
                        set(
                            urllib.parse.urljoin(course_url, u)
                            for u in course_page.links
                        )
                    ),
                )
            ]
        )
        return
    links = sorted(
        set(
            urllib.parse.urljoin(url, link)
            for link in parser.links
            if "/course/view.php" in link
        )
    )
    write("lms/course-links.json", links)
    # The My Courses page renders enrollment via a read AJAX method, not always in HTML.
    match = re.search(r'"sesskey"\s*:\s*"([^"]+)"', html)
    if match:
        if args.action == "calendar":
            payload = [
                {
                    "index": 0,
                    "methodname": "core_calendar_get_calendar_monthly_view",
                    "args": {"year": args.year, "month": args.month},
                }
            ]
            endpoint = (
                "https://edu.hse.ru/lib/ajax/service.php?sesskey="
                + urllib.parse.quote(match[1])
            )
            _, text = get(endpoint, json.dumps(payload).encode(), "application/json")
            result = json.loads(text)
            write(f"lms/calendar-{args.year}-{args.month:02d}.json", result)
            if result[0].get("error"):
                raise RuntimeError("Calendar read API unavailable")
            save(
                [
                    record(
                        "calendar",
                        f"lms:{args.year}-{args.month:02d}",
                        f"LMS calendar {args.year}-{args.month:02d}",
                        json.dumps(result[0]["data"], ensure_ascii=False),
                        "unknown",
                        "https://edu.hse.ru/calendar/view.php?view=month",
                        coverage="Moodle calendar only; HSE App X class timetable not verified",
                    )
                ]
            )
            return
        if args.action == "contents":
            payload = [
                {
                    "index": 0,
                    "methodname": "core_course_get_contents",
                    "args": {"courseid": args.course_id},
                }
            ]
            endpoint = (
                "https://edu.hse.ru/lib/ajax/service.php?sesskey="
                + urllib.parse.quote(match[1])
            )
            _, text = get(endpoint, json.dumps(payload).encode(), "application/json")
            result = json.loads(text)
            if (
                result[0].get("error")
                and result[0].get("exception", {}).get("errorcode")
                == "servicenotavailable"
            ):
                payload = [
                    {
                        "index": 0,
                        "methodname": "core_courseformat_get_state",
                        "args": {"courseid": args.course_id},
                    }
                ]
                _, text = get(
                    endpoint, json.dumps(payload).encode(), "application/json"
                )
                result = json.loads(text)
                if not result[0].get("error") and isinstance(
                    result[0].get("data"), str
                ):
                    result[0]["data"] = json.loads(result[0]["data"])
            write(f"lms/course-{args.course_id}.json", result)
            print(
                json.dumps(
                    {
                        "error": bool(result[0].get("error")),
                        "errorcode": result[0].get("exception", {}).get("errorcode"),
                        "data": result,
                    }
                )
            )
            return
        enrolled = []
        complete = False
        for offset in range(0, 2000, 100):
            payload = [
                {
                    "index": 0,
                    "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                    "args": {
                        "classification": "all",
                        "limit": 100,
                        "offset": offset,
                        "sort": "fullname",
                    },
                }
            ]
            endpoint = (
                "https://edu.hse.ru/lib/ajax/service.php?sesskey="
                + urllib.parse.quote(match[1])
            )
            _, result_text = get(
                endpoint, json.dumps(payload).encode(), "application/json"
            )
            result = json.loads(result_text)
            if not result or result[0].get("error"):
                write("lms/ajax-status.json", {"supported": False})
                break
            courses = result[0]["data"]["courses"]
            enrolled.extend(courses)
            if len(courses) < 100:
                complete = True
                break
        write("lms/enrolled-courses.json", {"complete": complete, "courses": enrolled})
    print(
        json.dumps(
            {
                "course_links": len(links),
                "courses": enrolled if match else [],
                "complete": complete if match else False,
            }
        )
    )


def main():
    global BUILD, AUTH, CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["login", "courses", "contents", "page", "grades", "calendar"]
    )
    parser.add_argument(
        "--secret-file",
        help="Private JSON {username,password}, or password using configured mail address",
    )
    parser.add_argument("--course-id", type=int)
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument(
        "--month", type=int, choices=range(1, 13), default=dt.date.today().month
    )
    args = parser.parse_args()
    if args.action == "login" and not args.secret_file:
        parser.error("login requires --secret-file")
    if args.action in ("contents", "page", "grades") and (
        not args.course_id or args.course_id <= 0
    ):
        parser.error("positive --course-id required")
    CONFIG = config()
    with workspace("lms") as (BUILD, AUTH):
        (BUILD / "lms").mkdir()
        lms(args)
