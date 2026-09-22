"""Time: the store keeps naive UTC; pages show the configured zone."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def to_local(value: dt.datetime | None, tz: ZoneInfo) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC).astimezone(tz)


def local_to_utc(local: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    return local.replace(tzinfo=tz).astimezone(dt.UTC).replace(tzinfo=None)


def iso_utc(value: dt.datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None
