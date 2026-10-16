"""014_1/015 public live selectors through local SDK Gateway Hosts.

Only the terminal/account leaves are synthetic. ServiceHost, CURVE transports,
SDK clients, ServiceReadProxy, BtApiStore/Feed, Broker, Cerebro, and each target
strategy are the ordinary production classes. No exchange or account is used.
"""

from __future__ import annotations

import copy
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import zmq
from bt_api_base.account_protocol import AccountKey, AccountResourceKey
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_gateway.ctp_instrument_metadata import bind_ctp_instrument_metadata_provider
from bt_api_gateway.event_journal import GatewayEventJournal
from bt_api_gateway.quota_admission import GatewayQuotaAdmission
from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
from bt_api_gateway.service_component import GatewayServiceAccountScope
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_gateway.session_owner import GatewaySessionOwner
from bt_api_py.gateway_operator import GatewayAccountSessionBinding, GatewayMarketBinding, GatewayOperatorDeployment
from bt_api_py.service_config import parse_service_config

from bt_api_ctp.feeds import live_ctp_feed
from bt_api_ctp.market_provider import CtpQuoteV2MarketProvider


_TARGETS = {
    "014_1": {
        "runner": "examples.unified.014_1_ctp_options_lowfreq.run",
        "strategy": "ctp_options_lowfreq",
        "contracts": {
            "future": "CZCE.SA701",
            "call": "CZCE.SA701C1080",
            "put": "CZCE.SA701P1080",
        },
        "metadata": {
            "CZCE.SA701": {"price_tick": 1.0, "volume_multiple": 20},
            "CZCE.SA701C1080": {"price_tick": 0.5, "volume_multiple": 20},
            "CZCE.SA701P1080": {"price_tick": 0.5, "volume_multiple": 20},
        },
    },
    "015": {
        "runner": "examples.unified.015_ctp_options_highfreq.run",
        "strategy": "ctp_options_highfreq",
        "contracts": {
            "future": "CZCE.FG701",
            "call": "CZCE.FG701C970",
            "put": "CZCE.FG701P970",
        },
        "metadata": {
            "CZCE.FG701": {"price_tick": 1.0, "volume_multiple": 20},
            "CZCE.FG701C970": {"price_tick": 0.5, "volume_multiple": 20},
            "CZCE.FG701P970": {"price_tick": 0.5, "volume_multiple": 20},
        },
    },
}


def _case_config(service_helpers: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str):
    target = _TARGETS[case]
    runner = importlib.import_module(target["runner"])
    strategy = target["strategy"]
    contracts = dict(target["contracts"])
    helper_module = service_helpers

    domain = f"paper:scn02-{case}-service-entry"
    account_ref = f"account:scn02-{case}"
    client_principal = f"principal:scn02-{case}-client"
    # Service IDs are inherited from the 0142 host builder, which derives
    # each host WireIdentity as ``principal:{service_id}``.
    account_principal = "principal:scn02-0142-account"
    market_principal = "principal:scn02-0142-market"
    source_ref = f"ctp-native-market-{case}-r1"
    entitlement_ref = f"ctp-quote-v2-{case}-r1"
    coverage = (
        AccountResourceKey("future", "futures"),
        AccountResourceKey("option", "options"),
    )
    account_key = AccountKey("ctp", "CZCE", "simnow", f"synthetic-{case}-account")
    instruments = {
        symbol.split(".", 1)[1]: "future" if role == "future" else "option"
        for role, symbol in contracts.items()
    }

    for name, value in {
        "_DOMAIN": domain,
        "_STRATEGY": strategy,
        "_ACCOUNT_REF": account_ref,
        "_CLIENT_PRINCIPAL": client_principal,
        # _authority() binds the service identity from these stable service IDs.
        "_ACCOUNT_SERVICE_PRINCIPAL": "principal:scn02-0142-account",
        "_MARKET_SERVICE_PRINCIPAL": "principal:scn02-0142-market",
        "_SOURCE_REF": source_ref,
        "_ENTITLEMENT_REF": entitlement_ref,
        "_ACCOUNT_KEY": account_key,
        "_COVERAGE": coverage,
        "_CONTRACTS": contracts,
        "_INSTRUMENTS": instruments,
    }.items():
        monkeypatch.setattr(helper_module, name, value)

    class TargetMdClient(helper_module._SyntheticMdClient):
        def _emit_ticks(self) -> None:
            first_event_time = helper_module.datetime.now(helper_module.UTC).astimezone(
                helper_module.timezone(helper_module.timedelta(hours=8))
            ) - helper_module.timedelta(minutes=5)
            for offset in range(3):
                if not self._active.is_set():
                    return
                event_time = first_event_time + helper_module.timedelta(minutes=offset)
                symbols = tuple(self.subscribed)
                update_time = event_time.strftime("%H:%M:%S")
                for symbol in symbols:
                    self._cumulative[symbol] = self._cumulative.get(symbol, 0) + 1
                    last = 972.0 if instruments[symbol] == "future" else 16.0
                    tick = SimpleNamespace(
                        InstrumentID=symbol,
                        ExchangeID="CZCE",
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

    monkeypatch.setattr(live_ctp_feed.ctp_client, "MdClient", TargetMdClient)
    monkeypatch.setattr(
        live_ctp_feed.ctp_client,
        "CThostFtdcReqUserLoginField",
        helper_module._SyntheticLoginField,
    )

    def query_target_instrument(self, field: object, request_id: int) -> int:
        instrument_id = str(getattr(field, "InstrumentID", ""))
        exchange_id = str(getattr(field, "ExchangeID", ""))
        self.query_rows.append((instrument_id, exchange_id, str(getattr(field, "ProductID", ""))))
        self.trader._handle_query_callback(
            "instruments",
            SimpleNamespace(
                InstrumentID=instrument_id,
                ExchangeID=exchange_id,
                ProductClass="1" if instruments[instrument_id] == "future" else "2",
                PriceTick=1.0 if instruments[instrument_id] == "future" else 0.5,
                VolumeMultiple=20,
            ),
            None,
            request_id,
            True,
        )
        return 0

    monkeypatch.setattr(helper_module._SyntheticTraderApi, "ReqQryInstrument", query_target_instrument)

    account_endpoint = helper_module._free_endpoint()
    market_rpc_endpoint = helper_module._free_endpoint()
    market_data_endpoint = helper_module._free_endpoint()
    account_service_id = "scn02-0142-account"
    market_service_id = "scn02-0142-market"
    account_session_ref = "session:scn02-0142"
    account_instance = f"scn02-{case}-account-instance"
    market_instance = f"scn02-{case}-market-instance"
    account_scope_ref = f"scn02-{case}-account-scope-v1"
    market_scope_ref = f"scn02-{case}-market-scope-v1"
    account_transport = f"scn02-{case}-account-server-v1"
    market_transport = f"scn02-{case}-market-server-v1"
    account_security = f"scn02-{case}-account-curve-v1"
    market_security = f"scn02-{case}-market-curve-v1"
    account_raw = helper_module._service_config(
        account_service_id, account_instance, account_scope_ref, account_transport,
        account_security, account_endpoint, role="account_session_worker",
    )
    market_raw = helper_module._service_config(
        market_service_id, market_instance, market_scope_ref, market_transport,
        market_security, market_rpc_endpoint, market_bind=market_data_endpoint,
        role="market_hub",
    )
    account_service_config = parse_service_config(account_raw)
    market_service_config = parse_service_config(market_raw)

    account_server_keys = zmq.curve_keypair()
    account_client_public, account_client_secret = zmq.curve_keypair()
    account_authority, _ = helper_module._authority(
        account_service_config,
        server_keys=account_server_keys,
        client_public=account_client_public,
        client_principal=client_principal,
        strategy_ref=strategy,
        domain=domain,
        account_ref=account_ref,
        operations=helper_module._ACCOUNT_OPERATIONS,
    )
    market_server_keys = zmq.curve_keypair()
    market_client_public, market_client_secret = zmq.curve_keypair()
    market_authority, _ = helper_module._authority(
        market_service_config,
        server_keys=market_server_keys,
        client_public=market_client_public,
        client_principal=client_principal,
        strategy_ref=strategy,
        domain=domain,
        account_ref=None,
        operations=helper_module._MARKET_OPERATIONS,
    )

    account_scope = GatewayServiceAccountScope(
        account_ref,
        domain,
        f"journal:scn02-{case}-account",
        account_read_strategy_scope=f"state:scn02-{case}-account",
        shared_account_facts_scope=f"state:scn02-{case}-account",
        shared_fact_strategy_refs=frozenset({strategy}),
    )
    account_principal_record = GatewayPrincipal(
        client_principal,
        frozenset({f"journal:scn02-{case}-account"}),
        frozenset({f"state:scn02-{case}-account"}),
        frozenset({GatewayCommandKind.READ}),
    )
    quota = GatewayQuotaAdmission(
        tmp_path / f"{case}-account-quota.sqlite3",
        f"synthetic:{case}-account-quota",
        capacity_per_window=64,
        window_seconds=60.0,
        reserved_capacity=0,
        max_queue=64,
        max_queue_per_subject=16,
        max_backoff_seconds=1.0,
        max_queue_wait_seconds=5.0,
        poll_interval_seconds=0.005,
    )
    account_provider_holder = []

    def account_deployment_factory():
        guard_dir = tmp_path / f"{case}-account-guard"
        guard_dir.mkdir(exist_ok=True)
        journal = GatewayEventJournal(tmp_path / f"{case}-account-journal.sqlite3")

        def provider_factory(_session_ref: str, _credential: object):
            provider = helper_module._SyntheticAccountProvider()
            account_provider_holder.append(provider)
            return bind_ctp_instrument_metadata_provider(
                provider,
                request_feed=provider.ctp_request_feed,
                market_stream=provider.ctp_market_stream,
            )

        owner = GatewaySessionOwner(
            {account_session_ref: f"credential:synthetic-{case}"},
            resolve_credential=lambda _ref: object(),
            provider_factory=provider_factory,
        )
        return GatewayOperatorDeployment(
            account_service_config,
            account_authority,
            tmp_path / f"{case}-account-registry.sqlite3",
            resource_provider=lambda *_args: pytest.fail("account role bypassed its worker"),
            session_owner=owner,
            account_session=GatewayAccountSessionBinding(
                account_session_ref=account_session_ref,
                journal=journal,
                account_key=account_key,
                account_scope=account_scope,
                state_scope=f"state:scn02-{case}-account",
                guard=LocalAccountSessionGuard(
                    guard_dir, account_key.account_key_id, f"scn02-{case}-synthetic-owner"
                ),
                required_coverage=coverage,
                principals={client_principal: account_principal_record},
                require_open_orders=True,
                refresh_interval_seconds=60.0,
                max_staleness_seconds=30.0,
                request_timeout_seconds=3.0,
                quota_admission=quota,
            ),
        )

    market_keys = tuple(
        MarketSubscriptionKey(
            source_ref=source_ref,
            entitlement_ref=entitlement_ref,
            instrument=MarketInstrumentKey(
                provider="ctp",
                venue="CZCE",
                environment="simnow",
                product_type=instruments[name],
                instrument_id=name,
                native_symbol=name,
            ),
            channel="ctp.quote.v2",
        )
        for name in instruments
    )
    market_provider_holder = []
    md_streams = []

    def market_provider_factory():
        def stream_factory(_key, sink):
            stream = helper_module.CtpMarketStream(
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
            md_streams.append(stream)
            return stream

        provider = CtpQuoteV2MarketProvider(
            stream_factory=stream_factory,
            source_ref=source_ref,
            entitlement_ref=entitlement_ref,
            connect_timeout_seconds=2.0,
            stop_timeout_seconds=3.0,
        )
        market_provider_holder.append(provider)
        return provider

    def market_deployment_factory():
        return GatewayOperatorDeployment(
            market_service_config,
            market_authority,
            tmp_path / f"{case}-market-registry.sqlite3",
            resource_provider=lambda *_args: pytest.fail("market role bypassed its hub"),
            market_binding=GatewayMarketBinding(
                key_universe=market_keys,
                principal_allowed_keys={client_principal: frozenset(market_keys)},
                provider_factory=market_provider_factory,
            ),
        )

    account_startup, account_stop, account_thread, account_holder = helper_module._host_thread(
        account_deployment_factory, f"{case}-account-host"
    )
    market_startup, market_stop, market_thread, market_holder = helper_module._host_thread(
        market_deployment_factory, f"{case}-market-host"
    )
    account_status = account_startup.get(timeout=10.0)
    market_status = market_startup.get(timeout=10.0)
    assert account_status[0] == market_status[0] == "started", (account_status, market_status)

    env_names = {
        account_security: (f"SCN02_{case}_ACCOUNT_SERVER_KEY", f"SCN02_{case}_ACCOUNT_CLIENT_PUBLIC", f"SCN02_{case}_ACCOUNT_CLIENT_SECRET"),
        market_security: (f"SCN02_{case}_MARKET_SERVER_KEY", f"SCN02_{case}_MARKET_CLIENT_PUBLIC", f"SCN02_{case}_MARKET_CLIENT_SECRET"),
    }
    for security, names in env_names.items():
        values = (account_server_keys[0], account_client_public, account_client_secret) if security == account_security else (
            market_server_keys[0], market_client_public, market_client_secret
        )
        for env_name, value in zip(names, values, strict=True):
            monkeypatch.setenv(env_name, value.decode("ascii"))
    monkeypatch.setenv("BT_API_PY_ROOT", "D:/bt_api_py")
    client_config = helper_module._client_document(
        strategy_ref=strategy,
        account_endpoint=account_status[1],
        market_rpc_endpoint=market_status[1],
        market_data_endpoint=market_status[2],
        account_instance=account_instance,
        account_scope=account_scope_ref,
        market_instance=market_instance,
        market_scope=market_scope_ref,
        account_transport=f"scn02-{case}-account-client-v1",
        market_transport=f"scn02-{case}-market-client-v1",
        account_security=account_security,
        market_security=market_security,
    )
    resource_by_leg = {
        "future": coverage[0].to_dict(),
        "call": coverage[1].to_dict(),
        "put": coverage[1].to_dict(),
    }
    live = copy.deepcopy(runner._load_raw_config()[runner.LIVE_ADAPTER_KEY])
    live.update(
        backend="service",
        live_candidate={"exchange": "CZCE", "contracts": contracts},
        instrument_metadata=copy.deepcopy(target["metadata"]),
        policy={"allow_write": False},
        timeouts={"run_seconds": 0.8, "stop_seconds": 5.0},
        observation={"quote_limit": 24, "max_pending_decisions": 8},
        service={
            "client_config": client_config,
            "identity": {
                "principal_ref": client_principal,
                "strategy_ref": strategy,
                "execution_domain_ref": domain,
            },
            "service_principals": {
                account_service_id: account_principal,
                market_service_id: market_principal,
            },
            "curve_key_envs": {
                account_security: dict(zip(
                    ("server_key_env", "client_public_key_env", "client_secret_key_env"),
                    env_names[account_security], strict=True,
                )),
                market_security: dict(zip(
                    ("server_key_env", "client_public_key_env", "client_secret_key_env"),
                    env_names[market_security], strict=True,
                )),
            },
            "account": {
                "mount": "store.account",
                "account_ref": account_ref,
                "key": account_key.to_dict(),
                "required_coverage": [item.to_dict() for item in coverage],
                "resource_by_leg": resource_by_leg,
                "valuation_currency": "CNY",
                "position_mode": "net",
                "qty_unit": "contracts",
            },
            "market": {
                "mount": "store.market",
                "source_ref": source_ref,
                "entitlement_ref": entitlement_ref,
            },
        },
    )
    raw_config = runner._load_raw_config()
    raw_config[runner.LIVE_ADAPTER_KEY] = live
    return runner, raw_config, {
        "account_stop": account_stop,
        "market_stop": market_stop,
        "account_thread": account_thread,
        "market_thread": market_thread,
        "account_holder": account_holder,
        "market_holder": market_holder,
        "account_provider_holder": account_provider_holder,
        "market_provider_holder": market_provider_holder,
        "md_streams": md_streams,
        "instruments": instruments,
    }


@pytest.mark.integration
@pytest.mark.parametrize("case", ("014_1", "015"))
def test_0141_and_015_public_live_selector_uses_service_hosts_and_real_bt(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper_module = importlib.import_module("tests.integration.test_0142_service_backend_ctp_host")
    runner, raw_config, hosts = _case_config(helper_module, monkeypatch, tmp_path, case)
    proxy_module = importlib.import_module("backtrader.stores.service_read_proxy")
    original_poll_tick = proxy_module.ServiceReadProxy.poll_tick
    consumed: dict[str, int] = {}

    def count_poll(proxy: Any, dataname: str):
        event = original_poll_tick(proxy, dataname)
        if event is not None:
            consumed[dataname] = consumed.get(dataname, 0) + 1
        return event

    monkeypatch.setattr(proxy_module.ServiceReadProxy, "poll_tick", count_poll)
    monkeypatch.setattr(runner, "_load_raw_config", lambda: raw_config)
    try:
        exit_code = runner.main(["--live", "--run-seconds", "0.8", "--evidence-dir", str(tmp_path / f"{case}-evidence")])
        summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    finally:
        hosts["account_stop"].set()
        hosts["market_stop"].set()
        hosts["account_thread"].join(10.0)
        hosts["market_thread"].join(10.0)
    assert not hosts["account_thread"].is_alive()
    assert not hosts["market_thread"].is_alive()

    assert exit_code == runner.EXIT_BLOCKED
    assert summary["backend"] == "service"
    assert summary["status"] == "BLOCKED"
    assert summary.get("cleanup_status") == "PASS", json.dumps(
        {
            key: summary.get(key)
            for key in (
                "reason",
                "error_type",
                "error_code",
                "cleanup_status",
                "service_session",
                "provider_operations",
                "run",
                "strategy_observation",
            )
        },
        sort_keys=True,
        default=str,
    )
    assert summary["external_request_counts"] == {"order_write": 0}
    assert summary["service_session"]["account_snapshot_id_present"] is True
    assert summary["service_session"]["account_coverage_count"] == 2
    assert summary["provider_operations"] == {
        "account_snapshot": "COMPLETE",
        "instrument_metadata": 3,
        "market_subscriptions": 3,
    }
    expected_names = set(hosts["instruments"])
    assert set(consumed) == expected_names
    assert all(consumed[name] > 0 for name in expected_names)

    if case == "014_1":
        assert summary["example_id"] == "014_1_ctp_options_lowfreq"
        assert summary["clock_qualification"] == "NOT_QUALIFIED"
        assert summary["reason"] == "service_clock_mapping_unqualified"
        assert summary["run"]["strategy_created"] is True
        assert summary["run"]["run_error_type"] is None
        assert summary["observation"]["bar_cohorts"] == 0
    else:
        assert summary["example_id"] == "015_ctp_options_highfreq"
        assert summary["reason"] == "service_trusted_now_unavailable"
        assert summary["trusted_now_status"] == "TRUSTED_NOW_INVALID"
        assert summary["cohort_admission"] == "NOT_ADMITTED"
        assert summary["confirmed_cohort_count"] == 0
        assert summary["hft_status"] == "NOT_ADMITTED"
        assert summary["strategy_observation"]["strategy_created"] is True
        assert summary["strategy_observation"]["run_error_type"] is None
        assert summary["strategy_observation"]["reject_counts"]["TRUSTED_NOW_INVALID"] > 0
        assert summary["strategy_observation"]["ordinary_intent_count"] == 0

    assert hosts["account_holder"]["deployment"].state == "closed"
    assert hosts["market_holder"]["deployment"].state == "closed"
    assert len(hosts["account_provider_holder"]) == 1
    assert hosts["account_provider_holder"][0].close_count == 1
    assert len(hosts["account_provider_holder"][0].trader_api.query_rows) == 3
    assert len(hosts["market_provider_holder"]) == 1
    assert hosts["market_provider_holder"][0].diagnostics["active_handles"] == 0
    assert len(hosts["md_streams"]) == 1


@pytest.mark.integration
@pytest.mark.parametrize("case", ("014_1", "015"))
def test_service_public_selector_refuses_write_grant_before_session_start(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _TARGETS[case]
    runner = importlib.import_module(target["runner"])
    config = runner._load_raw_config()
    live = copy.deepcopy(config[runner.LIVE_ADAPTER_KEY])
    live["backend"] = "service"
    live["service"] = object()
    config[runner.LIVE_ADAPTER_KEY] = live
    monkeypatch.setattr(runner, "_load_raw_config", lambda: config)

    def forbidden(*_args: Any, **_kwargs: Any):
        pytest.fail("write request reached service session construction")

    helper = importlib.import_module("backtrader_runtime.service_observation")
    monkeypatch.setattr(helper, "open_service_read_session", forbidden)
    exit_code = runner.main(["--live", "--allow-write"])
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert exit_code == runner.EXIT_BLOCKED
    assert summary["reason"] == "service_backend_is_read_only"
    assert summary["external_request_counts"] == {"order_write": 0}
