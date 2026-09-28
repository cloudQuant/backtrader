"""Exchange-agnostic contracts for tick collection.

The main collection flow depends only on these protocols and on
``TickRecord``.  Concrete exchange implementations (CTP first) live in
``bt_api_ctp.collector_ctp``.  No exchange-specific type may leak into
this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

#: Domestic futures exchanges reachable through CTP.
EXCHANGES: tuple[str, ...] = ("SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX")

#: Instrument classes collected by default.  The reference universe also
#: contains combination/tas/spot/efp/mi contracts, which carry no ordinary
#: depth quote and are excluded unless a caller opts in.  ``spot_option``
#: is included because CFFEX classifies its index options (IO/MO/HO) that
#: way, and they are ordinary tradeable options.
DEFAULT_ASSET_TYPES: tuple[str, ...] = ("future", "option", "spot_option")


@dataclass(frozen=True)
class InstrumentSpec:
    """One tradable contract from an exchange's reference universe."""

    instrument_id: str
    exchange_id: str
    asset_type: str
    underlying_instrument: str | None = None
    strike_price: float | None = None
    option_type: str | None = None
    product_id: str | None = None


@dataclass(frozen=True)
class TickRecord:
    """One normalized depth-market snapshot.

    Identity and time-key fields are required.  Quote fields mirror the
    native CTP ``CThostFtdcDepthMarketDataField`` member set so that a
    snapshot is never truncated; unavailable native sentinels (``DBL_MAX``
    or non-finite values) are normalized to ``None``.
    """

    # Identity and time key (required)
    exchange_id: str
    instrument_id: str
    trading_day: str
    action_day: str
    update_time: str
    update_millisec: int
    local_receive_time: int

    # Identity (optional)
    exchange_inst_id: str | None = None

    # Quote fields
    last_price: float | None = None
    pre_settlement: float | None = None
    pre_close: float | None = None
    pre_open_interest: float | None = None
    open_price: float | None = None
    highest_price: float | None = None
    lowest_price: float | None = None
    volume: int | None = None
    turnover: float | None = None
    open_interest: float | None = None
    close_price: float | None = None
    settlement_price: float | None = None
    upper_limit: float | None = None
    lower_limit: float | None = None
    pre_delta: float | None = None
    curr_delta: float | None = None
    average_price: float | None = None
    banding_upper_price: float | None = None
    banding_lower_price: float | None = None

    # Order book depth (five levels; missing levels are ``None``)
    bid_price: tuple[float | None, ...] = ()
    bid_volume: tuple[int | None, ...] = ()
    ask_price: tuple[float | None, ...] = ()
    ask_volume: tuple[int | None, ...] = ()


@runtime_checkable
class InstrumentProvider(Protocol):
    """Supplies the exchange's currently valid instrument universe."""

    def fetch_instruments(self) -> list[InstrumentSpec]:
        """Return every contract valid today (futures and options)."""
        ...


@runtime_checkable
class TickHandler(Protocol):
    """Receives one normalized tick; called on the market-data thread."""

    def on_tick(self, tick: TickRecord) -> None:
        """Handle a tick.  Must stay lightweight: no IO, no heavy compute."""
        ...


@runtime_checkable
class MarketDataSubscriber(Protocol):
    """Connects to a venue and delivers normalized ticks to a handler."""

    def connect(self) -> None: ...

    def subscribe(self, instruments: list[str]) -> None: ...

    def set_handler(self, handler: TickHandler) -> None: ...

    def run(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class TickNormalizer(Protocol):
    """Converts one native venue payload into a ``TickRecord``."""

    def normalize(self, raw: Any) -> TickRecord | None:
        """Return ``None`` when the payload carries no usable identity."""
        ...


__all__ = [
    "DEFAULT_ASSET_TYPES",
    "EXCHANGES",
    "InstrumentProvider",
    "InstrumentSpec",
    "MarketDataSubscriber",
    "TickHandler",
    "TickNormalizer",
    "TickRecord",
]
