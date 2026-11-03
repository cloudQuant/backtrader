"""Direct-mode strategy ledger wiring for ``BtApiBroker`` (iteration 60, P0-3).

The SDK ``bt_api_py.strategy_ledger.SqliteStrategyLedger`` owns the durable
per-strategy positions and the close-capacity/budget admission. This mixin
keeps only the Backtrader side:

* ``bind_direct_strategy_ledger`` binds each Strategy to its own ledger book
  (identity checked) and makes the ledger the Broker's admission gate;
* once a ledger is bound, *every* order submitted through this Broker must
  come from a bound Strategy and must pass ``ledger.reserve`` before it is
  handed to the Store; otherwise it is rejected locally and never dispatched;
* order notifications keep the ledger in step: accepted, cumulative fills,
  cancel/expire/reject, and UNKNOWN (which keeps the reservation);
* a ledger update that fails disables trading (fail closed) instead of
  letting positions and the ledger diverge silently.
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal

from ..order import Order
from ..utils.log_message import get_logger

_logger = get_logger(__name__)

_FINAL_STATES = {
    Order.Canceled: "CANCELLED",
    Order.Expired: "EXPIRED",
    Order.Margin: "REJECTED",
    Order.Rejected: "REJECTED",
}


def _decimal(value) -> Decimal | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return Decimal(str(number))


class StrategyLedgerBrokerMixin:
    """Bind strategies to an SDK strategy ledger and gate their orders."""

    _direct_strategy_ledger = None

    def bind_direct_strategy_ledger(self, strategy, ledger, *, account_positions=None):
        """Bind ``strategy`` to its book in ``ledger`` and gate its orders.

        ``ledger`` is the account's single active
        ``bt_api_py.strategy_ledger.SqliteStrategyLedger`` owner. One Broker
        uses one ledger. ``account_positions`` optionally returns provider
        account positions (instrument -> signed quantity); the book then
        fails closed unless the ledger reconciles with them.
        """

        from bt_api_py.strategy_ledger import SqliteStrategyLedger

        if type(ledger) is not SqliteStrategyLedger:
            raise ValueError("a bt_api_py SqliteStrategyLedger is required")
        current = self._direct_strategy_ledger
        if current is not None and current is not ledger:
            raise ValueError("this broker is already gated by another strategy ledger")
        strategy_ref = getattr(getattr(strategy, "p", None), "strategy_ref", None)
        if type(strategy_ref) is not str or not strategy_ref:
            raise ValueError("strategy identity does not match the account-book reader")
        reader = ledger.reader(strategy_ref, account_positions=account_positions)
        view = self.bind_direct_strategy_account_book(strategy, reader)
        self._direct_strategy_ledger = ledger
        return view

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    def _bound_strategy_ref(self, strategy):
        for (strategy_ref, _account_ref), owner in (
            getattr(self, "_direct_strategy_books", None) or {}
        ).items():
            if owner is strategy:
                return strategy_ref
        return None

    def _direct_ledger_admission_error(self, order):
        """Reserve ``order`` in the ledger; return ``(code, message)`` to reject."""

        ledger = self._direct_strategy_ledger
        if ledger is None:
            return None
        from bt_api_py.strategy_ledger import LedgerIntent, StrategyLedgerError

        strategy_ref = self._bound_strategy_ref(getattr(order, "owner", None))
        if strategy_ref is None:
            return (
                "strategy_ledger_unbound",
                "Orders on a ledger-gated account require a bound strategy book",
            )
        instrument = getattr(order.data, "_name", None)
        quantity = _decimal(abs(order.size or 0))
        if not instrument or quantity is None:
            return ("strategy_ledger_intent_invalid", "Order instrument or size is invalid")
        price = _decimal(order.price)
        if price is None and order.exectype == Order.Market:
            # Backtrader records the reference close for market orders.
            price = _decimal(getattr(order.created, "price", None))
        intent_id = f"bt-{uuid.uuid4().hex}"
        try:
            intent = LedgerIntent(
                intent_id,
                strategy_ref,
                instrument,
                "BUY" if order.isbuy() else "SELL",
                quantity,
                price,
            )
            ledger.reserve(intent)
        except StrategyLedgerError as error:
            return (
                f"strategy_ledger_{error.code.lower()}",
                "The strategy ledger refused the order before dispatch",
            )
        order.addinfo(strategy_ledger_intent_id=intent_id)
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _sync_direct_ledger(self, order) -> None:
        ledger = self._direct_strategy_ledger
        if ledger is None:
            return
        intent_id = self._order_info_get(order, "strategy_ledger_intent_id")
        if intent_id is None:
            return
        try:
            self._apply_ledger_status(ledger, intent_id, order)
        except Exception as error:  # fail closed: never trade on a divergent ledger
            _logger.error(
                "strategy ledger update failed; trading disabled (%s)",
                getattr(error, "code", type(error).__name__),
            )
            self._trading_enabled = False

    def _apply_ledger_status(self, ledger, intent_id, order) -> None:
        status = order.status
        executed = abs(float(getattr(order.executed, "size", 0) or 0))
        if executed > 0:
            ledger.apply_execution(
                intent_id,
                cumulative_quantity=Decimal(str(executed)),
                average_price=_decimal(getattr(order.executed, "price", None)),
            )
        if self._order_info_get(order, "execution_unknown") and status not in _FINAL_STATES:
            if ledger.intent_state(intent_id) in ("RESERVED", "SUBMITTED"):
                ledger.mark_unknown(intent_id)
            return
        if status in (Order.Submitted, Order.Accepted):
            if ledger.intent_state(intent_id) in ("RESERVED", "UNKNOWN"):
                ledger.mark_submitted(intent_id)
        elif status in _FINAL_STATES:
            if ledger.intent_state(intent_id) not in ("FILLED", "CANCELLED", "EXPIRED", "REJECTED"):
                ledger.finish(intent_id, _FINAL_STATES[status])
