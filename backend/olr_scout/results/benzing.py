"""Benzing Live / oneloftrace.live results — UNOFFICIAL endpoints.

These were found by watching the public results pages. They may change without
notice, so field names are read tolerantly and ``health_check`` fails loudly
when the shape is not what the parser expects.
"""

from __future__ import annotations

import logging
import re
import time

from ..config import settings
from ..util.http import PoliteClient, SourceUnavailable
from ..util.timeutil import parse_iso
from .base import (
    FlightInfo,
    FlightResults,
    HealthError,
    LoftInfo,
    ResultRow,
    ResultsSource,
    SeasonInfo,
    TeamEntry,
)
from .nuxt import find_seasons, payload_from_html

log = logging.getLogger(__name__)

PAGE_SIZE = 1000
TEAM_PAGE_SIZE = 200


def _rows(data) -> tuple[list[dict], int | None]:
    """Return (rows, total) from any of the paginated shapes seen."""
    if isinstance(data, list):
        return data, None
    if not isinstance(data, dict):
        return [], None
    total = None
    for k in ("total", "totalCount", "totalItems", "count", "recordsTotal"):
        if isinstance(data.get(k), int):
            total = data[k]
            break
    meta = data.get("meta") or data.get("pagination") or {}
    if total is None and isinstance(meta, dict):
        for k in ("total", "totalCount", "totalItems"):
            if isinstance(meta.get(k), int):
                total = meta[k]
    for k in ("data", "items", "results", "rows", "content", "lofts", "pigeons", "teams"):
        v = data.get(k)
        if isinstance(v, list):
            return v, total
        if isinstance(v, dict):
            inner, t2 = _rows(v)
            if inner:
                return inner, total if total is not None else t2
    return [], total


def _get(d: dict, *keys, default=None):
    for k in keys:
        cur = d
        ok = True
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur and cur[part] not in (None, ""):
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def _int(v) -> int | None:
    try:
        return int(str(v).strip().rstrip("."))
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").replace("km", "").strip())
    except (TypeError, ValueError):
        return None


class BenzingResultsSource(ResultsSource):
    key = "benzing"

    def __init__(self, client: PoliteClient, base_url: str | None = None, sleep=time.sleep):
        self.client = client
        self.base = (base_url or settings.benzing_base_url).rstrip("/")
        self._sleep = sleep
        self.mismatches: list[str] = []

    # ----------------------------------------------------------------- lofts / seasons
    def list_lofts(self) -> list[LoftInfo]:
        data = self.client.get_json(f"{self.base}/api/custom/v1/public/lofts", params={"page": 1, "paginationPerPage": 500})
        rows, _ = _rows(data)
        out = []
        for r in rows:
            lid = _int(_get(r, "id", "loftId"))
            name = _get(r, "name", "loftName", "title")
            if lid is not None and name:
                out.append(LoftInfo(lid, str(name).strip()))
        return out

    def list_seasons(self, loft_id: int) -> list[SeasonInfo]:
        html = self.client.get_text(f"{self.base}/lofts/{loft_id}")
        payload = payload_from_html(html)
        if payload is None:
            raise HealthError(f"loft {loft_id}: no Nuxt payload in page (site changed?)")
        return [SeasonInfo(s["id"], s["year"], s["name"]) for s in find_seasons(payload)]

    # ----------------------------------------------------------------- flights
    def list_flights(self, season_id: int) -> list[FlightInfo]:
        data = self.client.get_json(f"{self.base}/api/custom/v1/public/season/{season_id}/flightsAndTrainings")
        items: list[tuple[dict, bool]] = []
        if isinstance(data, dict) and any(k in data for k in ("flights", "trainings")):
            items += [(f, False) for f in data.get("flights") or []]
            items += [(f, True) for f in data.get("trainings") or []]
        else:
            rows, _ = _rows(data)
            items = [(f, False) for f in rows]
        out = []
        for f, training in items:
            fid = _int(_get(f, "id", "flightId"))
            if fid is None:
                continue
            name = str(_get(f, "name", "title", "flightName", default=f"Flight {fid}"))
            kind = str(_get(f, "type", "flightType", "kind", default="")).lower()
            is_training = training or bool(f.get("isTraining")) or "train" in kind or "train" in name.lower()
            dist = _float(_get(f, "distance", "distanceKm", "distance_km", "km"))
            if dist and dist > 5000:  # metres
                dist = dist / 1000
            m = re.search(r"(?:race|flight|vlug|wedvlug)\s*(\d+)", name, re.I)
            out.append(
                FlightInfo(
                    id=fid, name=name, distance_km=dist,
                    flown_at=parse_iso(_get(f, "date", "flightDate", "releaseTime", "startDate")),
                    is_training=is_training,
                    is_final="final" in name.lower() or "final" in kind,
                    race_no=_int(_get(f, "number", "raceNumber", "order")) or (int(m.group(1)) if m else None),
                    basketed=_int(_get(f, "basketed", "pigeonsCount", "entered", "numberOfPigeons")),
                )
            )
        return out

    # ----------------------------------------------------------------- results
    def flight_results(self, flight_id: int) -> FlightResults:
        rows: list[ResultRow] = []
        total: int | None = None
        page = 1
        prev_first = None
        while True:
            params = {"page": page, "search": "", "paginationPerPage": PAGE_SIZE, "onlyUserPigeons": "false"}
            data = self._get_with_backoff(f"{self.base}/api/search/v1/public/flights/{flight_id}/results/final", params)
            batch, t = _rows(data)
            total = t if t is not None else total
            first = repr(batch[0]) if batch else None
            if page > 1 and first == prev_first:
                self.mismatches.append(f"flight {flight_id}: page {page} repeated page {page - 1}; stopped")
                break  # the API ignored the page number — stop instead of looping
            prev_first = first
            for r in batch:
                ring = _get(r, "ringNumber", "ring", "pigeonRing", "pigeon.ringNumber", "pigeon.ring", "ring_number")
                if not ring:
                    continue
                rows.append(
                    ResultRow(
                        ring_raw=str(ring).strip(),
                        position=_int(_get(r, "position", "place", "rank", "pos")),
                        team=_get(r, "teamName", "team", "fancierName", "user.name", "owner", "loftName", "pigeon.teamName"),
                        name=_get(r, "pigeonName", "name", "pigeon.name"),
                        speed=_float(_get(r, "speed", "velocity")),
                        sex=_get(r, "sex", "gender", "pigeon.sex"),
                        colour=_get(r, "color", "colour", "pigeon.color"),
                    )
                )
            if not batch or len(batch) < PAGE_SIZE or (total is not None and len(rows) >= total):
                break
            page += 1
            if page > 200:
                break
        complete = total is None or len(rows) == total
        note = ""
        if total is not None and len(rows) != total:
            note = f"flight {flight_id}: got {len(rows)} rows, API total {total}"
            self.mismatches.append(note)
            log.warning("results mismatch: %s", note)
        return FlightResults(flight_id, rows, total, complete, note)

    def _get_with_backoff(self, url: str, params: dict, tries: int = 4):
        delay = 2.0
        for attempt in range(tries):
            try:
                return self.client.get_json(url, params=params, use_cache=False)
            except SourceUnavailable:
                if attempt == tries - 1:
                    raise
                self._sleep(delay)
                delay *= 2
        return None

    def season_teams(self, season_id: int) -> list[TeamEntry]:
        teams: list[TeamEntry] = []
        page = 1
        seen_total = None
        prev_first = None
        while True:
            data = self._get_with_backoff(
                f"{self.base}/api/search/v1/public/pigeon-team/{season_id}",
                {"page": page, "paginationPerPage": TEAM_PAGE_SIZE},
            )
            batch, total = _rows(data)
            seen_total = total if total is not None else seen_total
            first = repr(batch[0]) if batch else None
            if page > 1 and first == prev_first:
                break  # page number ignored by the API
            prev_first = first
            for t in batch:
                name = _get(t, "name", "teamName", "title")
                pigeons = _get(t, "pigeons", "birds", "pigeonList", default=[]) or []
                rings = []
                for p in pigeons:
                    if isinstance(p, dict):
                        r = _get(p, "ringNumber", "ring", "ring_number")
                        if r:
                            rings.append(str(r))
                    elif isinstance(p, str):
                        rings.append(p)
                if name:
                    teams.append(TeamEntry(str(name).strip(), rings))
            if not batch or len(batch) < TEAM_PAGE_SIZE or (seen_total is not None and len(teams) >= seen_total):
                break
            page += 1
            if page > 100:
                break
        return teams

    # ----------------------------------------------------------------- health
    def health_check(self) -> dict:
        """Fail loudly (HealthError) if the unofficial API no longer looks as expected."""
        data = self.client.get_json(f"{self.base}/api/custom/v1/public/lofts", params={"page": 1, "paginationPerPage": 5}, use_cache=False)
        rows, _ = _rows(data)
        if not rows:
            raise HealthError("lofts endpoint returned no rows — endpoint moved or response shape changed")
        missing = [k for k in ("id", "name") if _get(rows[0], k, "loft" + k.title()) is None]
        if missing:
            raise HealthError(f"lofts rows missing keys {missing}; keys now: {sorted(rows[0].keys())[:20]}")
        return {"ok": True, "sample": [_get(r, "name", "loftName") for r in rows[:5]]}
