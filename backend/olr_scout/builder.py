"""Family Builder: plan purchases to build a breeding family aimed at OLR aces.

Only verified data drives this mode. A lot's family is the OLR team family of
the bird itself (Tier A) or of its verified ancestors (Tier B). Tier C/D lots
are never put in a plan.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AncestorClaim, Bird, FamilyStat, LoftInventory, Lot, Plan, Season
from .rings import normalise
from .scoring import preferences
from .scoring.preferences import fold
from .scoring.tier_a import FIELD_RATE

TIER_FACTOR = {"A": 1.0, "B": 0.7}
MIN_INCREMENT = 50  # R; assume at least one increment above the current bid


def _key(x: str | None) -> str | None:
    if not x:
        return None
    n = normalise(x)
    return n if any(c.isdigit() for c in n) and len(n) >= 5 else (" ".join(fold(x).split()) or None)


@dataclass
class Candidate:
    kind: str  # lot | inventory
    id: int
    ring: str | None
    sex: str | None
    families: list[str]
    strength: float  # family ace rate / field rate × tier factor
    tier: str | None
    price: int = 0
    max_bid: int = 0
    gen1: set = field(default_factory=set)
    gen2: set = field(default_factory=set)
    label: str = ""
    url: str | None = None
    breeding: float | None = None


def family_records(s: Session, keys: list[str], olrs: set[str] | None = None) -> list[dict]:
    out = []
    for key in keys:
        rows = s.scalars(select(FamilyStat).where(FamilyStat.family_key == key)).all()
        seasons = []
        overall = None
        for r in rows:
            if r.season_id is None:
                overall = r
                continue
            season = s.get(Season, r.season_id)
            if olrs and season and season.olr.name not in olrs:
                continue
            seasons.append({"season_id": r.season_id, "olr": season.olr.name if season else None,
                            "year": season.year if season else None, "entries": r.entries, "aces": r.aces,
                            "finalists": r.finalists, "ace_rate": round(r.ace_rate_shrunk, 4),
                            "best_long": r.best_long})
        best = s.scalars(select(Bird).where(Bird.family_key == key, Bird.long_score.is_not(None))
                         .order_by(Bird.long_score).limit(5)).all()
        out.append({
            "family": key,
            "entries": overall.entries if overall else 0,
            "aces": overall.aces if overall else 0,
            "ace_rate": round(overall.ace_rate_shrunk, 4) if overall else None,
            "finalists": overall.finalists if overall else 0,
            "small_sample": (overall.entries if overall else 0) < 20,
            "seasons": sorted(seasons, key=lambda x: (x["year"] or 0)),
            "best_long": [{"ring": b.ring_raw, "long_score": b.long_score, "year": b.season.year,
                           "olr": b.season.olr.name} for b in best],
            "data_points": overall.entries if overall else 0,
        })
    return out


def _lot_ancestry(s: Session, lot: Lot) -> tuple[set, set, list[str]]:
    gen1, gen2, fams = set(), set(), []
    for t in (lot.sire, lot.dam):
        k = _key(t)
        if k:
            gen1.add(k)
    for c in s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id, AncestorClaim.status != "rejected")):
        k = _key(c.ring_raw) or _key(c.name)
        if not k or c.relation == "related":
            continue
        (gen1 if c.relation in ("sire", "dam", "parent") else gen2).add(k)
        if c.status in ("verified", "mismatch") and c.bird_id:
            b = s.get(Bird, c.bird_id)
            if b and b.family_key:
                fams.append(b.family_key)
    if lot.bird_id:
        b = s.get(Bird, lot.bird_id)
        if b and b.family_key:
            fams.insert(0, b.family_key)
    return gen1, gen2, list(dict.fromkeys(fams))


def _inventory_candidates(s: Session, fam_rate: dict[str, float]) -> list[Candidate]:
    out = []
    for inv in s.scalars(select(LoftInventory)):
        gp = {k for k in (_key(x) for x in (inv.grandparents or [])) if k}
        fam = inv.family
        fkey = None
        if fam:
            from .scoring.tier_a import family_key

            fkey = family_key(fam)
        out.append(Candidate("inventory", inv.id, inv.ring, inv.sex, [fkey] if fkey else [],
                             (fam_rate.get(fkey, FIELD_RATE) / FIELD_RATE) if fkey else 0.0, None,
                             gen1={k for k in (_key(inv.sire), _key(inv.dam)) if k}, gen2=gp,
                             label=f"{inv.ring} ({inv.name or 'own bird'})"))
    return out


def relation(a: Candidate, b: Candidate) -> str:
    """'too close' (shares a parent, or one is the other's parent/grandparent),
    'line-bred' (shares a grandparent), else 'unrelated'."""
    ra, rb = _key(a.ring), _key(b.ring)
    if (ra and ra in b.gen1) or (rb and rb in a.gen1):
        return "too close"
    if a.gen1 & b.gen1:
        return "too close"
    if (ra and ra in b.gen2) or (rb and rb in a.gen2):
        return "line-bred"
    if (a.gen1 | a.gen2) & (b.gen1 | b.gen2):
        return "line-bred"
    return "unrelated"


def build_plan(s: Session, goal: dict, save: bool = True) -> dict:
    prefs = preferences.load(s)
    pairs = int(goal.get("pairs") or 6)
    budget = int(goal.get("budget") or 0)
    cores = [f for f in (goal.get("core_families") or [])][:3]
    olrs = set(goal.get("olrs") or [])  # restricts family records to these OLRs
    target_cocks = int(goal.get("cocks", pairs))
    target_hens = int(goal.get("hens", pairs))
    allow_line_bred = bool(goal.get("allow_line_bred", True))
    fam_rate = {f.family_key: f.ace_rate_shrunk for f in s.scalars(select(FamilyStat).where(FamilyStat.season_id.is_(None)))}
    notes: list[str] = []
    if budget <= 0:
        notes.append("Set a total budget to get a shopping plan.")

    inventory = _inventory_candidates(s, fam_rate)
    have = defaultdict(lambda: {"cock": 0, "hen": 0, "unknown": 0})
    for c in inventory:
        for f in c.families or ["(no family)"]:
            have[f][c.sex or "unknown"] += 1
    need_cocks = max(0, target_cocks - sum(1 for c in inventory if c.sex == "cock"))
    need_hens = max(0, target_hens - sum(1 for c in inventory if c.sex == "hen"))

    cands: list[Candidate] = []
    excluded: list[dict] = []
    for lot in s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")), Lot.tier.in_(("A", "B")))):
        gen1, gen2, fams = _lot_ancestry(s, lot)
        if cores:
            fams = [f for f in fams if f in cores]
            if not fams:
                continue
        if not fams:
            continue
        family_strength = max(fam_rate.get(f, FIELD_RATE) for f in fams) / FIELD_RATE * TIER_FACTOR[lot.tier]
        # Plan on the combined score (your racing/breeding mix, racing at least 50%).
        from .scoring.engine import combined_score

        comb = combined_score(lot, prefs)["score"]
        strength = (comb / 25.0) if comb is not None else family_strength
        price = lot.current_bid if lot.current_bid is not None else (lot.starting_bid or 0)
        limit = preferences.lot_max(lot, lot.family_tags or [], prefs)
        next_bid = price + (MIN_INCREMENT if lot.current_bid else 0)
        c = Candidate("lot", lot.id, lot.ring_raw, lot.sex, fams, strength, lot.tier, price, limit, gen1, gen2,
                      f"{lot.auction_name} lot {lot.lot_no or '?'} {lot.ring_raw or ''}".strip(), lot.url)
        c.breeding = lot.breeding_score
        if next_bid > limit:
            excluded.append({"lot_id": lot.id, "reason": f"price already at/over your max (R{limit:,})"})
            continue
        too_close = [inv for inv in inventory if relation(c, inv) == "too close"]
        if too_close:
            excluded.append({"lot_id": lot.id, "reason": f"too closely related to your {too_close[0].label}"})
            continue
        if not allow_line_bred and any(relation(c, inv) == "line-bred" for inv in inventory):
            excluded.append({"lot_id": lot.id, "reason": "line-bred to a bird you own"})
            continue
        cands.append(c)

    cands.sort(key=lambda c: c.strength / max(c.max_bid, 1), reverse=True)
    chosen: list[Candidate] = []
    total = 0
    got = {"cock": 0, "hen": 0}
    need = {"cock": need_cocks, "hen": need_hens}
    for c in cands:
        if c.sex not in ("cock", "hen"):
            continue
        if got[c.sex] >= need[c.sex]:
            continue
        if budget and total + c.max_bid > budget:
            continue
        chosen.append(c)
        total += c.max_bid
        got[c.sex] += 1
    if got["cock"] < need["cock"] or got["hen"] < need["hen"]:
        notes.append(f"Short by {need['cock'] - got['cock']} cock(s) and {need['hen'] - got['hen']} hen(s) "
                     "within budget, max bids and verified families.")
    unknown_sex = [c for c in cands if c.sex not in ("cock", "hen")]
    if unknown_sex:
        notes.append(f"{len(unknown_sex)} verified lot(s) left out because the sex is not stated.")

    # Pair suggestions among chosen lots + inventory.
    cocks = [c for c in chosen + inventory if c.sex == "cock"]
    hens = [c for c in chosen + inventory if c.sex == "hen"]
    pair_list = []
    for ck in cocks:
        for hn in hens:
            rel = relation(ck, hn)
            cross = bool(ck.families and hn.families and set(ck.families).isdisjoint(hn.families))
            pair_list.append({
                "cock": ck.label, "hen": hn.label, "cock_kind": ck.kind, "hen_kind": hn.kind,
                "relation": rel, "cross": cross,
                "families": [ck.families[:1], hn.families[:1]],
                "strength": round((ck.strength + hn.strength) / 2, 3),
                "nick": "no verified nick data for this cross" if cross else None,
            })
    pair_list.sort(key=lambda p: (p["relation"] == "too close", -p["strength"]))

    # Gap view by core family.
    gaps = []
    per_family = math.ceil(pairs / len(cores)) if cores else pairs
    for fam in cores:
        owned = have.get(fam, {"cock": 0, "hen": 0})
        planned = {"cock": sum(1 for c in chosen if fam in c.families and c.sex == "cock"),
                   "hen": sum(1 for c in chosen if fam in c.families and c.sex == "hen")}
        fill = [{"lot_id": c.id, "label": c.label, "sex": c.sex, "max_bid": c.max_bid, "url": c.url}
                for c in cands if fam in c.families and c not in chosen
                and c.sex in ("cock", "hen") and owned[c.sex] + planned[c.sex] < per_family][:10]
        gaps.append({"family": fam, "have": {"cock": owned["cock"], "hen": owned["hen"]}, "planned": planned,
                     "target_each": per_family, "fill": fill})

    items = [{"lot_id": c.id, "label": c.label, "sex": c.sex, "tier": c.tier, "families": c.families,
              "strength": round(c.strength, 3), "breeding": c.breeding, "current": c.price, "max_bid": c.max_bid,
              "url": c.url, "basis": "combined (racing + breeding)" if c.breeding is not None else "racing only"}
             for c in chosen]
    assert not budget or total <= budget
    result = {"goal": goal, "items": items, "total_max": total, "budget": budget,
              "pairs": pair_list[:60], "gaps": gaps, "excluded": excluded[:50], "notes": notes,
              "families": family_records(s, cores, olrs)}
    if save:
        p = Plan(goal=goal, items=items, total_max=total, notes=notes)
        s.add(p)
        s.flush()
        result["plan_id"] = p.id
    return result
