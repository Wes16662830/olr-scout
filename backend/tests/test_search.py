"""Search lots by lot number, ring and breeder."""

from olr_scout import search
from olr_scout.models import AncestorClaim
from olr_scout.scoring import engine

from .helpers import make_lot, make_season

TOP = [1, 2, 1, 3, 2, 1]


def _setup(session):
    make_season(session, "AfrikaPro", 2025, {"ZA-25-PORT-7829": ("Van Wyk Lofts", TOP)}, pad=40)
    a = make_lot(session, 1, lot_no=6, auction_name="AfrikaPro", ring_raw="ZA-25-PORT-7829", seller="Piet Botha")
    b = make_lot(session, 2, lot_no=6, auction_name="Dinokeng", ring_raw="ZA-25-DINO-1234", seller="Sunstone Lofts",
                 description="Bred by Jan Smit")
    c = make_lot(session, 3, lot_no=58, auction_name="Dinokeng", ring_raw="ZA-25-DINO-5555", status="closed")
    session.add(AncestorClaim(lot_id=c.id, relation="sire", ring_raw="ZA-22-MOUN-6640", ring_norm="ZA22MOUN6640",
                              origin="pdf"))
    engine.score_all(session)
    return a, b, c


def ids(session, q):
    return [(l.id, why) for l, why in search.search(session, q)]


def test_lot_number_finds_every_auction_with_that_number(session):
    a, b, c = _setup(session)
    assert {i for i, _ in ids(session, "6")} == {a.id, b.id}
    assert ids(session, "Lot 58") == [(c.id, ["lot_no"])]


def test_ring_in_any_format_and_pedigree_rings(session):
    a, b, c = _setup(session)
    assert ids(session, "za 25 port 7829")[0] == (a.id, ["ring", "olr_ring"])
    assert ids(session, "7829")[0][0] == a.id
    assert ids(session, "MOUN 6640") == [(c.id, ["pedigree"])]  # lots whose pedigree names that bird


def test_breeder_seller_team_and_listing_text(session):
    a, b, c = _setup(session)
    assert ids(session, "botha") == [(a.id, ["breeder"])]
    assert ids(session, "van wyk") == [(a.id, ["olr_team"])]  # the team the bird raced for
    assert ids(session, "jan smit") == [(b.id, ["text"])]
    assert ids(session, "zz") == [] and ids(session, "") == []
