"""Old auctions leave the watchlist and search even when their site can't be re-read."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from olr_scout.api import create_app
from olr_scout.models import Watch
from olr_scout.refresh import close_stale, upsert_lot
from olr_scout.sources.base import Lot as SrcLot
from olr_scout.util.timeutil import now_utc

from .helpers import make_lot


def _api():
    api = TestClient(create_app(start_scheduler=False))
    api.post("/api/login", json={"password": "test-password"})
    return api


def test_lots_past_closing_are_closed_even_if_the_site_is_blocked(session):
    old = make_lot(session, 1, current_bid=900, bid_count=2, ends_at=now_utc() - timedelta(hours=3))
    recent = make_lot(session, 2, ends_at=now_utc() - timedelta(minutes=20))  # final read still due
    unseen = make_lot(session, 3, ends_at=None, fetched_at=now_utc() - timedelta(days=4))
    running = make_lot(session, 4, ends_at=now_utc() + timedelta(hours=2))
    assert close_stale(session) == 2
    assert (old.status, recent.status, unseen.status, running.status) == ("closed", "live", "closed", "live")
    assert old.sale_status == "sold" and "last one seen" in old.extra["closed_note"]


def test_a_lot_shown_running_again_reopens(session):
    lot = make_lot(session, 1, source="toppigeon", auction_id="a1", lot_key="k1", current_bid=900, bid_count=1,
                   ends_at=now_utc() - timedelta(hours=2))
    close_stale(session)
    assert lot.status == "closed" and lot.closed_at is not None
    upsert_lot(session, SrcLot(source="toppigeon", auction_id="a1", auction_name="Test Auction", lot_key="k1", url=lot.url, title="Lot 1",
                               status="live", ends_at=now_utc() + timedelta(minutes=5), fetched_at=now_utc()))
    assert lot.status == "live" and lot.closed_at is None and "closed_note" not in lot.extra


def test_watchlist_drops_lots_a_day_after_closing(session):
    gone = make_lot(session, 1, status="closed", ends_at=now_utc() - timedelta(days=2),
                    closed_at=now_utc() - timedelta(days=2))
    stale = make_lot(session, 2, ends_at=now_utc() - timedelta(days=5))  # never closed: site blocked
    today = make_lot(session, 3, status="closed", ends_at=now_utc() - timedelta(hours=3),
                     closed_at=now_utc() - timedelta(hours=3))
    live = make_lot(session, 4, ends_at=now_utc() + timedelta(hours=3))
    for l in (gone, stale, today, live):
        session.add(Watch(lot_id=l.id))
    session.commit()
    rows = _api().get("/api/watchlist").json()
    assert [r["lot"]["lot_no"] for r in rows] == [4, 3]  # today's result kept for a day
    session.expire_all()
    assert {w.lot_id for w in session.scalars(select(Watch))} == {today.id, live.id}


def test_search_shows_running_auctions_unless_asked(session):
    make_lot(session, 6, auction_name="AfrikaPro", ends_at=now_utc() + timedelta(hours=3))
    make_lot(session, 6, lot_key="old-6", auction_name="Old Auction", status="closed",
             ends_at=now_utc() - timedelta(days=30))
    make_lot(session, 6, lot_key="stale-6", auction_name="Stale", ends_at=now_utc() - timedelta(days=9))
    session.commit()
    api = _api()
    r = api.get("/api/search?q=6").json()
    assert [l["auction_name"] for l in r["lots"]] == ["AfrikaPro"] and r["closed_count"] == 2
    r = api.get("/api/search?q=6&closed=true").json()
    assert [l["auction_name"] for l in r["lots"]][0] == "AfrikaPro" and len(r["lots"]) == 3
