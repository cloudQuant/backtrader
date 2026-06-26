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
    """Verify LiveStoreBase ABC enforcement.

    Groups the contract tests for :class:`backtrader.stores.livestore.LiveStoreBase`:
    the base itself cannot be instantiated, incomplete subclasses are
    rejected, complete subclasses work, the ``start`` signature accepts
    optional data/broker arguments, and the set of abstract methods is
    exactly the expected nine.
    """

    def test_cannot_instantiate_abstract(self):
        """Instantiating :class:`LiveStoreBase` directly must raise ``TypeError``.

        The base class declares abstract methods, so Python's ABC
        machinery refuses to construct an instance. The expected error
        message contains ``"abstract method"``.
        """
        with pytest.raises(TypeError, match="abstract method"):
            LiveStoreBase()

    def test_incomplete_subclass_raises(self):
        """A subclass missing abstract methods must also fail to instantiate.

        Defines ``IncompleteStore`` with only ``start`` and ``stop``
        implemented; ``is_connected``, ``getbroker``, ``getdata``,
        ``get_cash``, ``get_value``, ``get_balance`` and
        ``get_positions`` are intentionally omitted. Constructing the
        class must raise ``TypeError`` mentioning ``"abstract method"``.
        """

        class IncompleteStore(LiveStoreBase):
            """Test stub that implements only ``start`` and ``stop``.

            Intentionally omits the rest of the abstract methods so the
            instantiation check can verify the ABC rejects it.
            """

            def start(self, data=None, broker=None):
                """No-op ``start`` to satisfy the partial contract."""
                pass

            def stop(self):
                """No-op ``stop`` to satisfy the partial contract."""
                pass

            # Missing: is_connected, getbroker, getdata, get_cash, get_value,
            #          get_balance, get_positions

        with pytest.raises(TypeError, match="abstract method"):
            IncompleteStore()

    def test_complete_subclass_works(self):
        """A subclass implementing every abstract method must be instantiable.

        ``CompleteStore`` provides no-op implementations for every
        abstract method on :class:`LiveStoreBase`. After construction
        the test asserts that ``is_connected`` returns ``True`` and
        the helpers return the expected sentinel values.
        """

        class CompleteStore(LiveStoreBase):
            """Test stub that implements every abstract method on the base.

            The body of each method is a no-op or returns a sentinel
            value. The test only needs the class to be instantiable
            and the methods to be callable.
            """

            def start(self, data=None, broker=None):
                """No-op ``start`` satisfying the contract."""
                pass

            def stop(self):
                """No-op ``stop`` satisfying the contract."""
                pass

            @property
            def is_connected(self) -> bool:
                """Return ``True`` so the assertion sees a connected store."""
                return True

            def getbroker(self, *args, **kwargs):
                """Return ``None`` for the broker lookup."""
                return None

            def getdata(self, *args, **kwargs):
                """Return ``None`` for the data feed lookup."""
                return None

            def get_cash(self) -> float:
                """Return ``0.0`` as the cash balance."""
                return 0.0

            def get_value(self) -> float:
                """Return ``0.0`` as the portfolio value."""
                return 0.0

            def get_balance(self):
                """No-op balance refresh."""
                pass

            def get_positions(self) -> list:
                """Return an empty list of positions."""
                return []

        store = CompleteStore()
        assert store.is_connected is True
        assert store.get_cash() == 0.0
        assert store.get_positions() == []

    def test_start_accepts_data_and_broker(self):
        """``start(data=None, broker=None)`` must accept both as optional args.

        ``MinimalStore`` records the data and broker instances it was
        started with. The test starts the store with no arguments,
        asserts both slots are ``None``, then restarts it with sentinel
        objects and asserts they were captured verbatim.
        """

        class MinimalStore(LiveStoreBase):
            """Test stub that records the data/broker passed to ``start``.

            All other abstract methods are stubbed out. The test
            inspects the ``started_data`` / ``started_broker`` slots
            to verify the start signature propagates the arguments
            through unchanged.
            """

            def __init__(self):
                """Initialize the recording slots to ``None``."""
                self.started_data = None
                self.started_broker = None

            def start(self, data=None, broker=None):
                """Record the data and broker arguments for later assertion."""
                self.started_data = data
                self.started_broker = broker

            def stop(self):
                """No-op ``stop`` satisfying the contract."""
                pass

            @property
            def is_connected(self) -> bool:
                """Return ``False``; this stub never connects."""
                return False

            def getbroker(self, *args, **kwargs):
                """Return ``None`` for the broker lookup."""
                return None

            def getdata(self, *args, **kwargs):
                """Return ``None`` for the data feed lookup."""
                return None

            def get_cash(self) -> float:
                """Return ``0.0`` as the cash balance."""
                return 0.0

            def get_value(self) -> float:
                """Return ``0.0`` as the portfolio value."""
                return 0.0

            def get_balance(self):
                """No-op balance refresh."""
                pass

            def get_positions(self) -> list:
                """Return an empty list of positions."""
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
        """The set of abstract methods must match the documented contract.

        Reads ``LiveStoreBase.__abstractmethods__`` and asserts it is
        exactly ``{"start", "stop", "is_connected", "getbroker",
        "getdata", "get_cash", "get_value", "get_balance",
        "get_positions"}``. If anyone adds or removes an abstract
        method, this test breaks the contract documentation.
        """
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
    """Verify :class:`BtApiStore` implements every abstract method.

    Confirms that :class:`backtrader.stores.btapistore.BtApiStore` is
    a proper subclass of :class:`LiveStoreBase` and that none of the
    abstract methods are left unimplemented. This guards against
    accidental signature drift between the contract and the
    production store.
    """

    def test_btapistore_is_livestorebase_subclass(self):
        """``BtApiStore`` must be a subclass of ``LiveStoreBase``.

        The test imports :class:`BtApiStore` lazily to avoid pulling
        in the (heavy) btapi dependency at collection time and asserts
        the inheritance relationship.
        """
        from backtrader.stores.btapistore import BtApiStore

        assert issubclass(BtApiStore, LiveStoreBase)

    def test_btapistore_implements_all_abstract_methods(self):
        """``BtApiStore`` must implement every abstract method.

        Iterates over ``LiveStoreBase.__abstractmethods__`` and asserts
        each name is present on the :class:`BtApiStore` class. The
        failure message names the missing method for fast diagnosis.
        """
        from backtrader.stores.btapistore import BtApiStore

        for method_name in LiveStoreBase.__abstractmethods__:
            assert hasattr(BtApiStore, method_name), (
                f"BtApiStore missing implementation for {method_name}"
            )
