"""JSON shapes for the API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import object_session

from .models import AncestorClaim, BidHistory, Bird, Flight
from .scoring import engine, preferences
from .scoring.tier_a import long_flight_ids, FlightIn
from .util.timeutil import as_aware


def iso(dt):
    dt = as_aware(dt)
    return dt.isoformat() if dt else None


def _race_label(f: Flight, i: int) -> str:
    if f.is_final:
        return "F"
    return f"R{f.race_no}" if f.race_no else f"R{i}"


def bird_summary(s, bird: Bird) -> dict:
    """Who entered the bird and how it did, race by race (from OLR results)."""
    flights = s.scalars(select(Flight).where(Flight.season_id == bird.season_id, Flight.is_training.is_(False))
                        .order_by(Flight.flown_at, Flight.id)).all()
    long_ids = set(long_flight_ids([FlightIn(f.id, f.distance_km) for f in flights]))
    pos = {r.flight_id: r.position for r in bird.results}
    races = []
    for i, f in enumerate(flights, 1):
        p = pos.get(f.id)
        races.append({"label": _race_label(f, i), "name": f.name, "km": f.distance_km, "position": p,
                      "arrived": f.arrived, "pct": round(p / f.arrived, 4) if p and f.arrived else None,
                      "long": f.id in long_ids, "final": f.is_final})
    flown = [r for r in races if r["position"]]
    best = min(flown, key=lambda r: r["pct"] if r["pct"] is not None else 9) if flown else None
    return {
        "ring": bird.ring_raw, "name": bird.name, "colour": bird.colour, "sex": bird.sex,
        "breeder": bird.team, "breeder_country": bird.team_country,
        "olr": bird.season.olr.name, "season": bird.season.year, "registered": bird.season.registered,
        "races": races, "arrived_in": len(flown), "race_count": len(races),
        "best": {"label": best["label"], "position": best["position"], "arrived": best["arrived"]} if best else None,
        "is_ace": bird.is_ace, "long_score": bird.long_score, "final_position": bird.final_position,
        "hard_score": bird.hard_score, "arrival_rate": bird.arrival_rate, "lost_after": bird.lost_after,
        "speed_index": bird.speed_index, "speed_pct": bird.speed_pct,
    }


def _record(b: Bird | None) -> dict | None:
    if b is None:
        return None
    return {"ring": b.ring_raw, "name": b.name, "olr": b.season.olr.name, "season": b.season.year,
            "long_score": b.long_score, "is_ace": b.is_ace, "breeder": b.team}


def parents(s, lot) -> dict:
    """Sire/dam from the listing's text or pedigree, each verified against OLR results where possible."""
    claims = s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id,
                                                   AncestorClaim.status != "rejected")).all()
    order = {"sire": 0, "dam": 1, "parent": 2}
    out = []
    for c in sorted((c for c in claims if c.relation in order), key=lambda c: order[c.relation]):
        out.append({"relation": c.relation, "ring": c.ring_raw, "name": c.name, "status": c.status,
                    "claims_ace": c.claims_ace, "record": _record(s.get(Bird, c.bird_id) if c.bird_id else None)})
    have = {p["relation"] for p in out}
    for rel, text in (("sire", lot.sire), ("dam", lot.dam)):
        if text and rel not in have:
            out.append({"relation": rel, "ring": None, "name": text[:80], "status": "claimed", "claims_ace": False,
                        "record": None})
    grand = [c for c in claims if c.relation == "grandparent"]
    return {"parents": out, "grandparents": {"total": len(grand),
                                             "verified": sum(c.status in ("verified", "mismatch") for c in grand)},
            "pedigree_url": lot.pedigree_url}


def last_bid(s, lot) -> dict | None:
    """The most recent bid as the site shows it (amount, bidder, time), else what the
    listing gives (current bid and bid count, no bidder)."""
    b = s.scalars(select(BidHistory).where(BidHistory.lot_id == lot.id)
                  .order_by(BidHistory.amount.desc(), BidHistory.at.desc()).limit(1)).first()
    if b is not None and b.amount is not None:
        return {"amount": b.amount, "bidder": b.bidder, "at": iso(b.at), "count": lot.bid_count,
                "bidder_shown": True}
    if lot.current_bid is not None:
        return {"amount": lot.current_bid, "bidder": None, "at": None, "count": lot.bid_count,
                "bidder_shown": False}
    return None


def lot_card(lot, prefs: dict, extra: dict | None = None) -> dict:
    tags = lot.family_tags or []
    limit = preferences.lot_max(lot, tags, prefs)
    price = lot.current_bid if lot.current_bid is not None else lot.starting_bid
    d = lot.score_detail or {}
    tier = lot.tier
    card = {
        "id": lot.id, "source": lot.source, "auction_id": lot.auction_id, "auction_name": lot.auction_name,
        "seller": lot.seller, "lot_no": lot.lot_no, "title": lot.title, "ring": lot.ring_raw,
        "sex": lot.sex, "year": lot.year, "colour": lot.colour, "bloodline": lot.bloodline,
        "current_bid": lot.current_bid, "starting_bid": lot.starting_bid, "reserve_price": lot.reserve_price,
        "reserve_met": lot.reserve_met, "bid_count": lot.bid_count, "price": price, "max": limit,
        "near_max": price is not None and limit - int(prefs.get("near_max_buffer", 0)) <= price <= limit,
        "over_max": price is not None and price > limit,
        "ends_at": iso(lot.ends_at), "url": lot.url, "image_url": lot.image_url, "status": lot.status,
        "olr_tag": lot.olr_tag, "olr_year": lot.olr_year,
        "tier": tier, "score": lot.score, "rank_score": engine.rank_score(lot, prefs),
        "tier_label": d.get("label"),
        "match_confidence": lot.match_confidence, "match_note": lot.match_note,
        "ring_low_confidence": bool((lot.extra or {}).get("ring_low_confidence")),
        "family_tags": tags, "claim_mismatch": lot.claim_mismatch, "own_lot": lot.own_lot,
        "you_lead": preferences.user_is_leading(lot, prefs),
        "ancestors": d.get("ancestors"), "seller_stat": d.get("seller"),
        # Performance numbers only where results are verified (Tier A/B).
        "performance": ({k: d.get(k) for k in ("long_score", "all_score", "is_ace", "final_position",
                                                 "family_key", "family_rate", "family_entries",
                                                 "small_family_sample", "components", "missing", "olr", "season")}
                        if tier == "A" else ({"ancestor_scores": d.get("ancestor_scores")} if tier == "B" else None)),
        "performance_claims": lot.performance_claims,
        "fetched_at": iso(lot.fetched_at),
        "breeding_score": lot.breeding_score,
        "breeding": d.get("breeding"),
    }
    sess = object_session(lot)
    if sess is not None:
        card["bird"] = bird_summary(sess, lot.bird) if (tier == "A" and lot.bird is not None) else None
        card["lineage"] = parents(sess, lot)
        card["last_bid"] = last_bid(sess, lot)
        card["bird_name"] = (card["bird"] or {}).get("name") or (lot.extra or {}).get("bird_name")
    if extra:
        card.update(extra)
    return card
