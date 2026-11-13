"""What-if standings over chosen races (Rankings screen)."""

from olr_scout.models import Bird, BirdResult, Flight, Olr, Season
from olr_scout.scenario import standings
from olr_scout.scoring import engine, preferences
from olr_scout.util.timeutil import now_utc

from .helpers import make_lot


def _season(session):
    olr = session.query(Olr).filter_by(name="AfrikaPro").one()
    se = Season(id=9001, olr_id=olr.id, year=2026, ingested_at=now_utc(), registered=3)
    session.add(se)
    for no in (1, 2, 3):  # 100 km each; race 3 is the final
        session.add(Flight(id=9100 + no, season_id=se.id, name=f"Race {no}", race_no=no, distance_km=100,
                           arrived=3, basketed=3, is_final=(no == 3), is_training=False))
    # speeds in m/min per race (None = not home)
    birds = {"ZA-25-AAA-1": (1000, 1000, 400),   # fast until a slow final (400 counts as 500)
             "ZA-25-BBB-2": (900, 900, 1000),    # steady, wins the final
             "ZA-25-CCC-3": (1250, 1250, None)}  # fastest early, lost in the final
    for i, (ring, sp) in enumerate(birds.items(), 1):
        b = Bird(season_id=se.id, ring_norm=ring.replace("-", ""), ring_raw=ring, team=f"T{i}")
        session.add(b)
        session.flush()
        for no, v in zip((1, 2, 3), sp):
            if v:
                session.add(BirdResult(bird_id=b.id, flight_id=9100 + no, position=1, speed=v, result_pct=0.5))
    session.flush()
    return se


def test_total_time_follows_jacket_rules_and_races_can_be_left_out(session):
    _season(session)
    full = standings(session, 9001, [1, 2, 3])
    # CCC missed the final: not ranked. AAA: 100+100+200 (400 m/min counts as 500) = 400 min; BBB ≈ 322 min.
    assert [r["ring"] for r in full["rows"]] == ["ZA-25-BBB-2", "ZA-25-AAA-1"]
    assert full["rows"][1]["value"] == 400.0
    before_final = standings(session, 9001, [1, 2])
    assert [r["ring"] for r in before_final["rows"]] == ["ZA-25-CCC-3", "ZA-25-AAA-1", "ZA-25-BBB-2"]
    assert [r["ring"] for r in standings(session, 9001, [3])["rows"]][0] == "ZA-25-BBB-2"


def test_birds_on_auction_and_suggestions_in_scenario_order(session):
    _season(session)
    for no, ring in ((5, "ZA-25-AAA-1"), (6, "ZA-25-CCC-3")):
        make_lot(session, no, lot_key=f"s{no}", ring_raw=ring, olr_tag="AfrikaPro", current_bid=1000)
    engine.score_all(session)
    st = standings(session, 9001, [1, 2], on_auction_only=True)
    assert [(r["ring"], [l["lot_no"] for l in r["lots"]]) for r in st["rows"]] == [("ZA-25-CCC-3", [6]), ("ZA-25-AAA-1", [5])]
    p = {**preferences.load(session), "rank_by": "scenario", "scenario": {"season_id": 9001, "races": [1, 2, 3]}}
    # Over all three races CCC (lost in the final) is unranked, so lot 5 leads.
    assert [x["lot"].lot_no for x in engine.suggestions(session, p)][:2] == [5, 6]
    p["scenario"]["races"] = [1, 2]
    assert [x["lot"].lot_no for x in engine.suggestions(session, p)][:2] == [6, 5]
