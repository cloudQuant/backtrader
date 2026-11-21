"""Pinned, synthetic Cerebro benchmark for the FindIndex R2 candidate.

This file is both orchestrator and isolated child. Results are created once at
an explicitly supplied new path; no source, index, or existing result is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

BASELINE_COMMIT = "535eaa80e9aa5b4a8002855f4f3b61da8e585e28"
ROOTS = {
    "baseline": Path("D:/temp/i71-index-baseline-535eaa80"),
    "candidate": Path("D:/temp/i71-index-inline-r2-535eaa80"),
}
BASICOPS_SHA256 = {
    "baseline": "cc06e9ddbc4d11fbac2dfd92e56ad22b702b9904d9d3028cbb9161e1fb3d568a",
    "candidate": "66e7f24598945a2e3cfeeec5362391143c3fcadaed4d0ac08d6c3469fb31ee7b",
}
PACKAGE_SHA256_EXCEPT_BASICOPS = "e9cea07e7387150f6d71e0d2d689d8e8ffc8c247fe392f154fb5206ce71e1d5e"
PACKAGE_FILE_COUNT = 697
SUPPORTED_VERSIONS = {
    "3.11.5": ("1.26.4", "2.2.3"),
    "3.14.2": ("2.4.1", "2.3.3"),
}
INDICATORS = (
    "FindFirstIndexHighest",
    "FindFirstIndexLowest",
    "FindLastIndexHighest",
    "FindLastIndexLowest",
)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_pin(root):
    package = root / "backtrader"
    paths = sorted(
        p
        for p in package.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")
    )
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(package).as_posix()
        if relative == "indicators/basicops.py":
            continue
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {
        "count": len(paths),
        "other_files_sha256": digest.hexdigest(),
        "basicops_sha256": file_hash(package / "indicators/basicops.py"),
    }


def verify_root(label):
    pin = package_pin(ROOTS[label])
    expected = {
        "count": PACKAGE_FILE_COUNT,
        "other_files_sha256": PACKAGE_SHA256_EXCEPT_BASICOPS,
        "basicops_sha256": BASICOPS_SHA256[label],
    }
    if pin != expected:
        raise RuntimeError(f"{label} snapshot pin mismatch: {pin}")
    return pin


def child(args):
    root = ROOTS[args.child].resolve()
    sys.path.insert(0, str(root))
    import numpy as np
    import pandas as pd
    import backtrader as bt
    import backtrader.indicators.basicops as ops

    python_version = ".".join(str(part) for part in sys.version_info[:3])
    if SUPPORTED_VERSIONS.get(python_version) != (np.__version__, pd.__version__):
        raise RuntimeError(
            f"unpinned dependency versions: python={python_version}, "
            f"numpy={np.__version__}, pandas={pd.__version__}"
        )
    origin = Path(ops.__file__).resolve()
    expected_origin = (root / "backtrader/indicators/basicops.py").resolve()
    if origin != expected_origin or file_hash(origin) != BASICOPS_SHA256[args.child]:
        raise RuntimeError("child source origin or hash mismatch")
    rng = random.Random(args.seed)
    close = [100.0 + rng.randrange(-500, 501) / 100.0 for _ in range(args.bars)]
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [v + 0.25 for v in close],
            "low": [v - 0.25 for v in close],
            "close": close,
            "volume": [1.0] * args.bars,
        },
        index=pd.date_range("2020-01-01", periods=args.bars, freq="min"),
    )
    source_hash = hashlib.sha256()
    source_hash.update(frame.index.asi8.astype("<i8", copy=False).tobytes())
    for key in ("open", "high", "low", "close", "volume"):
        source_hash.update(frame[key].to_numpy(dtype="<f8").tobytes())
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
    aggregate = hashlib.sha256()
    for name, indicator in zip(names, strategy.results):
        values = indicator.lines.index.array
        raw = values.tobytes()
        outputs[name] = {"length": len(values), "sha256": hashlib.sha256(raw).hexdigest()}
        if len(values) != args.bars:
            raise RuntimeError(f"{name} output length mismatch")
        encoded = name.encode("ascii")
        aggregate.update(len(encoded).to_bytes(4, "big"))
        aggregate.update(encoded)
        aggregate.update(len(raw).to_bytes(8, "big"))
        aggregate.update(raw)
    print(
        json.dumps(
            {
                "kind": args.child,
                "period": args.period,
                "count": args.count,
                "bars": args.bars,
                "seed": args.seed,
                "source_data_sha256": source_hash.hexdigest(),
                "output_arrays": outputs,
                "all_output_bytes_sha256": aggregate.hexdigest(),
                "elapsed_seconds": elapsed,
                "python_executable": str(Path(sys.executable).resolve()),
                "python_executable_sha256": file_hash(Path(sys.executable).resolve()),
                "python_version": sys.version,
                "platform": platform.platform(),
                "numpy_version": np.__version__,
                "numpy_origin": str(Path(np.__file__).resolve()),
                "numpy_init_sha256": file_hash(Path(np.__file__).resolve()),
                "pandas_version": pd.__version__,
                "pandas_origin": str(Path(pd.__file__).resolve()),
                "pandas_init_sha256": file_hash(Path(pd.__file__).resolve()),
                "backtrader_version": getattr(bt, "__version__", None),
                "basicops_origin": str(origin),
                "basicops_sha256": file_hash(origin),
            },
            sort_keys=True,
        )
    )


def parent(args):
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite result: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"result directory does not exist: {output.parent}")
    if args.pairs < 1 or args.bars < 1 or any(p < 1 or p > args.bars for p in args.periods):
        raise ValueError("require pairs >= 1 and 1 <= every period <= bars")
    if not args.counts or any(c not in (1, 2, 4) for c in args.counts):
        raise ValueError("counts must be selected from 1, 2, and 4")
    if len(set(args.periods)) != len(args.periods) or len(set(args.counts)) != len(args.counts):
        raise ValueError("periods and counts must not repeat")
    before = {label: verify_root(label) for label in ROOTS}
    script = Path(__file__).resolve()
    script_sha = file_hash(script)
    empty_cache = script.parent / "__benchmark_no_bytecode_cache__"
    if empty_cache.exists():
        raise RuntimeError("benchmark bytecode cache path must be absent")
    child_environment = dict(os.environ)
    child_environment["PYTHONHASHSEED"] = "0"
    identity_keys = (
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "platform",
        "numpy_version",
        "numpy_origin",
        "numpy_init_sha256",
        "pandas_version",
        "pandas_origin",
        "pandas_init_sha256",
        "backtrader_version",
    )
    identity = None
    scenarios = []
    for scenario_number, (period, count) in enumerate(
        (p, c) for p in args.periods for c in args.counts
    ):
        samples = []
        expected_data = None
        expected_outputs = None
        for pair in range(args.pairs):
            order = ("baseline", "candidate")
            if (scenario_number + pair) % 2:
                order = order[::-1]
            observed = {}
            for label in order:
                command = [
                    sys.executable,
                    "-B",
                    "-X",
                    f"pycache_prefix={empty_cache}",
                    str(script),
                    "--child",
                    label,
                    "--period",
                    str(period),
                    "--count",
                    str(count),
                    "--bars",
                    str(args.bars),
                    "--seed",
                    str(args.seed),
                ]
                proc = subprocess.run(
                    command,
                    cwd=ROOTS[label],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=child_environment,
                )
                row = json.loads(proc.stdout)
                row["stderr"] = proc.stderr
                if (row["kind"], row["period"], row["count"], row["bars"], row["seed"]) != (
                    label,
                    period,
                    count,
                    args.bars,
                    args.seed,
                ):
                    raise RuntimeError("child scenario mismatch")
                child_identity = {key: row[key] for key in identity_keys}
                if identity is None:
                    identity = child_identity
                if identity != child_identity:
                    raise RuntimeError("interpreter or dependency identity changed across samples")
                signature = (row["output_arrays"], row["all_output_bytes_sha256"])
                if expected_data is None:
                    expected_data, expected_outputs = row["source_data_sha256"], signature
                if row["source_data_sha256"] != expected_data or signature != expected_outputs:
                    raise RuntimeError("complete output or synthetic data mismatch")
                observed[label] = row
            samples.append({"order": list(order), "measurements": observed})
        medians = {
            label: statistics.median(
                item["measurements"][label]["elapsed_seconds"] for item in samples
            )
            for label in ROOTS
        }
        scenarios.append(
            {
                "period": period,
                "count": count,
                "indicators": list(INDICATORS[:count]),
                "source_data_sha256": expected_data,
                "output_arrays": expected_outputs[0],
                "all_output_bytes_sha256": expected_outputs[1],
                "samples": samples,
                "median_seconds": medians,
                "candidate_over_baseline_median": medians["candidate"] / medians["baseline"],
            }
        )
        print(f"completed period={period} indicators={count}", flush=True)
    after = {label: verify_root(label) for label in ROOTS}
    if after != before or file_hash(script) != script_sha or empty_cache.exists():
        raise RuntimeError("source snapshot or benchmark script changed during measurements")
    result = {
        "baseline_commit": BASELINE_COMMIT,
        "script_sha256": script_sha,
        "snapshot_roots": {key: str(value.resolve()) for key, value in ROOTS.items()},
        "snapshot_pins_before": before,
        "snapshot_pins_after": after,
        "environment": identity,
        "bars": args.bars,
        "seed": args.seed,
        "pairs": args.pairs,
        "pythonhashseed": "0",
        "version_pins": SUPPORTED_VERSIONS,
        "scenarios": scenarios,
        "scope": "synthetic full Cerebro runonce; timing excludes synthetic frame and engine construction",
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    print(f"result: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="new JSON result path; never overwritten")
    parser.add_argument("--bars", type=int, default=20000)
    parser.add_argument("--periods", type=int, nargs="+", default=[32, 128, 512])
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=710159)
    parser.add_argument("--child", choices=tuple(ROOTS), help=argparse.SUPPRESS)
    parser.add_argument("--period", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--count", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.period is None or args.count not in (1, 2, 4):
            parser.error("invalid child scenario")
        child(args)
    elif not args.output:
        parser.error("--output is required")
    else:
        parent(args)


if __name__ == "__main__":
    main()
