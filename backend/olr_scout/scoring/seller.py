"""Seller reliability: how often birds a seller sold went on to be OLR aces."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Bird, Lot, Season, SellerStat
from .preferences import fold
from .tier_a import FIELD_RATE, shrunk_rate


def seller_key(name: str | None) -> str | None:
    k = " ".join(fold(name).split()) if name else ""
    return k or None


def recompute(s: Session) -> int:
    """Count past lots whose ring later raced in an OLR season (year ≥ lot year) that
    the lot was not itself sold out of — i.e. the bird was sold before it raced."""
    birds_by_ring: dict[str, list[tuple[Bird, Season]]] = defaultdict(list)
    for b, season in s.execute(select(Bird, Season).join(Season, Bird.season_id == Season.id)).all():
        birds_by_ring[b.ring_norm].append((b, season))
    agg: dict[str, dict] = {}
    for lot in s.scalars(select(Lot).where(Lot.seller.is_not(None), Lot.ring_norm.is_not(None))):
        key = seller_key(lot.seller)
        if not key:
            continue
        for b, season in birds_by_ring.get(lot.ring_norm, []):
            if lot.year and season.year < lot.year:
                continue
            if lot.olr_tag and season.olr and season.olr.name == lot.olr_tag:
                continue  # a post-race OLR sale, not a breeder's youngster
            a = agg.setdefault(key, {"display": lot.seller, "rings": set(), "aces": set()})
            a["rings"].add(lot.ring_norm)
            if b.is_ace:
                a["aces"].add(lot.ring_norm)
    s.execute(delete(SellerStat))
    for key, a in agg.items():
        n, aces = len(a["rings"]), len(a["aces"])
        rate = shrunk_rate(aces, n)
        s.add(SellerStat(seller_key=key, display=a["display"], sold_raced=n, aces=aces,
                         ace_rate_shrunk=rate, factor=max(0.5, min(1.5, rate / FIELD_RATE))))
    s.flush()
    return len(agg)


def lookup(s: Session, seller: str | None) -> SellerStat | None:
    key = seller_key(seller)
    return s.get(SellerStat, key) if key else None
