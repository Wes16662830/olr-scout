"""Watchlist alert rules and web push."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import Alert, PushSubscription, Watch
from .scoring import preferences
from .util.money import format_zar
from .util.timeutil import as_aware, now_utc

log = logging.getLogger(__name__)


def _lot_label(lot) -> str:
    bits = [lot.auction_name or lot.source]
    if lot.lot_no:
        bits.append(f"Lot {lot.lot_no}")
    if lot.ring_raw:
        bits.append(lot.ring_raw)
    return " · ".join(bits)


def _add(s: Session, lot, kind: str, dedupe: str, message: str) -> Alert | None:
    if s.scalar(select(Alert).where(Alert.lot_id == lot.id, Alert.kind == kind, Alert.dedupe == dedupe)):
        return None
    a = Alert(lot_id=lot.id, kind=kind, dedupe=dedupe, message=message)
    try:
        with s.begin_nested():
            s.add(a)
    except IntegrityError:
        return None
    return a


def evaluate(s: Session) -> list[Alert]:
    prefs = preferences.load(s)
    now = now_utc()
    new: list[Alert] = []
    for w in s.scalars(select(Watch)):
        lot = w.lot
        if lot is None or lot.status not in ("live", "upcoming"):
            continue
        limit = preferences.lot_max(lot, lot.family_tags or [], prefs)
        price = lot.current_bid if lot.current_bid is not None else lot.starting_bid
        label = _lot_label(lot)
        from .mybids import my_bid

        mine = my_bid(s, lot, prefs)
        if mine and mine["status"] == "outbid" and mine["top"]:
            who = f" by {mine['top_bidder']}" if mine.get("top_bidder") else ""
            yours = f" (your bid {format_zar(mine['your_max'])})" if mine.get("your_max") else ""
            a = _add(s, lot, "outbid", str(mine["top"]),
                     f"Outbid on {label}: now {format_zar(mine['top'])}{who}{yours} — your max {format_zar(limit)}")
            if a:
                new.append(a)
        ends = as_aware(lot.ends_at)
        if ends:
            mins = (ends - now).total_seconds() / 60
            for threshold in sorted(w.closes_in or [], reverse=True):
                if 0 < mins <= threshold:
                    a = _add(s, lot, "closing", f"{threshold}", f"{label} closes in {int(mins) + 1} min — now {format_zar(price)} (your max {format_zar(limit)})")
                    if a:
                        new.append(a)
        if price is not None:
            buffer = w.near_max_within if w.near_max_within is not None else int(prefs.get("near_max_buffer", 0))
            if w.above_max and price > limit:
                a = _add(s, lot, "above_max", "above", f"{label} is now {format_zar(price)}, above your max {format_zar(limit)}")
                if a:
                    new.append(a)
            elif limit - buffer <= price <= limit:
                a = _add(s, lot, "near_max", str(price), f"{label} is at {format_zar(price)}, within {format_zar(limit - price)} of your max")
                if a:
                    new.append(a)
    s.flush()
    if new:
        push(s, new)
    return new


def push_enabled() -> bool:
    if not (settings.vapid_private_key and settings.vapid_public_key):
        return False
    try:
        import pywebpush  # noqa: F401
    except Exception:
        return False
    return True


def push(s: Session, items: list[Alert]) -> int:
    if not push_enabled():
        return 0
    from pywebpush import WebPushException, webpush

    sent = 0
    subs = list(s.scalars(select(PushSubscription)))
    for a in items:
        payload = json.dumps({"title": "OLR Scout", "body": a.message, "lot_id": a.lot_id, "kind": a.kind})
        for sub in subs:
            try:
                webpush({"endpoint": sub.endpoint, "keys": sub.keys}, payload,
                        vapid_private_key=settings.vapid_private_key, vapid_claims={"sub": settings.vapid_subject})
                sent += 1
            except WebPushException as exc:
                log.warning("push failed: %s", exc)
                if exc.response is not None and exc.response.status_code in (404, 410):
                    s.delete(sub)
        a.pushed = True
    return sent
