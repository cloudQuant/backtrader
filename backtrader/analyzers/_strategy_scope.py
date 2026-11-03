"""Financial reads for built-in strategy analyzers and observers.

Broker getters and fund notifications are account-scoped.  A strategy with a
bound account book must not consume them as its own financial data.
"""


def _book(strategy):
    # Strategy._strategy_account_book stores the binding in the strategy's
    # instance dictionary. Checking it first avoids mistaking an arbitrary
    # mock's dynamically generated attributes for an account-book binding.
    try:
        bound = vars(strategy).get("account_book")
    except TypeError:
        bound = None
    if bound is None:
        return None
    lookup = getattr(strategy, "_strategy_account_book", None)
    if not callable(lookup):
        _unavailable("STRATEGY_ACCOUNT_BOOK_UNAVAILABLE")
    result = lookup()
    if result is None:
        _unavailable("STRATEGY_ACCOUNT_BOOK_UNAVAILABLE")
    return result


def _unavailable(code):
    from ..service.service_strategy_account_book import ServiceStrategyAccountBookError

    raise ServiceStrategyAccountBookError(code)


def portfolio_value(strategy, *, fund=False, broker=None):
    book = _book(strategy)
    if book is not None:
        if fund:
            _unavailable("STRATEGY_FUND_VALUE_UNAVAILABLE")
        return book.getvalue()
    broker = broker if broker is not None else strategy.broker
    return broker.fundvalue if fund else broker.getvalue()


def cash_value(strategy, *, alias=False):
    book = _book(strategy)
    if book is not None:
        # The book requires an explicit currency; these consumers have no
        # currency parameter and must not guess one or perform implicit FX.
        return book.getcash()
    return strategy.broker.get_cash() if alias else strategy.broker.getcash()


def position_value(strategy, data):
    book = _book(strategy)
    if book is not None:
        # A validated zero position needs no mark. Nonzero position valuation
        # has no strategy-scoped public contract yet.
        if book.getposition(data).size == 0:
            return 0.0
        _unavailable("STRATEGY_POSITION_VALUE_UNAVAILABLE")
    return strategy.broker.get_value([data])


def _sanitized_notification(strategy, field, value, consumer):
    # The Strategy owns the snapshot and cleans financial notifications.
    # Re-reading a book here could mix different cuts and turn a sanitized
    # unavailable value into an unproven finite one.
    from ..mathsupport import is_finite_real

    reasons = vars(strategy).get("_strategy_financial_unavailable")
    if not isinstance(reasons, dict):
        reason = "STRATEGY_FINANCIAL_CONTEXT_UNAVAILABLE"
    else:
        reason = reasons.get(field)
        if reason is None and not is_finite_real(value):
            reason = "STRATEGY_FINANCIAL_INPUT_UNAVAILABLE"
    target_field = "cash" if field == "cash" else "value"
    if reason is not None:
        if consumer is not None:
            own = vars(consumer).setdefault("_strategy_financial_unavailable", {})
            own[target_field] = reason
        return float("nan")
    if consumer is not None:
        own = vars(consumer).get("_strategy_financial_unavailable")
        if own is not None:
            own.pop(target_field, None)
    return value


def notified_value(strategy, value, fundvalue, *, fund=False, consumer=None):
    value = fundvalue if fund else value
    if _book(strategy) is not None:
        return _sanitized_notification(strategy, "fundvalue" if fund else "value", value, consumer)
    _clear_field(consumer, "value")
    return value


def notified_cash(strategy, cash, *, consumer=None):
    if _book(strategy) is not None:
        return _sanitized_notification(strategy, "cash", cash, consumer)
    _clear_field(consumer, "cash")
    return cash


def portfolio_observation(strategy, *, fund=False, consumer=None, broker=None):
    """Read an analyzer's initial/final value without interrupting on GAP."""
    book = _book(strategy)
    if book is not None:
        # There is not yet a source-bound strategy valuation for this read.
        # A finite independently read book value cannot prove a common cut.
        return _sanitized_notification(
            strategy, "fundvalue" if fund else "value", float("nan"), consumer
        )
    _clear_field(consumer, "value")
    broker = broker if broker is not None else strategy.broker
    return broker.fundvalue if fund else broker.getvalue()


def scoped_missing_input(strategy, *values):
    """Missing financial inputs in a bound book are not numerical zero."""
    from ..mathsupport import is_finite_real

    return _book(strategy) is not None and any(not is_finite_real(value) for value in values)


def record_result_gap(consumer):
    reasons = vars(consumer).setdefault("_strategy_financial_unavailable", {})
    reasons["result"] = (
        reasons.get("value") or reasons.get("cash") or "STRATEGY_FINANCIAL_INPUT_UNAVAILABLE"
    )


def clear_result_gap(consumer):
    _clear_field(consumer, "result")


def _clear_field(consumer, field):
    if consumer is None:
        return
    reasons = vars(consumer).get("_strategy_financial_unavailable")
    if reasons is not None:
        reasons.pop(field, None)


def fund_shares(strategy):
    if _book(strategy) is not None:
        _unavailable("STRATEGY_FUND_SHARES_UNAVAILABLE")
    return strategy.broker.fundshares
