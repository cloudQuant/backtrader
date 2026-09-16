"""Iteration 28 loop/lifecycle feature tests.

Freezes observable execution traces for the four traditional engine loops,
order phases, channel modes and runstop so the cerebro split (iteration 28)
can be validated against its own pre-split baseline.

Baseline update (run once on the *pre-split* code, then commit both):

    BT_ITER28_UPDATE_BASELINE=1 python -m pytest tests/unit/core/test_cerebro_loop_features.py

Comparison (default): each trace must match the frozen baseline exactly.
The traces are deterministic (fixed data, fixed code path), therefore exact
float values (rounded to 1e-9) are compared - drift indicates a real
behavioral change.
"""

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path

import backtrader as bt

BASELINE_PATH = Path(__file__).with_name("iter28_loop_baseline.json")
DATAPATH = str(Path(__file__).resolve().parent.parent.parent / "datas" / "2006-day-001.txt")

UPDATE = os.environ.get("BT_ITER28_UPDATE_BASELINE", "") == "1"
_TRACES = {}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class TraceStrategy(bt.Strategy):
    """Records phases, bars, orders, trades and timers deterministically."""

    params = (("period", 5), ("stop_at", None))

    def __init__(self):
        self.sma = bt.ind.SMA(self.data.close, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, self.sma)
        self.trace = []

    def prenext(self):
        self.trace.append(("prenext", len(self.data)))

    def nextstart(self):
        self.trace.append(("nextstart", len(self.data)))

    def next(self):
        dt = self.data.datetime.date(0).isoformat()
        self.trace.append(("next", dt, len(self.data), self.data.close[0], self.position.size))
        if not self.position and self.crossover > 0:
            self.buy(size=1)
            self.trace.append(("submit_buy", dt))
        elif self.position and self.crossover < 0:
            self.close()
            self.trace.append(("submit_close", dt))
        if self.p.stop_at is not None and len(self.data) >= self.p.stop_at:
            self.trace.append(("runstop", dt))
            self.cerebro.runstop()

    def notify_order(self, order):
        self.trace.append(
            (
                "order",
                order.getstatusname(),
                order.size,
                order.executed.size if order.status == order.Completed else 0.0,
                order.executed.price if order.status == order.Completed else 0.0,
            )
        )

    def notify_trade(self, trade):
        self.trace.append(
            ("trade", "open" if trade.isopen else "close", trade.price, round(trade.pnlcomm, 10))
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        self.trace.append(("timer", timer.tid, when.isoformat()))


class CheatOpenTraceStrategy(TraceStrategy):
    def next_open(self):
        dt = self.data.datetime.date(0).isoformat()
        self.trace.append(("next_open", dt, self.data.open[0]))
        if not self.position and len(self.data) == self.p.period + 2:
            self.buy(size=2)


class BareTraceStrategy(bt.Strategy):
    """No indicators/observers/analyzers so the direct-load fast path engages.

    The rolling mean is computed in pure Python on purpose: registering any
    indicator would populate ``_lineiterators[IndType]`` and disable the fast
    path (see ``Strategy._fast_simple_next`` conditions).
    """

    params = (("period", 5),)

    def __init__(self):
        import collections

        self.trace = []
        self.closes = collections.deque(maxlen=self.p.period)
        self.prev_diff = None

    def next(self):
        dt = self.data.datetime.date(0).isoformat()
        close = self.data.close[0]
        self.closes.append(close)
        avg = sum(self.closes) / len(self.closes)
        diff = close - avg
        self.trace.append(("next", dt, len(self.data), close, self.position.size))
        if self.prev_diff is not None:
            if self.prev_diff <= 0 < diff and not self.position:
                self.buy(size=1)
                self.trace.append(("submit_buy", dt))
            elif self.prev_diff >= 0 > diff and self.position:
                self.close()
                self.trace.append(("submit_close", dt))
        self.prev_diff = diff

    def notify_order(self, order):
        self.trace.append(
            (
                "order",
                order.getstatusname(),
                order.size,
                order.executed.size if order.status == order.Completed else 0.0,
                order.executed.price if order.status == order.Completed else 0.0,
            )
        )

    def notify_trade(self, trade):
        self.trace.append(
            ("trade", "open" if trade.isopen else "close", trade.price, round(trade.pnlcomm, 10))
        )


class ChannelTraceStrategy(bt.Strategy):
    """Records channel notifications for tick/orderbook/bar/funding events."""

    def __init__(self):
        self.trace = []

    def notify_tick(self, tick):
        self.trace.append(("tick", tick.symbol, tick.price, tick.volume))

    def notify_orderbook(self, ob):
        self.trace.append(("orderbook", ob.symbol, ob.bids[0][0], ob.asks[0][0]))

    def notify_bar(self, bar):
        self.trace.append(("bar", bar.symbol, bar.close))

    def notify_funding(self, funding):
        self.trace.append(("funding", funding.symbol))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cerebro(**kwargs):
    """Return a Cerebro with the shared daily CSV data feed attached.

    Args:
        **kwargs: Keyword arguments forwarded to ``bt.Cerebro``.

    Returns:
        bt.Cerebro: The configured engine with one data feed.
    """
    cerebro = bt.Cerebro(**kwargs)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False))
    return cerebro


def _run_and_record(name, cerebro, stratcls=TraceStrategy, extra=None, **stratkwargs):
    """Run ``stratcls`` on ``cerebro`` and compare or record its trace.

    Args:
        name: Baseline key for the trace.
        cerebro: Engine to run.
        stratcls: Strategy class added before running.
        extra: Optional payload entries merged into the recorded result.
        **stratkwargs: Keyword arguments forwarded to ``addstrategy``.
    """
    cerebro.addstrategy(stratcls, **stratkwargs)
    results = cerebro.run()
    strat = results[0]
    broker = cerebro.getbroker()
    trace = list(strat.trace)
    trace.append(("final_cash", broker.getcash()))
    trace.append(("final_value", broker.getvalue()))
    trace.append(("final_position", strat.position.size if strat.position else 0))
    payload = {"trace": _normalize(trace)}
    if extra is not None:
        payload.update(extra)
    _compare_or_record(name, payload)


def _normalize(trace):
    """Return ``trace`` with float entries rounded to nine decimals."""
    return [[round(v, 9) if isinstance(v, float) else v for v in item] for item in trace]


def _compare_or_record(name, payload):
    """Store ``payload`` when updating the baseline, else assert it matches."""
    if UPDATE:
        _TRACES[name] = payload
        return
    baseline = json.loads(BASELINE_PATH.read_text())
    expected = baseline.get(name)
    if expected is None:
        raise AssertionError(f"{name}: missing from baseline - regenerate baseline first")
    if expected != payload:
        raise AssertionError(
            f"{name}: trace differs\nfirst divergence: {_first_diff(expected, payload)}"
        )


def _first_diff(expected, actual):
    """Return a human-readable description of the first trace difference."""
    et, at = expected.get("trace"), actual.get("trace")
    if len(et) != len(at):
        return f"length {len(et)} != {len(at)}; expected head/tail {et[:2]}{et[-2:]} vs {at[:2]}{at[-2:]}"
    for i, (e, a) in enumerate(zip(et, at)):
        if e != a:
            return f"index {i}: expected={e} actual={a}"
    return f"extra keys differ: expected={expected} actual={actual}"


def _fastpath_hit(strat):
    """The direct-load fast path installs an instance-level ``_next``."""
    return "_next" in strat.__dict__


def teardown_module(module):
    """Write collected traces back to the baseline file when updating."""
    if UPDATE:
        existing = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {}
        existing.update(_TRACES)
        BASELINE_PATH.write_text(json.dumps(existing, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# LOOP matrix: oldsync x runonce/preload (AC28-07 LOOP-1..4)
# ---------------------------------------------------------------------------


def test_loop1_runonce_modern():
    cerebro = _make_cerebro(oldsync=False, runonce=True, preload=True)
    _run_and_record("loop1_runonce_modern", cerebro)


def test_loop2a_runnext_fastpath():
    cerebro = _make_cerebro(oldsync=False, runonce=False, stdstats=False)
    cerebro.addstrategy(BareTraceStrategy)
    results = cerebro.run()
    strat = results[0]
    broker = cerebro.getbroker()
    trace = list(strat.trace)
    trace.append(("final_cash", broker.getcash()))
    trace.append(("final_value", broker.getvalue()))
    _run_and_record_probe("loop2a_runnext_fastpath", trace, {"fastpath": _fastpath_hit(strat)})


def _run_and_record_probe(name, trace, extra):
    """Normalize ``trace``, merge ``extra`` and compare it with the baseline."""
    payload = {"trace": _normalize(trace)}
    payload.update(extra)
    _compare_or_record(name, payload)


def test_loop2b_runnext_multi_data():
    cerebro = bt.Cerebro(oldsync=False, runonce=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False), name="d1")
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False), name="d2")
    _run_and_record("loop2b_runnext_multi_data", cerebro)


def test_loop3_runonce_old():
    cerebro = _make_cerebro(oldsync=True, runonce=True, preload=True)
    _run_and_record("loop3_runonce_old", cerebro)


def test_loop4_runnext_old():
    cerebro = _make_cerebro(oldsync=True, runonce=False)
    _run_and_record("loop4_runnext_old", cerebro)


# ---------------------------------------------------------------------------
# ORDER phases (AC28-07 ORDER)
# ---------------------------------------------------------------------------


def test_order_cheat_on_open():
    cerebro = _make_cerebro(cheat_on_open=True, runonce=False)
    _run_and_record("order_cheat_on_open", cerebro, CheatOpenTraceStrategy)


def test_order_timers_and_quicknotify():
    cerebro = _make_cerebro(runonce=False, quicknotify=True)
    cerebro.add_timer(when=datetime.time(11, 0), monthdays=[], monthcarry=True, strats=True)
    cerebro.add_timer(
        when=datetime.time(14, 30), monthdays=[], monthcarry=True, strats=True, cheat=True
    )
    _run_and_record("order_timers_and_quicknotify", cerebro)


def test_order_writer_csv():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "writer.csv"
        cerebro = bt.Cerebro(runonce=False, writer=True)
        # WriterFile includes ``data._name`` in its header and every data row.
        # ``DATAPATH`` is checkout-local, so use a fixed display name to keep
        # this frozen CSV artifact independent of the CI workspace path.
        data = bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False)
        cerebro.adddata(data, name="iter28_writer_data")
        # The Writer emits ``\n``.  Supplying a text stream with explicit LF
        # translation keeps the frozen byte-level artifact stable on Windows.
        with out.open("w", encoding="utf-8", newline="\n") as output:
            cerebro.addwriter(bt.WriterFile, csv=True, out=output, close_out=False)
            cerebro.addstrategy(TraceStrategy)
            cerebro.run()
        content = out.read_bytes()
        trace = [
            ("writer_bytes", len(content)),
            ("writer_sha256", hashlib.sha256(content).hexdigest()),
        ]
        _run_and_record_probe("order_writer_csv", trace, {})


def test_order_signal_strategy():
    cerebro = _make_cerebro(runonce=False)
    cerebro.add_signal(
        bt.SIGNAL_LONG,
        bt.indicators.CrossOver,
        bt.indicators.SMA(period=5),
        bt.indicators.SMA(period=10),
    )
    results = cerebro.run()
    strat = results[0]
    broker = cerebro.getbroker()
    trace = [
        ("signal_strat_cls", type(strat).__name__),
        ("final_cash", broker.getcash()),
        ("final_value", broker.getvalue()),
        ("final_position", strat.position.size if strat.position else 0),
    ]
    _run_and_record_probe("order_signal_strategy", trace, {})


# ---------------------------------------------------------------------------
# MULTI timeframe (AC28-07 MULTI)
# ---------------------------------------------------------------------------


def test_multi_timeframe_resample():
    cerebro = bt.Cerebro(oldsync=False, runonce=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False), name="day")
    cerebro.resampledata(
        bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False),
        name="week",
        timeframe=bt.TimeFrame.Weeks,
        compression=1,
    )
    _run_and_record("multi_timeframe_resample", cerebro)


# ---------------------------------------------------------------------------
# Channel modes (AC28-07 CH-1/CH-2)
# ---------------------------------------------------------------------------


def _channel_events(symbol="SYM"):
    """Return one tick, orderbook and bar event per timestamp for ``symbol``."""
    from backtrader.channel import Event
    from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent

    events = []
    for i, ts in enumerate((1.0, 2.0, 3.0)):
        events.append(
            Event(
                data=TickEvent(timestamp=ts, symbol=symbol, price=100.0 + i, volume=1.0),
                channel_type="tick",
                channel_name=symbol,
            )
        )
        events.append(
            Event(
                data=OrderBookSnapshot(
                    timestamp=ts,
                    symbol=symbol,
                    bids=[(100.0 + i, 2.0)],
                    asks=[(101.0 + i, 1.0)],
                ),
                channel_type="orderbook",
                channel_name=symbol,
            )
        )
        events.append(
            Event(
                data=BarEvent(
                    timestamp=ts,
                    symbol=symbol,
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5 + i,
                    volume=10.0,
                ),
                channel_type="bar",
                channel_name=symbol,
            )
        )
    return events


def test_ch1_channel_iterable():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ChannelTraceStrategy)
    strategies = cerebro.run(channel=_channel_events())
    trace = list(strategies[0].trace)
    _run_and_record_probe("ch1_channel_iterable", trace, {})


def test_ch2_channel_true_external():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ChannelTraceStrategy)
    strategies = cerebro.run(channel=True)
    assert cerebro._run_active
    for event in _channel_events():
        cerebro.dispatch_channel_event(event)
    trace = list(strategies[0].trace)
    closed = cerebro.close_channel()
    assert closed is True
    assert not cerebro._run_active
    trace.append(("closed", closed))
    _run_and_record_probe("ch2_channel_true_external", trace, {})


# ---------------------------------------------------------------------------
# STOP (AC28-07 STOP)
# ---------------------------------------------------------------------------


def test_stop_runstop_midway():
    cerebro = _make_cerebro(runonce=False)
    _run_and_record("stop_runstop_midway", cerebro, stop_at=30)
