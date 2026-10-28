# OLR Scout

Personal pigeon-auction decision app. It reads live lots from five South African
auction sites, matches birds to official one-loft-race (OLR) results, checks
pedigree claims against those results, ranks lots against your max bid and
bloodline preferences, and plans purchases for a breeding family (Family
Builder). It runs as a web app and installs to a phone as a PWA.

It never bids, never logs in to the auction sites, and never stores auction
passwords. Every lot links out with **Open lot ↗**.

> **Status.** Built without network access to any auction or results site.
> Parsers are written to the structures in the build brief and tested on
> synthetic fixtures. Before relying on it, record real fixtures
> (`backend/scripts/record_fixtures.py`) and check `docs/sources.md`.

## Layout

```
backend/   FastAPI + SQLAlchemy (SQLite, Postgres-ready) + APScheduler
  olr_scout/sources/   one adapter per auction site (AuctionSource)
  olr_scout/results/   Benzing/oneloftrace results (ResultsSource) + ingest
  olr_scout/scoring/   tiers, Bid Score, pedigree claims, preferences, seller reliability
  olr_scout/builder.py Family Builder
  tests/               offline tests (fixtures via httpx.MockTransport)
frontend/  React + TypeScript + Vite PWA
docs/sources.md        every endpoint and its verification status
```

## Try the demo (no setup)

**https://wes16662830.github.io/olr-scout/** — the frontend on GitHub Pages, published
on every push to `main` (same setup as the Hyrox Trainer app). It runs without the
backend on a **made-up snapshot** (`frontend/src/demo/snapshot.json`, built by
`backend/scripts/build_demo_snapshot.py` from the synthetic test fixtures), so every
screen can be clicked through, but nothing in it is a real auction or race result.
Refresh, results ingest, OCR, match overrides and push alerts need the backend and
say so. Settings, watchlist and inventory changes are kept in the browser only.

Run the demo locally: `cd frontend && npm install && npm run demo`.
Rebuild the snapshot after scoring changes: `cd backend && python scripts/build_demo_snapshot.py`.

## Run locally

```bash
cp .env.example .env            # set OLR_SCOUT_PASSWORD at least

# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # optional extras: requirements-optional.txt
set -a; . ../.env; set +a
uvicorn olr_scout.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                 # http://localhost:5173 (proxies /api to :8000)
```

Then in the app: **Sources → Ingest OLR results now** (first run takes a while:
1 request/second), then **Refresh lots now**. After that the scheduler keeps
things current: full refresh every 10 min, lots closing within 10 min every 20 s,
results nightly at 02:30 SAST and on demand for any OLR a live lot refers to.

Or with Docker:

```bash
cp .env.example .env && docker compose up -d --build
# → http://127.0.0.1:8000
```

### Tests

```bash
cd backend && pytest -q        # offline; no network needed
cd frontend && npm run build   # typecheck + build
```

`tests/test_acceptance_recorded.py` holds the spec's real-data checks (AfrikaPro
Auction 1 totals, lot 163/169 long scores, AfrikaPro 2026 counts, Auction 2 matching).
They **skip** until real recordings exist in `tests/fixtures/recorded/`.

## Deploy to a small VPS

1. A 1 vCPU / 1 GB VPS is enough (2 GB if you build with `INSTALL_PLAYWRIGHT=1`).
2. Install Docker, clone the repo, `cp .env.example .env`, set a
   strong `OLR_SCOUT_PASSWORD`, `OLR_SCOUT_SECRET` and `OLR_SCOUT_CONTACT`.
3. `docker compose up -d --build`. The container listens on 127.0.0.1:8000 only.
4. Put HTTPS in front (needed for the PWA install and web push), e.g. Caddy:
   ```
   scout.example.co.za {
     reverse_proxy 127.0.0.1:8000
   }
   ```
5. Web push: `npx web-push generate-vapid-keys`, put the keys in `.env`, restart,
   then **Watchlist → Enable phone notifications** on the phone (on iPhone, add to
   home screen first).
6. Back up the `olr-data` volume (`/app/backend/data/olr_scout.db`).
7. Postgres instead of SQLite: set `OLR_SCOUT_DATABASE_URL=postgresql+psycopg://…`
   and `pip install psycopg[binary]`.

## How scoring works (short)

| Tier | Evidence | Score |
|---|---|---|
| A | The bird's own ring matched to OLR results | Bid Score: 50% long-race + 15% consistency + 10% final + 20% family + 5% siblings |
| B | Sire/dam/grandparent rings verified in OLR results | Ancestors' Bid Scores (parents ×1, grandparents ×0.5), × seller reliability |
| C | Seller text/image only | Bloodline match + seller record, **capped at 60**, labelled "seller-claimed, unverified" |
| D | Nothing usable | Shown in lists, never suggested |

A higher tier always ranks above a lower one. Details:

* percentile = position ÷ birds arrived; a race the bird missed counts as 1.0.
* long score = mean percentile over the season's 5 longest races.
* ace = top 5% of registered birds by long score (field ace rate 5% by construction).
* family ace rate = (aces + 0.05 × 20) ÷ (entries + 20), teams grouped by stripping
  I/II/A/B/C/(Single) and ignoring partner order.
* Consistency (not defined in the brief, so chosen here): the share of the season's
  races the bird finished in the top half of arrivals.
* Components without data (no final flown, no family, no siblings) are left out
  and the other weights renormalised. Nothing is filled in with a guess.
* Preferences: Love ×1.15, Like ×1.07, Neutral ×1, Avoid = excluded. Tier C stays ≤ 60
  after the multiplier.
* Claim mismatch: the text says ace/winner/1st near an ancestor ring, but the matched
  bird is not an ace and its best race was worse than the 20th percentile (Settings).

All weights and thresholds are editable in **Settings**.

## How to add a new auction site

1. Create `backend/olr_scout/sources/<site>.py` with a class that subclasses
   `AuctionSource` (`sources/base.py`): set `key`, `name`, `base_url`, and implement
   `fetch_active() -> list[Auction]` and `fetch_lots(auction) -> list[Lot]`
   (optionally `refresh_lot(lot)` for the 20 s hot refresh).
2. Fetch only through `self.client` (the shared `PoliteClient`): it enforces the
   User-Agent, 1 request/second per host, caching and block detection.
3. Reuse what exists: `sources/woo.py` for WooCommerce shops, `sources/genericjson.py`
   for JSON APIs, `sources/render.py` (Playwright) for SPAs with no usable API.
   Parse rings with `rings.parse_ring` / `rings.find_rings`; tag the OLR with
   `base.tag_olr`.
4. Add it to `ADAPTERS` in `sources/registry.py`.
5. Record fixtures (`scripts/record_fixtures.py --only <key>`), add routes for them
   in `tests/fakeweb.py`, and write tests like `tests/test_adapters.py`.
6. Add its endpoints and verification status to `docs/sources.md`.

## What this app cannot tell you

* Most pedigree ancestors raced from home lofts, not OLRs, so Tier B covers a minority
  of lots. Home-loft claims stay "claimed".
* OLR results show that a family performs in OLR conditions; they do not prove it breeds
  winners. Seller reliability and family offspring records are the proxy.
* About 37% of entries reach an OLR Final, so winning stays largely luck. The Family
  Builder aims to raise the odds through volume of well-bred birds, not to pick a winner.
* Price does not track form: across AfrikaPro auctions the brief found Spearman 0.07
  between price and race form, so the app never rewards a high price.
