"""Pedigree image OCR (Tesseract) and PDF text. Output is shown to the user to confirm."""

from __future__ import annotations

import io

from .util.http import PoliteClient


WINDOWS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _configure_tesseract() -> None:
    """Tesseract's Windows installer does not add itself to PATH: look in its usual folders."""
    import os

    try:
        import pytesseract
    except ImportError:
        return
    local = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")
    for path in [*WINDOWS_TESSERACT, local]:
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return


def ocr_available() -> bool:
    try:
        import pytesseract

        _configure_tesseract()
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_status() -> dict:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return {"ocr": False, "message": "Python OCR package missing — run update-windows, then start-windows."}
    if ocr_available():
        return {"ocr": True, "message": "Tesseract found — pedigree images are read automatically."}
    return {"ocr": False, "message": "Tesseract is not installed, so pedigree images cannot be read (PDF pedigrees still "
                                     "are). Install it from https://github.com/UB-Mannheim/tesseract/wiki (Windows)."}


def _prepare(img):
    """Greyscale, enlarge small scans and boost contrast: ring numbers read far better."""
    from PIL import ImageOps

    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 1600:
        f = 1600 / img.width
        img = img.resize((int(img.width * f), int(img.height * f)))
    return ImageOps.autocontrast(img)


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

    img = _prepare(Image.open(io.BytesIO(data)))
    return pytesseract.image_to_string(img, lang="eng", config="--psm 11"), "ocr"
