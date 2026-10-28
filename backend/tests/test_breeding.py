"""Breeding score: progeny from listings, siblings via shared parents, honest when empty."""

from olr_scout.scoring import engine

from .helpers import make_lot, make_season

TOP = [1, 2, 1, 3, 2, 1]
MID = [40, 45, 50, 40, 45, 50]


def _world(session):
    # Sire raced 2024; his offspring raced 2026. Field padded so the ace cut is realistic.
    make_season(session, "AfrikaPro", 2024, {"ZA-23-SIRE-101": ("Old Lofts", TOP)}, pad=40)
    make_season(session, "AfrikaPro", 2026, {
        "ZA-25-KID-201": ("New Lofts", TOP), "ZA-25-KID-202": ("New Lofts", TOP),
        "ZA-25-KID-203": ("New Lofts", MID), "ZA-25-OTHER-909": ("Other Lofts", MID),
    }, pad=60)
    # Earlier (closed) auctions named the sire of three 2026 birds.
    for i, ring in enumerate(["ZA-25-KID-201", "ZA-25-KID-202", "ZA-25-KID-203"]):
        make_lot(session, 50 + i, auction_id="old", status="closed", ring_raw=ring,
                 description="Sire: ZA-23-SIRE-101 super breeder.", current_bid=1000)


def test_progeny_siblings_and_confidence(session):
    _world(session)
    sire_for_sale = make_lot(session, 1, ring_raw="ZA-23-SIRE-101", current_bid=2000, description="Proven breeder.")
    youngster = make_lot(session, 2, ring_raw="ZA-26-YOUNG-707", current_bid=800,
                         description="Sire: ZA-23-SIRE-101. Dam: ZA 2022 PORT 555.")
    no_evidence = make_lot(session, 3, ring_raw="ZA-25-OTHER-909", current_bid=800)
    session.flush()
    engine.score_all(session)

    b = sire_for_sale.score_detail["breeding"]
    assert b["progeny"]["n"] == 3 and b["progeny"]["aces"] >= 1
    assert sire_for_sale.breeding_score is not None and b["confidence"] in ("medium", "high")

    y = youngster.score_detail["breeding"]
    assert y["siblings"]["n"] == 3 and y["parents_verified"] == 1  # the sire's own results
    assert youngster.breeding_score is not None

    # Raced well enough to score as a racer, but no offspring/sibling/parent evidence:
    assert no_evidence.tier == "A" and no_evidence.score is not None
    assert no_evidence.breeding_score is None
    assert no_evidence.score_detail["breeding"]["confidence"] == "none"


def test_better_offspring_give_a_better_breeding_score(session):
    make_season(session, "AfrikaPro", 2026, {
        **{f"ZA-25-A-30{i}": ("Lofts A", TOP) for i in range(4)},
        **{f"ZA-25-B-40{i}": ("Lofts B", MID) for i in range(4)},
    }, pad=80)
    for i in range(4):
        make_lot(session, 10 + i, auction_id="old", status="closed", ring_raw=f"ZA-25-A-30{i}",
                 description="Sire: ZA-21-SIREA-501.")
        make_lot(session, 20 + i, auction_id="old", status="closed", ring_raw=f"ZA-25-B-40{i}",
                 description="Sire: ZA-21-SIREB-502.")
    a = make_lot(session, 1, ring_raw="ZA-21-SIREA-501", current_bid=1000)
    b = make_lot(session, 2, ring_raw="ZA-21-SIREB-502", current_bid=1000)
    session.flush()
    engine.score_all(session)
    assert a.breeding_score > b.breeding_score


def test_rank_by_breeding(session):
    from olr_scout.scoring import preferences

    _world(session)
    racer = make_lot(session, 1, ring_raw="ZA-25-OTHER-909", current_bid=500)  # no breeding evidence
    breeder = make_lot(session, 2, ring_raw="ZA-26-YOUNG-707", current_bid=500, description="Sire: ZA-23-SIRE-101.")
    session.flush()
    engine.score_all(session)
    p = preferences.load(session)
    p["rank_by"] = "breeding"
    ids = [x["lot"].id for x in engine.suggestions(session, p)]
    assert ids.index(breeder.id) < ids.index(racer.id)


def test_own_racing_never_carries_more_than_its_share():
    from olr_scout.scoring.progeny import breeding_score

    weak_parent = breeding_score(None, None, [20.0], breeder_rate=None, own_racing=100.0)
    assert weak_parent["used"]["own"] == 0.1 and weak_parent["used"]["parents"] == 0.9
    assert weak_parent["score"] == round(100 * (0.9 * 0.2 + 0.1 * 1.0), 1)
    none = breeding_score(None, None, [], breeder_rate=0.2, own_racing=95.0)
    assert none["score"] is None
