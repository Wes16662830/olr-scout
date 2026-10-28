from olr_scout.rings import RingIndex, ResultRing, find_rings, normalise, parse_ring


def test_normalise():
    assert normalise(" za-2026 port/7829 (c) ") == "ZA2026PORT7829C"


def test_best_pigeon_ring():
    r = parse_ring("ZA 2026 PORT 7829 (C)")
    assert (r.country, r.year, r.club, r.number, r.sex) == ("ZA", 2026, "PORT", "7829", "cock")


def test_elite_ring():
    r = parse_ring("9822 OERF", default_year=2026)
    assert (r.number_int, r.club, r.country, r.year) == (9822, "OERF", None, 2026)


def test_benzing_ring():
    r = parse_ring("BE-25-6087189")
    assert (r.country, r.year, r.number) == ("BE", 2025, "6087189")


def test_find_rings_in_prose():
    rings = find_rings("Sire BE 25-6087189 ace; dam NL 2022-1234567 x ZA 2019 PORT 112")
    assert {r.canonical for r in rings} == {"BE256087189", "NL221234567", "ZA19PORT112"}


def _index():
    return RingIndex([
        ResultRing(1, normalise("BE-25-6087189"), "BE-25-6087189"),
        ResultRing(2, normalise("ZA-26-OERF-9822"), "ZA-26-OERF-9822"),
        ResultRing(3, normalise("ZA-26-PORT-7829"), "ZA-26-PORT-7829"),
        ResultRing(4, normalise("ZA-26-GAUT-5000"), "ZA-26-GAUT-5000"),
        ResultRing(5, normalise("ZA-26-NWPU-5000"), "ZA-26-NWPU-5000"),
    ])


def test_match_order():
    idx = _index()
    assert idx.match("BE-25-6087189", []).confidence == "exact"
    # Same ring written differently (4-digit year) still counts as exact.
    m = idx.match("ZA 2026 PORT 7829 (C)", [])
    assert (m.bird_id, m.confidence) == (3, "exact")
    m = idx.match(None, ["Lot 4 BE256087189 stunning cock"])
    assert (m.bird_id, m.confidence) == (1, "contains")
    m = idx.match("9822 OERF", [], year=2026)
    assert (m.bird_id, m.confidence) == (2, "fuzzy")
    # Ambiguous fuzzy (two clubs share the number, no club given) → none + candidates
    m = idx.match("ZA 26 5000", [])
    assert m.confidence == "none" and m.candidates == [4, 5]
    assert idx.match("9822 OERF", [], year=2024).confidence == "none"
    assert idx.match("XX", [], override_bird_id=4).confidence == "manual"
