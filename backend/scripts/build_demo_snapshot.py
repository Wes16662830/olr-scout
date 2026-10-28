#!/usr/bin/env python3
"""Build the DEMO snapshot used by the GitHub Pages frontend.

Everything here is SYNTHETIC: the offline test fixtures (tests/fixtures) plus a
made-up OLR season. It runs the real backend (adapters, ingest, scoring,
Family Builder) against that data and saves the API responses to
frontend/src/demo/snapshot.json, so the static site behaves like the app
without a server. It is not real auction or race data.

    cd backend && python scripts/build_demo_snapshot.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OLR_SCOUT_SCHEDULER"] = "0"
os.environ["OLR_SCOUT_DATABASE_URL"] = "sqlite://"
os.environ["OLR_SCOUT_PASSWORD"] = "demo"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from olr_scout import db, refresh  # noqa: E402
from olr_scout.models import Alert, Lot, Watch  # noqa: E402
from olr_scout.results.benzing import BenzingResultsSource  # noqa: E402
from olr_scout.results.ingest import ingest_all, seed_registry  # noqa: E402
from olr_scout.scoring import engine, preferences  # noqa: E402
from olr_scout.sources.registry import build_sources  # noqa: E402
from olr_scout.util.http import PoliteClient  # noqa: E402
from olr_scout.util.timeutil import now_utc  # noqa: E402
from tests.fakeweb import default_web  # noqa: E402
from tests.helpers import make_lot  # noqa: E402

OUT = ROOT.parent / "frontend" / "src" / "demo" / "snapshot.json"

DEMO_LOTS = [  # (sex, current bid, seller text) — rings point at birds in the synthetic season
    ("cock", 1500, 'Kittel. Sire: ZA 2023 PORT 555 "Blue Kittel". Dam: ZA-26-100009 ace hen.'),
    ("hen", 1300, "Janssen"),
    ("cock", 2500, "Kittel x Janssen"),
    ("hen", 4200, "Thoné hen"),
    ("cock", 1800, ""),
    ("hen", 900, "Son of ace ZA-26-100005"),
    ("cock", 6500, "Over your max"),
    ("hen", 2200, "Dam: ZA-26-100000 ace of the season."),
]


def seed(s) -> None:
    from datetime import timedelta

    seed_registry(s)
    s.commit()
    web = default_web()
    client = PoliteClient(transport=web.transport(), min_interval=0, cache_seconds=0)
    ingest_all(s, BenzingResultsSource(client, sleep=lambda _x: None), ["AfrikaPro"])
    s.commit()
    refresh.refresh_all(s, build_sources(client))
    for i, (sex, price, text) in enumerate(DEMO_LOTS):
        ring = f"ZA-26-{100000 + i * 8}" if i < 4 else f"ZA-26-{100001 + i}"
        if i == 7:
            ring = None  # unraced youngster: Tier B through its dam
        make_lot(s, 100 + i, source="demo", auction_id="demo-afrikapro", auction_name="DEMO AfrikaPro 2026 Auction",
                 ring_raw=ring, sex=sex, current_bid=price, description=text or None, seller="Demo Lofts",
                 olr_tag="AfrikaPro", olr_year=2026, title=f"Lot {100 + i} {text}".strip(),
                 ends_at=now_utc() + timedelta(minutes=25 + 90 * i))
    s.commit()
    # DEMO bid history (made-up usernames) so cards show a latest bidder.
    from olr_scout.models import BidHistory

    for i, lot in enumerate(s.scalars(select(Lot).where(Lot.source == "demo").order_by(Lot.id)).all()[:4]):
        for j, who in enumerate(["b***r", "pigeonman", "GeForce RTX" if i == 1 else "k***p"]):
            s.add(BidHistory(lot_id=lot.id, bidder=who, amount=(lot.current_bid or 500) - (2 - j) * 100,
                             at=now_utc() - timedelta(hours=3 - j)))
        lot.bid_count = 3
        lot.leading_bidder = "GeForce RTX" if i == 1 else "k***p"
    s.commit()
    # A finished DEMO auction for the Results screen (prices, buyers and outcomes are made up).
    from olr_scout.refresh import settle

    buyers = ["b***r", "pigeonman", "GeForce RTX", "loft_77", "b***r", "s***h", "pigeonman", None, "k***p", "t***o"]
    for i in range(10):
        price = [8500, 2200, 4100, 600, 12500, 3300, 1500, None, 950, 5200][i]
        lot = make_lot(s, 200 + i, source="demo", auction_id="demo-closed", auction_name="DEMO AfrikaPro 2026 Auction 1",
                       ring_raw=f"ZA-26-{100010 + i}", sex="cock" if i % 2 else "hen", seller="Demo Lofts",
                       olr_tag="AfrikaPro", olr_year=2026, title=f"Lot {200 + i}", status="closed",
                       current_bid=price, bid_count=0 if price is None else 3 + i, reserve_met=False if i == 3 else True,
                       leading_bidder=buyers[i], ends_at=now_utc() - timedelta(days=2, minutes=-2 * i))
        lot.final_read = True
        settle(lot)
    s.commit()
    engine.score_all(s)
    first = s.scalar(select(Lot).where(Lot.source == "demo").order_by(Lot.id))
    s.add(Watch(lot_id=first.id))
    s.add(Alert(lot_id=first.id, kind="closing", dedupe="30", message=f"DEMO {first.auction_name} · Lot {first.lot_no} closes in 25 min"))
    s.commit()


def main() -> int:
    db.configure("sqlite://")
    db.init_db()
    s = db.SessionLocal()
    seed(s)
    from olr_scout.api import create_app

    api = TestClient(create_app(start_scheduler=False))
    assert api.post("/api/login", json={"password": "demo"}).status_code == 200

    def get(path: str):
        r = api.get("/api" + path)
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type", "") else r.text

    snap: dict = {"generated_at": now_utc().isoformat(), "get": {}, "plans": {}}
    for path in ["/me", "/suggestions", "/closing?hours=24", "/watchlist", "/alerts", "/alerts?unread=true",
                 "/families?min_entries=1&limit=300", "/olrs", "/inventory", "/pedigree/review", "/sources",
                 "/settings", "/push/key", "/builder/plans", "/export.csv", "/export/whatsapp"]:
        snap["get"][path] = get(path)
    snap["get"]["/lots?status=all"] = get("/lots?status=all")
    snap["get"]["/results/auctions"] = get("/results/auctions")
    for a in snap["get"]["/results/auctions"]:
        path = f"/results/auction?source={a['source']}&auction_id={a['auction_id']}"
        snap["get"][path] = get(path)
    closed_ids = [r["id"] for a in snap["get"]["/results/auctions"]
                  for r in get(f"/results/auction?source={a['source']}&auction_id={a['auction_id']}")["lots"]]
    for lot_id in [lot["id"] for lot in snap["get"]["/lots?status=all"]] + closed_ids:
        snap["get"][f"/lots/{lot_id}"] = get(f"/lots/{lot_id}")
    snap["xlsx_base64"] = base64.b64encode(api.get("/api/export.xlsx").content).decode()
    goal = {"pairs": 6, "cocks": 6, "hens": 6, "budget": 60000, "olrs": [], "allow_line_bred": True}
    families = [f["family"] for f in snap["get"]["/families?min_entries=1&limit=300"]["families"]]
    for fam in families:
        r = api.post("/api/builder/plan", json={**goal, "core_families": [fam]})
        snap["plans"][fam] = r.json()
    snap["plans"][""] = api.post("/api/builder/plan", json={**goal, "core_families": []}).json()
    snap["default_goal"] = goal
    OUT.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(snap['get']['/lots?status=all'])} lots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
