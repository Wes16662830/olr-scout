from __future__ import annotations

from ..util.http import PoliteClient
from .afripigeon import AfriPigeonSource
from .base import AuctionSource
from .bestpigeon import BestPigeonSource
from .elite import EliteSource
from .pah import PigeonAuctionHouseSource
from .toppigeon import TopPigeonSource

ADAPTERS: list[type[AuctionSource]] = [
    TopPigeonSource,
    EliteSource,
    BestPigeonSource,
    AfriPigeonSource,
    PigeonAuctionHouseSource,
]


def build_sources(client: PoliteClient) -> dict[str, AuctionSource]:
    return {cls.key: cls(client) for cls in ADAPTERS}


def disabled_keys(s) -> set[str]:
    """Auction sites switched off in Settings (a site with no row is on)."""
    from sqlalchemy import select

    from ..models import Source

    return {r.id for r in s.scalars(select(Source).where(Source.enabled.is_(False)))}


def set_enabled(s, key: str, on: bool) -> None:
    from ..models import Source

    cls = next((c for c in ADAPTERS if c.key == key), None)
    if cls is None:
        raise KeyError(key)
    row = s.get(Source, key) or Source(id=key, name=cls.name, base_url=cls.base_url)
    row.enabled = bool(on)
    s.add(row)
