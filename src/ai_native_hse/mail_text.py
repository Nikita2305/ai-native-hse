import base64
from html.parser import HTMLParser
import re
import urllib.parse


class MailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "div", "tr", "br", "li"):
            self.parts.append("\n")
        if tag == "a" and not self.hidden:
            url = dict(attrs).get("href", "")
            parsed = urllib.parse.urlsplit(url)
            # Yandex wraps source URLs; decode locally, never follow the links.
            if (
                parsed.hostname in ("mail.yandex.com", "mail.yandex.ru")
                and parsed.path == "/re.jsx"
            ):
                encoded = urllib.parse.parse_qs(parsed.query).get("l", [""])[0]
                try:
                    url = base64.urlsafe_b64decode(
                        encoded + "=" * (-len(encoded) % 4)
                    ).decode()
                except (ValueError, UnicodeError):
                    pass
            if url.startswith(("https://", "http://")):
                self.parts.append(" " + url + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalize(row):
    if row["source"] == "mail":
        parts = []
        for part in row.pop("body_parts", []):
            if part.get("type") != "text":
                continue
            content = part.get("content", "")
            if part.get("subtype") == "html":
                parser = MailText()
                parser.feed(content)
                content = "".join(parser.parts)
            parts.append(content)
        row["text"] = "\n".join(parts)
        course_ids = {
            int(value)
            for value in re.findall(
                r"https://edu\.hse\.ru/course/view\.php\?id=(\d+)", row["text"]
            )
        }
        if len(course_ids) == 1:
            row["lms_course_id"] = next(iter(course_ids))
    return row
