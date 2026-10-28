"""Offline web for tests: routes requests to fixture files via httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from . import synthetic

FIX = Path(__file__).parent / "fixtures"


def _file(rel: str) -> str:
    return (FIX / rel).read_text(encoding="utf-8")


def html(rel: str, status: int = 200, headers: dict | None = None):
    return httpx.Response(status, text=_file(rel), headers={"content-type": "text/html; charset=utf-8", **(headers or {})})


def js(rel: str):
    return httpx.Response(200, text=_file(rel), headers={"content-type": "application/javascript"})


def jsn(data, status: int = 200):
    return httpx.Response(status, text=json.dumps(data), headers={"content-type": "application/json"})


class FakeWeb:
    def __init__(self):
        self.routes: dict[str, object] = {}
        self.blocked_hosts: set[str] = set()
        self.calls: list[str] = []
        self.anon_key = _file("elite/anon_key.txt").strip()
        self.results_page_size = None  # set to force pagination
        self.results_max_per_page = 15  # the live API caps page size; forces several pages

    def add(self, url: str, handler):
        self.routes[url.rstrip("/")] = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        host = request.url.host
        if host in self.blocked_hosts:
            return httpx.Response(403, text=_file("toppigeon/turnstile.html"),
                                  headers={"content-type": "text/html", "server": "cloudflare", "cf-ray": "x"})
        base = url.split("?")[0].rstrip("/")
        h = self.routes.get(base)
        if h is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/plain"})
        if callable(h):
            return h(request)
        return h

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def default_web() -> FakeWeb:
    w = FakeWeb()
    # Top Pigeon
    tp = "https://toppigeon.co.za"
    w.add(f"{tp}/product-category/active-auctions", html("toppigeon/active-auctions.html"))
    w.add(f"{tp}/product-category/active-auctions/afrikapro-2026-auction-2", html("toppigeon/category-afrikapro.html"))
    w.add(f"{tp}/product-category/active-auctions/dinokeng-upcoming", html("toppigeon/category-dinokeng.html"))
    w.add(f"{tp}/product/lot-1-za-2026-port-7829", html("toppigeon/lot-1.html"))
    w.add(f"{tp}/product/lot-2-za-2026-port-1001", html("toppigeon/lot-2.html"))
    w.add(f"{tp}/product/lot-3-unraced-youngster", html("toppigeon/lot-3.html"))
    w.add(f"{tp}/product/dinokeng-lot-1", html("toppigeon/dinokeng-lot-1.html"))
    # Best Pigeon
    bp = "https://bestpigeon.co.za"
    cat = f"{bp}/product-category/live-auctions/bloodstock-lofts-ends-28-okt-from-2000"
    w.add(f"{bp}/auctions/live", html("bestpigeon/live.html"))
    w.add(f"{bp}/auctions/pre-bidding", html("bestpigeon/pre-bidding.html"))
    w.add(cat, html("bestpigeon/category.html"))
    w.add(f"{cat}/page/2", html("bestpigeon/category-p2.html"))
    w.add(f"{bp}/product/za-2026-port-7829", html("bestpigeon/lot-7829.html"))
    w.add(f"{bp}/product/za-2026-port-8001", html("bestpigeon/lot-8001.html"))
    # Elite
    el = "https://elitepigeonauctions.co.za"
    supa = "https://amsnfjkefytwxipkqzev.supabase.co/rest/v1"
    w.add(f"{el}/auctions", html("elite/auctions.html"))
    w.add(f"{el}/assets/index-AbC123.js", js("elite/bundle.js"))

    def supa_handler(name):
        def h(req: httpx.Request):
            if req.headers.get("apikey") != w.anon_key or req.headers.get("authorization") != f"Bearer {w.anon_key}":
                return jsn({"message": "Invalid API key"}, 401)
            rows = json.loads(_file(f"elite/{name}.json"))
            q = parse_qs(req.url.query.decode())
            if "id" in q:
                want = q["id"][0].split(".", 1)[1]
                rows = [r for r in rows if str(r.get("id")) == want]
            return jsn(rows)
        return h

    w.add(f"{supa}/lots", supa_handler("lots"))
    w.add(f"{supa}/lofts", supa_handler("lofts"))
    # AfriPigeon
    ap = "https://afripigeon.com"
    w.add(f"{ap}/api/auctions/active", jsn(json.loads(_file("afripigeon/active.json"))))
    w.add(f"{ap}/api/auctions/upcoming", jsn(json.loads(_file("afripigeon/upcoming.json"))))
    w.add(f"{ap}/auctions", html("afripigeon/auctions.html"))
    w.add(f"{ap}/static/js/main.9f8e7d6c.js", js("afripigeon/main.js"))
    w.add(f"{ap}/api/auction-lots/by-auction/41", jsn(json.loads(_file("afripigeon/lots.json"))))
    w.add(f"{ap}/api/auction-lots/by-auction/42", jsn({"lots": []}))
    # Pigeon Auction House
    w.add("https://pigeonauctionhouse.com/live-auctions", html("pah/live-empty.html"))
    # Benzing (synthetic season)
    bz = "https://oneloftrace.live"
    w.add(f"{bz}/api/custom/v1/public/lofts", jsn(json.loads(_file("benzing/lofts.json"))))
    w.add(f"{bz}/lofts/147", html("benzing/loft-147.html"))
    w.add(f"{bz}/lofts/300", httpx.Response(200, headers={"content-type": "text/html"}, text=(
        '<script>window.__NUXT__=(function(a,b,C){C.id=3001;C.name="Season 2026";return {seasons:[C]}}(1,2,{}))'
        '</script>')))
    w.add(f"{bz}/api/custom/v1/public/season/3001/flightsAndTrainings", jsn({"stopped_flights": [], "running_flights": []}))
    w.add(f"{bz}/lofts/251", httpx.Response(200, text="<html><body>no payload</body></html>", headers={"content-type": "text/html"}))
    # Shape seen live: {"stopped_flights": [...], "running_flights": [...]} with flight_type.
    w.add(f"{bz}/api/custom/v1/public/season/2873/flightsAndTrainings",
          jsn({"stopped_flights": [{"id": f["id"], "name": f["name"], "distance": f["distance"], "season_id": 2873,
                                    "flight_type": f.get("type", "race"),
                                    "release_time": f"2026-07-{10 + i:02d} 08:30:00",
                                    "trigger_arrivals_counter": len(synthetic.results()[f["id"]]) or None,
                                    "trigger_basketings_counter": 40 if f.get("type") != "training" else None}
                                   for i, f in enumerate(synthetic.FLIGHTS)],
               "running_flights": []}))
    res = synthetic.results()

    def results_handler(fid):
        # Shape seen live (Oct 2026): {"all_flight_results": {Laravel page}, "my_flight_results": {...}};
        # the ring is pigeon.ring_description, the position arrival_order. The server caps page size.
        def h(req: httpx.Request):
            q = parse_qs(req.url.query.decode())
            page = int(q.get("page", ["1"])[0])
            size = min(w.results_page_size or int(q.get("paginationPerPage", ["1000"])[0]), w.results_max_per_page)
            rows = res[fid]
            data = [{"id": 900000 + r["position"], "flight_id": fid, "arrival_order": r["position"], "speed": r["speed"],
                     "pigeon": {"name": None, "ring_number": None, "ring_description": r["ringNumber"], "color": "BC",
                                "sex": "", "pigeon_team": {"country": "ZA", "name": r["teamName"]}}}
                    for r in rows[(page - 1) * size: page * size]]
            last = max(1, -(-len(rows) // size))
            return jsn({"all_flight_results": {"current_page": page, "data": data, "per_page": size,
                                               "last_page": last, "total": len(rows)},
                        "my_flight_results": {"current_page": 1, "data": [], "total": 0}})
        return h

    for f in synthetic.FLIGHTS:
        w.add(f"{bz}/api/search/v1/public/flights/{f['id']}/results/final", results_handler(f["id"]))
    # Shape seen live: Laravel pagination, teams carry a count but no ring list.
    teams = [{"id": i, "season_id": 2873, "name": t["name"], "registered_pigeons_count": len(t["pigeons"])}
             for i, t in enumerate(synthetic.teams())]
    w.add(f"{bz}/api/search/v1/public/pigeon-team/2873", jsn({"current_page": 1, "data": teams, "total": len(teams),
                                                            "last_page": 1, "per_page": 200}))
    # Other registry seasons have no flights in the synthetic web.
    for sid in (2722, 2141, 1160, 1049):
        w.add(f"{bz}/api/custom/v1/public/season/{sid}/flightsAndTrainings",
              jsn({"stopped_flights": [], "running_flights": []}))
        w.add(f"{bz}/api/search/v1/public/pigeon-team/{sid}", jsn({"data": [], "total": 0}))
    return w
