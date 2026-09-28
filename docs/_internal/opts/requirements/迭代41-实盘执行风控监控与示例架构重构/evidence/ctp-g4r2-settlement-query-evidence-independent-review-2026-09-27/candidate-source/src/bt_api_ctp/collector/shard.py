"""Sharding: split the instrument universe across independent machines.

Each machine runs with its own ``ShardConfig`` and never coordinates with
the others, so the partition must be deterministic.  ``hash_mod`` therefore
uses CRC32 rather than the builtin ``hash()``, whose value depends on
``PYTHONHASHSEED`` and would differ between machines.
"""

from __future__ import annotations

import zlib
from collections import Counter
from dataclasses import dataclass, field

from bt_api_ctp.collector.protocols import InstrumentSpec

_STRATEGIES = ("by_exchange", "by_prefix", "hash_mod")


@dataclass(frozen=True)
class ShardConfig:
    """Declarative shard assignment for one machine."""

    strategy: str
    exchanges: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    shard_id: int = 0
    total_shards: int = 1


@dataclass
class ShardValidationReport:
    """Outcome of checking several machines' shard configs together."""

    overlaps: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ok: bool = True


def _matches(spec: InstrumentSpec, config: ShardConfig) -> bool:
    if config.strategy == "by_exchange":
        return spec.exchange_id in config.exchanges
    if config.strategy == "by_prefix":
        symbol = spec.instrument_id.upper()
        return any(symbol.startswith(prefix.upper()) for prefix in config.prefixes)
    if config.strategy == "hash_mod":
        return zlib.crc32(spec.instrument_id.encode("utf-8")) % config.total_shards == (
            config.shard_id
        )
    raise ValueError(f"unknown shard strategy: {config.strategy!r}")


def _validate_config(config: ShardConfig) -> None:
    if config.strategy not in _STRATEGIES:
        raise ValueError(f"unknown shard strategy: {config.strategy!r}")
    if config.strategy == "hash_mod":
        if config.total_shards < 1:
            raise ValueError("total_shards must be >= 1")
        if not 0 <= config.shard_id < config.total_shards:
            raise ValueError("shard_id must satisfy 0 <= shard_id < total_shards")


def select_instruments(
    instruments: list[InstrumentSpec], config: ShardConfig
) -> list[InstrumentSpec]:
    """Return the subset this machine owns."""
    _validate_config(config)
    return [spec for spec in instruments if _matches(spec, config)]


def validate_shards(
    configs: list[ShardConfig], all_instruments: list[InstrumentSpec]
) -> ShardValidationReport:
    """Check that a set of machine configs partitions the universe exactly."""
    counts: Counter[str] = Counter()
    for config in configs:
        for spec in select_instruments(all_instruments, config):
            counts[spec.instrument_id] += 1

    overlaps = sorted(name for name, count in counts.items() if count > 1)
    missing = sorted({spec.instrument_id for spec in all_instruments} - set(counts))
    return ShardValidationReport(
        overlaps=overlaps,
        missing=missing,
        ok=not overlaps and not missing,
    )


__all__ = ["ShardConfig", "ShardValidationReport", "select_instruments", "validate_shards"]
