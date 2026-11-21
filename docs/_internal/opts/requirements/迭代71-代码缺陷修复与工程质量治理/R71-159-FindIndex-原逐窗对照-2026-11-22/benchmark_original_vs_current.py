"""Pair exact pre-FindIndex OperationN.once with current deque in Cerebro.

Both variants use the same current public snapshot and synthetic input. The
old method is compiled from the pinned 2bebe4e47 file and attached to the
current OperationN in the baseline child; all its globals resolve in the same
current module. The result must be a new file. No other source is modified.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("D:/temp/i71-index-original-window-c5fc2e7e")
CURRENT_COMMIT = "c5fc2e7e954eae104d4acae5accdd9bf30e9c44d"
OLD_COMMIT = "2bebe4e47"
OLD_SHA = "9382da9640e4229d8786afa9a522a8090a774eeab40424d1e25ce122c227fc32"
CURRENT_SHA = "c39958aef1b8d6e761ba1605e083d1acc51266ab5347e8b1b2a8a2f3261da058"
PACKAGE_SHA = "a727877846205c6b850ae812dbf7ecdfd4dcda3c7698992c3fc0079ecce9a7c2"
INDICATORS = (
    "FindFirstIndexHighest",
    "FindFirstIndexLowest",
    "FindLastIndexHighest",
    "FindLastIndexLowest",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot():
    package = ROOT / "backtrader"
    paths = sorted(
        p
        for p in package.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")
    )
    h = hashlib.sha256()
    for p in paths:
        encoded = p.relative_to(package).as_posix().encode("utf-8")
        h.update(len(encoded).to_bytes(4, "big"))
        h.update(encoded)
        h.update(hashlib.sha256(p.read_bytes()).digest())
    actual = {
        "count": len(paths),
        "package_sha256": h.hexdigest(),
        "old_sha256": digest(ROOT / "basicops_original_2bebe4e47.py"),
        "current_sha256": digest(package / "indicators/basicops.py"),
    }
    assert actual == {
        "count": 697,
        "package_sha256": PACKAGE_SHA,
        "old_sha256": OLD_SHA,
        "current_sha256": CURRENT_SHA,
    }, actual
    return actual


def original_once(module):
    raw = (ROOT / "basicops_original_2bebe4e47.py").read_bytes()
    if hashlib.sha256(raw).hexdigest() != OLD_SHA:
        raise RuntimeError("old source hash mismatch")
    tree = ast.parse(raw.decode("utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OperationN")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "once")
    namespace = {}
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "<2bebe4e47:OperationN.once>", "exec"),
        module.__dict__,
        namespace,
    )
    return namespace["once"]


def child(args):
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import pandas as pd
    import backtrader as bt
    import backtrader.indicators.basicops as ops

    if (
        Path(ops.__file__).resolve() != (ROOT / "backtrader/indicators/basicops.py").resolve()
        or digest(Path(ops.__file__)) != CURRENT_SHA
    ):
        raise RuntimeError("current source origin mismatch")
    if args.child == "old_window":
        ops.OperationN.once = original_once(ops)
    fast_calls = []
    original_fast = ops._once_monotonic_index

    def tracked(*a, **kw):
        fast_calls.append(1)
        return original_fast(*a, **kw)

    ops._once_monotonic_index = tracked
    random = np.random.default_rng(args.seed)
    close = 100.0 + random.integers(-500, 501, args.bars).astype("float64") / 100.0
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": np.ones(args.bars),
        },
        index=pd.date_range("2020-01-01", periods=args.bars, freq="min"),
    )
    h = hashlib.sha256()
    h.update(frame.index.asi8.astype("<i8", copy=False).tobytes())
    for col in ("open", "high", "low", "close", "volume"):
        h.update(frame[col].to_numpy(dtype="<f8").tobytes())
    names = INDICATORS[: args.count]

    class Probe(bt.Strategy):
        def __init__(self):
            self.results = [
                getattr(bt.ind, name)(self.data.close, period=args.period) for name in names
            ]

    engine = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    start = time.perf_counter()
    strategy = engine.run()[0]
    elapsed = time.perf_counter() - start
    outputs = {}
    all_hash = hashlib.sha256()
    for name, indicator in zip(names, strategy.results):
        values = indicator.lines.index.array
        raw = values.tobytes()
        if len(values) != args.bars:
            raise RuntimeError("unexpected output length")
        outputs[name] = {"length": len(values), "sha256": hashlib.sha256(raw).hexdigest()}
        encoded = name.encode("ascii")
        all_hash.update(len(encoded).to_bytes(4, "big"))
        all_hash.update(encoded)
        all_hash.update(len(raw).to_bytes(8, "big"))
        all_hash.update(raw)
    if args.child == "old_window" and fast_calls:
        raise RuntimeError("old method unexpectedly reached deque")
    if args.child == "current" and args.period >= 32 and not fast_calls:
        raise RuntimeError("current deque not reached")
    print(
        json.dumps(
            {
                "kind": args.child,
                "bars": args.bars,
                "period": args.period,
                "count": args.count,
                "seed": args.seed,
                "elapsed_seconds": elapsed,
                "source_data_sha256": h.hexdigest(),
                "output_arrays": outputs,
                "all_output_bytes_sha256": all_hash.hexdigest(),
                "deque_calls": len(fast_calls),
                "python": sys.version,
                "python_executable": str(Path(sys.executable).resolve()),
                "python_executable_sha256": digest(Path(sys.executable)),
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "platform": platform.platform(),
                "basicops_sha256": digest(Path(ops.__file__)),
            }
        )
    )


def parent(args):
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError(out)
    if not out.parent.is_dir():
        raise FileNotFoundError(out.parent)
    if (
        args.bars < 1
        or args.pairs < 1
        or any(p < 1 or p > args.bars for p in args.periods)
        or any(c not in (1, 2, 4) for c in args.counts)
    ):
        raise ValueError("invalid benchmark dimensions")
    before = verify_snapshot()
    script = Path(__file__).resolve()
    script_sha = digest(script)
    no_cache = ROOT / "__no_bytecode_cache__"
    if no_cache.exists():
        raise RuntimeError("cache prefix must be absent")
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    scenarios = []
    identity = None
    for scenario, (period, count) in enumerate((p, c) for p in args.periods for c in args.counts):
        samples = []
        signature = None
        for pair in range(args.pairs):
            order = (
                ("old_window", "current")
                if (scenario + pair) % 2 == 0
                else ("current", "old_window")
            )
            rows = {}
            for label in order:
                cmd = [
                    sys.executable,
                    "-B",
                    "-X",
                    f"pycache_prefix={no_cache}",
                    str(script),
                    "--child",
                    label,
                    "--bars",
                    str(args.bars),
                    "--period",
                    str(period),
                    "--count",
                    str(count),
                    "--seed",
                    str(args.seed),
                ]
                proc = subprocess.run(
                    cmd,
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True,
                )
                row = json.loads(proc.stdout)
                row["stderr"] = proc.stderr
                if (row["kind"], row["bars"], row["period"], row["count"], row["seed"]) != (
                    label,
                    args.bars,
                    period,
                    count,
                    args.seed,
                ):
                    raise RuntimeError("child mismatch")
                this_identity = tuple(
                    row[k]
                    for k in (
                        "python",
                        "python_executable",
                        "python_executable_sha256",
                        "numpy",
                        "pandas",
                        "platform",
                    )
                )
                if identity is None:
                    identity = this_identity
                if identity != this_identity:
                    raise RuntimeError("runtime changed")
                sig = (
                    row["source_data_sha256"],
                    row["output_arrays"],
                    row["all_output_bytes_sha256"],
                )
                if signature is None:
                    signature = sig
                if signature != sig:
                    raise RuntimeError("complete output mismatch")
                rows[label] = row
            samples.append({"order": order, "measurements": rows})
        medians = {
            k: statistics.median(x["measurements"][k]["elapsed_seconds"] for x in samples)
            for k in ("old_window", "current")
        }
        scenarios.append(
            {
                "period": period,
                "count": count,
                "samples": samples,
                "median_seconds": medians,
                "current_over_old_median": medians["current"] / medians["old_window"],
                "output_arrays": signature[1],
                "all_output_bytes_sha256": signature[2],
                "source_data_sha256": signature[0],
            }
        )
        print("completed", period, count, scenarios[-1]["current_over_old_median"], flush=True)
    after = verify_snapshot()
    if after != before or digest(script) != script_sha or no_cache.exists():
        raise RuntimeError("snapshot changed")
    report = {
        "current_commit": CURRENT_COMMIT,
        "old_method_commit": OLD_COMMIT,
        "script_sha256": script_sha,
        "snapshot_before": before,
        "snapshot_after": after,
        "bars": args.bars,
        "seed": args.seed,
        "pairs": args.pairs,
        "scenarios": scenarios,
        "scope": "Cerebro runonce; exact old method compiled against current module globals; synthetic data; frame and engine construction outside timer",
    }
    with out.open("x", encoding="utf-8", newline="\n") as fp:
        json.dump(report, fp, indent=2)
        fp.write("\n")
    print("result", out, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output")
    p.add_argument("--bars", type=int, default=20000)
    p.add_argument("--periods", type=int, nargs="+", default=[50, 128, 512])
    p.add_argument("--counts", type=int, nargs="+", default=[4])
    p.add_argument("--pairs", type=int, default=3)
    p.add_argument("--seed", type=int, default=710159)
    p.add_argument("--child", choices=("old_window", "current"))
    p.add_argument("--period", type=int)
    p.add_argument("--count", type=int)
    a = p.parse_args()
    if a.child:
        child(a)
    elif a.output:
        parent(a)
    else:
        p.error("--output required")


if __name__ == "__main__":
    main()
