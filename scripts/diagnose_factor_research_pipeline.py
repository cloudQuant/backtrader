"""Instrumented, non-gating diagnostics for factor-research pipeline stages.

This script is DIAGNOSTIC_ONLY. It calls the selected checkout's existing
``benchmark_factor_research.py`` entry implementation and adds observer hooks
for FactorStrategy callbacks, sink collection/finalization, panel construction,
alignment, pivots, complete panel CSV writes, and reports. It also provides a
20-asset, 243-grid-point 1/3/10-factor scaling diagnostic with two fixed
ten-asset groups and alternating close/open field bindings, plus a bounded
Alpha101 operator profile using the existing 320-row native fixture. The hooks
add overhead and are not performance acceptance evidence.

Example 500-symbol stage comparison (each output directory must be new)::

    /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python scripts/diagnose_factor_research_pipeline.py \\
        --mode stage --baseline-root /path/to/4ce64007 --candidate-root /path/to/dev \\
        --example 025 --symbols 500 \\
        --data-dir /path/to/backtrader/tests/datas/a_stocks --csv --report \\
        --evaluate --output /tmp/factor-stage-candidate

Example panel scaling diagnostic::

    /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python scripts/diagnose_factor_research_pipeline.py \\
        --mode scaling --root /path/to/checkout --symbols 20 \\
        --data-dir /path/to/backtrader/tests/datas/a_stocks --csv --report \\
        --output /tmp/factor-scaling

Example operator diagnostic::

    /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python scripts/diagnose_factor_research_pipeline.py \\
        --mode operators --root /path/to/checkout --profile-report \\
        --output /tmp/factor-operators

The output JSON records the exact worker command, root/source provenance,
input-manifest hashes, stage results, call counts, and RSS observation points.
The operators mode profiles only Cerebro.run and, when requested, one report
call; it records finite output counts and matching cProfile function records.
It does not instrument production indicator lifecycles or assert model-copy
counts. It never sums a nested sink/panel/CSV duration into the parent Cerebro
duration.
When the selected baseline predates FactorPanel and has no staged benchmark,
the script calls its real example ``run.py`` main in the isolated worker and
records the legacy Cerebro/get_dataset boundaries. Its ResearchDataset path is
reported separately from the candidate FactorPanel stages.
"""

from __future__ import annotations

import argparse
import datetime as dt
from functools import wraps
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

EXAMPLES = ("025", "026", "027")
EXAMPLE_DIRECTORIES = {
    "025": "025_factor_single",
    "026": "026_factor_multi",
    "027": "027_alpha003_panel_acceptance",
}
EXPECTED_SCALE = (1, 3, 10)
EXPECTED_SCALE_GRID = 243
EXPECTED_RESEARCH_GRID_ROWS = 243
OPERATOR_ALPHA_IDS = (5, 13, 29, 34, 48, 71, 100)
EXPECTED_EVALUATION_TABLES = (
    "signals.csv",
    "labels.csv",
    "ic.csv",
    "ic_summary.csv",
    "quantile_returns.csv",
    "turnover.csv",
    "spreads.csv",
    "stability.csv",
    "correlation.csv",
    "comparisons.csv",
    "coverage.csv",
    "diagnostics.csv",
)
DIAGNOSTIC_CLASS = "DIAGNOSTIC_ONLY"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(root: Path) -> Optional[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    value = result.stdout.strip()
    return value or None


def _rss_bytes() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss)


def _json_write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


class _Observer:
    """Small in-process observer. RSS samples are sparse at on_point scale."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.phase: Optional[str] = None
        self.metrics: Dict[str, Any] = {
            "factor_strategy": {"grid_callbacks": 0, "callback_time_s": 0.0, "rss_samples": []},
            "factor_spec_configuration": {
                "calls": 0,
                "factor_count": None,
                "factor_names": [],
                "factor_bindings": {},
                "indicator_instances": None,
                "boundary": None,
            },
            "scaling_actuals": {
                "cerebro_run_calls": 0,
                "strategy_count": 0,
                "factor_instance_count": None,
                "factor_indicator_tree_instance_count": None,
                "observed_after_run": False,
            },
            "factor_spec_assembly": {"calls": 0, "time_s": 0.0, "rss_bytes": {}},
            "sink": {
                "on_point_calls": 0,
                "on_point_factor_values": 0,
                "on_point_time_s": 0.0,
                "on_point_rss_samples": [],
                "finalize_calls": 0,
                "finalize_time_s": 0.0,
                "finalize_rss_bytes": {},
            },
            "panel": {"build_calls": 0, "build_time_s": 0.0, "build_rss_samples": []},
            "align": {"calls": 0, "time_s": 0.0, "rss_samples": []},
            "pandas_calls": {
                "dataframe_reindex_by_source": {},
                "series_reindex_by_source": {},
                "pivot_by_source": {},
                "dataframe_to_csv_by_source": {},
            },
            "csv": {"complete_panel_writes": 0, "complete_panel_write_time_s": 0.0},
            "report": {"calls": 0, "time_s": 0.0},
            "evaluation": {"calls": 0, "time_s": 0.0},
            "runtime_window": None,
        }
        self._restorers: List[Callable[[], None]] = []

    def add_restorer(self, restore: Callable[[], None]) -> None:
        self._restorers.append(restore)

    def restore(self) -> None:
        for restore in reversed(self._restorers):
            restore()
        self._restorers.clear()

    def source_tag(self, filename: str) -> str:
        try:
            return Path(filename).resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return Path(filename).name

    def count_source(self, bucket: str, filename: str) -> None:
        counts = self.metrics["pandas_calls"][bucket]
        source = self.source_tag(filename)
        counts[source] = int(counts.get(source, 0)) + 1


def _patch_method(
    observer: _Observer, owner: Any, name: str, wrapper_factory: Callable[..., Any]
) -> None:
    original = getattr(owner, name)
    setattr(owner, name, wrapper_factory(original))
    observer.add_restorer(lambda: setattr(owner, name, original))


def _install_observers(root: Path, observer: _Observer) -> None:
    import importlib

    import pandas as pd

    sink_module = importlib.import_module("backtrader.research.sink")
    panel_module = importlib.import_module("backtrader.research.panel")
    align_module = importlib.import_module("backtrader.research.align")
    strategy_module = importlib.import_module("backtrader.research.factor_strategy")
    research_package = importlib.import_module("backtrader.research")

    original_sink = sink_module.MemorySink

    class ObservedMemorySink(original_sink):
        def on_point(
            self,
            when: Any,
            asset: str,
            values: Mapping[str, float],
            open_price: float,
            close_price: float,
            present: bool,
        ) -> None:
            metrics = observer.metrics["sink"]
            metrics["on_point_calls"] += 1
            metrics["on_point_factor_values"] += len(values)
            sample = metrics["on_point_calls"] == 1 or metrics["on_point_calls"] % 1000 == 0
            before = _rss_bytes() if sample else None
            started = time.perf_counter()
            try:
                super().on_point(when, asset, values, open_price, close_price, present)
            finally:
                metrics["on_point_time_s"] += time.perf_counter() - started
                if sample:
                    metrics["on_point_rss_samples"].append(
                        {
                            "call": metrics["on_point_calls"],
                            "rss_before_bytes": before,
                            "rss_after_bytes": _rss_bytes(),
                        }
                    )

        def finalize(self, context: Any) -> Any:
            metrics = observer.metrics["sink"]
            metrics["finalize_calls"] += 1
            metrics["finalize_rss_bytes"]["before"] = _rss_bytes()
            if metrics["on_point_calls"] and (
                not metrics["on_point_rss_samples"]
                or metrics["on_point_rss_samples"][-1]["call"] != metrics["on_point_calls"]
            ):
                metrics["on_point_rss_samples"].append(
                    {
                        "call": metrics["on_point_calls"],
                        "rss_before_bytes": None,
                        "rss_after_bytes": metrics["finalize_rss_bytes"]["before"],
                        "sample": "after_last_on_point_before_finalize",
                    }
                )
            started = time.perf_counter()
            previous_phase = observer.phase
            observer.phase = "sink_finalize"
            try:
                return super().finalize(context)
            finally:
                observer.phase = previous_phase
                metrics["finalize_time_s"] += time.perf_counter() - started
                metrics["finalize_rss_bytes"]["after"] = _rss_bytes()

    sink_module.MemorySink = ObservedMemorySink
    observer.add_restorer(lambda: setattr(sink_module, "MemorySink", original_sink))

    original_panel_init = panel_module.FactorPanel.__init__

    @wraps(original_panel_init)
    def observed_panel_init(instance: Any, *args: Any, **kwargs: Any) -> None:
        metrics = observer.metrics["panel"]
        metrics["build_calls"] += 1
        rss_sample = {
            "build": metrics["build_calls"],
            "parent_phase": observer.phase,
            "rss_before_bytes": _rss_bytes(),
        }
        metrics["build_rss_samples"].append(rss_sample)
        started = time.perf_counter()
        previous_phase = observer.phase
        observer.phase = "panel_build"
        try:
            original_panel_init(instance, *args, **kwargs)
        finally:
            observer.phase = previous_phase
            metrics["build_time_s"] += time.perf_counter() - started
            rss_sample["rss_after_bytes"] = _rss_bytes()

    panel_module.FactorPanel.__init__ = observed_panel_init
    observer.add_restorer(
        lambda: setattr(panel_module.FactorPanel, "__init__", original_panel_init)
    )

    original_collect = strategy_module.FactorStrategy._collect_current_grid_point

    def observed_collect(instance: Any) -> Any:
        metrics = observer.metrics["factor_strategy"]
        next_cursor = int(getattr(instance, "_grid_cursor", 0))
        before = _rss_bytes()
        started = time.perf_counter()
        try:
            return original_collect(instance)
        finally:
            metrics["grid_callbacks"] += 1
            metrics["callback_time_s"] += time.perf_counter() - started
            metrics["rss_samples"].append(
                {
                    "grid_cursor_before": next_cursor,
                    "rss_before_bytes": before,
                    "rss_after_bytes": _rss_bytes(),
                }
            )

    strategy_module.FactorStrategy._collect_current_grid_point = observed_collect
    observer.add_restorer(
        lambda: setattr(
            strategy_module.FactorStrategy, "_collect_current_grid_point", original_collect
        )
    )

    original_align = align_module.align_to_grid

    def observed_align(*args: Any, **kwargs: Any) -> Any:
        metrics = observer.metrics["align"]
        metrics["calls"] += 1
        rss_sample = {"call": metrics["calls"], "rss_before_bytes": _rss_bytes()}
        metrics["rss_samples"].append(rss_sample)
        started = time.perf_counter()
        previous_phase = observer.phase
        observer.phase = "align"
        try:
            return original_align(*args, **kwargs)
        finally:
            observer.phase = previous_phase
            metrics["time_s"] += time.perf_counter() - started
            rss_sample["rss_after_bytes"] = _rss_bytes()

    align_module.align_to_grid = observed_align
    observer.add_restorer(lambda: setattr(align_module, "align_to_grid", original_align))

    def pandas_wrapper(owner: Any, method: str, original: Callable[..., Any]) -> Callable[..., Any]:
        bucket = {
            (pd.DataFrame, "reindex"): "dataframe_reindex_by_source",
            (pd.Series, "reindex"): "series_reindex_by_source",
            (pd.DataFrame, "pivot"): "pivot_by_source",
            (pd.DataFrame, "to_csv"): "dataframe_to_csv_by_source",
        }[(owner, method)]

        @wraps(original)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            caller = sys._getframe(1).f_code.co_filename
            tag = observer.source_tag(caller)
            if tag.startswith("backtrader/research/"):
                counts = observer.metrics["pandas_calls"][bucket]
                counts[tag] = int(counts.get(tag, 0)) + 1
            return original(self, *args, **kwargs)

        return wrapped

    for owner, method in (
        (pd.DataFrame, "reindex"),
        (pd.Series, "reindex"),
        (pd.DataFrame, "pivot"),
        (pd.DataFrame, "to_csv"),
    ):
        _patch_method(
            observer,
            owner,
            method,
            lambda original, owner=owner, method=method: pandas_wrapper(owner, method, original),
        )

    original_panel_csv = panel_module.FactorPanel.to_csv

    @wraps(original_panel_csv)
    def observed_panel_csv(instance: Any, *args: Any, **kwargs: Any) -> Any:
        metrics = observer.metrics["csv"]
        metrics["complete_panel_writes"] += 1
        started = time.perf_counter()
        previous_phase = observer.phase
        observer.phase = "panel_csv"
        try:
            return original_panel_csv(instance, *args, **kwargs)
        finally:
            observer.phase = previous_phase
            metrics["complete_panel_write_time_s"] += time.perf_counter() - started

    panel_module.FactorPanel.to_csv = observed_panel_csv
    observer.add_restorer(lambda: setattr(panel_module.FactorPanel, "to_csv", original_panel_csv))

    original_report = research_package.write_factor_report

    @wraps(original_report)
    def observed_report(*args: Any, **kwargs: Any) -> Any:
        metrics = observer.metrics["report"]
        metrics["calls"] += 1
        started = time.perf_counter()
        try:
            return original_report(*args, **kwargs)
        finally:
            metrics["time_s"] += time.perf_counter() - started

    research_package.write_factor_report = observed_report
    observer.add_restorer(lambda: setattr(research_package, "write_factor_report", original_report))

    original_evaluate = research_package.evaluate_frames

    @wraps(original_evaluate)
    def observed_evaluate(*args: Any, **kwargs: Any) -> Any:
        metrics = observer.metrics["evaluation"]
        metrics["calls"] += 1
        started = time.perf_counter()
        try:
            return original_evaluate(*args, **kwargs)
        finally:
            metrics["time_s"] += time.perf_counter() - started

    research_package.evaluate_frames = observed_evaluate
    observer.add_restorer(lambda: setattr(research_package, "evaluate_frames", original_evaluate))


def _scaling_field_name(factor_index: int) -> str:
    """Alternate the same declared close alias over provided close/open feeds."""
    return "close" if factor_index % 2 == 0 else "open"


def _scaling_field_binding(factor_index: int) -> Dict[str, str]:
    return {"close": "feed:target:%s" % _scaling_field_name(factor_index)}


def _scaling_group_assignments(targets: Sequence[str]) -> Dict[str, str]:
    """Split the fixed scaling universe into two stable, explicit groups."""
    if len(targets) != 20:
        raise ValueError("scaling group assignment requires exactly 20 targets")
    midpoint = len(targets) // 2
    return {
        target: "scale_a" if index < midpoint else "scale_b" for index, target in enumerate(targets)
    }


def _group_members(groups: Mapping[str, str]) -> Dict[str, List[str]]:
    members: Dict[str, List[str]] = {}
    for target, group in groups.items():
        members.setdefault(group, []).append(target)
    return members


def _with_scaling_groups(research: Any) -> Any:
    """Rebuild a ResearchSpec through its public constructor with fixed groups."""
    from backtrader.research import ResearchSpec

    universe = None if research.universe_defaulted else research.universe
    return ResearchSpec(
        grid=research.grid,
        start=research.start,
        end=research.end,
        targets=research.targets,
        source_timezone=research.source_timezone,
        snapshot_id=research.snapshot_id,
        price_basis=research.price_basis,
        calendar_id=research.calendar_id,
        frequency=research.frequency,
        feed_time_kind=research.feed_time_kind,
        groups=_scaling_group_assignments(research.targets),
        universe=universe,
    )


def _binding_aware_scaling_indicator(base: Any) -> Any:
    """Make the diagnostic factor consume the explicit declared field binding."""
    import math

    from backtrader.indicators import SMA

    def initialize(self: Any) -> None:
        # Skip the 025 concrete initializer, which hardcodes data.close, while
        # retaining its normal FactorIndicator/Backtrader construction path.
        super(base, self).__init__()
        self._averages = {
            data: SMA(self.field("close", data), period=self.p.period) for data in self.datas
        }

    def next(self: Any) -> None:
        for data in self.datas:
            source = self.field("close", data)
            current = float(source[0])
            average = float(self._averages[data][0])
            value = math.nan
            if (
                len(data) >= self.p.period
                and math.isfinite(current)
                and math.isfinite(average)
                and average != 0.0
            ):
                value = current / average
            self.outputs[data].factor[0] = value

    namespace = {
        "__module__": base.__module__,
        "__qualname__": "_ScalingFieldBound%s" % base.__name__,
        "lines": tuple(base._factor_template_names()),
        "panel_mode": "next",
        "formula_fields": tuple(base.formula_fields),
        "__init__": initialize,
        "next": next,
    }
    return type(namespace["__qualname__"], (base,), namespace)


def _observe_research_window(stage: Any, observer: _Observer, *, scaling: bool = False) -> None:
    original = stage._research_spec

    @wraps(original)
    def observed_research_spec(*args: Any, **kwargs: Any) -> Any:
        research = original(*args, **kwargs)
        if scaling:
            research = _with_scaling_groups(research)
        grid = research.grid
        window = {
            "grid_rows": len(grid.index),
            "grid_start": str(grid.index[0]),
            "grid_end": str(grid.index[-1]),
            "research_start": str(research.start),
            "research_end": str(research.end),
            "target_count": len(research.targets),
            "targets": list(research.targets),
        }
        if scaling:
            groups = dict(research.groups)
            window["groups_by_target"] = groups
            window["group_members"] = _group_members(groups)
        observer.metrics["runtime_window"] = window
        return research

    stage._research_spec = observed_research_spec
    observer.add_restorer(lambda: setattr(stage, "_research_spec", original))


def _observe_factor_specs(stage: Any, observer: _Observer) -> None:
    original = stage._factor_specs

    @wraps(original)
    def observed_factor_specs(*args: Any, **kwargs: Any) -> Any:
        assembly = observer.metrics["factor_spec_assembly"]
        assembly["calls"] += 1
        assembly["rss_bytes"]["before"] = _rss_bytes()
        started = time.perf_counter()
        try:
            factors = original(*args, **kwargs)
            construction = observer.metrics["factor_spec_configuration"]
            construction["calls"] += 1
            construction["factor_count"] = len(factors)
            construction["factor_names"] = list(factors)
            construction["factor_bindings"] = {
                name: dict(spec.field_bindings) for name, spec in factors.items()
            }
            construction["boundary"] = (
                "FactorSpec configuration; indicator instances are created inside Cerebro.run"
            )
            return factors
        finally:
            assembly["time_s"] += time.perf_counter() - started
            assembly["rss_bytes"]["after"] = _rss_bytes()

    stage._factor_specs = observed_factor_specs
    observer.add_restorer(lambda: setattr(stage, "_factor_specs", original))


def _observe_completed_strategies(observer: _Observer) -> None:
    """Read factor instance counts from Cerebro's returned strategies."""
    import backtrader as bt

    original = bt.Cerebro.run

    @wraps(original)
    def observed_run(instance: Any, *args: Any, **kwargs: Any) -> Any:
        strategies = original(instance, *args, **kwargs)
        metrics = observer.metrics["scaling_actuals"]
        metrics["cerebro_run_calls"] += 1
        returned = list(strategies) if isinstance(strategies, (list, tuple)) else []
        metrics["strategy_count"] = len(returned)
        by_strategy = []
        total_instances = 0
        total_tree_instances = 0
        observed_any = False
        for strategy in returned:
            instances_by_name = getattr(strategy, "_factor_instances_by_name", None)
            if not isinstance(instances_by_name, Mapping):
                continue
            observed_any = True
            per_name = {name: len(instances) for name, instances in instances_by_name.items()}
            direct_count = sum(per_name.values())
            tree_count = sum(
                len(strategy._factor_tree(root))
                for instances in instances_by_name.values()
                for root in instances
            )
            total_instances += direct_count
            total_tree_instances += tree_count
            by_strategy.append(
                {
                    "factor_count": len(instances_by_name),
                    "instances_by_factor": per_name,
                    "factor_indicator_instances": direct_count,
                    "factor_indicator_tree_instances": tree_count,
                }
            )
        metrics.update(
            {
                "factor_instance_count": total_instances if observed_any else None,
                "factor_indicator_tree_instance_count": (
                    total_tree_instances if observed_any else None
                ),
                "by_strategy": by_strategy,
                "observed_after_run": observed_any,
            }
        )
        return strategies

    bt.Cerebro.run = observed_run
    observer.add_restorer(lambda: setattr(bt.Cerebro, "run", original))


def _input_manifest(data_dir: Path, symbols: int) -> Dict[str, Any]:
    manifest_path = data_dir / "_metadata" / "manifest.json"
    calendar_path = data_dir / "_metadata" / "observed_calendar.csv"
    if not manifest_path.is_file() or not calendar_path.is_file():
        raise FileNotFoundError(
            "data-dir requires _metadata/manifest.json and observed_calendar.csv"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(manifest["output"]["symbols"])
    if symbols and symbols < len(entries):
        step = len(entries) / float(symbols)
        selected = [entries[int(index * step)] for index in range(symbols)]
    else:
        selected = entries
    symbol_files = {}
    for item in selected:
        source = data_dir / item["file"]
        if not source.is_file():
            raise FileNotFoundError("missing selected symbol input: %s" % source)
        symbol_files[str(item["symbol"])] = _sha256(source)
    with calendar_path.open("r", encoding="utf-8", newline="") as source:
        grid_rows = max(0, sum(1 for _ in source) - 1)
    return {
        "data_dir": str(data_dir.resolve()),
        "manifest_sha256": _sha256(manifest_path),
        "calendar_sha256": _sha256(calendar_path),
        "calendar_rows": grid_rows,
        "requested_symbols": symbols,
        "selected_symbols": [str(item["symbol"]) for item in selected],
        "selected_symbol_file_sha256": symbol_files,
    }


_OPERATOR_PROFILE_NAMES = {
    "_read_window",
    "_read_panel_value",
    "_read_value",
    "_evaluate",
    "_evaluate_panel",
    "next",
    "nextstart",
}


def _operator_profile_summary(
    profile_stats: Mapping[Tuple[str, int, str], Tuple[Any, ...]],
    operators_path: Path,
) -> Dict[str, Any]:
    """Aggregate selected cProfile rows from the exact operators.py source."""
    expected = operators_path.resolve()
    aggregate: Dict[str, Dict[str, Any]] = {}
    details = []
    for (filename, line, function), values in profile_stats.items():
        try:
            source = Path(filename).resolve()
        except (OSError, RuntimeError):
            continue
        if source != expected or function not in _OPERATOR_PROFILE_NAMES:
            continue
        _primitive_calls, total_calls, total_time, cumulative_time = values[:4]
        row = aggregate.setdefault(
            function,
            {"ncalls": 0, "tottime_s": 0.0, "cumtime_s": 0.0},
        )
        row["ncalls"] += int(total_calls)
        row["tottime_s"] += float(total_time)
        row["cumtime_s"] += float(cumulative_time)
        details.append(
            {
                "file": str(source),
                "line": int(line),
                "function": function,
                "ncalls": int(total_calls),
                "tottime_s": float(total_time),
                "cumtime_s": float(cumulative_time),
            }
        )
    details.sort(key=lambda row: (row["function"], row["line"]))
    return {"by_function": aggregate, "rows": details}


def _report_profile_summary(
    profile_stats: Mapping[Tuple[str, int, str], Tuple[Any, ...]],
) -> Dict[str, Any]:
    """Keep report-boundary profiles limited to fincore label/weight/position work."""
    categories = {"labels": {}, "weights": {}, "positions": {}}
    details = []
    for (filename, line, function), values in profile_stats.items():
        normalized = str(filename).replace("\\", "/")
        if "/fincore/" not in normalized:
            continue
        lowered = function.casefold()
        matched = [category for category in categories if category.rstrip("s") in lowered]
        if not matched:
            continue
        _primitive_calls, total_calls, total_time, cumulative_time = values[:4]
        row = {
            "file": normalized,
            "line": int(line),
            "function": function,
            "ncalls": int(total_calls),
            "tottime_s": float(total_time),
            "cumtime_s": float(cumulative_time),
            "categories": matched,
        }
        details.append(row)
        for category in matched:
            bucket = categories[category].setdefault(
                function,
                {"ncalls": 0, "tottime_s": 0.0, "cumtime_s": 0.0},
            )
            bucket["ncalls"] += row["ncalls"]
            bucket["tottime_s"] += row["tottime_s"]
            bucket["cumtime_s"] += row["cumtime_s"]
    details.sort(key=lambda row: (row["file"], row["line"], row["function"]))
    return {"by_category": categories, "rows": details}


def _operator_worker(args: argparse.Namespace, root: Path, origins: Dict[str, str]) -> int:
    import cProfile
    import inspect
    import pstats

    import numpy as np
    import backtrader as bt
    import backtrader.research.operators as operators_module
    from backtrader.research import write_factor_report
    from backtrader.research.alpha101 import get_alpha
    from tests.test_utils.alpha101_native_harness import (
        alpha_name,
        make_positive_fixture,
        run_native_batch,
    )

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    frames = make_positive_fixture(periods=320)
    grid_rows = len(next(iter(frames.values())).index)
    if grid_rows != 320:
        raise ValueError("the operator diagnostic fixture must have 320 grid rows")
    input_rows = {str(name): len(frame.index) for name, frame in frames.items()}
    run_profile = cProfile.Profile()
    original_run = bt.Cerebro.run

    def profiled_run(cerebro: Any, *call_args: Any, **call_kwargs: Any) -> Any:
        run_profile.enable()
        try:
            return original_run(cerebro, *call_args, **call_kwargs)
        finally:
            run_profile.disable()

    bt.Cerebro.run = profiled_run
    started = time.perf_counter()
    try:
        strategy = run_native_batch(frames, OPERATOR_ALPHA_IDS, runonce=False)
    finally:
        elapsed_s = time.perf_counter() - started
        bt.Cerebro.run = original_run

    operators_path = root / "backtrader" / "research" / "operators.py"
    if not operators_path.is_file():
        raise FileNotFoundError("selected root lacks backtrader/research/operators.py")
    formula_sources = {}
    for alpha_id in OPERATOR_ALPHA_IDS:
        source_file = inspect.getsourcefile(get_alpha(alpha_id))
        if source_file is None:
            raise ImportError("could not locate Alpha%d source" % alpha_id)
        source = Path(source_file).resolve()
        try:
            relative = source.relative_to(root).as_posix()
        except ValueError as exc:
            raise ImportError(
                "Alpha%d resolved outside selected root: %s" % (alpha_id, source)
            ) from exc
        formula_sources[str(alpha_id)] = {"path": relative, "sha256": _sha256(source)}
    operator_origin = Path(operators_module.__file__).resolve()
    if operator_origin != operators_path.resolve():
        raise ImportError(
            "operators module resolved outside selected source file: %s" % operator_origin
        )
    origins["backtrader.research.operators"] = str(operator_origin)
    operator_profile = _operator_profile_summary(
        pstats.Stats(run_profile).stats,
        operators_path,
    )
    panel = strategy.get_panel()
    finite_counts = {}
    for name in panel.factor_order:
        values = panel.factors[name].to_numpy(dtype="float64")
        finite_counts[name] = {
            "finite_values": int(np.isfinite(values).sum()),
            "total_values": int(values.size),
        }
    expected_factor_names = [alpha_name(alpha_id) for alpha_id in OPERATOR_ALPHA_IDS]
    factor_order_matches = list(panel.factor_order) == expected_factor_names

    report_result: Dict[str, Any] = {
        "requested": bool(args.profile_report),
        "status": "NOT_REQUESTED",
    }
    if args.profile_report:
        report_path = work_dir / ("factor_report_%s.html" % alpha_name(OPERATOR_ALPHA_IDS[0]))
        report_profile = cProfile.Profile()
        report_started = time.perf_counter()
        try:
            report_profile.enable()
            generated = write_factor_report(
                panel,
                alpha_name(OPERATOR_ALPHA_IDS[0]),
                report_path,
                language="en",
            )
            report_profile.disable()
            resolved_report = Path(generated).resolve()
            report_result = {
                "requested": True,
                "status": (
                    "OK"
                    if resolved_report.is_file() and resolved_report.stat().st_size
                    else "INCOMPLETE"
                ),
                "path": str(resolved_report),
                "bytes": resolved_report.stat().st_size if resolved_report.is_file() else 0,
                "sha256": (
                    _sha256(resolved_report)
                    if resolved_report.is_file() and resolved_report.stat().st_size
                    else None
                ),
                "elapsed_s": time.perf_counter() - report_started,
                "profile": _report_profile_summary(pstats.Stats(report_profile).stats),
                "profile_scope": "one public backtrader.research.write_factor_report call only",
            }
        except Exception:
            report_profile.disable()
            report_result = {
                "requested": True,
                "status": "FAILED",
                "elapsed_s": time.perf_counter() - report_started,
                "error": traceback.format_exc(),
                "profile": _report_profile_summary(pstats.Stats(report_profile).stats),
            }

    source_hashes = {}
    for path in (
        root / "backtrader" / "research" / "operators.py",
        root / "backtrader" / "research" / "alpha101" / "__init__.py",
        root / "tests" / "test_utils" / "alpha101_native_harness.py",
    ):
        if path.is_file():
            source_hashes[path.relative_to(root).as_posix()] = _sha256(path)
    source_hashes["diagnose_factor_research_pipeline.py"] = _sha256(Path(__file__).resolve())
    output = {
        "classification": DIAGNOSTIC_CLASS,
        "mode": "operators",
        "runner_api": "tests.test_utils.alpha101_native_harness.run_native_batch",
        "root": str(root),
        "git_head": _git_head(root),
        "module_origins": origins,
        "source_hashes": source_hashes,
        "formula_sources": formula_sources,
        "profile_scope": "cProfile is enabled only during the actual Cerebro.run call in run_native_batch",
        "runonce": False,
        "fixture": {
            "builder": "make_positive_fixture(periods=320)",
            "asset_count": len(frames),
            "grid_rows": grid_rows,
            "asset_rows": input_rows,
        },
        "requested_alpha_ids": list(OPERATOR_ALPHA_IDS),
        "elapsed_s_including_harness_setup": elapsed_s,
        "operator_profile": operator_profile,
        "factor_order_matches_requested_ids": factor_order_matches,
        "finite_value_counts": finite_counts,
        "report_profile": report_result,
        "status": (
            "OK"
            if factor_order_matches
            and all(item["finite_values"] > 0 for item in finite_counts.values())
            and report_result["status"] not in ("FAILED", "INCOMPLETE")
            else "INCOMPLETE"
        ),
        "limitations": [
            "DIAGNOSTIC_ONLY; profiler overhead makes this unsuitable for a performance gate",
            "cProfile does not count semantic cache hits or infer mathematical contributions",
            "report profile includes only fincore functions whose names match labels, weights, or positions",
        ],
    }
    result_path = work_dir / "worker-result.json"
    _json_write(result_path, output)
    print(json.dumps({"status": output["status"], "result": str(result_path)}, ensure_ascii=False))
    return 0 if output["status"] == "OK" else 2


def _compare_input_window_contracts(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> Dict[str, Any]:
    baseline_observers = baseline.get("observers", {})
    candidate_observers = candidate.get("observers", {})
    baseline_input = baseline.get("input_manifest")
    candidate_input = candidate.get("input_manifest")
    baseline_window = baseline_observers.get("runtime_window")
    candidate_window = candidate_observers.get("runtime_window")
    baseline_factors = baseline_observers.get("factor_spec_configuration", {}).get("factor_names")
    candidate_factors = candidate_observers.get("factor_spec_configuration", {}).get("factor_names")

    def valid_input(value: Any) -> bool:
        return (
            isinstance(value, Mapping)
            and bool(value.get("manifest_sha256"))
            and bool(value.get("calendar_sha256"))
            and isinstance(value.get("selected_symbol_file_sha256"), Mapping)
            and bool(value["selected_symbol_file_sha256"])
        )

    def valid_window(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        targets = value.get("targets")
        return (
            isinstance(value.get("grid_rows"), int)
            and value["grid_rows"] > 0
            and bool(value.get("grid_start"))
            and bool(value.get("grid_end"))
            and bool(value.get("research_start"))
            and bool(value.get("research_end"))
            and isinstance(value.get("target_count"), int)
            and value["target_count"] > 0
            and isinstance(targets, list)
            and len(targets) == value["target_count"]
        )

    baseline_evidence_present = (
        valid_input(baseline_input)
        and valid_window(baseline_window)
        and isinstance(baseline_factors, list)
        and bool(baseline_factors)
    )
    candidate_evidence_present = (
        valid_input(candidate_input)
        and valid_window(candidate_window)
        and isinstance(candidate_factors, list)
        and bool(candidate_factors)
    )
    checks = {
        "baseline_evidence_present": baseline_evidence_present,
        "candidate_evidence_present": candidate_evidence_present,
        "input_manifest_matches": baseline_evidence_present
        and candidate_evidence_present
        and baseline_input == candidate_input,
        "runtime_window_matches": baseline_evidence_present
        and candidate_evidence_present
        and baseline_window == candidate_window,
        "factor_names_match": baseline_evidence_present
        and candidate_evidence_present
        and baseline_factors == candidate_factors,
    }
    return {"checks": checks, "all_match": all(checks.values())}


def _compare_scaling_workloads(
    runs: Sequence[Mapping[str, Any]], requested_counts: Sequence[int]
) -> Dict[str, Any]:
    profiles = [run for run in runs if run.get("mode") == "scaling"]
    by_count = {run.get("factor_count"): run for run in profiles}
    expected_counts = sorted(requested_counts)
    profile_counts = [run.get("factor_count") for run in profiles]
    all_profiles_present = (
        len(profiles) == len(expected_counts)
        and all(type(count) is int for count in profile_counts)
        and sorted(profile_counts) == expected_counts
        and len(profiles) == len(by_count)
    )
    reference = profiles[0] if profiles else {}
    reference_input = reference.get("input_manifest")
    reference_workload = reference.get("scaling_workload") or {}
    reference_targets = reference_workload.get("fixed_input_targets")
    reference_groups = reference_workload.get("groups_by_target")
    reference_members = reference_workload.get("group_members")
    input_evidence_valid = (
        isinstance(reference_input, Mapping)
        and bool(reference_input.get("manifest_sha256"))
        and bool(reference_input.get("calendar_sha256"))
        and isinstance(reference_input.get("selected_symbol_file_sha256"), Mapping)
        and len(reference_input["selected_symbol_file_sha256"]) == 20
    )
    input_frames_match = input_evidence_valid and all(
        run.get("input_manifest") == reference_input for run in profiles
    )
    targets_valid = isinstance(reference_targets, list) and len(reference_targets) == 20
    targets_match = targets_valid and all(
        (run.get("scaling_workload") or {}).get("fixed_input_targets") == reference_targets
        for run in profiles
    )
    groups_valid = (
        isinstance(reference_groups, Mapping)
        and set(reference_groups) == set(reference_targets or ())
        and len(set(reference_groups.values())) == 2
        and isinstance(reference_members, Mapping)
        and len(reference_members) == 2
        and all(isinstance(items, list) for items in reference_members.values())
        and sorted(len(items) for items in reference_members.values()) == [10, 10]
    )
    groups_match = groups_valid and all(
        (run.get("scaling_workload") or {}).get("groups_by_target") == reference_groups
        and (run.get("scaling_workload") or {}).get("group_members") == reference_members
        for run in profiles
    )
    per_profile_contracts = {}
    for count in expected_counts:
        run = by_count.get(count, {})
        workload = run.get("scaling_workload") or {}
        bindings = workload.get("factor_bindings")
        binding_fields = (
            [
                next(iter(binding.values())).rsplit(":", 1)[-1]
                for binding in bindings.values()
                if isinstance(binding, Mapping) and binding
            ]
            if isinstance(bindings, Mapping)
            else []
        )
        actuals = workload.get("actual_instances_after_run") or {}
        per_profile_contracts[str(count)] = {
            "worker_status_ok": run.get("status") == "OK" and run.get("worker_returncode") == 0,
            "binding_count_matches": isinstance(bindings, Mapping) and len(bindings) == count,
            "alternating_binding_order_matches": binding_fields
            == [_scaling_field_name(index) for index in range(count)],
            "actual_factor_instance_count_matches": actuals.get("observed_after_run") is True
            and actuals.get("factor_instance_count") == count * 2,
            "fixed_20_asset_group_contract_matches": isinstance(
                workload.get("fixed_input_targets"), list
            )
            and len(workload["fixed_input_targets"]) == 20
            and isinstance(workload.get("groups_by_target"), Mapping)
            and set(workload["groups_by_target"]) == set(workload["fixed_input_targets"])
            and isinstance(workload.get("group_members"), Mapping)
            and len(workload["group_members"]) == 2
            and all(isinstance(items, list) for items in workload["group_members"].values())
            and sorted(len(items) for items in workload["group_members"].values()) == [10, 10],
        }
    checks = {
        "all_requested_factor_counts_present": all_profiles_present,
        "same_input_file_hashes": input_frames_match,
        "same_20_input_targets": targets_match,
        "same_two_group_assignment": groups_match,
        "each_profile_contract_matches": all(
            all(profile.values()) for profile in per_profile_contracts.values()
        )
        and bool(per_profile_contracts),
    }
    return {
        "checks": checks,
        "per_profile_contracts": per_profile_contracts,
        "all_match": all(checks.values()),
    }


def _single_worker_example(value: Any) -> str:
    """Resolve one argparse append value at worker boundaries; never accept ambiguity."""
    if not isinstance(value, (list, tuple)) or len(value) != 1:
        raise ValueError("worker mode requires exactly one --example")
    example = value[0]
    if not isinstance(example, str) or example not in EXAMPLES:
        raise ValueError("worker example must be one of %s" % (EXAMPLES,))
    return example


def _load_stage_benchmark(root: Path) -> Any:
    path = Path(__file__).resolve().with_name("benchmark_factor_research.py")
    if not path.is_file():
        raise FileNotFoundError("host scripts/benchmark_factor_research.py is missing: %s" % path)
    spec = importlib.util.spec_from_file_location("_diagnostic_stage_benchmark", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load existing stage benchmark at %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected_root = root.resolve()
    module.REPO_ROOT = selected_root
    module.EXAMPLES = {
        example: selected_root / "examples" / "backtest" / EXAMPLE_DIRECTORIES[example]
        for example in EXAMPLES
    }
    return module


def _supports_current_stage(root: Path) -> bool:
    required = (
        root / "backtrader" / "research" / "align.py",
        root / "backtrader" / "research" / "panel.py",
        root / "backtrader" / "research" / "sink.py",
    )
    return all(path.is_file() for path in required)


def _load_example_entry(root: Path, example: str) -> Any:
    example_dir = root / "examples" / "backtest" / EXAMPLE_DIRECTORIES[example]
    path = example_dir / "run.py"
    if not path.is_file():
        raise FileNotFoundError("selected root lacks example entry: %s" % path)
    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))
    spec = importlib.util.spec_from_file_location("_diagnostic_entry_%s" % example, path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load example entry at %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_origins(root: Path) -> Dict[str, str]:
    import backtrader
    import backtrader.research

    origins = {
        "backtrader": str(Path(backtrader.__file__).resolve()),
        "backtrader.research": str(Path(backtrader.research.__file__).resolve()),
    }
    for name, value in origins.items():
        try:
            Path(value).relative_to(root.resolve())
        except ValueError as exc:
            raise ImportError("%s resolved outside selected root: %s" % (name, value)) from exc
    return origins


def _legacy_source_hashes(root: Path, example: str) -> Dict[str, str]:
    example_dir = root / "examples" / "backtest" / EXAMPLE_DIRECTORIES[example]
    paths = [example_dir / "run.py", example_dir / "config.yaml"]
    for path in example_dir.glob("*.py"):
        paths.append(path)
    research_dir = root / "backtrader" / "research"
    if research_dir.is_dir():
        paths.extend(research_dir.rglob("*.py"))
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(set(paths))
        if path.is_file()
    }


def _install_legacy_observers(root: Path, entry: Any, observer: _Observer) -> Dict[str, str]:
    import backtrader as bt
    import backtrader.research as research_package
    from backtrader.research.factor_strategy import FactorStrategy
    from backtrader.research import inputs as inputs_module

    origins = _module_origins(root)
    metrics = observer.metrics
    metrics["legacy_pipeline"] = {
        "load_daily_panel": {"calls": 0, "time_s": 0.0, "rss_bytes": {}},
        "collection_entry": {"calls": 0, "time_s": 0.0, "rss_bytes": {}},
        "cerebro_run": {"calls": 0, "time_s": 0.0, "cpu_s": 0.0, "rss_bytes": {}},
        "get_dataset": {"calls": 0, "time_s": 0.0, "rss_bytes": {}, "artifacts": {}},
        "prealign_bars": {"calls": 0, "time_s": 0.0, "rss_samples": []},
        "report": {"calls": 0, "time_s": 0.0, "rss_samples": []},
    }

    def time_and_rss(bucket: str, function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            stage = metrics["legacy_pipeline"][bucket]
            stage["calls"] += 1
            stage["rss_bytes"]["before"] = _rss_bytes()
            cpu_before = time.process_time()
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                stage["time_s"] += time.perf_counter() - started
                if "cpu_s" in stage:
                    stage["cpu_s"] += time.process_time() - cpu_before
                stage["rss_bytes"]["after"] = _rss_bytes()

        return wrapped

    original_load = entry.load_daily_panel

    @wraps(original_load)
    def observed_load(data_config: Mapping[str, Any]) -> Any:
        metrics["legacy_pipeline"]["load_daily_panel"]["calls"] += 1
        stage = metrics["legacy_pipeline"]["load_daily_panel"]
        stage["rss_bytes"]["before"] = _rss_bytes()
        started = time.perf_counter()
        try:
            panel = original_load(data_config)
            stage["panel"] = {
                "symbols": len(panel.get("assets", ())),
                "grid_rows": len(panel.get("grid", ())),
                "symbols_in_order": list(panel.get("assets", ())),
            }
            return panel
        finally:
            stage["time_s"] += time.perf_counter() - started
            stage["rss_bytes"]["after"] = _rss_bytes()

    entry.load_daily_panel = observed_load
    observer.add_restorer(lambda: setattr(entry, "load_daily_panel", original_load))

    original_research_spec = getattr(entry, "_create_research_spec", None)
    if original_research_spec is not None:

        @wraps(original_research_spec)
        def observed_research_spec(*args: Any, **kwargs: Any) -> Any:
            research = original_research_spec(*args, **kwargs)
            grid = research.grid
            metrics["runtime_window"] = {
                "grid_rows": len(grid),
                "grid_start": str(grid.index[0]),
                "grid_end": str(grid.index[-1]),
                "research_start": str(research.start),
                "research_end": str(research.end),
                "target_count": len(research.targets),
                "targets": list(research.targets),
            }
            return research

        entry._create_research_spec = observed_research_spec
        observer.add_restorer(
            lambda: setattr(entry, "_create_research_spec", original_research_spec)
        )

    collection_name = "_run_factor" if hasattr(entry, "_run_factor") else "_run_native_collection"
    original_collection = getattr(entry, collection_name)
    setattr(entry, collection_name, time_and_rss("collection_entry", original_collection))
    observer.add_restorer(lambda: setattr(entry, collection_name, original_collection))

    original_cerebro_run = bt.Cerebro.run
    metrics["legacy_pipeline"]["cerebro_run"]["rss_bytes"] = {}
    bt.Cerebro.run = time_and_rss("cerebro_run", original_cerebro_run)
    observer.add_restorer(lambda: setattr(bt.Cerebro, "run", original_cerebro_run))

    original_get_dataset = FactorStrategy.get_dataset

    @wraps(original_get_dataset)
    def observed_get_dataset(instance: Any, *args: Any, **kwargs: Any) -> Any:
        stage = metrics["legacy_pipeline"]["get_dataset"]
        stage["calls"] += 1
        stage["rss_bytes"]["before"] = _rss_bytes()
        started = time.perf_counter()
        try:
            dataset = original_get_dataset(instance, *args, **kwargs)
            research = getattr(instance, "_research", None)
            if research is None:
                research = getattr(instance, "_research_spec", None)
            if research is not None:
                grid = getattr(research, "grid", None)
                grid_index = getattr(grid, "index", grid)
                targets = list(getattr(research, "targets", getattr(dataset, "targets", ())))
                if grid_index is not None and len(grid_index):
                    observer.metrics["runtime_window"] = {
                        "grid_rows": len(grid_index),
                        "grid_start": str(grid_index[0]),
                        "grid_end": str(grid_index[-1]),
                        "research_start": str(getattr(research, "start", "")),
                        "research_end": str(getattr(research, "end", "")),
                        "target_count": len(targets),
                        "targets": targets,
                    }
                    observer.metrics["runtime_window_source"] = (
                        "FactorStrategy._research via get_dataset"
                    )
            stage["artifacts"] = {
                "factor_names": list(getattr(instance, "_factor_specs_by_name", {})),
                "symbols": len(getattr(dataset, "targets", ())),
                "grid_rows": len(getattr(dataset, "grid", ())),
            }
            return dataset
        finally:
            stage["time_s"] += time.perf_counter() - started
            stage["rss_bytes"]["after"] = _rss_bytes()

    FactorStrategy.get_dataset = observed_get_dataset
    observer.add_restorer(lambda: setattr(FactorStrategy, "get_dataset", original_get_dataset))

    original_collect = FactorStrategy._collect_current_grid_point

    @wraps(original_collect)
    def observed_collect(instance: Any, *args: Any, **kwargs: Any) -> Any:
        stage = metrics["factor_strategy"]
        cursor = int(getattr(instance, "_grid_cursor", 0))
        before = _rss_bytes()
        started = time.perf_counter()
        try:
            return original_collect(instance, *args, **kwargs)
        finally:
            stage["grid_callbacks"] += 1
            stage["callback_time_s"] += time.perf_counter() - started
            stage["rss_samples"].append(
                {
                    "grid_cursor_before": cursor,
                    "rss_before_bytes": before,
                    "rss_after_bytes": _rss_bytes(),
                }
            )

    FactorStrategy._collect_current_grid_point = observed_collect
    observer.add_restorer(
        lambda: setattr(FactorStrategy, "_collect_current_grid_point", original_collect)
    )

    original_prealign = inputs_module.prealign_bars

    @wraps(original_prealign)
    def observed_prealign(*args: Any, **kwargs: Any) -> Any:
        stage = metrics["legacy_pipeline"]["prealign_bars"]
        stage["calls"] += 1
        sample = {"call": stage["calls"], "rss_before_bytes": _rss_bytes()}
        stage["rss_samples"].append(sample)
        started = time.perf_counter()
        try:
            return original_prealign(*args, **kwargs)
        finally:
            stage["time_s"] += time.perf_counter() - started
            sample["rss_after_bytes"] = _rss_bytes()

    inputs_module.prealign_bars = observed_prealign
    observer.add_restorer(lambda: setattr(inputs_module, "prealign_bars", original_prealign))

    original_report = research_package.write_factor_report

    @wraps(original_report)
    def observed_report(*args: Any, **kwargs: Any) -> Any:
        stage = metrics["legacy_pipeline"]["report"]
        stage["calls"] += 1
        sample = {"call": stage["calls"], "rss_before_bytes": _rss_bytes()}
        stage["rss_samples"].append(sample)
        started = time.perf_counter()
        try:
            return original_report(*args, **kwargs)
        finally:
            stage["time_s"] += time.perf_counter() - started
            sample["rss_after_bytes"] = _rss_bytes()

    research_package.write_factor_report = observed_report
    observer.add_restorer(lambda: setattr(research_package, "write_factor_report", original_report))
    return origins


def _load_pair_validator() -> Any:
    path = Path(__file__).resolve().with_name("benchmark_factor_research_pair.py")
    if not path.is_file():
        raise FileNotFoundError("host paired benchmark validator is missing: %s" % path)
    spec = importlib.util.spec_from_file_location("_diagnostic_pair_validator", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load paired benchmark validator at %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_evaluation_table_contract(
    summary: Optional[Mapping[str, Any]], output_dir: Path, validator: Any
) -> Dict[str, Any]:
    if summary is None:
        return {"status": "FAILED", "expected": list(EXPECTED_EVALUATION_TABLES), "files": []}
    evaluation_id = summary.get("evaluation_id")
    if not isinstance(evaluation_id, str) or not evaluation_id:
        return {"status": "FAILED", "expected": list(EXPECTED_EVALUATION_TABLES), "files": []}
    evaluation_dir = output_dir / "evaluation" / evaluation_id
    if not validator._path_inside(evaluation_dir, output_dir / "evaluation"):
        return {
            "status": "FAILED",
            "path": str(evaluation_dir),
            "expected": list(EXPECTED_EVALUATION_TABLES),
            "files": [],
            "error": "evaluation output resolves outside the evaluation directory",
        }
    manifest_path = evaluation_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "status": "FAILED",
            "path": str(evaluation_dir),
            "expected": list(EXPECTED_EVALUATION_TABLES),
            "files": [],
            "error": "evaluation export manifest is missing or invalid",
        }
    exports = manifest.get("exports") if isinstance(manifest, Mapping) else None
    if not isinstance(exports, list) or any(not isinstance(item, str) for item in exports):
        exports = []
    declared_csv = []
    safe_exports = True
    for name in exports:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            safe_exports = False
            continue
        if relative.suffix.lower() == ".csv":
            declared_csv.append(relative.as_posix())
    actual_csv = (
        sorted(
            path.relative_to(evaluation_dir).as_posix()
            for path in evaluation_dir.rglob("*.csv")
            if path.is_file()
        )
        if evaluation_dir.is_dir()
        else []
    )
    expected = sorted(EXPECTED_EVALUATION_TABLES)
    table_files = []
    for relative in expected:
        path = evaluation_dir / relative
        stats = (
            validator._csv_stats(path)
            if path.is_file()
            else {
                "path": str(path),
                "exists": False,
                "rows": 0,
                "headers": [],
                "finite_values": {},
                "error": "CSV is missing",
            }
        )
        size_bytes = path.stat().st_size if path.is_file() else 0
        valid = bool(
            path.is_file()
            and size_bytes > 0
            and stats.get("error") is None
            and stats.get("headers")
        )
        table_files.append(
            {
                "name": relative,
                "path": str(path),
                "exists_nonempty_parseable": valid,
                "size_bytes": size_bytes,
                "rows": stats.get("rows", 0),
                "headers": stats.get("headers", []),
                "sha256": _sha256(path) if path.is_file() and size_bytes else None,
            }
        )
    exact = (
        safe_exports
        and sorted(declared_csv) == expected
        and actual_csv == expected
        and all(item["exists_nonempty_parseable"] for item in table_files)
    )
    return {
        "status": "OK" if exact else "FAILED",
        "path": str(evaluation_dir),
        "expected": expected,
        "declared": sorted(declared_csv),
        "actual": actual_csv,
        "count": len(actual_csv),
        "files": table_files,
    }


def _validate_legacy_outputs(
    example: str,
    summary: Optional[Mapping[str, Any]],
    return_code: int,
    output_dir: Path,
    requested_symbols: int,
    observer_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    validator = _load_pair_validator()
    save_mode = "legacy_research_dataset" if example in ("025", "026") else "factor_values_csv_only"
    pair_result = validator._validate_run(
        example,
        summary,
        return_code,
        output_dir,
        save_mode=save_mode,
        requested_symbols=requested_symbols,
        charts_enabled=True,
    )
    tables = (
        _legacy_evaluation_table_contract(summary, output_dir, validator)
        if example in ("025", "026")
        else {"status": "NOT_APPLICABLE", "expected": [], "files": []}
    )
    window = observer_metrics.get("runtime_window")
    effective_symbols = summary.get("symbols") if summary is not None else None
    effective_dates = summary.get("dates") if summary is not None else None
    sample_checks = {
        "summary_completed": summary is not None and summary.get("status") == "COMPLETED",
        "effective_symbols_meet_request": (
            isinstance(effective_symbols, int)
            and not isinstance(effective_symbols, bool)
            and effective_symbols >= requested_symbols
        ),
        "summary_dates_match_expected": effective_dates == EXPECTED_RESEARCH_GRID_ROWS,
        "runtime_window_present": isinstance(window, Mapping),
        "runtime_grid_rows_match_expected": (
            isinstance(window, Mapping) and window.get("grid_rows") == EXPECTED_RESEARCH_GRID_ROWS
        ),
        "runtime_target_count_matches_summary": (
            isinstance(window, Mapping)
            and window.get("target_count") == effective_symbols
            and isinstance(window.get("targets"), list)
            and len(window["targets"]) == effective_symbols
        ),
        "evaluation_ok": (
            example == "027"
            or (summary is not None and str(summary.get("evaluation_status", "")).upper() == "OK")
        ),
        "all_12_evaluation_tables_present": tables["status"] in ("OK", "NOT_APPLICABLE"),
        "reports_pngs_and_core_tables_valid": pair_result.get("status") == "OK",
    }
    return {
        "status": "OK" if all(sample_checks.values()) else "FAILED",
        "sample_checks": sample_checks,
        "requested_symbols": requested_symbols,
        "effective_symbols": effective_symbols,
        "expected_grid_rows": EXPECTED_RESEARCH_GRID_ROWS,
        "effective_grid_rows": window.get("grid_rows") if isinstance(window, Mapping) else None,
        "summary_dates": effective_dates,
        "evaluation_tables": tables,
        "reports_pngs_evaluation": pair_result,
    }


def _legacy_worker(
    args: argparse.Namespace, root: Path, data_dir: Path, inventory: Dict[str, Any]
) -> int:
    example = _single_worker_example(args.example)
    entry = _load_example_entry(root, example)
    observer = _Observer(root)
    origins = _install_legacy_observers(root, entry, observer)
    work_dir = Path(args.work_dir).resolve()
    output_dir = work_dir / "legacy-entry-output"
    command_args = [
        "--output-dir",
        str(output_dir),
        "--data-dir",
        str(data_dir),
        "--max-symbols",
        str(args.symbols),
        "--report-language",
        "zh",
    ]
    if args.report:
        command_args.append("--report")
    if example in ("025", "026"):
        command_args.append("--save-dataset")
    command = [sys.executable, str(Path(entry.__file__).resolve()), *command_args]
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        return_code = entry.main(command_args)
    except Exception:
        return_code = 2
        error = traceback.format_exc()
    else:
        error = None
    elapsed_s = time.perf_counter() - started
    cpu_s = time.process_time() - cpu_started
    observer.restore()

    summary_path = output_dir / "summary.json"
    summary = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = None
    report_values = []
    if summary:
        raw_reports = summary.get("reports", [])
        if summary.get("report"):
            raw_reports = list(raw_reports) + [summary["report"]]
        report_values = [str(value) for value in raw_reports if value]
    reports = []
    for value in report_values:
        path = Path(value)
        reports.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": _sha256(path) if path.is_file() and path.stat().st_size else None,
            }
        )
    evaluation_pngs = []
    evaluation_dir = output_dir / "evaluation"
    if evaluation_dir.is_dir():
        for path in sorted(evaluation_dir.rglob("*.png")):
            evaluation_pngs.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    try:
        legacy_validation = _validate_legacy_outputs(
            example,
            summary,
            return_code,
            output_dir,
            args.symbols,
            observer.metrics,
        )
    except Exception:
        legacy_validation = {
            "status": "FAILED",
            "error": traceback.format_exc(),
        }
    status = legacy_validation.get("status", "FAILED")
    source_hashes = _legacy_source_hashes(root, example)
    source_hashes["diagnose_factor_research_pipeline.py"] = _sha256(Path(__file__).resolve())
    legacy_metrics = observer.metrics["legacy_pipeline"]
    factor_info = legacy_metrics["get_dataset"].get("artifacts", {})
    if factor_info:
        observer.metrics["factor_spec_configuration"] = {
            "calls": legacy_metrics["get_dataset"]["calls"],
            "time_s": legacy_metrics["get_dataset"]["time_s"],
            "rss_bytes": legacy_metrics["get_dataset"]["rss_bytes"],
            "factor_count": len(factor_info.get("factor_names", [])),
            "factor_names": factor_info.get("factor_names", []),
            "indicator_instances": None,
            "boundary": "get_dataset only; legacy factor construction is inside cerebro_run",
        }
    output = {
        "classification": DIAGNOSTIC_CLASS,
        "runner_api": "legacy_public_run_py",
        "mode": args.mode,
        "side": args.side,
        "example": example,
        "root": str(root),
        "git_head": _git_head(root),
        "module_origins": origins,
        "source_hashes": source_hashes,
        "input_manifest": inventory,
        "input_panel_symbols": legacy_metrics["load_daily_panel"].get("panel", {}).get("symbols"),
        "input_panel_grid_rows": legacy_metrics["load_daily_panel"]
        .get("panel", {})
        .get("grid_rows"),
        "worker_arguments": {
            "root": str(root),
            "example": example,
            "symbols": args.symbols,
            "data_dir": str(data_dir),
            "report": args.report,
            "entry_arguments": command_args,
        },
        "entry_command": command,
        "entry_called_via_main_in_diagnostic_worker": True,
        "entry_returncode": return_code,
        "entry_elapsed_s": elapsed_s,
        "entry_cpu_s": cpu_s,
        "summary": summary,
        "summary_path": str(summary_path),
        "requested_symbols": args.symbols,
        "effective_symbols": summary.get("symbols") if summary is not None else None,
        "effective_grid_rows": summary.get("dates") if summary is not None else None,
        "legacy_validation": legacy_validation,
        "reports": reports,
        "evaluation_pngs": evaluation_pngs,
        "status": status,
        "error": error,
        "observers": observer.metrics,
        "instrumentation_overhead_warning": "legacy entry hooks are diagnostic only and do not match the candidate stage schema",
        "api_differences": [
            "legacy API writes ResearchDataset and factor_values.csv; candidate stage API writes FactorPanel CSV files",
            "legacy collection uses prealign_bars and get_dataset; candidate uses align_to_grid and MemorySink.finalize",
            "legacy collection and get_dataset/Cerebro timings are nested; do not add them together",
        ],
    }
    result_path = work_dir / "worker-result.json"
    _json_write(result_path, output)
    print(json.dumps({"status": status, "result": str(result_path)}, ensure_ascii=False))
    return 0 if status == "OK" else 2


def _expanded_factor_specs(
    reference_builder: Callable[..., Mapping[str, Any]],
    example: str,
    config: Mapping[str, Any],
    count: int,
) -> Dict[str, Any]:
    from backtrader.research import FactorSpec

    originals = reference_builder(example, config, None)
    if len(originals) != 1:
        raise ValueError("scaling requires 025 to supply exactly one reference FactorSpec")
    reference = next(iter(originals.values()))
    if tuple(reference.field_bindings) != ("close",):
        raise ValueError("scaling requires the 025 reference factor to bind only close")
    indicator = _binding_aware_scaling_indicator(reference.indicator)
    factors = {}
    for index in range(count):
        field_name = _scaling_field_name(index)
        name = "%s_ma_%02d" % (field_name, index + 1)
        factors[name] = FactorSpec(
            name=name,
            indicator=indicator,
            params=dict(reference.params),
            panel_line=reference.panel_line,
            direction=reference.direction,
            field_bindings=_scaling_field_binding(index),
        )
    return factors


def _worker(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if not (root / "backtrader" / "__init__.py").is_file():
        raise ValueError("root is not a Backtrader checkout: %s" % root)
    sys.path.insert(0, str(root))
    import psutil  # noqa: F401 - hard requirement for observed RSS values

    origins = _module_origins(root)

    if args.mode == "operators":
        return _operator_worker(args, root, origins)

    example = "025" if args.mode == "scaling" else _single_worker_example(args.example)

    data_dir = Path(args.data_dir).expanduser().resolve()
    inventory = _input_manifest(data_dir, args.symbols)
    if not _supports_current_stage(root):
        if args.mode != "stage":
            raise ValueError(
                "scaling mode requires a checkout with the native FactorPanel pipeline"
            )
        return _legacy_worker(args, root, data_dir, inventory)
    if args.mode == "scaling":
        if args.factor_count not in EXPECTED_SCALE:
            raise ValueError("scaling worker requires factor_count in %r" % (EXPECTED_SCALE,))
        if args.symbols != 20:
            raise ValueError("scaling diagnostic requires exactly 20 requested symbols")
        if inventory["calendar_rows"] != EXPECTED_SCALE_GRID:
            raise ValueError(
                "scaling diagnostic requires 243 calendar rows; found %s"
                % inventory["calendar_rows"]
            )
        if len(inventory["selected_symbols"]) != 20:
            raise ValueError(
                "scaling diagnostic requires 20 selected assets; found %s"
                % len(inventory["selected_symbols"])
            )

    stage = _load_stage_benchmark(root)
    observer = _Observer(root)
    _install_observers(root, observer)
    previous_specs = stage._factor_specs
    _observe_research_window(stage, observer, scaling=args.mode == "scaling")
    if args.mode == "scaling":
        stage._factor_specs = lambda selected, config, module: _expanded_factor_specs(
            previous_specs, selected, config, args.factor_count
        )
        _observe_completed_strategies(observer)
    _observe_factor_specs(stage, observer)
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    benchmark_output = work_dir / "stage-output"
    run_args = SimpleNamespace(
        symbols=args.symbols,
        data_dir=str(data_dir),
        runnext=False,
        csv=args.csv,
        report=args.report,
        evaluate=args.evaluate and example in ("025", "026"),
        output=str(benchmark_output),
    )
    started = time.perf_counter()
    try:
        result = stage._run_once(run_args, example, benchmark_output, 0)
    except Exception:
        result = {
            "example": example,
            "status": "FAILED",
            "error": traceback.format_exc(),
        }
    elapsed_s = time.perf_counter() - started
    observer.restore()
    stage._factor_specs = previous_specs

    if args.mode == "scaling":
        artifacts = result.get("artifacts", {})
        if result.get("status") == "OK" and (
            artifacts.get("symbols") != 20 or artifacts.get("grid_rows") != EXPECTED_SCALE_GRID
        ):
            result["status"] = "INCOMPLETE"
            result["error"] = "runtime input did not yield exactly 20 assets x 243 grid rows"
        if result.get("status") == "OK":
            actuals = observer.metrics["scaling_actuals"]
            factor_configuration = observer.metrics["factor_spec_configuration"]
            runtime_window = observer.metrics["runtime_window"] or {}
            bindings = factor_configuration["factor_bindings"]
            fields = [
                next(iter(binding.values())).rsplit(":", 1)[-1]
                for binding in bindings.values()
                if binding
            ]
            group_members = runtime_window.get("group_members", {})
            if (
                not actuals["observed_after_run"]
                or actuals["factor_instance_count"] != args.factor_count * 2
                or len(group_members) != 2
                or sorted(len(members) for members in group_members.values()) != [10, 10]
                or fields != [_scaling_field_name(index) for index in range(args.factor_count)]
            ):
                result["status"] = "INCOMPLETE"
                result["error"] = (
                    "scaling workload contract failed: expected two fixed 10-asset groups, "
                    "alternating close/open bindings, and two factor instances per factor"
                )
    elif int(result.get("artifacts", {}).get("symbols", 0)) < args.symbols:
        result["status"] = "INCOMPLETE"
        result["error"] = "runtime loaded fewer symbols than requested"
    source_hashes = stage._source_hashes(example)
    for relative in (
        "backtrader/research/align.py",
        "backtrader/research/factor_strategy.py",
        "backtrader/research/panel.py",
        "backtrader/research/sink.py",
    ):
        source_path = root / relative
        if source_path.is_file():
            source_hashes[relative] = _sha256(source_path)
    source_hashes["diagnostic_factor_research_pipeline.py"] = _sha256(Path(__file__).resolve())
    output = {
        "classification": DIAGNOSTIC_CLASS,
        "runner_api": "existing_stage_benchmark",
        "mode": args.mode,
        "side": args.side,
        "example": example,
        "factor_count": args.factor_count if args.mode == "scaling" else None,
        "worker_arguments": {
            "mode": args.mode,
            "root": str(root),
            "example": example,
            "symbols": args.symbols,
            "factor_count": args.factor_count if args.mode == "scaling" else None,
            "data_dir": str(data_dir),
            "csv": args.csv,
            "report": args.report,
            "evaluate": run_args.evaluate,
        },
        "root": str(root),
        "git_head": _git_head(root),
        "module_origins": origins,
        "source_hashes": source_hashes,
        "input_manifest": inventory,
        "effective_symbols": result.get("artifacts", {}).get("symbols"),
        "effective_grid_rows": result.get("artifacts", {}).get("grid_rows"),
        "instrumentation_overhead_warning": (
            "observer hooks are active; timings and RSS samples are diagnostic, not an acceptance benchmark"
        ),
        "stage_elapsed_s": elapsed_s,
        "status": result.get("status"),
        "stage_result": result,
        "observers": observer.metrics,
        "scaling_workload": (
            {
                "fixed_input_targets": observer.metrics["runtime_window"]["targets"],
                "groups_by_target": observer.metrics["runtime_window"]["groups_by_target"],
                "group_members": observer.metrics["runtime_window"]["group_members"],
                "factor_bindings": observer.metrics["factor_spec_configuration"]["factor_bindings"],
                "binding_semantics": (
                    "diagnostic FactorIndicator reads its declared close alias; each factor's "
                    "feed:target:close/open binding selects the actual input line"
                ),
                "factor_implementation": (
                    "diagnostic subclass of the configured 025 factor, preserving its SMA-ratio "
                    "formula while resolving the declared close alias"
                ),
                "actual_instances_after_run": observer.metrics["scaling_actuals"],
            }
            if args.mode == "scaling" and observer.metrics["runtime_window"] is not None
            else None
        ),
        "unsupported_measurements": [
            "per-operator Alpha101 timing and finite witnesses",
            "fincore model-copy counts inside report generation",
        ],
        "rss_sampling": {
            "process": "current worker process RSS via psutil",
            "on_point": "first and every 1000th call, plus a labeled post-final-call sample",
            "grid_callbacks": "every callback",
            "finalize_panel_align_and_factor_spec_configuration": "before and after each observed call",
        },
    }
    result_path = work_dir / "worker-result.json"
    _json_write(result_path, output)
    print(
        json.dumps({"status": result.get("status"), "result": str(result_path)}, ensure_ascii=False)
    )
    return 0 if result.get("status") == "OK" else 2


def _worker_command(
    args: argparse.Namespace,
    root: Path,
    side: str,
    job_dir: Path,
    example: str,
    count: Optional[int],
) -> List[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker",
        "--mode",
        args.mode,
        "--root",
        str(root),
        "--side",
        side,
        "--work-dir",
        str(job_dir),
    ]
    if args.mode in ("stage", "scaling"):
        command.extend(["--symbols", str(args.symbols)])
    if args.data_dir:
        command.extend(["--data-dir", str(Path(args.data_dir).expanduser().resolve())])
    if args.mode == "stage":
        command.extend(["--example", example])
    elif args.mode == "scaling":
        command.extend(["--factor-count", str(count)])
    elif args.profile_report:
        command.append("--profile-report")
    if args.csv:
        command.append("--csv")
    if args.report:
        command.append("--report")
    if args.evaluate:
        command.append("--evaluate")
    return command


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stage", "scaling", "operators"), required=True)
    parser.add_argument(
        "--root", help="one checkout root, used by scaling or a single-side stage run"
    )
    parser.add_argument(
        "--baseline-root", help="frozen 4ce64007 source root for a side-by-side stage run"
    )
    parser.add_argument(
        "--candidate-root", help="candidate source root for a side-by-side stage run"
    )
    parser.add_argument("--example", action="append", choices=EXAMPLES)
    parser.add_argument("--symbols", type=int, default=500)
    parser.add_argument("--data-dir")
    parser.add_argument("--output", help="new output directory; existing paths are refused")
    parser.add_argument(
        "--csv", action="store_true", help="write/read the complete six-file factor panel"
    )
    parser.add_argument("--report", action="store_true", help="render the report for each factor")
    parser.add_argument(
        "--evaluate", action="store_true", help="run the stage benchmark evaluation"
    )
    parser.add_argument(
        "--profile-report", action="store_true", help="profile one report call in operators mode"
    )
    parser.add_argument("--factors", type=int, nargs="+", default=list(EXPECTED_SCALE))
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--side", default="single")
    parser.add_argument("--factor-count", type=int)
    parser.add_argument("--work-dir", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args._worker:
            return _worker(args)
        if not args.output:
            raise ValueError("parent mode requires --output")
        if args.symbols < 1:
            raise ValueError("--symbols must be positive")
        if args.mode == "stage":
            if args.example is None or not args.example:
                raise ValueError("stage mode requires at least one --example")
            if not args.csv or not args.report:
                raise ValueError(
                    "stage mode requires --csv and --report for full pipeline diagnostics"
                )
            if any(example in ("025", "026") for example in args.example) and not args.evaluate:
                raise ValueError("stage mode requires --evaluate for 025/026 comparison")
            if args.root and (args.baseline_root or args.candidate_root):
                raise ValueError("use --root or baseline/candidate roots, not both")
            if bool(args.baseline_root) != bool(args.candidate_root):
                raise ValueError(
                    "side-by-side mode requires both --baseline-root and --candidate-root"
                )
            if not args.root and not args.baseline_root:
                raise ValueError("stage mode requires --root or both baseline/candidate roots")
            roots = (
                [("baseline", Path(args.baseline_root)), ("candidate", Path(args.candidate_root))]
                if args.baseline_root
                else [("single", Path(args.root))]
            )
            if not args.data_dir:
                raise ValueError("stage mode requires --data-dir")
            if args.profile_report:
                raise ValueError("--profile-report is only supported in operators mode")
        elif args.mode == "scaling":
            if not args.root or args.baseline_root or args.candidate_root:
                raise ValueError("scaling mode requires one --root and no baseline/candidate roots")
            if args.symbols != 20:
                raise ValueError("scaling mode requires --symbols 20")
            if tuple(args.factors) != EXPECTED_SCALE:
                raise ValueError("scaling mode is fixed to --factors 1 3 10")
            if not args.csv or not args.report:
                raise ValueError("scaling mode requires --csv and --report to measure those stages")
            if not args.data_dir:
                raise ValueError("scaling mode requires --data-dir")
            if args.profile_report:
                raise ValueError("--profile-report is only supported in operators mode")
            roots = [("candidate", Path(args.root))]
        else:
            if not args.root or args.baseline_root or args.candidate_root:
                raise ValueError(
                    "operators mode requires one --root and no baseline/candidate roots"
                )
            if args.example or args.csv or args.report or args.evaluate:
                raise ValueError("operators mode uses --profile-report, not stage/example options")
            roots = [("candidate", Path(args.root))]

        output_root = Path(args.output).expanduser().resolve()
        if output_root.exists():
            raise FileExistsError("output directory already exists: %s" % output_root)
        output_root.mkdir(parents=True)
        runs = []
        commands = []
        jobs: Iterable[Tuple[str, Path, Optional[str], Optional[int]]]
        if args.mode == "stage":
            jobs = ((side, root, example, None) for side, root in roots for example in args.example)
        elif args.mode == "scaling":
            jobs = ((side, root, None, count) for side, root in roots for count in args.factors)
        else:
            jobs = ((side, root, None, None) for side, root in roots)

        for side, root, example, count in jobs:
            root = root.expanduser().resolve()
            if args.mode == "operators":
                run_name = "operators"
            elif example:
                run_name = example
            else:
                run_name = "factors-%d" % count
            job_name = "%s-%s" % (side, run_name)
            job_dir = output_root / job_name
            job_dir.mkdir()
            command = _worker_command(args, root, side, job_dir, example or "025", count)
            commands.append(command)
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment["PYTHONPATH"] = str(root)
            completed = subprocess.run(
                command,
                cwd=str(root),
                env=environment,
                capture_output=True,
                text=True,
            )
            result_path = job_dir / "worker-result.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                result = {
                    "classification": DIAGNOSTIC_CLASS,
                    "mode": args.mode,
                    "side": side,
                    "example": example,
                    "factor_count": count,
                    "command": command,
                    "stage_result": {
                        "status": "HARNESS_FAILED",
                        "returncode": completed.returncode,
                        "stdout_tail": completed.stdout[-3000:],
                        "stderr_tail": completed.stderr[-3000:],
                    },
                }
            result["worker_returncode"] = completed.returncode
            result["worker_stdout_tail"] = completed.stdout[-3000:]
            result["worker_stderr_tail"] = completed.stderr[-3000:]
            runs.append(result)

        input_window_comparisons = {}
        if args.mode == "stage" and len(roots) == 2:
            for example in args.example:
                by_side = {run.get("side"): run for run in runs if run.get("example") == example}
                baseline_result = by_side.get("baseline")
                candidate_result = by_side.get("candidate")
                if baseline_result is None or candidate_result is None:
                    input_window_comparisons[example] = {
                        "checks": {},
                        "all_match": False,
                        "error": "one or both side results are missing",
                    }
                else:
                    input_window_comparisons[example] = _compare_input_window_contracts(
                        baseline_result,
                        candidate_result,
                    )
        comparison_ok = all(
            value.get("all_match", False) for value in input_window_comparisons.values()
        )
        scaling_comparison = None
        if args.mode == "scaling":
            scaling_comparison = _compare_scaling_workloads(runs, args.factors)
            comparison_ok = scaling_comparison["all_match"]
        manifest = {
            "classification": DIAGNOSTIC_CLASS,
            "schema_version": 1,
            "mode": args.mode,
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "python_executable": sys.executable,
            "python_version": sys.version,
            "platform": platform.platform(),
            "symbols": args.symbols if args.mode in ("stage", "scaling") else None,
            "data_dir": str(Path(args.data_dir).expanduser().resolve()) if args.data_dir else None,
            "requested_examples": args.example or [],
            "requested_factor_counts": args.factors if args.mode == "scaling" else [],
            "requested_alpha_ids": list(OPERATOR_ALPHA_IDS) if args.mode == "operators" else [],
            "observer_overhead": True,
            "stage_sum_policy": (
                "candidate Cerebro includes callbacks and sink finalization; legacy collection_entry "
                "contains cerebro_run and get_dataset; nested durations are never added"
            ),
            "command": [sys.executable, str(Path(__file__).resolve()), *(argv or sys.argv[1:])],
            "worker_commands": commands,
            "runs": runs,
            "input_window_comparisons": input_window_comparisons,
            "scaling_workload_comparison": scaling_comparison,
            "limitations": [
                "instrumented timings are DIAGNOSTIC_ONLY and are not paired performance acceptance",
                "operator/report cProfile is diagnostic and does not prove semantic caching or causal cost attribution",
                "fincore report functions are included only when their function names match labels, weights, or positions",
            ],
        }
        _json_write(output_root / "diagnostic.json", manifest)
        print(
            json.dumps(
                {
                    "classification": DIAGNOSTIC_CLASS,
                    "output": str(output_root / "diagnostic.json"),
                    "runs": len(runs),
                },
                ensure_ascii=False,
            )
        )
        return 0 if all(run.get("worker_returncode") == 0 for run in runs) and comparison_ok else 2
    except Exception as exc:
        print("%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
