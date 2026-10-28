#!/usr/bin/env python3
"""Probe the OLR results site (Benzing / oneloftrace) and write what it returns.

Writes results-diagnosis.txt in the OLR Scout folder: HTTP status, field
names and one sample row per endpoint, plus the last error the app stored.
Nothing personal is included. Paste the file's contents to Claude.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from olr_scout.config import settings  # noqa: E402
from olr_scout.results.benzing import BenzingResultsSource, _rows  # noqa: E402
from olr_scout.results.nuxt import find_seasons, payload_from_html  # noqa: E402
from olr_scout.util.http import PoliteClient  # noqa: E402

OUT = ROOT.parent / "results-diagnosis.txt"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def short(obj, limit: int = 700) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str) if not isinstance(obj, str) else obj
    return text if len(text) <= limit else text[:limit] + f" … (+{len(text) - limit} chars)"


def describe(label: str, url: str, params: dict | None = None):
    say(f"\n=== {label}\nGET {url} {params or ''}")
    try:
        resp = client.get(url, params=params, use_cache=False)
    except Exception as exc:
        say(f"FAILED: {type(exc).__name__}: {exc}")
        return None
    ctype = resp.headers.get("content-type", "")
    say(f"HTTP {resp.status_code} · {ctype} · {len(resp.text)} bytes")
    if "json" not in ctype:
        say("Body starts: " + short(resp.text[:400].replace("\n", " ")))
        return resp.text
    try:
        data = resp.json()
    except ValueError:
        say("Not valid JSON. Body starts: " + short(resp.text[:300]))
        return None
    if isinstance(data, dict):
        say(f"Top-level keys: {list(data.keys())[:30]}")
    rows, total = _rows(data)
    say(f"Rows found by the app's reader: {len(rows)} · total reported: {total}")
    if rows:
        say(f"Row keys: {list(rows[0].keys()) if isinstance(rows[0], dict) else type(rows[0]).__name__}")
        say("First row: " + short(rows[0]))
    elif isinstance(data, (dict, list)):
        say("Body: " + short(data))
    return data


client = PoliteClient(cache_seconds=0)
base = settings.benzing_base_url.rstrip("/")
say("OLR Scout results diagnosis")
say(f"Base URL: {base}")

lofts = describe("Loft list", f"{base}/api/custom/v1/public/lofts", {"page": 1, "paginationPerPage": 500})
if lofts is not None:
    rows, _ = _rows(lofts)
    names = [f"{r.get('id')}: {r.get('name')}" for r in rows if isinstance(r, dict)][:40]
    say("Lofts (id: name): " + "; ".join(names))

html = describe("Loft page AfrikaPro (seasons)", f"{base}/lofts/147")
season_id = 2873
if isinstance(html, str):
    payload = payload_from_html(html)
    say(f"Nuxt payload found: {payload is not None}")
    if payload is not None:
        seasons = find_seasons(payload)
        say(f"Seasons the app found: {seasons[:10]}")
        if not seasons:
            say("Payload sample: " + short(payload, 1500))
    for marker in ("__NUXT_DATA__", "window.__NUXT__", "__NEXT_DATA__", "seasonId", "season"):
        say(f"  page contains '{marker}': {marker in html}")
    import re as _re

    say("Where 'season' appears in the page (first 8):")
    for m in list(_re.finditer(r"season", html, _re.I))[:8]:
        say("  …" + html[max(0, m.start() - 80): m.end() + 120].replace("\n", " ") + "…")
    say("Numbers 2873 / 2722 (known AfrikaPro season ids) in the page:")
    for sid in ("2873", "2722"):
        i = html.find(sid)
        say(f"  {sid}: " + ("…" + html[max(0, i - 120): i + 80].replace("\n", " ") + "…" if i >= 0 else "not found"))

for cand in (f"{base}/api/custom/v1/public/lofts/147", f"{base}/api/custom/v1/public/loft/147/seasons",
             f"{base}/api/custom/v1/public/lofts/147/seasons"):
    describe("Possible seasons endpoint", cand)

flights = describe(f"Flights of season {season_id}", f"{base}/api/custom/v1/public/season/{season_id}/flightsAndTrainings")
src = BenzingResultsSource(client, sleep=lambda _s: None)
first_race = None
try:
    fl = src.list_flights(season_id)
    say(f"Flights the app parsed: {len(fl)}")
    if isinstance(flights, dict):
        types = {}
        for key in ("stopped_flights", "running_flights"):
            for f in flights.get(key) or []:
                types[str(f.get("flight_type"))] = types.get(str(f.get("flight_type")), 0) + 1
        say(f"flight_type values: {types}")
    say(f"Training tosses: {sum(f.is_training for f in fl)} · races:")
    for f in [x for x in fl if not x.is_training][:20]:
        say(f"  id={f.id} name={f.name!r} km={f.distance_km} final={f.is_final} arrived={f.arrived} basketed={f.basketed}")
    first_race = next((f for f in fl if not f.is_training), None)
except Exception as exc:
    say(f"App could not parse flights: {type(exc).__name__}: {exc}")

if first_race:
    res = describe(f"Results of {first_race.name} (page 1)",
                   f"{base}/api/search/v1/public/flights/{first_race.id}/results/final",
                   {"page": 1, "search": "", "paginationPerPage": 5, "onlyUserPigeons": "false"})
    if res is not None:
        rws, _ = _rows(res)
        if len(rws) > 1:
            say("Second row: " + short(rws[1]))
    try:
        import olr_scout.results.benzing as bzmod

        bzmod.PAGE_SIZE = 5
        fr = src.flight_results(first_race.id)
        say(f"How the app reads these rows: {len(fr.rows)} rows, total {fr.total}")
        for r in fr.rows[:3]:
            say(f"  ring={r.ring_raw!r} position={r.position} team={r.team!r} name={r.name!r}")
        if not fr.rows:
            say("  -> the app found NO ring in these rows (field names differ)")
    except Exception as exc:
        say(f"App could not read results: {type(exc).__name__}: {exc}")

describe(f"Teams of season {season_id}", f"{base}/api/search/v1/public/pigeon-team/{season_id}",
         {"page": 1, "paginationPerPage": 3})

say("\n=== Health check")
try:
    say(str(src.health_check()))
except Exception as exc:
    say(f"FAILED: {type(exc).__name__}: {exc}")

say("\n=== Last results error stored by the app")
try:
    from olr_scout.db import SessionLocal
    from olr_scout.models import Bird, Season, SourceHealth

    with SessionLocal() as s:
        h = s.get(SourceHealth, "benzing")
        say(f"status={h.status if h else None} message={h.message if h else None}")
        say(f"detail={short(h.detail) if h else None}")
        say(f"birds stored: {s.query(Bird).count()} · seasons ingested: "
            f"{s.query(Season).filter(Season.ingested_at.is_not(None)).count()}")
except Exception:
    say(traceback.format_exc()[-800:])

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nSaved to {OUT}")
