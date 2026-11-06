"""Invalid order fields are refused locally, never raised into strategy code (iteration 62).

SimNow 2026-11-06: example strategies priced orders from a feed line that was not
written yet (``close[0] == 0``): a buy went out at 2.0 and a sell at -2.0 made the
SDK ``OrderRequest`` raise ``ValueError`` out of ``broker.sell()``, ending the run.
UNIT/FAKE.
"""

import math
import warnings

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers import _btapi_direct_mode as direct_mode


@pytest.fixture
def broker(env):
    return env.start(first_init=True)


def _limit(env, broker, side, price, size=1):
    method = broker.buy if side == "buy" else broker.sell
    return method(env.strategy, env.feed, size, price=price, exectype=bt.Order.Limit, offset="open")


@pytest.mark.parametrize("price", [-2.0, 0.0, math.nan, math.inf, None])
def test_non_positive_or_non_finite_limit_price_is_refused_locally(env, broker, price):
    order = _limit(env, broker, "sell", price)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "limit_price_invalid"
    assert env.api.place_calls == []


def test_zero_size_is_refused_locally(env, broker):
    order = _limit(env, broker, "buy", 3500.0, size=0)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "order_size_invalid"
    assert env.api.place_calls == []


def test_a_request_the_sdk_cannot_represent_is_a_local_rejection(env, broker, monkeypatch):
    def refuse(self, order, meta):
        raise ValueError("quantity must be finite and > 0")

    monkeypatch.setattr(direct_mode.BtApiDirectModeMixin, "_direct_request", refuse)
    order = _limit(env, broker, "buy", 3500.0)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"].startswith("request_unrepresentable:")
    assert env.api.place_calls == []
    # nothing was reserved: the next valid order still gets the next local sequence
    monkeypatch.undo()
    later = _limit(env, broker, "buy", 3500.0)
    assert later.status == bt.Order.Submitted
    assert len(env.api.place_calls) == 1


class _OneElementPrice:
    """A price ``float()`` accepts but whose text is no decimal literal.

    Like a one-element numpy array or pandas Series (``str`` gives ``[3500.]``):
    ``Decimal(str(price))`` raises ``decimal.InvalidOperation``, an
    ``ArithmeticError`` rather than a ``ValueError``.
    """

    def __float__(self):
        return 3500.0

    def __str__(self):
        return "[3500.]"


def test_a_price_whose_text_is_not_a_decimal_is_a_local_rejection(env, broker):
    order = _limit(env, broker, "buy", _OneElementPrice())
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"].startswith("request_unrepresentable:")
    assert env.api.place_calls == []


def test_a_numpy_one_element_price_is_a_local_rejection(env, broker):
    np = pytest.importorskip("numpy")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # numpy ndim>0 -> scalar
        order = _limit(env, broker, "buy", np.array([3500.0]))
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"].startswith("request_unrepresentable:")
    assert env.api.place_calls == []


def test_a_valid_limit_price_is_still_sent(env, broker):
    order = _limit(env, broker, "buy", 3500.0)
    assert order.status == bt.Order.Submitted
    assert env.api.place_calls[-1].request.price == pytest.approx(3500.0)
