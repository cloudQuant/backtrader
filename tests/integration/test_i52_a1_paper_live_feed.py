"""Source/fake paper and live market-data vertical slice for Iteration 52.

This proves only that one ordinary Strategy source can consume deterministic
live bars through real Backtrader Store/Feed/Broker/Cerebro objects under two
parsed configurations. The provider boundary is fake and the Broker is
configured market-data-only. This does not exercise write rejection and is not
order/write, account, provider, or full A1 acceptance.

Required local acceptance invocation (set both environment variables):

    $env:BT_I52_REQUIRE_FEED = '1'
    $env:BT_API_RUN_CONTRACT_SITE_ROOT = '<installed contract site-packages root>'
    python -m pytest -q -p no:asyncio tests/integration/test_i52_a1_paper_live_feed.py::test_i52_a1_paper_live_share_one_strategy_over_real_btapi_feed_stack
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_SITE_ROOT_ENV = "BT_API_RUN_CONTRACT_SITE_ROOT"
_WORKER_MARKER = "I52_A1_FEED_RESULT="


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _verify_contract_origin():
    """Import the configured installed parser and verify its package origin."""

    site_root = Path(os.environ[_CONTRACT_SITE_ROOT_ENV]).resolve()
    package = importlib.import_module("bt_api_run_contract")
    parser = importlib.import_module("bt_api_run_contract.parser")
    errors = importlib.import_module("bt_api_run_contract.errors")

    assert _is_within(Path(package.__file__), site_root)
    assert _is_within(Path(parser.__file__), site_root)
    assert _is_within(Path(errors.__file__), site_root)
    assert callable(getattr(package, "parse_config", None))
    return package, parser, errors.RunConfigError


def _config(mode: str, provider_ref: str, endpoint_ref: str, account_ref: str, credential_ref: str):
    return "\n".join(
        (
            "schema_version: 1",
            "mode: {}".format(mode),
            "environment: {}".format(mode),
            "references:",
            "  strategy: strategy/i52_quote_observer",
            "  provider: {}".format(provider_ref),
            "  endpoint: {}".format(endpoint_ref),
            "  account: {}".format(account_ref),
            "  credential: {}".format(credential_ref),
            "  scope: scope/market_data_only",
            "plugins: {}",
            "",
        )
    )


class _FiniteFeedClock:
    """Deterministic monotonic clock used by the live feed's local timing path."""

    def __init__(self):
        self._value = 0

    def monotonic_ns(self):
        self._value += 1_000_000
        return self._value


def _worker():
    sys.path.insert(0, str(_PROJECT_ROOT))

    import backtrader as bt
    from bt_api_run_contract import RunConfigError, parse_config
    from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar
    from backtrader.stores.btapistore import BtApiStore

    contract_package, contract_parser, verified_error_type = _verify_contract_origin()
    assert verified_error_type is RunConfigError
    assert contract_parser.parse_config is parse_config
    assert _is_within(Path(bt.__file__), _PROJECT_ROOT)

    paper_rows = [
        make_bar(0, 100.0, 101.0, 99.0, 100.5),
        make_bar(1, 100.5, 102.0, 100.0, 101.5),
    ]
    live_rows = [
        make_bar(0, 200.0, 201.0, 199.0, 200.5),
        make_bar(1, 200.5, 202.0, 200.0, 201.5),
    ]

    class _FiniteFakeBtApiClient(FakeBtApiClient):
        """Fixture client with explicit finite-source and event-time contracts."""

        provider_label = "abstract"

        def __init__(self, rows):
            self.source_rows = tuple(dict(row) for row in rows)
            self.source_clock = tuple(row["datetime"] for row in rows)
            self.exhaustion_queries = []
            self.watermark_queries = []
            self.poll_bar_calls = []
            self.connect_calls = 0
            self.disconnect_calls = 0
            super().__init__(
                balance={"cash": 1000.0, "value": 1000.0},
                positions=[],
                live={DEFAULT_SYMBOL: rows},
            )

        def connect(self):
            self.connect_calls += 1
            return super().connect()

        def disconnect(self):
            self.disconnect_calls += 1
            return super().disconnect()

        def poll_bar(self, dataname):
            self.poll_bar_calls.append(dataname)
            return super().poll_bar(dataname)

        def is_source_exhausted(self, dataname):
            self.exhaustion_queries.append(dataname)
            if dataname != DEFAULT_SYMBOL:
                return False
            queue = self.live.get(dataname)
            return queue is not None and not queue

        def get_source_event_time_watermark(self, dataname):
            self.watermark_queries.append(dataname)
            if dataname != DEFAULT_SYMBOL or not self.source_clock:
                return None
            return self.source_clock[-1]

    class _PaperQuoteProviderFake(_FiniteFakeBtApiClient):
        provider_label = "paper_fake"

    class _LiveQuoteProviderFake(_FiniteFakeBtApiClient):
        provider_label = "live_fake"

    providers = {
        "provider/paper_quotes": (_PaperQuoteProviderFake, paper_rows, "paper"),
        "provider/live_quotes": (_LiveQuoteProviderFake, live_rows, "live"),
    }
    factory_calls = []

    def _parse_then_make_store(source):
        config = parse_config(source)
        factory_calls.append(config.references.provider)
        provider_type, rows, required_environment = providers[config.references.provider]
        assert config.environment.value == required_environment
        fake = provider_type(rows)
        store = BtApiStore(
            provider="btapi",
            api=fake,
            cash=1000.0,
            value=1000.0,
        )
        return config, store, fake

    invalid_factory_calls = len(factory_calls)
    invalid = _config(
        "paper",
        "provider/paper_quotes",
        "endpoint/paper_synthetic",
        "account/paper_fixture",
        "credential/paper_fixture",
    ).replace("environment: paper", "environment: live")
    try:
        _parse_then_make_store(invalid)
    except RunConfigError as exc:
        mismatch_code = exc.code
    else:
        raise AssertionError("mismatched mode/environment was accepted")
    assert mismatch_code == "environment_mismatch"
    assert len(factory_calls) == invalid_factory_calls

    configs = (
        _config(
            "paper",
            "provider/paper_quotes",
            "endpoint/paper_synthetic",
            "account/paper_fixture",
            "credential/paper_fixture",
        ),
        _config(
            "live",
            "provider/live_quotes",
            "endpoint/live_synthetic",
            "account/live_fixture",
            "credential/live_fixture",
        ),
    )

    class QuoteObserver(bt.Strategy):
        """One ordinary read-only Strategy source that never sees the mode."""

        def __init__(self):
            self.observed_bars = []

        def next(self):
            data = self.datas[0]
            self.observed_bars.append(
                {
                    "datetime": data.datetime.datetime(0).isoformat(),
                    "open": float(data.open[0]),
                    "high": float(data.high[0]),
                    "low": float(data.low[0]),
                    "close": float(data.close[0]),
                    "volume": float(data.volume[0]),
                }
            )

    scenarios = []
    for source in configs:
        config, store, fake = _parse_then_make_store(source)
        assert type(store) is BtApiStore
        broker = store.getbroker(market_data_only=True)
        assert type(broker) is bt.brokers.BtApiBroker
        feed = store.getdata(
            dataname=DEFAULT_SYMBOL,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            backfill_start=False,
            qcheck=0.001,
            clock=_FiniteFeedClock(),
        )
        assert type(feed) is bt.feeds.BtApiFeed
        cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
        cerebro.setbroker(broker)
        assert type(cerebro) is bt.Cerebro
        assert cerebro.broker is broker
        cerebro.adddata(feed, name=DEFAULT_SYMBOL)
        cerebro.addstrategy(QuoteObserver)

        try:
            results = cerebro.run()
        finally:
            if store.is_connected:
                store.stop(timeout=0.25)

        assert len(results) == 1
        strategy = results[0]
        assert type(strategy) is QuoteObserver
        # Configuration wiring only: this scenario makes no write attempt and
        # does not test rejection behavior for submit/cancel calls.
        assert broker.get_param("market_data_only") is True
        assert fake.submitted_orders == []
        assert fake.cancelled_orders == []
        assert fake.connect_calls == 1
        assert fake.disconnect_calls >= 1
        assert len(fake.exhaustion_queries) > 0
        assert fake.watermark_queries
        assert len(strategy.observed_bars) == len(fake.source_clock)
        assert tuple(item["datetime"] for item in strategy.observed_bars) == tuple(
            value.isoformat() for value in fake.source_clock
        )
        for observed, source_bar in zip(strategy.observed_bars, fake.source_rows):
            for field in ("open", "high", "low", "close", "volume"):
                assert observed[field] == float(source_bar[field])

        scenarios.append(
            {
                "environment": config.environment.value,
                "provider_ref": config.references.provider,
                "provider_fake": fake.provider_label,
                "strategy_source": "{}.{}".format(
                    type(strategy).__module__, type(strategy).__qualname__
                ),
                "market_data_only": broker.get_param("market_data_only"),
                "bars": strategy.observed_bars,
                "eof_queries": len(fake.exhaustion_queries),
                "watermark_queries": len(fake.watermark_queries),
                "poll_bar_calls": len(fake.poll_bar_calls),
                "write_calls": len(fake.submitted_orders) + len(fake.cancelled_orders),
            }
        )

    assert factory_calls == ["provider/paper_quotes", "provider/live_quotes"]
    assert scenarios[0]["strategy_source"] == scenarios[1]["strategy_source"]
    assert [scenario["provider_fake"] for scenario in scenarios] == [
        "paper_fake",
        "live_fake",
    ]
    assert [scenario["bars"][-1]["close"] for scenario in scenarios] == [
        101.5,
        201.5,
    ]

    print(
        _WORKER_MARKER
        + json.dumps(
            {
                "contract_origin": str(Path(contract_package.__file__).resolve()),
                "invalid_environment_error": mismatch_code,
                "factory_calls": factory_calls,
                "strategy_source_shared": scenarios[0]["strategy_source"],
                "scenarios": scenarios,
                "evidence_level": "SOURCE_FAKE_PAPER_LIVE_FEED_PATH_ONLY",
            },
            sort_keys=True,
        )
    )


def test_i52_a1_paper_live_share_one_strategy_over_real_btapi_feed_stack():
    """Bounded fake-provider runs cover the same Strategy source in both modes."""

    contract_site_value = os.environ.get(_CONTRACT_SITE_ROOT_ENV)
    if not contract_site_value:
        message = (
            "set BT_API_RUN_CONTRACT_SITE_ROOT to the installed "
            "bt_api_run_contract site-packages root"
        )
        if os.environ.get("BT_I52_REQUIRE_FEED") == "1":
            pytest.fail(
                "BT_I52_REQUIRE_FEED=1 but the contract install root is missing; {}".format(message)
            )
        pytest.skip(message)
    contract_site_root = Path(contract_site_value).resolve()
    assert (
        contract_site_root.is_dir()
    ), "{} must name the installed bt_api_run_contract site-packages root".format(
        _CONTRACT_SITE_ROOT_ENV
    )
    child_env = os.environ.copy()
    # Put the explicitly selected installation first. The child imports the
    # public package normally and rejects a stale site-packages origin.
    child_env["PYTHONPATH"] = str(contract_site_root)
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--i52-a1-worker"],
            cwd=str(_PROJECT_ROOT),
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "bounded fake live-feed worker exceeded 12 seconds and was terminated: {}".format(exc)
        )

    assert (
        completed.returncode == 0
    ), "bounded fake live-feed worker failed (exit={}):\n{}\n{}".format(
        completed.returncode,
        completed.stdout[-4000:],
        completed.stderr[-6000:],
    )
    result_lines = [
        line for line in completed.stdout.splitlines() if line.startswith(_WORKER_MARKER)
    ]
    assert len(result_lines) == 1, completed.stdout[-4000:]
    result = json.loads(result_lines[0][len(_WORKER_MARKER) :])
    assert _is_within(Path(result["contract_origin"]), contract_site_root)
    assert result["invalid_environment_error"] == "environment_mismatch"
    assert result["factory_calls"] == ["provider/paper_quotes", "provider/live_quotes"]
    assert result["evidence_level"] == "SOURCE_FAKE_PAPER_LIVE_FEED_PATH_ONLY"
    assert [scenario["environment"] for scenario in result["scenarios"]] == [
        "paper",
        "live",
    ]
    assert [scenario["provider_fake"] for scenario in result["scenarios"]] == [
        "paper_fake",
        "live_fake",
    ]
    assert all(scenario["market_data_only"] is True for scenario in result["scenarios"])
    assert all(scenario["write_calls"] == 0 for scenario in result["scenarios"])
    assert all(scenario["eof_queries"] > 0 for scenario in result["scenarios"])
    assert all(scenario["watermark_queries"] > 0 for scenario in result["scenarios"])
    assert all(len(scenario["bars"]) == 2 for scenario in result["scenarios"])
    assert result["scenarios"][0]["strategy_source"] == result["scenarios"][1]["strategy_source"]


if __name__ == "__main__" and sys.argv[1:] == ["--i52-a1-worker"]:
    _worker()
