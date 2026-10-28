"""Spec §11 acceptance tests that need REAL recorded data.

They skip until `scripts/record_fixtures.py` has been run from a machine that can
reach the sites (the build environment could not). Expected values are from
the build brief.
"""

import json
from pathlib import Path

import pytest

REC = Path(__file__).parent / "fixtures" / "recorded"


def need(*parts):
    p = REC.joinpath(*parts)
    if not p.exists():
        pytest.skip(f"recorded fixture missing: {p.relative_to(REC.parent)} (run scripts/record_fixtures.py)")
    return p


def test_afrikapro_auction_1_totals():
    data = json.loads(need("toppigeon", "afrikapro-auction-1-summary.json").read_text())
    assert data["lots"] == 175 and data["sold"] == 174
    assert data["total_zar"] == 2_622_500 and data["buyers"] == 91


def test_afrikapro_auction_1_long_scores():
    data = json.loads(need("benzing", "afrikapro-auction-1-long-scores.json").read_text())
    assert data["163"] == pytest.approx(0.091, abs=0.002)
    assert data["169"] == pytest.approx(0.107, abs=0.002)


def test_afrikapro_2026_season_counts():
    data = json.loads(need("benzing", "season-2873-summary.json").read_text())
    assert data["teams"] == 261 and data["registered"] == 3135
    assert data["race_10_arrivals"] == 1037 and data["race_10_winner"] == "BE-25-6087189"


def test_afrikapro_auction_2_matching():
    data = json.loads(need("toppigeon", "afrikapro-auction-2-matching.json").read_text())
    assert data["matched"] == 175 and data["total"] == 175
    assert sorted(data["fuzzy_lots"]) == [39, 127, 150, 173]
