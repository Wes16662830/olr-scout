from datetime import timedelta

from sqlalchemy import select

from olr_scout import alerts, refresh
from olr_scout.models import Alert, Lot, LotPriceHistory, Watch
from olr_scout.scoring import preferences
from olr_scout.sources.registry import build_sources
from olr_scout.util.timeutil import now_utc

from .helpers import make_lot


def test_alert_rules(session):
    p = preferences.load(session)
    p.update(max_bid=5000, near_max_buffer=500)
    preferences.save(session, p)
    near = make_lot(session, 1, current_bid=4700, ends_at=now_utc() + timedelta(minutes=9))
    above = make_lot(session, 2, current_bid=5200, ends_at=now_utc() + timedelta(hours=3))
    for l in (near, above):
        session.add(Watch(lot_id=l.id, closes_in=[30, 10]))
    session.flush()
    new = alerts.evaluate(session)
    kinds = sorted((a.lot_id, a.kind) for a in new)
    assert (near.id, "near_max") in kinds and (near.id, "closing") in kinds and (above.id, "above_max") in kinds
    assert "R4,700" in next(a.message for a in new if a.kind == "near_max")
    # Same state again → no duplicates.
    assert alerts.evaluate(session) == []
    assert session.scalars(select(Alert)).all()


def test_price_history_and_closed_lots(session, client, web):
    sources = build_sources(client)
    refresh.refresh_all(session, sources, only=["toppigeon"])
    lot = session.scalar(select(Lot).where(Lot.lot_key.like("%7829%")))
    n_hist = len(session.scalars(select(LotPriceHistory).where(LotPriceHistory.lot_id == lot.id)).all())
    assert n_hist == 1
    refresh.refresh_all(session, sources, only=["toppigeon"])  # unchanged → no new history row
    assert len(session.scalars(select(LotPriceHistory).where(LotPriceHistory.lot_id == lot.id)).all()) == 1
    # The Dinokeng category disappears → its lot is marked closed after a clean run.
    web.add("https://toppigeon.co.za/product-category/active-auctions/dinokeng-upcoming",
            __import__("httpx").Response(200, text="<html><body class='woocommerce'><ul class='products'></ul></body></html>",
                                         headers={"content-type": "text/html"}))
    refresh.refresh_all(session, sources, only=["toppigeon"])
    dino = session.scalar(select(Lot).where(Lot.lot_key.like("%dinokeng-lot-1%")))
    assert dino.status == "closed"


def test_hot_refresh_only_touches_lots_closing_soon(session, client, web):
    sources = build_sources(client)
    refresh.refresh_all(session, sources, only=["toppigeon"])
    lots = session.scalars(select(Lot).where(Lot.source == "toppigeon")).all()
    for l in lots:
        l.ends_at = now_utc() + timedelta(hours=5)
    soon = next(l for l in lots if "7829" in l.lot_key)
    soon.ends_at = now_utc() + timedelta(minutes=5)
    session.commit()
    web.calls.clear()
    n = refresh.hot_refresh(session, sources)
    assert n == 1
    assert web.calls == ["https://toppigeon.co.za/product/lot-1-za-2026-port-7829/"]
