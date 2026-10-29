"""Background pedigree reading. OCR itself is replaced by a stub (no Tesseract in CI)."""

from olr_scout import ocr, pedigree_reader
from olr_scout.models import AncestorClaim

from .helpers import make_lot, make_season

TOP = [1, 2, 1, 3, 2, 1]


def _stub(monkeypatch, texts, can_ocr=True):
    calls = []

    def fake(client, url):
        calls.append(url)
        return texts[url], ("pdf" if url.endswith(".pdf") else "ocr")

    monkeypatch.setattr(ocr, "text_from_url", fake)
    monkeypatch.setattr(ocr, "ocr_available", lambda: can_ocr)
    return calls


def test_pedigree_rings_found_in_results_give_a_breeding_score(session, client, monkeypatch):
    make_season(session, "AfrikaPro", 2024, {"ZA-23-SIRE-101": ("Old Lofts", TOP)}, pad=40)
    lot = make_lot(session, 1, ring_raw="ZA-26-YOUNG-707", current_bid=900,
                   pedigree_url="https://x.co/ped-707.jpg")
    other = make_lot(session, 2, ring_raw="ZA-26-YOUNG-708", current_bid=900,
                     pedigree_url="https://x.co/ped-708.jpg")
    session.commit()
    _stub(monkeypatch, {
        # A pedigree chart as OCR returns it: rings with notes, no "Sire:" labels.
        "https://x.co/ped-707.jpg": "ZA-26-YOUNG-707 Blue cock\nZA-23-SIRE-101 1st AfrikaPro Ace\nNL-20-1234567 Golden Pair",
        # Only home-loft ancestors: claims, never a score.
        "https://x.co/ped-708.jpg": "ZA-26-YOUNG-708\nNL-19-7654321 1st National Ace\nBE-18-1111111 super breeder",
    })
    report = pedigree_reader.read_pending(session, client)
    assert report["read"] == 2
    rings = {c.ring_norm for c in session.query(AncestorClaim).filter_by(lot_id=lot.id)}
    assert "ZA23SIRE101" in rings and "ZA26YOUNG707" not in rings  # own ring is not an ancestor
    assert lot.breeding_score is not None
    b = lot.score_detail["breeding"]
    assert b["ancestors_verified"] == 1 and b["pedigree"]["read_from"] == "ocr"
    assert other.breeding_score is None  # "1st National Ace" text is never scored
    assert other.score_detail["breeding"]["pedigree"]["claimed_aces"] >= 1
    # Read once: the next run downloads nothing.
    assert pedigree_reader.read_pending(session, client)["read"] == 0


def test_images_wait_for_tesseract_but_pdfs_are_read(session, client, monkeypatch):
    img = make_lot(session, 1, ring_raw="ZA-26-AAA-101", pedigree_url="https://x.co/a.jpg")
    pdf = make_lot(session, 2, ring_raw="ZA-26-BBB-102", pedigree_url="https://x.co/b.pdf")
    session.commit()
    calls = _stub(monkeypatch, {"https://x.co/b.pdf": "Sire: ZA-24-CCC-103"}, can_ocr=False)
    pedigree_reader.read_pending(session, client)
    assert calls == ["https://x.co/b.pdf"]  # the image is not downloaded for nothing
    assert "ped_read" not in (img.extra or {}) and pdf.extra["ped_read"]["origin"] == "pdf"
    st = pedigree_reader.status(session)
    assert st["ocr"] is False and st["read"] == 1 and st["waiting"] == 1


def test_ocr_digit_cleanup():
    from olr_scout.pedigree_reader import clean_ocr

    assert clean_ocr("ZA-23-SIRE-1O1 and 12l5") == "ZA-23-SIRE-101 and 1215"
    assert clean_ocr("PORT DOVE Boss") == "PORT DOVE Boss"  # letters between letters untouched


def test_pedigree_chart_cannot_give_two_sires_or_four_dams(session, client, monkeypatch):
    """Lot 6 (AfrikaPro): every "Sire"/"Dam" on a chart labelled the next ring, so the card showed
    2 sires and 4 dams. The listing's own Sire: wins; an ambiguous document gives no dam at all."""
    from olr_scout import serialize

    make_season(session, "AfrikaPro", 2023, {"ZA-22-MOUN-6640": ("Moun Lofts", TOP)}, pad=40)
    lot = make_lot(session, 6, ring_raw="ZA-25-PORT-6006", year=2025, description="Sire: ZA-23-PORT-1111",
                   pedigree_url="https://x.co/ped-6.pdf")
    session.commit()
    _stub(monkeypatch, {"https://x.co/ped-6.pdf": "\n".join([
        "Sire ZA-23-PORT-1111 Bred by Old Lofts",
        "Sire ZA-20-PORT-2222 sire of 1st Ace AfrikaPro 2022",
        "Dam ZA-22-MOUN-6640 Janssen hen",
        "Dam ZA-19-PORT-3333 Janssen x Van Loon",
        "Dam ZA-18-PORT-4444",
        "Dam ZA-17-PORT-5555 1st National Ace",
        "Nest mate ZA-25-PORT-6007",
    ])})
    pedigree_reader.read_pending(session, client)
    rel = {c.ring_norm: c.relation for c in session.query(AncestorClaim).filter_by(lot_id=lot.id)}
    assert [r for r, v in rel.items() if v == "sire"] == ["ZA23PORT1111"]  # the listing's sire
    assert not [r for r, v in rel.items() if v == "dam"]  # four candidates: none is "the" dam
    assert rel["ZA22MOUN6640"] == "ancestor" and rel["ZA25PORT6007"] == "related"
    b = lot.score_detail["breeding"]
    assert b["parents_verified"] == 0 and b["ancestors_verified"] == 1  # MOUN 664 counts at low weight only
    lin = serialize.parents(session, lot, {"families": [{"name": "Janssen", "aliases": []}]})
    assert [p["relation"] for p in lin["parents"]] == ["sire"]
    assert lin["families"] == [{"name": "Janssen", "count": 2, "where": "pedigree"}]
    notes = [h["note"] for h in lin["highlights"]]
    assert "sire of 1st Ace AfrikaPro 2022" in notes and lin["highlights"][0]["ring"] == "ZA-22-MOUN-6640"


def test_single_parents_from_a_document_are_kept():
    from olr_scout.scoring.pedigree import Claim, settle_relations

    cs = [Claim("sire", "ZA-23-AAA-1001", "ZA23AAA1001", None, "", False, "pdf"),
          Claim("dam", "ZA-23-AAA-1002", "ZA23AAA1002", None, "", False, "pdf"),
          Claim("parent", "ZA-22-AAA-1003", "ZA22AAA1003", None, "", False, "text")]
    settle_relations(cs, 2025)
    assert [c.relation for c in cs] == ["sire", "dam", "ancestor"]  # no third parent
