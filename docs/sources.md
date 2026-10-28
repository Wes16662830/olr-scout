# Sources: endpoints and verification status

**Read this first.** OLR Scout was built in an environment whose network policy
blocked every auction and results host (toppigeon.co.za, elitepigeonauctions.co.za,
bestpigeon.co.za, afripigeon.com, pigeonauctionhouse.com, oneloftrace.live). Nothing
below was re-checked against the live sites during the build. "Brief" means the fact
comes from the build brief (checked by hand in a browser before the build); "not
verified" means no one has confirmed it yet. The adapters are written to fail
loudly, not silently, when a page or payload does not look as expected.

The fixtures in `backend/tests/fixtures/` (except `recorded/`) are **synthetic** and
test parsing logic only. Run `backend/scripts/record_fixtures.py` from a machine that
can reach the sites, then update this file.

| Source | What | Status |
|---|---|---|
| Top Pigeon | WooCommerce category pages, `li.product`, sub-category per auction | Brief |
| Top Pigeon | Price labels "Current bid" / "Winning Bid" / "Starting bid" | Brief |
| Top Pigeon | Lot page "Auction ends:" (SAST), bid-history table | Brief (table class names not verified) |
| Elite | `GET https://amsnfjkefytwxipkqzev.supabase.co/rest/v1/lots?select=*&status=eq.live&order=lot_number.asc` | Brief (from a browser) |
| Elite | `GET …/rest/v1/lofts?select=*&is_active=eq.true` | Brief (from a browser) |
| Elite | Anon key read from the JS bundle at run time; re-read on 401/403 | Brief: key works; bundle file name not verified |
| Elite | Per-lot URL pattern | **Not known**. "Open lot" links to `/auctions` until confirmed (`EliteSource.lot_url_template`) |
| Best Pigeon | `/auctions/live/` → `/product-category/live-auctions/<seller>-ends-<dd>-<mon>-from-<hhmm>/` | Brief |
| Best Pigeon | Title `ZA 2026 PORT 7829 (C) Name - Seller - BLOODLINE` | Brief (separator between name/seller/bloodline not verified) |
| Best Pigeon | Lot page end-time element | **Not verified**. Parser looks for "Auction ends:" and common data attributes; a lot without one is flagged "end time not found" |
| Best Pigeon | "Pre-bidding" / "Ending soon" pages | Discovered from links on the Live page; URLs not verified |
| AfriPigeon | `GET /api/auctions/active`, `/api/auctions/upcoming`, `/api/auctions/{id}` | Brief |
| AfriPigeon | Lot listing | **Not found.** `/api/auctions/{id}/lots`, `/api/lots?auctionId=`, `/items` returned 404/errors. The adapter reads `/static/js/main.*.js`, tries every `/api/…lot…` path it finds, then falls back to Playwright (captures lot-shaped JSON the page fetches, else scrapes the DOM). The endpoint it finds is shown on the Sources screen (`detail.lot_endpoint`, `detail.discovery_log`). Record it here once seen. |
| Pigeon Auction House | `/live-auctions/` | No live lot seen yet. Platform detected at run time (WooCommerce → shared parser; else Playwright). Shown as "no live lots / not yet verified" |
| Benzing / oneloftrace (unofficial) | `GET /api/custom/v1/public/lofts?page=1&paginationPerPage=500` | Brief. `health_check()` checks rows have `id`/`name` |
| Benzing | Seasons: Nuxt payload in `/lofts/{id}` HTML | Brief. Parser handles Nuxt 3 `__NUXT_DATA__` (devalue) and `window.__NUXT__` JSON; falls back to the registry's season ids |
| Benzing | `GET /api/custom/v1/public/season/{seasonId}/flightsAndTrainings` | Brief. Field names (`distance`, `type`, …) read tolerantly; **not verified** |
| Benzing | `GET /api/search/v1/public/flights/{flightId}/results/final?page=&search=&paginationPerPage=1000&onlyUserPigeons=false` | Brief. Paginates until rows == total; mismatches are logged and the source marked degraded |
| Benzing | `GET /api/search/v1/public/pigeon-team/{seasonId}?page=&paginationPerPage=200` | Brief. Field names not verified |

## Known OLR ids (seeded registry, editable in Settings)

| OLR | Loft id | Seasons (year → season id) |
|---|---|---|
| AfrikaPro | 147 | 2026→2873, 2025→2722, 2024→2141, 2023→1160, 2022→1049 |
| Marlbank OLR Winter | 251 | discovered from the loft page |
| Dinokeng, Karoo Million | from the loft list | auto-filled by `discover_olrs` when the loft list names them |

## Politeness

* User-Agent names the tool (add a contact with `OLR_SCOUT_CONTACT`).
* At most 1 request/second per host, enforced in `util/http.py` for every adapter.
* Full refresh at most every 60 s (default 10 min); lots closing within 10 min are
  re-read at most every 20 s.
* A Cloudflare/Turnstile page or a 401/403/429 raises `SourceBlocked`: that source
  is marked **degraded** and a banner is shown. Nothing tries to get round it.
* No logins, no stored auction passwords, no bidding.

## Terms of use

Not checked during the build (sites unreachable). Check each site's terms before
enabling it; disable a source by removing it from `sources/registry.py`.
