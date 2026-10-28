"""Data model. All datetimes are stored as UTC."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .util.timeutil import now_utc


class Source(Base):
    __tablename__ = "source"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # adapter key
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="auction")  # auction | results
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceHealth(Base):
    __tablename__ = "source_health"
    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # ok|degraded|empty|error|unverified
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lot_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Auction(Base):
    __tablename__ = "auction"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(300))
    seller: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    olr_tag: Mapped[str | None] = mapped_column(String(80))  # e.g. "AfrikaPro"
    olr_year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="live")  # live|upcoming|closed
    lot_count: Mapped[int | None] = mapped_column(Integer)
    first_close: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results_link: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Lot(Base):
    __tablename__ = "lot"
    __table_args__ = (UniqueConstraint("source", "auction_id", "lot_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    auction_id: Mapped[str] = mapped_column(String(200), index=True)
    auction_name: Mapped[str | None] = mapped_column(String(300))
    lot_key: Mapped[str] = mapped_column(String(300))  # stable id within source (url or row id)
    seller: Mapped[str | None] = mapped_column(String(200), index=True)
    lot_no: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="")
    ring_raw: Mapped[str | None] = mapped_column(String(80))
    ring_norm: Mapped[str | None] = mapped_column(String(80), index=True)
    sex: Mapped[str | None] = mapped_column(String(10))
    year: Mapped[int | None] = mapped_column(Integer)
    colour: Mapped[str | None] = mapped_column(String(60))
    sire: Mapped[str | None] = mapped_column(Text)
    dam: Mapped[str | None] = mapped_column(Text)
    bloodline: Mapped[str | None] = mapped_column(Text)
    pedigree_text: Mapped[str | None] = mapped_column(Text)
    pedigree_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    performance_claims: Mapped[str | None] = mapped_column(Text)
    current_bid: Mapped[int | None] = mapped_column(Integer)
    starting_bid: Mapped[int | None] = mapped_column(Integer)
    reserve_price: Mapped[int | None] = mapped_column(Integer)
    reserve_met: Mapped[bool | None] = mapped_column(Boolean)
    bid_count: Mapped[int | None] = mapped_column(Integer)
    leading_bidder: Mapped[str | None] = mapped_column(String(120))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str] = mapped_column(String(500))
    image_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="live")  # live|upcoming|closed|sold|unsold
    olr_tag: Mapped[str | None] = mapped_column(String(80))
    olr_year: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Matching
    bird_id: Mapped[int | None] = mapped_column(ForeignKey("bird.id"))
    match_confidence: Mapped[str] = mapped_column(String(12), default="none")
    match_note: Mapped[str | None] = mapped_column(Text)
    override_bird_id: Mapped[int | None] = mapped_column(Integer)
    override_none: Mapped[bool] = mapped_column(Boolean, default=False)  # "this lot has no results"
    # Scoring (cached; recomputed after each refresh)
    tier: Mapped[str | None] = mapped_column(String(1))
    score: Mapped[float | None] = mapped_column(Float)
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    family_tags: Mapped[list] = mapped_column(JSON, default=list)
    claim_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    own_lot: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    bird = relationship("Bird", foreign_keys=[bird_id])
    bids = relationship("BidHistory", cascade="all, delete-orphan", order_by="BidHistory.at")


class LotPriceHistory(Base):
    __tablename__ = "lot_price_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    current_bid: Mapped[int | None] = mapped_column(Integer)
    bid_count: Mapped[int | None] = mapped_column(Integer)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BidHistory(Base):
    """Bid rows as the site shows them. Usernames are stored exactly as displayed."""

    __tablename__ = "bid_history"
    __table_args__ = (UniqueConstraint("lot_id", "bidder", "amount", "at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id", ondelete="CASCADE"), index=True)
    bidder: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[int | None] = mapped_column(Integer)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Olr(Base):
    __tablename__ = "olr"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    loft_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)  # strings matched in auction names
    auto_discovered: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    seasons = relationship("Season", back_populates="olr", cascade="all, delete-orphan")


class Season(Base):
    __tablename__ = "season"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Benzing season id
    olr_id: Mapped[int] = mapped_column(ForeignKey("olr.id"))
    year: Mapped[int] = mapped_column(Integer)
    registered: Mapped[int | None] = mapped_column(Integer)
    teams: Mapped[int | None] = mapped_column(Integer)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time the season was looked at and had no races yet (so it is not re-asked every refresh).
    no_races_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    olr = relationship("Olr", back_populates="seasons")
    flights = relationship("Flight", back_populates="season", cascade="all, delete-orphan")


class Flight(Base):
    __tablename__ = "flight"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Benzing flight id
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    race_no: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    flown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_training: Mapped[bool] = mapped_column(Boolean, default=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    basketed: Mapped[int | None] = mapped_column(Integer)
    arrived: Mapped[int | None] = mapped_column(Integer)
    total_rows: Mapped[int | None] = mapped_column(Integer)
    ingested_rows: Mapped[int | None] = mapped_column(Integer)
    season = relationship("Season", back_populates="flights")


class Bird(Base):
    __tablename__ = "bird"
    __table_args__ = (UniqueConstraint("season_id", "ring_norm"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"), index=True)
    ring_raw: Mapped[str] = mapped_column(String(80))
    ring_norm: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str | None] = mapped_column(String(300))
    team_country: Mapped[str | None] = mapped_column(String(10))
    family_key: Mapped[str | None] = mapped_column(String(300), index=True)
    sex: Mapped[str | None] = mapped_column(String(10))
    colour: Mapped[str | None] = mapped_column(String(60))
    is_ace: Mapped[bool] = mapped_column(Boolean, default=False)
    long_score: Mapped[float | None] = mapped_column(Float)
    all_score: Mapped[float | None] = mapped_column(Float)
    final_position: Mapped[int | None] = mapped_column(Integer)
    results = relationship("BirdResult", back_populates="bird", cascade="all, delete-orphan")
    season = relationship("Season")


class BirdResult(Base):
    __tablename__ = "bird_result"
    __table_args__ = (UniqueConstraint("bird_id", "flight_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bird_id: Mapped[int] = mapped_column(ForeignKey("bird.id", ondelete="CASCADE"), index=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flight.id", ondelete="CASCADE"), index=True)
    position: Mapped[int | None] = mapped_column(Integer)
    speed: Mapped[float | None] = mapped_column(Float)
    bird = relationship("Bird", back_populates="results")
    flight = relationship("Flight")


class AncestorClaim(Base):
    """A sire/dam/grandparent extracted from seller text, a PDF or an OCR'd image."""

    __tablename__ = "ancestor_claim"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(10))  # sire|dam|ss|sd|ds|dd|ancestor
    ring_raw: Mapped[str | None] = mapped_column(String(80))
    ring_norm: Mapped[str | None] = mapped_column(String(80), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    claim_text: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20))  # text|pdf|ocr|manual
    claims_ace: Mapped[bool] = mapped_column(Boolean, default=False)
    bird_id: Mapped[int | None] = mapped_column(ForeignKey("bird.id"))
    status: Mapped[str] = mapped_column(String(12), default="claimed")  # verified|claimed|mismatch|rejected
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False)


class Family(Base):
    __tablename__ = "family"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(300), unique=True)  # normalised team partnership
    display: Mapped[str] = mapped_column(String(300))


class FamilyStat(Base):
    __tablename__ = "family_stat"
    __table_args__ = (UniqueConstraint("family_key", "season_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_key: Mapped[str] = mapped_column(String(300), index=True)
    season_id: Mapped[int | None] = mapped_column(Integer)  # None = all seasons
    olr_id: Mapped[int | None] = mapped_column(Integer)
    entries: Mapped[int] = mapped_column(Integer, default=0)
    aces: Mapped[int] = mapped_column(Integer, default=0)
    finalists: Mapped[int] = mapped_column(Integer, default=0)
    ace_rate_shrunk: Mapped[float] = mapped_column(Float, default=0.05)
    best_long: Mapped[float | None] = mapped_column(Float)


class SellerStat(Base):
    __tablename__ = "seller_stat"
    seller_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    display: Mapped[str] = mapped_column(String(200))
    sold_raced: Mapped[int] = mapped_column(Integer, default=0)
    aces: Mapped[int] = mapped_column(Integer, default=0)
    ace_rate_shrunk: Mapped[float] = mapped_column(Float, default=0.05)
    factor: Mapped[float] = mapped_column(Float, default=1.0)


class Preference(Base):
    """Single-row-per-key settings store (JSON values)."""

    __tablename__ = "preference"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class LoftInventory(Base):
    __tablename__ = "loft_inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ring: Mapped[str] = mapped_column(String(80))
    ring_norm: Mapped[str] = mapped_column(String(80), index=True)
    sex: Mapped[str | None] = mapped_column(String(10))
    family: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(200))
    sire: Mapped[str | None] = mapped_column(String(200))
    dam: Mapped[str | None] = mapped_column(String(200))
    grandparents: Mapped[list] = mapped_column(JSON, default=list)  # [ss, sd, ds, dd]
    notes: Mapped[str | None] = mapped_column(Text)


class Plan(Base):
    __tablename__ = "plan"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    goal: Mapped[dict] = mapped_column(JSON, default=dict)
    items: Mapped[list] = mapped_column(JSON, default=list)
    total_max: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[list] = mapped_column(JSON, default=list)


class Watch(Base):
    __tablename__ = "watch"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    near_max_within: Mapped[int | None] = mapped_column(Integer)  # R; None = use global buffer
    closes_in: Mapped[list] = mapped_column(JSON, default=lambda: [30, 10])  # minutes
    above_max: Mapped[bool] = mapped_column(Boolean, default=True)
    lot = relationship("Lot")


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (UniqueConstraint("lot_id", "kind", "dedupe"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # closing|near_max|above_max
    dedupe: Mapped[str] = mapped_column(String(60), default="")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    pushed: Mapped[bool] = mapped_column(Boolean, default=False)


class PushSubscription(Base):
    __tablename__ = "push_subscription"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(800), unique=True)
    keys: Mapped[dict] = mapped_column(JSON, default=dict)


class RawPayload(Base):
    """Raw responses kept for debugging; purged after 30 days."""

    __tablename__ = "raw_payload"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    url: Mapped[str] = mapped_column(String(800))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
    status: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
