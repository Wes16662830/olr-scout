"""Your own bids: found in the bid history the sites show (your usernames from
Settings, also when the site masks them), or marked by hand with "I bid on this"
for sites that show no bidder names. Lots you bid on are added to the watchlist
automatically (once: removing one keeps it removed) and raise an alert when
you are outbid."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BidHistory, Lot, Watch
from .scoring import preferences


def my_bid(s: Session, lot: Lot, prefs: dict) -> dict | None:
    """{"status": leading|outbid|bid, "your_max", "match": exact|masked|manual, "top", "top_bidder"} or None."""
    rows = s.scalars(select(BidHistory).where(BidHistory.lot_id == lot.id)).all()
    mine = [(b, preferences.bidder_match(b.bidder, prefs)) for b in rows]
    mine = [(b, m) for b, m in mine if m]
    manual = bool((lot.extra or {}).get("my_bid"))
    if not mine and not manual:
        return None
    top = max(rows, key=lambda b: (b.amount or 0), default=None)
    top_amount = top.amount if top else lot.current_bid
    top_bidder = top.bidder if top else lot.leading_bidder
    if mine:
        your_max = max(b.amount or 0 for b, _ in mine)
        match = "exact" if any(m == "exact" for _, m in mine) else "masked"
        leading = top is not None and preferences.bidder_match(top.bidder, prefs) is not None
        status = "leading" if leading else "outbid"
        # The listing's price moved past the history we hold: someone bid since — not known who.
        if leading and lot.current_bid is not None and top.amount is not None and lot.current_bid > top.amount:
            status = "bid"
    else:
        your_max = (lot.extra or {}).get("my_bid_amount")
        match = "manual"
        # Without bidder names we only know your amount if you entered it.
        if your_max and lot.current_bid is not None:
            status = "leading" if your_max >= lot.current_bid else "outbid"
        else:
            status = "bid"
    return {"status": status, "your_max": your_max or None, "match": match,
            "top": top_amount, "top_bidder": top_bidder}


def auto_watch(s: Session, prefs: dict | None = None) -> int:
    """Put every live lot you bid on in the watchlist (unless you removed it)."""
    prefs = prefs or preferences.load(s)
    watched = {w.lot_id for w in s.scalars(select(Watch))}
    added = 0
    for lot in s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")))):
        if lot.id in watched or (lot.extra or {}).get("auto_watch_dismissed"):
            continue
        if my_bid(s, lot, prefs) is not None:
            s.add(Watch(lot_id=lot.id, auto=True))
            added += 1
    s.flush()
    return added
