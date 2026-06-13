"""Predefined Cerebro profiles for common live/backtest setups.

Provides :class:`LiveProfile`, a declarative description of a run (mode,
strategy, data source, broker, frequency) plus :func:`build_cerebro` to turn a
profile into a wired-up :class:`~backtrader.cerebro.Cerebro` instance. Keeps the
boilerplate of selecting broker/data classes for backtest vs live in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from .brokers.bbroker import BackBroker
from .cerebro import Cerebro
from .feeds.btcsv import BacktraderCSVData
from .stores.btapistore import BtApiStore


@dataclass
class LiveProfile:
    """Declarative description of a single Cerebro run.

    Captures the run mode (``backtest`` or ``live``), the strategy
    class plus its args/kwargs, the data source description
    (``dataname``, ``symbols`` or a custom ``data_factory``), the
    broker construction knobs and the optional live store
    configuration. ``__post_init__`` normalizes the inputs and runs
    a set of consistency checks so that :func:`build_cerebro` can
    produce a fully wired Cerebro without further validation.

    Attributes:
        mode: ``"backtest"`` or ``"live"``. Validated in
            ``__post_init__``.
        strategy: The strategy class to register on the Cerebro.
        frequency: One of ``"lowfreq"``, ``"midfreq"`` or ``"hft"``.
            Used by downstream broker/feed wiring to pick the right
            defaults.
        dataname: Optional single-source identifier (e.g. CSV path).
        symbols: Optional tuple of symbol identifiers for multi-feed
            runs.
        strategy_args: Positional arguments forwarded to the
            strategy constructor.
        strategy_kwargs: Keyword arguments forwarded to the strategy
            constructor.
        data_cls: Optional explicit data feed class.
        data_factory: Optional callable returning one or more
            pre-built data instances. Mutually exclusive with
            ``dataname``/``symbols``.
        data_kwargs: Keyword arguments forwarded to the data feed
            constructor.
        data_name: Optional explicit name attached to the (single)
            data feed.
        broker_cls: Optional explicit broker class.
        broker_factory: Optional callable returning a broker instance.
        broker_kwargs: Keyword arguments forwarded to the broker
            constructor.
        store_factory: Optional callable returning a live store
            instance.
        store_kwargs: Keyword arguments forwarded to the live store
            constructor.
        store_provider: Live-store provider name (``"btapi"`` by
            default).
        cerebro_kwargs: Keyword arguments forwarded to the
            :class:`Cerebro` constructor.
    """

    mode: str
    strategy: type
    frequency: str = "lowfreq"
    dataname: Optional[str] = None
    symbols: Tuple[str, ...] = ()
    strategy_args: Tuple[Any, ...] = ()
    strategy_kwargs: Dict[str, Any] = field(default_factory=dict)
    data_cls: Optional[type] = None
    data_factory: Optional[Callable[[], Any]] = None
    data_kwargs: Dict[str, Any] = field(default_factory=dict)
    data_name: Optional[str] = None
    broker_cls: Optional[type] = None
    broker_factory: Optional[Callable[..., Any]] = None
    broker_kwargs: Dict[str, Any] = field(default_factory=dict)
    store_factory: Optional[Callable[[], Any]] = None
    store_kwargs: Dict[str, Any] = field(default_factory=dict)
    store_provider: str = "btapi"
    cerebro_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Run every input-normalization and validation pass."""
        self._normalize_mode_frequency()
        self._validate_store_config()
        self._normalize_symbols()
        self._validate_data_source()

    def _normalize_mode_frequency(self) -> None:
        """Lower-case and validate ``mode`` and ``frequency``."""
        self.mode = str(self.mode or "").lower()
        if self.mode not in {"backtest", "live"}:
            raise ValueError("LiveProfile.mode must be 'backtest' or 'live'")
        self.frequency = str(self.frequency or "").lower()
        if self.frequency not in {"lowfreq", "midfreq", "hft"}:
            raise ValueError("LiveProfile.frequency must be 'lowfreq', 'midfreq', or 'hft'")

    def _validate_store_config(self) -> None:
        """Reject live store configuration on backtest profiles."""
        if self.mode == "backtest" and (
            self.store_factory is not None or self.store_kwargs or self.store_provider != "btapi"
        ):
            raise ValueError("Backtest profiles cannot use live store configuration")

    def _normalize_symbols(self) -> None:
        """Coerce ``symbols`` into a tuple of non-empty strings."""
        symbols = self.symbols
        if isinstance(symbols, str):
            symbols = (symbols,)
        self.symbols = tuple(str(symbol) for symbol in (symbols or ()) if str(symbol))

    def _validate_data_source(self) -> None:
        """Ensure exactly one coherent data source is configured."""
        if self.data_factory is not None and (self.dataname not in (None, "") or self.symbols):
            raise ValueError("LiveProfile.data_factory cannot be used with dataname or symbols")
        if self.data_factory is None and self.dataname in (None, "") and not self.symbols:
            raise ValueError("LiveProfile requires dataname, symbols, or data_factory")
        if self.dataname not in (None, "") and self.symbols:
            raise ValueError("LiveProfile cannot use both dataname and symbols")
        if self.data_name not in (None, "") and len(self.symbols) > 1:
            raise ValueError("LiveProfile.data_name cannot be used with multiple symbols")

    @property
    def is_live(self) -> bool:
        """Return ``True`` when the profile's ``mode`` is ``"live"``.

        Used by :func:`build_cerebro` and friends to branch between
        the live (store-backed) and backtest (CSV-backed) wiring
        paths without re-comparing the raw ``mode`` string.
        """
        return self.mode == "live"


def build_cerebro(profile: LiveProfile) -> Cerebro:
    """Construct a fully wired-up :class:`Cerebro` from ``profile``.

    The function instantiates the store (for live profiles), the
    broker and the data feeds according to ``profile``, attaches
    them to a fresh :class:`Cerebro`, and registers the strategy.
    The profile and store are exposed back on the Cerebro as
    ``live_profile`` and ``profile_store`` for downstream
    introspection.

    Args:
        profile: The :class:`LiveProfile` describing the run.

    Returns:
        Cerebro: A Cerebro instance with the broker, data feed(s)
        and strategy attached.
    """
    cerebro = Cerebro(**dict(profile.cerebro_kwargs))
    store = _build_store(profile) if profile.is_live else None
    broker = _build_broker(profile, store)
    datas = list(_build_datas(profile, store))

    if profile.data_name not in (None, "") and len(datas) > 1:
        raise ValueError("LiveProfile.data_name cannot be used with multiple data feeds")

    cerebro.setbroker(broker)
    for data in datas:
        data_name = profile.data_name
        if data_name in (None, ""):
            data_name = getattr(data, "_name", None) or getattr(data, "_dataname", None)
        if data_name is None:
            cerebro.adddata(data)
        else:
            cerebro.adddata(data, name=data_name)
    cerebro.addstrategy(profile.strategy, *profile.strategy_args, **dict(profile.strategy_kwargs))
    cerebro.live_profile = profile
    cerebro.profile_store = store
    return cerebro


def _build_store(profile: LiveProfile):
    """Instantiate the live store declared by ``profile``.

    When ``profile.store_factory`` is set it is called with no
    arguments and its return value is used. Otherwise a
    :class:`BtApiStore` is constructed using
    ``profile.store_provider`` and ``profile.store_kwargs``.
    """
    if profile.store_factory is not None:
        return profile.store_factory()
    return BtApiStore(provider=profile.store_provider, **dict(profile.store_kwargs))


def _build_broker(profile: LiveProfile, store):
    """Instantiate the broker declared by ``profile``.

    ``profile.broker_factory`` short-circuits the standard flow
    when set (and must return a non-``None`` broker). For live
    profiles the broker is obtained via ``store.getbroker``; for
    backtest profiles a :class:`BackBroker` (or
    ``profile.broker_cls``) is constructed directly.
    """
    if profile.broker_factory is not None:
        broker = profile.broker_factory(store=store, profile=profile)
        if broker is None:
            raise ValueError("LiveProfile.broker_factory must return a broker instance")
        return broker

    broker_kwargs = dict(profile.broker_kwargs)
    if profile.is_live:
        if store is None:
            raise ValueError("Live profiles require a store instance")
        if profile.broker_cls is None:
            return store.getbroker(**broker_kwargs)
        return store.getbroker(broker_cls=profile.broker_cls, **broker_kwargs)

    broker_cls = profile.broker_cls or BackBroker
    return broker_cls(**broker_kwargs)


def _build_datas(profile: LiveProfile, store) -> Iterable[Any]:
    """Instantiate the data feed(s) declared by ``profile``.

    ``profile.data_factory`` short-circuits the standard flow when
    set; the factory may return a single data instance or a list /
    tuple of them. Otherwise the data feeds are constructed via the
    store (live) or via :class:`BacktraderCSVData` (backtest), one
    per ``dataname``/``symbol``.
    """
    if profile.data_factory is not None:
        data_obj = profile.data_factory()
        if isinstance(data_obj, (list, tuple)):
            datas = list(data_obj)
        else:
            datas = [data_obj]
        if not datas or any(data is None for data in datas):
            raise ValueError("LiveProfile.data_factory must return one or more data instances")
        return datas

    data_kwargs = dict(profile.data_kwargs)
    datanames = list(profile.symbols) if profile.symbols else [profile.dataname]
    if profile.is_live:
        if store is None:
            raise ValueError("Live profiles require a store instance")
        if profile.data_cls is None:
            return [store.getdata(dataname=dataname, **data_kwargs) for dataname in datanames]
        return [
            store.getdata(dataname=dataname, data_cls=profile.data_cls, **data_kwargs)
            for dataname in datanames
        ]

    data_cls = profile.data_cls or BacktraderCSVData
    return [data_cls(dataname=dataname, **data_kwargs) for dataname in datanames]


__all__ = ["LiveProfile", "build_cerebro"]
