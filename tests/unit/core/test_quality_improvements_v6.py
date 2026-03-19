"""Tests for code quality improvements v6.

Covers:
- Trade: getdataname/open_datetime/close_datetime safe when data is None
- Position: clone() preserves datetime/adjbase/updt state
- mathsupport: average() handles negative denominator edge case
- Store: put_notification/get_notifications safe when notifs is None
"""

import collections
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backtrader.mathsupport import average, standarddev, variance
from backtrader.position import Position
from backtrader.store import SingletonMixin, Store, StoreParams
from backtrader.trade import Trade


# ===========================================================================
# Trade defensive guards tests
# ===========================================================================


class TestTradeDefensiveGuards:
    """Tests for Trade methods when data is None."""

    def _make_trade_no_data(self):
        """Create a Trade with data=None for testing."""
        obj = object.__new__(Trade)
        obj.ref = 1
        obj.data = None
        obj.tradeid = 0
        obj.size = 0
        obj.price = 0.0
        obj.value = 0.0
        obj.commission = 0.0
        obj.pnl = 0.0
        obj.pnlcomm = 0.0
        obj.justopened = False
        obj.isopen = False
        obj.isclosed = False
        obj.baropen = 0
        obj.dtopen = 0.0
        obj.barclose = 0
        obj.dtclose = 0.0
        obj.barlen = 0
        obj.historyon = False
        obj.history = None
        obj.status = 0
        return obj

    def test_getdataname_returns_empty_when_data_none(self):
        """getdataname() should return empty string when data is None."""
        trade = self._make_trade_no_data()
        assert trade.getdataname() == ""

    def test_getdataname_returns_empty_when_data_has_no_name(self):
        """getdataname() should return empty string when data has no _name."""
        trade = self._make_trade_no_data()
        trade.data = object()  # object with no _name attribute
        assert trade.getdataname() == ""

    def test_getdataname_returns_name_when_data_has_name(self):
        """getdataname() should return _name when data has it."""
        trade = self._make_trade_no_data()

        class MockData:
            _name = "test_data"

        trade.data = MockData()
        assert trade.getdataname() == "test_data"

    def test_open_datetime_returns_none_when_data_none(self):
        """open_datetime() should return None when data is None."""
        trade = self._make_trade_no_data()
        assert trade.open_datetime() is None

    def test_close_datetime_returns_none_when_data_none(self):
        """close_datetime() should return None when data is None."""
        trade = self._make_trade_no_data()
        assert trade.close_datetime() is None


# ===========================================================================
# Position clone() tests
# ===========================================================================


class TestPositionClone:
    """Tests for Position.clone() preserving full state."""

    def test_clone_preserves_size_and_price(self):
        """clone() should preserve size and price."""
        pos = Position(size=100, price=50.0)
        cloned = pos.clone()
        assert cloned.size == 100
        assert cloned.price == 50.0

    def test_clone_preserves_adjbase(self):
        """clone() should preserve adjbase."""
        pos = Position(size=100, price=50.0)
        pos.adjbase = 55.0
        cloned = pos.clone()
        assert cloned.adjbase == 55.0

    def test_clone_preserves_datetime(self):
        """clone() should preserve datetime."""
        pos = Position(size=100, price=50.0)
        pos.datetime = 12345.678
        cloned = pos.clone()
        assert cloned.datetime == 12345.678

    def test_clone_preserves_updt(self):
        """clone() should preserve updt."""
        pos = Position(size=100, price=50.0)
        pos.updt = 99999.0
        cloned = pos.clone()
        assert cloned.updt == 99999.0

    def test_clone_creates_independent_copy(self):
        """Modifying clone should not affect original."""
        pos = Position(size=100, price=50.0)
        pos.adjbase = 55.0
        cloned = pos.clone()
        cloned.adjbase = 60.0
        assert pos.adjbase == 55.0
        assert cloned.adjbase == 60.0

    def test_clone_empty_position(self):
        """clone() should work with empty position."""
        pos = Position()
        cloned = pos.clone()
        assert cloned.size == 0
        assert cloned.price == 0.0


# ===========================================================================
# mathsupport.average() edge case tests
# ===========================================================================


class TestAverageEdgeCases:
    """Tests for average() edge cases."""

    def test_average_empty_list(self):
        """average([]) should return 0.0."""
        assert average([]) == 0.0

    def test_average_empty_list_with_bessel(self):
        """average([], bessel=True) should return 0.0, not -0.0."""
        result = average([], bessel=True)
        assert result == 0.0
        # Ensure it's not negative zero
        assert str(result) == "0.0"

    def test_average_single_element_with_bessel(self):
        """average([x], bessel=True) should return 0.0 (denominator would be 0)."""
        result = average([5.0], bessel=True)
        assert result == 0.0

    def test_average_normal_case(self):
        """average() should work correctly for normal inputs."""
        result = average([1.0, 2.0, 3.0])
        assert abs(result - 2.0) < 1e-10

    def test_average_with_bessel(self):
        """average() with bessel should divide by n-1."""
        result = average([2.0, 4.0], bessel=True)
        # sum = 6.0, n-1 = 1, result = 6.0
        assert abs(result - 6.0) < 1e-10

    def test_variance_empty_list(self):
        """variance([]) should not crash and return empty list."""
        result = variance([])
        assert result == []

    def test_standarddev_empty_list(self):
        """standarddev([]) should not crash."""
        result = standarddev([])
        assert result == 0.0


# ===========================================================================
# Store notification safety tests
# ===========================================================================


class TestStoreNotificationSafety:
    """Tests for Store notification methods when notifs is None."""

    def _make_raw_store(self):
        """Create a Store-like object with notifs=None for testing."""
        # We can't easily instantiate Store directly due to singleton,
        # so we test the methods via a simple mock
        class TestStore:
            notifs = None

            put_notification = Store.put_notification
            get_notifications = Store.get_notifications

        return TestStore()

    def test_get_notifications_returns_empty_when_notifs_none(self):
        """get_notifications() should return [] when notifs is None."""
        store = self._make_raw_store()
        result = store.get_notifications()
        assert result == []

    def test_put_notification_initializes_notifs_when_none(self):
        """put_notification() should initialize notifs when None."""
        store = self._make_raw_store()
        store.put_notification("test_msg", "arg1", key="val")
        assert store.notifs is not None
        assert len(store.notifs) == 1
        msg, args, kwargs = store.notifs[0]
        assert msg == "test_msg"
        assert args == ("arg1",)
        assert kwargs == {"key": "val"}

    def test_put_then_get_notifications(self):
        """put_notification() followed by get_notifications() should work."""
        store = self._make_raw_store()
        store.put_notification("msg1")
        store.put_notification("msg2")
        notifs = store.get_notifications()
        assert len(notifs) == 2
        assert notifs[0][0] == "msg1"
        assert notifs[1][0] == "msg2"

    def test_get_notifications_clears_queue(self):
        """get_notifications() should drain the queue."""
        store = self._make_raw_store()
        store.put_notification("msg1")
        notifs1 = store.get_notifications()
        assert len(notifs1) == 1
        notifs2 = store.get_notifications()
        assert len(notifs2) == 0


# ===========================================================================
# StoreParams tests
# ===========================================================================


class TestStoreParams:
    """Tests for StoreParams parameter initialization."""

    def test_params_from_tuple(self):
        """StoreParams should initialize params from tuple."""

        class MyStore(StoreParams):
            params = (("key1", "val1"), ("key2", 42))

        store = MyStore()
        assert store.p.key1 == "val1"
        assert store.p.key2 == 42

    def test_params_from_string(self):
        """StoreParams should handle string-only params."""

        class MyStore(StoreParams):
            params = ("simple_param",)

        store = MyStore()
        assert store.p.simple_param is None

    def test_empty_params(self):
        """StoreParams should handle empty params."""

        class MyStore(StoreParams):
            params = ()

        store = MyStore()
        assert store.p is not None


# ===========================================================================
# SingletonMixin tests
# ===========================================================================


class TestSingletonMixin:
    """Tests for SingletonMixin behavior."""

    def test_singleton_returns_same_instance(self):
        """Singleton should return the same instance."""

        class MySingleton(SingletonMixin):
            pass

        a = MySingleton()
        b = MySingleton()
        assert a is b

    def test_singleton_subclasses_are_independent(self):
        """Different subclasses should have independent singletons."""

        class SingletonA(SingletonMixin):
            pass

        class SingletonB(SingletonMixin):
            pass

        a = SingletonA()
        b = SingletonB()
        assert a is not b
        assert type(a) is SingletonA
        assert type(b) is SingletonB


# ===========================================================================
# Position edge case tests
# ===========================================================================


class TestPositionEdgeCases:
    """Additional edge case tests for Position."""

    def test_position_bool_false_when_empty(self):
        """Empty position should be falsy."""
        pos = Position()
        assert not bool(pos)

    def test_position_bool_true_when_has_size(self):
        """Position with size should be truthy."""
        pos = Position(size=100, price=50.0)
        assert bool(pos)

    def test_position_len_returns_abs_size(self):
        """len(position) should return absolute size."""
        pos = Position(size=-50, price=10.0)
        assert len(pos) == 50

    def test_position_repr(self):
        """Position repr should be informative."""
        pos = Position(size=100, price=50.0)
        r = repr(pos)
        assert "100" in r
        assert "50" in r

    def test_pseudoupdate_does_not_modify_original(self):
        """pseudoupdate should not modify the original position."""
        pos = Position(size=100, price=50.0)
        original_size = pos.size
        original_price = pos.price
        # pseudoupdate returns the result of update(), which is a tuple
        result = pos.pseudoupdate(size=50, price=55.0)
        assert pos.size == original_size
        assert pos.price == original_price
        # Result is a tuple (size, price, opened, closed)
        assert isinstance(result, tuple)

    def test_position_fix(self):
        """fix() should update position size and price."""
        pos = Position(size=100, price=50.0)
        same = pos.fix(size=100, price=55.0)
        assert pos.price == 55.0
        assert pos.size == 100
        assert same is True  # size didn't change

    def test_position_fix_changes_size(self):
        """fix() should return False when size changes."""
        pos = Position(size=100, price=50.0)
        same = pos.fix(size=200, price=55.0)
        assert pos.size == 200
        assert pos.price == 55.0
        assert same is False
