"""Pigeon Auction House (pigeonauctionhouse.com) — best-effort adapter.

No live lot had been seen when this was written, so the platform is detected at
run time: WooCommerce markup is parsed with the shared Woo parser; anything
else falls back to Playwright DOM extraction. Until a real lot parses, the
Sources screen shows "no live lots / not yet verified".
"""

from __future__ import annotations

from ..rings import normalise, parse_ring
from ..util.http import SourceUnavailable
from .base import Auction, AuctionSource, Lot, tag_olr
from .render import playwright_available, render
from .woo import lot_number, parse_category_page, parse_product_page


def detect_platform(html: str) -> str:
    low = html.lower()
    if "woocommerce" in low or "li class=\"product" in low or "wp-content" in low:
        return "woocommerce"
    if "__next_data__" in low or "id=\"root\"" in low or "id=\"app\"" in low:
        return "spa"
    return "unknown"


class PigeonAuctionHouseSource(AuctionSource):
    key = "pah"
    name = "Pigeon Auction House"
    base_url = "https://pigeonauctionhouse.com"
    live_url = "https://pigeonauctionhouse.com/live-auctions/"
    verified = False

    def __init__(self, client):
        super().__init__(client)
        self.platform: str | None = None

    def fetch_active(self) -> list[Auction]:
        html = self.client.get_text(self.live_url)
        self.platform = detect_platform(html)
        if self.platform == "woocommerce":
            subcats, products, _ = parse_category_page(html, self.base_url)
            auctions = [Auction(self.key, c.url, c.name, url=c.url, lot_count=c.count, olr_tag=tag_olr(c.name)[0])
                        for c in subcats]
            if products and not auctions:
                auctions = [Auction(self.key, self.live_url, "Live auctions", url=self.live_url)]
            return auctions
        if not playwright_available():
            raise SourceUnavailable(f"platform '{self.platform}' needs Playwright to read")
        page = render(self.live_url)
        _, products, _ = parse_category_page(page["html"], self.base_url)
        return [Auction(self.key, self.live_url, "Live auctions", url=self.live_url, extra={"html": page["html"]})] if products else []

    def fetch_lots(self, auction: Auction) -> list[Lot]:
        html = auction.extra.get("html") or self.client.get_text(auction.url)
        _, products, _ = parse_category_page(html, self.base_url)
        lots = []
        for p in products:
            lot = Lot(self.key, auction.auction_id, auction.name, p.url, p.url, title=p.title,
                      lot_no=lot_number(p.title), current_bid=p.price if p.price_kind != "starting" else None,
                      starting_bid=p.price if p.price_kind == "starting" else None, image_url=p.image_url,
                      olr_tag=auction.olr_tag)
            ring = parse_ring(p.title)
            if ring:
                lot.ring_raw, lot.ring_norm, lot.sex, lot.year = ring.raw, normalise(ring.raw), ring.sex, ring.year
            if self.platform == "woocommerce":
                page = parse_product_page(self.client.get_text(p.url), self.base_url)
                lot.ends_at, lot.description, lot.pedigree_text = page.ends_at, page.description, page.description
                lot.pedigree_url, lot.bids, lot.reserve_met = page.pedigree_url, page.bids, page.reserve_met
                if page.price is not None and page.price_kind != "starting":
                    lot.current_bid = page.price
                lot.detail_loaded = True
            lots.append(lot)
        return lots
