"""AfriPigeon (afripigeon.com) — React SPA with a JSON API.

Known: ``GET /api/auctions/active``, ``/api/auctions/upcoming`` and
``/api/auctions/{id}``. The lot-listing endpoint is NOT known
(``/api/auctions/{id}/lots``, ``/api/lots?auctionId=`` and ``/items`` returned
404/errors when checked). Discovery, in order:

1. Read ``/static/js/main.*.js`` and collect ``/api/...`` paths that mention
   lots; try each with the auction id substituted.
2. If none returns a lot list, render the auction page with Playwright and use
   any lot-shaped JSON the page fetches, else scrape the rendered DOM.

The working endpoint is remembered for the process and reported on the
Sources screen so it can be recorded in docs/sources.md.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..util.http import SourceUnavailable
from ..util.timeutil import parse_local_datetime
from .base import Auction, AuctionSource, Lot, clean_text, tag_olr
from .genericjson import first, json_to_lot, looks_like_lot_list
from .render import playwright_available, render
from .woo import soup

_MAIN_JS = re.compile(r"""/static/js/main\.[a-z0-9]+\.js""")
_API_PATH = re.compile(r"""["'`](/api/[A-Za-z0-9_\-/{}$:?=&.]*lot[A-Za-z0-9_\-/{}$:?=&.]*)["'`]""", re.I)
TRIED_AND_FAILED = ["/api/auctions/{id}/lots", "/api/lots?auctionId={id}", "/api/auctions/{id}/items"]


def candidate_endpoints(bundle_js: str) -> list[str]:
    out = []
    for m in _API_PATH.finditer(bundle_js):
        path = m.group(1)
        # Template literal pieces: `/api/auction-lots/${id}` → {id}
        path = re.sub(r"\$\{[^}]*\}|:[A-Za-z_]+", "{id}", path)
        if path.endswith("/") or path.endswith("="):
            path += "{id}"
        if path not in out:
            out.append(path)
    # Paths already shown not to work go last.
    return sorted(out, key=lambda p: p in TRIED_AND_FAILED)


class AfriPigeonSource(AuctionSource):
    key = "afripigeon"
    name = "AfriPigeon"
    base_url = "https://afripigeon.com"
    verified = False

    def __init__(self, client):
        super().__init__(client)
        self.lot_endpoint: str | None = None  # discovered template, e.g. "/api/xyz/{id}"
        self.discovery_log: list[str] = []

    def _auction_list(self, path: str, status: str) -> list[Auction]:
        data = self.client.get_json(self.base_url + path)
        rows = data if isinstance(data, list) else first(data, "auctions", "data", default=[]) or []
        out = []
        for r in rows:
            aid = str(first(r, "id", "auction_id"))
            name = clean_text(first(r, "auction_name", "name", default=f"Auction {aid}")) or aid
            olr, year = tag_olr(name)
            fc = parse_local_datetime(f"{r.get('first_lot_end_date', '')} {r.get('first_lot_end_time', '')}")
            out.append(Auction(self.key, aid, name, url=f"{self.base_url}/auctions/{aid}",
                               seller=first(r, "seller_name", "seller"), status=status,
                               lot_count=first(r, "lot_count", "lots_count"), first_close=fc,
                               olr_tag=olr, olr_year=year, extra={"raw": r}))
        return out

    def fetch_active(self) -> list[Auction]:
        auctions = self._auction_list("/api/auctions/active", "live")
        try:
            auctions += self._auction_list("/api/auctions/upcoming", "upcoming")
        except SourceUnavailable:
            pass
        return auctions

    # ----------------------------------------------------------- discovery
    def discover_lot_endpoint(self, auction_id: str) -> str | None:
        html = self.client.get_text(self.base_url + "/auctions")
        m = _MAIN_JS.search(html)
        if not m:
            self.discovery_log.append("main.*.js not referenced from /auctions")
            return None
        js = self.client.get_text(urljoin(self.base_url, m.group(0)))
        for tmpl in candidate_endpoints(js):
            if "{id}" not in tmpl:
                continue
            url = self.base_url + tmpl.format(id=auction_id)
            resp = self.client.get(url)
            ok = resp.status_code == 200 and "json" in resp.headers.get("content-type", "")
            self.discovery_log.append(f"{tmpl} → HTTP {resp.status_code}")
            if ok and looks_like_lot_list(resp.json()) is not None:
                self.lot_endpoint = tmpl
                return tmpl
        return None

    def fetch_lots(self, auction: Auction) -> list[Lot]:
        if self.lot_endpoint is None:
            self.discover_lot_endpoint(auction.auction_id)
        if self.lot_endpoint:
            data = self.client.get_json(self.base_url + self.lot_endpoint.format(id=auction.auction_id))
            rows = looks_like_lot_list(data) or []
            return [self._to_lot(r, auction) for r in rows]
        # Fallback: render the auction page.
        if not playwright_available():
            raise SourceUnavailable(
                "AfriPigeon lot endpoint not found in the JS bundle and Playwright is not installed; "
                "see docs/sources.md §AfriPigeon"
            )
        page = render(auction.url or f"{self.base_url}/auctions/{auction.auction_id}")
        for url, data in page["json"]:
            rows = looks_like_lot_list(data)
            if rows:
                path = url.replace(self.base_url, "")
                self.discovery_log.append(f"lot JSON seen while rendering: {path}")
                if auction.auction_id in path:
                    self.lot_endpoint = path.replace(auction.auction_id, "{id}")
                return [self._to_lot(r, auction) for r in rows]
        return self._from_dom(page["html"], auction)

    def _to_lot(self, r: dict, auction: Auction) -> Lot:
        lot = json_to_lot(r, self.key, auction.auction_id, auction.name, auction.url or self.base_url, auction.seller)
        lot.olr_tag, lot.olr_year = auction.olr_tag, auction.olr_year
        if r.get("id"):
            lot.url = f"{self.base_url}/auctions/{auction.auction_id}"
        return lot

    def _from_dom(self, html: str, auction: Auction) -> list[Lot]:
        s = soup(html)
        lots = []
        for card in s.select("[class*=lot-card], [class*=LotCard], [data-lot-id]"):
            text = card.get_text("\n", strip=True)
            lots.append(json_to_lot({"title": text.split("\n")[0], "description": text,
                                     "id": card.get("data-lot-id") or text[:60]},
                                    self.key, auction.auction_id, auction.name, auction.url or self.base_url, auction.seller))
        return lots
