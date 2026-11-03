"""Lazy access to shared strategy financial-scope checks."""


def observe(observer, field, reader, *args, **kwargs):
    """Expose unavailable scoped data as NaN with its finite reason code.

    Unbound strategies and non-account-book exceptions retain their previous
    behaviour. Consumers can inspect ``_strategy_financial_unavailable``.
    """
    try:
        value = reader(*args, **kwargs)
    except Exception as error:
        try:
            bound = vars(observer._owner).get("account_book") is not None
        except TypeError:
            bound = False
        if not bound:
            raise
        from ..service.service_strategy_account_book import ServiceStrategyAccountBookError

        if not isinstance(error, ServiceStrategyAccountBookError):
            raise
        reasons = getattr(observer, "_strategy_financial_unavailable", None)
        if reasons is None:
            reasons = observer._strategy_financial_unavailable = {}
        reasons[field] = error.code
        return float("nan")
    reasons = getattr(observer, "_strategy_financial_unavailable", None)
    if reasons is not None:
        reasons.pop(field, None)
    return value


def _unavailable_if_bound(strategy, field):
    from ..analyzers._strategy_scope import _book, _unavailable

    if _book(strategy) is not None:
        reasons = vars(strategy).get("_strategy_financial_unavailable")
        reason = reasons.get(field) if isinstance(reasons, dict) else None
        _unavailable(reason or "STRATEGY_FINANCIAL_CONTEXT_UNAVAILABLE")


def portfolio_value(strategy, *, fund=False):
    from ..analyzers._strategy_scope import portfolio_value as read_value

    _unavailable_if_bound(strategy, "fundvalue" if fund else "value")
    return read_value(strategy, fund=fund)


def cash_value(strategy):
    from ..analyzers._strategy_scope import cash_value as read_cash

    _unavailable_if_bound(strategy, "cash")
    return read_cash(strategy)


def fund_shares(strategy):
    from ..analyzers._strategy_scope import fund_shares as read_shares

    return read_shares(strategy)
