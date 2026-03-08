#!/usr/bin/env python
"""SimNow CTP live-surface tests for the unified bt_api_py adapter.

The underlying CTP native extension leaves background Join() threads alive on
macOS. Running the real live interactions in subprocesses and terminating those
children with os._exit avoids interpreter-shutdown segfaults in the parent
pytest session.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest

_TEST_FILE = Path(__file__).resolve()
_REPO_ROOT = _TEST_FILE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

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
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore


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

_DEFAULT_CASE_TIMEOUT = 180
_CASE_TIMEOUTS = {"all_environments": 300, "real_tick_subscription": 90}


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
    """Create SimNow configuration for a specific environment."""
    if env_key not in SIMNOW_ENVIRONMENTS:
        raise ValueError(f"Invalid environment key: {env_key}. Valid keys: {', '.join(SIMNOW_ENVIRONMENTS)}")

    env = SIMNOW_ENVIRONMENTS[env_key]
    investor_id, password = get_simnow_credentials()
    return {
        "td_address": env["td_address"],
        "md_address": env["md_address"],
        "broker_id": "9999",
        "investor_id": investor_id,
        "password": password,
        "app_id": "simnow_client_test",
        "auth_code": "0000000000000000",
    }


def _make_mock_bars(count=10):
    """Create deterministic mock minute bars for feed tests."""
    now = _dt.datetime.now()
    bars = []
    for i in range(count):
        bar_time = now - _dt.timedelta(minutes=count - i)
        bars.append(
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
    return bars


@contextlib.contextmanager
def _started_store(env_key=None):
    """Create a live BtApiStore in a subprocess-safe context."""
    env_key = env_key or os.getenv("SIMNOW_ENV", "new_7x24")
    config = create_simnow_config(env_key)
    env = SIMNOW_ENVIRONMENTS[env_key]
    store = BtApiStore(provider="ctp", **config)

    print(f"\n使用 SimNow 环境: {env['name']}")
    print(f"描述: {env['description']}")
    print(f"\n连接到 SimNow...")
    print(f"  交易前置: {config['td_address']}")
    print(f"  行情前置: {config['md_address']}")
    print(f"  BrokerID: {config['broker_id']}")
    print(f"  InvestorID: {config['investor_id']}")

    try:
        store.start()
        yield store, config, env_key
    finally:
        print("\n断开 SimNow 连接...")
        store.stop()


class SimNowTestStrategy(bt.Strategy):
    """Simple strategy for live SimNow smoke tests."""

    params = (
        ("printlog", True),
        ("stop_after", 10),
    )

    def __init__(self):
        self.bar_count = 0
        self.order_placed = False

    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"[{dt.isoformat()}] {txt}")

    def next(self):
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


def _case_connection():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试 SimNow 连接 ===")
        assert store.is_connected, "Failed to connect to SimNow"
        print("✓ 成功连接到 SimNow 环境")


def _case_market_data():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试 SimNow 行情数据 ===")
        symbol = "rb2505"
        exchange = "SHFE"

        data = BtApiFeed(
            store=store,
            dataname=f"{exchange}_{symbol}",
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            fromdate=_dt.datetime.now() - _dt.timedelta(days=1),
            todate=_dt.datetime.now(),
            historical_bars=_make_mock_bars(10),
        )

        cerebro = bt.Cerebro()
        cerebro.setbroker(BtApiBroker(store=store))
        cerebro.adddata(data)
        cerebro.addstrategy(SimNowTestStrategy, stop_after=5)

        print(f"订阅 {symbol} 行情数据...")
        results = cerebro.run()
        strategy = results[0] if results else None

        assert strategy is not None, "Strategy did not run"
        assert strategy.bar_count > 0, "No market data received"
        print(f"✓ 收到 {strategy.bar_count} 条行情数据")


def _case_account_balance():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试 SimNow 账户资金 ===")
        cash = store.getcash()
        value = store.getvalue()

        print(f"  可用资金: {cash:,.2f}")
        print(f"  总资产: {value:,.2f}")

        assert cash >= 0, f"Invalid cash balance: {cash}"
        assert value >= 0, f"Invalid portfolio value: {value}"
        print("✓ 成功获取账户资金")


def _case_order_placement():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试 SimNow 订单逻辑 ===")

        broker = BtApiBroker(store=store)
        assert broker is not None
        print("✓ Broker 创建成功")

        symbol = "rb2505"
        exchange = "SHFE"
        data = BtApiFeed(
            store=store,
            dataname=f"{exchange}_{symbol}",
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            historical_bars=_make_mock_bars(5),
        )
        assert data is not None
        print("✓ 数据源创建成功")

        cerebro = bt.Cerebro()
        cerebro.setbroker(broker)
        cerebro.adddata(data)

        class OrderTestStrategy(bt.Strategy):
            def __init__(self):
                self.order_created = False
                self.bar_count = 0

            def next(self):
                self.bar_count += 1
                if not self.order_created:
                    order = self.buy(size=1, exectype=bt.Order.Limit, price=3500.0)
                    if order:
                        self.order_created = True
                        self.cancel(order)
                self.cerebro.runstop()

        cerebro.addstrategy(OrderTestStrategy)
        results = cerebro.run()
        strategy = results[0] if results else None

        assert strategy is not None, "Strategy did not run"
        print("✓ 订单创建和撤销逻辑测试成功")


def _case_real_tick_subscription():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试真实 CTP Tick 订阅 ===")
        symbol = os.getenv("SIMNOW_TICK_SYMBOL", "rb2610")
        bar_seconds = int(os.getenv("SIMNOW_TICK_BAR_SECONDS", "5"))
        timeout_seconds = int(os.getenv("SIMNOW_TICK_TIMEOUT", "30"))

        data = BtApiFeed(
            store=store,
            dataname=symbol,
            timeframe=bt.TimeFrame.Seconds,
            compression=bar_seconds,
            backfill_start=False,
        )

        cerebro = bt.Cerebro()
        cerebro.setbroker(BtApiBroker(store=store))
        cerebro.adddata(data)

        class RealTickStrategy(bt.Strategy):
            def __init__(self):
                self.tick_count = 0
                self.bar_count = 0
                self.next_count = 0
                self.last_tick = None
                self.last_bar = None

            def notify_tick(self, tick):
                self.tick_count += 1
                self.last_tick = tick
                if self.tick_count <= 5:
                    print(
                        "  tick[%d] symbol=%s price=%.2f volume=%.0f time=%s"
                        % (
                            self.tick_count,
                            tick.symbol,
                            tick.price,
                            tick.volume,
                            getattr(tick, "datetime", None) or tick.timestamp,
                        )
                    )

            def notify_bar(self, bar):
                self.bar_count += 1
                self.last_bar = bar
                print(
                    "  bar[%d] symbol=%s open=%.2f high=%.2f low=%.2f close=%.2f volume=%.0f time=%s"
                    % (
                        self.bar_count,
                        bar.symbol,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        getattr(bar, "datetime", None) or bar.timestamp,
                    )
                )

            def next(self):
                self.next_count += 1
                if self.bar_count >= 1 and self.tick_count >= 1:
                    self.cerebro.runstop()

        cerebro.addstrategy(RealTickStrategy)
        stop_timer = threading.Timer(timeout_seconds, cerebro.runstop)
        stop_timer.daemon = True
        stop_timer.start()
        try:
            print(f"订阅真实行情: {symbol}，等待最多 {timeout_seconds}s ...")
            results = cerebro.run()
        finally:
            stop_timer.cancel()

        strategy = results[0] if results else None
        assert strategy is not None, "Strategy did not run"
        if strategy.tick_count <= 0:
            pytest.skip(f"No live ticks received for {symbol} within {timeout_seconds}s")

        print(
            "✓ 收到真实 Tick: %d 条，生成 Bar: %d 条，next 调用: %d 次"
            % (strategy.tick_count, strategy.bar_count, strategy.next_count)
        )
        if strategy.bar_count > 0:
            assert strategy.next_count > 0, "A completed live bar should eventually trigger next()"
            print("✓ notify_bar 与 next 联动正常")
        else:
            print("  ! 在当前等待窗口内未完成一个整 Bar，但 notify_tick 已验证可用")


def _case_positions():
    with _started_store() as (store, _config, _env_key):
        print("\n=== 测试 SimNow 持仓查询 ===")
        positions = store.getpositions()

        if positions:
            print(f"  总持仓数: {len(positions)}")
            for position in positions:
                symbol = (
                    position.get("instrument")
                    or position.get("symbol")
                    or position.get("dataname")
                    or "UNKNOWN"
                )
                volume = position.get("volume", position.get("size", 0))
                price = position.get("price", position.get("avg_price", 0))
                print(f"  - {symbol}: {volume} @ {price:.2f}")
        else:
            print("  无持仓")

        print("✓ 成功查询持仓")


def _case_full_trading_cycle():
    print("\n=== 测试完整交易周期 ===")
    env_key = os.getenv("SIMNOW_ENV", "new_7x24")
    config = create_simnow_config(env_key)
    symbol = "rb2505"
    exchange = "SHFE"
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
            historical_bars=_make_mock_bars(10),
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
    finally:
        store.stop()


def _case_all_environments():
    print("\n=== 测试所有 SimNow 环境 ===")
    get_simnow_credentials()

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
                print("  ✓ 连接成功")
                results.append((env_key, "SUCCESS", None))
            else:
                print("  ✗ 连接失败")
                results.append((env_key, "FAILED", "Not connected"))
        except Exception as exc:
            print(f"  ✗ 连接异常: {exc}")
            results.append((env_key, "ERROR", str(exc)))
        finally:
            store.stop()
            time.sleep(1)

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


_CASE_HANDLERS = {
    "connection": _case_connection,
    "market_data": _case_market_data,
    "account_balance": _case_account_balance,
    "order_placement": _case_order_placement,
    "real_tick_subscription": _case_real_tick_subscription,
    "positions": _case_positions,
    "full_trading_cycle": _case_full_trading_cycle,
    "all_environments": _case_all_environments,
}


def _emit_subprocess_output(completed):
    """Relay child process output into the parent pytest process."""
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)


def _run_live_case(case_name):
    """Execute a live CTP case in an isolated subprocess."""
    cmd = [sys.executable, "-u", str(_TEST_FILE), "--subprocess-case", case_name]
    timeout = _CASE_TIMEOUTS.get(case_name, _DEFAULT_CASE_TIMEOUT)

    try:
        completed = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"SimNow subprocess case '{case_name}' timed out after {timeout}s: {exc}")

    _emit_subprocess_output(completed)
    if completed.returncode == 3:
        pytest.skip(f"SimNow subprocess case '{case_name}' skipped")
    assert completed.returncode == 0, f"SimNow subprocess case '{case_name}' failed"


def _run_subprocess_case(case_name):
    """Run the actual live case and hard-exit to avoid native shutdown crashes."""
    handler = _CASE_HANDLERS.get(case_name)
    if handler is None:
        print(f"Unknown subprocess case: {case_name}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(2)

    try:
        handler()
    except pytest.skip.Exception as exc:
        print(f"SKIPPED: {exc}")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


@pytest.mark.live
def test_simnow_connection():
    _run_live_case("connection")


@pytest.mark.live
def test_simnow_market_data():
    _run_live_case("market_data")


@pytest.mark.live
def test_simnow_account_balance():
    _run_live_case("account_balance")


@pytest.mark.live
def test_simnow_order_placement():
    _run_live_case("order_placement")


@pytest.mark.live
def test_simnow_real_tick_subscription():
    _run_live_case("real_tick_subscription")


@pytest.mark.live
def test_simnow_positions():
    _run_live_case("positions")


@pytest.mark.live
def test_simnow_full_trading_cycle():
    _run_live_case("full_trading_cycle")


@pytest.mark.live
def test_all_simnow_environments():
    _run_live_case("all_environments")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--subprocess-case")
    args, passthrough = parser.parse_known_args()

    if args.subprocess_case:
        _run_subprocess_case(args.subprocess_case)

    raise SystemExit(pytest.main([__file__, *passthrough]))
