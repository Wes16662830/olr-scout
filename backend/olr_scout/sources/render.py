"""Optional Playwright rendering for SPAs whose data API is unknown.

Respects the same politeness as the HTTP client: one page at a time, no
challenge solving. If a Cloudflare/Turnstile page is shown, ``SourceBlocked``.
"""

from __future__ import annotations

import json

from ..config import settings
from ..util.http import CHALLENGE_MARKERS, SourceBlocked, SourceUnavailable


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def render(url: str, wait_selector: str | None = None, capture_json: bool = True, timeout_ms: int = 25000) -> dict:
    """Render ``url``; return {"html": str, "json": [(url, data), ...]} of JSON XHR responses."""
    if not playwright_available():
        raise SourceUnavailable("Playwright is not installed (pip install playwright)")
    from playwright.sync_api import sync_playwright

    captured: list[tuple[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=settings.user_agent)

            def on_response(resp):
                if not capture_json:
                    return
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    try:
                        captured.append((resp.url, json.loads(resp.text())))
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass
            html = page.content()
        finally:
            browser.close()
    if any(m in html[:8000].lower() for m in CHALLENGE_MARKERS):
        raise SourceBlocked(f"{url}: bot challenge shown to the browser")
    return {"html": html, "json": captured}
