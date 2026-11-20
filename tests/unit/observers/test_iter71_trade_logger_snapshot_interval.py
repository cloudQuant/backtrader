"""TradeLogger position snapshot callback cadence tests."""

from __future__ import annotations

import copy
import datetime as dt

import backtrader as bt
import pytest

from backtrader.observers.trade_logger import TradeLogger
import backtrader.observers.trade_logger as trade_logger_module


class _SyntheticFeed(bt.feed.DataBase):
    """Finite in-memory bars for a real Cerebro observer lifecycle."""

    params = (("bar_count", 7),)

    def __init__(self):
        super().__init__()
        self._bar_index = 0

    def _load(self):
        if self._bar_index >= self.p.bar_count:
            return False

        day = dt.datetime(2026, 1, 1) + dt.timedelta(days=self._bar_index)
        close = 100.0 + self._bar_index
        self.lines.datetime[0] = bt.date2num(day)
        self.lines.open[0] = close
        self.lines.high[0] = close + 1.0
        self.lines.low[0] = close - 1.0
        self.lines.close[0] = close
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._bar_index += 1
        return True


class _CountingStore:
    """Local metadata fake; this test never constructs a provider client."""

    def __init__(self):
        self.metadata_reads = []

    def get_contract_metadata(self, dataname):
        self.metadata_reads.append(dataname)
        return {"multiplier": 2.0, "margin_rate": 0.1}


class _NoopStrategy(bt.Strategy):
    def next(self):
        pass


class _BuyOnceStrategy(bt.Strategy):
    def next(self):
        if len(self) == 1:
            self.buy(size=1)


class _HotUpdateStrategy(bt.Strategy):
    def start(self):
        observers = [item for item in self.stats.items if type(item) is TradeLogger]
        assert len(observers) == 1
        self.trade_logger = observers[0]

    def next(self):
        bar = len(self)
        if bar == 3:
            self.trade_logger.p.snapshot_interval = 2
        elif bar == 4:
            self.trade_logger.p.log_position_snapshot = False
        elif bar == 5:
            self.trade_logger.p.log_position_snapshot = True
            self.trade_logger.p.snapshot_interval = 1


def _disable_other_sinks():
    return {
        "log_orders": False,
        "log_trades": False,
        "log_positions": False,
        "log_indicators": False,
        "log_signals": False,
        "log_ticks": False,
        "log_bars": False,
        "log_system": False,
        "log_monitoring": False,
        "log_errors": False,
        "log_value": False,
        "startup_snapshot_file": None,
        "mysql_enabled": False,
    }


def _run_cerebro(tmp_path, monkeypatch, *, strategy, bar_count=7, **observer_params):
    yaml_module = trade_logger_module.yaml
    if yaml_module is None:
        pytest.skip("PyYAML is unavailable")

    writes = []
    original_dump = yaml_module.dump

    def capture_dump(value, *args, **kwargs):
        if (
            isinstance(value, dict)
            and {"datetime", "strategy", "positions"}.issubset(value)
        ):
            writes.append(copy.deepcopy(value))
        return original_dump(value, *args, **kwargs)

    monkeypatch.setattr(yaml_module, "dump", capture_dump)

    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.addstrategy(strategy)
    cerebro.adddata(_SyntheticFeed(bar_count=bar_count), name="SYNTH")
    store = _CountingStore()
    cerebro.broker.store = store
    params = {
        **_disable_other_sinks(),
        "log_dir": str(tmp_path),
        "log_position_snapshot": True,
        **observer_params,
    }
    cerebro.addobserver(TradeLogger, **params)
    (result,) = cerebro.run(runonce=False, preload=False)
    return result, writes, store


def test_default_snapshot_interval_keeps_every_bar_and_stop_write(
    tmp_path, monkeypatch
):
    _strategy, writes, store = _run_cerebro(
        tmp_path, monkeypatch, strategy=_BuyOnceStrategy
    )

    # Seven actual Cerebro bars plus the existing final stop refresh.
    assert len(writes) == 8
    assert len(store.metadata_reads) == 8
    assert [item["datetime"][:10] for item in writes] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-07",
    ]
    assert writes[1]["positions"]["SYNTH"]["current_price"] == pytest.approx(101.0)
    assert writes[-1]["positions"]["SYNTH"]["current_price"] == pytest.approx(106.0)
    assert writes[-1]["positions"]["SYNTH"]["value"] == pytest.approx(212.0)


def test_larger_interval_throttles_snapshot_and_snapshot_reads(
    tmp_path, monkeypatch
):
    _strategy, writes, store = _run_cerebro(
        tmp_path,
        monkeypatch,
        strategy=_BuyOnceStrategy,
        snapshot_interval=3,
    )

    # First callback writes immediately, then every third callback; stop is
    # still an unconditional final refresh even when the last bar just wrote.
    assert len(writes) == 4
    assert len(store.metadata_reads) == 4
    assert [item["datetime"][:10] for item in writes] == [
        "2026-01-01",
        "2026-01-04",
        "2026-01-07",
        "2026-01-07",
    ]
    assert writes[1]["positions"]["SYNTH"]["current_price"] == pytest.approx(103.0)
    assert writes[2]["positions"]["SYNTH"]["value"] == pytest.approx(212.0)
    assert (tmp_path / "current_position.yaml").is_file()


def test_interval_and_logging_settings_are_read_from_live_params(
    tmp_path, monkeypatch
):
    _strategy, writes, store = _run_cerebro(
        tmp_path,
        monkeypatch,
        strategy=_HotUpdateStrategy,
        snapshot_interval=3,
    )

    # Callback 1 writes; the interval change at callback 3 takes effect there,
    # callback 4 is disabled, and re-enabling at callback 5 writes immediately.
    # Callbacks 6-7 and stop preserve the every-callback/final-write behavior.
    assert len(writes) == 6
    assert len(store.metadata_reads) == 6
    assert [item["datetime"][:10] for item in writes] == [
        "2026-01-01",
        "2026-01-03",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-07",
    ]


def test_disabled_position_snapshot_has_no_per_bar_or_stop_reads(
    tmp_path, monkeypatch
):
    _strategy, writes, store = _run_cerebro(
        tmp_path,
        monkeypatch,
        strategy=_NoopStrategy,
        log_position_snapshot=False,
    )

    assert writes == []
    assert store.metadata_reads == []
    assert not (tmp_path / "current_position.yaml").exists()


@pytest.mark.parametrize("interval", [0, -1, True, 1.5, "2"])
def test_snapshot_interval_requires_positive_integer(tmp_path, interval):
    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.addstrategy(_NoopStrategy)
    cerebro.adddata(_SyntheticFeed(bar_count=1), name="SYNTH")
    cerebro.addobserver(
        TradeLogger,
        **{
            **_disable_other_sinks(),
            "log_dir": str(tmp_path),
            "snapshot_interval": interval,
        },
    )

    with pytest.raises(ValueError, match="snapshot_interval must be a positive integer"):
        cerebro.run(runonce=False, preload=False)
