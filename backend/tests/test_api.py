import pytest
from fastapi.testclient import TestClient

from olr_scout import refresh
from olr_scout.api import create_app
from olr_scout.sources.registry import build_sources


@pytest.fixture()
def api(session, client):
    refresh.refresh_all(session, build_sources(client))
    app = create_app(start_scheduler=False)
    return TestClient(app)


def login(api):
    r = api.post("/api/login", json={"password": "test-password"})
    assert r.status_code == 200


def test_requires_login(api):
    assert api.get("/api/suggestions").status_code == 401
    assert api.post("/api/login", json={"password": "nope"}).status_code == 401


def test_suggestions_settings_export(api):
    login(api)
    r = api.get("/api/suggestions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(i["price"] <= i["max"] for i in items)
    assert all(i["tier"] in ("A", "B", "C") for i in items)
    s = api.get("/api/settings").json()
    s["max_bid"] = 1000
    assert api.put("/api/settings", json=s).json()["max_bid"] == 1000
    assert all(i["price"] <= 1000 for i in api.get("/api/suggestions").json()["items"])
    csv = api.get("/api/export.csv")
    assert csv.status_code == 200 and csv.text.startswith("Tier,Combined,Racing,Breeding")
    assert api.get("/api/export.xlsx").content[:2] == b"PK"
    wa = api.get("/api/export/whatsapp").text
    assert wa.startswith("*OLR Scout suggestions*") and "```" in wa


def test_lot_detail_watch_and_sources(api):
    login(api)
    lots = api.get("/api/lots").json()
    lid = lots[0]["id"]
    d = api.get(f"/api/lots/{lid}").json()
    assert "price_history" in d and "claims" in d
    assert api.post(f"/api/lots/{lid}/watch", json={"closes_in": [30, 10]}).json()["ok"]
    assert api.get("/api/watchlist").json()[0]["lot"]["id"] == lid
    srcs = {x["key"]: x for x in api.get("/api/sources").json()}
    assert set(srcs) == {"toppigeon", "elite", "bestpigeon", "afripigeon", "pah", "benzing"}
    assert srcs["pah"]["status"] == "empty"
    assert api.get("/api/closing?hours=99999").status_code == 200


def test_inventory_and_plan(api):
    login(api)
    r = api.post("/api/inventory", json={"ring": "ZA 2024 PORT 1", "sex": "hen", "family": "Alpha Lofts"})
    assert r.status_code == 200
    plan = api.post("/api/builder/plan", json={"pairs": 2, "budget": 10000, "core_families": []}).json()
    assert plan["total_max"] <= 10000


def test_export_limited_to_selected_auctions(api):
    login(api)
    items = api.get("/api/suggestions").json()["items"]
    keys = sorted({f"{i['source']}:{i['auction_id']}" for i in items})
    assert len(keys) >= 2
    one = keys[0]
    csv_all = api.get("/api/export.csv").text.strip().splitlines()
    csv_one = api.get("/api/export.csv", params={"auctions": one}).text.strip().splitlines()
    expected = sum(1 for i in items if f"{i['source']}:{i['auction_id']}" == one)
    assert len(csv_one) - 1 == expected < len(csv_all) - 1


def test_card_shows_latest_bid_and_bidder(api):
    login(api)
    cards = {c["title"]: c for c in api.get("/api/lots").json()}
    tp = next(c for t, c in cards.items() if "7829 (C) – Kittel" in t)
    assert tp["last_bid"]["amount"] == 3500 and tp["last_bid"]["bidder"] == "GeForce RTX"
    assert tp["last_bid"]["at"] and tp["last_bid"]["count"] == 3 and tp["last_bid"]["bidder_shown"]
    elite = next(c for c in cards.values() if c["source"] == "elite" and c["current_bid"] == 1200)
    assert elite["last_bid"] == {"amount": 1200, "bidder": None, "at": None, "count": 4, "bidder_shown": False}


def test_best_race_conditions(session):
    from olr_scout.models import BirdResult, Flight
    from olr_scout.serialize import bird_summary

    from .helpers import make_season

    # 6 races at 100..600 km; the bird is near the top in the 3 slowest races, mid-field in the fast ones.
    _, birds = make_season(session, "AfrikaPro", 2026, {"ZA-26-100": ("A Lofts", [50, 50, 50, 2, 3, 1])}, pad=10)
    bird = birds["ZA-26-100"]
    flights = session.query(Flight).filter(Flight.season_id == bird.season_id).order_by(Flight.id).all()
    winner_speeds = [1600, 1550, 1500, 1100, 1050, 1000]  # races 4-6 were slow
    for f, sp in zip(flights, winner_speeds):
        session.add(BirdResult(bird_id=next(iter(birds.values())).id + 1, flight_id=f.id, position=1, speed=sp))
    session.flush()
    out = bird_summary(session, bird)
    assert out["best_speed"]["best"] == "slow"
    assert out["best_speed"]["by"]["slow"]["races"] == 2  # thirds of 6 races: the 2 slowest
    assert [r["speed_class"] for r in out["races"]] == ["fast", "fast", "medium", "medium", "slow", "slow"]
    assert out["best_distance"]["best"] == "450 km +"
