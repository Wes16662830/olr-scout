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
    # No club on the lot ring: never a loose match against rings that have one
    m = idx.match("ZA 26 5000", [])
    assert m.confidence == "none" and m.candidates == []
    assert idx.match("9822 OERF", [], year=2024).confidence == "none"
    assert idx.match("XX", [], override_bird_id=4).confidence == "manual"


def test_loose_match_needs_the_same_club_and_olr():
    """Live bug: lot ZA 22 CRU 173 was matched to another bird numbered 173."""
    idx = RingIndex([
        ResultRing(1, normalise("ZA-22-RVN-173"), "ZA-22-RVN-173"),   # same number, other club
        ResultRing(2, normalise("ZA-22-0173"), "ZA-22-0173"),         # no club at all
        ResultRing(3, normalise("ZA-21-CRU-173"), "ZA-21-CRU-173"),   # other year
    ])
    assert idx.match("ZA 22 CRU 173", []).bird_id is None
    idx = RingIndex([ResultRing(7, normalise("ZA-22-CRU-0173"), "ZA-22-CRU-0173")])
    assert idx.match("ZA 22 CRU 173", []).bird_id == 7  # same bird written with a leading zero → exact
    # Elite-style short ring: a loose match is allowed only among the lot's own OLR birds.
    assert idx.match("173 CRU", [], year=2022, fuzzy_allowed={7}).bird_id == 7
    assert idx.match("173 CRU", [], year=2022, fuzzy_allowed={9}).bird_id is None


def test_a_rejected_lookalike_does_not_hide_the_real_ring():
    # "LOT 74 - ZA 26" looks like a ring (LOT as a country) and used to swallow the real one.
    from olr_scout.rings import find_rings, parse_ring

    t = "Lot 74 - ZA 26-ABC-1234 Son of ZA 24-GPU-9161"
    assert [r.raw for r in find_rings(t)] == ["ZA 26-ABC-1234", "ZA 24-GPU-9161"]
    assert parse_ring(t).raw == "ZA 26-ABC-1234"


def test_own_ring_skips_relatives_and_pairings():
    from olr_scout.scoring.pedigree import own_ring

    def own(t):
        r = own_ring(t)
        return r.raw if r else None

    assert own("Lot 74 - ZA 26-ABC-1234 Son of ZA 24-GPU-9161") == "ZA 26-ABC-1234"
    assert own("Son of ZA 24-GPU-9161 - ZA 26-ABC-1234") == "ZA 26-ABC-1234"
    assert own("Lot 75 Son of ZA 24-GPU-9161") is None
    assert own("Lot 76 Full sister to ZA 24-GPU-9161") is None
    assert own("Nestmate of ZA 24-GPU-9161") is None
    assert own("ZA 24-GPU-9161 x ZA 23-CRU-1111") is None  # a pairing: the parents
    assert own("Lot 9 ZA 2026 PORT 7829 (C)") == "ZA 2026 PORT 7829"


def test_first_ring_wins_and_sa_is_za():
    """Lot 74 (AfrikaPro Auction 4): own ring SA-26-1146, title also names ZA 24-GPU-9161."""
    from olr_scout.rings import ResultRing, RingIndex, parse_ring
    from olr_scout.scoring.pedigree import own_ring

    title = "Lot 74 SA-26-1146 son of ZA 24-GPU-9161"
    assert parse_ring(title).raw == "SA-26-1146"  # the fuller-looking ring later on no longer wins
    assert own_ring(title).raw == "SA-26-1146"
    assert parse_ring("SA-26-1146").canonical == parse_ring("ZA-26-1146").canonical
    idx = RingIndex([ResultRing(1, "ZA261146", "ZA-26-1146")])
    assert idx.match("SA-26-1146", []).bird_id == 1


def test_ring_formats_seen_in_afrikapro_2026_results():
    from olr_scout.rings import parse_ring

    same = {
        "BULGARIA-25-60582": "BG-25-60582", "QATAR-26-2112": "QA-26-2112", "MAROC-25-81608": "MA-25-81608",
        "HUNG-25-01-24670": "HU-25-01-24670", "SLOVENIJA-25-107-5764": "SI-25-107-5764",
        "ZA-25-CRU DERBY-3175": "ZA 25 CRUDERBY 3175", "GB-A-25-79641": "GB-25-A-79641",
        "(ZA)-(26)-TURFPET-12622": "ZA-26-TURFPET-12622", "ZA-25-SFM-5": "ZA 2025 SFM 5",
    }
    for a, b in same.items():
        assert parse_ring(a) is not None and parse_ring(a).canonical == parse_ring(b).canonical, a
    assert parse_ring("flew at 25 km 300 today") is None  # prose is not a ring


def test_title_bird_first_sire_second():
    from olr_scout.scoring.pedigree import own_ring, title_parents

    t = "Lot 16 BULGARIA-25-60582 Unpredictable Valya ZA21 ABL 344"
    assert own_ring(t).raw == "BULGARIA-25-60582" and title_parents(t) == {"ZA21ABL344": "sire"}
    assert title_parents("Lot 74 SA-26-1146 son of ZA 24-GPU-9161") == {"ZA24GPU9161": "sire"}
    assert title_parents("Lot 9 ZA-26-ABC-1234 ZA-23-PORT-111 x ZA-22-PORT-222") == {
        "ZA23PORT111": "sire", "ZA22PORT222": "dam"}
    assert title_parents("Lot 3 ZA-26-ABC-1234 full brother to ZA-24-GPU-9161") == {}  # a sibling, not the sire


def test_auction_4_titles_live():
    """AfrikaPro Auction 4 titles that were unreadable: a team named 'Brothers' read as a
    sibling, and clubs with a slash or two parts."""
    from olr_scout.scoring.pedigree import own_ring

    assert own_ring("LOT 18 AFRIKAPRO AUCTION 4-Alpdağ Brothers-TR-25-34-10366 -SIRE: TR-23-36219").raw == "TR-25-34-10366"
    assert own_ring("LOT 121 AFRIKAPRO AUCTION 4-P & C Loft-ZA-25-EC/DRPC-837 —45TH FINAL").raw == "ZA-25-EC/DRPC-837"
    assert own_ring("LOT 73 AFRIKAPRO AUCTION 4-Mazepa-PL-25-FC-ZP-1050689 -Sire · PL-FC-ZP-22-1050737").raw == "PL-25-FC-ZP-1050689"
    assert own_ring("Lot 76 Full sister to ZA 24-GPU-9161") is None
