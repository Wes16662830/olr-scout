"""AfrikaPro jacket standings (Blue = Ace pigeon over all races, Green = sprint races 1-5,
Brown = endurance races 6-10), shown on the lot cards next to the race results.

The standings come from files in ``olr_scout/data`` (``afrikapro_jackets_<year>.json``): the
official final standings as the AfrikaPro rankings page shows them to visitors, top 375 of each
jacket. A season's jackets are final once its final is flown, so one file per season is enough.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .rings import normalise, parse_ring

DATA = Path(__file__).resolve().parent / "data"
JACKETS = ("blue", "green", "brown")


def ring_key(ring: str | None) -> str | None:
    if not ring:
        return None
    p = parse_ring(ring)
    return p.canonical if p and p.canonical else normalise(ring)


@lru_cache(maxsize=1)
def _standings() -> dict[tuple[str, int], dict]:
    """(OLR, season year) → {"meta": …, "by_ring": {ring key: {jacket: rank}}}."""
    out: dict[tuple[str, int], dict] = {}
    for f in sorted(DATA.glob("*_jackets_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        by_ring: dict[str, dict] = {}
        for jacket, rank, ring, _team in d["rows"]:
            k = ring_key(ring)
            if k:
                by_ring.setdefault(k, {})[jacket] = rank
        meta = {k: d.get(k) for k in ("olr", "season_year", "race_number", "final", "top", "source", "captured")}
        out[(d["olr"], int(d["season_year"]))] = {"meta": meta, "by_ring": by_ring}
    return out


def for_bird(olr: str | None, season_year: int | None, ring: str | None) -> dict | None:
    """The bird's jacket places in that OLR season, or None when no standings are known for it.
    A jacket missing from ``places`` means outside the published top ``top``."""
    st = _standings().get((olr or "", int(season_year or 0)))
    if st is None or not ring:
        return None
    return {**st["meta"], "places": st["by_ring"].get(ring_key(ring), {})}
