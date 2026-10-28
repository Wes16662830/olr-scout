"""Run auction adapters, store lots, keep price history, rescore, raise alerts.

Each adapter runs on its own: one failing or blocked source never fails the
refresh of the others.
"""

from __future__ import annotations

import dataclasses
import logging
import traceback
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import alerts
from .config import settings
from .models import Auction as AuctionRow
from .models import BidHistory, Lot as LotRow, LotPriceHistory, RawPayload, SourceHealth
from .scoring import engine, seller
from .sources.base import Auction, AuctionSource, Lot
from .util.http import SourceBlocked
from .util.timeutil import as_aware, now_utc

log = logging.getLogger(__name__)

LOT_FIELDS = [f.name for f in dataclasses.fields(Lot) if f.name not in ("bids", "detail_loaded", "extra", "fetched_at")]


def _health(s: Session, key: str) -> SourceHealth:
    h = s.get(SourceHealth, key)
    if h is None:
        h = SourceHealth(source_id=key, status="unknown", detail={})
        s.add(h)
    return h


def _save_raw(s: Session, source: str, captured: list[tuple[str, int, str]], limit: int = 3) -> None:
    for url, status, text in captured[:limit]:
        s.add(RawPayload(source=source, url=url[:800], status=status, body=text[:500_000]))


def upsert_lot(s: Session, lot: Lot) -> LotRow:
    row = s.scalar(select(LotRow).where(LotRow.source == lot.source, LotRow.auction_id == lot.auction_id,
                                        LotRow.lot_key == lot.lot_key))
    is_new = row is None
    if is_new:
        row = LotRow(source=lot.source, auction_id=lot.auction_id, lot_key=lot.lot_key, url=lot.url, extra={})
        s.add(row)
    prev_bid, prev_count, prev_end = (row.current_bid, row.bid_count, row.ends_at) if not is_new else (None, None, None)
    for f in LOT_FIELDS:
        val = getattr(lot, f)
        # Don't wipe detail fields with None when only the listing was read.
        if val is None and not lot.detail_loaded and f in ("ends_at", "description", "pedigree_text", "pedigree_url", "reserve_met", "bid_count"):
            continue
        setattr(row, f, val)
    row.fetched_at = lot.fetched_at
    if lot.detail_loaded:
        row.detail_fetched_at = lot.fetched_at
    row.extra = {**(row.extra or {}), **(lot.extra or {})}
    s.flush()
    if lot.bids:
        known = {(b.bidder, b.amount, as_aware(b.at)) for b in row.bids}
        for b in lot.bids:
            key = (b.get("bidder"), b.get("amount"), b.get("at"))
            if key not in known:
                row.bids.append(BidHistory(bidder=b.get("bidder"), amount=b.get("amount"), at=b.get("at")))
                known.add(key)
        top = max(lot.bids, key=lambda b: (b.get("amount") or 0))
        row.leading_bidder = top.get("bidder")
    if is_new or prev_bid != row.current_bid or prev_count != row.bid_count or as_aware(prev_end) != as_aware(row.ends_at):
        s.add(LotPriceHistory(lot_id=row.id, current_bid=row.current_bid, bid_count=row.bid_count, ends_at=row.ends_at))
    return row


def upsert_auction(s: Session, a: Auction, results_link: bool) -> None:
    row = s.scalar(select(AuctionRow).where(AuctionRow.source == a.source, AuctionRow.external_id == a.auction_id))
    if row is None:
        row = AuctionRow(source=a.source, external_id=a.auction_id, name=a.name)
        s.add(row)
    row.name, row.seller, row.url, row.status = a.name, a.seller, a.url, a.status
    row.olr_tag, row.olr_year, row.lot_count, row.first_close = a.olr_tag, a.olr_year, a.lot_count, a.first_close
    row.results_link = results_link
    row.updated_at = now_utc()


def run_source(s: Session, src: AuctionSource) -> dict:
    h = _health(s, src.key)
    h.last_run = now_utc()
    captured: list[tuple[str, int, str]] = []
    src.client.on_response = lambda url, status, text: captured.append((url, status, text)) if len(captured) < 5 else None
    report = {"source": src.key, "auctions": 0, "lots": 0, "errors": []}
    seen_ids: set[int] = set()
    try:
        auctions = src.fetch_active()
    except SourceBlocked as exc:
        h.status, h.message = "degraded", f"blocked: {exc}"
        _save_raw(s, src.key, captured)
        s.flush()
        report["errors"].append(str(exc))
        return report
    except Exception as exc:
        h.status, h.message = "error", f"{type(exc).__name__}: {exc}"
        h.detail = {"trace": traceback.format_exc()[-3000:]}
        _save_raw(s, src.key, captured)
        s.flush()
        report["errors"].append(str(exc))
        return report
    report["auctions"] = len(auctions)
    blocked = False
    for a in auctions:
        try:
            lots = src.fetch_lots(a)
        except SourceBlocked as exc:
            blocked = True
            report["errors"].append(f"{a.name}: {exc}")
            break
        except Exception as exc:
            log.exception("%s %s", src.key, a.name)
            report["errors"].append(f"{a.name}: {type(exc).__name__}: {exc}")
            continue
        upsert_auction(s, a, results_link=bool(a.olr_tag))
        for lot in lots:
            row = upsert_lot(s, lot)
            seen_ids.add(row.id)
        report["lots"] += len(lots)
    # Lots of this source that are no longer listed have closed (only trust a clean run).
    if not report["errors"]:
        for row in s.scalars(select(LotRow).where(LotRow.source == src.key, LotRow.status.in_(("live", "upcoming")))):
            if row.id not in seen_ids:
                row.status = "closed"
    h.lot_count = report["lots"]
    if blocked:
        h.status, h.message = "degraded", "; ".join(report["errors"])[:2000]
    elif report["errors"] and report["lots"] == 0:
        h.status, h.message = "error", "; ".join(report["errors"])[:2000]
    elif report["errors"]:
        h.status, h.message = "degraded", "; ".join(report["errors"])[:2000]
    elif report["lots"] == 0:
        h.status, h.message = "empty", "no live lots" + ("" if src.verified else " / not yet verified")
    else:
        h.status, h.message = "ok", "" if src.verified else "parsing not yet verified against live pages"
        h.last_success = now_utc()
    extra = {}
    for attr in ("lot_endpoint", "discovery_log", "platform"):
        if hasattr(src, attr):
            extra[attr] = getattr(src, attr)
    h.detail = {"auctions": report["auctions"], "errors": report["errors"][:20], **extra}
    if report["errors"]:
        _save_raw(s, src.key, captured)
    s.flush()
    return report


def refresh_all(s: Session, sources: dict[str, AuctionSource], only: list[str] | None = None) -> list[dict]:
    reports = []
    for key, src in sources.items():
        if only and key not in only:
            continue
        try:
            reports.append(run_source(s, src))
            s.commit()
        except Exception as exc:  # never let one source break the rest
            s.rollback()
            log.exception("source %s", key)
            reports.append({"source": key, "errors": [str(exc)]})
    seller.recompute(s)
    engine.score_all(s)
    alerts.evaluate(s)
    purge_raw(s)
    s.commit()
    return reports


def row_to_lot(row: LotRow) -> Lot:
    kw = {f: getattr(row, f) for f in LOT_FIELDS}
    lot = Lot(**kw)
    lot.extra = dict(row.extra or {})
    return lot


def hot_refresh(s: Session, sources: dict[str, AuctionSource]) -> int:
    """Re-read only lots closing within the hot window (default 10 min)."""
    now = now_utc()
    soon = now + timedelta(minutes=settings.hot_window_minutes)
    rows = s.scalars(select(LotRow).where(LotRow.status == "live", LotRow.ends_at.is_not(None),
                                          LotRow.ends_at <= soon, LotRow.ends_at >= now - timedelta(minutes=2))).all()
    done = []
    for row in rows:
        src = sources.get(row.source)
        if src is None:
            continue
        h = s.get(SourceHealth, row.source)
        if h and h.status in ("degraded", "error") and "blocked" in (h.message or ""):
            continue
        try:
            fresh = src.refresh_lot(row_to_lot(row))
        except SourceBlocked as exc:
            _health(s, row.source).status = "degraded"
            _health(s, row.source).message = f"blocked: {exc}"
            continue
        except Exception:
            log.exception("hot refresh %s", row.url)
            continue
        if fresh is not None:
            fresh.fetched_at = now_utc()
            done.append(upsert_lot(s, fresh))
    if done:
        engine.score_all(s, done)
        alerts.evaluate(s)
    s.commit()
    return len(done)


def purge_raw(s: Session) -> None:
    cutoff = now_utc() - timedelta(days=settings.raw_payload_days)
    s.execute(delete(RawPayload).where(RawPayload.at < cutoff))
