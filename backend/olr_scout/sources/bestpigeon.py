"""Best Pigeon (bestpigeon.co.za) — WooCommerce, one category per seller.

The Live page links to e.g.
``/product-category/live-auctions/bloodstock-lofts-ends-28-okt-from-2000/`` with
link text like "BLOODSTOCK LOFTS ENDS 28 OKT FROM 20:00 (45)". Lot titles carry
the ring as ``ZA 2026 PORT 7829 (C)`` then the bird's name, the seller and a
capitals bloodline description.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from ..config import TZ
from ..rings import normalise, parse_best_pigeon_title
from ..util.timeutil import MONTHS, now_utc
from .base import Auction, AuctionSource, Lot, clean_text, tag_olr
from .woo import lot_number, parse_category_page, parse_product_page, soup

MAX_PAGES = 30
_CAT_TEXT = re.compile(
    r"^(?P<seller>.+?)\s+ENDS?\s+(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3,10})\.?(?:\s+(?P<y>\d{4}))?\s+(?:FROM|@|AT)?\s*(?P<H>\d{1,2})[:h]?(?P<M>\d{2})",
    re.I,
)


def parse_category_name(text: str, today: datetime | None = None) -> tuple[str, datetime | None, int | None]:
    """'BLOODSTOCK LOFTS ENDS 28 OKT FROM 20:00 (45)' → (seller, first close UTC, lot count)."""
    text = " ".join((text or "").split())
    count = None
    mc = re.search(r"\((\d+)\)\s*$", text)
    if mc:
        count = int(mc.group(1))
        text = text[: mc.start()].strip()
    m = _CAT_TEXT.match(text)
    if not m:
        return text.title(), None, count
    month = MONTHS.get(m.group("mon").lower())
    today = (today or now_utc()).astimezone(TZ)
    year = int(m.group("y")) if m.group("y") else today.year
    first = None
    if month:
        try:
            first = datetime(year, month, int(m.group("d")), int(m.group("H")), int(m.group("M")), tzinfo=TZ)
            # A year-less date more than ~2 months in the past is next year's.
            if not m.group("y") and (today - first).days > 60:
                first = first.replace(year=year + 1)
        except ValueError:
            first = None
    seller = m.group("seller").strip().title()
    return seller, first.astimezone(timezone.utc) if first else None, count


_CAPS_TAIL = re.compile(r"((?:[A-Z0-9&'’./]+[\s\-x×X,]*){2,})$")


def split_title(title: str, seller: str | None) -> dict:
    ring, rest = parse_best_pigeon_title(title)
    out = {"ring": ring, "name": None, "bloodline": None}
    if not ring:
        return out
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+|\s{2,}", rest) if p.strip()]
    if seller:
        parts = [p for p in parts if normalise(p) != normalise(seller)]
    caps = [p for p in parts if p.isupper() and len(re.sub(r"[^A-Z]", "", p)) >= 4]
    names = [p for p in parts if p not in caps]
    if not caps and parts:
        m = _CAPS_TAIL.search(rest)
        if m and m.group(1).strip() != rest.strip():
            caps = [m.group(1).strip()]
            names = [rest[: m.start()].strip(" -–|")]
    name = names[0] if names else None
    if name and seller:
        name = re.sub(re.escape(seller), "", name, flags=re.I).strip(" -–|") or None
    out["name"] = name
    out["bloodline"] = " ".join(caps) if caps else None
    return out


class BestPigeonSource(AuctionSource):
    key = "bestpigeon"
    name = "Best Pigeon"
    base_url = "https://bestpigeon.co.za"
    live_url = "https://bestpigeon.co.za/auctions/live/"
    verified = False  # live list + title format confirmed manually; lot-page end time NOT confirmed

    def _discover(self, html: str) -> tuple[list[tuple[str, str]], list[str]]:
        s = soup(html)
        cats, extras = [], []
        for a in s.find_all("a", href=True):
            href = urljoin(self.base_url, a["href"])
            text = a.get_text(" ", strip=True)
            if "/product-category/" in href and "live-auctions/" in href and href.rstrip("/").split("/")[-1] != "live-auctions":
                cats.append((href, text))
            low = (text + " " + href).lower()
            if ("pre-bid" in low or "prebid" in low or "ending-soon" in low or "ending soon" in low) and href.startswith(self.base_url):
                extras.append(href)
        # de-dupe, keep first text
        seen, uniq = set(), []
        for href, text in cats:
            if href not in seen:
                seen.add(href)
                uniq.append((href, text))
        return uniq, sorted(set(extras))

    def fetch_active(self) -> list[Auction]:
        html = self.client.get_text(self.live_url)
        cats, extras = self._discover(html)
        for url in extras:
            try:
                more, _ = self._discover(self.client.get_text(url))
            except Exception:
                continue
            cats.extend(c for c in more if c[0] not in {x[0] for x in cats})
        auctions = []
        for href, text in cats:
            seller, first, count = parse_category_name(text)
            olr, year = tag_olr(text)
            auctions.append(
                Auction(self.key, href, clean_text(text) or href, url=href, seller=seller,
                        lot_count=count, first_close=first, olr_tag=olr, olr_year=year,
                        status="upcoming" if "pre-bid" in href or "prebid" in href else "live")
            )
        return auctions

    def fetch_lots(self, auction: Auction) -> list[Lot]:
        lots: list[Lot] = []
        url, pages = auction.url, 0
        while url and pages < MAX_PAGES:
            pages += 1
            _, products, url = parse_category_page(self.client.get_text(url), self.base_url)
            for p in products:
                parts = split_title(p.title, auction.seller)
                ring = parts["ring"]
                lot = Lot(
                    source=self.key, auction_id=auction.auction_id, auction_name=auction.name,
                    lot_key=p.url, url=p.url, title=p.title, seller=auction.seller,
                    lot_no=lot_number(p.title),
                    current_bid=p.price if p.price_kind in ("current", "winning") else None,
                    starting_bid=p.price if p.price_kind == "starting" else None,
                    image_url=p.image_url, status="closed" if p.ended else auction.status,
                    olr_tag=auction.olr_tag, olr_year=auction.olr_year,
                    bloodline=parts["bloodline"],
                )
                if ring:
                    lot.ring_raw, lot.ring_norm, lot.sex, lot.year = ring.raw, normalise(ring.raw), ring.sex, ring.year
                lot.extra["bird_name"] = parts["name"]
                lots.append(self._load_detail(lot))
        return lots

    def _load_detail(self, lot: Lot) -> Lot:
        page = parse_product_page(self.client.get_text(lot.url), self.base_url)
        lot.detail_loaded = True
        lot.ends_at = page.ends_at
        if page.ends_at is None:
            lot.extra["ends_at_note"] = "end time not found on lot page"
        if page.price is not None and page.price_kind != "starting":
            lot.current_bid = page.price
        elif page.price is not None:
            lot.starting_bid = page.price
        lot.reserve_met = page.reserve_met
        lot.bids = page.bids
        lot.bid_count = len(page.bids) if page.bids else None
        lot.description = page.description
        lot.pedigree_text = page.description
        lot.pedigree_url = page.pedigree_url
        lot.image_url = page.image_url or lot.image_url
        if page.ended:
            lot.status = "closed"
        return lot

    def refresh_lot(self, lot: Lot) -> Lot | None:
        return self._load_detail(lot)
