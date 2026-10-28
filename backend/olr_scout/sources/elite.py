"""Elite Pigeon Auctions (elitepigeonauctions.co.za) — React SPA on Supabase REST.

The public anon key ships in the site's JS bundle. It is read from the bundle at
runtime (never hard-coded) and re-read if a request is refused, in case it rotated.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..rings import find_rings, normalise, parse_ring
from ..util.http import SourceBlocked, SourceUnavailable
from ..util.money import parse_zar
from ..util.timeutil import parse_iso
from .base import Auction, AuctionSource, Lot, clean_text, parse_sex, tag_olr

SUPABASE_DEFAULT = "https://amsnfjkefytwxipkqzev.supabase.co"
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_SUPA = re.compile(r"https://[a-z0-9]{10,40}\.supabase\.co")
_SCRIPT = re.compile(r"""<script[^>]+src=["']([^"']+\.js)["']""", re.I)


def extract_supabase_config(bundle_js: str) -> tuple[str | None, str | None]:
    url = None
    m = _SUPA.search(bundle_js)
    if m:
        url = m.group(0)
    key = None
    # Prefer a JWT whose payload says role "anon".
    import base64
    import json

    for cand in _JWT.findall(bundle_js):
        try:
            payload = cand.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            continue
        if data.get("role") == "anon":
            key = cand
            break
    if key is None:
        m2 = re.search(r"""(sb_publishable_[A-Za-z0-9_-]{20,})""", bundle_js)
        if m2:
            key = m2.group(1)
    return url, key


class EliteSource(AuctionSource):
    key = "elite"
    name = "Elite Pigeon Auctions"
    base_url = "https://elitepigeonauctions.co.za"
    site_lot_url = "https://elitepigeonauctions.co.za/auctions"
    lot_url_template = "https://elitepigeonauctions.co.za/auctions"
    verified = False  # endpoint + anon key confirmed from a browser, not from this server

    def __init__(self, client):
        super().__init__(client)
        self._supabase_url: str | None = None
        self._anon_key: str | None = None
        self._lofts: dict[str, dict] = {}

    # ---------------------------------------------------------------- key discovery
    def _discover_key(self) -> None:
        html = self.client.get_text(self.base_url + "/auctions", use_cache=False)
        scripts = [urljoin(self.base_url, s) for s in _SCRIPT.findall(html)]
        url = key = None
        for js_url in scripts[:8]:
            js = self.client.get_text(js_url)
            u, k = extract_supabase_config(js)
            url = url or u
            key = key or k
            if key:
                break
        if not key:
            raise SourceUnavailable("Elite: Supabase anon key not found in the JS bundle (site changed?)")
        self._supabase_url = url or SUPABASE_DEFAULT
        self._anon_key = key

    def _rest(self, path: str, params: dict) -> list[dict]:
        for attempt in range(2):
            if not self._anon_key:
                self._discover_key()
            headers = {"apikey": self._anon_key, "Authorization": f"Bearer {self._anon_key}", "Accept": "application/json"}
            try:
                resp = self.client.get(f"{self._supabase_url}/rest/v1/{path}", params=params, headers=headers, use_cache=False)
            except SourceBlocked:
                if attempt == 0:
                    self._anon_key = None  # key may have rotated; re-read the bundle once
                    continue
                raise
            if resp.status_code in (401, 403) and attempt == 0:
                self._anon_key = None
                continue
            if resp.status_code >= 400:
                raise SourceUnavailable(f"Elite REST {path}: HTTP {resp.status_code}")
            return resp.json()
        raise SourceBlocked("Elite: anon key refused after re-reading the bundle")

    # ---------------------------------------------------------------- interface
    def fetch_active(self) -> list[Auction]:
        lofts = self._rest("lofts", {"select": "*", "is_active": "eq.true"})
        self._lofts = {str(l.get("id")): l for l in lofts}
        lots = self._rest("lots", {"select": "*", "status": "eq.live", "order": "lot_number.asc"})
        self._live_rows = lots
        by_loft: dict[str, list[dict]] = {}
        for row in lots:
            by_loft.setdefault(str(row.get("loft_id") or row.get("seller_id") or "unknown"), []).append(row)
        auctions = []
        for loft_id, rows in by_loft.items():
            loft = self._lofts.get(loft_id, {})
            name = loft.get("name") or f"Loft {loft_id}"
            olr, year = tag_olr(name)
            ends = [parse_iso(r.get("ends_at")) for r in rows if r.get("ends_at")]
            auctions.append(
                Auction(self.key, loft_id, name, url=self.site_lot_url, seller=name, lot_count=len(rows),
                        first_close=min(ends) if ends else None, olr_tag=olr, olr_year=year, extra={"rows": rows})
            )
        return auctions

    def fetch_lots(self, auction: Auction) -> list[Lot]:
        rows = auction.extra.get("rows")
        if rows is None:
            rows = self._rest("lots", {"select": "*", "status": "eq.live", "loft_id": f"eq.{auction.auction_id}", "order": "lot_number.asc"})
        return [self.row_to_lot(r, auction) for r in rows]

    def row_to_lot(self, r: dict, auction: Auction) -> Lot:
        title = clean_text(r.get("title")) or ""
        ring_field = clean_text(r.get("ring_number"))
        year = None
        try:
            year = int(r.get("year")) if r.get("year") else None
        except (TypeError, ValueError):
            year = None
        images = r.get("images")
        pedigree = r.get("pedigree")
        if isinstance(pedigree, (dict, list)):
            import json

            pedigree = json.dumps(pedigree, ensure_ascii=False)
        lot = Lot(
            source=self.key,
            auction_id=auction.auction_id,
            auction_name=auction.name,
            lot_key=str(r.get("id")),
            # The per-lot URL pattern has not been confirmed, so link to the verified
            # auctions page; set ELITE_LOT_URL_TEMPLATE in docs/sources.md once known.
            url=self.lot_url_template.format(id=r.get("id"), lot_number=r.get("lot_number")),
            title=title,
            seller=auction.seller or (self._lofts.get(str(r.get("seller_id")), {}).get("name")),
            lot_no=r.get("lot_number"),
            sex=parse_sex(r.get("sex")),
            year=year,
            colour=r.get("colour") or r.get("color"),
            bloodline=" / ".join(x for x in [r.get("strain"), r.get("bloodline_name")] if x) or None,
            pedigree_text=clean_text(pedigree) if pedigree else None,
            pedigree_url=r.get("pdf_url"),
            description=clean_text(r.get("description")),
            performance_claims=clean_text(r.get("performance_highlights")),
            current_bid=parse_zar(r.get("current_bid")),
            starting_bid=parse_zar(r.get("starting_bid")),
            reserve_price=parse_zar(r.get("reserve_price")),
            bid_count=r.get("total_bids"),
            ends_at=parse_iso(r.get("ends_at")),
            image_url=r.get("image_url") or (images[0] if isinstance(images, list) and images else None),
            status="live" if r.get("status") == "live" else (r.get("status") or "live"),
            olr_tag=auction.olr_tag,
            olr_year=auction.olr_year,
        )
        if lot.reserve_price is not None and lot.current_bid is not None:
            lot.reserve_met = lot.current_bid >= lot.reserve_price
        # Elite rings: "9822 OERF" — number + club, no country/year.
        longer = None
        for text in (title, lot.description, lot.pedigree_text):
            for ring in find_rings(text):
                short = parse_ring(ring_field, default_year=year) if ring_field else None
                if short is None or (ring.number_int == short.number_int):
                    longer = ring
                    break
            if longer:
                break
        if longer:
            lot.ring_raw, lot.ring_norm = longer.raw, normalise(longer.raw)
            lot.extra["ring_low_confidence"] = False
        elif ring_field:
            lot.ring_raw, lot.ring_norm = ring_field, normalise(ring_field)
            lot.extra["ring_low_confidence"] = True
        lot.extra["video_url"] = r.get("video_url")
        lot.extra["starts_at"] = r.get("starts_at")
        lot.detail_loaded = True
        olr, oy = tag_olr(title)
        if olr:
            lot.olr_tag, lot.olr_year = olr, oy or lot.olr_year
        return lot

    def refresh_lot(self, lot: Lot) -> Lot | None:
        rows = self._rest("lots", {"select": "*", "id": f"eq.{lot.lot_key}"})
        if not rows:
            return None
        a = Auction(self.key, lot.auction_id, lot.auction_name or "", seller=lot.seller,
                    olr_tag=lot.olr_tag, olr_year=lot.olr_year)
        return self.row_to_lot(rows[0], a)
