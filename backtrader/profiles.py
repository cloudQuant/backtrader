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
        return self.mode == "live"


def build_cerebro(profile: LiveProfile) -> Cerebro:
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
    if profile.store_factory is not None:
        return profile.store_factory()
    return BtApiStore(provider=profile.store_provider, **dict(profile.store_kwargs))


def _build_broker(profile: LiveProfile, store):
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
