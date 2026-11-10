import contextlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("HSE_DATA_DIR", ROOT / "data")).expanduser().resolve()
SOURCES = ("roots", "telegram", "lms", "mail", "calendar", "smartpro", "external")


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def config():
    value = read_json(DATA / "config.json")
    if value is None:
        raise RuntimeError("CONFIG_MISSING: run scripts/hse/hse.sh init")
    return value


def secret(path):
    return Path(path).expanduser().read_text().strip()


@contextlib.contextmanager
def workspace(source):
    # Authentication persists; source content exists only for this invocation.
    os.umask(0o077)
    auth = DATA / "auth" / source
    auth.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="ai-native-hse-" + source + "-") as folder:
        yield Path(folder), auth


def entry(main):
    os.umask(0o077)
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        raise SystemExit(130)
    except Exception as error:
        # Do not expose URLs with query tokens or remote response bodies.
        import sys

        message = str(error)
        safe = isinstance(error, RuntimeError) and (
            message.startswith(
                (
                    "CONFIG_MISSING:",
                    "TELEGRAM_ACCESS_DENIED:",
                    "TELEGRAM_RATE_LIMIT:",
                    "BROWSER_DEPENDENCIES_MISSING",
                )
            )
            or message.isupper()
            and message.replace("_", "").isalnum()
        )
        print(
            message if safe else "REQUEST_FAILED: " + type(error).__name__,
            file=sys.stderr,
        )
        raise SystemExit(1)
