"""Time helpers. All stored datetimes are timezone-aware UTC; display is Africa/Johannesburg."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..config import TZ

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january", "januarie"),
            ("feb", "february", "februarie"),
            ("mar", "march", "maart", "mrt"),
            ("apr", "april"),
            ("may", "mei"),
            ("jun", "june", "junie"),
            ("jul", "july", "julie"),
            ("aug", "august", "augustus"),
            ("sep", "sept", "september"),
            ("oct", "october", "okt", "oktober"),
            ("nov", "november"),
            ("dec", "december", "des", "desember"),
        ],
        start=1,
    )
    for m in names
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def as_aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; values we stored are UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_utc(dt)


_DATE_PATTERNS = [
    # 2026-10-28 14:02 / 2026/10/28 14:02:00
    re.compile(r"(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})[ T,]+(?P<H>\d{1,2})[:h](?P<M>\d{2})(?::(?P<S>\d{2}))?"),
    # 28/10/2026 14:02
    re.compile(r"(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})[ ,]+(?P<H>\d{1,2})[:h](?P<M>\d{2})"),
    # 28 October 2026 14:02 / October 28, 2026 2:02 pm
    re.compile(
        r"(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3,10})\.?,?\s+(?P<y>\d{4})(?:\s*(?:@|at|,|om)?\s*(?P<H>\d{1,2})[:h](?P<M>\d{2})\s*(?P<ap>[ap]\.?m\.?)?)?",
        re.I,
    ),
    re.compile(
        r"(?P<mon>[A-Za-z]{3,10})\.?\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})(?:\s*(?:@|at|,)?\s*(?P<H>\d{1,2})[:h](?P<M>\d{2})\s*(?P<ap>[ap]\.?m\.?)?)?",
        re.I,
    ),
]


def parse_local_datetime(text: str | None) -> datetime | None:
    """Parse a date/time written on a South African site (local time) into UTC."""
    if not text:
        return None
    t = " ".join(str(text).split())
    for pat in _DATE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        g = m.groupdict()
        if g.get("mon"):
            month = MONTHS.get(g["mon"].lower().rstrip("."))
            if not month:
                continue
        else:
            month = int(g["m"])
        hour = int(g.get("H") or 0)
        minute = int(g.get("M") or 0)
        ap = (g.get("ap") or "").lower().replace(".", "")
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        try:
            local = datetime(
                int(g["y"]), month, int(g["d"]), hour, minute, int(g.get("S") or 0), tzinfo=TZ
            )
        except ValueError:
            continue
        return local.astimezone(timezone.utc)
    return None


def fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return "–"
    return as_aware(dt).astimezone(TZ).strftime("%a %d %b %H:%M")
