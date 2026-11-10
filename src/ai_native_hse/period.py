"""Select a sourced academic module or a bounded explicit override."""

import datetime as dt
from zoneinfo import ZoneInfo
from .common import config


def resolve_period(since=None, until=None, settings=None, now=None):
    settings = config() if settings is None else settings
    module = settings.get("module", {})
    zone = ZoneInfo(module.get("timezone") or "Europe/Moscow")
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone)
    start_override = since or module.get("start")
    end_override = until or module.get("end")
    selected = None
    mode = "explicit"
    if not start_override or not end_override:
        schedule = sorted(settings.get("modules", []), key=lambda m: m["start"])
        today = now.date().isoformat()
        valid_until = settings.get("calendar_valid_until")
        if valid_until and today > valid_until:
            raise ValueError(
                "Academic calendar needs updating; pass --since and --until for an explicit period"
            )
        for item in schedule:
            if item["start"] <= today <= item["end"]:
                selected = item
                mode = "current_module"
                break
        if selected is None:
            completed = [m for m in schedule if m["end"] < today]
            if not completed:
                raise ValueError("No applicable module; pass --since and --until")
            selected = completed[-1]
            mode = "between_modules"

    def date(value):
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(value)

    start = date(start_override or selected["start"])
    lower = dt.datetime.combine(start, dt.time.min, zone)
    if end_override:
        upper = dt.datetime.combine(
            date(end_override) + dt.timedelta(days=1), dt.time.min, zone
        )
    elif mode == "current_module":
        upper = dt.datetime.combine(
            date(selected["end"]) + dt.timedelta(days=1), dt.time.min, zone
        )
    else:
        upper = now + dt.timedelta(microseconds=1)
    if lower >= upper:
        raise ValueError("Period end must not precede start")
    return lower, upper, {"module": selected, "mode": mode, "timezone": str(zone)}
