"""Read pedigree images and PDFs in the background and turn the ancestor rings in
them into claims. A claim only counts once its ring is found in OLR results;
the text itself ("1st Ace", "super breeder") is never scored."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ocr
from .models import AncestorClaim, Lot
from .scoring import engine
from .scoring.pedigree import extract_claims
from .util.http import PoliteClient, SourceBlocked
from .util.timeutil import now_utc

log = logging.getLogger(__name__)
PER_RUN = 15


def _is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf")


def pending(s: Session, can_ocr: bool, limit: int = PER_RUN) -> list[Lot]:
    lots = s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")), Lot.pedigree_url.is_not(None))
                     .order_by(Lot.ends_at.is_(None), Lot.ends_at)).all()
    out = []
    for lot in lots:
        done = (lot.extra or {}).get("ped_read")
        if done and not done.get("retry"):
            continue
        if not can_ocr and not _is_pdf(lot.pedigree_url):
            continue  # an image, and no Tesseract: don't download it for nothing
        out.append(lot)
        if len(out) >= limit:
            break
    return out


_OCR_DIGIT = {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8", "Z": "2"}


def clean_ocr(text: str) -> str:
    """Fix letters OCR puts inside numbers (1O1 → 101, 12l5 → 1215). Only a letter with a
    digit on both sides is changed, so club codes and names are left alone."""
    import re

    return re.sub(r"(?<=\d)[OoQDIl|SBZ](?=\d)", lambda m: _OCR_DIGIT[m.group(0)], text)


def store(s: Session, lot: Lot, text: str | None, origin: str | None, error: str | None) -> int:
    added = 0
    if text and origin == "ocr":
        text = clean_ocr(text)
    if text:
        have = {c.ring_norm for c in s.scalars(select(AncestorClaim).where(AncestorClaim.lot_id == lot.id))}
        for c in extract_claims(text, origin=origin or "ocr", own_ring=lot.ring_raw):
            if c.ring_norm in have:
                continue
            s.add(AncestorClaim(lot_id=lot.id, relation=c.relation, ring_raw=c.ring_raw, ring_norm=c.ring_norm,
                                name=c.name, claim_text=c.text, origin=origin or "ocr", claims_ace=c.claims_ace))
            have.add(c.ring_norm)
            added += 1
    lot.extra = {**(lot.extra or {}),
                 "ped_read": {"at": now_utc().isoformat(), "origin": origin, "rings": added, "error": error,
                              "retry": bool(error and "not installed" in error)},
                 **({"ocr_text": text[:20000]} if text else {})}
    return added


def read_pending(s: Session, client: PoliteClient, limit: int = PER_RUN) -> dict:
    can_ocr = ocr.ocr_available()
    jobs = [(lot.id, lot.pedigree_url) for lot in pending(s, can_ocr, limit)]
    s.commit()  # no database lock while downloading
    fetched = []
    for lot_id, url in jobs:
        try:
            text, origin = ocr.text_from_url(client, url)
            fetched.append((lot_id, text, origin, None))
        except SourceBlocked as exc:
            log.warning("pedigree download blocked: %s", exc)
            break
        except Exception as exc:
            fetched.append((lot_id, None, None, str(exc)[:200]))
    changed, rings = [], 0
    for lot_id, text, origin, error in fetched:
        lot = s.get(Lot, lot_id)
        if lot is None:
            continue
        rings += store(s, lot, text, origin, error)
        changed.append(lot)
    s.flush()
    if changed:
        engine.score_all(s, changed)
    s.commit()
    return {"read": len(changed), "rings": rings, "ocr": can_ocr}


def status(s: Session) -> dict:
    lots = s.scalars(select(Lot).where(Lot.status.in_(("live", "upcoming")), Lot.pedigree_url.is_not(None))).all()
    read = [l for l in lots if (l.extra or {}).get("ped_read") and not (l.extra or {})["ped_read"].get("error")]
    failed = [l for l in lots if ((l.extra or {}).get("ped_read") or {}).get("error")]
    return {**ocr.ocr_status(), "with_pedigree": len(lots), "read": len(read), "failed": len(failed),
            "waiting": len(lots) - len(read) - len(failed),
            "rings_found": sum(((l.extra or {}).get("ped_read") or {}).get("rings", 0) for l in read)}
