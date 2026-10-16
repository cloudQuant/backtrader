from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.sizers import StrategyAccountBookPercentSizer


class _Book:
    strategy_ref = "strategy.alpha"
    account_ref = "account.shared"

    def __init__(self, *, cash=Decimal("200"), position=Decimal("1.25")):
        self.cash = cash
        self.position = position
        self.cash_reads = []
        self.position_reads = []

    def getcash(self, *, currency):
        self.cash_reads.append(currency)
        return self.cash

    def getposition(self, data):
        self.position_reads.append(data)
        return SimpleNamespace(size=float(self.position))


class _Broker:
    def getcash(self):
        raise AssertionError("strategy-book sizing must not read aggregate cash")


class _Data:
    _name = "BTC-USDT"

    class _Close:
        def __getitem__(self, index):
            assert index == 0
            return 20.0

    close = _Close()


def _sizer(
    *,
    book=None,
    strategy_ref="strategy.alpha",
    account_ref="account.shared",
    currency="USDT",
    retint=False,
):
    strategy = SimpleNamespace(
        p=SimpleNamespace(strategy_ref=strategy_ref, account_ref=account_ref),
        account_book=book,
    )
    options = {"percents": 50, "retint": retint}
    if currency is not None:
        options["currency"] = currency
    sizer = StrategyAccountBookPercentSizer(**options)
    sizer.set(strategy, _Broker())
    return sizer


def test_buy_uses_strategy_cash_in_explicit_currency_not_broker_cash():
    book = _Book(cash=Decimal("200"))
    sizer = _sizer(book=book)
    data = _Data()

    assert sizer.getsizing(data, True) == pytest.approx(5.0)
    assert book.cash_reads == ["USDT"]
    assert book.position_reads == [data]


def test_sell_size_is_capped_at_strategy_owned_position():
    book = _Book(position=Decimal("1.25"))
    sizer = _sizer(book=book)

    assert sizer.getsizing(_Data(), False) == pytest.approx(1.25)
    assert book.cash_reads == []
    assert len(book.position_reads) == 1


@pytest.mark.parametrize("isbuy", [True, False])
def test_short_position_fails_closed_for_either_order_side(isbuy):
    book = _Book(position=Decimal("-1.25"))
    sizer = _sizer(book=book)

    assert sizer.getsizing(_Data(), isbuy) == 0
    assert len(book.position_reads) == 1
    assert book.cash_reads == []


def test_missing_or_mismatched_owner_view_fails_closed():
    with pytest.raises(ValueError, match="strategy-owned account book"):
        _sizer().getsizing(_Data(), True)

    book = _Book()
    sizer = _sizer(book=book, strategy_ref="strategy.beta")
    with pytest.raises(ValueError, match="strategy-owned account book"):
        sizer.getsizing(_Data(), True)

    with pytest.raises(ValueError, match="explicit account-book cash currency"):
        _sizer(book=_Book(), currency=None).getsizing(_Data(), True)


def test_zero_cash_and_nonpositive_price_do_not_create_size():
    book = _Book(cash=Decimal("0"))
    assert _sizer(book=book).getsizing(_Data(), True) == 0

    class _ZeroData:
        class _Close:
            def __getitem__(self, index):
                return 0.0

        close = _Close()

    assert _sizer(book=book).getsizing(_ZeroData(), True) == 0


def test_integer_sizing_truncates_inside_owner_cash_limit():
    book = _Book(cash=Decimal("200"))
    sizer = _sizer(book=book, retint=True)

    assert sizer.getsizing(_Data(), True) == 5
