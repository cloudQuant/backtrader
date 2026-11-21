"""Restricted public-snapshot Cerebro parity pilot; not a full indicator audit."""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "snapshot_r3"
HEAD = "c5fc2e7e954eae104d4acae5accdd9bf30e9c44d"

# Explicitly reviewed pilot modules only; the matrix is not an import allowlist.
CASES = {
    "adxdmi_default_finite": (
        "backtrader.indicators.contrib.adxdmi",
        "ADXDMI",
        {},
        "one",
        "finite",
        None,
    ),
    "ai_accel_default_finite": (
        "backtrader.indicators.contrib.ai_acceleration_deceleration_oscillator",
        "AIAccelerationDecelerationOscillator",
        {},
        "one",
        "finite",
        None,
    ),
    "altr_default_finite": (
        "backtrader.indicators.contrib.altr_trend_signal_v22",
        "AltrTrendSignalV22",
        {},
        "one",
        "finite",
        None,
    ),
    "asimmetric_default_finite": (
        "backtrader.indicators.contrib.asimmetric_stoch_nr_indicator",
        "AsimmetricStochNRIndicator",
        {},
        "one",
        "finite",
        None,
    ),
    "atr_normalize_default_finite": (
        "backtrader.indicators.contrib.atr_normalize_histogram",
        "AtrNormalizeHistogram",
        {},
        "one",
        "finite",
        None,
    ),
    "average_change_default_finite": (
        "backtrader.indicators.contrib.average_change_candle",
        "AverageChangeCandle",
        {},
        "one",
        "finite",
        None,
    ),
    "bears_power_default_finite": (
        "backtrader.indicators.contrib.bulls_power",
        "BearsPower",
        {},
        "one",
        "finite",
        None,
    ),
    "bulls_power_default_finite": (
        "backtrader.indicators.contrib.bulls_power",
        "BullsPower",
        {},
        "one",
        "finite",
        None,
    ),
    "blau_tstoch_default_finite": (
        "backtrader.indicators.contrib.blau_t_stoch_i",
        "BlauTStochI",
        {},
        "one",
        "finite",
        None,
    ),
    "blau_tvi_default_finite": (
        "backtrader.indicators.contrib.blau_tvi",
        "BlauTVI",
        {},
        "one",
        "finite",
        None,
    ),
    "breakout_default_finite": (
        "backtrader.indicators.contrib.breakout_bars_trend_v2",
        "BreakoutBarsTrendV2",
        {},
        "one",
        "finite",
        None,
    ),
    "bsi_default_finite": (
        "backtrader.indicators.contrib.bsi_indicator",
        "BSIIndicator",
        {},
        "one",
        "finite",
        None,
    ),
    "sma_finite": (
        "backtrader.indicators.sma",
        "MovingAverageSimple",
        {"period": 5},
        "close",
        "finite",
        5,
    ),
    "sma_missing": (
        "backtrader.indicators.sma",
        "MovingAverageSimple",
        {"period": 5},
        "close",
        "missing",
        5,
    ),
    "arrows_finite": (
        "backtrader.indicators.contrib.arrows_curves_indicator",
        "ArrowsCurvesIndicator",
        {"ssp": 3, "relay": 1},
        "one",
        "finite",
        None,
    ),
    "derivative_missing": (
        "backtrader.indicators.contrib.derivative_indicator",
        "DerivativeIndicator",
        {"i_slowing": 5, "applied_price": "PRICE_DEMARK"},
        "one",
        "missing",
        6,
    ),
    "derivative_short_history": (
        "backtrader.indicators.contrib.derivative_indicator",
        "DerivativeIndicator",
        {"i_slowing": 200, "applied_price": "PRICE_CLOSE"},
        "one",
        "finite",
        None,
    ),
    "spread_finite": (
        "backtrader.indicators.spread",
        "SpreadZScore",
        {"period": 10},
        "two",
        "finite",
        None,
    ),
    "aroon_horn_finite": (
        "backtrader.indicators.contrib.aroon_horn_sign_indicator",
        "AroonHornSignIndicator",
        {},
        "one",
        "finite",
        None,
    ),
    "aroon_horn_high_missing": (
        "backtrader.indicators.contrib.aroon_horn_sign_indicator",
        "AroonHornSignIndicator",
        {},
        "one",
        "high_missing",
        None,
    ),
}

# Statically reviewed one-feed/default finite samples only; see static_review_r3.py.
EXTRA_CLASSES = (
    ("candle_stop_color", "CandleStopColor"),
    ("cci_woodies_indicator", "CCIWoodiesIndicator"),
    ("cg_oscillator", "CGOscillator"),
    ("close_price_fractals", "ClosePriceFractals"),
    ("color_hma", "ColorHMA"),
    ("color_metro_wpr_indicator", "ColorMetroWprIndicator"),
    ("color_x2_ma", "ColorX2MA"),
    ("darvas_boxes_system", "DarvasBoxesSystem"),
    ("dots_indicator", "DotsIndicator"),
    ("ef_distance_indicator", "EFDistanceIndicator"),
    ("ema_rsi_va", "EmaRsiVa"),
    ("envelopes_jp_alonso", "EnvelopesJpAlonso"),
    ("f2a_ao_indicator", "F2aAOIndicator"),
    ("fatl_filter", "FatlFilter"),
    ("fine_tuning_ma", "FineTuningMA"),
    ("fisher_org_v1", "FisherOrgV1"),
    ("fisher_org_v1_sign", "FisherOrgV1Sign"),
    ("force_index_ema", "ForceDiverSign"),
    ("force_index_ema", "ForceIndexEMA"),
    ("force_index_ema_2", "ForceIndexEma"),
    ("forecast_oscilator", "ForecastOscilator"),
    ("fractal_amambk", "FractalAMAMBK"),
    ("frasm_av2_indicator", "FRASMAv2Indicator"),
)
if len({cls for _, cls in EXTRA_CLASSES}) != len(EXTRA_CLASSES):
    raise ValueError("duplicate indicator class name in pilot allowlist")
CASES.update(
    {
        "r4_" + cls: (
            "backtrader.indicators.contrib." + mod,
            cls,
            {},
            "one",
            "finite",
            None,
        )
        for mod, cls in EXTRA_CLASSES
    }
)

BLOCKED = (
    "backtrader.stores.btapi",
    "backtrader.brokers.btapi",
    "backtrader.brokers._btapi",
    "backtrader.feeds.btapi",
    "backtrader.feeds._btapi",
    "backtrader.service",
    "backtrader.execution",
    "backtrader.factor_execution",
    "backtrader.live_state",
    "bt_api_py",
    "bt_api_",
)


def source_hash(module):
    path = SNAPSHOT.joinpath(*module.split(".")).with_suffix(".py")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash():
    digest = hashlib.sha256()
    for path in sorted(p for p in SNAPSHOT.rglob("*") if p.is_file()):
        name = path.relative_to(SNAPSHOT).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(hashlib.sha256(raw).digest())
    return digest.hexdigest()


def serial(value):
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "+inf" if value > 0 else "-inf"
    return value


def child(case_name, runonce):
    import importlib
    import importlib.abc
    import importlib.machinery
    import io
    import types

    class Limited(io.TextIOBase):
        def __init__(self):
            self.count = 0

        def write(self, text):
            self.count += len(text)
            if self.count > 8192:
                raise RuntimeError("captured output exceeded 8192 characters")
            return len(text)

        def flush(self):
            pass

    output = sys.stdout
    sys.stdout = sys.stderr = Limited()
    case = CASES[case_name]
    denied = []

    class InsufficientHistory(Exception):
        pass

    class DenyFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname.startswith(prefix) for prefix in BLOCKED):
                denied.append("excluded_import:" + fullname)
                raise ImportError("excluded component")
            if (
                fullname.startswith("backtrader.indicators.contrib.")
                and fullname != case[0]
            ):
                denied.append("unreviewed_contrib_import:" + fullname)
                raise ImportError("unreviewed indicator dependency")

    sys.meta_path.insert(0, DenyFinder())
    sys.path.insert(0, str(SNAPSHOT))
    os.environ["BACKTRADER_LIGHT_IMPORT"] = "1"

    # Do not execute stores, observers, sizers, or bulk contrib initializers.
    def stub(name, path):
        module = types.ModuleType(name)
        module.__package__ = name
        module.__path__ = [str(path)]
        module.__spec__ = importlib.machinery.ModuleSpec(
            name, loader=None, is_package=True
        )
        module.__spec__.submodule_search_locations = module.__path__
        sys.modules[name] = module

    stub("backtrader.stores", SNAPSHOT / "backtrader/stores")
    stub("backtrader.indicators.contrib", SNAPSHOT / "backtrader/indicators/contrib")
    stub("backtrader.observers", SNAPSHOT / "backtrader/observers")
    stub("backtrader.sizers", SNAPSHOT / "backtrader/sizers")

    roots = [
        os.path.normcase(os.path.realpath(str(p)))
        for p in (SNAPSHOT, Path(sys.prefix), Path(sys.base_prefix))
    ]

    def audit(event, args):
        if event.startswith("socket.") or event in (
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.spawn",
        ):
            denied.append("operation:" + event)
            raise PermissionError("operation denied")
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(ch in mode for ch in "wax+")) or (
                isinstance(flags, int)
                and flags
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            path = os.path.normcase(os.path.realpath(os.fsdecode(args[0])))
            if writing or not any(
                path == root or path.startswith(root + os.sep) for root in roots
            ):
                denied.append("file_write" if writing else "file_read_outside_roots")
                raise PermissionError("file access denied")

    sys.addaudithook(audit)
    try:
        checks = {}
        try:
            importlib.import_module("bt_api_py")
        except ImportError:
            checks["excluded_import"] = denied.pop() == "excluded_import:bt_api_py"
        try:
            (HERE / "nonexistent-public-sentinel").read_bytes()
        except PermissionError:
            checks["outside_read"] = denied.pop() == "file_read_outside_roots"
        try:
            sys.audit("socket.connect", None, None)
        except PermissionError:
            checks["network_audit"] = denied.pop() == "operation:socket.connect"
        if checks != {
            "excluded_import": True,
            "outside_read": True,
            "network_audit": True,
        }:
            raise RuntimeError("guard selfcheck failed")
        import backtrader as bt
        import pandas as pd
        from backtrader.feeds.pandafeed import PandasData
        from backtrader.sizers.fixedsize import FixedSize

        sys.modules["backtrader.sizers"].FixedSize = FixedSize
        bt.indicators.contrib = sys.modules["backtrader.indicators.contrib"]
        module = importlib.import_module(case[0])
        if not Path(bt.__file__).resolve().is_relative_to(SNAPSHOT.resolve()):
            raise RuntimeError("unexpected backtrader import origin")
        if not Path(module.__file__).resolve().is_relative_to(SNAPSHOT.resolve()):
            raise RuntimeError("unexpected indicator import origin")
        indicator_type = getattr(module, case[1])
        if indicator_type.__module__ != case[0] or indicator_type.__name__ != case[1]:
            raise RuntimeError("unexpected indicator class identity")
        bars = 128
        close = [100 + 0.11 * i + 1.7 * math.sin(i * 0.23) for i in range(bars)]
        frame = pd.DataFrame(
            {
                "open": [x - 0.2 for x in close],
                "high": [x + 1 for x in close],
                "low": [x - 1 for x in close],
                "close": close,
                "volume": [100 + i % 13 for i in range(bars)],
            },
            index=pd.date_range("2024-01-01", periods=bars, freq="h"),
        )
        other = frame.copy()
        other["close"] = [0.9 * x + math.sin(i * 0.11) for i, x in enumerate(close)]
        if case[4] == "missing":
            frame.loc[frame.index[55], "close"] = float("nan")
        if case[4] == "high_missing":
            frame.loc[frame.index[55], "high"] = float("nan")

        class Probe(bt.Strategy):
            def __init__(self):
                args = (
                    (self.data0.close,)
                    if case[3] == "close"
                    else (self.data0, self.data1)
                    if case[3] == "two"
                    else (self.data0,)
                )
                self.indicator = indicator_type(*args, **case[2])
                if (
                    type(self.indicator._minperiod) is int
                    and self.indicator._minperiod > bars
                ):
                    raise InsufficientHistory(self.indicator._minperiod)

            def stop(self):
                self.minperiod = self.indicator._minperiod
                aliases = list(self.indicator.lines.getlinealiases())
                lines = list(self.indicator.lines)
                if (
                    not aliases
                    or len(aliases) != len(lines)
                    or len(set(aliases)) != len(aliases)
                ):
                    raise ValueError("unsupported line layout")
                self.output_lines = {
                    name: [serial(x) for x in line.array]
                    for name, line in zip(aliases, lines)
                }

        class TraceCerebro(bt.Cerebro):
            def _runonce(self, runstrats):
                self.executed_mode = "once"
                return super()._runonce(runstrats)

            def _runnext(self, runstrats):
                self.executed_mode = "next"
                return super()._runnext(runstrats)

        engine = TraceCerebro(stdstats=False, runonce=runonce, preload=True)
        engine.adddata(
            PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
        )
        if case[3] == "two":
            engine.adddata(
                PandasData(
                    dataname=other, timeframe=bt.TimeFrame.Minutes, compression=60
                )
            )
        engine.addstrategy(Probe)
        strategy = engine.run()[0]
        feed = engine.datas[0]
        if feed._timeframe != bt.TimeFrame.Minutes or feed._compression != 60:
            raise RuntimeError(
                "feed timeframe metadata differs from pilot configuration"
            )
        imported = sorted(
            name
            for name, module in sys.modules.items()
            if name.startswith("backtrader.")
            and isinstance(module, types.ModuleType)
            and vars(module).get("__file__")
        )
        output_data = {
            "status": "completed",
            "actual_mode": getattr(engine, "executed_mode", None),
            "minperiod": strategy.minperiod,
            "lines": strategy.output_lines,
            "source": str(Path(bt.__file__).resolve()),
            "input_timeframe": "Minutes",
            "input_timeframe_code": int(feed._timeframe),
            "input_compression": feed._compression,
            "input_timezone": "naive",
            "denied": denied,
            "guard_selfchecks": checks,
            "loaded_backtrader_modules": imported,
        }
    except InsufficientHistory as exc:
        output_data = {
            "status": "insufficient_history",
            "required": exc.args[0],
            "available": bars,
            "denied": denied,
            "guard_selfchecks": checks,
        }
    except Exception as exc:  # noqa: BLE001 -- classify child failures, including denied operations
        frames = []
        traceback = exc.__traceback__
        while traceback:
            code = traceback.tb_frame.f_code
            frames.append(
                {
                    "file": Path(code.co_filename).name,
                    "function": code.co_name,
                    "line": traceback.tb_lineno,
                }
            )
            traceback = traceback.tb_next
        output_data = {
            "status": "denied" if denied else "error",
            "error_type": type(exc).__name__,
            "missing_module": exc.name if isinstance(exc, ImportError) else None,
            "error_frames": frames[-12:],
            "denied": denied,
        }
    print(json.dumps(output_data, allow_nan=False), file=output)


def invoke(name, mode, timeout):
    allowed_env = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
    env = {key: os.environ[key] for key in allowed_env if key in os.environ}
    env["BACKTRADER_LIGHT_IMPORT"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "--child",
                name,
                str(int(mode)),
            ],
            cwd=SNAPSHOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    if result.returncode:
        return {
            "status": "child_failed",
            "returncode": result.returncode,
            "stderr_tail": result.stderr[-1000:],
        }
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        return {"status": "protocol_error", "stdout_length": len(result.stdout)}


def compare(name, left, right):
    if left.get("denied") or right.get("denied"):
        return {"status": "denied_caught"}
    if left.get("status") == right.get("status") == "insufficient_history":
        required_a = left.get("required")
        required_b = right.get("required")
        if type(required_a) is not int or type(required_b) is not int:
            return {"status": "minperiod_unsupported_type"}
        if required_a != required_b:
            return {"status": "minperiod_mismatch"}
        if (
            required_a <= 128
            or left.get("available") != 128
            or right.get("available") != 128
        ):
            return {"status": "inconsistent_short_history_report"}
        return {
            "status": "insufficient_history",
            "next_required": required_a,
            "once_required": required_b,
            "available": 128,
        }
    if left.get("status") != "completed" or right.get("status") != "completed":
        return {
            "status": "execution_not_completed",
            "next_status": left.get("status"),
            "once_status": right.get("status"),
        }
    if (left["actual_mode"], right["actual_mode"]) != ("next", "once"):
        return {"status": "mode_not_exercised"}
    if left["minperiod"] != right["minperiod"]:
        return {"status": "minperiod_mismatch"}
    if type(left["minperiod"]) is not int:
        return {"status": "minperiod_unsupported_type"}
    if left["minperiod"] < 1:
        return {"status": "minperiod_invalid"}
    if left["minperiod"] > 128:
        return {
            "status": "insufficient_history",
            "required": left["minperiod"],
            "available": 128,
        }
    expected = CASES[name][5]
    if expected is not None and left["minperiod"] != expected:
        return {"status": "independent_minperiod_mismatch", "expected": expected}
    a, b = left["lines"], right["lines"]
    if a.keys() != b.keys() or any(len(a[k]) != 128 or len(b[k]) != 128 for k in a):
        return {"status": "line_layout_mismatch"}
    differences = []
    nonfinite_only = []
    for key in a:
        if not any(
            isinstance(x, (int, float)) for x in a[key][left["minperiod"] - 1 :]
        ):
            nonfinite_only.append(key)
        for i, (x, y) in enumerate(zip(a[key], b[key])):
            equal = (
                x == y
                if isinstance(x, str) or isinstance(y, str)
                else math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-12)
            )
            if not equal:
                differences.append({"line": key, "index": i, "next": x, "once": y})
    oracle_differences = []
    if name in ("sma_finite", "sma_missing"):
        close = [100 + 0.11 * i + 1.7 * math.sin(i * 0.23) for i in range(128)]
        if name == "sma_missing":
            close[55] = float("nan")
        for i, value in enumerate(next(iter(a.values()))):
            window = close[i - 4 : i + 1] if i >= 4 else []
            expected_value = (
                math.fsum(window) / 5
                if window and not any(math.isnan(x) for x in window)
                else "nan"
            )
            same = (
                value == expected_value
                if isinstance(value, str) or isinstance(expected_value, str)
                else math.isclose(value, expected_value, rel_tol=1e-10, abs_tol=1e-12)
            )
            if not same:
                oracle_differences.append(
                    {"index": i, "actual": value, "expected": expected_value}
                )
    status = (
        "values_mismatch"
        if differences
        else "oracle_mismatch"
        if oracle_differences
        else "inconclusive_all_nonfinite"
        if nonfinite_only
        else "parity_sample"
    )
    return {
        "status": status,
        "differences_count": len(differences),
        "first_differences": differences[:5],
        "all_nonfinite_lines": nonfinite_only,
        "independent_minperiod": expected is not None,
        "oracle": "independent_sma_window"
        if name.startswith("sma_")
        else "not_provided",
        "oracle_differences_count": len(oracle_differences),
        "oracle_first_differences": oracle_differences[:5],
        "line_count": len(a),
        "bars_compared_per_line": 128,
        "nonzero_counts_post_minperiod": {
            key: sum(
                isinstance(x, (int, float)) and x != 0
                for x in values[left["minperiod"] - 1 :]
            )
            for key, values in a.items()
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=2, metavar=("CASE", "MODE"))
    parser.add_argument("--case", action="append")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child[0], bool(int(args.child[1])))
        return
    if args.timeout <= 0 or args.timeout > 60:
        parser.error("timeout must be in (0, 60]")
    rows = []
    for name in args.case or CASES:
        if name not in CASES:
            rows.append(
                {"case": name, "comparison": {"status": "unsupported_unreviewed"}}
            )
            print(name, "unsupported_unreviewed", file=sys.stderr, flush=True)
            continue
        tree_before = tree_hash()
        pin_before = source_hash(CASES[name][0])
        step = invoke(name, False, args.timeout)
        once = invoke(name, True, args.timeout)
        pin_after = source_hash(CASES[name][0])
        tree_after = tree_hash()
        verdict = (
            compare(name, step, once)
            if pin_before == pin_after and tree_before == tree_after
            else {"status": "source_changed"}
        )
        rows.append(
            {
                "case": name,
                "case_spec": CASES[name],
                "source_sha256": pin_before,
                "snapshot_tree_sha256": tree_before,
                "next": step,
                "once": once,
                "comparison": verdict,
            }
        )
        print(name, verdict["status"], file=sys.stderr, flush=True)
    report = {
        "head": HEAD,
        "scope": "selected classes and synthetic samples only; restricted package assembly",
        "python": sys.version,
        "cases": rows,
    }
    raw = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        target = args.out.resolve()
        if target.parent != HERE:
            parser.error("output must be directly under harness directory")
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
    else:
        print(raw)


if __name__ == "__main__":
    main()
