"""JSON shapes for the API."""

from __future__ import annotations

from .scoring import engine, preferences
from .util.timeutil import as_aware


def iso(dt):
    dt = as_aware(dt)
    return dt.isoformat() if dt else None


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
    }
    if extra:
        card.update(extra)
    return card
