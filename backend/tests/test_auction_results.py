from datetime import timedelta

import httpx
from sqlalchemy import select

from olr_scout import auction_results, refresh
from olr_scout.models import Lot
from olr_scout.sources.registry import build_sources
from olr_scout.util.timeutil import now_utc

from .helpers import make_lot


def test_settle_outcomes(session):
    sold = make_lot(session, 1, status="closed", current_bid=3000, bid_count=4, reserve_met=True, leading_bidder="b***r")
    no_res = make_lot(session, 2, status="closed", current_bid=900, bid_count=2, reserve_met=False)
    no_bids = make_lot(session, 3, status="closed", current_bid=None, bid_count=0)
    for lot in (sold, no_res, no_bids):
        refresh.settle(lot)
    assert (sold.sale_status, sold.final_price, sold.winner) == ("sold", 3000, "b***r")
    assert (no_res.sale_status, no_res.sale_note) == ("unsold", "reserve not met")
    assert (no_bids.sale_status, no_bids.sale_note) == ("unsold", "no bids")


def test_lots_that_leave_the_site_are_settled_and_summarised(session, client, web):
    sources = build_sources(client)
    refresh.refresh_all(session, sources, only=["toppigeon"])
    # The AfrikaPro auction ends: its category disappears from the site.
    web.add("https://toppigeon.co.za/product-category/active-auctions",
            httpx.Response(200, headers={"content-type": "text/html"},
                           text=open(__file__.replace("test_auction_results.py",
                                                      "fixtures/toppigeon/active-auctions.html")).read()
                           .replace("afrikapro-2026-auction-2", "gone")))
    web.add("https://toppigeon.co.za/product-category/active-auctions/gone",
            httpx.Response(200, headers={"content-type": "text/html"},
                           text="<html><body class='woocommerce'><ul class='products'></ul></body></html>"))
    refresh.refresh_all(session, sources, only=["toppigeon"])
    rows = auction_results.auctions(session)
    afp = next(a for a in rows if a["auction_name"] == "AfrikaPro 2026 Auction 2")
    # Lot 1 R3,500 reserve met (sold), lot 2 R6,000 reserve NOT met, lot 3 no bids.
    assert (afp["closed"], afp["sold"], afp["unsold"], afp["turnover"], afp["buyers"]) == (3, 1, 2, 3500, 1)
    d = auction_results.auction_detail(session, "toppigeon", afp["auction_id"])
    by_no = {r["lot_no"]: r for r in d["lots"]}
    assert by_no[1]["sale_status"] == "sold" and by_no[1]["winner"] == "GeForce RTX"
    assert by_no[1]["yours"] == "won" and d["yours"]["won"] == 1  # your Top Pigeon username
    assert by_no[2]["sale_note"] == "reserve not met"
    assert by_no[3]["sale_note"] == "no bids"


def test_final_read_after_close(session, client, web):
    sources = build_sources(client)
    refresh.refresh_all(session, sources, only=["toppigeon"])
    lot = session.scalar(select(Lot).where(Lot.lot_key.like("%7829%")))
    ended = now_utc() - timedelta(minutes=3)  # closed 3 minutes ago, still listed as live
    local = ended.astimezone(__import__("olr_scout.config", fromlist=["TZ"]).TZ)
    html = open(__file__.replace("test_auction_results.py", "fixtures/toppigeon/lot-1.html")).read()
    web.add("https://toppigeon.co.za/product/lot-1-za-2026-port-7829",
            httpx.Response(200, headers={"content-type": "text/html"},
                           text=html.replace("October 28, 2026 14:02", local.strftime("%B %d, %Y %H:%M"))))
    lot.ends_at = ended
    session.commit()
    web.calls.clear()
    refresh.hot_refresh(session, sources)
    session.refresh(lot)
    assert "https://toppigeon.co.za/product/lot-1-za-2026-port-7829/" in web.calls
    assert lot.status == "closed" and lot.final_read and lot.sale_status == "sold" and lot.final_price == 3500
    web.calls.clear()
    refresh.hot_refresh(session, sources)
    assert "https://toppigeon.co.za/product/lot-1-za-2026-port-7829/" not in web.calls  # read once only


def test_extended_lot_is_not_closed_by_the_final_read(session, client, web):
    """Anti-sniping: the lot page now shows a later end time — keep it live."""
    sources = build_sources(client)
    refresh.refresh_all(session, sources, only=["toppigeon"])
    lot = session.scalar(select(Lot).where(Lot.lot_key.like("%7829%")))
    later = (now_utc() + timedelta(minutes=4)).astimezone(__import__("olr_scout.config", fromlist=["TZ"]).TZ)
    html = open(__file__.replace("test_auction_results.py", "fixtures/toppigeon/lot-1.html")).read()
    web.add("https://toppigeon.co.za/product/lot-1-za-2026-port-7829",
            httpx.Response(200, headers={"content-type": "text/html"},
                           text=html.replace("October 28, 2026 14:02", later.strftime("%B %d, %Y %H:%M"))))
    lot.ends_at = now_utc() - timedelta(minutes=2)
    session.commit()
    refresh.hot_refresh(session, sources)
    session.refresh(lot)
    assert lot.status == "live" and not lot.final_read and lot.sale_status is None


def test_top_bid_on_unsold_lot_is_not_a_win(session):
    lot = make_lot(session, 1, auction_id="a1", status="closed", current_bid=900, bid_count=2, reserve_met=False,
                   leading_bidder="GeForce RTX")
    refresh.settle(lot)
    session.flush()
    d = auction_results.auction_detail(session, "test", "a1")
    assert d["lots"][0]["yours"] == "bid" and d["yours"] == {"won": 0, "bid": 1}
    assert auction_results.auctions(session)[0]["buyers"] == 0
