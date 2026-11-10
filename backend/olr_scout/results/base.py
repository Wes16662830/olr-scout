"""Results source interface (OLR race results)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LoftInfo:
    id: int
    name: str


@dataclass
class SeasonInfo:
    id: int
    year: int
    name: str = ""


@dataclass
class FlightInfo:
    id: int
    name: str
    distance_km: float | None = None
    flown_at: datetime | None = None
    is_training: bool = False
    is_final: bool = False
    race_no: int | None = None
    basketed: int | None = None
    arrived: int | None = None


@dataclass
class ResultRow:
    ring_raw: str
    position: int | None
    team: str | None = None
    name: str | None = None
    speed: float | None = None
    sex: str | None = None
    colour: str | None = None
    team_country: str | None = None


@dataclass
class FlightResults:
    flight_id: int
    rows: list[ResultRow]
    total: int | None
    complete: bool  # rows == total
    note: str = ""


@dataclass
class TeamEntry:
    team: str
    rings: list[str]
    registered: int | None = None  # registered_pigeons_count (rings are not listed)


@dataclass
class RaceLine:
    olr: str
    season_year: int
    flight: str
    distance_km: float | None
    position: int | None
    arrived: int | None
    registered: int | None
    percentile: float  # position / arrived; 1.0 if missing


@dataclass
class BirdRecord:
    ring_norm: str
    found: bool
    team: str | None = None
    races: list[RaceLine] = field(default_factory=list)


class HealthError(Exception):
    """The unofficial endpoint answered but not in the expected shape."""


class ResultsSource(ABC):
    key = "results"

    @abstractmethod
    def list_lofts(self) -> list[LoftInfo]: ...

    @abstractmethod
    def list_seasons(self, loft_id: int) -> list[SeasonInfo]: ...

    @abstractmethod
    def list_flights(self, season_id: int) -> list[FlightInfo]: ...

    @abstractmethod
    def flight_results(self, flight_id: int) -> FlightResults: ...

    @abstractmethod
    def season_teams(self, season_id: int) -> list[TeamEntry]: ...

    @abstractmethod
    def health_check(self) -> dict: ...

    def get_race_history(self, ring_norm: str) -> BirdRecord:  # pragma: no cover - DB-backed in ingest
        raise NotImplementedError("use olr_scout.results.ingest.race_history(session, ring_norm)")


FINAL_QUIET_DAYS = 14


def mark_assumed_final(flights: list, now) -> None:
    """Some OLRs (AfrikaPro 2026) don't name their final: it is just "Race 10". When no race
    is called a final, the season's last race is taken as the final if it is also its longest
    and nothing has been flown for FINAL_QUIET_DAYS since (so a season still racing is left
    alone). Works on FlightInfo and stored Flight rows (is_training, is_final, flown_at,
    distance_km)."""
    from datetime import timedelta

    from ..util.timeutil import as_aware

    races = [f for f in flights if not f.is_training]
    if not races or any(f.is_final for f in races):
        return
    dated = [f for f in races if f.flown_at is not None]
    if not dated:
        return
    last = max(dated, key=lambda f: as_aware(f.flown_at))
    longest = max((f.distance_km or 0) for f in races)
    if (last.distance_km or 0) >= longest > 0 and as_aware(last.flown_at) <= now - timedelta(days=FINAL_QUIET_DAYS):
        last.is_final = True
