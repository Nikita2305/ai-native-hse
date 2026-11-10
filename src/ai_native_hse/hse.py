"""Initialize local navigation and show configuration readiness."""

import argparse
from .common import DATA, ROOT, emit, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "status"])
    args = parser.parse_args()
    if args.action == "init":
        created = []
        for name in ("config.json", "tracks.json"):
            target = DATA / name
            if not target.exists():
                write_json(target, read_json(ROOT / "scripts/hse/templates" / name))
                created.append(name)
        emit({"data_dir": str(DATA), "created": created})
    else:
        from .doctor import report

        emit(report(False))
