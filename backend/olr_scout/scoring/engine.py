"""Assign each lot an evidence tier and a score, then rank suggestions.

Tier A  bird's own ring matched to OLR results          → Bid Score
Tier B  sire/dam/grandparents verified in OLR results   → ancestors' verified results
Tier C  seller text/image only                          → bloodline + seller record, capped at 60
Tier D  no usable data                                  → shown, never suggested

A higher tier always outranks a lower tier.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AncestorClaim, Bird, FamilyStat, Flight, Lot
from ..rings import RingIndex, ResultRing, normalise, parse_ring
from . import pedigree, preferences, seller
from ..util.timeutil import as_aware, now_utc
from .tier_a import bid_score

TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass
class Context:
    prefs: dict
    family_rate: dict[str, tuple[float, int]]  # family key → (shrunk rate, entries) all seasons
    season_has_final: dict[int, bool]
    index: RingIndex
    birds: dict[int, Bird]
    birds_by_ring: dict[str, list[Bird]]
    best_pct: dict[int, float | None]


def build_context(s: Session, prefs: dict | None = None) -> Context:
    prefs = prefs or preferences.load(s)
    fam = {f.family_key: (f.ace_rate_shrunk, f.entries) for f in s.scalars(select(FamilyStat).where(FamilyStat.season_id.is_(None)))}
    finals = defaultdict(bool)
    for f in s.scalars(select(Flight).where(Flight.is_final.is_(True))):
        finals[f.season_id] = True
    birds = {b.id: b for b in s.scalars(select(Bird))}
    by_ring: dict[str, list[Bird]] = defaultdict(list)
    rings = []
    for b in birds.values():
        by_ring[b.ring_norm].append(b)
        rings.append(ResultRing(b.id, b.ring_norm, b.ring_raw))
    best: dict[int, float | None] = {}
    flights = {f.id: f for f in s.scalars(select(Flight))}
    for b in birds.values():
        pcts = [r.position / flights[r.flight_id].arrived for r in b.results
                if r.position and flights.get(r.flight_id) and flights[r.flight_id].arrived]
        best[b.id] = min(pcts) if pcts else None
    return Context(prefs, fam, finals, RingIndex(rings), birds, by_ring, best)


# ----------------------------------------------------------------- matching

def match_lot(lot: Lot, ctx: Context) -> None:
    if lot.override_none:
        lot.bird_id, lot.match_confidence, lot.match_note = None, "none", "manual: no results for this bird"
        return
    # Only the ring field and the title name the bird itself. Rings the title
    # introduces as ancestors ("son of X") are excluded.
    ancestors = {c.ring_norm for c in pedigree.extract_claims(lot.title) if c.relation != "ancestor"}
    for c in pedigree.extract_claims(lot.title):
        p = parse_ring(c.ring_raw)
        if p and c.relation != "ancestor":
            ancestors.add(p.canonical)
    res = ctx.index.match(
        lot.ring_raw,
        [lot.title],
        year=lot.year,
        override_bird_id=lot.override_bird_id,
        exclude=ancestors,
    )
    # Prefer the season of the OLR the lot refers to when a ring raced in several.
    if res.bird_id and res.confidence != "manual":
        b = ctx.birds.get(res.bird_id)
        if b and lot.olr_year:
            for alt in ctx.birds_by_ring.get(b.ring_norm, []):
                if alt.season.year == lot.olr_year:
                    res.bird_id = alt.id
    lot.bird_id = res.bird_id
    lot.match_confidence = res.confidence
    note = res.note
    if res.confidence == "fuzzy" and (lot.extra or {}).get("ring_low_confidence"):
        note = (note + "; " if note else "") + "low confidence: short ring (number + club only)"
    if res.candidates:
        note = (note + "; " if note else "") + f"{len(res.candidates)} candidate birds"
    lot.match_note = note or None


# ----------------------------------------------------------------- claims

def refresh_claims(s: Session, lot: Lot, ctx: Context) -> list[AncestorClaim]:
    """Re-extract text claims (keeping user-confirmed/manual and OCR ones)."""
    existing = list(s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id)))
    keep = [c for c in existing if c.confirmed_by_user or c.origin in ("manual", "ocr", "pdf")]
    for c in existing:
        if c not in keep:
            s.delete(c)
    kept_rings = {c.ring_norm for c in keep}
    for c in pedigree.extract_claims(lot.sire and f"Sire: {lot.sire}", lot.dam and f"Dam: {lot.dam}",
                                     lot.pedigree_text, lot.description, lot.performance_claims,
                                     lot.title, own_ring=lot.ring_raw):
        if c.ring_norm in kept_rings:
            continue
        ac = AncestorClaim(lot_id=lot.id, relation=c.relation, ring_raw=c.ring_raw, ring_norm=c.ring_norm,
                           name=c.name, claim_text=c.text, origin=c.origin, claims_ace=c.claims_ace)
        s.add(ac)
        keep.append(ac)
    for c in keep:
        verify_claim(c, ctx)
    return keep


def verify_claim(c: AncestorClaim, ctx: Context) -> None:
    if c.status == "rejected":
        return
    birds = ctx.birds_by_ring.get(c.ring_norm or "", [])
    if not birds and c.ring_raw:
        p = parse_ring(c.ring_raw)
        if p and p.canonical:
            res = ctx.index.match(c.ring_raw, [])
            birds = [ctx.birds[res.bird_id]] if res.bird_id and res.confidence == "exact" else []
    raced = [b for b in birds if ctx.best_pct.get(b.id) is not None]
    if not raced:
        c.bird_id, c.status = None, "claimed"
        return
    best_bird = min(raced, key=lambda b: (b.long_score if b.long_score is not None else 1.0))
    c.bird_id = best_bird.id
    mismatch = pedigree.is_mismatch(
        c.claims_ace, any(b.is_ace for b in raced), min(ctx.best_pct[b.id] for b in raced),
        ctx.prefs.get("mismatch_threshold", 0.20),
    )
    c.status = "mismatch" if mismatch else "verified"


# ----------------------------------------------------------------- scoring

def _long_for(b: Bird, emphasis: str) -> float:
    long_s = b.long_score if b.long_score is not None else 1.0
    all_s = b.all_score if b.all_score is not None else 1.0
    if emphasis == "middle":
        return all_s
    if emphasis == "balanced":
        return (long_s + all_s) / 2
    return long_s


def _consistency(b: Bird, ctx: Context) -> float:
    races = [r for r in b.results if r.flight and not r.flight.is_training]
    n_races = sum(1 for f in b.season.flights if not f.is_training) or 1
    good = sum(1 for r in races if r.position and r.flight.arrived and r.position / r.flight.arrived <= 0.5)
    return good / n_races


def score_bird(b: Bird, ctx: Context, sibling_longs: list[float] | None = None):
    fam = ctx.family_rate.get(b.family_key) if b.family_key else None
    final_pct = None
    if b.final_position:
        finals = [f for f in b.season.flights if f.is_final and f.arrived]
        if finals:
            final_pct = min(1.0, b.final_position / finals[0].arrived)
    return bid_score(
        _long_for(b, ctx.prefs.get("distance_emphasis", "distance")),
        _consistency(b, ctx),
        final_pct,
        ctx.season_has_final.get(b.season_id, False),
        fam[0] if fam else None,
        sibling_longs,
        ctx.prefs.get("weights"),
        ctx.prefs.get("family_ceiling", 0.20),
    )


def _norm_parent(text: str | None) -> str | None:
    if not text:
        return None
    rings = parse_ring(text)
    return normalise(rings.raw) if rings else " ".join(preferences.fold(text).split())


def sibling_longs(lot: Lot, siblings: dict[str, list[Lot]], ctx: Context) -> list[float]:
    out = []
    for key in (_norm_parent(lot.sire), _norm_parent(lot.dam)):
        for other in siblings.get(key or "", []):
            if other.id != lot.id and other.bird_id and other.bird_id in ctx.birds:
                ob = ctx.birds[other.bird_id]
                if ob.long_score is not None:
                    out.append(ob.long_score)
    return out


def score_lot(s: Session, lot: Lot, ctx: Context, siblings: dict[str, list[Lot]]) -> None:
    prefs = ctx.prefs
    tags = preferences.family_tags(lot, prefs)
    lot.family_tags = tags
    lot.own_lot = preferences.is_own_lot(lot, prefs)
    claims = refresh_claims(s, lot, ctx)
    verified = [c for c in claims if c.status in ("verified", "mismatch") and c.bird_id]
    lot.claim_mismatch = any(c.status == "mismatch" for c in claims)
    sstat = seller.lookup(s, lot.seller)
    detail: dict = {
        "ancestors": {"verified": sum(c.status == "verified" for c in claims),
                      "mismatch": sum(c.status == "mismatch" for c in claims),
                      "claimed": sum(c.status == "claimed" for c in claims)},
        "seller": {"sold_raced": sstat.sold_raced, "aces": sstat.aces, "ace_rate": round(sstat.ace_rate_shrunk, 4),
                   "factor": round(sstat.factor, 3)} if sstat else None,
        "pref_multiplier": preferences.preference_multiplier(tags),
    }
    bird = ctx.birds.get(lot.bird_id) if lot.bird_id else None
    if bird is not None:
        sib = sibling_longs(lot, siblings, ctx)
        bs = score_bird(bird, ctx, sib)
        lot.tier, lot.score = "A", bs.score
        fam = ctx.family_rate.get(bird.family_key)
        detail.update({
            "label": "raced and verified",
            "components": bs.components, "weights": bs.weights_used, "missing": bs.missing,
            "long_score": bird.long_score, "all_score": bird.all_score, "is_ace": bird.is_ace,
            "final_position": bird.final_position, "family_key": bird.family_key,
            "family_rate": round(fam[0], 4) if fam else None, "family_entries": fam[1] if fam else 0,
            "small_family_sample": (fam[1] if fam else 0) < 20, "siblings": len(sib),
            "olr": bird.season.olr.name, "season": bird.season.year,
        })
    elif verified:
        total_w = 0.0
        acc = 0.0
        parts = []
        for c in verified:
            ab = ctx.birds[c.bird_id]
            w = pedigree.generation_weight(c.relation)
            sc = score_bird(ab, ctx).score
            acc += w * sc
            total_w += w
            parts.append({"relation": c.relation, "ring": c.ring_raw, "score": sc, "is_ace": ab.is_ace,
                          "long_score": ab.long_score, "olr": ab.season.olr.name, "season": ab.season.year,
                          "status": c.status})
        base = acc / total_w if total_w else 0.0
        has_parent = any(c.relation in ("sire", "dam", "parent") for c in verified)
        coverage = 1.0 if has_parent else 0.8
        factor = sstat.factor if sstat else 1.0
        lot.tier, lot.score = "B", round(min(100.0, base * coverage * factor), 1)
        detail.update({"label": "verified parentage", "ancestor_scores": parts, "coverage": coverage,
                       "seller_factor": factor})
    elif tags or lot.pedigree_text or lot.description or lot.bloodline or lot.pedigree_url or lot.performance_claims:
        cap = float(prefs.get("tier_c_cap", 60.0))
        bloodline_comp = 1.0 if tags else (0.5 if lot.bloodline else 0.25)
        seller_comp = min(1.0, sstat.ace_rate_shrunk / prefs.get("family_ceiling", 0.20)) if sstat else 0.25
        lot.tier = "C"
        lot.score = round(min(cap, cap * (0.6 * seller_comp + 0.4 * bloodline_comp)), 1)
        detail.update({"label": "seller-claimed, unverified", "bloodline_component": bloodline_comp,
                       "seller_component": seller_comp, "cap": cap})
    else:
        lot.tier, lot.score = "D", None
        detail.update({"label": "no usable data"})
    lot.score_detail = detail


def rank_score(lot: Lot, prefs: dict) -> float | None:
    if lot.score is None:
        return None
    mult = preferences.preference_multiplier(lot.family_tags or [])
    v = lot.score * mult
    if lot.tier == "C":
        v = min(v, float(prefs.get("tier_c_cap", 60.0)))
    return round(min(100.0, v), 2)


def score_all(s: Session, lots: list[Lot] | None = None) -> int:
    ctx = build_context(s)
    lots = lots if lots is not None else list(s.scalars(select(Lot)))
    for lot in lots:
        match_lot(lot, ctx)
    s.flush()
    siblings: dict[str, list[Lot]] = defaultdict(list)
    for lot in s.scalars(select(Lot).where((Lot.sire.is_not(None)) | (Lot.dam.is_not(None)))):
        for key in (_norm_parent(lot.sire), _norm_parent(lot.dam)):
            if key:
                siblings[key].append(lot)
    for lot in lots:
        score_lot(s, lot, ctx, siblings)
    s.flush()
    return len(lots)


# ----------------------------------------------------------------- suggestions

def passes_filters(lot: Lot, prefs: dict, ctx_birds: dict[int, Bird] | None = None) -> tuple[bool, str]:
    if lot.tier in (None, "D"):
        return False, "no usable data"
    if lot.tier == "C" and not prefs.get("include_tier_c", True):
        return False, "Tier C excluded in settings"
    if preferences.preference_multiplier(lot.family_tags or []) == 0.0:
        return False, "avoided family"
    if lot.own_lot and prefs.get("own", {}).get("exclude_own"):
        return False, "own lot"
    sex = prefs.get("sex", "any")
    if sex in ("cock", "hen") and lot.sex and lot.sex != sex:
        return False, "sex"
    if prefs.get("year_min") and lot.year and lot.year < int(prefs["year_min"]):
        return False, "year"
    if prefs.get("year_max") and lot.year and lot.year > int(prefs["year_max"]):
        return False, "year"
    if prefs.get("ace_only") and not (lot.score_detail or {}).get("is_ace"):
        return False, "not an ace"
    mr = int(prefs.get("min_races") or 0)
    if mr and lot.tier == "A" and lot.bird is not None and len([r for r in lot.bird.results if r.position]) < mr:
        return False, "too few races"
    return True, ""


def suggestions(s: Session, prefs: dict | None = None, include_over_max: bool = False) -> list[dict]:
    prefs = prefs or preferences.load(s)
    out = []
    stale = now_utc() - timedelta(minutes=5)  # anti-sniping can extend a little past the listed end
    for lot in s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")))):
        if lot.ends_at is not None and as_aware(lot.ends_at) < stale:
            continue
        ok, why = passes_filters(lot, prefs)
        if not ok:
            continue
        limit = preferences.lot_max(lot, lot.family_tags or [], prefs)
        price = lot.current_bid if lot.current_bid is not None else (lot.starting_bid or 0)
        if price > limit and not include_over_max:
            continue
        rs = rank_score(lot, prefs)
        out.append({"lot": lot, "max": limit, "price": price, "rank_score": rs,
                    "near_max": price >= limit - int(prefs.get("near_max_buffer", 0)),
                    "value": round(rs / max(price, 100) * 1000, 2) if rs is not None else None})
    out.sort(key=lambda x: (TIER_ORDER.get(x["lot"].tier, 9), -(x["rank_score"] or 0), x["price"]))
    # Value rank within budget (higher score per R1,000 = better value).
    by_value = sorted([x for x in out if x["value"] is not None], key=lambda x: -x["value"])
    for i, x in enumerate(by_value, 1):
        x["value_rank"] = i
    return out


REASON_TEXT = {
    "no usable data": "no usable data (Tier D: ring not in the downloaded OLR results, no pedigree or seller text)",
    "Tier C excluded in settings": "seller-claimed only, and Tier C is switched off in Settings",
    "avoided family": "a bloodline you marked Avoid",
    "own lot": "your own lots (hidden in Settings)",
    "sex": "wrong sex for your Settings",
    "year": "outside your year range",
    "not an ace": "not an ace (aces-only is on)",
    "too few races": "fewer races than your minimum",
    "over max": "current bid above your max",
    "closed": "closing time has passed",
}


def auction_overview(s: Session, prefs: dict | None = None) -> list[dict]:
    """Every running auction with its lot count, how many are suggested, and why the
    rest are not — so an auction never silently disappears from the filter."""
    prefs = prefs or preferences.load(s)
    stale = now_utc() - timedelta(minutes=5)
    out: dict[str, dict] = {}
    for lot in s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")))):
        key = f"{lot.source}:{lot.auction_id}"
        a = out.setdefault(key, {"key": key, "source": lot.source, "auction_id": lot.auction_id,
                                 "auction_name": lot.auction_name, "olr_tag": lot.olr_tag, "lots": 0,
                                 "suggested": 0, "tiers": {}, "hidden": {}})
        a["lots"] += 1
        a["tiers"][lot.tier or "?"] = a["tiers"].get(lot.tier or "?", 0) + 1
        if lot.ends_at is not None and as_aware(lot.ends_at) < stale:
            why = "closed"
        else:
            ok, why = passes_filters(lot, prefs)
            if ok:
                limit = preferences.lot_max(lot, lot.family_tags or [], prefs)
                price = lot.current_bid if lot.current_bid is not None else (lot.starting_bid or 0)
                why = "over max" if price > limit else ""
        if why:
            text = REASON_TEXT.get(why, why)
            a["hidden"][text] = a["hidden"].get(text, 0) + 1
        else:
            a["suggested"] += 1
    return sorted(out.values(), key=lambda a: (-a["suggested"], -a["lots"]))
