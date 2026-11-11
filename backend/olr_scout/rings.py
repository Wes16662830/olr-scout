"""Ring-number parsing, normalisation and lot↔result matching.

Ring formats seen (see docs/sources.md):
  Best Pigeon titles : ``ZA 2026 PORT 7829 (C)``  country, year, club, number, sex
  Elite lots         : ``9822 OERF``              number + club, no country/year
  Benzing results    : ``BE-25-6087189``          country, 2-digit year, number
  German             : ``DV 06523-24-123``         DV, club, year, number
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalise(ring: str | None) -> str:
    """Uppercase and strip every non-alphanumeric character."""
    if not ring:
        return ""
    return _NON_ALNUM.sub("", str(ring).upper())


@dataclass
class Ring:
    raw: str
    country: str | None = None
    year: int | None = None
    club: str | None = None
    number: str | None = None
    sex: str | None = None  # "cock" | "hen" | None

    @property
    def norm(self) -> str:
        return normalise(self.raw)

    @property
    def number_int(self) -> int | None:
        return int(self.number) if self.number and self.number.isdigit() else None

    @property
    def canonical(self) -> str:
        """A normalised form built from parts (country+yy+club+number) when known."""
        parts = [
            COUNTRY_ALIAS.get(self.country or "", self.country or ""),
            f"{self.year % 100:02d}" if self.year else "",
            self.club or "",
            str(self.number_int) if self.number_int is not None else (self.number or ""),
        ]
        return "".join(parts)


def _year4(y: str | int | None) -> int | None:
    if y is None or y == "":
        return None
    y = int(y)
    if y < 100:
        y += 2000 if y < 80 else 1900
    return y if 1980 <= y <= 2100 else None


SEX_MARK = re.compile(r"\(\s*([CHVW]|COCK|HEN)\s*\)", re.I)
_SEX_MAP = {"C": "cock", "COCK": "cock", "V": "hen", "W": "hen", "H": "hen", "HEN": "hen"}

# ZA 2026 PORT 7829 (C)  |  ZA-26-PORT-7829
_RE_FULL = re.compile(
    r"\b(?P<country>[A-Z]{2,9})[\s\-/.()]*(?P<year>(?:19|20)\d{2}|\d{2})\)?[\s\-/.]+(?P<club>[A-Z]{1,8})[\s\-/.]*(?P<number>\d{1,8})\b"
)
# GB-A-25-79641: a club letter before the year
_RE_LCYN = re.compile(
    r"\b(?P<country>[A-Z]{2,9})[\s\-/.]+(?P<club>[A-Z])[\s\-/.]+(?P<year>(?:19|20)\d{2}|\d{2})[\s\-/.]+(?P<number>\d{2,8})\b"
)
# ZA-25-CRU DERBY-3175 | ZA-25-EC/DRPC-837 | PL-25-FC-ZP-1050689 | CU-25-O&L-6460: a club of two or
# three parts, between dashes
_RE_WORDCLUB = re.compile(
    r"\b(?P<country>[A-Z]{2,9})-(?P<year>(?:19|20)\d{2}|\d{2})-(?P<club>[A-Z]{1,12}(?:[ /&-][A-Z]{1,12}){1,2})-(?P<number>\d{1,8})\b"
)
# PL-25-0400-3205: country, year, numeric club, number
_RE_NUMCLUB = re.compile(
    r"\b(?P<country>[A-Z]{2,9})[\s\-/.()]*(?P<year>(?:19|20)\d{2}|\d{2})\)?[\s\-/.]+(?P<club>\d{2,5})[\s\-/.]+(?P<number>\d{1,8})\b"
)
# BE-25-6087189 | NL 2024-1234567 | ZA 26 123456
_RE_CYN = re.compile(r"\b(?P<country>[A-Z]{2,9})[\s\-/.()]*(?P<year>(?:19|20)\d{2}|\d{2})\)?[\s\-/.]+(?P<number>\d{4,8})\b")
# DV 06523-24-123
_RE_DV = re.compile(r"\bDV[\s\-/.]*(?P<club>\d{4,5})[\s\-/.]+(?P<year>\d{2})[\s\-/.]+(?P<number>\d{1,5})\b")
# 9822 OERF  (Elite)
_RE_NUM_CLUB = re.compile(r"^\s*(?P<number>\d{2,8})[\s\-/]*(?P<club>[A-Z]{2,6})\s*$")
_RE_CLUB_NUM = re.compile(r"^\s*(?P<club>[A-Z]{2,6})[\s\-/]*(?P<number>\d{2,8})\s*$")

# Words that look like a club code in titles but are not.
_NOT_CLUBS = {"COCK", "HEN", "THE", "AND", "SON", "OF", "EX", "X", "ACE", "LOT", "OLR", "RACE", "RING",
              "KM", "KMH", "MPM", "MIN", "MINS", "HRS", "AM", "PM", "R", "ZAR", "IN", "AT", "ON", "TO"}
# Country as written on rings and by the results sites (AfrikaPro 2026 has BULGARIA-25-60582,
# QATAR-26-2112, MAROC-25-81608, SLOVENIJA-25-107-5764 …) → the code used to compare rings.
COUNTRY_ALIAS = {
    "SA": "ZA", "RSA": "ZA", "BEL": "BE", "BELG": "BE", "NED": "NL", "GBR": "GB", "FRA": "FR",
    "BULGARIA": "BG", "QATAR": "QA", "MAROC": "MA", "MAR": "MA", "MOROCCO": "MA", "ESP": "ES", "SPAIN": "ES",
    "PRT": "PT", "POR": "PT", "PORTUGAL": "PT", "HUNG": "HU", "HUN": "HU", "HUNGARY": "HU",
    "SLOVENIJA": "SI", "SLOVENIA": "SI", "SLO": "SI", "AUSTRIA": "AT", "AUT": "AT", "ITALIA": "IT",
    "ITALY": "IT", "ITA": "IT", "DAN": "DK", "DEN": "DK", "DENMARK": "DK", "NAM": "NA", "NAMIBIA": "NA",
    "KWT": "KW", "KUWAIT": "KW", "TUR": "TR", "TURKEY": "TR", "ROU": "RO", "ROM": "RO", "ROMANIA": "RO",
    "POL": "PL", "POLAND": "PL", "GER": "DE", "GERMANY": "DE", "CHN": "CN", "CHINA": "CN",
    "TAIWAN": "TW", "IRL": "IE", "IRELAND": "IE", "SUI": "CH", "SWITZERLAND": "CH", "ZIM": "ZW",
    "ZIMBABWE": "ZW", "BOT": "BW", "BOTSWANA": "BW", "UAE": "AE", "PHI": "PH", "CUBA": "CU",
}
_COUNTRIES = {
    "ZA", "SA", "RSA", "BE", "BEL", "NL", "NED", "GB", "GBR", "DE", "DV", "FR", "FRA", "PL", "CZ",
    "ES", "PT", "IT", "US", "AU", "CN", "TW", "RO", "HU", "SK", "IE", "IHU", "NPA", "BELG", "NEHU",
    "BG", "QA", "MA", "SI", "AT", "DK", "NA", "KW", "TR", "CU", "CH", "IS", "SU", "PH", "RSM", "AE",
    "ZW", "BW", "HR", "RS", "UA", "GR", "SE", "NO", "FI", "LT", "LV", "EE", "MT", "CY", "LU", "MX",
    "BR", "AR", "TH", "JP", "KR", "SG", "MY", "NZ", "CA",
} | set(COUNTRY_ALIAS)


def _scan(rx: re.Pattern, t: str):
    """Like ``rx.finditer`` but a match the caller rejects doesn't hide one starting inside
    it: "LOT 74 - ZA 26-ABC-1234" first matches "LOT 74 - ZA 26" (LOT is no country), and
    plain finditer would then skip the real ring."""
    pos = 0
    while (m := rx.search(t, pos)) is not None:
        yield m
        pos = m.start() + 1


def parse_ring(text: str | None, default_year: int | None = None) -> Ring | None:
    """Parse the first ring in ``text``. Returns None if nothing ring-like is found."""
    if not text:
        return None
    t = str(text).upper()
    sex = None
    sm = SEX_MARK.search(t)
    if sm:
        sex = _SEX_MAP.get(sm.group(1).upper())
    # The FIRST ring in the text, whatever its format: "Lot 74 SA-26-1146 son of ZA 24-GPU-9161"
    # is SA-26-1146 (a fuller-looking ring later on used to win). Same start: fuller format wins.
    found: list[tuple[int, int, Ring]] = []
    for prio, rx in enumerate((_RE_DV, _RE_WORDCLUB, _RE_FULL, _RE_LCYN, _RE_NUMCLUB, _RE_CYN)):
        for m in _scan(rx, t):
            if rx is _RE_DV:
                found.append((m.start(), prio, Ring(m.group(0), "DV", _year4(m.group("year")), m.group("club"),
                                                    m.group("number"), sex)))
            elif m.group("country") in _COUNTRIES and (rx in (_RE_NUMCLUB, _RE_CYN) or m.group("club") not in _NOT_CLUBS):
                club = None if rx is _RE_CYN else re.sub(r"[ /&-]", "", m.group("club"))
                found.append((m.start(), prio, Ring(m.group(0), m.group("country"), _year4(m.group("year")), club,
                                                    m.group("number"), sex)))
                break  # later matches of this format start further on
    if found:
        return min(found, key=lambda x: (x[0], x[1]))[2]
    m = _RE_NUM_CLUB.match(t) or _RE_CLUB_NUM.match(t)
    if m and m.group("club") not in _NOT_CLUBS:
        return Ring(m.group(0).strip(), None, default_year, m.group("club"), m.group("number"), sex)
    return None


def find_rings(text: str | None) -> list[Ring]:
    """Every full-looking ring in free text (pedigrees, descriptions). Short Elite-style
    rings are not extracted from prose; they are too ambiguous."""
    if not text:
        return []
    t = str(text).upper()
    out: list[Ring] = []
    seen: set[str] = set()
    spans: list[tuple[int, int]] = []

    def add(m: re.Match, ring: Ring) -> None:
        if any(a <= m.start() < b for a, b in spans):
            return
        spans.append((m.start(), m.end()))
        key = ring.canonical
        if key not in seen:
            seen.add(key)
            out.append(ring)

    for m in _scan(_RE_DV, t):
        add(m, Ring(m.group(0), "DV", _year4(m.group("year")), m.group("club"), m.group("number")))
    for rx in (_RE_WORDCLUB, _RE_LCYN):
        for m in _scan(rx, t):
            if m.group("country") in _COUNTRIES and m.group("club") not in _NOT_CLUBS:
                add(m, Ring(m.group(0), m.group("country"), _year4(m.group("year")), re.sub(r"[ /&-]", "", m.group("club")),
                            m.group("number")))
    for m in _scan(_RE_FULL, t):
        if m.group("country") in _COUNTRIES and m.group("club") not in _NOT_CLUBS:
            add(m, Ring(m.group(0), m.group("country"), _year4(m.group("year")), m.group("club"), m.group("number")))
    for m in _scan(_RE_NUMCLUB, t):
        if m.group("country") in _COUNTRIES:
            add(m, Ring(m.group(0), m.group("country"), _year4(m.group("year")), m.group("club"), m.group("number")))
    for m in _scan(_RE_CYN, t):
        if m.group("country") in _COUNTRIES:
            add(m, Ring(m.group(0), m.group("country"), _year4(m.group("year")), None, m.group("number")))
    return out


def parse_best_pigeon_title(title: str) -> tuple[Ring | None, str]:
    """``ZA 2026 PORT 7829 (C) Bird Name ...`` → (ring, rest of title)."""
    ring = parse_ring(title)
    if not ring:
        return None, title
    idx = title.upper().find(ring.raw)
    rest = title[idx + len(ring.raw):] if idx >= 0 else title
    rest = SEX_MARK.sub("", rest, count=1).strip(" -–|,")
    return ring, rest


# --------------------------------------------------------------------------- matching

@dataclass
class ResultRing:
    bird_id: int
    ring_norm: str
    ring_raw: str | None = None
    parsed: Ring | None = None


@dataclass
class MatchResult:
    bird_id: int | None
    confidence: str  # exact | contains | fuzzy | manual | none
    candidates: list[int] = field(default_factory=list)
    note: str = ""


class RingIndex:
    """Index of result rings for fast lot matching."""

    def __init__(self, rings: list[ResultRing]):
        self.by_norm: dict[str, int] = {}
        self.long: list[ResultRing] = []
        self.by_number: dict[int, list[ResultRing]] = {}
        for r in rings:
            if not r.ring_norm:
                continue
            self.by_norm.setdefault(r.ring_norm, r.bird_id)
            if len(r.ring_norm) >= 8:
                self.long.append(r)
            p = r.parsed or parse_ring(r.ring_raw or r.ring_norm)
            r.parsed = p
            if p and p.canonical:
                self.by_norm.setdefault(p.canonical, r.bird_id)
            if p and p.number_int is not None:
                self.by_number.setdefault(p.number_int, []).append(r)

    def match(
        self,
        ring_raw: str | None,
        haystacks: list[str | None],
        year: int | None = None,
        override_bird_id: int | None = None,
        fuzzy_texts: list[str | None] | None = None,
        exclude: set[str] | None = None,
        fuzzy_allowed: set[int] | None = None,
    ) -> MatchResult:
        """``haystacks`` must only hold text that names the bird itself (title, ring
        field) — never pedigree prose, or a parent's ring would match as the lot's.
        ``exclude``: normalised rings known to be ancestors (e.g. "son of X" in a title)."""
        exclude = exclude or set()
        if override_bird_id:
            return MatchResult(override_bird_id, "manual")
        norm = normalise(ring_raw)
        if norm and norm in self.by_norm:
            return MatchResult(self.by_norm[norm], "exact")
        parsed_lot = parse_ring(ring_raw) if ring_raw else None
        if parsed_lot and parsed_lot.country and parsed_lot.canonical in self.by_norm:
            return MatchResult(self.by_norm[parsed_lot.canonical], "exact", note="same ring, different formatting")
        # Full rings written in the title/description/pedigree, parsed and re-normalised.
        for text in haystacks:
            for r in find_rings(text):
                if r.norm in exclude or r.canonical in exclude:
                    continue
                for key in (r.norm, r.canonical):
                    if key in self.by_norm and len(key) >= 8:
                        return MatchResult(self.by_norm[key], "exact", note=f"ring found in text: {r.raw}")
        hay = [normalise(h) for h in [ring_raw, *haystacks] if h]
        for ex in exclude:
            hay = [h.replace(ex, "") for h in hay]
        contained = {r.bird_id for r in self.long if any(r.ring_norm in h for h in hay)}
        if len(contained) == 1:
            return MatchResult(contained.pop(), "contains")
        if len(contained) > 1:
            return MatchResult(None, "none", sorted(contained), "ambiguous containment")
        # Fuzzy: year + number + club (Elite-style rings), or country + year + number.
        parsed = parse_ring(ring_raw, default_year=year) if ring_raw else None
        if parsed is None:
            for text in fuzzy_texts or []:
                parsed = parse_ring(text, default_year=year)
                if parsed:
                    break
        if parsed and parsed.number_int is not None:
            # A loose match must agree on everything both rings state: year (known on both),
            # club (present on both — a ring without a club never loosely matches one with
            # one) and country. ``fuzzy_allowed`` limits it to the lot's own OLR.
            cands = []
            y = parsed.year or year
            for r in self.by_number.get(parsed.number_int, []):
                p = r.parsed
                if not p or not y or not p.year or y != p.year:
                    continue
                if not parsed.club or not p.club or parsed.club != p.club:
                    continue
                if parsed.country and p.country and parsed.country != p.country:
                    continue
                if fuzzy_allowed is not None and r.bird_id not in fuzzy_allowed:
                    continue
                cands.append(r.bird_id)
            cands = sorted(set(cands))
            if len(cands) == 1:
                return MatchResult(cands[0], "fuzzy", note="loose match: same year, club and number, ring written differently")
            if cands:
                return MatchResult(None, "none", cands, "ambiguous fuzzy match")
        return MatchResult(None, "none")
