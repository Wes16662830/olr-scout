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
