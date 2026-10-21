"""External installed-wheel QA; run only after a committed Backtrader wheel is installed.

Invoke with the prepared no-fincore interpreter using ``-I``. This file never
adds a repository path to sys.path and uses only synthetic in-memory inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any

SCRIPT = Path(__file__).resolve()
ARTIFACT_ROOT = SCRIPT.parent
REPOSITORY_SOURCE = Path(r"D:\source_code\backtrader").resolve()


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _assert_isolated_external_process() -> None:
    if sys.flags.isolated != 1:
        raise RuntimeError("this acceptance must run in a fresh Python -I process")
    if _under(Path.cwd(), REPOSITORY_SOURCE):
        raise RuntimeError("working directory must remain outside the Backtrader source tree")
    for entry in sys.path:
        candidate = Path(entry or Path.cwd())
        if candidate.exists() and _under(candidate, REPOSITORY_SOURCE):
            raise RuntimeError("Backtrader repository source appeared on sys.path")


def _require_no_fincore() -> None:
    if any(
        (dist.metadata.get("Name") or "").lower().replace("-", "") == "fincore"
        for dist in metadata.distributions()
    ):
        raise RuntimeError("fincore distribution must not be installed in this venv")
    if importlib.util.find_spec("fincore") is not None:
        raise RuntimeError("fincore must not be importable in this venv")
    if any(name == "fincore" or name.startswith("fincore.") for name in sys.modules):
        raise RuntimeError("fincore must not be loaded in this process")


def _installed_origin(module: Any) -> str:
    origin = Path(module.__file__).resolve()
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
    if not _under(origin, purelib):
        raise RuntimeError(f"{module.__name__} did not load from this venv: {origin}")
    if _under(origin, REPOSITORY_SOURCE):
        raise RuntimeError(f"{module.__name__} resolved to repository source: {origin}")
    return str(origin)


def _plot_modules() -> set[str]:
    return {
        name
        for name in sys.modules
        if name == "backtrader.plot" or name.startswith("backtrader.plot.")
    }


def _worker_import_boundary() -> dict[str, Any]:
    _assert_isolated_external_process()
    _require_no_fincore()
    import backtrader as bt

    bt_origin = _installed_origin(bt)
    bt_version = metadata.version("backtrader")
    plot_baseline = sorted(_plot_modules())
    fincore_baseline = sorted(
        name for name in sys.modules if name == "fincore" or name.startswith("fincore.")
    )
    import backtrader.research as research

    plot_after_research = sorted(_plot_modules())
    fincore_after_research = sorted(
        name for name in sys.modules if name == "fincore" or name.startswith("fincore.")
    )
    research_origin = _installed_origin(research)
    fincore_spec_after = importlib.util.find_spec("fincore")
    added_plot = sorted(set(plot_after_research) - set(plot_baseline))
    added_fincore = sorted(set(fincore_after_research) - set(fincore_baseline))
    result = {
        "process_id": os.getpid(),
        "isolated": sys.flags.isolated == 1,
        "python": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "prefix": sys.prefix,
        "backtrader_version": bt_version,
        "backtrader_origin": bt_origin,
        "research_origin": research_origin,
        "plot_modules_after_plain_backtrader_import": plot_baseline,
        "plot_modules_after_research_import": plot_after_research,
        "plot_modules_added_by_research_import": added_plot,
        "fincore_modules_after_plain_backtrader_import": fincore_baseline,
        "fincore_modules_after_research_import": fincore_after_research,
        "fincore_spec_after_research_import": (
            None if fincore_spec_after is None else fincore_spec_after.origin
        ),
        "backtrader_version_attribute": getattr(bt, "__version__", None),
    }
    if added_plot or added_fincore or fincore_spec_after is not None:
        raise RuntimeError("research import changed the plot/fincore import boundary")
    return result


def _worker_roundtrip(output_dir: Path) -> dict[str, Any]:
    _assert_isolated_external_process()
    _require_no_fincore()
    import backtrader as bt
    import pandas as pd
    from backtrader.research import (
        DependencyError,
        FactorIndicator,
        FactorSpec,
        FactorStrategy,
        ResearchSpec,
        load_dataset,
        prealign_bars,
    )

    bt_origin = _installed_origin(bt)
    output_dir.mkdir(parents=True, exist_ok=True)
    times = pd.date_range(
        "2026-01-05 16:00:00+00:00",
        periods=6,
        freq="D",
        name="close_time",
    )
    grid = pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times)
    assets = ("ASSET_A", "ASSET_B")
    research = ResearchSpec(
        grid=grid,
        start=times[0],
        end=times[-1],
        targets=assets,
        source_timezone="UTC",
        snapshot_id="iteration45-no-fincore-installed-v1",
        price_basis="synthetic-unadjusted-close",
        calendar_id="synthetic-six-bar-v1",
        frequency="1session",
        groups={asset: "synthetic" for asset in assets},
    )
    frames = {}
    for asset_index, asset in enumerate(assets):
        close = [10.0 + asset_index * 100.0 + index for index in range(6)]
        frames[asset] = pd.DataFrame(
            {
                "open": [value - 0.5 for value in close],
                "high": [value + 1.0 for value in close],
                "low": [value - 1.0 for value in close],
                "close": close,
                "volume": [1000.0 + index for index in range(6)],
                "openinterest": [0.0] * 6,
            },
            index=times,
        )

    class SyntheticCloseFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        panel_mode = "next"

        @classmethod
        def lookback_h(cls) -> int:
            return 0

        def next(self) -> None:
            for data in self.datas:
                self.outputs[data].factor[0] = float(data.close[0])

    class CountingBroker(bt.brokers.BackBroker):
        def __init__(self) -> None:
            super().__init__()
            self.submit_count = 0
            self.cancel_count = 0

        def submit(self, *args: Any, **kwargs: Any) -> Any:
            self.submit_count += 1
            return super().submit(*args, **kwargs)

        def cancel(self, *args: Any, **kwargs: Any) -> Any:
            self.cancel_count += 1
            return super().cancel(*args, **kwargs)

    factor_spec = FactorSpec(
        name="close_factor",
        indicator=SyntheticCloseFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    broker = CountingBroker()
    cerebro.setbroker(broker)
    for asset in assets:
        aligned = prealign_bars(
            frames[asset], research, asset, data_version="synthetic-v1"
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={factor_spec.name: factor_spec},
    )
    strategy = cerebro.run(runonce=False, preload=True)[0]
    if (broker.submit_count, broker.cancel_count) != (0, 0):
        raise AssertionError("read-only Cerebro run submitted or cancelled orders")

    dataset = strategy.get_dataset()
    dataset_dir = output_dir / "dataset"
    dataset.save(dataset_dir)
    loaded = load_dataset(dataset_dir)
    if loaded.dataset_id != dataset.dataset_id:
        raise AssertionError("dataset ID changed across save/load")
    raw = loaded.raw_factors["close_factor"]
    if len(raw) != len(assets) * len(times) or int(raw.notna().sum()) != len(assets) * len(times):
        raise AssertionError("synthetic native factor panel is incomplete")

    dependency_error = None
    try:
        loaded.evaluate()
    except DependencyError as exc:
        dependency_error = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", None),
        }
    if dependency_error is None or dependency_error["code"] != "DEPENDENCY_UNAVAILABLE":
        raise AssertionError("evaluate() did not raise typed fincore dependency error")
    _require_no_fincore()
    if any(name == "fincore" or name.startswith("fincore.") for name in sys.modules):
        raise AssertionError("failed evaluation loaded a fincore module")

    manifest_path = dataset_dir / "manifest.json"
    result = {
        "process_id": os.getpid(),
        "isolated": sys.flags.isolated == 1,
        "python": sys.executable,
        "backtrader_version": metadata.version("backtrader"),
        "backtrader_origin": bt_origin,
        "assets": list(assets),
        "bar_count_per_asset": len(times),
        "factor_name": "close_factor",
        "factor_rows": len(raw),
        "factor_nonmissing_rows": int(raw.notna().sum()),
        "broker_submit_count": broker.submit_count,
        "broker_cancel_count": broker.cancel_count,
        "dataset_id": dataset.dataset_id,
        "loaded_dataset_id": loaded.dataset_id,
        "dataset_id_roundtrip_matches": loaded.dataset_id == dataset.dataset_id,
        "dataset_path": str(dataset_dir.resolve()),
        "dataset_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "dataset_file_count": sum(1 for path in dataset_dir.rglob("*") if path.is_file()),
        "evaluate_error": dependency_error,
        "fincore_spec_after_evaluate": importlib.util.find_spec("fincore"),
        "fincore_modules_loaded": sorted(
            name for name in sys.modules if name == "fincore" or name.startswith("fincore.")
        ),
    }
    result["fincore_spec_after_evaluate"] = (
        None if result["fincore_spec_after_evaluate"] is None else result["fincore_spec_after_evaluate"].origin
    )
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _worker_main(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.worker == "baseline":
        result = _worker_import_boundary()
        _write_json(output_dir / "baseline.json", result)
    elif args.worker == "roundtrip":
        result = _worker_roundtrip(output_dir)
        _write_json(output_dir / "roundtrip.json", result)
    else:
        raise ValueError(f"unknown worker {args.worker!r}")
    print(json.dumps(result, sort_keys=True))
    return 0


def _driver_main() -> int:
    _assert_isolated_external_process()
    _require_no_fincore()
    run_dir = Path(tempfile.mkdtemp(prefix="iteration45-no-fincore-run-", dir=ARTIFACT_ROOT))
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    results: dict[str, Any] = {}
    worker_errors: dict[str, str] = {}
    for worker in ("baseline", "roundtrip"):
        completed = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--worker", worker, "--output-dir", str(run_dir)],
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        (run_dir / f"{worker}.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (run_dir / f"{worker}.stderr.log").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            worker_errors[worker] = f"exit={completed.returncode}; see {worker}.stderr.log"
            continue
        results[worker] = json.loads(completed.stdout.strip().splitlines()[-1])
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    record = {
        "status": "PASS" if not worker_errors and pip_check.returncode == 0 else "FAIL",
        "acceptance": "COMMITTED_BACKTRADER_WHEEL_NO_FINCORE_INSTALLED_SOURCE_QA",
        "run_dir": str(run_dir),
        "python": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "fincore_distribution_installed": any(
            (dist.metadata.get("Name") or "").lower().replace("-", "") == "fincore"
            for dist in metadata.distributions()
        ),
        "fincore_spec": (
            None if importlib.util.find_spec("fincore") is None
            else importlib.util.find_spec("fincore").origin
        ),
        "pip_check": pip_check.stdout.strip(),
        "pip_check_exit_code": pip_check.returncode,
        "workers": results,
        "worker_errors": worker_errors,
    }
    _write_json(run_dir / "acceptance.json", record)
    print(json.dumps(record, sort_keys=True))
    return 0 if record["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("baseline", "roundtrip"))
    parser.add_argument("--output-dir", default=str(ARTIFACT_ROOT))
    args = parser.parse_args()
    if args.worker:
        _assert_isolated_external_process()
        return _worker_main(args)
    return _driver_main()


if __name__ == "__main__":
    raise SystemExit(main())
