"""What-if standings over any set of races of one OLR season ("Blue after race 9 without the
final", "best at race 8", "races 6-10" …), and which of those birds are on auction now.

Two measures:
* ``time``: total flying time over the chosen races, as AfrikaPro ranks its jackets: a bird
  must be home in every chosen race, and no race counts slower than 500 m/min (slower arrivals
  are scored at 500 m/min). Checked against AfrikaPro 2026's official Blue, Green and Brown
  jackets: the top 50 of each come out identical, place for place. Lower down, a bird that
  stayed out overnight can differ by up to an hour (AfrikaPro counts the night slightly
  differently from the results site).
* ``result``: OLR Scout's race result (half placing among the starters, half time behind the
  winner), averaged over the chosen races; a race the bird missed counts as last.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import jackets
from .models import Bird, BirdResult, Flight, Lot, Season

MIN_SPEED = 500.0  # m/min: AfrikaPro's floor (a slower arrival counts at this speed)
LIVE = ("live", "upcoming")


def season_races(s: Session, season_id: int) -> list[dict]:
    flights = s.scalars(select(Flight).where(Flight.season_id == season_id, Flight.is_training.is_(False))
                        .order_by(Flight.flown_at, Flight.id)).all()
    return [{"no": f.race_no or i, "flight_id": f.id, "name": f.name, "km": f.distance_km, "final": f.is_final,
             "date": f.flown_at.isoformat() if f.flown_at else None, "arrived": f.arrived, "basketed": f.basketed}
            for i, f in enumerate(flights, 1)]


def standings(s: Session, season_id: int, race_nos: list[int], measure: str = "time",
              on_auction_only: bool = False, limit: int = 100) -> dict:
    season = s.get(Season, season_id)
    if season is None:
        raise ValueError("unknown season")
    races = [r for r in season_races(s, season_id) if r["no"] in set(race_nos)]
    if not races:
        raise ValueError("choose at least one race")
    fids = {r["flight_id"]: r for r in races}
    birds = {b.id: b for b in s.scalars(select(Bird).where(Bird.season_id == season_id))}
    results: dict[int, dict[int, BirdResult]] = defaultdict(dict)
    for r in s.scalars(select(BirdResult).where(BirdResult.flight_id.in_(list(fids)))):
        results[r.bird_id][r.flight_id] = r

    rows = []
    for bid, b in birds.items():
        got = results.get(bid, {})
        home = [fid for fid in fids if got.get(fid) is not None and got[fid].position is not None]
        if measure == "time":
            if len(home) < len(fids) or any(not got[fid].speed for fid in fids):
                continue  # jacket rule: home in every chosen race
            value = sum((fids[fid]["km"] or 0) * 1000 / max(got[fid].speed, MIN_SPEED) for fid in fids)  # minutes
        else:
            if not home:
                continue
            value = sum((got[fid].result_pct if got.get(fid) is not None and got[fid].result_pct is not None
                         else 1.0) for fid in fids) / len(fids)
        rows.append((value, b, len(home)))
    rows.sort(key=lambda x: (x[0], x[1].ring_norm))
    ranked = {b.id: i for i, (_, b, _) in enumerate(rows, 1)}

    on_sale: dict[int, list[Lot]] = defaultdict(list)
    for lot in s.scalars(select(Lot).where(Lot.status.in_(LIVE), Lot.bird_id.in_(list(birds)))):
        on_sale[lot.bird_id].append(lot)

    lead = rows[0][0] if rows else None
    out = []
    for value, b, n_home in rows:
        lots = on_sale.get(b.id, [])
        if on_auction_only and not lots:
            continue
        j = jackets.for_bird(season.olr.name, season.year, b.ring_raw)
        out.append({
            "rank": ranked[b.id], "bird_id": b.id, "ring": b.ring_raw, "name": b.name, "team": b.team,
            "value": round(value, 4), "gap": round(value - lead, 4) if lead is not None else None, "races_home": n_home,
            "jackets": (j or {}).get("places"),
            "lots": [{"id": l.id, "lot_no": l.lot_no, "auction": l.auction_name, "source": l.source,
                      "price": l.current_bid if l.current_bid is not None else l.starting_bid,
                      "has_bid": l.current_bid is not None, "url": l.url} for l in lots],
        })
        if len(out) >= limit:
            break
    return {"olr": season.olr.name, "season": season.year, "season_id": season_id, "measure": measure,
            "races": [r["no"] for r in races], "ranked": len(rows),
            "on_auction": sum(1 for bid in ranked if bid in on_sale), "rows": out}


def rank_of_birds(s: Session, scenario: dict) -> dict[int, int]:
    """bird id → place in a saved scenario (Suggestions ordered by it)."""
    st = standings(s, int(scenario["season_id"]), [int(n) for n in scenario["races"]],
                   scenario.get("measure", "time"), limit=10 ** 6)
    return {r["bird_id"]: r["rank"] for r in st["rows"]}
