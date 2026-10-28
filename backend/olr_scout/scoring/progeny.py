"""Breeding evidence: who bred whom, and how the offspring raced.

Parent→offspring links come from every auction listing the app has seen: a
lot names its sire/dam (seller text or pedigree, read into ancestor claims),
and the lot's own ring is found in OLR results. Over many auctions this
gives each parent a progeny record, and each bird its siblings' records.

Breeding score (0–100), from the strongest evidence down:
    progeny 40 · siblings 25 · verified parents 15 · breeder record 10 · own racing 10
Only computed when progeny, sibling or verified-parent evidence exists; a
bird's own racing is never presented as a breeding score on its own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AncestorClaim, Bird, Lot
from .tier_a import FAMILY_CEILING, FIELD_RATE

PARENT_RELATIONS = ("sire", "dam", "parent")
PRIOR_N = 10  # offspring-worth of field-average evidence each record starts with
LAYER_WEIGHTS = {"progeny": 40.0, "siblings": 25.0, "parents": 15.0, "breeder": 10.0, "own": 10.0}


@dataclass
class OffspringRecord:
    n: int
    aces: int
    ace_rate: float  # shrunk toward the 5% field rate
    mean_long: float  # shrunk toward the average stored bird
    birds: list[dict] = field(default_factory=list)

    def strength(self) -> float:
        """0..1: 60% ace rate (full marks at 20%), 40% average long-race placing."""
        return 0.6 * min(1.0, self.ace_rate / FAMILY_CEILING) + 0.4 * (1.0 - self.mean_long)


class ProgenyIndex:
    def __init__(self, s: Session):
        birds = list(s.scalars(select(Bird)))
        self.best: dict[str, Bird] = {}
        for b in birds:  # a ring that raced several seasons: keep its best season
            cur = self.best.get(b.ring_norm)
            if cur is None or (b.long_score or 1.0) < (cur.long_score or 1.0):
                self.best[b.ring_norm] = b
        longs = [b.long_score for b in birds if b.long_score is not None]
        self.mean_long = sum(longs) / len(longs) if longs else 0.6
        self.offspring_of: dict[str, set[str]] = defaultdict(set)
        self.parents_of: dict[str, set[str]] = defaultdict(set)
        rows = s.execute(
            select(AncestorClaim.ring_norm, Lot.ring_norm, Lot.bird_id)
            .join(Lot, Lot.id == AncestorClaim.lot_id)
            .where(AncestorClaim.relation.in_(PARENT_RELATIONS), AncestorClaim.status != "rejected",
                   AncestorClaim.ring_norm.is_not(None))
        ).all()
        by_id = {b.id: b for b in birds}
        for parent, lot_ring, bird_id in rows:
            child = by_id[bird_id].ring_norm if bird_id in by_id else lot_ring
            if not parent or not child or parent == child:
                continue
            self.offspring_of[parent].add(child)
            self.parents_of[child].add(parent)

    def record(self, rings: set[str]) -> OffspringRecord | None:
        """Racing record of the given offspring rings (only those found in OLR results)."""
        raced = [self.best[r] for r in rings if r in self.best]
        if not raced:
            return None
        aces = sum(1 for b in raced if b.is_ace)
        n = len(raced)
        longs = [b.long_score if b.long_score is not None else 1.0 for b in raced]
        mean_long = (sum(longs) + self.mean_long * 5) / (n + 5)
        return OffspringRecord(
            n=n, aces=aces, ace_rate=(aces + FIELD_RATE * PRIOR_N) / (n + PRIOR_N), mean_long=mean_long,
            birds=[{"ring": b.ring_raw, "name": b.name, "olr": b.season.olr.name, "season": b.season.year,
                    "long_score": b.long_score, "is_ace": b.is_ace}
                   for b in sorted(raced, key=lambda x: x.long_score if x.long_score is not None else 1.0)[:8]],
        )

    def progeny(self, ring: str | None) -> OffspringRecord | None:
        return self.record(self.offspring_of.get(ring, set())) if ring else None

    def siblings(self, ring: str | None, parents: set[str]) -> OffspringRecord | None:
        sibs: set[str] = set()
        for p in parents | (self.parents_of.get(ring, set()) if ring else set()):
            sibs |= self.offspring_of.get(p, set())
        sibs.discard(ring or "")
        return self.record(sibs)


def breeding_score(progeny: OffspringRecord | None, siblings: OffspringRecord | None,
                   parent_scores: list[float], breeder_rate: float | None, own_racing: float | None,
                   weights: dict[str, float] | None = None) -> dict:
    """Returns {"score": float|None, "confidence", "components", "used", "missing"}."""
    w = dict(LAYER_WEIGHTS)
    w.update(weights or {})
    comps: dict[str, float] = {}
    if progeny:
        comps["progeny"] = progeny.strength()
    if siblings:
        comps["siblings"] = siblings.strength()
    if parent_scores:
        comps["parents"] = sum(parent_scores) / len(parent_scores) / 100.0
    evidence = bool(comps)  # progeny, siblings or verified parents
    if breeder_rate is not None:
        comps["breeder"] = min(1.0, breeder_rate / FAMILY_CEILING)
    if own_racing is not None:
        comps["own"] = own_racing / 100.0
    missing = [k for k in LAYER_WEIGHTS if k not in comps]
    if not evidence:
        return {"score": None, "confidence": "none", "components": {}, "used": {}, "missing": missing}
    # Breeder record and own racing are context: they keep their fixed share of the full
    # weight (10% each by default) and are never scaled up when evidence is thin. The
    # breeding evidence present shares the rest, so it always carries most of the score.
    total_all = sum(w.values()) or 1.0
    context = [k for k in ("breeder", "own") if k in comps]
    ctx_share = {k: w[k] / total_all for k in context}
    evid = [k for k in ("progeny", "siblings", "parents") if k in comps]
    evid_total = sum(w[k] for k in evid) or 1.0
    rest = 1.0 - sum(ctx_share.values())
    used = {**{k: rest * w[k] / evid_total for k in evid}, **ctx_share}
    score = round(100.0 * sum(comps[k] * used[k] for k in comps), 1)
    n = (progeny.n if progeny else 0) + (siblings.n if siblings else 0)
    if n >= 8:
        confidence = "high"
    elif n >= 3 or len(parent_scores) >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    return {"score": score, "confidence": confidence, "components": {k: round(v, 3) for k, v in comps.items()},
            "used": {k: round(v, 3) for k, v in used.items()}, "missing": missing}
