import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from olr_scout.api import create_app
from olr_scout.models import Olr, Season


@pytest.fixture()
def api(session):
    c = TestClient(create_app(start_scheduler=False), raise_server_exceptions=False)
    c.post("/api/login", json={"password": "test-password"})
    return c


def test_loft_id_taken_by_an_auto_added_entry_is_merged(session, api):
    # The loft list added "Dinokeng One Loft Race" (disabled) with loft 300, plus one season.
    auto = Olr(name="Dinokeng One Loft Race", loft_id=300, aliases=["dinokeng one loft race"],
               auto_discovered=True, enabled=False)
    session.add(auto)
    session.flush()
    session.add(Season(id=3001, olr_id=auto.id, year=2026))
    session.commit()
    dino = session.scalar(select(Olr).where(Olr.name == "Dinokeng"))
    r = api.put("/api/olrs", json={"id": dino.id, "loft_id": 300})
    assert r.status_code == 200, r.text
    assert "merged" in r.json()["message"]
    session.expire_all()
    dino = session.scalar(select(Olr).where(Olr.name == "Dinokeng"))
    assert dino.loft_id == 300 and [x.id for x in dino.seasons] == [3001]
    assert session.scalar(select(Olr).where(Olr.name == "Dinokeng One Loft Race")) is None


def test_loft_id_of_another_real_entry_gives_a_clear_error(session, api):
    dino = session.scalar(select(Olr).where(Olr.name == "Dinokeng"))
    r = api.put("/api/olrs", json={"id": dino.id, "loft_id": 147})  # AfrikaPro's
    assert r.status_code == 409 and "AfrikaPro" in r.json()["detail"]


def test_new_entry_needs_a_name_and_saves_seasons(session, api):
    assert api.put("/api/olrs", json={"name": "  ", "loft_id": 555}).status_code == 400
    r = api.put("/api/olrs", json={"name": "Cape Town Winter Aces", "loft_id": 323, "seasons": {"2026": "4001"}})
    assert r.status_code == 200, r.text
    session.expire_all()
    o = session.scalar(select(Olr).where(Olr.name == "Cape Town Winter Aces"))
    assert o.loft_id == 323 and o.enabled and [x.id for x in o.seasons] == [4001]


def test_nameless_entries_are_removed_and_ignored(session, client):
    from olr_scout.results.benzing import BenzingResultsSource
    from olr_scout.results.ingest import ingest_all, seed_registry

    session.add(Olr(name="", enabled=True))
    session.commit()
    seed_registry(session)
    session.commit()
    assert session.scalar(select(Olr).where(Olr.name == "")) is None
    session.add(Olr(name="   ", enabled=True, loft_id=None))
    session.commit()
    report = ingest_all(session, BenzingResultsSource(client, sleep=lambda s: None), keep=1)
    assert not any(e.startswith(":") or e.startswith("   :") for e in report["errors"])
