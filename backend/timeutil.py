"""應用程式對外顯示時間：一律以台灣（UTC+8）呈現。資料庫多為 naive UTC。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))


def to_taiwan_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TW_TZ).isoformat()


def format_taiwan_wallclock(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """人類可讀字串（台灣時間）；無效則 '-'."""
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TW_TZ).strftime(fmt)
