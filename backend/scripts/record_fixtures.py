#!/usr/bin/env python3
"""Record REAL fixtures from the live sites (run from a machine that can reach them).

Uses the same polite client as the app (clear User-Agent, ≤1 req/s per host,
stops on Cloudflare/Turnstile). Saves raw responses under
tests/fixtures/recorded/<source>/ and writes the summary JSON files the
recorded acceptance tests read.

    python scripts/record_fixtures.py --out tests/fixtures/recorded
    python scripts/record_fixtures.py --only benzing --season 2873
    python scripts/record_fixtures.py --only toppigeon --auction-url https://toppigeon.co.za/product-category/.../afrikapro-auction-1/ --auction-name afrikapro-auction-1

Check each site's terms of use before running this.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olr_scout.results.benzing import BenzingResultsSource  # noqa: E402
from olr_scout.sources.registry import build_sources  # noqa: E402
from olr_scout.util.http import PoliteClient, SourceBlocked  # noqa: E402


def slug(url: str) -> str:
    tail = url.split("://", 1)[-1].replace("/", "_").replace("?", "_")[:80]
    return f"{tail}-{hashlib.sha1(url.encode()).hexdigest()[:8]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/recorded")
    ap.add_argument("--only", nargs="*", help="toppigeon elite bestpigeon afripigeon pah benzing")
    ap.add_argument("--season", type=int, default=2873)
    ap.add_argument("--auction-url", help="a (closed) Top Pigeon auction category to summarise")
    ap.add_argument("--auction-name", default="afrikapro-auction-1")
    args = ap.parse_args()
    out = Path(args.out)
    client = PoliteClient(cache_seconds=0)
    current: dict[str, str] = {"src": "misc"}

    def save(url, status, text):
        d = out / current["src"]
        d.mkdir(parents=True, exist_ok=True)
        ext = ".json" if text.lstrip()[:1] in "[{" else ".html"
        (d / (slug(url) + ext)).write_text(text, encoding="utf-8")
        with open(d / "index.tsv", "a", encoding="utf-8") as f:
            f.write(f"{status}\t{url}\t{slug(url) + ext}\n")

    client.on_response = save
    only = set(args.only or ["toppigeon", "elite", "bestpigeon", "afripigeon", "pah", "benzing"])
    for key, src in build_sources(client).items():
        if key not in only:
            continue
        current["src"] = key
        try:
            auctions = src.fetch_active()
            for a in auctions[:3]:  # a sample is enough for fixtures
                src.fetch_lots(a)
            print(f"{key}: {len(auctions)} auctions recorded")
        except SourceBlocked as exc:
            print(f"{key}: BLOCKED ({exc}) — not retrying", file=sys.stderr)
        except Exception as exc:
            print(f"{key}: {type(exc).__name__}: {exc}", file=sys.stderr)

    if args.auction_url and "toppigeon" in only:
        from olr_scout.sources.base import Auction

        current["src"] = "toppigeon"
        tp = build_sources(client)["toppigeon"]
        lots = tp.fetch_lots(Auction("toppigeon", args.auction_url, args.auction_name, url=args.auction_url))
        sold = [l for l in lots if l.current_bid and l.bids]
        buyers = {max(l.bids, key=lambda b: b["amount"] or 0)["bidder"] for l in sold}
        summary = {"lots": len(lots), "sold": len(sold), "total_zar": sum(l.current_bid for l in sold),
                   "buyers": len(buyers)}
        (out / "toppigeon" / f"{args.auction_name}-summary.json").write_text(json.dumps(summary, indent=2))
        print("auction summary:", summary)

    if "benzing" in only:
        current["src"] = "benzing"
        bz = BenzingResultsSource(client)
        try:
            bz.health_check()
            flights = [f for f in bz.list_flights(args.season) if not f.is_training]
            teams = bz.season_teams(args.season)
            registered = {r for t in teams for r in t.rings}
            longest = max(flights, key=lambda f: f.distance_km or 0) if flights else None
            race10 = next((f for f in flights if f.race_no == 10), longest)
            res = bz.flight_results(race10.id) if race10 else None
            winner = next((r.ring_raw for r in (res.rows if res else []) if r.position == 1), None)
            summary = {"teams": len(teams), "registered": len(registered),
                       "race_10_arrivals": res.total if res else None, "race_10_winner": winner,
                       "mismatches": bz.mismatches}
            (out / "benzing" / f"season-{args.season}-summary.json").write_text(json.dumps(summary, indent=2))
            print("season summary:", summary)
        except Exception as exc:
            print(f"benzing: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
