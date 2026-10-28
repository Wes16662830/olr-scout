"""Build small, explicit OLR seasons and lots directly in the DB (SYNTHETIC)."""

from __future__ import annotations

from datetime import timedelta

from olr_scout.models import Bird, BirdResult, Flight, Lot, Olr, Season
from olr_scout.results.ingest import recompute_family_stats
from olr_scout.rings import normalise
from olr_scout.scoring.tier_a import FlightIn, family_key, season_metrics
from olr_scout.util.timeutil import now_utc

_ids = {"flight": 90000, "season": 80000}


def make_season(s, olr_name: str, year: int, birds: dict[str, tuple[str, list[int | None]]],
                arrived: int = 100, distances=(100, 200, 300, 400, 500, 600), final_last=True, pad: int = 0):
    """birds: ring → (team, [position per race or None]). ``pad`` adds filler birds so
    the registered count (and hence the 5% ace cut) is realistic."""
    olr = s.query(Olr).filter_by(name=olr_name).one_or_none() or Olr(name=olr_name, aliases=[olr_name.lower()])
    s.add(olr)
    s.flush()
    _ids["season"] += 1
    season = Season(id=_ids["season"], olr_id=olr.id, year=year)
    s.add(season)
    flights = []
    for i, d in enumerate(distances):
        _ids["flight"] += 1
        f = Flight(id=_ids["flight"], season_id=season.id, name=f"Race {i + 1}" if not (final_last and i == len(distances) - 1) else "Final",
                   distance_km=d, arrived=arrived, is_final=final_last and i == len(distances) - 1, race_no=i + 1)
        s.add(f)
        flights.append(f)
    s.flush()
    results = {f.id: {} for f in flights}
    teams = {}
    for ring, (team, positions) in birds.items():
        n = normalise(ring)
        teams[n] = (team, ring)
        for f, p in zip(flights, positions):
            if p is not None:
                results[f.id][n] = p
    registered = set(teams) | {f"PAD{i}" for i in range(pad)}
    metrics = season_metrics([FlightIn(f.id, f.distance_km, f.arrived, False, f.is_final) for f in flights],
                             results, registered)
    out = {}
    for n, m in metrics.items():
        team, raw = teams.get(n, ("Filler Lofts", n))
        b = Bird(season_id=season.id, ring_norm=n, ring_raw=raw, team=team, family_key=family_key(team),
                 is_ace=m.is_ace, long_score=m.long_score, all_score=m.all_score, final_position=m.final_position)
        s.add(b)
        s.flush()
        for fid, pos in m.positions.items():
            if pos is not None:
                s.add(BirdResult(bird_id=b.id, flight_id=fid, position=pos))
        out[raw] = b
    season.registered = len(registered)
    s.flush()
    recompute_family_stats(s)
    return season, out


def make_lot(s, n: int, **kw) -> Lot:
    defaults = dict(source="test", auction_id="auc", auction_name="Test Auction", lot_key=f"lot-{n}",
                    url=f"https://example.invalid/lot/{n}", title=f"Lot {n}", lot_no=n, status="live",
                    ends_at=now_utc() + timedelta(hours=5), extra={})
    defaults.update(kw)
    if defaults.get("ring_raw") and not defaults.get("ring_norm"):
        defaults["ring_norm"] = normalise(defaults["ring_raw"])
    lot = Lot(**defaults)
    s.add(lot)
    s.flush()
    return lot
