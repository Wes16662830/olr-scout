"""Pedigree image OCR (Tesseract) and PDF text. Output is shown to the user to confirm."""

from __future__ import annotations

import io

from .util.http import PoliteClient


def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def text_from_url(client: PoliteClient, url: str) -> tuple[str, str]:
    """Return (text, origin) where origin is 'pdf' or 'ocr'."""
    resp = client.get(url, use_cache=False)  # throttled like every other request
    if resp.status_code >= 400:
        raise RuntimeError(f"pedigree download failed: HTTP {resp.status_code}")
    data = resp.content
    ctype = resp.headers.get("content-type", "")
    if url.lower().endswith(".pdf") or "pdf" in ctype:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is not installed (pip install pypdf)") from exc
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        if text.strip():
            return text, "pdf"
        raise RuntimeError("PDF has no text layer; save the page as an image and OCR it")
    if not ocr_available():
        raise RuntimeError("Tesseract OCR is not installed (apt install tesseract-ocr; pip install pytesseract pillow)")
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(img, lang="eng"), "ocr"
