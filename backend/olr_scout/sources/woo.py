"""Shared WooCommerce + auction-plugin parsing (Top Pigeon, Best Pigeon).

Both sites list lots as ``li.product`` on category pages and show price labels
like "Current bid", "Winning Bid" or "Starting bid". Lot pages carry an
"Auction ends:" timestamp in Africa/Johannesburg time and, where the plugin
exposes it, a bid-history table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..util.money import parse_zar
from ..util.timeutil import parse_local_datetime
from .base import clean_text


@dataclass
class CategoryLink:
    url: str
    name: str
    count: int | None = None


@dataclass
class ProductCard:
    url: str
    title: str
    price_kind: str | None  # current | winning | starting | None
    price: int | None
    image_url: str | None = None
    product_id: str | None = None
    ended: bool = False


@dataclass
class ProductPage:
    title: str | None = None
    summary_text: str = ""
    description: str | None = None
    ends_at: datetime | None = None
    ends_at_text: str | None = None
    price_kind: str | None = None
    price: int | None = None
    reserve_met: bool | None = None
    bids: list[dict] = field(default_factory=list)
    pedigree_url: str | None = None
    image_url: str | None = None
    attributes: dict = field(default_factory=dict)
    ended: bool = False


PRICE_LABELS = [
    ("winning", re.compile(r"winning\s*bid", re.I)),
    ("current", re.compile(r"current\s*bid", re.I)),
    ("starting", re.compile(r"starting\s*bid|start(?:ing)?\s*price|opening\s*bid", re.I)),
]


def parse_price_label(text: str) -> tuple[str | None, int | None]:
    t = " ".join((text or "").split())
    for kind, pat in PRICE_LABELS:
        m = pat.search(t)
        if m:
            return kind, parse_zar(t[m.end():])
    amt = parse_zar(t) if re.search(r"R\s*\d", t) else None
    return (None, amt)


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _count(text: str) -> int | None:
    m = re.search(r"\((\d+)\)", text or "")
    return int(m.group(1)) if m else None


def parse_category_page(html: str, base_url: str) -> tuple[list[CategoryLink], list[ProductCard], str | None]:
    s = soup(html)
    subcats: list[CategoryLink] = []
    for li in s.select("li.product-category"):
        a = li.find("a", href=True)
        if not a:
            continue
        name_el = li.select_one(".woocommerce-loop-category__title") or a
        mark = li.select_one("mark.count")
        name = clean_text(name_el.get_text(" ", strip=True)) or ""
        count = _count(mark.get_text()) if mark else _count(name)
        name = re.sub(r"\s*\(\d+\)\s*$", "", name)
        subcats.append(CategoryLink(urljoin(base_url, a["href"]), name, count))
    products: list[ProductCard] = []
    for li in s.select("li.product"):
        if "product-category" in (li.get("class") or []):
            continue
        a = li.select_one("a.woocommerce-LoopProduct-link") or li.find("a", href=True)
        if not a:
            continue
        title_el = li.select_one(".woocommerce-loop-product__title") or li.find(["h2", "h3"])
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else clean_text(a.get_text(" ", strip=True))
        price_el = li.select_one(".price") or li.select_one(".auction-price")
        price_text = price_el.get_text(" ", strip=True) if price_el else li.get_text(" ", strip=True)
        kind, price = parse_price_label(price_text)
        img = li.find("img")
        img_url = None
        if img:
            img_url = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
        pid = None
        for cls in li.get("class") or []:
            m = re.match(r"post-(\d+)", cls)
            if m:
                pid = m.group(1)
        ended = bool(re.search(r"auction\s+(?:has\s+)?(?:ended|finished|closed)", li.get_text(" ", strip=True), re.I))
        products.append(ProductCard(urljoin(base_url, a["href"]), title or "", kind, price, img_url, pid, ended))
    nxt = s.select_one("a.next.page-numbers") or s.select_one("link[rel=next]")
    next_url = urljoin(base_url, nxt["href"]) if nxt and nxt.get("href") else None
    return subcats, products, next_url


_ENDS = re.compile(r"auction\s+end(?:s|ed|ing)?\s*(?:on|at)?\s*:?", re.I)


def _summary_block(s: BeautifulSoup) -> Tag | None:
    return (
        s.select_one("div.summary.entry-summary")
        or s.select_one(".product .summary")
        or s.select_one("div.product")
        or s.body
    )


def parse_product_page(html: str, base_url: str) -> ProductPage:
    """Extract only the product summary block, the pedigree image/link, the end time
    and the bid history. Theme CSS/JS is ignored."""
    s = soup(html)
    for bad in s(["style", "script", "noscript", "svg"]):
        bad.decompose()
    page = ProductPage()
    summary = _summary_block(s)
    if summary is None:
        return page
    t = summary.select_one(".product_title") or s.select_one("h1")
    page.title = clean_text(t.get_text(" ", strip=True)) if t else None
    page.summary_text = clean_text(summary.get_text("\n", strip=True)) or ""

    # End time: "Auction ends: October 28, 2026 14:02" (local time).
    full = s.get_text("\n", strip=True)
    for text in (page.summary_text, full):
        m = _ENDS.search(text or "")
        if m:
            snippet = text[m.end(): m.end() + 80]
            dt = parse_local_datetime(snippet)
            if dt:
                page.ends_at, page.ends_at_text = dt, clean_text(snippet.split("\n")[0])
                break
    if page.ends_at is None:
        el = s.select_one("[data-auction-end], [data-end-time], .auction-end-date, .auction-end .date")
        if el:
            raw = el.get("data-auction-end") or el.get("data-end-time") or el.get_text(" ", strip=True)
            page.ends_at = parse_local_datetime(raw)
            page.ends_at_text = raw

    price_el = summary.select_one(".auction-price, p.price, .price")
    if price_el:
        page.price_kind, page.price = parse_price_label(price_el.get_text(" ", strip=True))
    if page.price is None:
        page.price_kind, page.price = parse_price_label(page.summary_text)

    low = page.summary_text.lower()
    if re.search(r"reserve\s+price\s+(?:has\s+)?not\s+(?:been\s+)?met|reserve\s+not\s+met", low):
        page.reserve_met = False
    elif re.search(r"reserve\s+price\s+(?:has\s+been\s+)?met|reserve\s+met|no\s+reserve", low):
        page.reserve_met = True
    page.ended = bool(re.search(r"auction\s+(?:has\s+)?(?:ended|finished|closed)", low))

    # Bid history table (date | bid | user, in any column order).
    table = s.select_one("table.auction-history-table, table.auction_history, #auction-history-table, .auction-history table")
    if table is None:
        for tb in s.find_all("table"):
            head = tb.get_text(" ", strip=True).lower()[:200]
            if "bid" in head and ("user" in head or "bidder" in head):
                table = tb
                break
    if table is not None:
        headers = [h.get_text(" ", strip=True).lower() for h in table.select("thead th")] or []
        for tr in table.select("tbody tr") or table.select("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row = {"bidder": None, "amount": None, "at": None}
            for i, c in enumerate(cells):
                h = headers[i] if i < len(headers) else ""
                if "user" in h or "bidder" in h or "name" in h:
                    row["bidder"] = c
                elif "bid" in h or "amount" in h:
                    row["amount"] = parse_zar(c)
                elif "date" in h or "time" in h:
                    row["at"] = parse_local_datetime(c)
                elif not h:
                    if row["at"] is None and parse_local_datetime(c):
                        row["at"] = parse_local_datetime(c)
                    elif row["amount"] is None and re.search(r"R?\s*\d", c) and parse_zar(c) is not None and not re.search(r"[A-Za-z]{3,}", c):
                        row["amount"] = parse_zar(c)
                    elif row["bidder"] is None:
                        row["bidder"] = c
            if row["amount"] is not None:
                page.bids.append(row)

    # Description tab.
    desc = s.select_one("#tab-description, .woocommerce-Tabs-panel--description, .woocommerce-product-details__short-description")
    if desc:
        page.description = clean_text(desc.get_text("\n", strip=True))

    # Attributes table (Sex, Year, Colour ...).
    for tr in s.select("table.woocommerce-product-attributes tr, table.shop_attributes tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            page.attributes[th.get_text(" ", strip=True).lower()] = td.get_text(" ", strip=True)

    # Pedigree: a link or image mentioning pedigree, else a PDF link.
    for a in s.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
        if "pedigree" in label or "stamboom" in label or a["href"].lower().endswith(".pdf"):
            page.pedigree_url = urljoin(base_url, a["href"])
            break
    if page.pedigree_url is None:
        for img in s.find_all("img"):
            src = img.get("data-large_image") or img.get("data-src") or img.get("src") or ""
            if "pedigree" in (src + " " + (img.get("alt") or "")).lower():
                page.pedigree_url = urljoin(base_url, src)
                break
    gal = s.select_one(".woocommerce-product-gallery__image img, .wp-post-image")
    if gal:
        page.image_url = urljoin(base_url, gal.get("data-large_image") or gal.get("src") or "")
    return page


_LOT_NO = re.compile(r"\blot\s*(?:no\.?|#|number)?\s*(\d{1,4})\b", re.I)


def lot_number(*texts: str | None) -> int | None:
    for t in texts:
        m = _LOT_NO.search(t or "")
        if m:
            return int(m.group(1))
    return None
