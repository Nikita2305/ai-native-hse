"""Initialize local navigation and show configuration readiness."""

import argparse
from .common import DATA, ROOT, emit, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "status", "period"])
    args = parser.parse_args()
    if args.action == "init":
        created = []
        for name in ("config.json", "tracks.json"):
            target = DATA / name
            if not target.exists():
                write_json(target, read_json(ROOT / "scripts/hse/templates" / name))
                created.append(name)
        emit({"data_dir": str(DATA), "created": created})
    elif args.action == "period":
        from .period import resolve_period

        since, until, info = resolve_period()
        emit({**info, "since": since.isoformat(), "until_exclusive": until.isoformat()})
    else:
        from .doctor import report

        emit(report(False))
