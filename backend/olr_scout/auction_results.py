"""Auction results: what closed lots sold for, compared with their race form."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BidHistory, Lot
from .refresh import CLOSED
from .scoring import preferences
from .scoring.preferences import fold
from .scoring.tier_a import spearman
from .serialize import iso


def _closed_lots(s: Session, source: str | None = None, auction_id: str | None = None) -> list[Lot]:
    q = select(Lot).where(Lot.status.in_(CLOSED), Lot.closed_at.is_not(None))
    if source:
        q = q.where(Lot.source == source)
    if auction_id:
        q = q.where(Lot.auction_id == auction_id)
    return list(s.scalars(q))


def _summary(lots: list[Lot], still_live: int = 0) -> dict:
    sold = [l for l in lots if l.sale_status == "sold" and l.final_price is not None]
    prices = sorted(l.final_price for l in sold)
    return {
        "lots": len(lots) + still_live,
        "closed": len(lots),
        "still_live": still_live,
        "sold": len(sold),
        "unsold": sum(1 for l in lots if l.sale_status == "unsold"),
        "turnover": sum(prices),
        "buyers": len({fold(l.winner) for l in sold if l.winner}),
        "average": round(sum(prices) / len(prices)) if prices else None,
        "median": prices[len(prices) // 2] if prices else None,
        "top": prices[-1] if prices else None,
        "first_close": iso(min((l.closed_at for l in lots), default=None)),
        "last_close": iso(max((l.closed_at for l in lots), default=None)),
    }


def auctions(s: Session) -> list[dict]:
    """Every auction with at least one closed lot, newest first."""
    by: dict[tuple[str, str], list[Lot]] = defaultdict(list)
    for lot in _closed_lots(s):
        by[(lot.source, lot.auction_id)].append(lot)
    live = defaultdict(int)
    for src, aid in s.execute(select(Lot.source, Lot.auction_id).where(Lot.status.in_(("live", "upcoming")))):
        live[(src, aid)] += 1
    out = []
    for (src, aid), lots in by.items():
        out.append({"source": src, "auction_id": aid, "auction_name": lots[0].auction_name,
                    "olr_tag": lots[0].olr_tag, **_summary(lots, live.get((src, aid), 0))})
    return sorted(out, key=lambda a: a["last_close"] or "", reverse=True)


def _yours(s: Session, lots: list[Lot], prefs: dict) -> dict[int, str]:
    names = {fold(n) for n in prefs.get("own", {}).get("usernames", []) if n}
    if not names:
        return {}
    out = {}
    for lot in lots:
        if lot.winner and fold(lot.winner) in names:
            out[lot.id] = "won" if lot.sale_status == "sold" else "bid"  # top bid on an unsold lot is not a win
    bidders = s.execute(select(BidHistory.lot_id, BidHistory.bidder).where(
        BidHistory.lot_id.in_([l.id for l in lots])))
    for lot_id, bidder in bidders:
        if bidder and fold(bidder) in names and lot_id not in out:
            out[lot_id] = "bid"
    return out


def auction_detail(s: Session, source: str, auction_id: str) -> dict:
    prefs = preferences.load(s)
    lots = _closed_lots(s, source, auction_id)
    still_live = len(s.scalars(select(Lot.id).where(Lot.source == source, Lot.auction_id == auction_id,
                                                    Lot.status.in_(("live", "upcoming")))).all())
    yours = _yours(s, lots, prefs)
    rows = []
    for lot in sorted(lots, key=lambda l: (l.lot_no is None, l.lot_no or 0, l.id)):
        d = lot.score_detail or {}
        bird = lot.bird
        rows.append({
            "id": lot.id, "lot_no": lot.lot_no, "ring": lot.ring_raw, "title": lot.title,
            "bird_name": (bird.name if bird else None) or (lot.extra or {}).get("bird_name"),
            "breeder": bird.team if bird else None, "seller": lot.seller, "sex": lot.sex,
            "tier": lot.tier, "score": lot.score, "is_ace": bool(d.get("is_ace")), "long_score": d.get("long_score"),
            "final_price": lot.final_price, "sale_status": lot.sale_status, "sale_note": lot.sale_note,
            "winner": lot.winner, "bids": lot.bid_count, "closed_at": iso(lot.closed_at), "url": lot.url,
            "final_read": bool(lot.final_read), "yours": yours.get(lot.id),
        })
    sold = [r for r in rows if r["sale_status"] == "sold" and r["final_price"] and r["score"] is not None]
    verified = [r for r in sold if r["tier"] in ("A", "B")]
    rho = spearman([r["final_price"] for r in verified], [r["score"] for r in verified]) if len(verified) >= 5 else None
    # Best value: highest verified score per R1,000 paid.
    value = sorted(verified, key=lambda r: -(r["score"] / max(r["final_price"], 100)))[:5]
    top_sales = sorted(sold, key=lambda r: -r["final_price"])[:5]
    return {
        "source": source, "auction_id": auction_id,
        "auction_name": lots[0].auction_name if lots else None,
        "summary": _summary(lots, still_live),
        "price_vs_form": {"verified_sold": len(verified), "spearman": round(rho, 2) if rho is not None else None},
        "best_value": value, "top_sales": top_sales, "lots": rows,
        "yours": {"won": sum(1 for v in yours.values() if v == "won"), "bid": sum(1 for v in yours.values() if v == "bid")},
    }
