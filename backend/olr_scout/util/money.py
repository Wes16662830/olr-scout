"""ZAR parsing and formatting (South African English: R1,000)."""

from __future__ import annotations

import re

_NUM = re.compile(r"R?\s*([0-9][0-9 , ]*(?:\.[0-9]{1,2})?)", re.I)


def parse_zar(text: str | None) -> int | None:
    """Return whole rand from text like 'R1,250.00', 'R 1 250' or '450'. None if no amount."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(round(float(text)))
    m = _NUM.search(str(text).replace("&nbsp;", " "))
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace(" ", "").replace(" ", "")
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def format_zar(amount: int | float | None) -> str:
    if amount is None:
        return "–"
    return f"R{int(round(amount)):,}"
