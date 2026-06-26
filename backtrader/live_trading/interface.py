"""
Backtrader 实盘交易模块

提供实盘交易的抽象接口和基础实现
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class LiveOrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class LiveOrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class LiveOrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class LivePositionSide(str, Enum):
    """持仓方向"""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class LiveOrder:
    """实盘订单"""
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
        created_at: datetime = None,
        updated_at: datetime = None,
        filled_at: Optional[datetime] = None,
        rejected_reason: Optional[str] = None,
    ):
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
    """实盘持仓"""
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
        self.symbol = symbol
        self.size = size
        self.avg_price = avg_price
        self.side = side
        self.market_value = market_value
        self.unrealized_pnl = unrealized_pnl
        self.unrealized_pnl_pct = unrealized_pnl_pct


class LiveTrade:
    """实盘成交"""
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
        created_at: datetime = None,
    ):
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
    """实盘账户"""
    def __init__(
        self,
        cash: float,
        total_equity: float,
        available_cash: float,
        buying_power: float,
        margin: float = 0.0,
        maintenance_margin: float = 0.0,
    ):
        self.cash = cash
        self.total_equity = total_equity
        self.available_cash = available_cash
        self.buying_power = buying_power
        self.margin = margin
        self.maintenance_margin = maintenance_margin


class LiveTick:
    """实盘行情"""
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
    """实盘券商抽象接口"""

    @abstractmethod
    def connect(self, config: Dict[str, Any]) -> bool:
        """
        连接券商

        Args:
            config: 连接配置

        Returns:
            bool: 是否连接成功
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        断开连接
        """
        pass

    @abstractmethod
    def get_account(self) -> LiveAccount:
        """
        获取账户信息

        Returns:
            LiveAccount: 账户信息
        """
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[LivePosition]:
        """
        获取持仓

        Args:
            symbol: 标的代码

        Returns:
            LivePosition or None: 持仓信息
        """
        pass

    @abstractmethod
    def get_positions(self) -> List[LivePosition]:
        """
        获取所有持仓

        Returns:
            List[LivePosition]: 持仓列表
        """
        pass

    @abstractmethod
    def place_order(self, order: LiveOrder) -> LiveOrder:
        """
        下单

        Args:
            order: 订单对象

        Returns:
            LiveOrder: 订单对象
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单

        Args:
            order_id: 订单 ID

        Returns:
            bool: 是否撤销成功
        """
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[LiveOrder]:
        """
        查询订单

        Args:
            order_id: 订单 ID

        Returns:
            LiveOrder or None: 订单信息
        """
        pass

    @abstractmethod
    def get_orders(self, status: Optional[LiveOrderStatus] = None) -> List[LiveOrder]:
        """
        查询所有订单

        Args:
            status: 订单状态（可选）

        Returns:
            List[LiveOrder]: 订单列表
        """
        pass

    @abstractmethod
    def get_trades(self, symbol: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[LiveTrade]:
        """
        查询成交

        Args:
            symbol: 标的代码（可选）
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            List[LiveTrade]: 成交列表
        """
        pass

    @abstractmethod
    def subscribe_tick(self, symbols: List[str], callback: Callable[[LiveTick], None]) -> None:
        """
        订阅行情

        Args:
            symbols: 标的代码列表
            callback: 行情回调函数
        """
        pass

    @abstractmethod
    def unsubscribe_tick(self, symbols: List[str]) -> None:
        """
        取消订阅行情

        Args:
            symbols: 标的代码列表
        """
        pass

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        frequency: str = "1d",
    ) -> List[LiveTick]:
        """
        获取历史行情

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            frequency: 频率（1m, 5m, 15m, 30m, 1h, 1d, 1w, 1M）

        Returns:
            List[LiveTick]: 历史行情列表
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        检查是否已连接

        Returns:
            bool: 是否连接
        """
        pass


class LiveBrokerFactory:
    """实盘券商工厂"""

    _brokers = {
        "ccxt": "backtrader.live_trading.ccxt_broker.CCXTBroker",
        "ctp": "backtrader.live_trading.ctp_broker.CTPBroker",
        # 可以添加更多券商
    }

    @classmethod
    def create_broker(cls, broker_type: str, config: Dict[str, Any]) -> LiveBroker:
        """
        创建券商实例

        Args:
            broker_type: 券商类型
            config: 券商配置

        Returns:
            LiveBroker: 券商实例
        """
        broker_class_path = cls._brokers.get(broker_type.lower())
        if not broker_class_path:
            raise ValueError(f"不支持的券商类型: {broker_type}")

        # 动态导入券商类
        parts = broker_class_path.split('.')
        module_path = '.'.join(parts[:-1])
        class_name = parts[-1]

        module = __import__(module_path, fromlist=[class_name])
        broker_class = getattr(module, class_name)

        # 创建实例
        return broker_class(config)

    @classmethod
    def register_broker(cls, broker_type: str, broker_class_path: str):
        """
        注册券商类型

        Args:
            broker_type: 券商类型
            broker_class_path: 券商类路径
        """
        cls._brokers[broker_type.lower()] = broker_class_path
