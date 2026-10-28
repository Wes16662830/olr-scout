"""Store OLR results and recompute per-bird and per-family metrics."""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Bird, BirdResult, FamilyStat, Flight, Olr, Season, SourceHealth
from ..rings import normalise
from ..scoring.tier_a import FlightIn, aggregate_families, family_key, season_metrics, shrunk_rate
from ..util.timeutil import now_utc
from .base import BirdRecord, HealthError, RaceLine, ResultsSource

log = logging.getLogger(__name__)

#: Live progress of the running results ingest, shown on the Sources screen.
PROGRESS: dict = {}

# Editable in Settings → OLR registry. Seasons: year → Benzing season id.
SEED_REGISTRY = [
    {"name": "AfrikaPro", "loft_id": 147, "aliases": ["afrikapro", "afrika pro"],
     "seasons": {2026: 2873, 2025: 2722, 2024: 2141, 2023: 1160, 2022: 1049}},
    {"name": "Marlbank OLR Winter", "loft_id": 251, "aliases": ["marlbank"], "seasons": {}},
    {"name": "Dinokeng", "loft_id": None, "aliases": ["dinokeng"], "seasons": {}},
    {"name": "Karoo Million", "loft_id": None, "aliases": ["karoo million"], "seasons": {}},
]


class NoRacesYet(Exception):
    """A season with only training tosses (or nothing) so far: skipped, not an error."""


def reset_empty_seasons(s: Session) -> int:
    """Seasons marked ingested that hold no birds were not really ingested (an
    earlier version accepted 0 races). Clear the mark so they are fetched again."""
    n = 0
    for season in s.scalars(select(Season).where(Season.ingested_at.is_not(None))):
        if s.scalar(select(Bird.id).where(Bird.season_id == season.id).limit(1)) is None:
            season.ingested_at = None
            n += 1
    s.flush()
    return n


def seed_registry(s: Session) -> None:
    for entry in SEED_REGISTRY:
        olr = s.scalar(select(Olr).where(Olr.name == entry["name"]))
        if olr is None:
            olr = Olr(name=entry["name"], loft_id=entry["loft_id"], aliases=entry["aliases"])
            s.add(olr)
            s.flush()
        for year, sid in entry["seasons"].items():
            if s.get(Season, sid) is None:
                s.add(Season(id=sid, olr_id=olr.id, year=year))
    s.flush()
    reset_empty_seasons(s)


def discover_olrs(s: Session, src: ResultsSource) -> int:
    """Add every loft from the Benzing loft list that is not in the registry yet."""
    added = 0
    known = {o.loft_id for o in s.scalars(select(Olr)) if o.loft_id}
    names = {o.name.lower(): o for o in s.scalars(select(Olr))}
    for loft in src.list_lofts():
        if loft.id in known:
            continue
        existing = names.get(loft.name.lower())
        if existing is None:
            for o in names.values():
                if not o.loft_id and any(a in loft.name.lower() for a in (o.aliases or [])):
                    existing = o
                    break
        if existing is not None and not existing.loft_id:
            existing.loft_id = loft.id
        else:
            s.add(Olr(name=loft.name, loft_id=loft.id, aliases=[loft.name.lower()], auto_discovered=True, enabled=False))
            added += 1
    s.flush()
    return added


def refresh_seasons(s: Session, src: ResultsSource, olr: Olr) -> list[Season]:
    if not olr.loft_id:
        return list(olr.seasons)
    try:
        infos = src.list_seasons(olr.loft_id)
    except Exception as exc:
        log.warning("seasons for %s: %s (keeping registry seasons)", olr.name, exc)
        return list(olr.seasons)
    for info in infos:
        if s.get(Season, info.id) is None:
            s.add(Season(id=info.id, olr_id=olr.id, year=info.year))
    s.flush()
    s.refresh(olr)
    return list(olr.seasons)


def ingest_season(s: Session, src: ResultsSource, season: Season) -> dict:
    """Download every race of one season and recompute bird + family metrics."""
    flights = src.list_flights(season.id)
    PROGRESS.update(season=season.year, season_id=season.id, phase="reading teams", race=0,
                    races=sum(1 for f in flights if not f.is_training))
    report = {"season": season.id, "flights": 0, "rows": 0, "mismatches": []}
    team_of: dict[str, str] = {}
    raw_of: dict[str, str] = {}
    info_of: dict[str, dict] = {}  # name, colour, sex, team country from result rows
    registered: set[str] = set()
    try:
        teams = src.season_teams(season.id)
    except Exception as exc:  # teams are a bonus; results are what matter
        log.warning("teams for season %s failed: %s", season.id, exc)
        teams = []
    for t in teams:
        for r in t.rings:
            n = normalise(r)
            registered.add(n)
            team_of[n] = t.team
            raw_of.setdefault(n, r)
    if teams:
        season.teams = len(teams)
    reg_counts = [t.registered for t in teams if t.registered is not None]
    registered_count = sum(reg_counts) if reg_counts else None
    if not any(not f.is_training for f in flights):
        raise NoRacesYet(f"{season.year}: no races flown yet")
    results: dict[int, dict[str, int]] = {}
    flight_rows: dict[int, Flight] = {}
    for f in flights:
        fl = s.get(Flight, f.id) or Flight(id=f.id, season_id=season.id, name=f.name)
        fl.name, fl.distance_km, fl.flown_at = f.name, f.distance_km, f.flown_at
        fl.is_training, fl.is_final, fl.race_no, fl.basketed = f.is_training, f.is_final, f.race_no, f.basketed
        s.add(fl)
        flight_rows[f.id] = fl
        if f.is_training:
            continue
        PROGRESS.update(phase="reading race results", race=report["flights"] + 1, race_name=f.name)
        fr = src.flight_results(f.id)
        report["flights"] += 1
        report["rows"] += len(fr.rows)
        if not fr.complete:
            report["mismatches"].append(fr.note)
        fl.total_rows, fl.ingested_rows = fr.total, len(fr.rows)
        positions = [r.position for r in fr.rows if r.position]
        fl.arrived = f.arrived or fr.total or (max(positions) if positions else len(fr.rows))
        per: dict[str, int] = {}
        for r in fr.rows:
            n = normalise(r.ring_raw)
            if not n:
                continue
            raw_of.setdefault(n, r.ring_raw)
            if r.team and n not in team_of:
                team_of[n] = r.team
            info = info_of.setdefault(n, {})
            for k, v in (("name", r.name), ("colour", r.colour), ("sex", r.sex), ("team_country", r.team_country)):
                if v and not info.get(k):
                    info[k] = str(v).strip()
            if r.position is not None:
                per[n] = min(per.get(n, r.position), r.position)
        results[f.id] = per
    s.flush()
    PROGRESS.update(phase="scoring birds")
    season.registered = max(len(registered | {r for rows in results.values() for r in rows}), registered_count or 0)
    if not any(results.values()):
        raise HealthError(f"season {season.year}: races found but no result rows could be read "
                          "(ring field names changed?) — run diagnose-results")
    metrics = season_metrics(
        [FlightIn(f.id, f.distance_km, flight_rows[f.id].arrived, f.is_training, f.is_final, f.name) for f in flights],
        results,
        registered,
        registered_count=registered_count,
    )
    # Replace this season's birds wholesale (results are immutable once a race is final).
    existing = {b.ring_norm: b for b in s.scalars(select(Bird).where(Bird.season_id == season.id))}
    for ring, m in metrics.items():
        b = existing.get(ring) or Bird(season_id=season.id, ring_norm=ring, ring_raw=raw_of.get(ring, ring))
        b.team = team_of.get(ring)
        info = info_of.get(ring, {})
        b.name = info.get("name") or b.name
        b.colour = info.get("colour") or b.colour
        b.team_country = info.get("team_country") or b.team_country
        sx = (info.get("sex") or "").lower()
        b.sex = {"c": "cock", "m": "cock", "cock": "cock", "h": "hen", "f": "hen", "hen": "hen"}.get(sx, b.sex)
        b.family_key = family_key(b.team)
        b.is_ace, b.long_score, b.all_score, b.final_position = m.is_ace, m.long_score, m.all_score, m.final_position
        s.add(b)
        s.flush()
        s.execute(delete(BirdResult).where(BirdResult.bird_id == b.id))
        for fid, pos in m.positions.items():
            if pos is not None:
                s.add(BirdResult(bird_id=b.id, flight_id=fid, position=pos))
    season.ingested_at = now_utc()
    s.flush()
    recompute_family_stats(s, season.olr_id)
    return report


def recompute_family_stats(s: Session, olr_id: int | None = None) -> None:
    """Per family: one row per season, plus an all-seasons row (season_id None)."""
    q = select(Bird, Season).join(Season, Bird.season_id == Season.id)
    rows = s.execute(q).all()
    by_season: dict[int, list] = defaultdict(list)
    olr_of: dict[int, int] = {}
    for b, season in rows:
        by_season[season.id].append((b.family_key, _metric_view(b)))
        olr_of[season.id] = season.olr_id
    s.execute(delete(FamilyStat))
    overall: dict[str, list] = defaultdict(list)
    for sid, items in by_season.items():
        for key, agg in aggregate_families(items).items():
            s.add(FamilyStat(family_key=key, season_id=sid, olr_id=olr_of[sid], entries=agg.entries, aces=agg.aces,
                             finalists=agg.finalists, ace_rate_shrunk=agg.rate, best_long=agg.best_long))
            overall[key].append(agg)
    for key, aggs in overall.items():
        entries = sum(a.entries for a in aggs)
        aces = sum(a.aces for a in aggs)
        best = [a.best_long for a in aggs if a.best_long is not None]
        s.add(FamilyStat(family_key=key, season_id=None, entries=entries, aces=aces,
                         finalists=sum(a.finalists for a in aggs), ace_rate_shrunk=shrunk_rate(aces, entries),
                         best_long=min(best) if best else None))
    s.flush()


class _metric_view:
    def __init__(self, b: Bird):
        self.is_ace = b.is_ace
        self.final_position = b.final_position
        self.long_score = b.long_score if b.long_score is not None else 1.0


def race_history(s: Session, ring_norm: str) -> BirdRecord:
    """``ResultsSource.get_race_history`` backed by the ingested database."""
    birds = s.scalars(select(Bird).where(Bird.ring_norm == ring_norm)).all()
    if not birds:
        return BirdRecord(ring_norm, False)
    rec = BirdRecord(ring_norm, True, team=birds[0].team)
    for b in birds:
        season = b.season
        flights = s.scalars(select(Flight).where(Flight.season_id == b.season_id, Flight.is_training.is_(False))
                            .order_by(Flight.flown_at, Flight.id)).all()
        pos = {r.flight_id: r.position for r in b.results}
        for f in flights:
            p = pos.get(f.id)
            arrived = f.arrived
            rec.races.append(RaceLine(
                olr=season.olr.name, season_year=season.year, flight=f.name, distance_km=f.distance_km,
                position=p, arrived=arrived, registered=season.registered,
                percentile=min(1.0, p / arrived) if p and arrived else 1.0,
            ))
    return rec


def _rescore_lots(s: Session) -> None:
    """Match and score live lots against everything ingested so far."""
    from ..scoring import engine, seller

    try:
        seller.recompute(s)
        engine.score_all(s)
        s.commit()
    except Exception:
        s.rollback()
        log.exception("rescoring lots after a season")


def ingest_all(s: Session, src: ResultsSource, olr_names: list[str] | None = None, only_missing: bool = False,
               rescore_each_season: bool = True) -> dict:
    """Nightly / on-demand ingest. Records health on the 'benzing' source row."""
    health = s.get(SourceHealth, "benzing") or SourceHealth(source_id="benzing")
    s.add(health)
    health.last_run = now_utc()
    report = {"seasons": [], "errors": [], "skipped": []}
    PROGRESS.clear()
    PROGRESS.update(running=True, phase="checking the results site", started=now_utc().isoformat(), seasons_done=0)
    try:
        src.health_check()
    except Exception as exc:
        health.status, health.message = "error", f"health check failed: {exc}"
        s.flush()
        PROGRESS.update(running=False, phase="failed", error=str(exc)[:300])
        raise
    # Fill in loft ids for registry OLRs that lack one (e.g. Dinokeng) from the loft list.
    PROGRESS.update(phase="matching OLR names to the results site")
    try:
        discover_olrs(s, src)
        s.commit()
    except Exception as exc:
        log.warning("loft discovery failed: %s", exc)
    olrs = s.scalars(select(Olr).where(Olr.enabled.is_(True))).all()
    if olr_names:
        olrs = [o for o in olrs if o.name in olr_names]
    not_found = [o.name for o in olrs if not o.loft_id]
    for name in not_found:
        report["errors"].append(f"{name}: not found in the results site's loft list — set its loft id in Settings")
    for olr in olrs:
        PROGRESS.update(olr=olr.name, phase="finding seasons")
        # Newest season first: the one live auctions most likely refer to.
        seasons = refresh_seasons(s, src, olr)
        s.commit()  # keep newly found seasons even if one of them is skipped or fails below
        for season in sorted(seasons, key=lambda x: -x.year):
            if only_missing and season.ingested_at:
                continue
            try:
                report["seasons"].append(ingest_season(s, src, season))
                health.status, health.last_success = "ok", now_utc()
                s.commit()  # each finished season is usable straight away
                PROGRESS["seasons_done"] = PROGRESS.get("seasons_done", 0) + 1
                if rescore_each_season:
                    PROGRESS.update(phase="matching lots to the new results")
                    _rescore_lots(s)
            except NoRacesYet as exc:
                s.rollback()
                health = s.get(SourceHealth, "benzing") or health
                report["skipped"].append(f"{olr.name} {exc}")
            except Exception as exc:
                s.rollback()
                health = s.get(SourceHealth, "benzing") or health
                log.exception("ingest %s %s", olr.name, season.year)
                report["errors"].append(f"{olr.name} {season.year}: {exc}")
    mism = [m for r in report["seasons"] for m in r["mismatches"]]
    health.status = "error" if report["errors"] and not report["seasons"] else ("degraded" if report["errors"] or mism else "ok")
    health.message = "; ".join(report["errors"] + mism)[:2000]
    if report["seasons"]:
        health.last_success = now_utc()
    health.detail = {"seasons": len(report["seasons"]), "mismatches": mism, "skipped": report["skipped"],
                     "olrs_not_found": not_found}
    s.flush()
    PROGRESS.update(running=False, phase="done", finished=now_utc().isoformat())
    return report
