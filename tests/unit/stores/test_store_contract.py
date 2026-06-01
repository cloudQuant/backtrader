#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Store contract tests for Iteration 4 - T09.

Verify:
1. LiveStoreBase ABC enforces required abstract methods
2. BtApiStore satisfies the LiveStoreBase contract
3. Incomplete subclasses cannot be instantiated
"""

import pytest

from backtrader.stores.livestore import LiveStoreBase


class TestLiveStoreBaseContract:
    """Verify LiveStoreBase ABC enforcement."""

    def test_cannot_instantiate_abstract(self):
        """LiveStoreBase itself cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract method"):
            LiveStoreBase()

    def test_incomplete_subclass_raises(self):
        """Subclass missing abstract methods cannot be instantiated."""

        class IncompleteStore(LiveStoreBase):
            def start(self, data=None, broker=None):
                pass

            def stop(self):
                pass

            # Missing: is_connected, getbroker, getdata, get_cash, get_value,
            #          get_balance, get_positions

        with pytest.raises(TypeError, match="abstract method"):
            IncompleteStore()

    def test_complete_subclass_works(self):
        """Subclass implementing all abstract methods can be instantiated."""

        class CompleteStore(LiveStoreBase):
            def start(self, data=None, broker=None):
                pass

            def stop(self):
                pass

            @property
            def is_connected(self) -> bool:
                return True

            def getbroker(self, *args, **kwargs):
                return None

            def getdata(self, *args, **kwargs):
                return None

            def get_cash(self) -> float:
                return 0.0

            def get_value(self) -> float:
                return 0.0

            def get_balance(self):
                pass

            def get_positions(self) -> list:
                return []

        store = CompleteStore()
        assert store.is_connected is True
        assert store.get_cash() == 0.0
        assert store.get_positions() == []

    def test_start_accepts_data_and_broker(self):
        """start() signature accepts optional data and broker."""

        class MinimalStore(LiveStoreBase):
            def __init__(self):
                self.started_data = None
                self.started_broker = None

            def start(self, data=None, broker=None):
                self.started_data = data
                self.started_broker = broker

            def stop(self):
                pass

            @property
            def is_connected(self) -> bool:
                return False

            def getbroker(self, *args, **kwargs):
                return None

            def getdata(self, *args, **kwargs):
                return None

            def get_cash(self) -> float:
                return 0.0

            def get_value(self) -> float:
                return 0.0

            def get_balance(self):
                pass

            def get_positions(self) -> list:
                return []

        store = MinimalStore()
        store.start()
        assert store.started_data is None
        assert store.started_broker is None

        sentinel_data = object()
        sentinel_broker = object()
        store.start(data=sentinel_data, broker=sentinel_broker)
        assert store.started_data is sentinel_data
        assert store.started_broker is sentinel_broker

    def test_required_abstract_methods(self):
        """Verify the expected set of abstract methods."""
        abstract_methods = LiveStoreBase.__abstractmethods__
        expected = {
            "start",
            "stop",
            "is_connected",
            "getbroker",
            "getdata",
            "get_cash",
            "get_value",
            "get_balance",
            "get_positions",
        }
        assert abstract_methods == expected


class TestBtApiStoreSatisfiesContract:
    """Verify BtApiStore implements all LiveStoreBase abstract methods."""

    def test_btapistore_is_livestorebase_subclass(self):
        """BtApiStore inherits from LiveStoreBase."""
        from backtrader.stores.btapistore import BtApiStore

        assert issubclass(BtApiStore, LiveStoreBase)

    def test_btapistore_implements_all_abstract_methods(self):
        """BtApiStore has implementations for every abstract method."""
        from backtrader.stores.btapistore import BtApiStore

        for method_name in LiveStoreBase.__abstractmethods__:
            assert hasattr(BtApiStore, method_name), (
                f"BtApiStore missing implementation for {method_name}"
            )
