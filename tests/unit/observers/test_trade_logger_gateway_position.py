"""TradeLogger in Gateway mode logs the strategy's own position.

SimNow 2026-11-10: with the 007_ctp Gateway example every bar recorded
``observer_internal_error: GATEWAY_ACCOUNT_POSITION_UNAVAILABLE`` and the
indicator and snapshot logs after the position log were skipped.
"""
import math
from types import SimpleNamespace

from backtrader.observers.trade_logger import TradeLogger


class _Data:
    _name = "SA701"

    def __init__(self):
        self.bars = 1

    def __len__(self):
        return self.bars


def _gateway_logger(sizes, *, gateway=True):
    data = _Data()
    reads = []

    def own(feed, side=None):
        reads.append(side)
        value = sizes[side]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(size=value, price=float("nan"))

    def account(feed):
        if gateway:
            raise RuntimeError("GATEWAY_ACCOUNT_POSITION_UNAVAILABLE")
        return SimpleNamespace(size=7.0, price=12.5)

    owner = SimpleNamespace(
        broker=SimpleNamespace(store=SimpleNamespace(_gateway_mode=gateway)),
        get_strategy_position=own, getposition=account, datas=[data])
    logger = object.__new__(TradeLogger)
    logger._owner = owner
    return logger, data, reads


def test_gateway_mode_logs_the_strategys_own_net_position_once_per_bar():
    logger, data, reads = _gateway_logger({"long": 3.0, "short": 1.0})
    position = logger._position_to_log(data)
    assert position.size == 2.0 and math.isnan(position.price)
    # The snapshot of the same bar reuses the read; the next bar reads again.
    assert logger._position_to_log(data) is position and reads == ["long", "short"]
    data.bars = 2
    assert logger._position_to_log(data).size == 2.0 and len(reads) == 4

    flat, data, _ = _gateway_logger({"long": 0.0, "short": 0.0})
    position = flat._position_to_log(data)
    assert position.size == 0.0 and position.price == 0.0


def test_gateway_mode_skips_the_row_while_the_ledger_cannot_answer(monkeypatch):
    import backtrader.observers.trade_logger as module

    warnings = []
    monkeypatch.setattr(module.logger, "warning", lambda *args: warnings.append(args))
    sizes = {"long": RuntimeError("GATEWAY_STREAM_STRATEGY_POSITION_UNAVAILABLE"), "short": 0.0}
    logger, data, reads = _gateway_logger(sizes)
    assert logger._position_to_log(data) is None
    data.bars = 2
    assert logger._position_to_log(data) is None
    assert len(warnings) == 1  # said once, not on every bar
    assert warnings[0][1] == "GATEWAY_STREAM_STRATEGY_POSITION_UNAVAILABLE"
    sizes["long"] = 1.0
    data.bars = 3
    assert logger._position_to_log(data).size == 1.0
    # A later outage is reported again, also for the same reason.
    sizes["long"] = RuntimeError("GATEWAY_STREAM_STRATEGY_POSITION_UNAVAILABLE")
    data.bars = 4
    assert logger._position_to_log(data) is None and len(warnings) == 2


def test_outside_gateway_mode_the_account_position_is_logged_as_before():
    logger, data, reads = _gateway_logger({"long": 3.0, "short": 1.0}, gateway=False)
    position = logger._position_to_log(data)
    assert (position.size, position.price) == (7.0, 12.5) and reads == []
