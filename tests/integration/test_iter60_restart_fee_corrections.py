"""Iteration 60 (post-acceptance): a late fee correction that reaches a restarted process.

A spawned child process trades one SELL 2 of strategy A (two fills with
provider fees 0.5 CNY each) and is killed with ``os._exit``; a new process on
the same files then receives a fee correction of the first fill (0.5 -> 0.8
CNY). Before this fix the correction of an order a dead process finished was
only counted as orphaned (Gateway) or deferred as unmatched (direct), and the
correction of a fill of a rebuilt open Gateway order was applied as a second
fill. Now, in direct and Gateway mode alike:

* the strategy ledger fee moves once to 1.3 CNY (per currency, idempotent);
* ``notify_fee_correction`` is called once with delta 0.3 CNY (journaled before
  delivery, acknowledged after it, replayed after a crash), with a read-only
  ``RecoveredOrder`` rebuilt from the journal (original ref and intent id,
  last status, executed size/price, corrected commission) and a
  ``RecoveredTrade`` of the Trade that order last updated - or, for an open
  Gateway order that was rebuilt as a live ``Order``, that live order;
* the same correction again is ignored; a lower fee or another currency fails
  closed (direct) or is refused by the Gateway producer;
* restart and non-restart yield the same ledger fee and the same delta.

INTEGRATION_SIM: local SQLite files, test-owned processes, co-located Gateway
read service; no provider, account or network.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")
pytest.importorskip("bt_api_py.service_execution_event_consumer")
pytest.importorskip("bt_api_gateway.execution_event_publisher")

_HERE = Path(__file__).resolve().parent
_FEES = {"t-1": "0.5", "t-2": "0.5"}
_MODES = ("direct", "gateway")


def _support():
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_gateway_execution_support as support

    return support


class _Sink(list):
    """Deliveries, written durably before the callback returns (child processes)."""

    def __init__(self, path=None):
        super().__init__()
        self.path = path

    def append(self, entry):
        if self.path is not None:
            with open(self.path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        super().append(entry)


def _fee_call(order, trade, delta, currency):
    info = getattr(order, "info", {})
    return {
        "kind": "fee",
        "recovered": bool(getattr(order, "recovered", False)),
        "replayed": bool(getattr(order, "replayed", False)),
        "ref": order.ref,
        "status": order.getstatusname(),
        "executed_size": order.executed.size,
        "comm": order.executed.comm,
        "intent": info.get("strategy_ledger_intent_id"),
        "notification_id": getattr(order, "notification_id", None),
        "trade_commission": None if trade is None else trade.commission,
        "trade_recovered": bool(getattr(trade, "recovered", False)),
        "delta": delta,
        "currency": currency,
    }


def _open(directory, mode, *, log=None, acknowledge="after_apply"):
    """A ledger-bound BtApiBroker with notification recovery (``direct``/``gateway``)."""

    t = _support()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    book = t.ledger(directory / "ledger.sqlite3")
    store = t.SdkStore()
    store.frozen = []
    store.freeze_openings = store.frozen.append
    broker = t.BtApiBroker(store=store)
    feed = t.data()
    (a,) = t.strategies(broker, feed, "strategy-a")
    received = _Sink(log)
    t.recording(a, received)

    def notify_fee_correction(order, trade, delta, currency):
        received.append(_fee_call(order, trade, delta, currency))

    a.notify_fee_correction = notify_fee_correction
    broker.bind_direct_strategy_ledger(a, book, unreconciled=True)
    replayed = broker.bind_strategy_notification_recovery(
        a, directory / "recovery", deployment_ref="dep"
    )
    rebuilt = None
    if mode == "gateway":
        rebuilt = broker.bind_gateway_execution_events(
            a,
            t.consumer(directory / "gateway.sqlite3", directory / "sdk", "strategy-a"),
            directory / "projection",
            data_names={"SA2701": t.INSTRUMENT},
            acknowledge=acknowledge,
        )
    return SimpleNamespace(
        t=t,
        mode=mode,
        ledger=book,
        broker=broker,
        store=store,
        data=feed,
        a=a,
        received=received,
        replayed=replayed,
        rebuilt=rebuilt,
        directory=directory,
    )


def _close(s):
    if s.broker._gateway_execution_bindings is not None:
        s.broker.close_gateway_execution_events()
    if s.broker._strategy_notification_recovery is not None:
        s.broker.close_strategy_notification_recovery()
    s.ledger.close()


def _fee_trade(t, trade_id, fee, currency="CNY", quantity="1", price="1500"):
    from bt_api_base.execution_row_observation_protocol import AccountExecutionTradeObservation

    base = t.trade_obs(trade_id, "o-1", quantity, price)
    return AccountExecutionTradeObservation(base.account_key, base.trade, fee, currency)


def _direct_trade_row(t, trade_id, fee, currency="CNY", quantity="1", price="1500"):
    """What a direct SDK Store reports for a fill after a restart (provider ids only)."""

    return {
        "kind": "trade",
        "trade_id": trade_id,
        "external_order_id": "o-1",
        "order_id": "o-1",
        "side": "sell",
        "quantity": quantity,
        "price": price,
        "quantity_unit": "contracts",
        "data_name": t.INSTRUMENT,
        "fee": fee,
        "fee_currency": currency,
        "fee_unit": "currency",
    }


def _script(t, scenario):
    return t.SCRIPT if scenario == "terminal" else t.SCRIPT[:3]


def _trade(s, scenario):
    """Strategy A sells 2: every fill with a provider fee (terminal: both fills)."""

    t = s.t
    order = t.place(s)
    t.cycle(s)
    script = _script(t, scenario)
    if s.mode == "gateway":
        items = [
            t.order_obs(*step[1:]) if step[0] == "order" else _fee_trade(t, step[1], _FEES[step[1]])
            for step in script
        ]
        t.publish(s.directory / "gateway.sqlite3", items)
        s.broker.poll_gateway_execution_events()
        t.cycle(s)
        return order
    for row in t.direct_rows(order, script):
        if row["kind"] == "trade":
            row.update(fee=_FEES[row["trade_id"]], fee_currency="CNY", fee_unit="currency")
        s.store.rows.append(row)
        s.broker.next()
        t.cycle(s)
    return order


def _correct(s, fee, currency="CNY", trade_id="t-1"):
    t = s.t
    if s.mode == "gateway":
        t.publish(s.directory / "gateway.sqlite3", [_fee_trade(t, trade_id, fee, currency)])
        s.broker.poll_gateway_execution_events()
    else:
        s.store.rows.append(_direct_trade_row(t, trade_id, fee, currency))
        s.broker.next()
    t.cycle(s)


def _child(directory, mode, scenario, stage):
    directory = Path(directory)
    s = _open(directory, mode, log=directory / f"{stage}.log")
    recovery = s.broker._strategy_notification_recovery[id(s.a)]
    if stage == "trade":
        order = _trade(s, scenario)
        (directory / "order_ref.txt").write_text(str(order.ref))
        os._exit(70)  # everything delivered and acknowledged; no clean shutdown
    if stage == "trade_correct":
        _trade(s, scenario)
        _correct(s, "0.8")
        os._exit(70)
    if stage == "trade_correct_crash_before_record":
        _trade(s, scenario)
        binding = s.broker._gateway_execution_bindings[id(s.a)]

        def record_then_die(*_args, **_kwargs):
            os._exit(74)  # the correction applied and journaled, its fact not recorded

        binding.store.record_fact = record_then_die
        _correct(s, "0.8")
        os._exit(79)
    real_append = recovery.journal.append_many

    def append_then_die(entries, **kwargs):
        correction = any(item[1] == "fee_correction" for item in entries)
        if correction and stage == "die_before_append":
            os._exit(72)  # the ledger moved; nothing journaled
        results = real_append(entries, **kwargs)
        if correction and stage == "die_after_append" and any(c for _e, c in results):
            os._exit(71)  # journaled; no callback, no ACK, no Gateway fact record
        return results

    recovery.journal.append_many = append_then_die
    _correct(s, "0.8")
    os._exit(79)


def _run(directory, mode, scenario, stage):
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_child, args=(str(directory), mode, scenario, stage))
    child.start()
    child.join(timeout=120)
    try:
        return child.exitcode
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def _logged(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _fees(s):
    return dict(s.ledger.snapshot("strategy-a").fees_since_baseline)


def _corrections(entries):
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("kind") == "fee"]


def _healthy(s):
    assert s.broker._trading_enabled is not False
    assert s.broker.strategy_notification_recovery_state(s.a) == "ACTIVE"
    assert s.broker.fee_correction_fence() is None
    if s.mode == "gateway":
        assert s.broker.gateway_execution_events_state(s.a)["state"] == "ACTIVE"
    journal = s.broker._strategy_notification_recovery[id(s.a)].journal
    assert journal.stats()["pending"] == 0


def _no_restart(directory, mode, scenario):
    """The reference: the same trades and correction in one process."""

    s = _open(directory, mode)
    _trade(s, scenario)
    _correct(s, "0.8")
    return s


# -- (a) terminal order, with parity ---------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("mode", _MODES)
def test_fee_correction_after_restart_for_a_terminal_order(tmp_path, mode):
    assert _run(tmp_path, mode, "terminal", "trade") == 70
    original_ref = int((tmp_path / "order_ref.txt").read_text())
    s = _open(tmp_path, mode)
    reference = _no_restart(tmp_path / "reference", mode, "terminal")
    try:
        assert s.replayed == 0 and s.rebuilt in (None, 0)
        assert _fees(s) == {"CNY": Decimal("1.0")}
        _correct(s, "0.8")
        (call,) = _corrections(s.received)
        assert (call["delta"], call["currency"]) == (pytest.approx(0.3), "CNY")
        assert call["recovered"] is True and call["replayed"] is False
        assert call["ref"] == original_ref and call["intent"] == "intent-sa-1"
        assert call["status"] == "Completed" and call["executed_size"] == -2.0
        assert call["comm"] == pytest.approx(1.3)
        assert call["trade_recovered"] is True and call["trade_commission"] == pytest.approx(1.3)
        # ... followed by the corrected order notification (as without a restart).
        assert s.received[-1][:2] == ("order", "Completed") and s.received[-1][3] is False
        assert _fees(s) == {"CNY": Decimal("1.3")}
        assert s.t.position(s) == Decimal("0")
        assert s.ledger.intent_state("intent-sa-1") == "FILLED"
        _healthy(s)
        if mode == "gateway":
            assert s.broker.gateway_execution_events_state(s.a)["applied"] == 1

        # Parity with the same correction without a restart.
        (expected,) = _corrections(reference.received)
        assert _fees(reference) == _fees(s)
        assert (expected["delta"], expected["currency"]) == (call["delta"], call["currency"])
        assert expected["trade_commission"] == pytest.approx(call["trade_commission"])
        assert expected["comm"] == pytest.approx(call["comm"])

        # The same correction again: nothing.
        before = len(s.received)
        _correct(s, "0.8")
        assert len(s.received) == before and _fees(s) == {"CNY": Decimal("1.3")}
        _healthy(s)
    finally:
        _close(s)
        _close(reference)
    third = _open(tmp_path, mode)
    try:
        assert third.replayed == 0 and third.received == []
        _correct(third, "0.8")
        assert third.received == [] and _fees(third) == {"CNY": Decimal("1.3")}
    finally:
        _close(third)


# -- (b) open order ----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("mode", _MODES)
def test_fee_correction_after_restart_for_an_open_order(tmp_path, mode):
    assert _run(tmp_path, mode, "open", "trade") == 70
    s = _open(tmp_path, mode)
    reference = _no_restart(tmp_path / "reference", mode, "open")
    try:
        assert _fees(s) == {"CNY": Decimal("0.5")} and s.t.position(s) == Decimal("1")
        _correct(s, "0.8")
        (call,) = _corrections(s.received)
        (expected,) = _corrections(reference.received)
        assert (call["delta"], call["currency"]) == (pytest.approx(0.3), "CNY")
        assert (expected["delta"], expected["currency"]) == (call["delta"], call["currency"])
        assert _fees(s) == _fees(reference) == {"CNY": Decimal("0.8")}
        # Never a second fill: the order stays half filled.
        assert call["executed_size"] == -1.0 and call["comm"] == pytest.approx(0.8)
        assert s.t.position(s) == Decimal("1")
        assert s.ledger.intent_state("intent-sa-1") == "PARTIALLY_FILLED"
        _healthy(s)
        if mode == "gateway":
            # The open order was rebuilt as a live Order and takes the correction itself.
            assert s.rebuilt == 1 and call["recovered"] is False and call["status"] == "Partial"
            assert call["trade_commission"] is None  # its Trade belongs to the dead process
            (order,) = s.broker.orders.values()
            assert order.executed.size == -1.0 and order.executed.comm == pytest.approx(0.8)
            # The rest of the order still projects, with the corrected cumulative fee.
            t = s.t
            t.publish(
                s.directory / "gateway.sqlite3",
                [_fee_trade(t, "t-2", "0.5", price="1510"), t.order_obs(*t.SCRIPT[4][1:])],
            )
            s.broker.poll_gateway_execution_events()
            t.cycle(s)
            assert order.executed.size == -2.0 and order.executed.comm == pytest.approx(1.3)
            assert _fees(s) == {"CNY": Decimal("1.3")} and t.position(s) == Decimal("0")
            assert s.ledger.intent_state("intent-sa-1") == "FILLED"
            assert len(_corrections(s.received)) == 1
            _healthy(s)
        else:
            assert call["recovered"] is True and call["status"] == "Partial"
            assert call["trade_recovered"] is True
            assert call["trade_commission"] == pytest.approx(0.8)
    finally:
        _close(s)
        _close(reference)


# -- (c) duplicate correction after restart ------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("mode", _MODES)
def test_correction_already_applied_before_the_restart_is_ignored(tmp_path, mode):
    assert _run(tmp_path, mode, "terminal", "trade_correct") == 70
    child = _corrections(_logged(tmp_path / "trade_correct.log"))
    assert [(c["delta"], c["recovered"]) for c in child] == [(pytest.approx(0.3), False)]
    s = _open(tmp_path, mode)
    try:
        assert s.replayed == 0 and _fees(s) == {"CNY": Decimal("1.3")}
        _correct(s, "0.8")  # Gateway: the same fact is not even published twice
        _correct(s, "0.8")
        assert _corrections(s.received) == [] and _fees(s) == {"CNY": Decimal("1.3")}
        _healthy(s)
    finally:
        _close(s)


@pytest.mark.integration
def test_gateway_correction_journaled_but_not_recorded_is_not_applied_twice(tmp_path):
    """Crash after the live correction was booked and journaled, before its Gateway fact."""

    assert _run(tmp_path, "gateway", "terminal", "trade_correct_crash_before_record") == 74
    assert _corrections(_logged(tmp_path / "trade_correct_crash_before_record.log")) == []
    s = _open(tmp_path, "gateway")
    try:
        # The journaled correction comes back once as a replay...
        (replay,) = _corrections(s.received)
        assert replay["replayed"] is True and replay["delta"] == pytest.approx(0.3)
        # ... and the re-read Gateway event is recognised from the applied-fill index.
        s.broker.poll_gateway_execution_events()
        s.t.cycle(s)
        assert len(_corrections(s.received)) == 1
        assert _fees(s) == {"CNY": Decimal("1.3")}
        state = s.broker.gateway_execution_events_state(s.a)
        assert state["skipped"] == 1 and state["applied"] == 0
        checkpoint = s.broker._gateway_execution_bindings[id(s.a)].consumer.checkpoint()
        assert checkpoint.cursor == 6 and not checkpoint.pending_ack
        _healthy(s)
    finally:
        _close(s)


@pytest.mark.integration
def test_gateway_open_order_correction_journaled_but_not_recorded_is_not_applied_twice(
    tmp_path,
):
    """The same window for an open order: rebuilt live, the re-read correction re-applied."""

    assert _run(tmp_path, "gateway", "open", "trade_correct_crash_before_record") == 74
    s = _open(tmp_path, "gateway")
    try:
        assert s.rebuilt == 1
        (replay,) = _corrections(s.received)
        assert replay["replayed"] is True and replay["delta"] == pytest.approx(0.3)
        (order,) = s.broker.orders.values()
        assert order.executed.comm == pytest.approx(0.5)  # the recorded state: pre-correction
        replays = list(s.received)  # the correction and its order notification
        assert replays[-1][:2] == ("order", "Partial") and replays[-1][3] is True
        # Re-applied onto the recorded state: same journal ids, not delivered again.
        assert s.broker.poll_gateway_execution_events() == 1
        s.t.cycle(s)
        assert s.received == replays
        assert order.executed.size == -1.0 and order.executed.comm == pytest.approx(0.8)
        assert _fees(s) == {"CNY": Decimal("0.8")} and s.t.position(s) == Decimal("1")
        _healthy(s)
        # Later fills keep the corrected cumulative fee and never re-fire the correction.
        t = s.t
        t.publish(
            s.directory / "gateway.sqlite3",
            [_fee_trade(t, "t-2", "0.5", price="1510"), t.order_obs(*t.SCRIPT[4][1:])],
        )
        s.broker.poll_gateway_execution_events()
        t.cycle(s)
        assert len(_corrections(s.received)) == 1
        assert _fees(s) == {"CNY": Decimal("1.3")} and t.position(s) == Decimal("0")
        assert s.ledger.intent_state("intent-sa-1") == "FILLED"
        _healthy(s)
    finally:
        _close(s)


# -- (d) regression or another currency after restart ----------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fee", "currency", "reason"),
    [("0.4", "CNY", "fee_regressed"), ("0.9", "USD", "fee_currency_or_basis_mismatch")],
)
def test_direct_regressed_or_foreign_fee_after_restart_fails_closed(
    tmp_path, fee, currency, reason
):
    assert _run(tmp_path, "direct", "terminal", "trade") == 70
    s = _open(tmp_path, "direct")
    try:
        _correct(s, fee, currency)
        assert s.broker._trading_enabled is False
        assert s.store.frozen == ["fill_fee_correction_unprojectable"]
        assert s.broker.fee_correction_fence() == reason
        assert _corrections(s.received) == [] and _fees(s) == {"CNY": Decimal("1.0")}
        # The fill keeps its booked fee: a valid correction is still recognised later.
        recovery = s.broker._strategy_notification_recovery[id(s.a)]
        assert recovery.journal.stats()["pending"] == 0
    finally:
        _close(s)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fee", "currency", "code"),
    [("0.4", "CNY", "EXECUTION_FEE_REGRESSED"), ("0.9", "USD", "EXECUTION_FEE_CURRENCY_CONFLICT")],
)
def test_gateway_refuses_a_regressed_or_foreign_fee_after_restart(tmp_path, fee, currency, code):
    from bt_api_gateway.execution_event_publisher import GatewayExecutionEventError

    assert _run(tmp_path, "gateway", "terminal", "trade") == 70
    s = _open(tmp_path, "gateway")
    try:
        with pytest.raises(GatewayExecutionEventError) as refused:
            s.t.publish(s.directory / "gateway.sqlite3", [_fee_trade(s.t, "t-1", fee, currency)])
        assert refused.value.code == code
        assert s.broker.poll_gateway_execution_events() == 0
        s.t.cycle(s)
        assert _corrections(s.received) == [] and _fees(s) == {"CNY": Decimal("1.0")}
        _healthy(s)
    finally:
        _close(s)


# -- (e) crash between the journal append and the callback -------------------------


@pytest.mark.integration
@pytest.mark.parametrize("mode", _MODES)
def test_crash_between_journal_append_and_callback_replays_once(tmp_path, mode):
    assert _run(tmp_path, mode, "terminal", "trade") == 70
    assert _run(tmp_path, mode, "terminal", "die_after_append") == 71
    assert _corrections(_logged(tmp_path / "die_after_append.log")) == []
    s = _open(tmp_path, mode)
    try:
        (replay,) = _corrections(s.received)
        assert replay["replayed"] is True and replay["recovered"] is True
        assert (replay["delta"], replay["currency"]) == (pytest.approx(0.3), "CNY")
        assert replay["trade_commission"] == pytest.approx(1.3)
        assert _fees(s) == {"CNY": Decimal("1.3")}
        _correct(s, "0.8")  # Gateway: re-read (not recorded); direct: provider re-reports
        assert len(_corrections(s.received)) == 1 and _fees(s) == {"CNY": Decimal("1.3")}
        _healthy(s)
    finally:
        _close(s)


@pytest.mark.integration
@pytest.mark.parametrize("mode", _MODES)
def test_crash_after_the_ledger_before_the_journal_books_the_fee_once(tmp_path, mode):
    assert _run(tmp_path, mode, "terminal", "trade") == 70
    assert _run(tmp_path, mode, "terminal", "die_before_append") == 72
    s = _open(tmp_path, mode)
    try:
        assert s.replayed == 0 and _corrections(s.received) == []
        assert _fees(s) == {"CNY": Decimal("1.3")}  # the dead process moved the ledger
        _correct(s, "0.8")  # re-delivered: journaled and delivered now, ledger unchanged
        (call,) = _corrections(s.received)
        assert call["replayed"] is False and call["delta"] == pytest.approx(0.3)
        assert _fees(s) == {"CNY": Decimal("1.3")}
        _healthy(s)
    finally:
        _close(s)
