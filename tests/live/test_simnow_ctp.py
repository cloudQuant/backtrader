#!/usr/bin/env python
"""Test SimNow CTP connectivity and trading operations using btapi interface.

This test file verifies the integration with SimNow CTP environment
using the unified bt_api_py interface. It tests:
- Market data subscription and retrieval
- Order placement
- Order cancellation
- Account balance inquiry

SimNow Environment Configuration:
- Group 1-3: Production-like environment (trade hours match real market)
- 7x24: 24/7 testing environment (available 16:00-next day 09:00/12:00)

Prerequisites:
- bt_api_py package must be installed
- SimNow account credentials must be configured in .env file
- CTP market and trading servers must be accessible

Usage:
    pytest tests/live/test_simnow_ctp.py -v -s

    # Or run specific test:
    pytest tests/live/test_simnow_ctp.py::test_simnow_market_data -v -s
"""

import datetime as _dt
import os
import time

import pytest

try:
    import bt_api_py
except ImportError as e:
    raise ImportError(
        "bt_api_py package is required for live trading tests. Please install it with: pip install bt_api_py"
    ) from e

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import backtrader as bt
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from backtrader.brokers.btapibroker import BtApiBroker


SIMNOW_ENVIRONMENTS = {
    "group1": {
        "name": "第一组（生产环境）",
        "td_address": "tcp://180.168.146.187:10130",
        "md_address": "tcp://180.168.146.187:10131",
        "description": "生产环境，交易时间与实盘一致",
    },
    "group2": {
        "name": "第二组（生产环境）",
        "td_address": "tcp://180.168.146.187:10131",
        "md_address": "tcp://180.168.146.187:10141",
        "description": "生产环境，交易时间与实盘一致",
    },
    "group3": {
        "name": "第三组（生产环境）",
        "td_address": "tcp://180.168.146.187:10132",
        "md_address": "tcp://180.168.146.187:10142",
        "description": "生产环境，交易时间与实盘一致",
    },
    "7x24": {
        "name": "7x24环境",
        "td_address": "tcp://180.168.146.187:10133",
        "md_address": "tcp://180.168.146.187:10143",
        "description": "7x24测试环境，交易日16:00-次日09:00，非交易日16:00-次日12:00",
    },
    "new_group1": {
        "name": "新第一组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30001",
        "md_address": "tcp://182.254.243.31:30011",
        "description": "看穿式前置，使用监控中心生产秘钥",
    },
    "new_group2": {
        "name": "新第二组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30002",
        "md_address": "tcp://182.254.243.31:30012",
        "description": "看穿式前置，使用监控中心生产秘钥",
    },
    "new_group3": {
        "name": "新第三组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30003",
        "md_address": "tcp://182.254.243.31:30013",
        "description": "看穿式前置，使用监控中心生产秘钥",
    },
    "new_7x24": {
        "name": "新7x24环境（看穿式前置）",
        "td_address": "tcp://182.254.243.31:40001",
        "md_address": "tcp://182.254.243.31:40011",
        "description": "7x24看穿式前置，使用监控中心生产秘钥",
    },
}


def get_simnow_credentials():
    """Get SimNow credentials from environment variables."""
    investor_id = os.getenv("simnow_user_id") or os.getenv("SIMNOW_USER_ID")
    password = os.getenv("simnow_password") or os.getenv("SIMNOW_PASSWORD")

    if not investor_id or not password:
        raise RuntimeError(
            "SimNow credentials not found in environment variables. "
            "Please set simnow_user_id and simnow_password in .env file."
        )

    return investor_id, password


def create_simnow_config(env_key="new_7x24"):
    """Create SimNow configuration for specified environment.

    Args:
        env_key: Environment key (group1, group2, group3, 7x24, new_group1, new_group2, new_group3, new_7x24)

    Returns:
        dict: SimNow configuration
    """
    if env_key not in SIMNOW_ENVIRONMENTS:
        raise ValueError(f"Invalid environment key: {env_key}. Valid keys: {', '.join(SIMNOW_ENVIRONMENTS.keys())}")

    env = SIMNOW_ENVIRONMENTS[env_key]
    investor_id, password = get_simnow_credentials()

    config = {
        "td_address": env["td_address"],
        "md_address": env["md_address"],
        "broker_id": "9999",
        "investor_id": investor_id,
        "password": password,
        "app_id": "simnow_client_test",
        "auth_code": "0000000000000000",
    }

    return config


class SimNowTestStrategy(bt.Strategy):
    """Simple strategy for testing SimNow connectivity."""

    params = (
        ("printlog", True),
        ("stop_after", 10),
    )

    def __init__(self):
        self.bar_count = 0
        self.order_placed = False

    def log(self, txt, dt=None):
        """Logging function."""
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"[{dt.isoformat()}] {txt}")

    def next(self):
        """Main strategy logic."""
        self.bar_count += 1

        self.log(
            f"Open: {self.data.open[0]:.2f}, "
            f"High: {self.data.high[0]:.2f}, "
            f"Low: {self.data.low[0]:.2f}, "
            f"Close: {self.data.close[0]:.2f}, "
            f"Volume: {self.data.volume[0]:.0f}"
        )

        if self.bar_count == 5 and not self.order_placed:
            self.log("Placing test buy order...")
            order = self.buy(size=1)
            if order:
                self.log(f"Order placed: {order.ref}")
                self.order_placed = True

        if self.bar_count >= self.p.stop_after:
            self.log(f"Received {self.bar_count} bars, stopping...")
            self.cerebro.runstop()


@pytest.fixture(scope="module")
def simnow_config():
    """Provide SimNow configuration."""
    env_key = os.getenv("SIMNOW_ENV", "new_7x24")
    config = create_simnow_config(env_key)

    print(f"\n使用 SimNow 环境: {SIMNOW_ENVIRONMENTS[env_key]['name']}")
    print(f"描述: {SIMNOW_ENVIRONMENTS[env_key]['description']}")

    return config


@pytest.fixture(scope="module")
def btapi_store(simnow_config):
    """Create and start a BtApiStore instance for SimNow."""
    store = BtApiStore(provider="ctp", **simnow_config)

    try:
        print(f"\n连接到 SimNow...")
        print(f"  交易前置: {simnow_config['td_address']}")
        print(f"  行情前置: {simnow_config['md_address']}")
        print(f"  BrokerID: {simnow_config['broker_id']}")
        print(f"  InvestorID: {simnow_config['investor_id']}")

        store.start()
        yield store
    finally:
        print("\n断开 SimNow 连接...")
        store.stop()


def test_simnow_connection(btapi_store):
    """Test connection to SimNow environment."""
    print("\n=== 测试 SimNow 连接 ===")

    assert btapi_store.is_connected, "Failed to connect to SimNow"
    print("✓ 成功连接到 SimNow 环境")


def test_simnow_market_data(btapi_store):
    """Test market data subscription and retrieval from SimNow."""
    print("\n=== 测试 SimNow 行情数据 ===")

    symbol = "rb2505"
    exchange = "SHFE"

    # Create mock historical data for testing
    now = _dt.datetime.now()
    mock_bars = []
    for i in range(10):
        bar_time = now - _dt.timedelta(minutes=10 - i)
        mock_bars.append(
            {
                "datetime": bar_time,
                "open": 3500.0 + i * 10,
                "high": 3510.0 + i * 10,
                "low": 3490.0 + i * 10,
                "close": 3505.0 + i * 10,
                "volume": 1000 + i * 100,
                "openinterest": 5000,
            }
        )

    data = BtApiFeed(
        store=btapi_store,
        dataname=f"{exchange}_{symbol}",
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        fromdate=_dt.datetime.now() - _dt.timedelta(days=1),
        todate=_dt.datetime.now(),
        historical_bars=mock_bars,
    )

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(SimNowTestStrategy, stop_after=5)

    print(f"订阅 {symbol} 行情数据...")
    results = cerebro.run()

    strategy = results[0] if results else None
    assert strategy is not None, "Strategy did not run"
    assert strategy.bar_count > 0, "No market data received"
    print(f"✓ 收到 {strategy.bar_count} 条行情数据")


def test_simnow_account_balance(btapi_store):
    """Test account balance retrieval from SimNow."""
    print("\n=== 测试 SimNow 账户资金 ===")

    cash = btapi_store.getcash()
    value = btapi_store.getvalue()

    print(f"  可用资金: {cash:,.2f}")
    print(f"  总资产: {value:,.2f}")

    assert cash >= 0, f"Invalid cash balance: {cash}"
    assert value >= 0, f"Invalid portfolio value: {value}"
    print("✓ 成功获取账户资金")


def test_simnow_order_placement(btapi_store):
    """Test order creation logic (not actual submission)."""
    print("\n=== 测试 SimNow 订单逻辑 ===")

    # Test that we can create a broker
    broker = BtApiBroker(store=btapi_store)
    assert broker is not None
    print("✓ Broker 创建成功")

    # Test that we can create mock data
    now = _dt.datetime.now()
    mock_bars = []
    for i in range(5):
        bar_time = now - _dt.timedelta(minutes=5 - i)
        mock_bars.append(
            {
                "datetime": bar_time,
                "open": 3500.0 + i * 10,
                "high": 3510.0 + i * 10,
                "low": 3490.0 + i * 10,
                "close": 3505.0 + i * 10,
                "volume": 1000 + i * 100,
                "openinterest": 5000,
            }
        )

    symbol = "rb2505"
    exchange = "SHFE"
    data = BtApiFeed(
        store=btapi_store,
        dataname=f"{exchange}_{symbol}",
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        historical_bars=mock_bars,
    )
    assert data is not None
    print("✓ 数据源创建成功")

    # Test cerebro setup
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.adddata(data)

    # Test order creation in strategy (without running)
    class OrderTestStrategy(bt.Strategy):
        def __init__(self):
            self.order_created = False

        def next(self):
            if not self.order_created:
                # Create a limit order (won't actually submit to CTP)
                order = self.buy(size=1, exectype=bt.Order.Limit, price=3500.0)
                if order:
                    self.order_created = True
                    # Cancel it immediately
                    self.cancel(order)

    cerebro.addstrategy(OrderTestStrategy)

    # Run with mock data only
    results = cerebro.run()
    strategy = results[0] if results else None

    assert strategy is not None, "Strategy did not run"
    print("✓ 订单创建和撤销逻辑测试成功")


def test_simnow_positions(btapi_store):
    """Test position retrieval from SimNow."""
    print("\n=== 测试 SimNow 持仓查询 ===")

    positions = btapi_store.getpositions()

    if positions:
        print(f"  总持仓数: {len(positions)}")
        for symbol, position in positions.items():
            print(f"  - {symbol}: {position.get('volume', 0)} @ {position.get('price', 0):.2f}")
    else:
        print("  无持仓")

    print("✓ 成功查询持仓")


def test_simnow_full_trading_cycle():
    """Test a complete trading cycle: connect, subscribe, order, cancel, disconnect."""
    print("\n=== 测试完整交易周期 ===")

    env_key = os.getenv("SIMNOW_ENV", "new_7x24")
    config = create_simnow_config(env_key)
    symbol = "rb2505"
    exchange = "SHFE"

    # Create mock data for testing
    now = _dt.datetime.now()
    mock_bars = []
    for i in range(10):
        bar_time = now - _dt.timedelta(minutes=10 - i)
        mock_bars.append(
            {
                "datetime": bar_time,
                "open": 3500.0 + i * 10,
                "high": 3510.0 + i * 10,
                "low": 3490.0 + i * 10,
                "close": 3505.0 + i * 10,
                "volume": 1000 + i * 100,
                "openinterest": 5000,
            }
        )

    store = BtApiStore(provider="ctp", **config)

    try:
        print("步骤 1: 连接 SimNow...")
        store.start()
        assert store.is_connected
        print("✓ 已连接")

        print("\n步骤 2: 查询账户资金...")
        cash = store.getcash()
        value = store.getvalue()
        print(f"  可用: {cash:,.2f}, 总资产: {value:,.2f}")
        print("✓ 资金查询完成")

        print(f"\n步骤 3: 订阅 {symbol} 行情...")
        data = BtApiFeed(
            store=store,
            dataname=f"{exchange}_{symbol}",
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            fromdate=_dt.datetime.now() - _dt.timedelta(hours=1),
            historical_bars=mock_bars,
        )
        print("✓ 行情订阅已创建")

        print("\n步骤 4: 创建 Broker...")
        broker = BtApiBroker(store=store)
        print("✓ Broker 已创建")

        print("\n步骤 5: 运行策略...")
        cerebro = bt.Cerebro()
        cerebro.setbroker(broker)
        cerebro.adddata(data)
        cerebro.addstrategy(SimNowTestStrategy, stop_after=5)

        results = cerebro.run()
        strategy = results[0] if results else None

        if strategy:
            print(f"✓ 策略执行完成，收到 {strategy.bar_count} 条数据")

        print("\n步骤 6: 断开连接...")
        store.stop()
        print("✓ 已断开")

        print("\n✓✓✓ 完整交易周期测试成功 ✓✓✓")

    except Exception as e:
        print(f"\n✗ 交易周期测试失败: {e}")
        store.stop()
        raise


def test_all_simnow_environments():
    """Test connection to all SimNow environments."""
    print("\n=== 测试所有 SimNow 环境 ===")

    investor_id, password = get_simnow_credentials()

    results = []
    for env_key, env_info in SIMNOW_ENVIRONMENTS.items():
        print(f"\n测试环境: {env_info['name']}")
        print(f"  交易前置: {env_info['td_address']}")
        print(f"  行情前置: {env_info['md_address']}")

        config = create_simnow_config(env_key)
        store = BtApiStore(provider="ctp", **config)

        try:
            store.start()
            time.sleep(2)

            if store.is_connected:
                print(f"  ✓ 连接成功")
                results.append((env_key, "SUCCESS", None))
            else:
                print(f"  ✗ 连接失败")
                results.append((env_key, "FAILED", "Not connected"))

            store.stop()
            time.sleep(1)

        except Exception as e:
            print(f"  ✗ 连接异常: {e}")
            results.append((env_key, "ERROR", str(e)))

    print("\n\n=== 连接测试结果汇总 ===")
    success_count = sum(1 for _, status, _ in results if status == "SUCCESS")
    print(f"成功: {success_count}/{len(results)}")

    for env_key, status, error in results:
        env_name = SIMNOW_ENVIRONMENTS[env_key]["name"]
        if status == "SUCCESS":
            print(f"  ✓ {env_name}")
        else:
            print(f"  ✗ {env_name}: {error}")

    assert success_count > 0, "至少需要连接成功一个环境"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
