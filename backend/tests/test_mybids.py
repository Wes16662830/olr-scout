from datetime import timedelta

from sqlalchemy import select

from olr_scout import alerts
from olr_scout.models import Alert, BidHistory, Watch
from olr_scout.mybids import auto_watch, my_bid
from olr_scout.scoring import preferences
from olr_scout.scoring.preferences import bidder_match
from olr_scout.util.timeutil import now_utc

from .helpers import make_lot

PREFS = {"own": {"usernames": ["GeForce RTX"]}}


def test_name_matching_including_masked_names():
    assert bidder_match("GeForce RTX", PREFS) == "exact"
    assert bidder_match("geforce  rtx", PREFS) == "exact"
    assert bidder_match("G*********X", PREFS) == "masked"
    assert bidder_match("ge***tx", PREFS) == "masked"
    assert bidder_match("g***", PREFS) is None  # too little visible
    assert bidder_match("b***r", PREFS) is None
    assert bidder_match("pigeonman", PREFS) is None


def _bids(session, lot, rows):
    for i, (who, amount) in enumerate(rows):
        session.add(BidHistory(lot_id=lot.id, bidder=who, amount=amount, at=now_utc() - timedelta(minutes=10 - i)))
    session.flush()


def test_leading_outbid_and_auto_watch(session):
    p = preferences.load(session)
    lead = make_lot(session, 58, current_bid=3500, leading_bidder="G*********X")
    _bids(session, lead, [("b***r", 3000), ("G*********X", 3500)])
    outbid = make_lot(session, 59, current_bid=3800, leading_bidder="b***r")
    _bids(session, outbid, [("GeForce RTX", 3500), ("b***r", 3800)])
    other = make_lot(session, 60, current_bid=900)
    _bids(session, other, [("b***r", 900)])

    assert my_bid(session, lead, p) == {"status": "leading", "your_max": 3500, "match": "masked", "top": 3500,
                                        "top_bidder": "G*********X"}
    assert my_bid(session, outbid, p)["status"] == "outbid" and my_bid(session, outbid, p)["your_max"] == 3500
    assert my_bid(session, other, p) is None

    assert auto_watch(session) == 2
    watched = {w.lot_id for w in session.scalars(select(Watch))}
    assert watched == {lead.id, outbid.id}

    new = alerts.evaluate(session)
    out = [a for a in new if a.kind == "outbid"]
    assert len(out) == 1 and out[0].lot_id == outbid.id and "R3,800" in out[0].message
    assert not [a for a in alerts.evaluate(session) if a.kind == "outbid"]  # once per new top bid


def test_removed_auto_watch_stays_removed(session, client):
    from fastapi.testclient import TestClient

    from olr_scout.api import create_app

    lot = make_lot(session, 58, current_bid=3500)
    _bids(session, lot, [("GeForce RTX", 3500)])
    auto_watch(session)
    session.commit()
    api = TestClient(create_app(start_scheduler=False))
    api.post("/api/login", json={"password": "test-password"})
    assert api.delete(f"/api/lots/{lot.id}/watch").status_code == 200
    session.expire_all()
    assert auto_watch(session) == 0
    assert session.scalar(select(Watch).where(Watch.lot_id == lot.id)) is None


def test_manual_mark_for_sites_without_names(session):
    from fastapi.testclient import TestClient

    from olr_scout.api import create_app

    lot = make_lot(session, 70, source="elite", current_bid=1200, bid_count=4)
    session.commit()
    api = TestClient(create_app(start_scheduler=False))
    api.post("/api/login", json={"password": "test-password"})
    d = api.post(f"/api/lots/{lot.id}/mybid", json={"on": True, "amount": 1200}).json()
    assert d["my_bid"]["status"] == "leading" and d["my_bid"]["match"] == "manual" and d["watched"]
    lot.current_bid = 1500
    session.commit()
    session.expire_all()
    assert my_bid(session, lot, preferences.load(session))["status"] == "outbid"
