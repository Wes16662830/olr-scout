#!/usr/bin/env python3
"""Ingest OLR results now (same as the nightly job). Usage: python scripts/ingest_results.py [OLR name ...]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from olr_scout.db import init_db  # noqa: E402
from olr_scout.results.ingest import seed_registry  # noqa: E402
from olr_scout.db import session_scope  # noqa: E402

init_db()
with session_scope() as s:
    seed_registry(s)
from olr_scout.scheduler import job_nightly_results  # noqa: E402

print(job_nightly_results(sys.argv[1:] or None))
