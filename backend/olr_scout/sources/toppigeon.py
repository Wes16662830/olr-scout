"""Top Pigeon (toppigeon.co.za) — WooCommerce with an auction plugin.

Each sub-category of "Active Auctions" is one auction. Close times are sequential
with anti-sniping extensions, so the end time is always read from the lot page.
"""

from __future__ import annotations

import re

from ..rings import normalise, parse_ring
from .base import Auction, AuctionSource, Lot, parse_sex, tag_olr
from .woo import lot_number, parse_category_page, parse_product_page

MAX_PAGES = 30


class TopPigeonSource(AuctionSource):
    key = "toppigeon"
    name = "Top Pigeon"
    base_url = "https://toppigeon.co.za"
    root = "https://toppigeon.co.za/product-category/active-auctions/"
    verified = False  # structure described from manual inspection; fixtures are synthetic until recorded

    def fetch_active(self) -> list[Auction]:
        html = self.client.get_text(self.root)
        subcats, products, _ = parse_category_page(html, self.base_url)
        auctions: list[Auction] = []
        seen: set[str] = set()
        queue = list(subcats)
        depth = {c.url: 0 for c in subcats}
        while queue:
            c = queue.pop(0)
            if c.url in seen:
                continue
            seen.add(c.url)
            # A sub-category may itself have sub-categories (one level deeper is enough).
            if depth.get(c.url, 0) == 0:
                try:
                    sub_html = self.client.get_text(c.url)
                    inner, inner_products, _ = parse_category_page(sub_html, self.base_url)
                except Exception:
                    inner, inner_products = [], []
                if inner and not inner_products:
                    for i in inner:
                        depth[i.url] = 1
                        queue.append(i)
                    continue
            olr, year = tag_olr(c.name)
            auctions.append(
                Auction(
                    self.key, c.url, c.name, url=c.url, lot_count=c.count, olr_tag=olr, olr_year=year,
                    status="upcoming" if "upcoming" in c.name.lower() or "pre-bid" in c.name.lower() else "live",
                )
            )
        if not auctions and products:
            auctions.append(Auction(self.key, self.root, "Active Auctions", url=self.root))
        return auctions

    def fetch_lots(self, auction: Auction) -> list[Lot]:
        lots: list[Lot] = []
        url = auction.url
        pages = 0
        while url and pages < MAX_PAGES:
            pages += 1
            html = self.client.get_text(url)
            _, products, url = parse_category_page(html, self.base_url)
            for p in products:
                lot = Lot(
                    source=self.key,
                    auction_id=auction.auction_id,
                    auction_name=auction.name,
                    lot_key=p.url,
                    url=p.url,
                    title=p.title,
                    lot_no=lot_number(p.title),
                    current_bid=p.price if p.price_kind in ("current", "winning") else None,
                    starting_bid=p.price if p.price_kind == "starting" else None,
                    image_url=p.image_url,
                    status="closed" if p.ended else auction.status,
                )
                olr, year = tag_olr(p.title)
                lot.olr_tag = olr or auction.olr_tag
                lot.olr_year = year or auction.olr_year
                ring = parse_ring(p.title)
                if ring:
                    lot.ring_raw, lot.sex, lot.year = ring.raw, ring.sex, ring.year
                    lot.ring_norm = normalise(ring.raw)
                lot = self._load_detail(lot)
                lots.append(lot)
        return lots

    def _load_detail(self, lot: Lot) -> Lot:
        html = self.client.get_text(lot.url)
        page = parse_product_page(html, self.base_url)
        lot.detail_loaded = True
        lot.ends_at = page.ends_at
        if page.price is not None:
            if page.price_kind == "starting":
                lot.starting_bid, lot.current_bid = page.price, lot.current_bid
            else:
                lot.current_bid = page.price
        lot.reserve_met = page.reserve_met
        lot.bids = page.bids
        lot.bid_count = len(page.bids) if page.bids else lot.bid_count
        lot.description = page.description
        lot.pedigree_text = page.description
        lot.pedigree_url = page.pedigree_url
        lot.image_url = page.image_url or lot.image_url
        if page.ended:
            lot.status = "closed"
        attrs = page.attributes
        lot.sex = lot.sex or parse_sex(attrs.get("sex") or attrs.get("gender")) or parse_sex(lot.title)
        m = re.search(r"(?:19|20)\d{2}", attrs.get("year") or "")
        if m:
            lot.year = lot.year or int(m.group(0))
        lot.colour = attrs.get("colour") or attrs.get("color")
        lot.bloodline = attrs.get("bloodline") or attrs.get("strain")
        if not lot.ring_raw:
            ring = parse_ring(attrs.get("ring") or attrs.get("ring number") or page.summary_text)
            if ring:

                lot.ring_raw, lot.ring_norm, lot.year = ring.raw, normalise(ring.raw), lot.year or ring.year
        if lot.lot_no is None:
            lot.lot_no = lot_number(page.title, page.summary_text)
        lot.seller = lot.seller or attrs.get("seller") or attrs.get("breeder")
        return lot

    def refresh_lot(self, lot: Lot) -> Lot | None:
        return self._load_detail(lot)
