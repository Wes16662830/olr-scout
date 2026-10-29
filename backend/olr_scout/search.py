"""Find lots by lot number, ring (the bird's own, its matched OLR bird, or a ring its
pedigree names) or breeder (the seller, or the OLR team the bird raced for)."""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AncestorClaim, Bird, Lot
from .rings import normalise

# Lower is a better match; shown on the result so you can see why a lot came up.
WHY = {
    "lot_no": (0, "lot number"),
    "ring": (1, "bird's ring"),
    "olr_ring": (1, "ring in OLR results"),
    "breeder": (2, "seller / breeder"),
    "olr_team": (2, "breeder in OLR results"),
    "pedigree": (3, "named in its pedigree"),
    "text": (4, "mentioned in the listing"),
}
_LOT_NO = re.compile(r"^\s*(?:lot\s*(?:no\.?|nr\.?|#)?\s*)?#?(\d{1,4})\s*$", re.I)


def search(s: Session, q: str, limit: int = 60) -> list[tuple[Lot, list[str]]]:
    q = (q or "").strip()
    if len(q) < 1:
        return []
    hits: dict[int, set[str]] = {}

    def add(lots, why):
        for l in lots:
            hits.setdefault(l.id, set()).add(why)

    m = _LOT_NO.match(q)
    if m:
        add(s.scalars(select(Lot).where(Lot.lot_no == int(m.group(1)))), "lot_no")
    n = normalise(q)
    # Ring searches need enough characters to mean something ("664" yes, "6" no).
    if n and len(re.sub(r"\D", "", n)) >= 3:
        like = f"%{n}%"
        add(s.scalars(select(Lot).where(Lot.ring_norm.ilike(like))), "ring")
        add(s.scalars(select(Lot).join(Bird, Lot.bird_id == Bird.id).where(Bird.ring_norm.ilike(like))), "olr_ring")
        add(s.scalars(select(Lot).join(AncestorClaim, AncestorClaim.lot_id == Lot.id)
                      .where(AncestorClaim.ring_norm.ilike(like), AncestorClaim.status != "rejected")), "pedigree")
    words = q if not m else None
    if words and len(words) >= 3 and re.search(r"[A-Za-z]", words):
        like = f"%{words}%"
        add(s.scalars(select(Lot).where(Lot.seller.ilike(like))), "breeder")
        add(s.scalars(select(Lot).join(Bird, Lot.bird_id == Bird.id).where(Bird.team.ilike(like))), "olr_team")
        add(s.scalars(select(Lot).where(or_(Lot.title.ilike(like), Lot.description.ilike(like),
                                            Lot.pedigree_text.ilike(like), Lot.bloodline.ilike(like)))), "text")
    if not hits:
        return []
    lots = {l.id: l for l in s.scalars(select(Lot).where(Lot.id.in_(hits)))}

    def key(l: Lot):
        best = min(WHY[w][0] for w in hits[l.id])
        live = l.status == "live"
        return (best, not live, -(l.ends_at.timestamp() if l.ends_at and not live else 0),
                l.ends_at.timestamp() if l.ends_at and live else 0, l.auction_name or "", l.lot_no or 0)

    ordered = sorted(lots.values(), key=key)[:limit]
    order = list(WHY)
    return [(l, sorted(hits[l.id], key=order.index)) for l in ordered]
