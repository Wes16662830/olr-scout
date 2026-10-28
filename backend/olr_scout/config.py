"""Runtime configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Johannesburg")
USER_AGENT = (
    "OLRScout/0.1 (+personal research tool; read-only; contact: set OLR_SCOUT_CONTACT) "
    "python-httpx"
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("OLR_SCOUT_DATABASE_URL", "sqlite:///./data/olr_scout.db")
    )
    password: str = field(default_factory=lambda: _env("OLR_SCOUT_PASSWORD", ""))
    secret_key: str = field(default_factory=lambda: _env("OLR_SCOUT_SECRET", ""))
    contact: str = field(default_factory=lambda: _env("OLR_SCOUT_CONTACT", ""))
    cache_dir: Path = field(default_factory=lambda: Path(_env("OLR_SCOUT_CACHE_DIR", "./data/cache")))
    # Polling. The hard floor for a full refresh is 60 s and 20 s for the hot
    # (closing within 10 min) refresh; lower values are clamped up.
    full_refresh_seconds: int = field(
        default_factory=lambda: max(60, int(_env("OLR_SCOUT_FULL_REFRESH_SECONDS", "600")))
    )
    hot_refresh_seconds: int = field(
        default_factory=lambda: max(20, int(_env("OLR_SCOUT_HOT_REFRESH_SECONDS", "20")))
    )
    hot_window_minutes: int = 10
    min_host_interval: float = 1.0  # max 1 request/sec per host
    raw_payload_days: int = 30
    benzing_base_url: str = field(
        default_factory=lambda: _env("OLR_SCOUT_BENZING_BASE_URL", "https://oneloftrace.live")
    )
    enable_scheduler: bool = field(default_factory=lambda: _env("OLR_SCOUT_SCHEDULER", "1") == "1")
    vapid_private_key: str = field(default_factory=lambda: _env("OLR_SCOUT_VAPID_PRIVATE_KEY", ""))
    vapid_public_key: str = field(default_factory=lambda: _env("OLR_SCOUT_VAPID_PUBLIC_KEY", ""))
    vapid_subject: str = field(default_factory=lambda: _env("OLR_SCOUT_VAPID_SUBJECT", "mailto:admin@localhost"))

    @property
    def user_agent(self) -> str:
        if self.contact:
            return USER_AGENT.replace("set OLR_SCOUT_CONTACT", self.contact)
        return USER_AGENT


settings = Settings()
