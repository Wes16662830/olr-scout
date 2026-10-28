"""Spec §11 acceptance tests that can run on SYNTHETIC data.

Tests that need real recorded fixtures live in test_acceptance_recorded.py.
"""

import pytest
from sqlalchemy import select

from olr_scout import builder, refresh
from olr_scout.models import AncestorClaim, Lot, LoftInventory, SourceHealth
from olr_scout.rings import parse_ring
from olr_scout.scoring import engine, preferences
from olr_scout.sources.registry import build_sources

from .helpers import make_lot, make_season

GOOD = [1, 2, 1, 3, 2, 1]


def _prefs(s, **kw):
    p = preferences.load(s)
    p.update(kw)
    preferences.save(s, p)
    return p


def test_elite_short_ring_parses_and_is_low_confidence(session):
    r = parse_ring("9822 OERF", default_year=2026)
    assert (r.number_int, r.club) == (9822, "OERF")
    make_season(session, "AfrikaPro", 2026, {"ZA-26-OERF-9822": ("Kilo Lofts", [10, 20, 30, 40, 50, 60])})
    lot = make_lot(session, 1, source="elite", ring_raw="9822 OERF", year=2026, extra={"ring_low_confidence": True},
                   description="text", current_bid=100)
    engine.score_all(session)
    assert lot.match_confidence == "fuzzy" and "low confidence" in lot.match_note
    assert lot.tier == "A"


def test_best_pigeon_ring():
    r = parse_ring("ZA 2026 PORT 7829 (C)")
    assert (r.country, r.year, r.club, r.number_int, r.sex) == ("ZA", 2026, "PORT", 7829, "cock")


def test_max_bid_and_love_kittel(session):
    make_season(session, "AfrikaPro", 2026, {
        "ZA-26-1": ("Alpha Lofts", GOOD), "ZA-26-2": ("Alpha Lofts", GOOD), "ZA-26-3": ("Beta Lofts", [50] * 6),
    })
    _prefs(session, max_bid=5000, families=[{"name": "Kittel", "aliases": ["kittel"], "weight": "love"}])
    kittel = make_lot(session, 1, ring_raw="ZA-26-1", title="Lot 1 Kittel cock", current_bid=4000)
    neutral = make_lot(session, 2, ring_raw="ZA-26-2", title="Lot 2 Janssen cock", current_bid=4000)
    pricey = make_lot(session, 3, ring_raw="ZA-26-3", title="Lot 3", current_bid=5001)
    engine.score_all(session)
    assert kittel.score == neutral.score  # identical race records
    sugg = engine.suggestions(session)
    assert all(x["price"] <= 5000 for x in sugg)
    ids = [x["lot"].id for x in sugg]
    assert pricey.id not in ids
    assert ids.index(kittel.id) < ids.index(neutral.id)


def test_claim_mismatch_son_of_ace_at_40th_percentile(session):
    # 40th percentile in every race, in a 100-bird field (so not an ace by definition).
    make_season(session, "AfrikaPro", 2025, {"BE-24-1234567": ("Gamma Lofts", [40, 40, 40, 40, 40, 40]),
                                             **{f"ZA-25-{i}": ("Filler Lofts", [i % 30 + 1] * 6) for i in range(99)}})
    lot = make_lot(session, 1, title="Unraced youngster", description="Son of ace BE-24-1234567, a super pigeon.",
                   current_bid=1000)
    engine.score_all(session)
    claim = session.scalar(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id))
    assert claim.status == "mismatch" and claim.claims_ace
    assert lot.claim_mismatch is True
    assert lot.tier == "B"  # the parent IS verified, just not as claimed


def test_parent_ring_in_description_is_not_the_lots_own_ring(session):
    make_season(session, "AfrikaPro", 2025, {"BE-24-7654321": ("Gamma Lofts", GOOD)})
    lot = make_lot(session, 1, title="Son of BE-24-7654321", description="Sire BE-24-7654321", current_bid=100)
    engine.score_all(session)
    assert lot.bird_id is None and lot.tier == "B"


def test_verified_ace_claim_is_not_a_mismatch(session):
    make_season(session, "AfrikaPro", 2025, {"BE-24-7654321": ("Gamma Lofts", GOOD)}, pad=30)
    lot = make_lot(session, 1, description="Son of ace BE-24-7654321.", current_bid=1000)
    engine.score_all(session)
    assert lot.tier == "B" and not lot.claim_mismatch


def test_tier_c_cap_and_ordering(session):
    make_season(session, "AfrikaPro", 2026, {"ZA-26-9": ("Weak Lofts", [95, 95, 95, 95, 95, 95])})
    _prefs(session, families=[{"name": "Kittel", "aliases": ["kittel"], "weight": "love"}])
    a = make_lot(session, 1, ring_raw="ZA-26-9", current_bid=100)
    c = make_lot(session, 2, title="Kittel super breeder", description="Kittel. Many club wins.", bloodline="Kittel",
                 current_bid=100)
    engine.score_all(session)
    assert c.tier == "C" and c.score <= 60 and engine.rank_score(c, preferences.load(session)) <= 60
    # Force equal scores: tier still decides.
    a.score = c.score
    ids = [x["lot"].id for x in engine.suggestions(session)]
    assert ids.index(a.id) < ids.index(c.id)
    for lot in session.scalars(select(Lot).where(Lot.tier == "C")):
        assert lot.score <= 60


def test_no_results_link_means_seller_claimed_without_numbers(session):
    from olr_scout.serialize import lot_card

    lot = make_lot(session, 1, auction_name="Shamwari Lofts Production Sale", olr_tag=None,
                   description="Janssen x Freddy, sire won many club races", current_bid=800)
    engine.score_all(session)
    card = lot_card(lot, preferences.load(session))
    assert card["tier"] == "C" and card["tier_label"] == "seller-claimed, unverified"
    assert card["performance"] is None


def test_family_builder_budget_max_and_line_bred(session):
    _, birds = make_season(session, "AfrikaPro", 2026, {
        **{f"ZA-26-{i}": ("Alpha Lofts", GOOD) for i in range(1, 7)},
        **{f"ZA-26-{i}": ("Filler Lofts", [80] * 6) for i in range(20, 40)},
    })
    _prefs(session, max_bid=3000, per_lot_max={})
    lots = []
    for i, (sex, price) in enumerate([("cock", 1000), ("cock", 2500), ("hen", 1500), ("hen", 900), ("cock", 2900), ("hen", 2000)], 1):
        lots.append(make_lot(session, i, ring_raw=f"ZA-26-{i}", sex=sex, current_bid=price))
    # Lot 1 (cock) and lot 3 (hen) share a grandparent.
    lots[0].description = "Sire: ZA 2023 PORT 555. Grandson of ZA 2019 PORT 112."
    lots[2].description = "Dam: ZA 2022 PORT 777. Granddaughter of ZA 2019 PORT 112."
    session.flush()
    _prefs(session, per_lot_max={str(lots[1].id): 2600})
    engine.score_all(session)
    plan = builder.build_plan(session, {"pairs": 2, "budget": 7000, "core_families": ["alpha lofts"]})
    assert plan["total_max"] <= 7000
    for item in plan["items"]:
        assert item["max_bid"] <= 3000
        if item["lot_id"] == lots[1].id:
            assert item["max_bid"] <= 2600
    pair = next(p for p in plan["pairs"] if lots[0].ring_raw in p["cock"] and lots[2].ring_raw in p["hen"]) \
        if any(lots[0].ring_raw in p["cock"] and lots[2].ring_raw in p["hen"] for p in plan["pairs"]) else None
    if pair is None:  # not both picked — check the relation directly
        c1 = builder.Candidate("lot", lots[0].id, lots[0].ring_raw, "cock", [], 1, "A")
        c1.gen1, c1.gen2, _ = builder._lot_ancestry(session, lots[0])
        c3 = builder.Candidate("lot", lots[2].id, lots[2].ring_raw, "hen", [], 1, "A")
        c3.gen1, c3.gen2, _ = builder._lot_ancestry(session, lots[2])
        assert builder.relation(c1, c3) == "line-bred"
    else:
        assert pair["relation"] == "line-bred"


def test_builder_never_over_budget_small_budget(session):
    make_season(session, "AfrikaPro", 2026, {f"ZA-26-{i}": ("Alpha Lofts", GOOD) for i in range(1, 5)})
    for i in range(1, 5):
        make_lot(session, i, ring_raw=f"ZA-26-{i}", sex="cock" if i % 2 else "hen", current_bid=1800)
    engine.score_all(session)
    plan = builder.build_plan(session, {"pairs": 2, "budget": 6000, "core_families": ["alpha lofts"]})
    assert plan["total_max"] <= 6000 and plan["notes"]


def test_builder_excludes_birds_too_close_to_inventory(session):
    make_season(session, "AfrikaPro", 2026, {"ZA-26-1": ("Alpha Lofts", GOOD)})
    lot = make_lot(session, 1, ring_raw="ZA-26-1", sex="cock", current_bid=500, sire="ZA 2023 PORT 555")
    session.add(LoftInventory(ring="ZA 2024 PORT 1", ring_norm="ZA2024PORT1", sex="hen", sire="ZA 2023 PORT 555"))
    session.flush()
    engine.score_all(session)
    plan = builder.build_plan(session, {"pairs": 1, "budget": 5000, "core_families": ["alpha lofts"]})
    assert not plan["items"]
    assert any(e["lot_id"] == lot.id and "too closely related" in e["reason"] for e in plan["excluded"])


def test_blocked_source_degrades_only_itself(session, client, web):
    web.blocked_hosts.add("bestpigeon.co.za")
    sources = build_sources(client)
    reports = refresh.refresh_all(session, sources)
    health = {h.source_id: h for h in session.scalars(select(SourceHealth))}
    assert health["bestpigeon"].status == "degraded" and "blocked" in health["bestpigeon"].message
    assert health["toppigeon"].status == "ok"
    assert health["elite"].status == "ok"
    assert health["afripigeon"].status == "ok"
    assert health["pah"].status == "empty"
    assert session.scalars(select(Lot).where(Lot.source == "toppigeon")).all()
    assert {r["source"] for r in reports} == {"toppigeon", "elite", "bestpigeon", "afripigeon", "pah"}


def test_own_lot_flag_and_leading(session, client):
    refresh.refresh_all(session, build_sources(client))
    own = session.scalar(select(Lot).where(Lot.source == "elite", Lot.lot_key == "a3"))
    assert own.own_lot
    lot1 = session.scalar(select(Lot).where(Lot.source == "toppigeon", Lot.lot_no == 1,
                                            Lot.auction_name == "AfrikaPro 2026 Auction 2"))
    assert preferences.user_is_leading(lot1, preferences.load(session))
