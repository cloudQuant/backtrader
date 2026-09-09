"""Persistent daily risk policy and deterministic execution deadlines."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class DailyRiskRecord:
    schema_version: str
    account_fingerprint: str
    trading_day: str
    starting_equity: float
    realized_pnl: float = 0.0
    fees: float = 0.0
    consecutive_losses: int = 0
    entry_attempts: int = 0
    smoke_entry_attempts: int = 0
    write_requests: int = 0
    emergency_write_requests: int = 0
    halted_reason: str = ""


class DailyRiskStore:
    """Atomic state keyed by account fingerprint and TradingDay."""

    SCHEMA = "iter22.daily-risk.v2"
    _COUNTER_FIELDS = (
        "consecutive_losses",
        "entry_attempts",
        "smoke_entry_attempts",
        "write_requests",
        "emergency_write_requests",
    )
    _FLOAT_FIELDS = ("starting_equity", "realized_pnl", "fees")
    _REQUIRED_FIELDS = {
        "schema_version",
        "account_fingerprint",
        "trading_day",
        "starting_equity",
        "realized_pnl",
        "fees",
        *_COUNTER_FIELDS,
        "halted_reason",
    }

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.record: Optional[DailyRiskRecord] = None
        self.persistence_ok = True
        self.last_error = ""
        # If the local risk file becomes unavailable after an order has been
        # admitted, one process-local token per emergency action still permits
        # a risk-reducing SDK request.  The SDK journal remains the durable
        # source of order intent; this volatile ledger is exposed as evidence
        # and never re-opens entry admission.
        self.volatile_emergency_keys: set[str] = set()

    def load_or_create(
        self,
        *,
        account_fingerprint: str,
        trading_day: str,
        starting_equity: float,
        reconciliation_complete: bool = False,
    ) -> DailyRiskRecord:
        if not account_fingerprint or not trading_day:
            raise ValueError("account fingerprint and TradingDay are required")
        if not math.isfinite(float(starting_equity)) or starting_equity <= 0:
            raise ValueError("a positive complete-preflight starting equity is required")
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._validate_payload(raw)
            if raw.get("account_fingerprint") != account_fingerprint:
                raise ValueError("risk state account mismatch")
            if raw.get("trading_day") == trading_day:
                self.record = DailyRiskRecord(**raw)
                return self.record
        # Creating the first record and crossing TradingDay both freeze a new
        # equity baseline.  The caller must bind that baseline to a fresh,
        # terminal account/position/order/trade reconciliation; a positive
        # number by itself is not evidence of a completed snapshot.
        if reconciliation_complete is not True:
            raise ValueError("new TradingDay requires complete reconciliation")
        self.record = DailyRiskRecord(
            schema_version=self.SCHEMA,
            account_fingerprint=account_fingerprint,
            trading_day=trading_day,
            starting_equity=float(starting_equity),
        )
        self.save()
        return self.record

    def save(self) -> None:
        if self.record is None:
            raise RuntimeError("risk record has not been initialized")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(self.record)
            self._validate_payload(payload)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        payload,
                        handle,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, self.path)
                self._fsync_directory(self.path.parent)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            self.persistence_ok = True
            self.last_error = ""
        except Exception as exc:
            self.persistence_ok = False
            self.last_error = type(exc).__name__
            raise

    @classmethod
    def _validate_payload(cls, raw: Any) -> None:
        if not isinstance(raw, dict) or set(raw) != cls._REQUIRED_FIELDS:
            raise ValueError("risk state fields are incomplete or unexpected")
        if raw.get("schema_version") != cls.SCHEMA:
            raise ValueError("risk state schema mismatch")
        account = raw.get("account_fingerprint")
        trading_day = raw.get("trading_day")
        if not isinstance(account, str) or not account.startswith("acct_"):
            raise ValueError("risk state account fingerprint is invalid")
        if not isinstance(trading_day, str) or len(trading_day) != 8 or not trading_day.isdigit():
            raise ValueError("risk state TradingDay is invalid")
        for name in cls._FLOAT_FIELDS:
            value = raw.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"risk state {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"risk state {name} must be finite")
        if float(raw["starting_equity"]) <= 0 or float(raw["fees"]) < 0:
            raise ValueError("risk state equity/fees are outside allowed bounds")
        for name in cls._COUNTER_FIELDS:
            value = raw.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"risk state {name} must be a nonnegative integer")
        if not isinstance(raw.get("halted_reason"), str):
            raise ValueError("risk state halted_reason must be a string")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _update(self, **values: Any) -> None:
        if self.record is None:
            raise RuntimeError("risk record has not been initialized")
        for key, value in values.items():
            setattr(self.record, key, value)
        self.save()

    def reserve_entry(self, max_entries: int = 30, *, budget_key: str = "all") -> bool:
        record = self._require()
        if budget_key not in {"all", "engineering_smoke"}:
            raise ValueError("unsupported entry budget key")
        used = (
            record.smoke_entry_attempts
            if budget_key == "engineering_smoke"
            else record.entry_attempts
        )
        if not self.persistence_ok or used >= max_entries:
            return False
        values = {"entry_attempts": record.entry_attempts + 1}
        if budget_key == "engineering_smoke":
            values["smoke_entry_attempts"] = record.smoke_entry_attempts + 1
        self._update(**values)
        return True

    def _reserve_volatile_emergency(self, key: str, reserve: int) -> bool:
        if reserve <= 0:
            return False
        token = str(key or "unspecified")
        if token in self.volatile_emergency_keys or len(self.volatile_emergency_keys) >= reserve:
            return False
        self.volatile_emergency_keys.add(token)
        if self.record is not None:
            self.record.halted_reason = "risk_persistence_unavailable"
        return True

    def reserve_write(
        self,
        *,
        emergency: bool = False,
        normal_limit: int = 100,
        reserve: int = 20,
        allow_unpersisted_emergency: bool = False,
        emergency_key: str = "",
    ) -> bool:
        record = self._require()
        if not self.persistence_ok:
            if emergency and allow_unpersisted_emergency:
                return self._reserve_volatile_emergency(emergency_key, reserve)
            return False
        if emergency:
            if record.emergency_write_requests >= reserve:
                self._update(halted_reason="emergency_write_budget_exhausted")
                return False
            try:
                self._update(emergency_write_requests=record.emergency_write_requests + 1)
            except Exception:
                if allow_unpersisted_emergency:
                    return self._reserve_volatile_emergency(emergency_key, reserve)
                raise
            return True
        if record.write_requests >= normal_limit:
            return False
        self._update(write_requests=record.write_requests + 1)
        return True

    def record_closed_trade(self, gross_pnl: float, fee: float = 0.0) -> None:
        record = self._require()
        gross = float(gross_pnl)
        commission = float(fee)
        if not math.isfinite(gross) or not math.isfinite(commission) or commission < 0:
            raise ValueError("gross PnL and nonnegative fee must be finite")
        net = gross - commission
        loss_streak = record.consecutive_losses + 1 if net < 0 else 0
        reason = "three_consecutive_losses" if loss_streak >= 3 else record.halted_reason
        self._update(
            # ``realized_pnl`` is deliberately gross.  Admission subtracts the
            # separately accumulated fees exactly once.
            realized_pnl=record.realized_pnl + gross,
            fees=record.fees + commission,
            consecutive_losses=loss_streak,
            halted_reason=reason,
        )

    def admission(
        self,
        *,
        unrealized_pnl: Optional[float],
        daily_loss_cny: float = 500.0,
        daily_loss_fraction: float = 0.005,
    ) -> tuple[bool, str, float]:
        record = self._require()
        threshold = min(float(daily_loss_cny), record.starting_equity * float(daily_loss_fraction))
        if not self.persistence_ok:
            return False, "risk_persistence_unavailable", threshold
        if unrealized_pnl is None or not math.isfinite(float(unrealized_pnl)):
            return False, "unrealized_pnl_unavailable", threshold
        total = record.realized_pnl - record.fees + float(unrealized_pnl)
        if total <= -threshold:
            return False, "daily_loss_limit", threshold
        if record.consecutive_losses >= 3:
            return False, "three_consecutive_losses", threshold
        if record.halted_reason:
            return False, record.halted_reason, threshold
        return True, "ok", threshold

    def _require(self) -> DailyRiskRecord:
        if self.record is None:
            raise RuntimeError("risk record has not been initialized")
        return self.record


@dataclass(frozen=True)
class FillTimeBounds:
    """Conservative monotonic bounds for the first actual entry fill."""

    earliest: float
    latest: float
    source: str
    trusted: bool

    def validate(self) -> None:
        if not all(math.isfinite(value) for value in (self.earliest, self.latest)):
            raise ValueError("fill time bounds must be finite")
        if self.earliest > self.latest:
            raise ValueError("earliest fill bound cannot follow latest bound")

    def normal_exit_allowed(self, now: float, minimum_seconds: float = 60.0) -> bool:
        self.validate()
        return float(now) - self.latest >= float(minimum_seconds)

    def maximum_expired(self, now: float, maximum_seconds: float = 900.0) -> bool:
        self.validate()
        return float(now) - self.earliest >= float(maximum_seconds)

    def interval(self, now: float) -> tuple[float, float]:
        self.validate()
        return max(float(now) - self.latest, 0.0), max(float(now) - self.earliest, 0.0)


class GFDOrderDeadline:
    """Track submit, cancel request, confirmation, and UNKNOWN transitions."""

    def __init__(self, entry_timeout: float = 3.0, cancel_timeout: float = 5.0) -> None:
        self.entry_timeout = float(entry_timeout)
        self.cancel_timeout = float(cancel_timeout)
        self.reset()

    def reset(self) -> None:
        self.submitted_at: float | None = None
        self.cancel_requested_at: float | None = None
        self.terminal = False
        self.unknown = False

    def submitted(self, now: float) -> None:
        self.reset()
        self.submitted_at = float(now)

    def cancel_requested(self, now: float) -> None:
        if self.submitted_at is None or self.terminal:
            raise RuntimeError("cannot cancel an inactive order")
        self.cancel_requested_at = float(now)

    def confirmed_terminal(self) -> None:
        self.terminal = True

    def action(self, now: float) -> str:
        if self.terminal or self.submitted_at is None:
            return "wait"
        if self.cancel_requested_at is None:
            return "cancel" if now - self.submitted_at >= self.entry_timeout else "wait"
        if now - self.cancel_requested_at >= self.cancel_timeout:
            self.unknown = True
            return "unknown"
        return "wait_for_cancel_confirmation"


def potential_exposure_lots(position_lots: int, pending_open_lots: int) -> int:
    return abs(int(position_lots)) + abs(int(pending_open_lots))
