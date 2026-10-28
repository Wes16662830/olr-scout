"""Auction source interface and the normalised Lot/Auction records every adapter returns."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from ..rings import normalise
from ..util.http import PoliteClient
from ..util.timeutil import as_aware, now_utc

# A lot page is re-read when its price changed, it closes within this window,
# or the last read is older than DETAIL_MAX_AGE. Otherwise the listing is enough.
DETAIL_CLOSE_WINDOW = timedelta(minutes=60)
DETAIL_MAX_AGE = timedelta(hours=6)


@dataclass
class Auction:
    source: str
    auction_id: str
    name: str
    url: str | None = None
    seller: str | None = None
    status: str = "live"  # live | upcoming
    lot_count: int | None = None
    first_close: datetime | None = None
    olr_tag: str | None = None
    olr_year: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Lot:
    source: str
    auction_id: str
    auction_name: str | None
    lot_key: str
    url: str
    title: str = ""
    seller: str | None = None
    lot_no: int | None = None
    ring_raw: str | None = None
    ring_norm: str | None = None
    sex: str | None = None
    year: int | None = None
    colour: str | None = None
    sire: str | None = None
    dam: str | None = None
    bloodline: str | None = None
    pedigree_text: str | None = None
    pedigree_url: str | None = None
    description: str | None = None
    performance_claims: str | None = None
    current_bid: int | None = None
    starting_bid: int | None = None
    reserve_price: int | None = None
    reserve_met: bool | None = None
    bid_count: int | None = None
    ends_at: datetime | None = None
    image_url: str | None = None
    status: str = "live"
    olr_tag: str | None = None
    olr_year: int | None = None
    fetched_at: datetime = field(default_factory=now_utc)
    bids: list[dict] = field(default_factory=list)  # [{bidder, amount, at}]
    detail_loaded: bool = False
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.ring_raw and not self.ring_norm:
            self.ring_norm = normalise(self.ring_raw)

    def to_dict(self) -> dict:
        return asdict(self)


class AuctionSource(ABC):
    key: str = ""
    name: str = ""
    base_url: str = ""
    #: Whether the adapter's parsing has been confirmed against live pages.
    verified: bool = False

    def __init__(self, client: PoliteClient):
        self.client = client
        #: lot_key → {"bid", "start", "detail_at", "ends_at"} from the database,
        #: set by the refresh so unchanged lot pages are not downloaded again.
        self.known: dict[str, dict] = {}
        #: live progress for the Sources screen
        self.progress: dict = {}

    def need_detail(self, lot: "Lot") -> bool:
        k = self.known.get(lot.lot_key)
        if not k or not k.get("detail_at"):
            return True
        if (lot.current_bid, lot.starting_bid) != (k.get("bid"), k.get("start")) and (
            lot.current_bid is not None or lot.starting_bid is not None
        ):
            return True
        now = now_utc()
        ends = as_aware(k.get("ends_at"))
        if ends is None or ends - now < DETAIL_CLOSE_WINDOW:
            return True
        return now - as_aware(k["detail_at"]) > DETAIL_MAX_AGE

    def tick(self, **kw) -> None:
        self.progress.update(kw)

    @abstractmethod
    def fetch_active(self) -> list[Auction]: ...

    @abstractmethod
    def fetch_lots(self, auction: Auction) -> list[Lot]: ...

    def refresh_lot(self, lot: Lot) -> Lot | None:
        """Re-read one lot (used for the 20 s hot refresh). Default: unsupported."""
        return None


# --------------------------------------------------------------------- OLR tagging

DEFAULT_OLR_ALIASES: dict[str, list[str]] = {
    "AfrikaPro": ["afrikapro", "afrika pro"],
    "Marlbank OLR Winter": ["marlbank"],
    "Dinokeng": ["dinokeng"],
    "Karoo Million": ["karoo million", "karoo"],
    "Cape Blue": ["cape blue"],
}

_YEAR = re.compile(r"\b(20\d{2})\b")


def tag_olr(text: str, aliases: dict[str, list[str]] | None = None) -> tuple[str | None, int | None]:
    """Find which OLR (and year) a title or auction name refers to."""
    aliases = aliases or DEFAULT_OLR_ALIASES
    low = (text or "").lower()
    for name, words in aliases.items():
        if any(w in low for w in words):
            m = _YEAR.search(text)
            return name, int(m.group(1)) if m else None
    return None, None


def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"[ \t ]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip() or None


SEX_WORDS = {
    "cock": "cock", "male": "cock", "c": "cock", "doffer": "cock", "mannetjie": "cock",
    "hen": "hen", "female": "hen", "h": "hen", "duivin": "hen", "wyfie": "hen",
}


def parse_sex(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower()
    if t in SEX_WORDS:
        return SEX_WORDS[t]
    if re.search(r"\(\s*c\s*\)|\bcock\b", t):
        return "cock"
    if re.search(r"\(\s*h\s*\)|\bhen\b", t):
        return "hen"
    return None
