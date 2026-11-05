"""Iteration 62 (62.08): Gateway MarketHub ticks feed a BtApiFeed in Cerebro.

A Gateway CTP MarketHub (SDK ``ctp_gateway_composition``, SimNow profile
``set1_group1_vpn``) serves on loopback CURVE ZMQ; its native MD client is a
synthetic stand-in that emits SimNow-shaped rows (empty ``ExchangeID``). The
strategy process builds ``BtApiStore(..., market_runtime_factory=...)``: the
SDK facade then serves its tick subscriptions from the Gateway instead of an
in-process CTP market session, and ``store.getdata`` produces 1-second bars.
The ticks keep their clock facts: without SDK clock verification they stay
unqualified (the Feed records why) and are still usable for bars/indicators.

INTEGRATION_SIM: one local process (Gateway host on a daemon thread), temp
SQLite, CURVE on 127.0.0.1; no real CTP front, credentials or network.
"""

from __future__ import annotations

import queue
import threading
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("zmq")
pytest.importorskip("bt_api_py.ctp_gateway_composition")

import backtrader as bt  # noqa: E402
from bt_api_ctp.ctp.client import CtpNativeStopReceipt  # noqa: E402
from bt_api_ctp.feeds import live_ctp_feed  # noqa: E402
from bt_api_py.ctp_gateway_composition import (  # noqa: E402
    build_ctp_gateway_market_host,
    create_gateway_market_runtime,
    ctp_gateway_instrument_key,
)

from backtrader.stores.btapistore import BtApiStore  # noqa: E402

_ROUTE = "CTP___FUTURE"
_SYMBOL = "rb2701"
_CN = timezone(timedelta(hours=8))


class _SyntheticMdClient:
    """Native MD stand-in: login, subscription acks and a tick every 100 ms."""

    instances: list = []

    def __init__(self, md_front, *_args, **_kwargs):
        self.md_front = md_front
        self.connection_generation = 1
        self.subscribed: list[str] = []
        self.on_login = self.on_subscribe_response = self.on_disconnect = self.on_tick = None
        self._stop = threading.Event()
        self.volume = 1_000
        self.__class__.instances.append(self)

    def subscribe(self, instruments):
        self.subscribed.extend(instruments)

    def subscribe_additional(self, instruments):
        added = tuple(item for item in instruments if item not in self.subscribed)
        self.subscribed.extend(added)
        for item in added:
            self.on_subscribe_response(
                SimpleNamespace(InstrumentID=item), SimpleNamespace(ErrorID=0), 1, True, 1
            )
        return added

    def unsubscribe(self, instruments):
        self.subscribed = [item for item in self.subscribed if item not in instruments]
        return True

    def start(self, *, block=False):
        assert block is False
        self.on_login(SimpleNamespace())
        for index, item in enumerate(self.subscribed):
            self.on_subscribe_response(
                SimpleNamespace(InstrumentID=item),
                SimpleNamespace(ErrorID=0),
                1,
                index == len(self.subscribed) - 1,
                1,
            )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        price = 3_050.0
        while not self._stop.wait(0.1):
            now = datetime.now(_CN)
            self.volume += 1
            price += 1.0
            for item in list(self.subscribed):
                self.on_tick(
                    SimpleNamespace(
                        InstrumentID=item,
                        ExchangeID="",  # SimNow MD rows leave it empty
                        LastPrice=price,
                        PreSettlementPrice=3_000.0,
                        OpenPrice=3_040.0,
                        HighestPrice=price,
                        LowestPrice=3_030.0,
                        BidPrice1=price - 1.0,
                        BidVolume1=3,
                        AskPrice1=price,
                        AskVolume1=4,
                        OpenInterest=10_000.0,
                        Volume=self.volume,
                        Turnover=1.0e7,
                        UpperLimitPrice=3_300.0,
                        LowerLimitPrice=2_800.0,
                        TradingDay=now.strftime("%Y%m%d"),
                        ActionDay=now.strftime("%Y%m%d"),
                        UpdateTime=now.strftime("%H:%M:%S"),
                        UpdateMillisec=now.microsecond // 1000,
                    )
                )

    def stop(self):
        self._stop.set()

    def stop_and_wait(self, *, timeout):
        self._stop.set()
        return CtpNativeStopReceipt(
            connection_generation=1,
            join_required=False,
            join_completed=True,
            native_released=True,
            thread_alive=False,
            timed_out=False,
        )


class _CollectBars(bt.Strategy):
    params = (("stop_after", 3),)

    def __init__(self):
        self.closes = []
        self.qualifications = []

    def next(self):
        self.closes.append(float(self.data.close[0]))
        qualify = getattr(self.data, "trade_qualification", None)
        if callable(qualify):
            self.qualifications.append(qualify())
        if len(self.closes) >= self.p.stop_after:
            self.env.runstop()


@pytest.mark.integration
def test_gateway_ticks_build_bars_in_a_btapifeed(monkeypatch, tmp_path):
    _SyntheticMdClient.instances.clear()
    monkeypatch.setattr(live_ctp_feed.ctp_client, "MdClient", _SyntheticMdClient)
    # The hub process holds the market credentials (synthetic here).
    monkeypatch.setenv("CTP_USER_ID", "synthetic-user")
    monkeypatch.setenv("CTP_BROKER_ID", "9999")
    monkeypatch.setenv("CTP_PASSWORD", "synthetic-password")

    profile, connection = build_ctp_gateway_market_host(
        ctp_profile="set1_group1_vpn",
        instruments=[(_SYMBOL, "SHFE")],
        registry_path=tmp_path / "gateway-market-registry.sqlite3",
    )
    deployment = profile.deployment_factory()
    started: queue.Queue = queue.Queue()
    stop = threading.Event()

    def serve() -> None:
        try:
            deployment.start()
            started.put("started")
            while not stop.is_set():
                deployment.serve_once(10)
        except BaseException as exc:  # reported to the test thread
            started.put(getattr(exc, "code", type(exc).__name__))
        finally:
            if deployment.state not in {"closed", "failed"}:
                with suppress(BaseException):
                    deployment.close()

    owner = threading.Thread(target=serve, name="iter62-gateway-market", daemon=True)
    owner.start()
    runtime = None
    store = None
    try:
        assert started.get(timeout=15) == "started"
        runtime, factory = create_gateway_market_runtime(connection)
        store = BtApiStore(
            provider="ctp",
            contract_metadata={
                _SYMBOL: {
                    "instrument_key": ctp_gateway_instrument_key(_SYMBOL, "SHFE"),
                    "price_tick": 1.0,
                    "multiplier": 10.0,
                }
            },
            # The strategy process's own CTP route (direct orders/account in
            # the examples) is never connected here: loopback closed port.
            exchange_kwargs={
                _ROUTE: {
                    "broker_id": "9999",
                    "user_id": "synthetic-user",
                    "password": "synthetic-password",
                    "td_front": "tcp://127.0.0.1:1",
                    "md_front": "tcp://127.0.0.1:1",
                    "ctp_env_profile": "config_front_pair",
                }
            },
            write_admission={_ROUTE: True},
            market_clock_verification=False,
            symbol_routes={_SYMBOL: _ROUTE},
            market_runtime_factory=factory,
        )
        data = store.getdata(
            dataname=_SYMBOL,
            timeframe=bt.TimeFrame.Seconds,
            compression=1,
            backfill_start=False,
        )
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(data, name=_SYMBOL)
        cerebro.addstrategy(_CollectBars)
        timer = threading.Timer(20.0, cerebro.runstop)
        timer.daemon = True
        timer.start()
        try:
            (strategy,) = cerebro.run(runonce=False, preload=False)
        finally:
            timer.cancel()

        assert len(strategy.closes) >= 3, strategy.closes
        assert all(3_050.0 < close < 3_400.0 for close in strategy.closes)
        assert strategy.closes == sorted(strategy.closes)  # synthetic prices rise
        # One native MD session, opened by the Gateway host (the strategy
        # process opened none) on the selected SimNow profile's MD front.
        (client,) = _SyntheticMdClient.instances
        assert client.md_front == "tcp://182.254.243.31:30011"
        assert client.subscribed == [_SYMBOL]
        # The ticks kept their (unverified) clock facts: usable for bars and
        # indicators, never reported as trade-qualified.
        assert strategy.qualifications
        assert all(not getattr(q, "ok", True) for q in strategy.qualifications)
    finally:
        if store is not None:
            with suppress(Exception):
                store.stop()
        if runtime is not None:
            with suppress(Exception):
                runtime.close()
        stop.set()
        owner.join(10)
    assert not owner.is_alive()
    assert deployment.state == "closed"
