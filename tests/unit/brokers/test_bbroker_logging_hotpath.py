"""Regression coverage for BackBroker lifecycle logging and hot-path guards."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import backtrader as bt
import backtrader.brokers.bbroker as bbroker_module
import backtrader.order as order_module

DATA_PATH = Path(__file__).parents[2] / "datas" / "2006-day-001.txt"


class _FailOnDebug:
    def debug(self, *args, **kwargs):
        raise AssertionError("expected order protocol probe attempted to log")


class _DisabledInfoLogger:
    def isEnabledFor(self, level):  # noqa: N802 - logging.Logger API spelling
        return False

    def info(self, *args, **kwargs):
        raise AssertionError("disabled INFO logger received an order event")

    def debug(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


class _SubmitAndClose(bt.Strategy):
    def __init__(self):
        self._opened = False
        self._closed = False

    def next(self):
        if not self._opened:
            self._opened = True
            self.buy(size=1)
        elif self.position and not self._closed:
            self._closed = True
            self.close()


class _BuyOnce(bt.Strategy):
    """Submit one ordinary opening order for lifecycle event assertions."""

    def __init__(self):
        self._submitted = False

    def next(self):
        if not self._submitted:
            self._submitted = True
            self.buy(size=1)


class _DualSideBuyOnce(bt.Strategy):
    """Submit one dual-side opening order for the dual execution path."""

    def __init__(self):
        self._submitted = False

    def next(self):
        if not self._submitted:
            self._submitted = True
            self.buy(size=1, position_side="long", offset="open")


class _OversizedBuy(bt.Strategy):
    """Submit an order that cannot pass the broker's cash projection."""

    def __init__(self):
        self._submitted = False

    def next(self):
        if not self._submitted:
            self._submitted = True
            self.buy(size=10_000)


class _DualSideOversizedBuy(bt.Strategy):
    """Exercise the dual-side margin path through a real Cerebro run."""

    def __init__(self):
        self._submitted = False

    def next(self):
        if not self._submitted:
            self._submitted = True
            self.buy(size=10_000, position_side="long", offset="open")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture_bbroker_logger(monkeypatch, level=logging.DEBUG):
    """Install an opt-in in-memory logger recognized by the lifecycle gate."""
    handler = _Capture()
    capture_logger = logging.Logger("test.backtrader.bbroker", level)
    capture_logger.propagate = False
    capture_logger.addHandler(handler)
    monkeypatch.setattr(bbroker_module, "logger", capture_logger)
    return handler


def _messages(handler, *, level=None):
    records = handler.records
    if level is not None:
        records = [record for record in records if record.levelno == level]
    return [record.getMessage() for record in records]


class _LifecycleOrder:
    """Minimal order protocol used to isolate BackBroker state transitions."""

    def __init__(
        self,
        *,
        ref=1,
        status=order_module.Order.Created,
        transmit=True,
        parent=None,
        isbuy=True,
    ):
        self.ref = ref
        self.status = status
        self.transmit = transmit
        self.parent = parent
        self.size = 2
        self.price = 101.5
        self.data = SimpleNamespace(_name="asset")
        self.executed = SimpleNamespace(remsize=2)
        self.info = {}
        self._isbuy = isbuy

    def isbuy(self):
        return self._isbuy

    def alive(self):
        return self.status in {
            order_module.Order.Created,
            order_module.Order.Submitted,
            order_module.Order.Accepted,
            order_module.Order.Partial,
        }

    def submit(self):
        self.status = order_module.Order.Submitted

    def accept(self):
        self.status = order_module.Order.Accepted

    def cancel(self):
        self.status = order_module.Order.Canceled

    def reject(self):
        self.status = order_module.Order.Rejected

    def margin(self):
        self.status = order_module.Order.Margin

    def clone(self):
        return self


def test_order_protocol_attribute_misses_do_not_log(monkeypatch):
    """Construction and copy protocol probes are expected AttributeErrors."""
    monkeypatch.setattr(order_module, "logger", _FailOnDebug(), raising=False)
    order = object.__new__(order_module.OrderBase)

    with pytest.raises(AttributeError):
        order.__setstate__

    order.transient_value = 1
    assert order.transient_value == 1


def test_disabled_order_info_does_not_evaluate_payload(monkeypatch):
    """The submit fast path must not inspect fields solely used for INFO logs."""
    broker = bbroker_module.BackBroker()
    monkeypatch.setattr(bbroker_module, "logger", _DisabledInfoLogger())
    monkeypatch.setattr(broker, "_freeze_position_mode", lambda *args: None)
    monkeypatch.setattr(broker, "_take_children", lambda order: None)

    class _UnreadableOrder:
        @property
        def ref(self):
            raise AssertionError("INFO payload read order.ref while logging was disabled")

        @property
        def size(self):
            raise AssertionError("INFO payload read order.size while logging was disabled")

        @property
        def price(self):
            raise AssertionError("INFO payload read order.price while logging was disabled")

        @property
        def data(self):
            raise AssertionError("INFO payload read order.data while logging was disabled")

    order = _UnreadableOrder()
    assert broker.submit(order) is order


def test_disabled_order_info_logger_allows_real_submit_and_fill(monkeypatch):
    """A real backtest keeps its order semantics when no INFO sink is enabled."""
    monkeypatch.setattr(bbroker_module, "logger", _DisabledInfoLogger())
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(DATA_PATH), plot=False))
    cerebro.addstrategy(_SubmitAndClose)

    strategy = cerebro.run()[0]

    assert strategy._opened
    assert strategy._closed


def test_submission_logging_waits_for_real_submitted_transition(monkeypatch):
    """Deferred or rejected bracket children must not claim to be submitted."""
    handler = _capture_bbroker_logger(monkeypatch)
    broker = bbroker_module.BackBroker()
    monkeypatch.setattr(broker, "notify", lambda order: None)

    deferred = _LifecycleOrder(transmit=False)
    assert broker.submit(deferred) is deferred
    assert deferred.status == order_module.Order.Created
    assert not _messages(handler, level=logging.INFO)

    assert broker.transmit(deferred) is deferred
    assert deferred.status == order_module.Order.Submitted
    submitted = _messages(handler, level=logging.INFO)
    assert submitted == [
        "order submitted: ref=1 side=buy size=2 price=101.5 data=asset",
    ]

    missing_parent = SimpleNamespace(ref=999)
    rejected = _LifecycleOrder(ref=2, parent=missing_parent)
    assert broker.submit(rejected) is rejected
    assert rejected.status == order_module.Order.Rejected
    assert _messages(handler, level=logging.INFO) == submitted
    assert _messages(handler, level=logging.WARNING) == [
        "order rejected: ref=2 reason=parent order missing",
    ]


@pytest.mark.parametrize(
    ("queue_name", "status"),
    [
        ("pending", order_module.Order.Accepted),
        ("submitted", order_module.Order.Submitted),
    ],
)
def test_cancellation_logs_terminal_event_without_queue_probe_debug(
    monkeypatch, queue_name, status
):
    """Only a real cancellation is observable; the alternate queue miss is normal."""
    handler = _capture_bbroker_logger(monkeypatch)
    broker = bbroker_module.BackBroker()
    monkeypatch.setattr(broker, "notify", lambda order: None)
    monkeypatch.setattr(broker, "_ococheck", lambda order: None)
    monkeypatch.setattr(broker, "_bracketize", lambda *args, **kwargs: None)
    order = _LifecycleOrder(status=status)
    getattr(broker, queue_name).append(order)

    assert broker.cancel(order) is True
    assert order.status == order_module.Order.Canceled
    assert _messages(handler, level=logging.INFO) == [
        "order canceled: ref=1 side=buy size=2 price=101.5 data=asset",
    ]
    assert not _messages(handler, level=logging.DEBUG)


def test_oco_cancellation_logs_terminal_event(monkeypatch):
    """The direct OCO cancellation path has the same lifecycle observability."""
    handler = _capture_bbroker_logger(monkeypatch)
    broker = bbroker_module.BackBroker()
    monkeypatch.setattr(broker, "notify", lambda order: None)
    sibling = _LifecycleOrder(status=order_module.Order.Accepted)
    trigger = SimpleNamespace(ref=2)
    broker.pending.append(sibling)
    broker._ocos[trigger.ref] = trigger.ref
    broker._ocol[trigger.ref].append(sibling.ref)

    broker._ococheck(trigger)

    assert sibling.status == order_module.Order.Canceled
    assert _messages(handler, level=logging.INFO) == [
        "order canceled: ref=1 side=buy size=2 price=101.5 data=asset",
    ]


def test_disabled_cancellation_info_does_not_evaluate_payload(monkeypatch):
    """Cancellation metadata remains lazy while no configured sink can receive INFO."""
    broker = bbroker_module.BackBroker()
    monkeypatch.setattr(bbroker_module, "logger", _DisabledInfoLogger())
    monkeypatch.setattr(broker, "notify", lambda order: None)
    monkeypatch.setattr(broker, "_ococheck", lambda order: None)
    monkeypatch.setattr(broker, "_bracketize", lambda *args, **kwargs: None)

    class _UnreadableCancellationOrder:
        status = order_module.Order.Submitted

        def alive(self):
            return True

        def cancel(self):
            self.status = order_module.Order.Canceled

        @property
        def ref(self):
            raise AssertionError("INFO payload read order.ref while logging was disabled")

        @property
        def size(self):
            raise AssertionError("INFO payload read order.size while logging was disabled")

        @property
        def price(self):
            raise AssertionError("INFO payload read order.price while logging was disabled")

        @property
        def data(self):
            raise AssertionError("INFO payload read order.data while logging was disabled")

        def isbuy(self):
            raise AssertionError("INFO payload read order side while logging was disabled")

    order = _UnreadableCancellationOrder()
    broker.submitted.append(order)
    assert broker.cancel(order) is True


@pytest.mark.parametrize(
    ("broker_kwargs", "strategy"),
    [
        ({"cash": 1.0}, _OversizedBuy),
        ({"cash": 1.0, "position_mode": "dual_side"}, _DualSideOversizedBuy),
    ],
)
def test_margin_terminal_outcomes_are_warning_observable(monkeypatch, broker_kwargs, strategy):
    """Normal and dual-side submission checks expose real margin terminal states."""
    handler = _capture_bbroker_logger(monkeypatch, level=logging.WARNING)
    broker = bbroker_module.BackBroker(**broker_kwargs)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(DATA_PATH), plot=False), name="asset")
    cerebro.addstrategy(strategy)

    cerebro.run()

    warnings = _messages(handler, level=logging.WARNING)
    assert any("order margin:" in message for message in warnings)
    assert any(
        "insufficient cash or margin during submission check" in message for message in warnings
    )


def test_dual_side_runtime_close_rejection_is_warning_observable(monkeypatch):
    """A position that vanishes after acceptance still emits a terminal rejection warning."""
    handler = _capture_bbroker_logger(monkeypatch, level=logging.WARNING)
    broker = bbroker_module.BackBroker(position_mode="dual_side")
    monkeypatch.setattr(broker, "getcommissioninfo", lambda data: object())
    monkeypatch.setattr(broker, "_get_leg_position", lambda data, side: SimpleNamespace(size=0))
    monkeypatch.setattr(
        broker,
        "_make_signed_position",
        lambda side, position: SimpleNamespace(size=0),
    )
    monkeypatch.setattr(broker, "notify", lambda order: None)
    monkeypatch.setattr(broker, "_ococheck", lambda order: None)
    monkeypatch.setattr(broker, "_bracketize", lambda *args, **kwargs: None)
    order = _LifecycleOrder()
    order.info = SimpleNamespace(position_side="long", offset="close")
    order.data = SimpleNamespace(_compensate=None)

    assert broker._execute_dual_side(order, ago=0, price=101.0) is None
    assert order.status == order_module.Order.Rejected
    assert _messages(handler, level=logging.WARNING) == [
        "order rejected: ref=1 reason=close quantity exceeds available position",
    ]


@pytest.mark.parametrize(
    ("broker_kwargs", "strategy"),
    [
        ({}, _BuyOnce),
        ({"position_mode": "dual_side"}, _DualSideBuyOnce),
    ],
)
def test_execution_logging_uses_current_fill_size_and_commission(
    monkeypatch, broker_kwargs, strategy
):
    """Normal and dual paths log the current fill rather than remaining size."""
    handler = _capture_bbroker_logger(monkeypatch, level=logging.INFO)
    broker = bbroker_module.BackBroker(**broker_kwargs)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(DATA_PATH), plot=False), name="asset")
    cerebro.addstrategy(strategy)

    cerebro.run()

    executions = [
        message for message in _messages(handler) if message.startswith("order executed:")
    ]
    assert executions
    assert all("size=1" in message for message in executions)
    assert all("commission=" in message for message in executions)
    assert all("size=0" not in message for message in executions)
