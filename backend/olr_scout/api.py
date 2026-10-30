"""HTTP API (FastAPI). Every route except /api/login requires the session cookie."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import alerts as alerts_mod
from . import auth, builder, export
from .config import settings
from .db import get_session, init_db, session_scope
from .models import (
    Alert,
    AncestorClaim,
    Bird,
    FamilyStat,
    Flight,
    LoftInventory,
    Lot,
    LotPriceHistory,
    Olr,
    Plan,
    PushSubscription,
    Season,
    SourceHealth,
    Watch,
)
from .results.ingest import race_history, seed_registry
from .rings import normalise
from .scoring import engine, preferences
from .scoring.tier_a import family_key, persistence, FamilyAgg
from .serialize import iso, lot_card
from .util.timeutil import now_utc

api = APIRouter(prefix="/api")
protected = APIRouter(prefix="/api", dependencies=[Depends(auth.require_user)])


# ------------------------------------------------------------------ auth
@api.post("/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    if not settings.password:
        raise HTTPException(503, "Set OLR_SCOUT_PASSWORD on the server first")
    if not auth.check_password(str(body.get("password", ""))):
        raise HTTPException(401, "wrong password")
    response.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return {"ok": True}


@api.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@protected.get("/me")
def me():
    return {"user": "wes", "tz": "Africa/Johannesburg", "currency": "ZAR"}


# ------------------------------------------------------------------ lots
@protected.get("/suggestions")
def get_suggestions(s: Session = Depends(get_session), include_over_max: bool = False):
    prefs = preferences.load(s)
    items = engine.suggestions(s, prefs, include_over_max)
    banners = [{"source": h.source_id, "status": h.status, "message": h.message}
               for h in s.scalars(select(SourceHealth)) if h.status in ("degraded", "error")]
    tiers = {t: n for t, n in s.execute(select(Lot.tier, func.count()).where(Lot.status.in_(("live", "upcoming")))
                                        .group_by(Lot.tier)).all()}
    bh = s.get(SourceHealth, "benzing")
    diagnosis = {
        "result_birds": s.scalar(select(func.count()).select_from(Bird)) or 0,
        "seasons_ingested": s.scalar(select(func.count()).select_from(Season).where(Season.ingested_at.is_not(None))) or 0,
        "results_status": bh.status if bh else "never run",
        "results_message": bh.message if bh else "",
        "tiers": tiers,
        "lots_with_ring": s.scalar(select(func.count()).select_from(Lot).where(
            Lot.status.in_(("live", "upcoming")), Lot.ring_norm.is_not(None))) or 0,
        "sample_lot_rings": [r for (r,) in s.execute(select(Lot.ring_raw).where(
            Lot.status == "live", Lot.ring_raw.is_not(None)).limit(5))],
        "sample_result_rings": [r for (r,) in s.execute(select(Bird.ring_raw).limit(5))],
        # Live lots whose ring appears in the stored results (same ring, any formatting).
        "lots_in_results": s.scalar(select(func.count(func.distinct(Lot.id))).select_from(Lot).join(
            Bird, Bird.ring_norm == Lot.ring_norm).where(Lot.status.in_(("live", "upcoming")))) or 0,
        "result_seasons": [f"{o} {y}" for o, y in s.execute(
            select(Olr.name, Season.year).join(Season, Season.olr_id == Olr.id)
            .where(Season.ingested_at.is_not(None)).order_by(Season.year.desc()))],
    }
    return {"items": [lot_card(x["lot"], prefs, {"value_rank": x.get("value_rank")}) for x in items],
            "banners": banners, "max_bid": prefs["max_bid"], "rank_by": prefs.get("rank_by", "racing"),
            "diagnosis": diagnosis,
            "auctions": engine.auction_overview(s, prefs)}


@protected.get("/lots")
def list_lots(s: Session = Depends(get_session), status: str = "live", source: str | None = None,
              tier: str | None = None, q: str | None = None, limit: int = 500):
    prefs = preferences.load(s)
    stmt = select(Lot)
    if status != "all":
        stmt = stmt.where(Lot.status == status)
    if source:
        stmt = stmt.where(Lot.source == source)
    if tier:
        stmt = stmt.where(Lot.tier == tier)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Lot.title.ilike(like), Lot.ring_raw.ilike(like), Lot.seller.ilike(like),
                              Lot.ring_norm.ilike(f"%{normalise(q)}%")))
    stmt = stmt.order_by(Lot.ends_at.is_(None), Lot.ends_at).limit(limit)
    return [lot_card(l, prefs) for l in s.scalars(stmt)]


@protected.get("/search")
def search_lots(q: str = "", s: Session = Depends(get_session)):
    """Lots by lot number, ring or breeder — live lots first, then closed ones (newest first)."""
    from .search import WHY, search

    prefs = preferences.load(s)
    return [lot_card(l, prefs, {"found_by": [WHY[w][1] for w in why]}) for l, why in search(s, q)]


@protected.get("/closing")
def closing_soon(s: Session = Depends(get_session), hours: int = 24):
    prefs = preferences.load(s)
    now = now_utc()
    lots = s.scalars(select(Lot).where(Lot.status == "live", Lot.ends_at.is_not(None), Lot.ends_at >= now,
                                       Lot.ends_at <= now + timedelta(hours=hours)).order_by(Lot.ends_at)).all()
    groups: dict[str, list] = {}
    for l in lots:
        key = iso(l.ends_at.replace(second=0, microsecond=0))
        groups.setdefault(key, []).append(lot_card(l, prefs))
    return [{"ends_at": k, "lots": v} for k, v in groups.items()]


@protected.get("/lots/{lot_id}")
def lot_detail(lot_id: int, s: Session = Depends(get_session)):
    lot = s.get(Lot, lot_id)
    if lot is None:
        raise HTTPException(404)
    prefs = preferences.load(s)
    card = lot_card(lot, prefs)
    card.update({"description": lot.description, "pedigree_text": lot.pedigree_text,
                 "pedigree_url": lot.pedigree_url, "sire": lot.sire, "dam": lot.dam, "extra": lot.extra,
                 "score_detail": lot.score_detail})
    races = []
    family = None
    siblings = []
    if lot.bird_id:
        rec = race_history(s, lot.bird.ring_norm)
        races = [r.__dict__ for r in rec.races]
        bird = lot.bird
        if bird.family_key:
            fam_rows = s.scalars(select(FamilyStat).where(FamilyStat.family_key == bird.family_key)).all()
            family = {"key": bird.family_key, "team": bird.team,
                      "rows": [{"season_id": f.season_id, "entries": f.entries, "aces": f.aces,
                                "finalists": f.finalists, "ace_rate": f.ace_rate_shrunk} for f in fam_rows]}
            siblings = [{"ring": b.ring_raw, "long_score": b.long_score, "is_ace": b.is_ace,
                         "year": b.season.year, "olr": b.season.olr.name}
                        for b in s.scalars(select(Bird).where(Bird.family_key == bird.family_key, Bird.id != bird.id)
                                           .order_by(Bird.long_score).limit(30))]
    card["races"] = races
    card["family"] = family
    card["family_birds"] = siblings
    card["price_history"] = [{"at": iso(p.at), "current_bid": p.current_bid, "bid_count": p.bid_count}
                             for p in s.scalars(select(LotPriceHistory).where(LotPriceHistory.lot_id == lot.id)
                                                .order_by(LotPriceHistory.at))]
    card["bid_history"] = [{"bidder": b.bidder, "amount": b.amount, "at": iso(b.at)} for b in lot.bids]
    card["claims"] = [claim_json(c, s) for c in s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id))]
    card["watched"] = s.scalar(select(Watch).where(Watch.lot_id == lot.id)) is not None
    return card


def claim_json(c: AncestorClaim, s: Session) -> dict:
    b = s.get(Bird, c.bird_id) if c.bird_id else None
    return {"id": c.id, "relation": c.relation, "ring": c.ring_raw, "name": c.name, "text": c.claim_text,
            "origin": c.origin, "claims_ace": c.claims_ace, "status": c.status, "confirmed": c.confirmed_by_user,
            "bird": {"id": b.id, "ring": b.ring_raw, "long_score": b.long_score, "is_ace": b.is_ace,
                     "olr": b.season.olr.name, "year": b.season.year} if b else None}


@protected.post("/lots/{lot_id}/override")
def override_match(lot_id: int, body: dict = Body(...), s: Session = Depends(get_session)):
    """{"ring": "BE-25-6087189"} or {"bird_id": 12} or {"none": true} or {"clear": true}."""
    lot = s.get(Lot, lot_id)
    if lot is None:
        raise HTTPException(404)
    if body.get("clear"):
        lot.override_bird_id, lot.override_none = None, False
    elif body.get("none"):
        lot.override_bird_id, lot.override_none = None, True
    else:
        bird_id = body.get("bird_id")
        if not bird_id and body.get("ring"):
            b = s.scalar(select(Bird).where(Bird.ring_norm == normalise(body["ring"])).order_by(Bird.season_id.desc()))
            if b is None:
                raise HTTPException(404, "that ring is not in the stored OLR results")
            bird_id = b.id
        if not bird_id or s.get(Bird, int(bird_id)) is None:
            raise HTTPException(400, "give a ring or bird_id that exists in the results")
        lot.override_bird_id, lot.override_none = int(bird_id), False
    engine.score_all(s, [lot])
    s.commit()
    return lot_detail(lot_id, s)


@protected.get("/birds/search")
def bird_search(q: str, s: Session = Depends(get_session)):
    n = normalise(q)
    rows = s.scalars(select(Bird).where(Bird.ring_norm.contains(n)).limit(20)).all() if n else []
    return [{"id": b.id, "ring": b.ring_raw, "team": b.team, "olr": b.season.olr.name, "year": b.season.year,
             "long_score": b.long_score, "is_ace": b.is_ace} for b in rows]


# ------------------------------------------------------------------ watchlist & alerts
@protected.post("/lots/{lot_id}/watch")
def watch(lot_id: int, body: dict = Body(default={}), s: Session = Depends(get_session)):
    if s.get(Lot, lot_id) is None:
        raise HTTPException(404)
    w = s.scalar(select(Watch).where(Watch.lot_id == lot_id)) or Watch(lot_id=lot_id)
    if "near_max_within" in body:
        w.near_max_within = body["near_max_within"]
    if "closes_in" in body:
        w.closes_in = [int(x) for x in body["closes_in"]]
    if "above_max" in body:
        w.above_max = bool(body["above_max"])
    s.add(w)
    s.commit()
    return {"ok": True, "id": w.id}


@protected.delete("/lots/{lot_id}/watch")
def unwatch(lot_id: int, s: Session = Depends(get_session)):
    from .mybids import is_leading

    lot = s.get(Lot, lot_id)
    if lot is not None and is_leading(s, lot, preferences.load(s)):
        raise HTTPException(409, "You're leading on this lot, so it stays on your watchlist until you're "
                                 "outbid or the auction closes.")
    w = s.scalar(select(Watch).where(Watch.lot_id == lot_id))
    if w:
        s.delete(w)
    if lot is not None:  # don't add it back automatically just because you bid on it
        lot.extra = {**(lot.extra or {}), "auto_watch_dismissed": True}
    s.commit()
    return {"ok": True}


@protected.post("/lots/{lot_id}/mybid")
def mark_my_bid(lot_id: int, body: dict = Body(default={}), s: Session = Depends(get_session)):
    """For sites that show no bidder names: {"on": true, "amount": 3500} marks your bid."""
    lot = s.get(Lot, lot_id)
    if lot is None:
        raise HTTPException(404)
    extra = dict(lot.extra or {})
    if body.get("on", True):
        extra["my_bid"] = True
        if body.get("amount"):
            extra["my_bid_amount"] = int(body["amount"])
        extra.pop("auto_watch_dismissed", None)
    else:
        extra.pop("my_bid", None)
        extra.pop("my_bid_amount", None)
    lot.extra = extra
    s.flush()
    from .mybids import auto_watch

    auto_watch(s)
    s.commit()
    return lot_detail(lot_id, s)


@protected.get("/watchlist")
def watchlist(s: Session = Depends(get_session)):
    """Live lots you lead first, then ones you were outbid on, then the rest by closing time;
    closed lots last (latest first)."""
    prefs = preferences.load(s)
    rows = [{"watch": {"id": w.id, "near_max_within": w.near_max_within, "closes_in": w.closes_in,
                       "above_max": w.above_max, "auto": bool(w.auto)}, "lot": lot_card(w.lot, prefs)}
            for w in s.scalars(select(Watch)) if w.lot]
    live = [r for r in rows if r["lot"].get("status") in ("live", "upcoming")]
    done = [r for r in rows if r not in live]
    rank = {"leading": 0, "outbid": 1}
    live.sort(key=lambda r: (rank.get((r["lot"].get("my_bid") or {}).get("status"), 2), r["lot"].get("ends_at") or "9999"))
    done.sort(key=lambda r: r["lot"].get("ends_at") or "", reverse=True)
    return live + done


@protected.get("/alerts")
def list_alerts(s: Session = Depends(get_session), unread: bool = False):
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(100)
    if unread:
        stmt = stmt.where(Alert.read.is_(False))
    return [{"id": a.id, "lot_id": a.lot_id, "kind": a.kind, "message": a.message, "at": iso(a.created_at),
             "read": a.read} for a in s.scalars(stmt)]


@protected.post("/alerts/read")
def read_alerts(s: Session = Depends(get_session)):
    for a in s.scalars(select(Alert).where(Alert.read.is_(False))):
        a.read = True
    s.commit()
    return {"ok": True}


@protected.get("/push/key")
def push_key():
    return {"enabled": alerts_mod.push_enabled(), "public_key": settings.vapid_public_key or None}


@protected.post("/push/subscribe")
def push_subscribe(body: dict = Body(...), s: Session = Depends(get_session)):
    ep = body.get("endpoint")
    if not ep:
        raise HTTPException(400, "endpoint required")
    sub = s.scalar(select(PushSubscription).where(PushSubscription.endpoint == ep)) or PushSubscription(endpoint=ep)
    sub.keys = body.get("keys") or {}
    s.add(sub)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ families
@protected.get("/families")
def families(s: Session = Depends(get_session), olr: str | None = None, min_entries: int = 1, limit: int = 300):
    rows = s.scalars(select(FamilyStat).where(FamilyStat.season_id.is_(None), FamilyStat.entries >= min_entries)
                     .order_by(FamilyStat.ace_rate_shrunk.desc()).limit(limit)).all()
    seasons = {x.id: x for x in s.scalars(select(Season))}
    per = s.scalars(select(FamilyStat).where(FamilyStat.season_id.is_not(None))).all()
    by_fam: dict[str, list] = {}
    by_season: dict[int, dict[str, FamilyAgg]] = {}
    for f in per:
        season = seasons.get(f.season_id)
        if olr and season and season.olr.name != olr:
            continue
        by_fam.setdefault(f.family_key, []).append({"year": season.year if season else None,
                                                    "olr": season.olr.name if season else None,
                                                    "entries": f.entries, "aces": f.aces,
                                                    "ace_rate": round(f.ace_rate_shrunk, 4)})
        if season:
            agg = FamilyAgg(f.family_key, f.entries, f.aces, f.finalists)
            by_season.setdefault(season.year, {})[f.family_key] = agg
    out = []
    for f in rows:
        if olr and f.family_key not in by_fam:
            continue
        out.append({"family": f.family_key, "entries": f.entries, "aces": f.aces, "finalists": f.finalists,
                    "ace_rate": round(f.ace_rate_shrunk, 4), "small_sample": f.entries < 20,
                    "seasons": sorted(by_fam.get(f.family_key, []), key=lambda x: x["year"] or 0)})
    return {"families": out, "persistence": persistence(by_season), "leaders": leaders(s),
            "top_parents": top_parents(s)}


def top_parents(s: Session, limit: int = 30) -> list[dict]:
    """Sires/dams with at least 2 offspring found in OLR results (from auction listings)."""
    from .scoring.progeny import ProgenyIndex

    idx = ProgenyIndex(s)
    rows = []
    for parent, kids in idx.offspring_of.items():
        rec = idx.record(kids)
        if rec is None or rec.n < 2:
            continue
        own = idx.best.get(parent)
        rows.append({"ring": own.ring_raw if own else parent, "name": own.name if own else None,
                     "raced": f"{own.season.olr.name} {own.season.year}" if own else None,
                     "offspring_named": len(kids), "offspring_raced": rec.n, "aces": rec.aces,
                     "ace_rate": round(rec.ace_rate, 4), "mean_long": round(rec.mean_long, 4),
                     "strength": round(rec.strength() * 100, 1), "best": rec.birds[:3]})
    return sorted(rows, key=lambda r: -r["strength"])[:limit]


def leaders(s: Session) -> dict:
    """Breeders: sellers whose sold birds later raced (aces first). Buyers: winning
    bidders on closed lots, exactly as the sites display them (no de-anonymising)."""
    from .models import SellerStat

    breeders = [{"seller": x.display, "sold_raced": x.sold_raced, "aces": x.aces, "ace_rate": round(x.ace_rate_shrunk, 4)}
                for x in s.scalars(select(SellerStat).order_by(SellerStat.aces.desc(), SellerStat.ace_rate_shrunk.desc()).limit(15))]
    rows = s.execute(select(Lot.leading_bidder, func.count(), func.sum(Lot.current_bid))
                     .where(Lot.status.in_(("closed", "sold")), Lot.leading_bidder.is_not(None))
                     .group_by(Lot.leading_bidder).order_by(func.count().desc()).limit(15)).all()
    buyers = [{"bidder": b, "lots": n, "spent": total} for b, n, total in rows]
    return {"breeders": breeders, "buyers": buyers}


@protected.get("/families/{key}")
def family_detail(key: str, s: Session = Depends(get_session)):
    return builder.family_records(s, [key])[0]


@protected.get("/olrs")
def list_olrs(s: Session = Depends(get_session)):
    return [{"id": o.id, "name": o.name, "loft_id": o.loft_id, "aliases": o.aliases, "enabled": o.enabled,
             "auto_discovered": o.auto_discovered,
             "seasons": [{"id": x.id, "year": x.year, "registered": x.registered, "teams": x.teams,
                          "ingested_at": iso(x.ingested_at),
                          "flights": len(x.flights)} for x in sorted(o.seasons, key=lambda x: -x.year)]}
            for o in s.scalars(select(Olr).order_by(Olr.enabled.desc(), Olr.name))]


@protected.put("/olrs")
def save_olr(body: dict = Body(...), s: Session = Depends(get_session)):
    """Add or edit a registry entry: {id?, name, loft_id, aliases, enabled, seasons: {year: id}}.

    A loft id or season id held by an entry the app added automatically from the loft
    list is merged into this one; one held by another real entry is refused with the
    reason (it used to fail silently with a database error)."""
    notes: list[str] = []
    olr = s.get(Olr, int(body["id"])) if body.get("id") else None
    if olr is None:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Give the OLR a name")
        olr = s.scalar(select(Olr).where(Olr.name == name))
        if olr is None:
            olr = Olr(name=name, aliases=[name.lower()], enabled=True)
            s.add(olr)
            s.flush()
            notes.append(f"{name} added")
    if "name" in body and str(body["name"]).strip() and str(body["name"]).strip() != olr.name:
        clash = s.scalar(select(Olr).where(Olr.name == str(body["name"]).strip(), Olr.id != olr.id))
        if clash:
            raise HTTPException(409, f"Another OLR is already called {clash.name}")
        olr.name = str(body["name"]).strip()

    if "loft_id" in body:
        raw = body["loft_id"]
        try:
            loft_id = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(400, f"Loft id must be a number (got {raw!r})")
        if loft_id is not None:
            holder = s.scalar(select(Olr).where(Olr.loft_id == loft_id, Olr.id != olr.id))
            if holder is not None and not holder.auto_discovered:
                raise HTTPException(409, f"Loft {loft_id} already belongs to {holder.name}. Clear it there first.")
            if holder is not None:
                # Auto-added from the results site's loft list: fold it into this entry.
                for season in list(holder.seasons):
                    olr.seasons.append(season)  # moves it (a cascade would delete it with the holder)
                olr.aliases = sorted(set((olr.aliases or []) + (holder.aliases or [])))
                notes.append(f"merged the automatically added entry “{holder.name}”")
                holder.loft_id = None
                s.flush()
                s.delete(holder)
                s.flush()
        olr.loft_id = loft_id
        notes.append(f"loft id {loft_id}" if loft_id else "loft id cleared")

    for k in ("aliases", "enabled"):
        if k in body:
            setattr(olr, k, body[k])
    s.flush()
    for year, sid in (body.get("seasons") or {}).items():
        try:
            sid, year = int(sid), int(year)
        except (TypeError, ValueError):
            raise HTTPException(400, "Season year and id must be numbers")
        existing = s.get(Season, sid)
        if existing is None:
            s.add(Season(id=sid, olr_id=olr.id, year=year))
            notes.append(f"season {year} added")
        elif existing.olr_id != olr.id:
            other = s.get(Olr, existing.olr_id)
            if other is not None and not other.auto_discovered:
                raise HTTPException(409, f"Season {sid} already belongs to {other.name}")
            olr.seasons.append(existing)
            notes.append(f"season {year} moved here")
    s.commit()
    if "enabled" in body or "loft_id" in body:
        _rescore_in_background()  # lots tied to this OLR may change tier
    return {"ok": True, "id": olr.id, "enabled": olr.enabled,
            "message": f"{olr.name} saved" + (f" — {', '.join(notes)}" if notes else "") +
                       (". Click Ingest OLR results now on Sources to download its results." if "loft_id" in body else "")}


# ------------------------------------------------------------------ builder & inventory
@protected.post("/builder/plan")
def make_plan(goal: dict = Body(...), s: Session = Depends(get_session)):
    out = builder.build_plan(s, goal)
    s.commit()
    return out


@protected.get("/builder/plans")
def plans(s: Session = Depends(get_session)):
    return [{"id": p.id, "created_at": iso(p.created_at), "goal": p.goal, "items": p.items, "total_max": p.total_max,
             "notes": p.notes} for p in s.scalars(select(Plan).order_by(Plan.created_at.desc()).limit(20))]


def inv_json(i: LoftInventory) -> dict:
    return {"id": i.id, "ring": i.ring, "sex": i.sex, "family": i.family, "name": i.name, "sire": i.sire,
            "dam": i.dam, "grandparents": i.grandparents, "notes": i.notes}


@protected.get("/inventory")
def inventory(s: Session = Depends(get_session)):
    return [inv_json(i) for i in s.scalars(select(LoftInventory).order_by(LoftInventory.id))]


@protected.post("/inventory")
def add_inventory(body: dict = Body(...), s: Session = Depends(get_session)):
    if not body.get("ring"):
        raise HTTPException(400, "ring required")
    i = LoftInventory(ring=body["ring"], ring_norm=normalise(body["ring"]))
    for k in ("sex", "family", "name", "sire", "dam", "grandparents", "notes"):
        if k in body:
            setattr(i, k, body[k])
    s.add(i)
    s.commit()
    return inv_json(i)


@protected.put("/inventory/{inv_id}")
def edit_inventory(inv_id: int, body: dict = Body(...), s: Session = Depends(get_session)):
    i = s.get(LoftInventory, inv_id)
    if i is None:
        raise HTTPException(404)
    for k in ("ring", "sex", "family", "name", "sire", "dam", "grandparents", "notes"):
        if k in body:
            setattr(i, k, body[k])
    i.ring_norm = normalise(i.ring)
    s.commit()
    return inv_json(i)


@protected.delete("/inventory/{inv_id}")
def delete_inventory(inv_id: int, s: Session = Depends(get_session)):
    i = s.get(LoftInventory, inv_id)
    if i:
        s.delete(i)
        s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ pedigree review
@protected.get("/pedigree/review")
def pedigree_review(s: Session = Depends(get_session), status: str | None = None):
    stmt = select(AncestorClaim).join(Lot, AncestorClaim.lot_id == Lot.id).where(Lot.status.in_(("live", "upcoming")))
    if status:
        stmt = stmt.where(AncestorClaim.status == status)
    by_lot: dict[int, dict] = {}
    for c in s.scalars(stmt.order_by(AncestorClaim.lot_id)):
        lot = s.get(Lot, c.lot_id)
        entry = by_lot.setdefault(c.lot_id, {"lot": {"id": lot.id, "title": lot.title, "ring": lot.ring_raw,
                                                     "auction": lot.auction_name, "lot_no": lot.lot_no,
                                                     "pedigree_url": lot.pedigree_url, "tier": lot.tier},
                                             "claims": []})
        entry["claims"].append(claim_json(c, s))
    pending = s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")), Lot.pedigree_url.is_not(None),
                                          Lot.tier.in_(("C", "D"))).limit(100)).all()
    return {"lots": list(by_lot.values()),
            "unread_pedigrees": [{"id": l.id, "title": l.title, "pedigree_url": l.pedigree_url} for l in pending
                                 if l.id not in by_lot]}


@protected.post("/lots/{lot_id}/claims")
def add_claim(lot_id: int, body: dict = Body(...), s: Session = Depends(get_session)):
    lot = s.get(Lot, lot_id)
    if lot is None:
        raise HTTPException(404)
    c = AncestorClaim(lot_id=lot_id, relation=body.get("relation", "ancestor"), ring_raw=body.get("ring"),
                      ring_norm=normalise(body.get("ring")), name=body.get("name"),
                      claim_text=body.get("text"), origin="manual", claims_ace=bool(body.get("claims_ace")),
                      confirmed_by_user=True)
    s.add(c)
    s.flush()
    engine.score_all(s, [lot])
    s.commit()
    return claim_json(c, s)


@protected.put("/claims/{claim_id}")
def edit_claim(claim_id: int, body: dict = Body(...), s: Session = Depends(get_session)):
    """Correct an OCR/parse result. {ring, relation, name, reject: bool, confirm: bool}."""
    c = s.get(AncestorClaim, claim_id)
    if c is None:
        raise HTTPException(404)
    if "ring" in body:
        c.ring_raw, c.ring_norm = body["ring"], normalise(body["ring"])
    for k in ("relation", "name"):
        if k in body:
            setattr(c, k, body[k])
    if body.get("reject"):
        c.status = "rejected"
    elif c.status == "rejected" and body.get("reject") is False:
        c.status = "claimed"
    c.confirmed_by_user = True
    s.flush()
    engine.score_all(s, [s.get(Lot, c.lot_id)])
    s.commit()
    return claim_json(c, s)


@protected.get("/pedigree/status")
def pedigree_status(s: Session = Depends(get_session)):
    from .pedigree_reader import status

    return status(s)


@protected.post("/pedigree/read-now")
def pedigree_read_now():
    from .scheduler import job_read_pedigrees

    return _background(job_read_pedigrees)


@protected.post("/lots/{lot_id}/ocr")
def ocr_lot(lot_id: int, s: Session = Depends(get_session)):
    from . import ocr
    from .scheduler import client

    lot = s.get(Lot, lot_id)
    if lot is None or not lot.pedigree_url:
        raise HTTPException(404, "no pedigree link on this lot")
    try:
        text, origin = ocr.text_from_url(client, lot.pedigree_url)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    from .pedigree_reader import store

    store(s, lot, text, origin, None)
    s.flush()
    engine.score_all(s, [lot])
    s.commit()
    return {"text": text, "claims": [claim_json(c, s) for c in
                                     s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id))]}


# ------------------------------------------------------------------ sources
@protected.get("/sources")
def sources_status(s: Session = Depends(get_session)):
    from . import scheduler
    from .sources.registry import ADAPTERS

    out = []
    for cls in ADAPTERS:
        h = s.get(SourceHealth, cls.key)
        live = s.scalar(select(func.count()).select_from(Lot).where(Lot.source == cls.key, Lot.status == "live"))
        out.append({"key": cls.key, "name": cls.name, "base_url": cls.base_url, "verified": cls.verified,
                    "status": h.status if h else "never run", "last_run": iso(h.last_run) if h else None,
                    "last_success": iso(h.last_success) if h else None, "lot_count": live,
                    "message": h.message if h else "", "detail": h.detail if h else {},
                    "progress": dict(scheduler.sources[cls.key].progress) if cls.key in scheduler.sources else {}})
    h = s.get(SourceHealth, "benzing")
    out.append({"key": "benzing", "name": "Benzing Live / oneloftrace (results, unofficial)",
                "base_url": settings.benzing_base_url, "verified": False,
                "status": h.status if h else "never run", "last_run": iso(h.last_run) if h else None,
                "last_success": iso(h.last_success) if h else None,
                "lot_count": s.scalar(select(func.count()).select_from(Bird)),
                "message": h.message if h else "", "detail": h.detail if h else {},
                "progress": {**ingest_progress(), "running": scheduler.results_busy()}})
    return out


def ingest_progress() -> dict:
    from .results.ingest import PROGRESS

    return dict(PROGRESS)


def _background(fn, *args, busy=None, busy_message="a job is already running") -> JSONResponse:
    """Run a site-touching job off the request thread (1 req/s makes them slow)."""
    import threading

    if busy is not None and busy():
        return JSONResponse({"started": False, "message": busy_message}, status_code=409)
    threading.Thread(target=fn, args=args, daemon=True).start()
    return JSONResponse({"started": True, "message": "started — watch this screen for the result"}, status_code=202)


@protected.post("/sources/refresh")
def trigger_refresh(body: dict = Body(default={})):
    from .scheduler import is_busy, job_full_refresh

    return _background(job_full_refresh, body.get("only"), busy=is_busy,
                       busy_message="a lot refresh is already running — progress is shown below")


@protected.post("/results/ingest")
def trigger_ingest(body: dict = Body(default={})):
    from .scheduler import job_nightly_results, results_busy

    return _background(job_nightly_results, body.get("olrs"), busy=results_busy,
                       busy_message="the OLR results download is already running — progress is shown in the Benzing row")


# ------------------------------------------------------------------ settings
@protected.get("/settings")
def get_settings(s: Session = Depends(get_session)):
    return preferences.load(s)


@protected.put("/settings")
def put_settings(body: dict = Body(...), s: Session = Depends(get_session)):
    try:
        prefs = preferences.save(s, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    s.commit()  # saved now; rescoring follows in the background
    _rescore_in_background()
    return prefs


def _rescore_in_background() -> None:
    import threading

    from .db import SessionLocal

    def run():
        with SessionLocal() as bg:
            try:
                engine.score_all(bg)
                bg.commit()
            except Exception:
                bg.rollback()
                import logging

                logging.getLogger(__name__).exception("rescoring after settings change")

    import os

    if os.environ.get("OLR_SCOUT_SYNC_RESCORE") == "1":  # tests: one shared in-memory connection
        run()
        return
    threading.Thread(target=run, daemon=True, name="rescore").start()


@protected.get("/scores/check")
def scores_check(s: Session = Depends(get_session)):
    from .scoring.progeny import evidence_check

    return evidence_check(s)


# ------------------------------------------------------------------ auction results
@protected.get("/results/auctions")
def results_auctions(s: Session = Depends(get_session)):
    from . import auction_results

    return auction_results.auctions(s)


@protected.get("/results/auction")
def results_auction(source: str, auction_id: str, s: Session = Depends(get_session)):
    from . import auction_results

    return auction_results.auction_detail(s, source, auction_id)


@protected.get("/results/auction.csv")
def results_auction_csv(source: str, auction_id: str, s: Session = Depends(get_session)):
    import csv
    import io

    from . import auction_results

    d = auction_results.auction_detail(s, source, auction_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Lot", "Ring", "Bird", "Breeder", "Seller", "Tier", "Score", "Ace", "Final price", "Status", "Note",
                "Winner (as shown)", "Bids", "Closed", "Link"])
    for r in d["lots"]:
        w.writerow([r["lot_no"], r["ring"], r["bird_name"], r["breeder"], r["seller"], r["tier"], r["score"],
                    "yes" if r["is_ace"] else "", r["final_price"], r["sale_status"], r["sale_note"], r["winner"],
                    r["bids"], r["closed_at"], r["url"]])
    name = "".join(c if c.isalnum() else "-" for c in (d["auction_name"] or "auction"))[:60]
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=results-{name}.csv"})


# ------------------------------------------------------------------ export
def _selected(s: Session, auctions: str | None) -> list[dict]:
    """Suggestions, optionally limited to "source:auction_id" keys (comma-separated)."""
    items = engine.suggestions(s)
    if not auctions:
        return items
    keys = {k for k in auctions.split(",") if k}
    return [x for x in items if f"{x['lot'].source}:{x['lot'].auction_id}" in keys]


@protected.get("/export.csv")
def export_csv(s: Session = Depends(get_session), auctions: str | None = None):
    return PlainTextResponse(export.to_csv(_selected(s, auctions)), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=olr-scout-suggestions.csv"})


@protected.get("/export.xlsx")
def export_xlsx(s: Session = Depends(get_session), auctions: str | None = None):
    return Response(export.to_xlsx(_selected(s, auctions)),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=olr-scout-suggestions.xlsx"})


@protected.get("/export/whatsapp")
def export_whatsapp(s: Session = Depends(get_session), limit: int = Query(25, le=100), auctions: str | None = None):
    return PlainTextResponse(export.to_whatsapp(_selected(s, auctions), limit))


# ------------------------------------------------------------------ app
def _open_browser_when_ready(port: int) -> None:
    """Open the default browser as soon as the server accepts connections."""
    import socket
    import threading
    import time
    import webbrowser

    def wait_and_open():
        for _ in range(120):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=wait_and_open, daemon=True, name="open-browser").start()


def create_app(start_scheduler: bool | None = None) -> FastAPI:
    from contextlib import asynccontextmanager

    run = settings.enable_scheduler if start_scheduler is None else start_scheduler

    @asynccontextmanager
    async def lifespan(_app):
        sched = None
        if run:
            from . import scheduler

            sched = scheduler.start()
        if settings.open_browser:
            _open_browser_when_ready(settings.port)
        yield
        if sched:
            sched.shutdown(wait=False)

    app = FastAPI(title="OLR Scout", version="0.1.0", lifespan=lifespan)
    init_db()
    with session_scope() as s:
        seed_registry(s)
    app.include_router(api)
    app.include_router(protected)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app
