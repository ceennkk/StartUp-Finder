from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: str | datetime | date | None) -> datetime | None:
    """Parse ISO-8601 or RFC-2822 strings to an aware UTC datetime. Unparseable input yields None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
    # Naive values are treated as UTC because sources that omit a zone publish UTC or date-only values.
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def bucket_time(moment: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def iter_windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Split [start, end] into inclusive windows of at most `days` days."""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows
