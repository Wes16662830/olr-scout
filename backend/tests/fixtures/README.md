# Test fixtures

**Everything in these folders except `recorded/` is SYNTHETIC.** The sites were
not reachable from the build environment, so these files were hand-written to
the page/JSON structure described in the build brief (WooCommerce `li.product`,
"Current bid" labels, Supabase REST rows, Benzing paginated results …). They
test the parsers' logic; they do **not** prove the parsers match today's live
markup. Names, rings and prices in them are made up.

Real captures go in `recorded/<source>/` via:

    python scripts/record_fixtures.py --out tests/fixtures/recorded

Acceptance tests that need real data (AfrikaPro Auction 1 totals, Lot 163 /
169 long scores, AfrikaPro 2026 team/arrival counts) skip until those
recordings exist. See `tests/test_acceptance_recorded.py`.
