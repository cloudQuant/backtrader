"""Versioned position snapshot at ``logs/current_position.yaml`` (D62-05).

Version 2 content::

    version: 2
    mode: live | backtest
    strategy_uuid: <uuid4>
    account_hash: <sha256 hex> | null      # required for live
    exchange_name: <text> | null           # required for live
    trading_day: YYYYMMDD | null           # required for live
    updated_at_utc: <iso>
    positions:
      <instrument_id>:
        long:  {total: int, today: int|null, yesterday: int|null}
        short: {total: int, today: int|null, yesterday: int|null}
        net: int                           # == long.total - short.total
    local_seq_high: int

The legacy TradeLogger file (no ``version``; ``positions`` entries with
``size``) is rejected by :meth:`PositionSnapshotStore.read` and readable only
through :meth:`PositionSnapshotStore.read_legacy`, which returns net sizes and
is flagged as legacy.  A snapshot proves nothing about the account; it is the
local reconciliation entry that must be checked against venue queries.

Write guard: :meth:`PositionSnapshotStore.write` refuses to overwrite a
snapshot that belongs to another mode, strategy, account or exchange, or an
unreadable/legacy file, unless ``replace_foreign=True``; the replaced file is
then kept as ``current_position.yaml.replaced-<utc>``.  This stops a backtest
run in a live strategy directory from silently clobbering the live snapshot.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from ._common import (
    StatePaths,
    is_sha256_hex,
    is_strict_int,
    is_text,
    is_trading_day,
    is_uuid4,
    utc_compact,
    utc_now_iso,
)
from .atomic import (
    FileLock,
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    atomic_write_bytes,
    atomic_write_text,
)

__all__ = ("LegacyPositions", "PositionSnapshotStore", "SNAPSHOT_VERSION")

SNAPSHOT_VERSION = 2
MODES = frozenset({"live", "backtest"})
_TOP_KEYS = frozenset(
    {
        "version",
        "mode",
        "strategy_uuid",
        "account_hash",
        "exchange_name",
        "trading_day",
        "updated_at_utc",
        "positions",
        "local_seq_high",
    }
)
_SIDE_KEYS = frozenset({"total", "today", "yesterday"})


def _yaml():
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a backtrader requirement
        raise LiveStateError("yaml_unavailable") from None
    return yaml


class LegacyPositions(dict):
    """``{instrument: net_size}`` read from a legacy TradeLogger snapshot.

    ``legacy`` is always ``True``; ``datetime`` and ``strategy`` repeat the
    legacy header fields when they were text.
    """

    legacy = True

    def __init__(self, positions, *, datetime=None, strategy=None, source_path=""):
        super().__init__(positions)
        self.datetime = datetime
        self.strategy = strategy
        self.source_path = source_path


def _side(value: Any, where: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != _SIDE_KEYS:
        raise ValueError(where)
    total = value["total"]
    today = value["today"]
    yesterday = value["yesterday"]
    if not is_strict_int(total, minimum=0):
        raise ValueError(f"{where}.total")
    for name, part in (("today", today), ("yesterday", yesterday)):
        if part is not None and not (is_strict_int(part, minimum=0) and part <= total):
            raise ValueError(f"{where}.{name}")
    if today is not None and yesterday is not None and today + yesterday != total:
        raise ValueError(f"{where}.split")
    return {"total": total, "today": today, "yesterday": yesterday}


# Host facts stored atomically with the positions (iteration 62 direct mode):
# applied venue trade keys of the current trading day (fill de-duplication
# across restarts) and the average open price of each side.
_OPTIONAL_TOP_KEYS = frozenset({"applied_trades", "position_prices"})


def _normalize(raw: Any, *, writing: bool) -> dict:
    """Return the validated v2 snapshot or raise ``ValueError(field)``."""
    if not isinstance(raw, Mapping):
        raise ValueError("not_a_mapping")
    data = dict(raw)
    if writing:
        data.setdefault("version", SNAPSHOT_VERSION)
        data.setdefault("updated_at_utc", utc_now_iso())
    if "version" not in data:
        raise ValueError("version_missing")
    if type(data["version"]) is not int or data["version"] != SNAPSHOT_VERSION:
        raise ValueError("version_unsupported")
    extra_keys = set(data) - _TOP_KEYS
    if not extra_keys <= _OPTIONAL_TOP_KEYS or not _TOP_KEYS <= set(data):
        raise ValueError("unexpected_keys")
    applied = data.get("applied_trades", {})
    if not isinstance(applied, Mapping) or any(
        not is_trading_day(day)
        or not isinstance(keys, list)
        or any(not is_text(key, max_len=512) for key in keys)
        for day, keys in applied.items()
    ):
        raise ValueError("applied_trades")
    prices = data.get("position_prices", {})
    if not isinstance(prices, Mapping) or any(
        not isinstance(entry, Mapping)
        or set(entry) - {"long", "short"}
        or any(type(value) not in (int, float) for value in entry.values())
        for entry in prices.values()
    ):
        raise ValueError("position_prices")
    mode = data["mode"]
    if mode not in MODES:
        raise ValueError("mode")
    if not is_uuid4(data["strategy_uuid"]):
        raise ValueError("strategy_uuid")
    live = mode == "live"
    account_hash = data["account_hash"]
    if not (is_sha256_hex(account_hash) or (account_hash is None and not live)):
        raise ValueError("account_hash")
    exchange_name = data["exchange_name"]
    if not (is_text(exchange_name, max_len=128) or (exchange_name is None and not live)):
        raise ValueError("exchange_name")
    trading_day = data["trading_day"]
    if not (is_trading_day(trading_day) or (trading_day is None and not live)):
        raise ValueError("trading_day")
    if not is_text(data["updated_at_utc"], max_len=64):
        raise ValueError("updated_at_utc")
    if not is_strict_int(data["local_seq_high"], minimum=0):
        raise ValueError("local_seq_high")
    positions_in = data["positions"]
    if not isinstance(positions_in, Mapping):
        raise ValueError("positions")
    positions = {}
    for instrument, entry in positions_in.items():
        if not is_text(instrument, max_len=128):
            raise ValueError("positions.instrument")
        where = f"positions.{instrument}"
        if not isinstance(entry, Mapping) or set(entry) != {"long", "short", "net"}:
            raise ValueError(where)
        long_side = _side(entry["long"], f"{where}.long")
        short_side = _side(entry["short"], f"{where}.short")
        net = entry["net"]
        if not is_strict_int(net) or net != long_side["total"] - short_side["total"]:
            raise ValueError(f"{where}.net")
        positions[instrument] = {"long": long_side, "short": short_side, "net": net}
    data["positions"] = positions
    return data


def _is_legacy(raw: Any) -> bool:
    if not isinstance(raw, Mapping) or "version" in raw:
        return False
    positions = raw.get("positions")
    if not isinstance(positions, Mapping):
        return False
    return all(isinstance(entry, Mapping) and "size" in entry for entry in positions.values())


class PositionSnapshotStore:
    """Reader/writer of ``logs/current_position.yaml`` for one strategy directory."""

    def __init__(self, strategy_dir: Any, *, lock_timeout: float = 10.0) -> None:
        self.paths = StatePaths(strategy_dir)
        self.lock_timeout = lock_timeout

    @property
    def path(self) -> str:
        return self.paths.snapshot

    def _parse_file(self) -> Optional[Any]:
        try:
            with open(self.paths.snapshot, "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return None
        yaml = _yaml()
        try:
            text = raw.decode("utf-8")
            parsed = yaml.safe_load(text)
        except (UnicodeDecodeError, yaml.YAMLError):
            raise LiveStateCorrupt(self.paths.snapshot, "yaml_parse_error") from None
        if parsed is None:
            raise LiveStateCorrupt(self.paths.snapshot, "empty_file")
        return parsed

    def read(self) -> Optional[dict]:
        """Return the validated v2 snapshot, ``None`` if the file is missing.

        ``None`` is not evidence of a flat account.  Raises
        :class:`LiveStateCorrupt` (``legacy_format`` for a TradeLogger legacy
        file, ``version_unsupported``, ``invalid_field:<name>`` ...).
        """
        parsed = self._parse_file()
        if parsed is None:
            return None
        if _is_legacy(parsed):
            raise LiveStateCorrupt(self.paths.snapshot, "legacy_format")
        try:
            return _normalize(parsed, writing=False)
        except ValueError as exc:
            reason = str(exc)
            if reason not in ("version_unsupported", "version_missing", "not_a_mapping"):
                reason = f"invalid_field:{reason}"
            raise LiveStateCorrupt(self.paths.snapshot, reason) from None

    def read_legacy(self) -> Optional[LegacyPositions]:
        """Read a legacy TradeLogger snapshot as ``{instrument: net_size}``.

        ``None`` if missing; ``LiveStateError("snapshot_not_legacy")`` for a
        non-legacy file; :class:`LiveStateCorrupt` for unusable sizes.
        """
        parsed = self._parse_file()
        if parsed is None:
            return None
        if not _is_legacy(parsed):
            raise LiveStateError("snapshot_not_legacy")
        positions = {}
        for instrument, entry in parsed["positions"].items():
            size = entry["size"]
            if type(instrument) is not str or not instrument:
                raise LiveStateCorrupt(self.paths.snapshot, "legacy_instrument")
            if type(size) is float:
                if size != size or size in (float("inf"), float("-inf")):
                    raise LiveStateCorrupt(self.paths.snapshot, f"legacy_size:{instrument}")
                if size.is_integer():
                    size = int(size)
            elif type(size) is not int:
                raise LiveStateCorrupt(self.paths.snapshot, f"legacy_size:{instrument}")
            positions[instrument] = size
        stamp = parsed.get("datetime")
        strategy = parsed.get("strategy")
        return LegacyPositions(
            positions,
            datetime=stamp if type(stamp) is str else None,
            strategy=strategy if type(strategy) is str else None,
            source_path=self.paths.snapshot,
        )

    def read_for_live(
        self, account_hash: str, exchange_name: str, *, strategy_uuid: Optional[str] = None
    ) -> dict:
        """Return the snapshot only if it is a live snapshot of this account/exchange.

        Raises :class:`LiveStateNotInitialized` if missing,
        :class:`LiveStateCorrupt` if unusable, and
        :class:`LiveStateIdentityMismatch` (``snapshot_mode_mismatch``,
        ``snapshot_account_mismatch``, ``snapshot_exchange_mismatch``,
        ``snapshot_strategy_mismatch``) otherwise.
        """
        if not is_sha256_hex(account_hash):
            raise LiveStateError("account_hash_invalid")
        if not is_text(exchange_name, max_len=128):
            raise LiveStateError("snapshot_invalid", "exchange_name")
        snapshot = self.read()
        if snapshot is None:
            raise LiveStateNotInitialized(self.paths.snapshot)
        if snapshot["mode"] != "live":
            raise LiveStateIdentityMismatch("snapshot_mode_mismatch")
        if snapshot["account_hash"] != account_hash:
            raise LiveStateIdentityMismatch("snapshot_account_mismatch")
        if snapshot["exchange_name"] != exchange_name:
            raise LiveStateIdentityMismatch("snapshot_exchange_mismatch")
        if strategy_uuid is not None and snapshot["strategy_uuid"] != strategy_uuid:
            raise LiveStateIdentityMismatch("snapshot_strategy_mismatch")
        return snapshot

    def write(self, snapshot: Mapping[str, Any], *, replace_foreign: bool = False) -> dict:
        """Validate and atomically write ``snapshot``; return the written dict.

        ``version`` defaults to 2 and ``updated_at_utc`` to now.  Raises
        ``LiveStateError("snapshot_invalid", field)`` for invalid content and
        ``LiveStateIdentityMismatch("snapshot_foreign")`` when the existing
        file belongs elsewhere (see module docstring) and ``replace_foreign``
        is false.
        """
        try:
            data = _normalize(snapshot, writing=True)
        except ValueError as exc:
            raise LiveStateError("snapshot_invalid", str(exc)) from None
        yaml = _yaml()
        text = yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=True)
        if not os.path.isdir(self.paths.strategy_dir):
            raise LiveStateError("strategy_dir_missing")
        os.makedirs(self.paths.logs_dir, exist_ok=True)
        with FileLock(self.paths.snapshot_lock, timeout=self.lock_timeout):
            foreign = self._foreign_reason(data)
            if foreign is not None:
                if not replace_foreign:
                    raise LiveStateIdentityMismatch("snapshot_foreign", foreign)
                with open(self.paths.snapshot, "rb") as handle:
                    previous = handle.read()
                atomic_write_bytes(f"{self.paths.snapshot}.replaced-{utc_compact()}", previous)
            atomic_write_text(self.paths.snapshot, text)
        return data

    def _foreign_reason(self, new: Mapping[str, Any]) -> Optional[str]:
        try:
            existing = self.read()
        except LiveStateCorrupt as exc:
            return f"existing_{exc.reason}"
        if existing is None:
            return None
        for key in ("mode", "strategy_uuid", "account_hash", "exchange_name"):
            if existing[key] != new[key]:
                return f"existing_{key}_differs"
        return None
