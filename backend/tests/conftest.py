import os

os.environ["OLR_SCOUT_SKIP_ENV_FILE"] = "1"  # tests never read your real .env

os.environ.setdefault("OLR_SCOUT_SCHEDULER", "0")
os.environ.setdefault("OLR_SCOUT_DATABASE_URL", "sqlite://")
os.environ.setdefault("OLR_SCOUT_PASSWORD", "test-password")

import pytest

from olr_scout import db
from olr_scout.util.http import PoliteClient

from .fakeweb import default_web


@pytest.fixture()
def web():
    return default_web()


@pytest.fixture()
def client(web):
    sleeps = []
    c = PoliteClient(transport=web.transport(), min_interval=1.0, cache_seconds=0, sleep=sleeps.append)
    c.sleeps = sleeps
    return c


@pytest.fixture()
def session():
    db.configure("sqlite://")
    db.init_db()
    s = db.SessionLocal()
    from olr_scout.results.ingest import seed_registry

    seed_registry(s)
    s.commit()
    yield s
    s.close()
    db.Base.metadata.drop_all(db.engine)
