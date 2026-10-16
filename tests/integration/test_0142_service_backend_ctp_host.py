"""014_2 normal service backend through local Gateway Hosts and Cerebro.

The Gateway workers, SDK clients, CURVE transports, BtApiStore/Feed, and
production strategy are real. Account facts and native CTP Trader/MD terminal
callbacks are synthetic local leaves; no exchange or account is contacted.
"""

from __future__ import annotations

import importlib
import json
import queue
import socket
import threading
import time
import traceback
from contextlib import suppress
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import zmq
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_ctp.ctp.client import CtpNativeStopReceipt, MdClient, TraderClient, _TraderSpi
from bt_api_ctp.feeds import live_ctp_feed
from bt_api_ctp.feeds.live_ctp_feed import CtpMarketStream, CtpRequestDataFuture
from bt_api_ctp.market_provider import BoundedCtpQuoteV2Queue, CtpQuoteV2MarketProvider
from bt_api_gateway.ctp_instrument_metadata import bind_ctp_instrument_metadata_provider
from bt_api_gateway.event_journal import GatewayEventJournal
from bt_api_gateway.quota_admission import GatewayQuotaAdmission
from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
from bt_api_gateway.service_component import GatewayServiceAccountScope
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_operator import (
    GatewayAccountSessionBinding,
    GatewayMarketBinding,
    GatewayOperatorDeployment,
)
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_gateway.session_owner import GatewaySessionOwner


_DOMAIN = "paper:scn02-0142-service-host"
_TRADING_DAY = datetime.now(UTC).astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d")
_STRATEGY = "ctp_options_midfreq"
_ACCOUNT_REF = "account:scn02-0142"
_CLIENT_PRINCIPAL = "principal:scn02-0142-client"
_ACCOUNT_SERVICE_PRINCIPAL = "principal:scn02-0142-account"
_MARKET_SERVICE_PRINCIPAL = "principal:scn02-0142-market"
_SOURCE_REF = "ctp-native-market-r1"
_ENTITLEMENT_REF = "ctp-quote-v2-entitlement-r1"
_ACCOUNT_OPERATIONS = frozenset(
    {
        "account.ack",
        "account.configuration",
        "account.head",
        "account.instrument_metadata",
        "account.progress",
        "account.read_after",
        "account.server_time_probe",
        "account.snapshot",
    }
)
_MARKET_OPERATIONS = frozenset(
    {"market.subscribe", "market.unsubscribe", "market.snapshot", "market.head", "market.read_after"}
)
_COVERAGE = (
    AccountResourceKey("future", "futures"),
    AccountResourceKey("option", "options"),
)
_ACCOUNT_KEY = AccountKey("ctp", "CFFEX", "simnow", "synthetic-0142-account")
_CONTRACTS = {
    "future": "CFFEX.IF2612",
    "call": "CFFEX.IO2612-C-4000",
    "put": "CFFEX.IO2612-P-4000",
}
_INSTRUMENTS = {
    "IF2612": "future",
    "IO2612-C-4000": "option",
    "IO2612-P-4000": "option",
}


class _SyntheticLoginField:
    BrokerID = ""
    UserID = ""
    Password = ""


class _SyntheticMdApi:
    def __init__(self) -> None:
        self.login_calls: list[tuple[object, int]] = []
        self.release_calls = 0
        self.detach_calls = 0

    def ReqUserLogin(self, field: object, request_id: int) -> int:
        self.login_calls.append((field, request_id))
        return 0

    def RegisterSpi(self, spi: object) -> None:
        if spi is None:
            self.detach_calls += 1

    def Release(self) -> None:
        self.release_calls += 1


class _SyntheticMdClient(MdClient):
    instances: list[_SyntheticMdClient] = []

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self._connection_generation = 1
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.stop_calls = 0
        self.stop_wait_calls = 0
        self._active = threading.Event()
        self._ticker_thread: threading.Thread | None = None
        self._cumulative: dict[str, int] = {}
        self.__class__.instances.append(self)

    def subscribe(self, instruments: list[str]) -> None:
        self.subscribed.extend(item for item in instruments if item not in self.subscribed)

    def subscribe_additional(self, instruments: list[str]) -> tuple[str, ...]:
        additions = tuple(item for item in instruments if item not in self.subscribed)
        self.subscribed.extend(additions)
        return additions

    def unsubscribe(self, instruments: list[str]) -> bool:
        self.unsubscribed.extend(instruments)
        self.subscribed = [item for item in self.subscribed if item not in instruments]
        return True

    def start(self, *, block: bool = False) -> None:
        assert block is False
        api = _SyntheticMdApi()
        self._api = api
        spi = self._create_md_spi(api)
        self._spi = spi
        spi.OnFrontConnected()
        request_id = api.login_calls[-1][1]
        spi.OnRspUserLogin(
            SimpleNamespace(
                BrokerID=self._bound_broker_id,
                UserID=self._bound_user_id,
                TradingDay=_TRADING_DAY,
            ),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id,
            True,
        )
        self._active.set()
        if self.subscribed:
            self._ticker_thread = threading.Thread(
                target=self._emit_ticks,
                name="0142-synthetic-ctp-md-leaf",
                daemon=True,
            )
            self._ticker_thread.start()

    def _emit_ticks(self) -> None:
        first_event_time = datetime.now(UTC).astimezone(
            timezone(timedelta(hours=8))
        ) - timedelta(minutes=5)
        for offset in range(3):
            if not self._active.is_set():
                return
            event_time = first_event_time + timedelta(minutes=offset)
            symbols = tuple(self.subscribed)
            update_time = event_time.strftime("%H:%M:%S")
            for symbol in symbols:
                self._cumulative[symbol] = self._cumulative.get(symbol, 0) + 1
                product_type = _INSTRUMENTS[symbol]
                last = 4_000.0 if product_type == "future" else 20.0 if "-C-" in symbol else 15.0
                tick = SimpleNamespace(
                    InstrumentID=symbol,
                    ExchangeID="CFFEX",
                    LastPrice=last,
                    PreSettlementPrice=last,
                    OpenPrice=last,
                    HighestPrice=last + 1,
                    LowestPrice=last - 1,
                    BidPrice1=last - 0.1,
                    BidVolume1=2,
                    AskPrice1=last + 0.1,
                    AskVolume1=3,
                    OpenInterest=1_000.0,
                    Volume=self._cumulative[symbol],
                    Turnover=last * self._cumulative[symbol],
                    UpperLimitPrice=last + 500,
                    LowerLimitPrice=max(0.1, last - 500),
                    TradingDay=event_time.strftime("%Y%m%d"),
                    ActionDay=event_time.strftime("%Y%m%d"),
                    UpdateTime=update_time,
                    UpdateMillisec=event_time.microsecond // 1_000,
                )
                if callable(self.on_tick):
                    self.on_tick(tick)
            time.sleep(0.025)
        self._active.wait()

    def stop(self) -> None:
        self.stop_calls += 1
        self._active.clear()
        super().stop()

    def stop_and_wait(self, *, timeout: float) -> CtpNativeStopReceipt:
        self.stop_wait_calls += 1
        if self._ticker_thread is not None:
            self._ticker_thread.join(timeout)
        alive = bool(self._ticker_thread and self._ticker_thread.is_alive())
        stopped_api = self._last_stopped_native_api
        return CtpNativeStopReceipt(
            connection_generation=self._connection_generation,
            join_required=self._ticker_thread is not None,
            join_completed=not alive,
            native_released=bool(stopped_api and stopped_api.release_calls == 1),
            thread_alive=alive,
            timed_out=alive,
        )


class _SyntheticTraderApi:
    def __init__(self, trader: TraderClient) -> None:
        self.trader = trader
        self.query_rows: list[tuple[str, str, str]] = []

    def ReqQryInstrument(self, field: object, request_id: int) -> int:
        instrument_id = str(getattr(field, "InstrumentID", ""))
        exchange_id = str(getattr(field, "ExchangeID", ""))
        self.query_rows.append((instrument_id, exchange_id, str(getattr(field, "ProductID", ""))))
        product_class = "1" if _INSTRUMENTS[instrument_id] == "future" else "2"
        self.trader._handle_query_callback(
            "instruments",
            SimpleNamespace(
                InstrumentID=instrument_id,
                ExchangeID=exchange_id,
                ProductClass=product_class,
                PriceTick=0.2,
                VolumeMultiple=100,
            ),
            None,
            request_id,
            True,
        )
        return 0


class _SyntheticAccountProvider:
    def __init__(self) -> None:
        self.trader = TraderClient(
            "tcp://offline.invalid:0",
            "synthetic-broker",
            "synthetic-investor",
            "",
            auto_settlement_confirm=False,
        )
        self.trader._connected = True
        self.trader._authentication_state = "authenticated"
        self.trader._login_state = "logging_in"
        self.trader._connection_generation = 7
        self.trader._req_id = 30
        self.trader._login_request_id = 30
        self.trader._login_connection_generation = 7
        self.trader._query_interval = 0.0
        _TraderSpi(self.trader).OnRspUserLogin(
            SimpleNamespace(
                BrokerID=self.trader._bound_broker_id,
                InvestorID=self.trader._bound_user_id,
                UserID=self.trader._bound_user_id,
                TradingDay=_TRADING_DAY,
                FrontID=0,
                SessionID=0,
                MaxOrderRef="",
            ),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            30,
            True,
        )
        self.trader_api = _SyntheticTraderApi(self.trader)
        self.trader._api = self.trader_api
        self.ctp_request_feed = CtpRequestDataFuture()
        self.ctp_request_feed._trader = self.trader
        self.ctp_market_stream = CtpMarketStream(
            md_front="tcp://127.0.0.1:1",
            broker_id="synthetic-broker",
            user_id="synthetic-investor",
            password="synthetic-password",
            topics=(),
        )
        self.ctp_trader_client = self.trader
        self.ctp_account_key: AccountKey | None = None
        self.read_count = 0
        self.close_count = 0

    def connect(self, *, account_key: AccountKey, generation: str, timeout: float) -> None:
        assert generation and timeout > 0
        self.ctp_account_key = account_key
        self.ctp_market_stream.connect()

    def read_account(self, *, generation: str, timeout: float) -> AccountObservation:
        assert generation and timeout > 0
        self.read_count += 1
        observed_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        balances = tuple(
            AccountBalance(
                resource=resource,
                currency="CNY",
                total="100000",
                available="90000",
                locked="10000",
                observed_at_utc=observed_at,
            )
            for resource in _COVERAGE
        )
        return AccountObservation(
            account_key=_ACCOUNT_KEY,
            observation_id=f"synthetic-0142-account-{self.read_count}",
            coverage=_COVERAGE,
            balances=balances,
            positions=(),
            valuation=AccountValuation(
                currency="CNY",
                available_cash="90000",
                equity="100000",
                observed_at_utc=observed_at,
            ),
            started_at_utc=observed_at,
            completed_at_utc=observed_at,
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
            open_orders=(),
            open_orders_complete=True,
        )

    def close(self) -> bool:
        self.close_count += 1
        self.ctp_market_stream.disconnect()
        return True


def _free_endpoint() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"
    finally:
        probe.close()


def _service_config(
    service_id: str,
    instance_id: str,
    scope_ref: str,
    transport_ref: str,
    security_ref: str,
    rpc_bind: str,
    *,
    market_bind: str | None = None,
    role: str,
) -> dict[str, Any]:
    if role == "account_session_worker":
        ports = ["service.account_read", "service.provider_session"]
        options = {"role": role, "account_session_ref": "session:scn02-0142"}
    else:
        ports = ["service.market_source"]
        options = {"role": "market_hub"}
    endpoints = {"rpc_bind": rpc_bind}
    if market_bind is not None:
        endpoints["market_bind"] = market_bind
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": service_id,
        "scope_ref": scope_ref,
        "transport_ref": transport_ref,
        "registration_policy_ref": f"{service_id}-policy-v1",
        "service_requirements_ref": f"{service_id}-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": instance_id,
                    "bind_ports": ports,
                    "options": options,
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                transport_ref: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": endpoints,
                    "security_profile_ref": security_ref,
                    "options": {"high_water_mark": 64, "max_message_bytes": 262_144},
                }
            },
        },
    }


def _authority(
    config: Any,
    *,
    server_keys: tuple[bytes, bytes],
    client_public: bytes,
    client_principal: str,
    strategy_ref: str,
    domain: str,
    account_ref: str | None,
    operations: frozenset[str],
) -> tuple[TrustedServiceAuthority, WireIdentity]:
    service_id = config.service_id
    service_principal = f"principal:{service_id}"
    service_identity = WireIdentity(WireRole.SERVICE, service_principal, service_id)
    strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, client_principal, strategy_ref)
    scope = WireScope(domain, account_ref=account_ref, strategy_ref=strategy_ref)
    grant = ResourceGrant(
        config.components["gateway"]["settings"]["instance_id"],
        "service.account_read" if account_ref is not None else "service.market_source",
        config.scope_ref,
        scope,
        operations,
    )
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=WireScope(domain),
        scope_ref=config.scope_ref,
        scope_version=f"{service_id}-scope-v1",
        security_ref=config.communication["profiles"][config.transport_ref]["security_profile_ref"],
        security_version=f"{service_id}-security-v1",
        curve_public_key=server_keys[0],
        curve_secret_key=server_keys[1],
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version=f"{service_id}-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version=f"{service_id}-requirements-v1",
        principals={client_public: client_principal},
        grants={client_principal: (PrincipalGrant(strategy_identity, (grant,)),)},
    )
    return authority, service_identity


def _market_key(instrument_id: str, product_type: str) -> MarketSubscriptionKey:
    return MarketSubscriptionKey(
        source_ref=_SOURCE_REF,
        entitlement_ref=_ENTITLEMENT_REF,
        instrument=MarketInstrumentKey(
            provider="ctp",
            venue="CFFEX",
            environment="simnow",
            product_type=product_type,
            instrument_id=instrument_id,
            native_symbol=instrument_id,
        ),
        channel="ctp.quote.v2",
    )


def _client_document(
    *,
    strategy_ref: str,
    account_endpoint: str,
    market_rpc_endpoint: str,
    market_data_endpoint: str,
    account_instance: str,
    account_scope: str,
    market_instance: str,
    market_scope: str,
    account_transport: str,
    market_transport: str,
    account_security: str,
    market_security: str,
) -> dict[str, Any]:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": strategy_ref},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "store.account",
                            "service_id": "scn02-0142-account",
                            "instance_id": account_instance,
                            "scope_ref": account_scope,
                            "account_ref": _ACCOUNT_REF,
                            "transport_ref": account_transport,
                        },
                        {
                            "mount": "store.market",
                            "service_id": "scn02-0142-market",
                            "instance_id": market_instance,
                            "scope_ref": market_scope,
                            "transport_ref": market_transport,
                        },
                    ],
                    "options": {"request_timeout_ms": 3_000, "heartbeat_interval_seconds": 5},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                account_transport: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": account_endpoint},
                    "security_profile_ref": account_security,
                    "options": {"request_timeout_ms": 3_000, "high_water_mark": 64, "max_message_bytes": 262_144},
                },
                market_transport: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {
                        "rpc_connect": market_rpc_endpoint,
                        "market_connect": market_data_endpoint,
                    },
                    "security_profile_ref": market_security,
                    "options": {"request_timeout_ms": 3_000, "high_water_mark": 64, "max_message_bytes": 262_144},
                },
            },
        },
    }


def _host_thread(deployment_factory, name: str):
    startup: queue.Queue[tuple[str, object, object]] = queue.Queue()
    stop = threading.Event()
    holder: dict[str, GatewayOperatorDeployment] = {}

    def serve() -> None:
        deployment = None
        try:
            deployment = deployment_factory()
            holder["deployment"] = deployment
            deployment.start()
            startup.put(("started", deployment.endpoint, deployment.market_endpoint))
            while not stop.is_set():
                deployment.serve_once(10)
        except BaseException as exc:
            startup.put(("error", getattr(exc, "code", type(exc).__name__), None))
        finally:
            if deployment is not None and deployment.state not in {"closed", "failed"}:
                with suppress(BaseException):
                    deployment.close()

    thread = threading.Thread(target=serve, name=name, daemon=True)
    thread.start()
    return startup, stop, thread, holder


@pytest.mark.integration
def test_0142_run_live_service_reaches_three_leg_cerebro_through_gateway_hosts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(live_ctp_feed.ctp_client, "MdClient", _SyntheticMdClient)
    monkeypatch.setattr(live_ctp_feed.ctp_client, "CThostFtdcReqUserLoginField", _SyntheticLoginField)
    _SyntheticMdClient.instances.clear()

    runner = importlib.import_module("examples.unified.014_2_ctp_options_midfreq.run")
    service_backend = importlib.import_module(
        "examples.unified.014_2_ctp_options_midfreq.service_live_backend"
    )
    bt_module = importlib.import_module("backtrader")
    original_cerebro_run = bt_module.Cerebro.run
    cerebro_errors: list[dict[str, str]] = []

    def capture_cerebro_error(self, *args: Any, **kwargs: Any):
        try:
            return original_cerebro_run(self, *args, **kwargs)
        except Exception as exc:
            cerebro_errors.append(
                {
                    "type": type(exc).__name__,
                    "message": str(exc)[:160],
                    "traceback": traceback.format_exc(limit=8),
                }
            )
            raise

    monkeypatch.setattr(bt_module.Cerebro, "run", capture_cerebro_error)
    proxy_module = importlib.import_module("backtrader.stores.service_read_proxy")
    original_poll_tick = proxy_module.ServiceReadProxy.poll_tick
    original_event_tick = proxy_module.ServiceReadProxy._event_tick
    proxy_type = proxy_module.ServiceReadProxy
    consumed_ticks: dict[str, int] = {}
    tick_failures: list[dict[str, Any]] = []

    def capture_event_tick_failure(proxy, dataname: str, event: Any, *, expected_sequence: int):
        try:
            return original_event_tick(
                proxy, dataname, event, expected_sequence=expected_sequence
            )
        except Exception as exc:
            data = event.payload.get("data") if hasattr(event, "payload") else None
            tick = data if isinstance(data, Mapping) else {}
            descriptor = proxy._ctp_tick_source_descriptors.get(dataname)
            client = proxy._binding(dataname).market_client
            current_descriptor = getattr(client, "source_descriptor", None)
            key = getattr(client, "key", None)
            tick_failures.append(
                {
                    "dataname": dataname,
                    "event_type": type(event).__name__,
                    "event_payload_keys": sorted(event.payload) if hasattr(event, "payload") else None,
                    "tick_data_type": type(data).__name__,
                    "tick_data_keys": sorted(tick) if tick else None,
                    "tick_symbol": tick.get("symbol"),
                    "tick_source": tick.get("source"),
                    "tick_clock_domain_id": tick.get("clock_domain_id"),
                    "tick_clock_source_session_id": tick.get("clock_source_session_id"),
                    "tick_clock_source": tick.get("clock_source"),
                    "tick_generation": tick.get("connection_generation"),
                    "descriptor_generation": getattr(descriptor, "connection_generation", None),
                    "tick_subscription_epoch": tick.get("subscription_epoch"),
                    "previous_scope": proxy._ctp_tick_scopes.get(dataname),
                    "descriptor": descriptor.to_dict() if hasattr(descriptor, "to_dict") else None,
                    "current_descriptor": current_descriptor.to_dict()
                    if hasattr(current_descriptor, "to_dict")
                    else None,
                    "bound_equals_current": current_descriptor == descriptor,
                    "descriptor_key_equals_client_key": getattr(descriptor, "key", None) == key,
                    "descriptor_stream_equals_client_key": getattr(descriptor, "stream_id", None)
                    == getattr(key, "stream_id", None),
                    "descriptor_epoch": getattr(descriptor, "epoch", None),
                    "client_cursor_epoch": getattr(client, "_cursor_epoch", None),
                    "client_state": getattr(client, "_state", None),
                    "client_recovery_required": getattr(client, "recovery_required", None),
                    "proxy_stream_epoch": proxy._stream_epochs.get(dataname),
                    "ingest_seq": tick.get("ingest_seq"),
                    "expected_sequence": expected_sequence,
                    "error": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                }
            )
            raise

    def count_real_proxy_ticks(proxy, dataname: str):
        event = original_poll_tick(proxy, dataname)
        if event is not None:
            consumed_ticks[dataname] = consumed_ticks.get(dataname, 0) + 1
        return event

    monkeypatch.setattr(
        proxy_type,
        "poll_tick",
        count_real_proxy_ticks,
    )
    monkeypatch.setattr(proxy_type, "_event_tick", capture_event_tick_failure)

    account_endpoint = _free_endpoint()
    market_rpc_endpoint = _free_endpoint()
    market_data_endpoint = _free_endpoint()
    account_service_id = "scn02-0142-account"
    market_service_id = "scn02-0142-market"
    account_instance = "scn02-0142-account-instance"
    market_instance = "scn02-0142-market-instance"
    account_scope_ref = "scn02-0142-account-scope-v1"
    market_scope_ref = "scn02-0142-market-scope-v1"
    account_transport = "scn02-0142-account-server-v1"
    market_transport = "scn02-0142-market-server-v1"
    account_security = "scn02-0142-account-curve-v1"
    market_security = "scn02-0142-market-curve-v1"
    account_raw = _service_config(
        account_service_id,
        account_instance,
        account_scope_ref,
        account_transport,
        account_security,
        account_endpoint,
        role="account_session_worker",
    )
    market_raw = _service_config(
        market_service_id,
        market_instance,
        market_scope_ref,
        market_transport,
        market_security,
        market_rpc_endpoint,
        market_bind=market_data_endpoint,
        role="market_hub",
    )
    account_service_config = parse_service_config(account_raw)
    market_service_config = parse_service_config(market_raw)

    account_server_keys = zmq.curve_keypair()
    account_client_public, account_client_secret = zmq.curve_keypair()
    account_authority, account_service_identity = _authority(
        account_service_config,
        server_keys=account_server_keys,
        client_public=account_client_public,
        client_principal=_CLIENT_PRINCIPAL,
        strategy_ref=_STRATEGY,
        domain=_DOMAIN,
        account_ref=_ACCOUNT_REF,
        operations=_ACCOUNT_OPERATIONS,
    )
    market_server_keys = zmq.curve_keypair()
    market_client_public, market_client_secret = zmq.curve_keypair()
    market_authority, market_service_identity = _authority(
        market_service_config,
        server_keys=market_server_keys,
        client_public=market_client_public,
        client_principal=_CLIENT_PRINCIPAL,
        strategy_ref=_STRATEGY,
        domain=_DOMAIN,
        account_ref=None,
        operations=_MARKET_OPERATIONS,
    )

    account_scope = GatewayServiceAccountScope(
        _ACCOUNT_REF,
        _DOMAIN,
        "journal:scn02-0142-account",
        account_read_strategy_scope="state:scn02-0142-account",
        shared_account_facts_scope="state:scn02-0142-account",
        shared_fact_strategy_refs=frozenset({_STRATEGY}),
    )
    account_gateway_principal = GatewayPrincipal(
        _CLIENT_PRINCIPAL,
        frozenset({"journal:scn02-0142-account"}),
        frozenset({"state:scn02-0142-account"}),
        frozenset({GatewayCommandKind.READ}),
    )
    account_quota = GatewayQuotaAdmission(
        tmp_path / "0142-account-quota.sqlite3",
        "synthetic:0142-account-quota",
        capacity_per_window=64,
        window_seconds=60.0,
        reserved_capacity=0,
        max_queue=64,
        max_queue_per_subject=16,
        max_backoff_seconds=1.0,
        max_queue_wait_seconds=5.0,
        poll_interval_seconds=0.005,
    )
    account_provider_holder: list[_SyntheticAccountProvider] = []

    def account_deployment_factory():
        guard_dir = tmp_path / "0142-account-guard"
        guard_dir.mkdir(exist_ok=True)
        journal = GatewayEventJournal(tmp_path / "0142-account-journal.sqlite3")

        def provider_factory(_session_ref: str, _credential: object):
            provider = _SyntheticAccountProvider()
            account_provider_holder.append(provider)
            return bind_ctp_instrument_metadata_provider(
                provider,
                request_feed=provider.ctp_request_feed,
                market_stream=provider.ctp_market_stream,
            )

        owner = GatewaySessionOwner(
            {"session:scn02-0142": "credential:synthetic-local"},
            resolve_credential=lambda _ref: object(),
            provider_factory=provider_factory,
        )
        binding = GatewayAccountSessionBinding(
            account_session_ref="session:scn02-0142",
            journal=journal,
            account_key=_ACCOUNT_KEY,
            account_scope=account_scope,
            state_scope="state:scn02-0142-account",
            guard=LocalAccountSessionGuard(
                guard_dir,
                _ACCOUNT_KEY.account_key_id,
                "scn02-0142-synthetic-owner",
            ),
            required_coverage=_COVERAGE,
            principals={_CLIENT_PRINCIPAL: account_gateway_principal},
            require_open_orders=True,
            refresh_interval_seconds=60.0,
            max_staleness_seconds=30.0,
            request_timeout_seconds=3.0,
            quota_admission=account_quota,
        )
        return GatewayOperatorDeployment(
            account_service_config,
            account_authority,
            tmp_path / "0142-account-registry.sqlite3",
            resource_provider=lambda *_args: pytest.fail("account role bypassed its worker"),
            session_owner=owner,
            account_session=binding,
        )

    market_keys = tuple(
        _market_key(instrument_id, "future" if leg == "future" else "option")
        for leg, full_symbol in _CONTRACTS.items()
        for instrument_id in (full_symbol.split(".", 1)[1],)
    )
    market_provider_holder: list[CtpQuoteV2MarketProvider] = []
    market_md_streams: list[CtpMarketStream] = []

    def market_provider_factory():
        def stream_factory(key: MarketSubscriptionKey, sink: BoundedCtpQuoteV2Queue):
            stream = CtpMarketStream(
                sink,
                broker_id="synthetic-broker",
                user_id="synthetic-investor",
                password="synthetic-password",
                auth_code="synthetic-auth-code",
                app_id="synthetic-app",
                td_front="tcp://127.0.0.1:1",
                md_front="tcp://127.0.0.1:1",
                ctp_env_profile="config_front_pair",
                ctp_environment="simnow",
            )
            market_md_streams.append(stream)
            return stream

        provider = CtpQuoteV2MarketProvider(
            stream_factory=stream_factory,
            source_ref=_SOURCE_REF,
            entitlement_ref=_ENTITLEMENT_REF,
            connect_timeout_seconds=2.0,
            stop_timeout_seconds=3.0,
        )
        market_provider_holder.append(provider)
        return provider

    def market_deployment_factory():
        return GatewayOperatorDeployment(
            market_service_config,
            market_authority,
            tmp_path / "0142-market-registry.sqlite3",
            resource_provider=lambda *_args: pytest.fail("market role bypassed its hub"),
            market_binding=GatewayMarketBinding(
                key_universe=market_keys,
                principal_allowed_keys={_CLIENT_PRINCIPAL: frozenset(market_keys)},
                provider_factory=market_provider_factory,
            ),
        )

    account_startup, account_stop, account_thread, account_holder = _host_thread(
        account_deployment_factory, "0142-account-service-host"
    )
    market_startup, market_stop, market_thread, market_holder = _host_thread(
        market_deployment_factory, "0142-market-service-host"
    )
    account_status = account_startup.get(timeout=10.0)
    market_status = market_startup.get(timeout=10.0)
    assert account_status[0] == "started", account_status
    assert market_status[0] == "started", market_status
    assert account_status[1] == account_endpoint
    assert market_status[1:] == (market_rpc_endpoint, market_data_endpoint)

    env_names = {
        account_security: ("SCN02_ACCOUNT_SERVER_KEY", "SCN02_ACCOUNT_CLIENT_PUBLIC", "SCN02_ACCOUNT_CLIENT_SECRET"),
        market_security: ("SCN02_MARKET_SERVER_KEY", "SCN02_MARKET_CLIENT_PUBLIC", "SCN02_MARKET_CLIENT_SECRET"),
    }
    for security_ref, names in env_names.items():
        values = (
            account_server_keys[0],
            account_client_public,
            account_client_secret,
        ) if security_ref == account_security else (
            market_server_keys[0],
            market_client_public,
            market_client_secret,
        )
        for env_name, value in zip(names, values, strict=True):
            monkeypatch.setenv(env_name, value.decode("ascii"))
    monkeypatch.setenv("BT_API_PY_ROOT", "D:/bt_api_py")
    client_document = _client_document(
        strategy_ref=_STRATEGY,
        account_endpoint=account_endpoint,
        market_rpc_endpoint=market_rpc_endpoint,
        market_data_endpoint=market_data_endpoint,
        account_instance=account_instance,
        account_scope=account_scope_ref,
        market_instance=market_instance,
        market_scope=market_scope_ref,
        account_transport="scn02-0142-account-client-v1",
        market_transport="scn02-0142-market-client-v1",
        account_security=account_security,
        market_security=market_security,
    )
    live = {
        "backend": "service",
        "schema_version": 1,
        "venue": "simnow",
        "policy": {"allow_write": False},
        "live_candidate": {
            "exchange": "CFFEX",
            "contracts": dict(_CONTRACTS),
            "strike": 4000,
            "multiplier": 100,
            "discount_factor": 1,
            "option_style": "European",
            "quantities": {"future": 1, "call": 1, "put": 1},
            "price_ticks": dict.fromkeys(_CONTRACTS.values(), 0.2),
            "signal": {"residual_floor_cny": 60},
        },
        "service": {
            "client_config": client_document,
            "identity": {
                "principal_ref": _CLIENT_PRINCIPAL,
                "strategy_ref": _STRATEGY,
                "execution_domain_ref": _DOMAIN,
            },
            "service_principals": {
                "scn02-0142-account": _ACCOUNT_SERVICE_PRINCIPAL,
                "scn02-0142-market": _MARKET_SERVICE_PRINCIPAL,
            },
            "curve_key_envs": {
                account_security: dict(
                    zip(("server_key_env", "client_public_key_env", "client_secret_key_env"), env_names[account_security], strict=True)
                ),
                market_security: dict(
                    zip(("server_key_env", "client_public_key_env", "client_secret_key_env"), env_names[market_security], strict=True)
                ),
            },
            "account": {
                "mount": "store.account",
                "account_ref": _ACCOUNT_REF,
                "key": _ACCOUNT_KEY.to_dict(),
                "required_coverage": [resource.to_dict() for resource in _COVERAGE],
                "resource_by_leg": {
                    "future": _COVERAGE[0].to_dict(),
                    "call": _COVERAGE[1].to_dict(),
                    "put": _COVERAGE[1].to_dict(),
                },
                "valuation_currency": "CNY",
                "position_mode": "net",
                "qty_unit": "contracts",
            },
            "market": {
                "mount": "store.market",
                "source_ref": _SOURCE_REF,
                "entitlement_ref": _ENTITLEMENT_REF,
            },
        },
        "timeouts": {"run_seconds": 0.8, "stop_seconds": 5.0},
        "observation": {"max_pending_decisions": 8, "quote_limit": 24},
    }
    raw_config = runner._load_raw_config()
    raw_config[runner.LIVE_ADAPTER_KEY] = live
    decision = runner.entry_tier.decide(raw_config, "live")
    assert decision.effective_tier == "live"
    args = SimpleNamespace(
        allow_write=False,
        run_seconds=0.8,
        evidence_dir=str(tmp_path / "0142-evidence"),
        tier_decision=decision,
    )

    try:
        exit_code = service_backend.run_live_service(args, raw_config, decision, runner)
        output = capsys.readouterr().out.strip().splitlines()[-1]
        summary = json.loads(output)
    finally:
        account_stop.set()
        market_stop.set()
        account_thread.join(10.0)
        market_thread.join(10.0)
        assert not account_thread.is_alive()
        assert not market_thread.is_alive()

    assert exit_code == runner.EXIT_BLOCKED
    assert summary["status"] == "BLOCKED"
    assert summary["reason"] == "ctp_source_clock_mapping_unqualified", json.dumps(
        {
            "reason": summary.get("reason"),
            "error_type": summary.get("error_type"),
            "run": summary.get("run"),
            "cleanup_errors": summary.get("cleanup_errors"),
            "broker_shutdown": summary.get("broker_shutdown"),
            "store_shutdown_state": summary.get("store_shutdown_state"),
            "cerebro_errors": cerebro_errors,
            "tick_failures": tick_failures,
        },
        sort_keys=True,
        default=str,
    )
    assert summary["clock_qualification"] == "NOT_QUALIFIED"
    assert summary["external_request_counts"] == {"order_write": 0}
    assert summary["service_session"]["account_coverage_count"] == 2
    assert summary["provider_operations"]["instrument_metadata"] == 3
    assert summary["provider_operations"]["market_subscriptions"] == 3
    assert summary["run"]["run_error_type"] is None, cerebro_errors
    assert summary["cleanup_status"] == "closed"
    assert summary["store_shutdown_state"] == "PASS"
    assert set(consumed_ticks) == {symbol.split(".", 1)[1] for symbol in _CONTRACTS.values()}
    assert all(count > 0 for count in consumed_ticks.values())

    descriptors = summary["service_session"]["metadata"]
    for leg, full_symbol in _CONTRACTS.items():
        projection = descriptors[leg]
        descriptor = projection["market_source_descriptor"]
        instrument_id = full_symbol.split(".", 1)[1]
        assert descriptor["key"]["instrument"]["instrument_id"] == instrument_id
        assert descriptor["key"]["instrument"]["native_symbol"] == instrument_id
        assert descriptor["source"] == "ctp.native.md"
        assert descriptor["clock_qualification"] == "NOT_QUALIFIED"
    market_descriptors = [descriptors[leg]["market_source_descriptor"] for leg in _CONTRACTS]
    assert len({item["clock_domain_id"] for item in market_descriptors}) == 1
    assert len({item["clock_source_session_id"] for item in market_descriptors}) == 1
    assert len({item["connection_generation"] for item in market_descriptors}) == 1
    assert len({item["clock_source"] for item in market_descriptors}) == 1

    account_deployment = account_holder["deployment"]
    market_deployment = market_holder["deployment"]
    assert account_deployment.state == market_deployment.state == "closed"
    assert len(account_provider_holder) == 1
    assert account_provider_holder[0].read_count >= 1
    assert account_provider_holder[0].close_count == 1
    assert len(account_provider_holder[0].trader_api.query_rows) == 3
    assert len(market_provider_holder) == 1
    assert market_provider_holder[0].diagnostics["active_handles"] == 0
    assert len(market_md_streams) == 1
    market_md_client = next(item for item in _SyntheticMdClient.instances if item.subscribed)
    expected_native_symbols = {symbol.split(".", 1)[1] for symbol in _CONTRACTS.values()}
    assert set(market_md_client.subscribed) | set(market_md_client.unsubscribed) == expected_native_symbols
    assert market_md_client.stop_calls == 1
    assert market_md_client.stop_wait_calls == 1
