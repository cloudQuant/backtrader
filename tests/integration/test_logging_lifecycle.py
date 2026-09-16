"""Integration test: iteration 29 lifecycle logging over a real backtest.

Runs a small real backtest (CSV fixture + SMA crossover strategy) with the
split-file layout enabled and asserts the full lifecycle INFO chain plus
order events land in ``log_dir/<script>/<date>/info.log`` — with no per-bar
degradation.
"""

import logging
import os
from datetime import date

import pytest

import backtrader as bt
import backtrader.brokers.bbroker as bbroker_module
from backtrader.utils import log_message

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datas")
CSV = os.path.join(DATA, "2006-day-001.txt")


@pytest.fixture(autouse=True)
def _clean_logging():
    """Reset lifecycle logging before and after each test."""
    log_message.reset_logging()
    yield
    log_message.reset_logging()


class _SmaCross(bt.Strategy):
    params = (("fast", 3), ("slow", 10))

    def __init__(self):
        sma_fast = bt.ind.SMA(period=self.p.fast)
        sma_slow = bt.ind.SMA(period=self.p.slow)
        self.crossover = bt.ind.CrossOver(sma_fast, sma_slow)

    def next(self):
        if not self.position and self.crossover > 0:
            self.buy(size=10)
        elif self.position and self.crossover < 0:
            self.close()


class _LifecycleGuardBroker(bt.brokers.BackBroker):
    """Reject diagnostic portfolio reads outside an active broker lifecycle."""

    def __init__(self, **kwargs):
        self.phase = "new"
        self.cash_phases = []
        self.value_phases = []
        super().__init__(**kwargs)

    def start(self):
        self.phase = "starting"
        result = super().start()
        self.phase = "active"
        return result

    def stop(self):
        self.phase = "stopped"
        return super().stop()

    def getcash(self):
        self.cash_phases.append(self.phase)
        if self.phase != "active":
            raise RuntimeError("getcash outside active broker lifecycle")
        return super().getcash()

    def getvalue(self, datas=None):
        self.value_phases.append(self.phase)
        if self.phase != "active":
            raise RuntimeError("getvalue outside active broker lifecycle")
        return super().getvalue(datas=datas)


class _CountingBroker(bt.brokers.BackBroker):
    """Record optional portfolio reads without changing BackBroker behavior."""

    def __init__(self, **kwargs):
        self.cash_reads = 0
        self.value_reads = 0
        super().__init__(**kwargs)

    def getcash(self):
        self.cash_reads += 1
        return super().getcash()

    def getvalue(self, datas=None):
        self.value_reads += 1
        return super().getvalue(datas=datas)


class _UnavailableCashBroker(bt.brokers.BackBroker):
    """Make an opt-in diagnostic accessor fail with an unsafe payload."""

    def getcash(self):
        raise RuntimeError("unclassified-sensitive-payload")


class _StopLenFeed(bt.feeds.GenericCSVData):
    """Release its length after stop, like a resource-owning live feed."""

    def __init__(self, *args, **kwargs):
        self._length_released = False
        super().__init__(*args, **kwargs)

    def stop(self):
        result = super().stop()
        self._length_released = True
        return result

    def __len__(self):
        if self._length_released:
            raise RuntimeError("length unavailable after feed stop")
        return super().__len__()


def _add_csv_strategy(cerebro, strategy=bt.Strategy, feed_cls=bt.feeds.GenericCSVData):
    """Add the CSV fixture feed and a strategy to a cerebro."""
    cerebro.adddata(
        feed_cls(
            dataname=CSV,
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        )
    )
    cerebro.addstrategy(strategy)


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize("backend", ["stdlib", "spdlog"])
def test_logging_lifecycle_over_real_backtest(tmp_path, runonce, backend):
    if backend == "spdlog" and log_message._detect_spdlog() is None:
        pytest.skip("spdlog smoke probe unavailable")
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="lifecycle_test",
        backend=backend,
        console=False,
    )

    cerebro = bt.Cerebro()
    data = bt.feeds.GenericCSVData(
        dataname=CSV,
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )
    cerebro.adddata(data)
    cerebro.addstrategy(_SmaCross)
    cerebro.broker.setcash(100000.0)
    results = cerebro.run(runonce=runonce)
    log_message.flush_all()

    assert len(results) == 1

    today = date.today().strftime("%Y_%m_%d")
    info_file = tmp_path / "logs" / "lifecycle_test" / today / "info.log"
    assert info_file.is_file()
    info = info_file.read_text(encoding="utf-8")

    for expected in (
        "run starting",
        "data loaded",
        "strategy nextstart",
        "order submitted",
        "order executed",
        "strategy stopping",
        "run finished",
    ):
        assert expected in info, f"lifecycle event {expected!r} missing from info.log"

    # Order events must be present but bounded: no per-bar degradation.
    # ~250 bars in the fixture; lifecycle INFO should stay O(10), not O(bars).
    lines = [ln for ln in info.splitlines() if ln.strip()]
    assert len(lines) >= 7
    assert len(lines) < 200, f"info.log has {len(lines)} lines - per-bar degradation?"

    # run finished must carry the final value and pnl fields
    finished = [ln for ln in lines if "run finished" in ln][0]
    assert "final value=" in finished
    assert "pnl=" in finished

    # error.log exists (config-time creation) and stays empty on a clean run
    err_file = tmp_path / "logs" / "lifecycle_test" / today / "error.log"
    assert err_file.is_file()
    assert not err_file.read_text(encoding="utf-8").strip()


def test_lifecycle_logging_respects_custom_broker_access_window(tmp_path, monkeypatch):
    """INFO summaries must not probe cash before start or value after stop."""
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="broker_lifecycle",
        backend="stdlib",
        console=False,
    )
    broker = _LifecycleGuardBroker(cash=100000.0)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    _add_csv_strategy(cerebro, _SmaCross)
    # Writer reporting has historically read broker state after ``stop()``.
    # This probe isolates the lifecycle diagnostic contract introduced here.
    monkeypatch.setattr(cerebro, "stop_writers", lambda runstrats: None)

    assert len(cerebro.run()) == 1
    assert broker.cash_phases and set(broker.cash_phases) == {"active"}
    assert broker.value_phases and set(broker.value_phases) == {"active"}


def test_host_root_info_without_backtrader_output_does_not_probe_broker(monkeypatch):
    """Host logging alone must not enable lifecycle accessor side effects."""
    host_root = logging.getLogger()
    prior_level = host_root.level
    backtrader_root = logging.getLogger(log_message.ROOT_LOGGER_NAME)
    prior_handlers = list(backtrader_root.handlers)
    prior_backtrader_level = backtrader_root.level
    prior_propagate = backtrader_root.propagate
    retained_handler = logging.StreamHandler()
    # Model a caller-owned handler that ``reset_logging()`` would preserve.
    backtrader_root.addHandler(retained_handler)

    # Isolate this default-silence contract from the retained handler while
    # preserving production support for direct caller-owned output handlers.
    backtrader_root.handlers[:] = [logging.NullHandler()]
    backtrader_root.setLevel(logging.NOTSET)
    backtrader_root.propagate = False
    host_root.setLevel(logging.INFO)
    try:
        broker = _CountingBroker(cash=100000.0)
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        _add_csv_strategy(cerebro)
        monkeypatch.setattr(cerebro, "stop_writers", lambda runstrats: None)

        assert len(cerebro.run()) == 1
        assert broker.cash_reads == 0
        assert broker.value_reads == 0
    finally:
        backtrader_root.handlers[:] = prior_handlers
        retained_handler.close()
        backtrader_root.setLevel(prior_backtrader_level)
        backtrader_root.propagate = prior_propagate
        host_root.setLevel(prior_level)


def test_lifecycle_accessor_failure_does_not_log_third_party_payload(tmp_path, monkeypatch):
    """Optional broker diagnostics preserve a safe fixed warning message."""
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="broker_lifecycle_failure",
        backend="stdlib",
        console=False,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(_UnavailableCashBroker(cash=100000.0))
    _add_csv_strategy(cerebro)
    monkeypatch.setattr(cerebro, "stop_writers", lambda runstrats: None)

    assert len(cerebro.run()) == 1
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    warning = (tmp_path / "logs" / "broker_lifecycle_failure" / today / "warning.log").read_text(
        encoding="utf-8"
    )
    assert "broker getcash unavailable for lifecycle logging" in warning
    assert "unclassified-sensitive-payload" not in warning


def test_lifecycle_final_summary_reads_feed_length_before_stop(tmp_path, monkeypatch):
    """A feed may release its buffer in stop without breaking INFO logging."""
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="feed_lifecycle",
        backend="stdlib",
        console=False,
    )
    cerebro = bt.Cerebro(stdstats=False)
    _add_csv_strategy(cerebro, feed_cls=_StopLenFeed)
    monkeypatch.setattr(cerebro, "stop_writers", lambda runstrats: None)

    assert len(cerebro.run()) == 1
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    info = (tmp_path / "logs" / "feed_lifecycle" / today / "info.log").read_text(encoding="utf-8")
    assert "run finished" in info


def test_lifecycle_logging_does_not_require_sized_strategy_iterable(tmp_path, monkeypatch):
    """An INFO summary must preserve the legacy generator runstrategies input."""
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="generator_lifecycle",
        backend="stdlib",
        console=False,
    )
    broker = _LifecycleGuardBroker(cash=100000.0)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    _add_csv_strategy(cerebro)
    cerebro._resolve_run_flags()
    monkeypatch.setattr(cerebro, "stop_writers", lambda runstrats: None)
    strategies = cerebro.runstrategies(iter(((bt.Strategy, (), {}),)))

    assert len(strategies) == 1
    assert broker.phase == "stopped"
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    info = (tmp_path / "logs" / "generator_lifecycle" / today / "info.log").read_text(
        encoding="utf-8"
    )
    assert "strategies=unavailable" in info


def test_channel_lifecycle_logging_starts_broker_before_cash_summary(tmp_path):
    """Channel INFO logging uses broker cash only after broker.start()."""
    bt.configure_logging(
        level="INFO",
        log_dir=str(tmp_path / "logs"),
        script_name="channel_lifecycle",
        backend="stdlib",
        console=False,
    )
    broker = _LifecycleGuardBroker(cash=100000.0)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.addstrategy(bt.Strategy)

    strategies = cerebro.run(channel=True)
    assert strategies
    assert broker.cash_phases and set(broker.cash_phases) == {"active"}
    assert cerebro.close_channel() is True
    assert broker.phase == "stopped"


def test_empty_backbroker_notification_poll_does_not_write_debug_records(monkeypatch):
    """An empty order queue is normal per-bar control flow, not a diagnostic."""
    broker = bbroker_module.BackBroker()
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.Logger("test.backtrader.bbroker", logging.DEBUG)
    logger.addHandler(_Capture())
    monkeypatch.setattr(bbroker_module, "logger", logger)

    for _ in range(3):
        assert broker.get_notification() is None
    assert records == []
