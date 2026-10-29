"""Adapter tests against SYNTHETIC fixtures (see fixtures/README.md)."""

from datetime import datetime, timezone

import pytest

from olr_scout.config import TZ
from olr_scout.sources.afripigeon import AfriPigeonSource, candidate_endpoints
from olr_scout.sources.bestpigeon import BestPigeonSource
from olr_scout.sources.elite import EliteSource, extract_supabase_config
from olr_scout.sources.pah import PigeonAuctionHouseSource
from olr_scout.sources.toppigeon import TopPigeonSource
from olr_scout.sources.woo import parse_price_label
from olr_scout.util.http import SourceBlocked


def local(y, m, d, H, M):
    return datetime(y, m, d, H, M, tzinfo=TZ).astimezone(timezone.utc)


@pytest.mark.parametrize("text,kind,amount", [
    ("Current bid: R3,500.00", "current", 3500),
    ("Winning Bid: R6 000.00", "winning", 6000),
    ("Starting bid: R500.00", "starting", 500),
    ("Current bid: R450", "current", 450),
])
def test_price_labels(text, kind, amount):
    assert parse_price_label(text) == (kind, amount)


def test_toppigeon_auctions_and_lots(client):
    src = TopPigeonSource(client)
    auctions = src.fetch_active()
    names = [a.name for a in auctions]
    assert names == ["AfrikaPro 2026 Auction 2", "Dinokeng 2026 Upcoming – Pre-bids open"]
    afp, dino = auctions
    assert (afp.olr_tag, afp.olr_year, afp.lot_count) == ("AfrikaPro", 2026, 3)
    assert dino.status == "upcoming" and dino.olr_tag == "Dinokeng"
    lots = src.fetch_lots(afp)
    assert [l.lot_no for l in lots] == [1, 2, 3]
    l1, l2, l3 = lots
    assert l1.ring_norm == "ZA2026PORT7829" and l1.sex == "cock"
    assert l1.current_bid == 3500 and l1.reserve_met is True
    # End time read from the lot page (local SAST → UTC), never from a formula.
    assert l1.ends_at == local(2026, 10, 28, 14, 2)
    assert [b["bidder"] for b in l1.bids] == ["GeForce RTX", "b***r", "pigeonman"]
    assert l1.bids[0]["amount"] == 3500
    assert l1.pedigree_url.endswith("pedigree-7829.jpg")
    assert l1.colour == "Blue"
    assert l2.current_bid == 6000 and l2.reserve_met is False and l2.sex == "hen"
    assert l2.ends_at == local(2026, 10, 28, 14, 4)
    assert l3.starting_bid == 500 and l3.current_bid is None and l3.ring_raw is None
    assert l3.ends_at == local(2026, 10, 28, 14, 6)


def test_bestpigeon(client):
    src = BestPigeonSource(client)
    auctions = src.fetch_active()
    assert len(auctions) == 1
    a = auctions[0]
    assert a.seller == "Bloodstock Lofts" and a.lot_count == 2
    assert a.first_close == local(2026, 10, 28, 20, 0)
    lots = src.fetch_lots(a)
    assert len(lots) == 2  # page 2 is empty
    l = lots[0]
    assert (l.ring_raw, l.year, l.sex) == ("ZA 2026 PORT 7829", 2026, "cock")
    assert l.extra["bird_name"] == "Blue Thunder" and l.bloodline == "KITTEL X JANSSEN"
    assert l.current_bid == 450
    assert l.ends_at == local(2026, 10, 28, 20, 0)
    assert l.pedigree_url.endswith(".pdf")
    assert "Sire: ZA 2023 PORT 555" in l.description
    l2 = lots[1]
    assert l2.starting_bid == 300 and l2.sex == "hen"
    assert l2.ends_at is None and "end time not found" in l2.extra["ends_at_note"]


def test_elite_key_from_bundle_and_low_confidence(client, web):
    url, key = extract_supabase_config(open(__file__.replace("test_adapters.py", "fixtures/elite/bundle.js")).read())
    assert url == "https://amsnfjkefytwxipkqzev.supabase.co"
    assert key == web.anon_key  # picks the role=anon JWT, not the other one
    src = EliteSource(client)
    auctions = src.fetch_active()
    assert {a.name for a in auctions} == {"Sunrise Lofts", "Oudeluck, Baard & Spammer"}
    sunrise = next(a for a in auctions if a.name == "Sunrise Lofts")
    lots = src.fetch_lots(sunrise)
    l1, l2 = lots
    assert l1.ring_raw == "9822 OERF" and l1.extra["ring_low_confidence"] is True
    assert l1.reserve_price == 1500 and l1.reserve_met is False
    assert l1.performance_claims == "Bred from our top OLR performers"
    assert l1.bloodline == "Kittel / Janssen" and l1.sex == "cock" and l1.year == 2026
    # A longer ring in the title wins and removes the low-confidence flag.
    assert l2.ring_raw == "ZA 2026 OERF 9823" and l2.extra["ring_low_confidence"] is False
    assert l2.pedigree_url.endswith("a2.pdf")
    # The key is sent as both headers.
    assert any("rest/v1/lots" in c for c in web.calls)


def test_elite_rereads_rotated_key(client, web):
    src = EliteSource(client)
    src.fetch_active()
    web.anon_key = "rotated"  # server now rejects the old key …
    # … and the bundle now ships the new one
    web.add("https://elitepigeonauctions.co.za/assets/index-AbC123.js",
            __import__("httpx").Response(200, text='x="https://amsnfjkefytwxipkqzev.supabase.co";k="sb_publishable_rotatedkeyrotatedkey00"',
                                         headers={"content-type": "application/javascript"}))
    web.anon_key = "sb_publishable_rotatedkeyrotatedkey00"
    auctions = src.fetch_active()
    assert auctions


def test_afripigeon_discovers_lot_endpoint(client):
    js = open(__file__.replace("test_adapters.py", "fixtures/afripigeon/main.js")).read()
    cands = candidate_endpoints(js)
    assert cands[0] == "/api/auction-lots/by-auction/{id}"  # known-bad paths are tried last
    src = AfriPigeonSource(client)
    auctions = src.fetch_active()
    assert [(a.name, a.status) for a in auctions] == [("Marlbank Winter OLR Encore", "live"),
                                                      ("Shamwari Lofts Production Sale", "upcoming")]
    assert auctions[0].olr_tag == "Marlbank OLR Winter"
    assert auctions[0].first_close == local(2026, 10, 31, 14, 0)
    lots = src.fetch_lots(auctions[0])
    assert src.lot_endpoint == "/api/auction-lots/by-auction/{id}"
    assert [l.ring_norm for l in lots] == ["ZA2026MARL3301", "ZA2026MARL3302"]
    assert lots[0].ends_at == local(2026, 10, 31, 14, 0) and lots[0].current_bid == 2500


def test_pah_empty_is_not_an_error(client):
    src = PigeonAuctionHouseSource(client)
    assert src.fetch_active() == []
    assert src.platform == "woocommerce"


def test_turnstile_raises_blocked(client, web):
    web.blocked_hosts.add("toppigeon.co.za")
    with pytest.raises(SourceBlocked):
        TopPigeonSource(client).fetch_active()


def test_one_request_per_second_per_host(client):
    TopPigeonSource(client).fetch_active()
    # Three requests to the same host → at least two waits of up to 1 s.
    assert len(client.sleeps) >= 2 and all(0 < s <= 1.0 for s in client.sleeps)


def test_pedigree_link_ignores_other_lots_on_the_page():
    from olr_scout.sources.woo import parse_product_page

    html = """<html><body>
      <div class="product type-product" id="product-1">
        <div class="woocommerce-product-gallery">
          <div class="woocommerce-product-gallery__image"><img src="https://x.co/photo-7829.jpg"></div>
          <div class="woocommerce-product-gallery__image"><a href="https://x.co/pedigree-old-1111.jpg"><img src="https://x.co/pedigree-old-1111.jpg" alt="pedigree"></a></div>
          <div class="woocommerce-product-gallery__image"><a href="https://x.co/pedigree-7829.jpg"><img src="https://x.co/pedigree-7829.jpg" alt="pedigree"></a></div>
        </div>
        <div class="summary entry-summary"><h1 class="product_title">Lot 1 ZA 2026 PORT 7829</h1></div>
        <section class="related products"><ul class="products"><li class="product">
          <a href="https://x.co/pedigree-9999.pdf">View pedigree</a><span>Auction ends: October 29, 2026 10:00</span>
        </li></ul></section>
      </div>
      <aside class="widget"><a href="https://x.co/pedigree-sidebar.pdf">Featured pedigree</a></aside>
    </body></html>"""
    page = parse_product_page(html, "https://x.co", hints=["ZA 2026 PORT 7829"])
    assert page.pedigree_url == "https://x.co/pedigree-7829.jpg"
    assert page.ends_at is None  # the related lot's end time is not taken
    no_hint = parse_product_page(html, "https://x.co")
    assert "9999" not in no_hint.pedigree_url and "sidebar" not in no_hint.pedigree_url


def test_normal_pages_with_cloudflare_scripts_are_not_challenges():
    """Elite showed 'bot challenge (HTTP 200)': Cloudflare's beacon script and a Turnstile
    widget on a login form sit on ordinary pages. A real challenge is a refusal or a
    challenge page."""
    import httpx

    from olr_scout.util.http import challenge_evidence

    html = {"content-type": "text/html"}
    normal = ('<html><head><title>Elite Pigeon Auctions</title>'
              '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
              '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></head>'
              '<body><div class="cf-turnstile"></div></body></html>')
    assert challenge_evidence(httpx.Response(200, text=normal, headers=html)) is None
    assert challenge_evidence(httpx.Response(403, text=normal, headers=html))  # refused + widget
    page = "<html><head><title>Just a moment...</title></head><script>window._cf_chl_opt={}</script></html>"
    assert challenge_evidence(httpx.Response(200, text=page, headers=html))
    assert challenge_evidence(httpx.Response(403, text="", headers={"cf-mitigated": "challenge"}))
    assert challenge_evidence(httpx.Response(403, text="denied", headers={"server": "cloudflare"})) == \
        "refused by Cloudflare"
    assert challenge_evidence(httpx.Response(200, text='{"ok": true}', headers={"content-type": "application/json"})) is None


def test_blocked_message_says_what_was_seen(web):
    import httpx

    from olr_scout.util.http import PoliteClient

    def handler(req):
        return httpx.Response(403, text="Forbidden", headers={"server": "nginx"})

    c = PoliteClient(transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda _: None)
    with pytest.raises(SourceBlocked) as e:
        c.get("https://afripigeon.com/api/auctions/active")
    assert str(e.value) == "afripigeon.com: HTTP 403, server nginx (access refused) — /api/auctions/active"
