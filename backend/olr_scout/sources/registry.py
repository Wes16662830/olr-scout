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
