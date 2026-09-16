"""Backtrader live-trading module.

Provides the abstract interfaces and base implementations used for live
trading.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, cast

logger = logging.getLogger(__name__)


class LiveOrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class LiveOrderSide(str, Enum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class LiveOrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class LivePositionSide(str, Enum):
    """Position side."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class LiveOrder:
    """Live order."""

    def __init__(
        self,
        order_id: str,
        symbol: str,
        order_type: LiveOrderType,
        side: LiveOrderSide,
        size: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        filled_size: float = 0.0,
        avg_fill_price: float = 0.0,
        status: LiveOrderStatus = LiveOrderStatus.PENDING,
        commission: float = 0.0,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        filled_at: Optional[datetime] = None,
        rejected_reason: Optional[str] = None,
    ):
        """Create a live order.

        Args:
            order_id: Unique order identifier.
            symbol: Instrument symbol.
            order_type: Order type.
            side: Order side.
            size: Order size.
            price: Order price.
            stop_price: Trigger price for stop orders.
            limit_price: Limit price for stop-limit orders.
            filled_size: Cumulative filled size.
            avg_fill_price: Average fill price.
            status: Current order status.
            commission: Accumulated commission.
            created_at: Creation timestamp; defaults to now (UTC).
            updated_at: Last-update timestamp; defaults to now (UTC).
            filled_at: Fill timestamp, if the order has been filled.
            rejected_reason: Reason reported when the order was rejected.
        """
        self.order_id = order_id
        self.symbol = symbol
        self.order_type = order_type
        self.side = side
        self.size = size
        self.price = price
        self.stop_price = stop_price
        self.limit_price = limit_price
        self.filled_size = filled_size
        self.avg_fill_price = avg_fill_price
        self.status = status
        self.commission = commission
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.filled_at = filled_at
        self.rejected_reason = rejected_reason


class LivePosition:
    """Live position."""

    def __init__(
        self,
        symbol: str,
        size: float,
        avg_price: float,
        side: LivePositionSide,
        market_value: float,
        unrealized_pnl: float,
        unrealized_pnl_pct: float,
    ):
        """Create a live position snapshot.

        Args:
            symbol: Instrument symbol.
            size: Signed position size.
            avg_price: Average entry price.
            side: Position side.
            market_value: Current market value.
            unrealized_pnl: Unrealized profit and loss in account currency.
            unrealized_pnl_pct: Unrealized profit and loss as a ratio.
        """
        self.symbol = symbol
        self.size = size
        self.avg_price = avg_price
        self.side = side
        self.market_value = market_value
        self.unrealized_pnl = unrealized_pnl
        self.unrealized_pnl_pct = unrealized_pnl_pct


class LiveTrade:
    """Live trade (fill)."""

    def __init__(
        self,
        trade_id: str,
        order_id: str,
        symbol: str,
        side: LiveOrderSide,
        size: float,
        price: float,
        commission: float,
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        created_at: Optional[datetime] = None,
    ):
        """Create a live trade record.

        Args:
            trade_id: Unique trade identifier.
            order_id: Identifier of the order that produced this trade.
            symbol: Instrument symbol.
            side: Trade side.
            size: Filled size.
            price: Fill price.
            commission: Commission charged for this fill.
            pnl: Realized profit and loss in account currency.
            pnl_pct: Realized profit and loss as a ratio.
            created_at: Trade timestamp; defaults to now (UTC).
        """
        self.trade_id = trade_id
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.size = size
        self.price = price
        self.commission = commission
        self.pnl = pnl
        self.pnl_pct = pnl_pct
        self.created_at = created_at or datetime.utcnow()


class LiveAccount:
    """Live account snapshot."""

    def __init__(
        self,
        cash: float,
        total_equity: float,
        available_cash: float,
        buying_power: float,
        margin: float = 0.0,
        maintenance_margin: float = 0.0,
    ):
        """Create a live account snapshot.

        Args:
            cash: Settled cash balance.
            total_equity: Total account equity.
            available_cash: Cash available for new positions.
            buying_power: Broker-reported buying power.
            margin: Margin currently in use.
            maintenance_margin: Maintenance margin requirement.
        """
        self.cash = cash
        self.total_equity = total_equity
        self.available_cash = available_cash
        self.buying_power = buying_power
        self.margin = margin
        self.maintenance_margin = maintenance_margin


class LiveTick:
    """Live tick (market data snapshot)."""

    def __init__(
        self,
        symbol: str,
        timestamp: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        bid_size: Optional[float] = None,
        ask_size: Optional[float] = None,
    ):
        """Create a live tick.

        Args:
            symbol: Instrument symbol.
            timestamp: Tick timestamp.
            open: Open price of the bar this tick belongs to.
            high: High price of the bar this tick belongs to.
            low: Low price of the bar this tick belongs to.
            close: Close (last) price.
            volume: Traded volume.
            bid: Best bid price, if available.
            ask: Best ask price, if available.
            bid_size: Size available at the best bid.
            ask_size: Size available at the best ask.
        """
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.bid = bid
        self.ask = ask
        self.bid_size = bid_size
        self.ask_size = ask_size


class LiveBroker(ABC):
    """Abstract live-broker interface."""

    @abstractmethod
    def connect(self, config: Dict[str, Any]) -> bool:
        """Connect to the broker.

        Args:
            config: Connection configuration.

        Returns:
            bool: Whether the connection succeeded.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the broker."""

    @abstractmethod
    def get_account(self) -> LiveAccount:
        """Fetch the account snapshot.

        Returns:
            LiveAccount: Account snapshot.
        """

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[LivePosition]:
        """Fetch a single position.

        Args:
            symbol: Instrument symbol.

        Returns:
            LivePosition or None: Position snapshot, or None if there is no
            position for the symbol.
        """

    @abstractmethod
    def get_positions(self) -> List[LivePosition]:
        """Fetch all open positions.

        Returns:
            List[LivePosition]: Position list.
        """

    @abstractmethod
    def place_order(self, order: LiveOrder) -> LiveOrder:
        """Submit an order.

        Args:
            order: Order to submit.

        Returns:
            LiveOrder: The order as accepted by the broker.
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order identifier.

        Returns:
            bool: Whether the cancellation succeeded.
        """

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[LiveOrder]:
        """Fetch a single order.

        Args:
            order_id: Order identifier.

        Returns:
            LiveOrder or None: Order snapshot, or None if the order is unknown.
        """

    @abstractmethod
    def get_orders(self, status: Optional[LiveOrderStatus] = None) -> List[LiveOrder]:
        """Fetch all orders.

        Args:
            status: Restrict the result to one order status, if given.

        Returns:
            List[LiveOrder]: Order list.
        """

    @abstractmethod
    def get_trades(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[LiveTrade]:
        """Fetch trade (fill) history.

        Args:
            symbol: Restrict the result to one instrument, if given.
            start_date: Inclusive lower bound on the trade timestamp, if given.
            end_date: Inclusive upper bound on the trade timestamp, if given.

        Returns:
            List[LiveTrade]: Trade list.
        """

    @abstractmethod
    def subscribe_tick(self, symbols: List[str], callback: Callable[[LiveTick], None]) -> None:
        """Subscribe to market data.

        Args:
            symbols: Instrument symbols to subscribe to.
            callback: Callable invoked with each incoming tick.
        """

    @abstractmethod
    def unsubscribe_tick(self, symbols: List[str]) -> None:
        """Unsubscribe from market data.

        Args:
            symbols: Instrument symbols to unsubscribe from.
        """

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        frequency: str = "1d",
    ) -> List[LiveTick]:
        """Fetch historical market data.

        Args:
            symbol: Instrument symbol.
            start_date: Inclusive start of the requested range.
            end_date: Inclusive end of the requested range.
            frequency: Bar frequency (1m, 5m, 15m, 30m, 1h, 1d, 1w, 1M).

        Returns:
            List[LiveTick]: Historical bar list.
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Report whether the broker session is currently connected.

        Returns:
            bool: Whether the session is connected.
        """


class LiveBrokerFactory:
    """Live-broker factory."""

    _brokers = {
        "ccxt": "backtrader.live_trading.ccxt_broker.CCXTBroker",
        "ctp": "backtrader.live_trading.ctp_broker.CTPBroker",
        # More broker types can be registered here.
    }

    @classmethod
    def create_broker(cls, broker_type: str, config: Dict[str, Any]) -> LiveBroker:
        """Create a broker instance.

        Args:
            broker_type: Broker type key, as registered on this factory.
            config: Broker configuration.

        Returns:
            LiveBroker: The broker instance.

        Raises:
            ValueError: If ``broker_type`` has not been registered.
        """
        broker_class_path = cls._brokers.get(broker_type.lower())
        if not broker_class_path:
            raise ValueError(f"Unsupported broker type: {broker_type}")

        # Import the broker class dynamically.
        parts = broker_class_path.split(".")
        module_path = ".".join(parts[:-1])
        class_name = parts[-1]

        module = __import__(module_path, fromlist=[class_name])
        broker_class = getattr(module, class_name)

        # Create the instance.
        return cast(LiveBroker, broker_class(config))

    @classmethod
    def register_broker(cls, broker_type: str, broker_class_path: str):
        """Register a broker type.

        Args:
            broker_type: Broker type key.
            broker_class_path: Fully qualified path of the broker class.
        """
        cls._brokers[broker_type.lower()] = broker_class_path
