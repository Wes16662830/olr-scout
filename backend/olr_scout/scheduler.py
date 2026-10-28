"""Background jobs: full refresh, hot refresh (lots closing soon), nightly results."""

from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .config import TZ, settings
from .db import SessionLocal
from .models import Lot, Olr, Season
from .refresh import hot_refresh, refresh_all
from .results.benzing import BenzingResultsSource
from .results.ingest import ingest_all
from .sources.registry import build_sources
from .util.http import PoliteClient

log = logging.getLogger(__name__)

_lock = threading.Lock()  # one full refresh / results ingest at a time
_hot_lock = threading.Lock()  # the 20 s near-close refresh runs even during a long full refresh
client = PoliteClient()
sources = build_sources(client)
results_source = BenzingResultsSource(client)


def is_busy() -> bool:
    return _lock.locked()


def _locked(fn):
    def run(*a, **kw):
        if not _lock.acquire(blocking=False):
            log.info("skip %s: another job is running", fn.__name__)
            return None
        try:
            return fn(*a, **kw)
        finally:
            _lock.release()

    run.__name__ = fn.__name__
    return run


@_locked
def job_full_refresh(only: list[str] | None = None):
    with SessionLocal() as s:
        reports = refresh_all(s, sources, only)
    job_results_for_live_lots()
    return reports


def job_hot_refresh():
    if not _hot_lock.acquire(blocking=False):
        return None
    try:
        with SessionLocal() as s:
            return hot_refresh(s, sources)
    finally:
        _hot_lock.release()


def job_results_for_live_lots():
    """Ingest on demand any OLR that a live lot refers to and that has un-ingested seasons."""
    with SessionLocal() as s:
        tags = {t for (t,) in s.execute(select(Lot.olr_tag).where(Lot.status == "live", Lot.olr_tag.is_not(None)))}
        names = []
        for olr in s.scalars(select(Olr).where(Olr.name.in_(tags))):
            if any(season.ingested_at is None for season in s.scalars(select(Season).where(Season.olr_id == olr.id))):
                names.append(olr.name)
        if not names:
            return None
        try:
            report = ingest_all(s, results_source, names, only_missing=True)
            s.commit()
            return report
        except Exception:
            s.commit()  # keep the health row
            log.exception("on-demand results ingest")
            return None


@_locked
def job_nightly_results(olr_names: list[str] | None = None):
    with SessionLocal() as s:
        try:
            report = ingest_all(s, results_source, olr_names)
        except Exception:
            s.commit()
            log.exception("nightly results ingest")
            return None
        from .scoring import engine, seller

        seller.recompute(s)
        engine.score_all(s)
        s.commit()
        return report


scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global scheduler
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(job_full_refresh, "interval", seconds=settings.full_refresh_seconds, id="full",
                      max_instances=1, coalesce=True, next_run_time=None)
    scheduler.add_job(job_hot_refresh, "interval", seconds=settings.hot_refresh_seconds, id="hot",
                      max_instances=1, coalesce=True)
    scheduler.add_job(job_nightly_results, CronTrigger(hour=2, minute=30, timezone=TZ), id="nightly",
                      max_instances=1, coalesce=True)
    scheduler.start()
    # First full refresh shortly after start-up.
    from datetime import datetime, timedelta

    scheduler.modify_job("full", next_run_time=datetime.now(TZ) + timedelta(seconds=10))
    return scheduler
