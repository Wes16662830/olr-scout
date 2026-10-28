"""Map loosely-known JSON lot objects (AfriPigeon, future sites) to ``Lot``."""

from __future__ import annotations

from ..rings import find_rings, normalise, parse_ring
from ..util.money import parse_zar
from ..util.timeutil import parse_iso, parse_local_datetime
from .base import Lot, clean_text, parse_sex

LOT_KEYS = {"lot_number", "lotNumber", "lot_no", "ring_number", "ringNumber", "current_bid", "currentBid", "highest_bid"}


def first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def looks_like_lot_list(data) -> list[dict] | None:
    """Return the list of lot dicts inside ``data`` if it looks like one."""
    if isinstance(data, dict):
        for k in ("lots", "items", "data", "results", "auction_lots"):
            if isinstance(data.get(k), list):
                found = looks_like_lot_list(data[k])
                if found is not None:
                    return found
        return None
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data[:5]):
        keys = set().union(*(x.keys() for x in data[:5]))
        if keys & LOT_KEYS or ({"title", "price"} <= keys) or ("ring" in keys):
            return data
    return None


def json_to_lot(d: dict, source: str, auction_id: str, auction_name: str | None, url: str, seller: str | None) -> Lot:
    ring_raw = clean_text(str(first(d, "ring_number", "ringNumber", "ring", "ring_no", default="") or "")) or None
    title = clean_text(first(d, "title", "name", "lot_title", "pigeon_name", default="")) or ""
    ends = first(d, "ends_at", "end_time", "endTime", "end_date_time", "closing_time", "lot_end")
    ends_at = parse_iso(ends) if ends else None
    if ends and ends_at is None:
        ends_at = parse_local_datetime(str(ends))
    if ends_at is None and d.get("end_date") and d.get("end_time"):
        ends_at = parse_local_datetime(f"{d['end_date']} {d['end_time']}")
    lot = Lot(
        source=source, auction_id=auction_id, auction_name=auction_name,
        lot_key=str(first(d, "id", "lot_id", "uuid", default=title)),
        url=url, title=title, seller=seller,
        lot_no=first(d, "lot_number", "lotNumber", "lot_no"),
        ring_raw=ring_raw, ring_norm=normalise(ring_raw) if ring_raw else None,
        sex=parse_sex(str(first(d, "sex", "gender", default="") or "")),
        colour=first(d, "colour", "color"),
        bloodline=first(d, "bloodline", "strain", "bloodline_name"),
        sire=first(d, "sire", "father"), dam=first(d, "dam", "mother"),
        pedigree_text=clean_text(str(first(d, "pedigree", "pedigree_text", default="") or "")) or None,
        pedigree_url=first(d, "pedigree_url", "pdf_url", "pedigree_image"),
        description=clean_text(first(d, "description", "details")),
        performance_claims=clean_text(first(d, "performance", "performance_highlights", "results")),
        current_bid=parse_zar(first(d, "current_bid", "currentBid", "highest_bid", "price")),
        starting_bid=parse_zar(first(d, "starting_bid", "startingBid", "start_price", "opening_bid")),
        reserve_price=parse_zar(first(d, "reserve_price", "reserve")),
        bid_count=first(d, "total_bids", "bid_count", "bids_count", "bidCount"),
        ends_at=ends_at,
        image_url=first(d, "image_url", "image", "photo", "thumbnail"),
        status=str(first(d, "status", default="live")).lower(),
    )
    y = first(d, "year", "ring_year")
    try:
        lot.year = int(y) if y else None
    except (TypeError, ValueError):
        pass
    if lot.ring_raw:
        p = parse_ring(lot.ring_raw, default_year=lot.year)
        if p:
            lot.year = lot.year or p.year
            lot.sex = lot.sex or p.sex
    elif title:
        rings = find_rings(title)
        if rings:
            lot.ring_raw, lot.ring_norm, lot.year = rings[0].raw, normalise(rings[0].raw), lot.year or rings[0].year
    lot.detail_loaded = True
    return lot
