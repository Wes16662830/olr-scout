import math

import pytest
from sqlalchemy import func, select

from olr_scout.models import Bird, FamilyStat, Flight, Olr, Season, SourceHealth
from olr_scout.results.base import HealthError
from olr_scout.results.benzing import BenzingResultsSource
from olr_scout.results.ingest import discover_olrs, ingest_all, race_history
from olr_scout.results.nuxt import find_seasons, payload_from_html
from olr_scout.scoring.tier_a import (FlightIn, bid_score, family_key, season_metrics, shrunk_rate, spearman)

from . import synthetic


def test_nuxt_seasons():
    html = open(__file__.replace("test_results_and_scoring.py", "fixtures/benzing/loft-147.html")).read()
    seasons = find_seasons(payload_from_html(html))
    assert [(s["id"], s["year"]) for s in seasons] == [(2873, 2026), (2722, 2025)]


def test_percentiles_missing_race_counts_as_worst():
    flights = [FlightIn(1, 100), FlightIn(2, 200), FlightIn(3, 300, is_final=True)]
    field = {f"o{i}": i + 2 for i in range(8)}  # 8 other birds behind A and B
    res = {1: {"A": 1, "B": 2, **field}, 2: {"A": 2, "B": 1, **field}, 3: {"B": 1, **field}}
    m = season_metrics(flights, res, {"A", "B", "C", "D"} | set(field))
    assert m["A"].percentiles == {1: 0.1, 2: 0.2, 3: 1.0}  # missed the final → 1.0
    assert m["C"].long_score == 1.0
    assert m["B"].final_position == 1 and m["B"].final_percentile == pytest.approx(1 / 9)
    # 12 registered → ceil(5% × 12) = 1 ace: B (better long score)
    assert m["B"].is_ace and not m["A"].is_ace


def test_long_score_uses_top5_distances():
    dists = [50, 100, 383, 420, 480, 550, 601]
    flights = [FlightIn(i, d) for i, d in enumerate(dists, start=1)]
    others = {f"o{k}": k for k in range(1, 10)}
    # X wins the two short races and is 10th of 10 in the five long ones.
    res = {i: ({"X": 1, **{k: v + 1 for k, v in others.items()}} if i <= 2 else {**others, "X": 10})
           for i in range(1, 8)}
    m = season_metrics(flights, res)
    assert m["X"].long_score == pytest.approx(1.0)
    assert m["X"].all_score == pytest.approx((0.1 * 2 + 1.0 * 5) / 7)


def test_family_key_and_shrinkage():
    assert family_key("A & B") == family_key("B & A")
    assert family_key("Alpha Lofts I") == family_key("Alpha Lofts II") == "alpha lofts"
    assert family_key("Bravo & Charlie") == family_key("Charlie & Bravo (Single)")
    assert shrunk_rate(0, 0) == pytest.approx(0.05)
    assert shrunk_rate(5, 20) == pytest.approx((5 + 1) / 40)


def test_bid_score_weights_and_missing_components():
    full = bid_score(0.1, 0.8, 0.2, True, 0.2, [0.3], hard_score=0.25, arrival_rate=0.9, speed_pct=0.1)
    w = {"long": 40, "hard": 15, "consistency": 10, "final": 10, "family": 10, "sibling": 5, "reliability": 5, "speed": 5}
    parts = {"long": 0.9, "hard": 0.75, "consistency": 0.8, "final": 0.8, "family": 1.0, "sibling": 0.7,
             "reliability": 0.9, "speed": 0.9}
    assert full.score == pytest.approx(round(100 * sum(w[k] * parts[k] for k in w) / 100, 1))
    partial = bid_score(0.1, 0.8, None, False, None, None)
    assert set(partial.missing) == {"final", "family", "sibling", "hard", "reliability", "speed"}
    assert partial.score == pytest.approx(round(100 * (40 * 0.9 + 10 * 0.8) / 50, 1))


def test_own_long_hard_consistency_always_lead():
    from olr_scout.scoring.tier_a import CORE, CORE_MIN_SHARE

    cases = [
        bid_score(0.5, 0.5, None, False, 0.2, [0.1]),  # no hard-race data, no final: family+siblings would grow
        bid_score(0.5, 0.5, 0.5, True, 0.2, [0.1], weights={"family": 300, "sibling": 100}),  # extreme weights
        bid_score(0.5, 0.5, 0.5, True, 0.2, [0.1], hard_score=0.5, arrival_rate=1, speed_pct=0),
    ]
    for c in cases:
        core = sum(v for k, v in c.weights_used.items() if k in CORE)
        others = {k: v for k, v in c.weights_used.items() if k not in CORE}
        assert core >= CORE_MIN_SHARE - 1e-9
        assert c.weights_used["long"] > max(others.values())  # long-race placing is the single biggest part
        assert sum(c.weights_used.values()) == pytest.approx(1.0)


def test_settings_refuse_weights_that_break_the_rule(session):
    from olr_scout.scoring import preferences

    p = preferences.load(session)
    p["weights"] = {**p["weights"], "family": 200}
    with pytest.raises(ValueError, match="long \\+ hard \\+ consistency"):
        preferences.save(session, p)


def test_consistency_counts_long_and_hard_races_only():
    # Seven races; the bird wins the two short easy ones and is bottom half in the 5 long/hard ones.
    flights = [FlightIn(i, d, arrived=a, basketed=100, race_no=i)
               for i, (d, a) in enumerate([(50, 99), (60, 98), (250, 45), (300, 40), (400, 35), (500, 30), (600, 25)], 1)]
    res = {1: {"X": 1}, 2: {"X": 1}, 3: {"X": 30}, 4: {"X": 30}, 5: {"X": 30}, 6: {"X": 25}, 7: {"X": 20}}
    m = season_metrics(flights, res)["X"]
    assert m.consistency == 0.0  # short-race wins no longer count


def test_hard_races_survival_and_speed():
    flights = [FlightIn(1, 100, arrived=90, basketed=100, race_no=1), FlightIn(2, 200, arrived=50, basketed=100, race_no=2),
               FlightIn(3, 300, arrived=40, basketed=100, race_no=3), FlightIn(4, 400, arrived=20, basketed=100, race_no=4)]
    res = {1: {"A": 1, "B": 2}, 2: {"A": 2, "B": 1}, 3: {"A": 1}, 4: {}}
    speeds = {1: {"A": 1500.0, "B": 1490.0}, 2: {"A": 1300.0, "B": 1400.0}, 3: {"A": 1200.0}}
    m = season_metrics(flights, res, {"A", "B", "C"}, speeds=speeds)
    # Hardest three: race 4 (80% lost), 3 (60%), 2 (50%).
    assert m["A"].hard_score == pytest.approx((2 / 50 + 1 / 40 + 1.0) / 3)
    assert m["A"].arrival_rate == 0.75 and m["A"].lost_after == "R3"
    assert m["B"].lost_after == "R2" and m["C"].lost_after == "never"
    assert m["B"].speed_index > m["A"].speed_index  # B won race 2 by a margin, A only race 1/3
    assert m["B"].speed_pct == 0.0 and m["C"].speed_index is None


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_ingest_paginates_and_verifies_totals(session, client, web):
    web.results_page_size = 7  # force several pages per race
    import olr_scout.results.benzing as bz

    bz.PAGE_SIZE = 7
    try:
        src = BenzingResultsSource(client, sleep=lambda s: None)
        report = ingest_all(session, src, ["AfrikaPro"])
    finally:
        bz.PAGE_SIZE = 1000
    session.commit()
    s2026 = session.get(Season, 2873)
    assert s2026.registered == 40 and s2026.teams == 8
    races = session.scalars(select(Flight).where(Flight.season_id == 2873, Flight.is_training.is_(False))).all()
    assert len(races) == 6
    for f in races:
        assert f.ingested_rows == f.total_rows == len(synthetic.results()[f.id])
    assert not src.mismatches
    assert any(f.is_final for f in races)
    aces = session.scalar(select(func.count()).select_from(Bird).where(Bird.season_id == 2873, Bird.is_ace.is_(True)))
    assert aces == math.ceil(0.05 * 40)
    best = session.scalar(select(Bird).where(Bird.ring_norm == "ZA26100000"))
    assert best.is_ace and best.long_score < 0.1
    fam = session.scalar(select(FamilyStat).where(FamilyStat.family_key == "alpha lofts", FamilyStat.season_id.is_(None)))
    assert fam.entries == 10  # Alpha Lofts I + II grouped
    assert session.get(SourceHealth, "benzing").status == "ok"
    rec = race_history(session, "ZA26100000")
    assert rec.found and len(rec.races) == 6
    assert report["seasons"]


def test_results_mismatch_is_logged(session, client, web):
    import httpx

    web.add("https://oneloftrace.live/api/search/v1/public/flights/7101/results/final",
            httpx.Response(200, json={"data": [{"position": 1, "ringNumber": "ZA-26-100000"}], "total": 5}))
    src = BenzingResultsSource(client, sleep=lambda s: None)
    fr = src.flight_results(7101)
    assert not fr.complete and "got 1 rows, API total 5" in fr.note


def test_health_check_fails_loudly(client, web):
    import httpx

    web.add("https://oneloftrace.live/api/custom/v1/public/lofts", httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(HealthError):
        BenzingResultsSource(client).health_check()


def test_discover_olrs(session, client):
    added = discover_olrs(session, BenzingResultsSource(client))
    dino = session.scalar(select(Olr).where(Olr.name == "Dinokeng"))
    assert dino.loft_id == 300  # alias match fills the registry entry
    assert added == 1  # "Some Other OLR" added, disabled until the user enables it
    other = session.scalar(select(Olr).where(Olr.loft_id == 999))
    assert other.auto_discovered and not other.enabled


def test_ingest_reports_progress_and_saves_each_season(session, client):
    from olr_scout.results import ingest as ing

    ingest_all(session, BenzingResultsSource(client, sleep=lambda s: None), ["AfrikaPro"])
    assert ing.PROGRESS["running"] is False and ing.PROGRESS["phase"] == "done"
    assert ing.PROGRESS["seasons_done"] >= 1
    # Saved (committed) per season: a fresh session sees the birds.
    from olr_scout import db

    with db.SessionLocal() as other:
        assert other.scalar(select(func.count()).select_from(Bird)) == 40


def test_results_ignoring_page_number_does_not_loop(client, web):
    import httpx

    import olr_scout.results.benzing as bz

    same = {"data": [{"position": i, "ringNumber": f"ZA-26-{i}"} for i in range(1, 4)], "total": 999}
    web.add("https://oneloftrace.live/api/search/v1/public/flights/7101/results/final", httpx.Response(200, json=same))
    bz.PAGE_SIZE = 3
    try:
        src = BenzingResultsSource(client, sleep=lambda s: None)
        fr = src.flight_results(7101)
    finally:
        bz.PAGE_SIZE = 1000
    assert len(fr.rows) == 3 and not fr.complete
    assert any("got 3 rows, API total 999" in m for m in src.mismatches)


def test_live_flight_list_shape(client):
    """stopped_flights/running_flights with flight_type, as returned in Oct 2026."""
    fl = BenzingResultsSource(client).list_flights(2873)
    assert [f.name for f in fl][:2] == ["Training 1", "Race 1"]  # chronological
    assert fl[0].is_training and not fl[1].is_training
    assert fl[-1].is_final and fl[-1].distance_km == 600
    assert fl[1].arrived == len(synthetic.results()[7101])


def test_seasons_marked_ingested_without_birds_are_retried(session):
    from olr_scout.results.ingest import reset_empty_seasons
    from olr_scout.util.timeutil import now_utc

    season = session.get(Season, 2873)
    season.ingested_at = now_utc()
    session.flush()
    assert reset_empty_seasons(session) >= 1 and season.ingested_at is None


def test_registered_count_sets_the_ace_cut():
    flights = [FlightIn(1, 100)]
    m = season_metrics(flights, {1: {f"r{i}": i for i in range(1, 11)}}, registered_count=100)
    assert sum(b.is_ace for b in m.values()) == 5  # 5% of 100 registered, not of the 10 that arrived


def test_live_result_row_shape_and_page_cap(client, web):
    """Rows under all_flight_results, ring in pigeon.ring_description, position arrival_order;
    the server returns fewer rows per page than asked, so last_page drives paging."""
    src = BenzingResultsSource(client, sleep=lambda s: None)
    fr = src.flight_results(7101)
    expected = synthetic.results()[7101]
    assert fr.complete and len(fr.rows) == len(expected) > 15
    assert fr.rows[0].ring_raw == expected[0]["ringNumber"] and fr.rows[0].position == 1
    assert fr.rows[0].team == expected[0]["teamName"]


def test_nuxt2_season_list_from_live_page_snippet():
    from olr_scout.results.nuxt import seasons_from_nuxt2

    html = ('C.distance=d;C.id=2873;C.name="Season 2026";C.payment_info=b;'
            'seasons:[C,{agb:b,completed:c,distance:d,id:2722,name:"Season 2025",payment_info:b},'
            '{agb:b,completed:a,distance:d,id:2141,name:"Season 2024",payment_info:b}]')
    assert [(x["id"], x["year"]) for x in seasons_from_nuxt2(html)] == [(2873, 2026), (2722, 2025), (2141, 2024)]


def test_polish_ring_with_numeric_club():
    from olr_scout.rings import parse_ring

    r = parse_ring("PL-25-0400-3205")
    assert (r.country, r.year, r.club, r.number) == ("PL", 2025, "0400", "3205")


def test_lots_are_matched_as_each_season_arrives(session, client):
    from olr_scout.models import Lot

    from .helpers import make_lot

    lot = make_lot(session, 1, ring_raw="ZA 26 100000", current_bid=500)  # formatted like an auction site
    session.commit()
    ingest_all(session, BenzingResultsSource(client, sleep=lambda s: None), ["AfrikaPro"])
    session.refresh(lot)
    assert lot.tier == "A" and lot.match_confidence == "exact" and lot.score > 33


def test_ingest_finds_loft_id_for_registry_olrs(session, client):
    """Dinokeng is in the registry without a loft id; the ingest looks it up and reads its seasons."""
    report = ingest_all(session, BenzingResultsSource(client, sleep=lambda s: None), ["Dinokeng"])
    dino = session.scalar(select(Olr).where(Olr.name == "Dinokeng"))
    assert dino.loft_id == 300
    assert [x.id for x in dino.seasons] == [3001]
    assert any("no races flown yet" in x for x in report["skipped"])


def test_only_newest_seasons_are_downloaded(session, client, web):
    src = BenzingResultsSource(client, sleep=lambda s: None)

    def flight_lists():
        return sorted({c.split("/season/")[1].split("/")[0] for c in web.calls if "flightsAndTrainings" in c})

    ingest_all(session, src, ["AfrikaPro"], keep=1)
    assert flight_lists() == ["2873"]  # 2025, 2024, 2023, 2022 never requested
    web.calls.clear()
    ingest_all(session, src, ["AfrikaPro"], keep=1, only_missing=True)
    assert flight_lists() == []  # nothing missing within the newest season
    web.calls.clear()
    ingest_all(session, src, ["AfrikaPro"], keep=1)
    assert flight_lists() == ["2873"]  # the newest season is refreshed (may still be racing)


def test_season_without_races_does_not_use_up_the_limit(session, client, web):
    # 2873 has races; 2722..1049 have none in the test web. keep=2 → 2873 counted,
    # the empty ones are skipped and do not count, so the search goes further back.
    report = ingest_all(session, BenzingResultsSource(client, sleep=lambda s: None), ["AfrikaPro"], keep=2)
    assert len(report["seasons"]) == 1 and len(report["skipped"]) == 4
    s2722 = session.get(Season, 2722)
    assert s2722.no_races_checked_at is not None and s2722.ingested_at is None


def test_ingest_holds_no_database_lock_while_downloading(tmp_path, client):
    """Saving settings must work while a season downloads: the ingest may only write
    after all its network calls are done."""
    import sqlite3

    from olr_scout import db
    from olr_scout.results.ingest import seed_registry

    path = tmp_path / "lock.db"
    db.configure(f"sqlite:///{path}")
    db.init_db()
    s = db.SessionLocal()
    seed_registry(s)
    s.commit()
    src = BenzingResultsSource(client, sleep=lambda x: None)
    blocked = []
    original = src.flight_results

    def probe(fid):
        other = sqlite3.connect(path, timeout=0.2)
        try:
            other.execute("UPDATE preference SET key = key")  # needs the write lock
            other.commit()
        except sqlite3.OperationalError:
            blocked.append(fid)
        finally:
            other.close()
        return original(fid)

    src.flight_results = probe
    ingest_all(s, src, ["AfrikaPro"], keep=1)
    s.close()
    assert not blocked
    assert db.SessionLocal().query(Bird).count() == 40



def _live_like(web, fid, n, *, cap, wrong_last_page=False, page_works_up_to=None, next_links=False):
    """A results endpoint that misbehaves like the live one can."""
    import httpx
    from urllib.parse import parse_qs

    rows = [{"arrival_order": i, "pigeon": {"ring_description": f"ZA-26-{500000 + i}",
                                           "pigeon_team": {"name": "T"}}} for i in range(1, n + 1)]
    base = f"https://oneloftrace.live/api/search/v1/public/flights/{fid}/results/final"

    def h(req):
        q = parse_qs(req.url.query.decode())
        page = int(q.get("page", ["1"])[0])
        per = min(int(q.get("paginationPerPage", ["15"])[0]), cap)
        if page_works_up_to is not None and per > page_works_up_to:
            page = 1  # the page number is ignored for big pages
        if "cursor" in q:  # the site's own next-page links carry their position
            page = int(q["cursor"][0])
        chunk = rows[(page - 1) * per: page * per]
        last = 1 if wrong_last_page else max(1, -(-n // per))
        nxt = f"{base}?cursor={page + 1}&paginationPerPage={per}" if next_links and page * per < n else None
        return httpx.Response(200, json={"all_flight_results": {"current_page": page, "data": chunk, "per_page": per,
                                                                  "last_page": last, "total": n,
                                                                  "next_page_url": nxt}})

    web.add(base, h)


def test_capped_pages_with_wrong_last_page_still_complete(client, web):
    """Live symptom: 1,000 rows of 1,875 — the site capped the page and said it was the last."""
    import olr_scout.results.benzing as bz

    _live_like(web, 9001, 47, cap=20, wrong_last_page=True)
    bz.PAGE_SIZE = 25
    try:
        fr = BenzingResultsSource(client, sleep=lambda s: None).flight_results(9001)
    finally:
        bz.PAGE_SIZE = 1000
    assert fr.complete and len(fr.rows) == 47 and fr.rows[-1].position == 47


def test_falls_back_to_small_pages_when_page_numbers_are_ignored(client, web):
    import olr_scout.results.benzing as bz

    _live_like(web, 9002, 230, cap=150, page_works_up_to=100)
    bz.PAGE_SIZE = 150
    try:
        src = BenzingResultsSource(client, sleep=lambda s: None)
        fr = src.flight_results(9002)
    finally:
        bz.PAGE_SIZE = 1000
    assert fr.complete and len(fr.rows) == 230 and not src.mismatches


def test_follows_next_page_links_as_a_last_resort(client, web):
    import olr_scout.results.benzing as bz

    # Numbered pages never advance, but the site's own next-page links do.
    _live_like(web, 9003, 60, cap=40, page_works_up_to=0, next_links=True)
    bz.PAGE_SIZE = 40
    try:
        fr = BenzingResultsSource(client, sleep=lambda s: None).flight_results(9003)
    finally:
        bz.PAGE_SIZE = 1000
    assert len(fr.rows) == 60 and fr.complete
