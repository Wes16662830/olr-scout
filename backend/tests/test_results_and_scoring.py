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
    full = bid_score(0.1, 0.8, 0.2, True, 0.2, [0.3])
    expected = 100 * (0.5 * 0.9 + 0.15 * 0.8 + 0.10 * 0.8 + 0.20 * 1.0 + 0.05 * 0.7)
    assert full.score == pytest.approx(round(expected, 1))
    partial = bid_score(0.1, 0.8, None, False, None, None)
    assert set(partial.missing) == {"final", "family", "sibling"}
    assert partial.score == pytest.approx(round(100 * (50 * 0.9 + 15 * 0.8) / 65, 1))


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
    assert any("repeated" in m for m in src.mismatches)


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
