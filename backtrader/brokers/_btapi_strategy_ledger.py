"""Direct-mode strategy ledger wiring for ``BtApiBroker`` (iteration 60, P0-3).

The SDK ``bt_api_py.strategy_ledger.SqliteStrategyLedger`` owns the durable
per-strategy positions and the close-capacity/budget admission. This mixin
keeps only the Backtrader side:

* ``bind_direct_strategy_ledger`` binds each Strategy to its own ledger book
  (identity checked) and makes the ledger the Broker's admission gate. The
  book is reconciled on every read against an ``AccountPositionReport``
  delivered by subscription: by default the Store's provider position
  stream (``BtApiStore.subscribe_account_positions``); for Gateway mode pass
  ``bt_api_py.account_position_stream.GatewayAccountPositionStream.report``.
  ``account_positions="store_snapshot"`` reads a provider snapshot on every
  query but cannot prove account identity and completeness from its projected
  rows alone, so remains unverified. A ledger-only book needs
  ``unreconciled=True``;
* once a ledger is bound, *every* order submitted through this Broker must
  come from a bound Strategy, the Broker must be bound to the account owner
  fence (``bind_account_owner``), and the order must pass ``ledger.reserve``
  before it is handed to the Store; otherwise it is rejected locally and
  never dispatched;
* order notifications keep the ledger in step: accepted, cumulative fills
  with the provider's cumulative fee per currency, cancel/expire/reject, and
  UNKNOWN (which keeps the reservation);
* a ledger update that fails disables trading (fail closed) instead of
  letting positions and the ledger diverge silently.
"""

from __future__ import annotations

import datetime as _dt
import math
import time
import uuid
from decimal import Decimal, InvalidOperation

from ..order import Order
from ._btapi_strategy_events import StrategyLedgerEventsBrokerMixin
from ..utils.log_message import get_logger

_logger = get_logger(__name__)

_FINAL_STATES = {
    Order.Canceled: "CANCELLED",
    Order.Expired: "EXPIRED",
    Order.Margin: "REJECTED",
    Order.Rejected: "REJECTED",
}


def _parse_utc_ns(text) -> int | None:
    if type(text) is not str or not text:
        return None
    try:
        moment = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return int(moment.timestamp() * 1_000_000_000)


def store_account_position_report(store, account_ref):
    """Build an ``AccountPositionReport`` from the Store's SDK position snapshot.

    The Store's list projection does not carry the SDK snapshot's account,
    session, completeness or lease evidence. The supplied ``account_ref`` and
    a local read timestamp cannot replace that evidence, including for an
    empty result. Preserve the rows for diagnostics but keep the report
    incomplete. Callers that possess an independently validated account report
    can provide it through ``account_positions`` instead.
    """

    from bt_api_py.strategy_ledger import AccountPositionReport

    if not getattr(store, "_sdk_mode", False):
        raise ValueError("store account positions need the unified SDK read path")
    read_ns = time.time_ns()
    rows = store.get_positions()
    positions: dict[str, Decimal] = {}
    observed = []
    for row in rows:
        name = row.get("data_name")
        side = row.get("side")
        try:
            quantity = Decimal(str(row.get("quantity")))
        except (InvalidOperation, ValueError):
            quantity = None
        stamp = _parse_utc_ns(row.get("observed_at_utc"))
        if (
            type(name) is not str
            or not name
            or side not in ("net", "long", "short")
            or quantity is None
            or not quantity.is_finite()
            or stamp is None
        ):
            raise ValueError("store account position row is not usable evidence")
        signed = -abs(quantity) if side == "short" else abs(quantity) if side == "long" else quantity
        positions[name] = positions.get(name, Decimal("0")) + signed
        observed.append(stamp)
    source = f"btapistore:{getattr(store, 'provider', None) or 'sdk'}:account_positions"
    return AccountPositionReport(
        account_ref, source, min(observed) if observed else read_ns, False, positions
    )


def _decimal(value) -> Decimal | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return Decimal(str(number))


class StrategyLedgerBrokerMixin(StrategyLedgerEventsBrokerMixin):
    """Bind strategies to an SDK strategy ledger and gate their orders."""

    _direct_strategy_ledger = None

    def bind_direct_strategy_ledger(
        self,
        strategy,
        ledger,
        *,
        account_positions=None,
        unreconciled=False,
        event_cursor_path=None,
    ):
        """Bind ``strategy`` to its book in ``ledger`` and gate its orders.

        ``ledger`` is the account's single active
        ``bt_api_py.strategy_ledger.SqliteStrategyLedger`` owner. One Broker
        uses one ledger. Every read of the book is reconciled with an
        ``AccountPositionReport`` (see the SDK ``StrategyLedgerReader``):
        ``account_positions`` returns that report, or is an object with a
        ``report()`` method such as the stream from
        ``bt_api_py.account_position_stream.gateway_position_stream_from_config``
        (built from the public client configuration). By default it comes from
        the Store's position subscription (``subscribe_account_positions``),
        so a read never queries the provider; for a Gateway pass
        ``GatewayAccountPositionStream(...).report``. ``"store_snapshot"``
        reads a projected snapshot per query but remains unverified until the
        identity and completeness evidence is retained. ``unreconciled=True``
        explicitly accepts a ledger-only book: positions, but never strategy
        cash or value.

        ``event_cursor_path`` opts in to at-least-once delivery of this
        strategy's ledger events to ``Strategy.notify_ledger_event`` with a
        durable cursor at that path (see ``_btapi_strategy_events``); events
        left undelivered by a crash are delivered during this call.
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
        if unreconciled is not True:
            store = getattr(self, "store", None)
            if account_positions is None:
                subscribe = getattr(store, "subscribe_account_positions", None)
                if not callable(subscribe) or not getattr(store, "_sdk_mode", False):
                    raise ValueError(
                        "a strategy ledger needs account positions to reconcile with: use an "
                        "SDK-mode Store, pass account_positions, or unreconciled=True"
                    )
                account_positions = subscribe(ledger.account_ref).report
            elif account_positions == "store_snapshot":
                if not getattr(store, "_sdk_mode", False):
                    raise ValueError("store snapshots need an SDK-mode Store")
                account_ref = ledger.account_ref

                def account_positions():
                    return store_account_position_report(store, account_ref)

            elif callable(getattr(account_positions, "report", None)):
                # A subscription object (GatewayAccountPositionStream,
                # StreamedAccountPositions, a Store subscription): use its report.
                account_positions = account_positions.report
            elif not callable(account_positions):
                raise ValueError("account_positions must return an AccountPositionReport")
        elif account_positions is not None:
            raise ValueError("unreconciled=True cannot be combined with account_positions")
        reader = ledger.reader(strategy_ref, account_positions=account_positions)
        view = self.bind_direct_strategy_account_book(strategy, reader)
        self._direct_strategy_ledger = ledger
        if event_cursor_path is not None:
            self._bind_strategy_ledger_events(strategy, ledger, strategy_ref, event_cursor_path)
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
        if getattr(self, "_account_owner_fence", None) is None:
            # A ledger-gated order requires a local owner-generation check.
            # This check does not establish account-wide single-writer authority.
            return (
                "account_owner_unbound",
                "Orders on a ledger-gated account require bind_account_owner",
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
            return
        self._deliver_after_ledger_update(order)

    def _apply_ledger_status(self, ledger, intent_id, order) -> None:
        status = order.status
        executed = abs(float(getattr(order.executed, "size", 0) or 0))
        if executed > 0:
            cumulative = Decimal(str(executed))
            average = _decimal(getattr(order.executed, "price", None))
            fees = dict(self._order_info_get(order, "provider_fee_totals") or {})
            first = sorted(fees)[:1]
            ledger.apply_execution(
                intent_id,
                cumulative_quantity=cumulative,
                average_price=average,
                fee=fees[first[0]] if first else None,
                fee_currency=first[0] if first else None,
            )
            for currency in sorted(fees)[1:]:
                ledger.apply_execution(
                    intent_id,
                    cumulative_quantity=cumulative,
                    average_price=average,
                    fee=fees[currency],
                    fee_currency=currency,
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
