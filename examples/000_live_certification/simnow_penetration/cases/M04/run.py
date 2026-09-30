"""Offline Cerebro smoke runner for one certification case."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import math
from pathlib import Path
import re
import sys

_CASE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(credential|token|password|secret|auth|user|account|broker|ctp|front)", re.I
)
_ORDER_ACTION_CASES = {
    "B01",
    "B02",
    "E01",
    "E02",
    "EM01",
    "L01",
    "L03",
    "L04",
    "M04",
    "M05",
    "O01",
    "O02",
    "O03",
    "T01",
    "T02",
    "T03",
    "TH02",
    "TH04",
    "TH06",
    "V01",
    "V02",
    "V03",
}
_MISSING = object()


class _SmokeError(Exception):
    pass


def _emit(case_id, *, exercised=False, observed=None, reason=None, mode="OFFLINE_SMOKE"):
    payload = {
        "case_id": case_id,
        "mode": mode,
        "strategy_exercised": bool(exercised),
        "observed": observed or {},
        "certification": "BLOCKED",
    }
    if reason:
        payload["reason"] = reason
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0 if exercised and reason is None else 2


def _case_config(suite_root, case_id):
    path = suite_root / "config.yaml"
    if not path.is_file():
        raise _SmokeError("offline_smoke_config_missing")
    try:
        import yaml

        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        raise _SmokeError("offline_smoke_config_invalid") from None
    cases = config.get("cases", {}) if isinstance(config, dict) else None
    values = cases.get(case_id, {}) if isinstance(cases, dict) else None
    if not isinstance(values, dict) or any(
        not isinstance(key, str)
        or not key.strip()
        or _SENSITIVE_KEY_RE.search(key)
        or type(value) not in (str, bool, int, float, type(None))
        or (type(value) is float and not math.isfinite(value))
        for key, value in values.items()
    ):
        raise _SmokeError("offline_smoke_config_invalid")
    return values


@contextlib.contextmanager
def _offline_guard():
    import socket
    from unittest.mock import patch

    def deny(*_args, **_kwargs):
        raise _SmokeError("offline_smoke_network_blocked")

    with contextlib.ExitStack() as stack:
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        for obj, name in (
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
            (socket.socket, "sendto"),
        ):
            stack.enter_context(patch.object(obj, name, side_effect=deny))
        yield


def _run_offline(case_id):
    path = Path(__file__).resolve()
    case_dir, repo_root = str(path.parent), str(path.parents[5])
    old_path = sys.path[:]
    sys.path[:0] = [case_dir, repo_root]
    module_name = f"{case_id}_strategy"
    old_module = sys.modules.pop(module_name, _MISSING)
    try:
        with _offline_guard():
            case_config = _case_config(path.parents[2], case_id)
            try:
                strategy = getattr(importlib.import_module(module_name), f"{case_id}Strategy")
            except Exception:
                raise _SmokeError("offline_smoke_strategy_import_failed") from None
            import backtrader as bt
            import pandas as pd

            if not isinstance(strategy, type) or not issubclass(strategy, bt.Strategy):
                raise _SmokeError("offline_smoke_strategy_invalid")
            closes = [100.0 + i * 0.2 + (i % 5) * 0.05 for i in range(64)]
            data = pd.DataFrame(
                {
                    "open": [x - 0.03 for x in closes],
                    "high": [x + 0.1 for x in closes],
                    "low": [x - 0.13 for x in closes],
                    "close": closes,
                    "volume": [100.0 + i for i in range(64)],
                    "openinterest": [0.0] * 64,
                },
                index=pd.date_range("2024-01-01", periods=64, freq="min"),
            )
            cerebro = bt.Cerebro(stdstats=False, runonce=False)
            broker = bt.brokers.BackBroker()
            broker.setcash(1_000_000.0)
            cerebro.setbroker(broker)
            cerebro.adddata(bt.feeds.PandasData(dataname=data))
            cerebro.addstrategy(
                strategy, case_config=case_config, allow_orders=case_id in _ORDER_ACTION_CASES
            )
            results = cerebro.run()
            if len(results) != 1:
                raise _SmokeError("offline_smoke_strategy_result_invalid")
            instance = results[0]
            bars = getattr(instance, "bars_seen", 0)
            bars = bars if type(bars) is int and bars > 0 else 0
            observed = {
                "bars_seen": bars,
                "case_observed": getattr(instance, "case_observed", False) is True,
            }
            if not bars:
                raise _SmokeError("offline_smoke_strategy_not_exercised")
        return _emit(case_id, exercised=True, observed=observed)
    except _SmokeError as exc:
        return _emit(case_id, reason=str(exc))
    except Exception:
        return _emit(case_id, reason="offline_smoke_run_failed")
    finally:
        sys.path[:] = old_path
        if old_module is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = old_module


def main():
    case_id = Path(__file__).resolve().parent.name
    if not _CASE_ID_RE.fullmatch(case_id):
        return _emit("unknown", reason="offline_smoke_case_id_invalid")
    if "--live" in sys.argv[1:]:
        return _emit(
            case_id, reason="managed_ctp_certification_not_registered", mode="LIVE_BLOCKED"
        )
    if sys.argv[1:]:
        return _emit(case_id, reason="offline_smoke_arguments_not_supported")
    return _run_offline(case_id)


if __name__ == "__main__":
    raise SystemExit(main())
