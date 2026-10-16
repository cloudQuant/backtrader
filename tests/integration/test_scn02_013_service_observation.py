"""013 public service-observation entries against local SDK Gateway Hosts.

Only CTP account/market leaves are synthetic. The test runs the three public
``run.py`` selectors against one local account Host and one local market Host;
the SDK client, CURVE RPC/event path, account metadata reader and service
observation helper remain real. No exchange, credential file, Broker, strategy,
or order-capable service is used.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


_BUNDLE_CASE = "013bundle"
_BUNDLE_STRATEGY = "scn02_013_service_observation"
_CONTRACTS = {
    "013_1": (("m2611", "DCE"), ("rm611", "CZCE")),
    "013_2": (("rb2611", "SHFE"), ("rb2701", "SHFE")),
    "013_3": (("SA701", "CZCE"),),
}
_EXCHANGE_BY_INSTRUMENT = {
    instrument: exchange
    for pairs in _CONTRACTS.values()
    for instrument, exchange in pairs
}


def _runner_config(case: str) -> dict[str, Any]:
    if case == "013_1":
        return {
            "live_contracts": {
                "symbols": ["m2611", "rm611"],
                "exchanges": {"m": "DCE", "rm": "CZCE"},
            }
        }
    if case == "013_2":
        return {
            "live_contracts": {
                "symbols": ["rb2611", "rb2701"],
                "exchanges": {"rb": "SHFE"},
            }
        }
    return {"live_contract": {"instrument": "SA701", "exchange": "CZCE"}}


def _tick_emitter(helper_module: ModuleType):
    def emit_ticks(self: Any) -> None:
        while self._active.is_set():
            event_time = helper_module.datetime.now(helper_module.UTC).astimezone(
                helper_module.timezone(helper_module.timedelta(hours=8))
            ) - helper_module.timedelta(minutes=5)
            update_time = event_time.strftime("%H:%M:%S")
            for symbol in tuple(self.subscribed):
                self._cumulative[symbol] = self._cumulative.get(symbol, 0) + 1
                last = 3_200.0 + self._cumulative[symbol]
                tick = helper_module.SimpleNamespace(
                    InstrumentID=symbol,
                    ExchangeID=_EXCHANGE_BY_INSTRUMENT[symbol],
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
                    LowerLimitPrice=last - 500,
                    TradingDay=event_time.strftime("%Y%m%d"),
                    ActionDay=event_time.strftime("%Y%m%d"),
                    UpdateTime=update_time,
                    UpdateMillisec=event_time.microsecond // 1_000,
                )
                if callable(self.on_tick):
                    self.on_tick(tick)
            # Event.wait() returns immediately while the event is set, so it
            # cannot serve as a paced wait here.  Keep the synthetic native
            # stream active long enough for subscriptions added after the
            # first key to receive their own callback.
            helper_module.time.sleep(0.025)

    return emit_ticks


@pytest.mark.integration
def test_013_public_service_observation_entries_share_local_gateway_hosts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise each public CLI selector through one synthetic read-only host pair."""

    entry_fixture = importlib.import_module("tests.integration.test_scn02_0141_015_service_entry")
    gateway_fixture = importlib.import_module("tests.integration.test_0142_service_backend_ctp_host")

    target_contracts = {
        "future": "DCE.m2611",
        "call": "CZCE.rm611",
        "put": "SHFE.rb2611",
        "rb_next": "SHFE.rb2701",
        "sa": "CZCE.SA701",
    }
    target = {
        "runner": "scn02_013_fixture_runner",
        "strategy": _BUNDLE_STRATEGY,
        "contracts": target_contracts,
        "metadata": {
            symbol: {"price_tick": 1.0, "volume_multiple": 20}
            for symbol in target_contracts.values()
        },
    }
    fixture_runner = ModuleType("scn02_013_fixture_runner")
    fixture_runner.LIVE_ADAPTER_KEY = "live_adapter"
    fixture_runner._load_raw_config = lambda: {"live_adapter": {}}
    monkeypatch.setitem(sys.modules, fixture_runner.__name__, fixture_runner)
    monkeypatch.setitem(entry_fixture._TARGETS, _BUNDLE_CASE, target)

    original_instrument_key = entry_fixture.MarketInstrumentKey

    def exact_venue_future_key(**values: Any):
        instrument_id = values["instrument_id"]
        values["venue"] = _EXCHANGE_BY_INSTRUMENT[instrument_id]
        # All five public contracts in this test are CTP futures. The fixture's
        # positional roles (future/call/put) describe 014 case structure only.
        values["product_type"] = "future"
        return original_instrument_key(**values)

    monkeypatch.setattr(entry_fixture, "MarketInstrumentKey", exact_venue_future_key)

    fixture_runner, host_config, hosts = entry_fixture._case_config(
        gateway_fixture, monkeypatch, tmp_path, _BUNDLE_CASE
    )

    md_client_type = gateway_fixture.live_ctp_feed.ctp_client.MdClient
    monkeypatch.setattr(md_client_type, "_emit_ticks", _tick_emitter(gateway_fixture))

    def query_exact_future_metadata(self: Any, field: object, request_id: int) -> int:
        instrument_id = str(getattr(field, "InstrumentID", ""))
        exchange_id = str(getattr(field, "ExchangeID", ""))
        self.query_rows.append(
            (instrument_id, exchange_id, str(getattr(field, "ProductID", "")))
        )
        self.trader._handle_query_callback(
            "instruments",
            gateway_fixture.SimpleNamespace(
                InstrumentID=instrument_id,
                ExchangeID=exchange_id,
                ProductClass="1",
                PriceTick=1.0,
                VolumeMultiple=20,
            ),
            None,
            request_id,
            True,
        )
        return 0

    monkeypatch.setattr(
        gateway_fixture._SyntheticTraderApi,
        "ReqQryInstrument",
        query_exact_future_metadata,
    )

    service_config = host_config[fixture_runner.LIVE_ADAPTER_KEY]["service"]
    service_path = tmp_path / "013-service-client.json"
    service_path.write_text(
        json.dumps({"service": service_config}, sort_keys=True), encoding="utf-8"
    )
    observed: dict[str, dict[str, Any]] = {}
    run_modules = {
        "013_1": "examples.unified.013_1_midfreq_cross_arbitrage.run",
        "013_2": "examples.unified.013_2_highfreq_calendar_arbitrage.run",
        "013_3": "examples.unified.013_3_sa_midfreq_simnow.run",
    }
    try:
        for case, module_name in run_modules.items():
            runner = importlib.import_module(module_name)
            config = {"entry": {"tier": "live"}, **_runner_config(case)}
            if case != "013_3":
                monkeypatch.setattr(
                    runner,
                    "_load_config",
                    lambda config=config, case=case: (config, tmp_path / f"{case}.yaml"),
                )
            else:
                monkeypatch.setattr(
                    runner,
                    "_load_config",
                    lambda config=config, case=case: (config, {}, tmp_path / f"{case}.yaml"),
                )
            monkeypatch.setattr(
                runner,
                "_load_env",
                lambda: pytest.fail("service observation attempted .env loading"),
                raising=False,
            )
            monkeypatch.setattr(
                runner,
                "_ensure_dev_sdk_path",
                lambda **_kwargs: pytest.fail("service observation used direct SDK bootstrap"),
                raising=False,
            )
            if case in {"013_1", "013_2"}:
                monkeypatch.setitem(sys.modules, "legacy_runner", None)

            exit_code = runner.main(
                [
                    "--live",
                    "--backend",
                    "service",
                    "--service-config",
                    str(service_path),
                    "--service-timeout-ms",
                    "2000",
                    "--evidence-dir",
                    str(tmp_path / f"{case}-evidence"),
                ]
            )
            output = capsys.readouterr().out.strip().splitlines()
            summary = json.loads(output[-1])
            observed[case] = summary
            assert exit_code == runner.EXIT_PASS, f"{case} exit={exit_code} summary={summary!r}"

            expected_pairs = _CONTRACTS[case]
            rows = summary["observation"]["instruments"]
            assert [
                (row["instrument_id"], row["exchange_id"]) for row in rows
            ] == list(expected_pairs)
            assert all(row["metadata"]["asset_type"] == "future" for row in rows)
            assert all(row["latest_event"] is not None for row in rows)
            assert all(row["source"]["source"] == "ctp.native.md" for row in rows)
            assert all(row["source"]["clock_mapping_qualified"] is False for row in rows)
            assert all(row["source"]["execution_eligible"] is False for row in rows)
            assert summary["observation"]["write_capability"] == "UNSUPPORTED"
            assert summary["observation"]["account_snapshot"]["balances_complete"] is True
            assert summary["observation"]["account_snapshot"]["positions_complete"] is True
            assert summary["observation"]["account_snapshot"]["open_orders_complete"] is True
            assert summary["observation"]["cleanup"]["status"] == "PASS"
            assert summary["trade_execution"] == "not_run"

        assert observed["013_1"]["example_id"] == "013_1_midfreq_cross_arbitrage"
        assert observed["013_2"]["example_id"] == "013_2_highfreq_calendar_arbitrage"
        assert observed["013_3"]["example_id"] == "013_3_sa_midfreq_simnow"
        assert observed["013_3"]["case_contract"] == {
            "instrument": "SA701",
            "exchange": "CZCE",
        }
    finally:
        hosts["account_stop"].set()
        hosts["market_stop"].set()
        hosts["account_thread"].join(10.0)
        hosts["market_thread"].join(10.0)

    assert not hosts["account_thread"].is_alive()
    assert not hosts["market_thread"].is_alive()
    assert hosts["account_holder"]["deployment"].state == "closed"
    assert hosts["market_holder"]["deployment"].state == "closed"
    assert len(hosts["account_provider_holder"]) == 1
    account_provider = hosts["account_provider_holder"][0]
    assert account_provider.close_count == 1
    queried = {(instrument, exchange) for instrument, exchange, _product in account_provider.trader_api.query_rows}
    expected_queries = {
        (instrument, exchange)
        for pairs in _CONTRACTS.values()
        for instrument, exchange in pairs
    }
    assert queried == expected_queries
    assert len(account_provider.trader_api.query_rows) == len(expected_queries)
    assert hosts["market_provider_holder"]
    assert all(
        provider.diagnostics["active_handles"] == 0
        for provider in hosts["market_provider_holder"]
    )
    assert hosts["md_streams"]

