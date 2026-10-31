from __future__ import annotations

import importlib
import json
import time
from types import SimpleNamespace

import pytest
from bt_api_base.account_protocol import AccountKey, AccountResourceKey
from bt_api_base.market_protocol import MarketSourceDescriptor, MarketSubscriptionKey

from backtrader.events import OrderBookSnapshot
from backtrader_runtime import service_observation
from backtrader_runtime import cross_exchange_orderbook_observation as observation


_STRATEGY = "012_1_midfreq_cross_exchange"


def _service(leg: str) -> dict:
    key = AccountKey(leg, leg, "demo", f"synthetic-{leg}")
    resource = AccountResourceKey("swap", "cross")
    return {
        "client_config": {},
        "identity": {"principal_ref": f"{leg}-client", "strategy_ref": _STRATEGY},
        "account": {
            "key": key.to_dict(),
            "resource_by_leg": {leg: resource.to_dict()},
            "required_coverage": [resource.to_dict()],
            "qty_unit": "contracts",
        },
        "market": {"source_ref": f"{leg}-market", "entitlement_ref": f"{leg}-read"},
    }


def _install_fake_sessions(
    monkeypatch: pytest.MonkeyPatch,
    services: dict[str, dict],
    *,
    cleanup_status: str = "PASS",
) -> list:
    opened = []

    def load(path: str):
        return services[path]

    monkeypatch.setattr(service_observation, "load_service_observation_config", load)
    monkeypatch.setattr(
        service_observation,
        "account_resource_key",
        lambda value: value if type(value) is AccountResourceKey else AccountResourceKey.from_dict(value),
    )
    monkeypatch.setattr(
        service_observation,
        "market_subscription_key",
        lambda value: value if type(value) is MarketSubscriptionKey else MarketSubscriptionKey.from_dict(value),
    )

    def open_session(service, *, instruments, allow_write, timeout_seconds, **_kwargs):
        assert allow_write is False
        assert timeout_seconds > 0
        assert len(instruments) == 1
        instrument = instruments[0]
        assert instrument.require_source_descriptor is True
        assert instrument.resource.product_type == instrument.market_key.instrument.product_type
        assert instrument.qty_unit == "contracts"
        assert instrument.quantity_multiplier == "1"
        leg = service["account"]["key"]["provider"]
        account_key = AccountKey.from_dict(service["account"]["key"])
        market_key = instrument.market_key
        descriptor = MarketSourceDescriptor(
            key=market_key,
            stream_id=market_key.stream_id,
            epoch=f"{leg}-epoch-1",
            provider=leg,
            source=f"synthetic.{leg}.orderbook",
            connection_generation=1,
            clock_domain_id=f"{leg}-clock",
            clock_source_session_id=f"{leg}-session",
            clock_source="synthetic-provider-time",
        )
        book = OrderBookSnapshot(
            timestamp=time.time(),
            symbol=market_key.instrument.native_symbol,
            exchange=market_key.instrument.venue,
            asset_type=market_key.instrument.product_type,
            bids=[(100.0, 2.0), (99.0, 3.0)],
            asks=[(101.0, 4.0), (102.0, 5.0)],
            exchange_time=time.time(),
            sequence=7,
            previous_sequence=None,
            snapshot_or_delta="snapshot",
            continuity_status="snapshot",
            stale=False,
            source=descriptor.source,
        )
        account_observation = SimpleNamespace(
            account_key=account_key,
            completed_at_utc="2026-10-17T00:00:00Z",
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
            open_orders_complete=True,
            coverage=(instrument.resource,),
            # These sentinels prove the output projection never serializes raw
            # account rows or values.
            balances=(SimpleNamespace(total="PRIVATE_BALANCE_SENTINEL"),),
            positions=(),
            open_orders=(),
        )

        class Session:
            account_view = SimpleNamespace(
                observation=account_observation,
                session_generation=f"{leg}-account-generation-1",
                cursor=11,
                fresh_until_monotonic=time.monotonic() + 30,
            )
            account_client = SimpleNamespace(healthy=True)
            market_clients = {instrument.dataname: SimpleNamespace(key=market_key)}

            def __init__(self):
                self.closed = 0

            def subscribe(self, dataname):
                assert dataname == instrument.dataname
                return descriptor

            def poll_orderbook(self, dataname):
                assert dataname == instrument.dataname
                return book

            def close(self):
                self.closed += 1
                return {
                    "status": cleanup_status,
                    "facades_closed": cleanup_status == "PASS",
                    "runtime_closed": cleanup_status == "PASS",
                }

        session = Session()
        opened.append((service, instrument, session))
        return session

    monkeypatch.setattr(service_observation, "open_service_read_session", open_session)
    return opened


def test_012_pair_observes_two_independent_read_only_orderbooks(monkeypatch):
    services = {"okx.json": _service("okx"), "binance.json": _service("binance")}
    opened = _install_fake_sessions(monkeypatch, services)

    report = observation.observe_cross_exchange_orderbooks(
        okx_config_path="okx.json",
        binance_config_path="binance.json",
        strategy_id=_STRATEGY,
        timeout_ms=500,
        depth=5,
        max_event_age_seconds="2.0",
    )

    assert report["status"] == "OBSERVED"
    assert report["write_capability"] == "UNSUPPORTED"
    assert report["trade_execution"] == "not_run"
    assert report["execution_eligible"] is False
    assert report["cross_venue_alignment"] == "NOT_EVALUATED"
    assert [row["symbol"] for row in report["legs"]] == ["BTC-USDT-SWAP", "BTCUSDT"]
    assert [row["account_snapshot"]["account_key_id"] for row in report["legs"]][0] != [
        row["account_snapshot"]["account_key_id"] for row in report["legs"]
    ][1]
    assert all(row["source"]["key_matches"] for row in report["legs"])
    assert all(row["source"]["execution_eligible"] is False for row in report["legs"])
    assert all(row["orderbook"]["sequence"] == 7 for row in report["legs"])
    assert all(row["orderbook"]["depth"] == 5 for row in report["legs"])
    assert all(row["cleanup"]["status"] == "PASS" for row in report["legs"])
    assert len(opened) == 2
    assert [row[0]["identity"]["strategy_ref"] for row in opened] == [_STRATEGY, _STRATEGY]
    assert all(session.closed == 1 for _service, _instrument, session in opened)
    assert "PRIVATE_BALANCE_SENTINEL" not in json.dumps(report)


def test_012_bad_second_leg_is_rejected_before_opening_first_session(monkeypatch):
    services = {"okx.json": _service("okx"), "binance.json": _service("okx")}
    opened = _install_fake_sessions(monkeypatch, services)

    with pytest.raises(service_observation.ServiceObservationError) as caught:
        observation.observe_cross_exchange_orderbooks(
            okx_config_path="okx.json",
            binance_config_path="binance.json",
            strategy_id=_STRATEGY,
        )

    assert caught.value.code == "ACCOUNT_LEG_IDENTITY_MISMATCH"
    assert opened == []


def test_012_uncertain_session_cleanup_never_reports_observed(monkeypatch):
    services = {"okx.json": _service("okx"), "binance.json": _service("binance")}
    opened = _install_fake_sessions(monkeypatch, services, cleanup_status="UNCONFIRMED")

    report = observation.observe_cross_exchange_orderbooks(
        okx_config_path="okx.json",
        binance_config_path="binance.json",
        strategy_id=_STRATEGY,
    )

    assert report["status"] == "UNKNOWN"
    assert all(row["status"] == "UNKNOWN" for row in report["legs"])
    assert all(row["reason"] == "cleanup_unconfirmed" for row in report["legs"])
    assert all(row["cleanup"]["status"] == "UNCONFIRMED" for row in report["legs"])
    assert all(session.closed == 1 for _service, _instrument, session in opened)


def test_012_read_handler_preserves_no_config_and_requires_config_pair(monkeypatch, capsys):
    routed = []

    def fake_observe(**kwargs):
        routed.append(kwargs)
        return {
            "status": "OBSERVED",
            "write_capability": "UNSUPPORTED",
            "trade_execution": "not_run",
            "execution_eligible": False,
            "cross_venue_alignment": "NOT_EVALUATED",
        }

    monkeypatch.setattr(observation, "observe_cross_exchange_orderbooks", fake_observe)
    for name in (
        "examples.unified.012_1_midfreq_cross_exchange.run",
        "examples.unified.012_2_event_driven_cross_exchange.run",
    ):
        runner = importlib.import_module(name)
        decision = SimpleNamespace(as_evidence=lambda: {"effective_tier": "live"})

        assert runner.run_live_observe(SimpleNamespace(tier_decision=decision)) == runner.EXIT_BLOCKED
        no_config = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert no_config["reason"] == "live_observation_unavailable"
        assert no_config["write_grant_result"] == "not_requested"
        assert no_config["gap"] == "independent account/orderbook observation requires both explicit service configs"
        assert "--service-config-okx" in no_config["hint"]

        result = runner.run_live_observe(
            SimpleNamespace(
                tier_decision=decision,
                service_config_okx="okx.json",
                service_config_binance=None,
            )
        )
        partial = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert result == runner.EXIT_BLOCKED
        assert partial["reason"] == "service_config_pair_incomplete"
        assert partial["write_grant_result"] == "not_requested"

        result = runner.main(
            [
                "--live",
                "--service-config-okx",
                "okx.json",
                "--service-config-binance",
                "binance.json",
                "--service-observation-timeout-ms",
                "700",
                "--service-book-depth",
                "3",
            ]
        )
        successful = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert result == runner.EXIT_PASS
        assert successful["write_grant_result"] == "not_requested"
        assert successful["trade_execution"] == "not_run"

    assert routed == [
        {
            "okx_config_path": "okx.json",
            "binance_config_path": "binance.json",
            "strategy_id": "012_1_midfreq_cross_exchange",
            "timeout_ms": 700,
            "depth": 3,
            "max_event_age_seconds": "2.0",
        },
        {
            "okx_config_path": "okx.json",
            "binance_config_path": "binance.json",
            "strategy_id": "012_2_event_driven_cross_exchange",
            "timeout_ms": 700,
            "depth": 3,
            "max_event_age_seconds": "0.50",
        },
    ]
