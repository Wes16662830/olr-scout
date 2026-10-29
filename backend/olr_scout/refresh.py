"""Run auction adapters, store lots, keep price history, rescore, raise alerts.

Each adapter runs on its own: one failing or blocked source never fails the
refresh of the others.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import traceback
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import alerts
from .config import settings
from .models import Auction as AuctionRow
from .models import BidHistory, Lot as LotRow, LotPriceHistory, RawPayload, SourceHealth
from .scoring import engine, seller
from .sources.base import DETAIL_VERSION, Auction, AuctionSource, Lot
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
        if val is None and not lot.detail_loaded:
            continue  # listing-only read: keep what the lot page told us last time
        setattr(row, f, val)
    row.fetched_at = lot.fetched_at
    if lot.detail_loaded:
        row.detail_fetched_at = lot.fetched_at
        lot.extra = {**(lot.extra or {}), "detail_version": DETAIL_VERSION}
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
    settle(row)
    return row


CLOSED = ("closed", "sold", "unsold", "ended")


def settle(row: LotRow) -> None:
    """Record the outcome of a closed lot from what was last seen. Called again after
    the final read, so later information wins."""
    if row.status not in CLOSED:
        return
    if row.closed_at is None:
        ends = as_aware(row.ends_at)
        row.closed_at = ends if ends and ends <= now_utc() else now_utc()
    row.final_price = row.current_bid
    row.winner = row.leading_bidder
    if row.status == "unsold":
        row.sale_status, row.sale_note = "unsold", "not sold"
    elif row.current_bid is None or row.bid_count == 0:
        row.sale_status, row.sale_note = "unsold", "no bids"
    elif row.reserve_met is False:
        row.sale_status, row.sale_note = "unsold", "reserve not met"
    else:
        row.sale_status = "sold"
        row.sale_note = None if row.reserve_met else "reserve not shown"


def upsert_auction(s: Session, a: Auction, results_link: bool) -> None:
    row = s.scalar(select(AuctionRow).where(AuctionRow.source == a.source, AuctionRow.external_id == a.auction_id))
    if row is None:
        row = AuctionRow(source=a.source, external_id=a.auction_id, name=a.name)
        s.add(row)
    row.name, row.seller, row.url, row.status = a.name, a.seller, a.url, a.status
    row.olr_tag, row.olr_year, row.lot_count, row.first_close = a.olr_tag, a.olr_year, a.lot_count, a.first_close
    row.results_link = results_link
    row.updated_at = now_utc()


_capture = threading.local()


def _dispatch_capture(url: str, status: int, text: str) -> None:
    """PoliteClient callback: keep the first few raw responses of the source
    being read on this thread (sources are read in parallel)."""
    buf = getattr(_capture, "buf", None)
    if buf is not None and len(buf) < 5:
        buf.append((url, status, text))


def _known_lots(s: Session, source: str) -> dict[str, dict]:
    return {
        r.lot_key: {"bid": r.current_bid, "start": r.starting_bid, "detail_at": r.detail_fetched_at, "ends_at": r.ends_at,
                    "detail_version": (r.extra or {}).get("detail_version")}
        for r in s.scalars(select(LotRow).where(LotRow.source == source))
    }


def _fetch_worker(src: AuctionSource, out: "queue.Queue") -> None:
    """Network only (no database): read one source and post results to ``out``."""
    _capture.buf = []
    src.progress.clear()
    src.tick(running=True, phase="listing auctions", started=now_utc().isoformat())
    try:
        try:
            auctions = src.fetch_active()
        except Exception as exc:
            out.put(("source_error", src.key, exc, isinstance(exc, SourceBlocked), traceback.format_exc()))
            return
        src.tick(phase="reading lots", auctions=len(auctions), auctions_done=0)
        for i, a in enumerate(auctions, 1):
            src.tick(auction=a.name, done=0, total=a.lot_count)
            try:
                lots = src.fetch_lots(a)
            except SourceBlocked as exc:
                out.put(("auction_error", src.key, a, exc, True))
                break
            except Exception as exc:
                log.exception("%s %s", src.key, a.name)
                out.put(("auction_error", src.key, a, exc, False))
                continue
            out.put(("auction_done", src.key, a, lots))
            src.tick(auctions_done=i)
        out.put(("source_done", src.key, len(auctions)))
    finally:
        out.put(("captured", src.key, list(_capture.buf)))
        src.tick(running=False, phase="done", finished=now_utc().isoformat())
        _capture.buf = None


def _finish_health(s: Session, src: AuctionSource, report: dict, seen_ids: set[int], blocked: bool) -> None:
    h = _health(s, src.key)
    # Lots of this source that are no longer listed have closed (only trust a clean run).
    if not report["errors"] and not report.get("source_failed"):
        for row in s.scalars(select(LotRow).where(LotRow.source == src.key, LotRow.status.in_(("live", "upcoming")))):
            if row.id not in seen_ids:
                row.status = "closed"
                settle(row)
    h.lot_count = report["lots"]
    if report.get("source_failed"):
        pass  # status already set from the exception
    elif blocked:
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
    h.detail = {**(h.detail or {}), "auctions": report["auctions"], "errors": report["errors"][:20],
                "pages_skipped_unchanged": report.get("skipped", 0), **extra}


def run_sources(s: Session, sources: list[AuctionSource]) -> list[dict]:
    """Read every source in parallel (each host still gets at most 1 request/s);
    store each auction in the database as soon as it arrives."""
    out: queue.Queue = queue.Queue()
    reports: dict[str, dict] = {}
    seen: dict[str, set[int]] = {}
    blocked: dict[str, bool] = {}
    for src in sources:
        src.client.on_response = _dispatch_capture
        src.known = _known_lots(s, src.key)
        h = _health(s, src.key)
        h.last_run = now_utc()
        reports[src.key] = {"source": src.key, "auctions": 0, "lots": 0, "errors": [], "skipped": 0}
        seen[src.key], blocked[src.key] = set(), False
    s.commit()
    threads = [threading.Thread(target=_fetch_worker, args=(src, out), daemon=True, name=f"fetch-{src.key}")
               for src in sources]
    for t in threads:
        t.start()
    by_key = {src.key: src for src in sources}
    finished = 0
    while finished < len(sources):
        try:
            item = out.get(timeout=1.0)
        except queue.Empty:
            if not any(t.is_alive() for t in threads) and out.empty():
                break
            continue
        kind, key = item[0], item[1]
        rep = reports[key]
        try:
            if kind == "auction_done":
                a, lots = item[2], item[3]
                upsert_auction(s, a, results_link=bool(a.olr_tag))
                for lot in lots:
                    seen[key].add(upsert_lot(s, lot).id)
                    rep["skipped"] += int(not lot.detail_loaded)
                rep["lots"] += len(lots)
                rep["auctions"] += 1
                _health(s, key).lot_count = rep["lots"]
            elif kind == "auction_error":
                a, exc, is_block = item[2], item[3], item[4]
                rep["errors"].append(f"{a.name}: {type(exc).__name__}: {exc}" if not is_block else f"{a.name}: blocked: {exc}")
                blocked[key] = blocked[key] or is_block
            elif kind == "source_error":
                exc, is_block, trace = item[2], item[3], item[4]
                h = _health(s, key)
                h.status = "degraded" if is_block else "error"
                h.message = (f"blocked: {exc}" if is_block else f"{type(exc).__name__}: {exc}")[:2000]
                h.detail = {"trace": trace[-3000:]}
                rep["errors"].append(str(exc))
                rep["source_failed"] = True
            elif kind == "source_done":
                pass
            elif kind == "captured":
                if rep["errors"]:
                    _save_raw(s, key, item[2])
                _finish_health(s, by_key[key], rep, seen[key], blocked[key])
                finished += 1
            s.commit()
        except Exception:
            s.rollback()
            log.exception("storing results from %s", key)
    for t in threads:
        t.join(timeout=5)
    return [{k: v for k, v in r.items() if k != "source_failed"} for r in reports.values()]


def refresh_all(s: Session, sources: dict[str, AuctionSource], only: list[str] | None = None) -> list[dict]:
    chosen = [src for key, src in sources.items() if not only or key in only]
    reports = run_sources(s, chosen)
    seller.recompute(s)
    engine.score_all(s)
    from .mybids import auto_watch

    auto_watch(s)
    alerts.evaluate(s)
    purge_raw(s)
    s.commit()
    return reports


def row_to_lot(row: LotRow) -> Lot:
    kw = {f: getattr(row, f) for f in LOT_FIELDS}
    lot = Lot(**kw)
    lot.extra = dict(row.extra or {})
    return lot


FINAL_READ_DELAY = timedelta(minutes=1)
FINAL_READ_WINDOW = timedelta(hours=12)
FINAL_READS_PER_RUN = 10


def hot_refresh(s: Session, sources: dict[str, AuctionSource]) -> int:
    """Re-read lots closing within the hot window (default 10 min), and read each
    lot's page once more shortly after it closes to confirm the final price.

    All pages are fetched before anything is written, so the database is never
    locked while waiting on a site."""
    now = now_utc()
    soon = now + timedelta(minutes=settings.hot_window_minutes)
    hot = s.scalars(select(LotRow).where(LotRow.status == "live", LotRow.ends_at.is_not(None),
                                         LotRow.ends_at <= soon, LotRow.ends_at >= now - timedelta(minutes=2))).all()
    final = s.scalars(select(LotRow).where(
        LotRow.ends_at.is_not(None), LotRow.ends_at <= now - FINAL_READ_DELAY,
        LotRow.ends_at >= now - FINAL_READ_WINDOW, LotRow.final_read.is_not(True),
        LotRow.status.in_(("live",) + CLOSED)).order_by(LotRow.ends_at).limit(FINAL_READS_PER_RUN)).all()
    jobs = [(row, row_to_lot(row), False) for row in hot] + [(row, row_to_lot(row), True) for row in final]
    s.commit()  # release before network calls

    fetched: list[tuple[LotRow, object, bool, str | None]] = []
    blocked: dict[str, str] = {}
    for row, lot, is_final in jobs:
        src = sources.get(row.source)
        if src is None or row.source in blocked:
            continue
        h = s.get(SourceHealth, row.source)
        if h and h.status in ("degraded", "error") and "blocked" in (h.message or ""):
            continue
        try:
            fetched.append((row, src.refresh_lot(lot), is_final, None))
        except SourceBlocked as exc:
            blocked[row.source] = str(exc)
        except Exception as exc:
            log.warning("re-reading %s: %s", row.url, exc)
            fetched.append((row, None, is_final, f"{type(exc).__name__}"))

    done = []
    for source, msg in blocked.items():
        _health(s, source).status = "degraded"
        _health(s, source).message = f"blocked: {msg}"
    for row, fresh, is_final, error in fetched:
        if fresh is not None:
            fresh.fetched_at = now_utc()
            ends = as_aware(fresh.ends_at)
            if is_final and fresh.status == "live" and ends is not None and ends <= now_utc():
                fresh.status = "closed"  # page still says live but its time has passed
            row = upsert_lot(s, fresh)
            done.append(row)
        if is_final:
            still_running = row.status == "live" and as_aware(row.ends_at) and as_aware(row.ends_at) > now_utc()
            if not still_running:  # anti-sniping may have extended it: read again later
                if row.status == "live":
                    row.status = "closed"
                settle(row)
                row.final_read = True
                if error:
                    row.extra = {**(row.extra or {}), "final_read_note": f"lot page not readable after closing ({error})"}
    if done:
        engine.score_all(s, done)
        from .mybids import auto_watch

        auto_watch(s)
        alerts.evaluate(s)
    s.commit()
    return len(done)


def purge_raw(s: Session) -> None:
    cutoff = now_utc() - timedelta(days=settings.raw_payload_days)
    s.execute(delete(RawPayload).where(RawPayload.at < cutoff))
