"""Paired, fresh-process iteration 28/29 runtime evidence (no network or orders).

Run with the same interpreter and dependency path for every source snapshot.
Raw samples are always retained, including failures; this script never retries
or discards measurements. Run on an otherwise idle machine.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import statistics
import subprocess
import sys
import time

SOURCES = ("pre28", "pre29", "candidate")
RUNTIME_REGRESSION_LIMIT = 0.05
COLD_IMPORT_RELATIVE_LIMIT = 0.10
COLD_IMPORT_ABSOLUTE_LIMIT_S = 0.02
MIN_PAIRS_FOR_POSITION_COVERAGE = 3
RECOMMENDED_SAMPLES_PER_SOURCE_POSITION = 3
COLD_IMPORT_ROUNDS = 12
RUNTIME_ENVIRONMENT = {
    # A cached baseline compared with an uncached candidate can make a source
    # change look like an import or RSS regression.  Every child is therefore
    # forced to compile from source without writing bytecode, and cache files
    # in a supplied snapshot make the acceptance run fail before sampling.
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
}

# The first three orders are the cyclic Latin square.  The next three are its
# reverse crossover.  Repeating this fixed six-order sequence exercises every
# possible three-source order.  Every three completed rounds balance each
# source across positions; with --pairs 9 every source appears exactly three
# times in positions 1, 2, and 3.
BALANCED_CROSSOVER_ORDERS = (
    ("pre28", "pre29", "candidate"),
    ("pre29", "candidate", "pre28"),
    ("candidate", "pre28", "pre29"),
    ("pre28", "candidate", "pre29"),
    ("candidate", "pre29", "pre28"),
    ("pre29", "pre28", "candidate"),
)


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot_manifest(snapshot_root):
    """Bind a cache-free runtime snapshot to the resulting report.

    The comparator receives snapshot roots rather than Git checkouts, so its
    evidence must fingerprint the exact package files actually imported. Rejecting
    bytecode artifacts avoids comparing cached historical sources against an
    uncached candidate (or the inverse).
    """
    snapshot_root = Path(snapshot_root).resolve()
    source = snapshot_root / "backtrader"
    if not (source / "__init__.py").is_file():
        raise ValueError(
            "source snapshot must contain a backtrader package: {}".format(snapshot_root)
        )

    cache_artifacts = sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    )
    if cache_artifacts:
        raise ValueError(
            "source snapshot contains bytecode cache artifacts: {}".format(
                ", ".join(cache_artifacts[:3])
            )
        )

    files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return {
        "snapshot_root": str(snapshot_root),
        "package_path": str(source),
        "file_count": len(files),
        "tree_sha256": digest.hexdigest(),
        "cache_artifacts": [],
    }


def source_environment(source):
    """Return the identical isolated import environment for every snapshot."""
    environment = dict(os.environ)
    # These inherited settings can redirect cache writes or select another
    # interpreter prefix, defeating the uniform child-process contract.
    environment.pop("PYTHONPYCACHEPREFIX", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONPATH"] = str(Path(source).resolve())
    environment.update(RUNTIME_ENVIRONMENT)
    return environment


def is_within(path, root):
    """Compatibility equivalent of Path.is_relative_to for Python 3.8."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def probe_harness_manifest(probe_path):
    """Fingerprint the frozen probe, its shared fixture, and neutral cwd."""
    probe = Path(probe_path).resolve()
    if not probe.is_file():
        raise ValueError("runtime probe does not exist: {}".format(probe))
    harness_root = probe.parent.parent
    fixture = harness_root / "tests" / "datas" / "2006-day-001.txt"
    if not fixture.is_file():
        raise ValueError("runtime probe fixture does not exist: {}".format(fixture))
    return {
        "harness_root": str(harness_root),
        "probe": {"path": str(probe), "sha256": _file_sha256(probe)},
        "fixture": {"path": str(fixture), "sha256": _file_sha256(fixture)},
    }


def build_crossover_orders(pairs):
    """Return the deterministic, position-balanced order for each round."""
    if pairs < MIN_PAIRS_FOR_POSITION_COVERAGE:
        raise ValueError(
            "--pairs must be at least {} to cover all three execution positions".format(
                MIN_PAIRS_FOR_POSITION_COVERAGE
            )
        )
    return [
        BALANCED_CROSSOVER_ORDERS[index % len(BALANCED_CROSSOVER_ORDERS)] for index in range(pairs)
    ]


def summarize_position_coverage(orders):
    """Describe source/position coverage so partial sequences remain auditable."""
    counts = {
        source: {str(position): 0 for position in range(1, len(SOURCES) + 1)} for source in SOURCES
    }
    for order in orders:
        if set(order) != set(SOURCES) or len(order) != len(SOURCES):
            raise ValueError("every crossover order must contain each source exactly once")
        for position, source in enumerate(order, start=1):
            counts[source][str(position)] += 1

    return _summarize_position_counts(counts)


def _summarize_position_counts(counts, execution_records=None):
    """Return the common coverage record for planned or completed execution."""
    flat_counts = [count for source_counts in counts.values() for count in source_counts.values()]
    minimum = min(flat_counts)
    maximum = max(flat_counts)
    summary = {
        "minimum_pairs_for_all_positions": MIN_PAIRS_FOR_POSITION_COVERAGE,
        "recommended_samples_per_source_position": RECOMMENDED_SAMPLES_PER_SOURCE_POSITION,
        "source_position_counts": counts,
        "all_positions_covered": minimum >= 1,
        "gate_eligible": minimum >= 1,
        "minimum_samples_per_source_position": minimum,
        "recommended_coverage_met": minimum >= RECOMMENDED_SAMPLES_PER_SOURCE_POSITION,
        "balanced_within_one_sample": maximum - minimum <= 1,
        "exactly_balanced": minimum == maximum,
    }
    if execution_records is not None:
        summary["completed_execution_records"] = execution_records
    return summary


def summarize_execution_position_coverage(execution_order):
    """Describe the sources and positions that have actually completed."""
    counts = {
        source: {str(position): 0 for position in range(1, len(SOURCES) + 1)} for source in SOURCES
    }
    for entry in execution_order:
        source = entry["source"]
        position = entry["position"]
        if source not in counts or position not in range(1, len(SOURCES) + 1):
            raise ValueError("runtime execution order contains an unknown source or position")
        counts[source][str(position)] += 1
    return _summarize_position_counts(counts, execution_records=len(execution_order))


def _rows_by_round(rows):
    recorded_rounds = [row.get("round") for row in rows]
    if any(round_number is None for round_number in recorded_rounds):
        if any(round_number is not None for round_number in recorded_rounds):
            raise ValueError("runtime report mixes explicit and implicit round samples")
        # Preserve the historical raw worker schema.  Raw rows are appended
        # once per round, so their stable list position is their round number.
        by_round = dict(enumerate(rows, start=1))
    else:
        by_round = {row["round"]: row for row in rows}
    if len(by_round) != len(rows):
        raise ValueError("runtime report contains duplicate round samples")
    return by_round


def execution_position_maps(execution_order):
    """Index separately reported metadata without changing raw worker rows."""
    positions = {source: {} for source in SOURCES}
    for entry in execution_order:
        source = entry["source"]
        round_number = entry["round"]
        if source not in positions or round_number in positions[source]:
            raise ValueError("runtime execution order contains a duplicate or unknown source")
        positions[source][round_number] = entry["position"]
    return positions


def _row_position(row, round_number, positions):
    """Use report metadata in production and embedded metadata in unit fixtures."""
    if positions is None:
        return row["position"]
    try:
        return positions[round_number]
    except KeyError as error:
        raise ValueError("runtime execution order is missing a source round") from error


def compare_load_by_position(
    baseline, candidate, load, baseline_positions=None, candidate_positions=None
):
    """Return the diagnostic paired delta and the position-stratified gate.

    The diagnostic compares source samples within the same round, preserving
    the historical output.  It can be confounded when the two sources occupy
    different execution positions.  The gate instead compares the median
    candidate and baseline measurements at the *same* position before taking
    the median of those three ratios.
    """
    baseline_by_round = _rows_by_round(baseline)
    candidate_by_round = _rows_by_round(candidate)
    if set(baseline_by_round) != set(candidate_by_round):
        raise ValueError("baseline and candidate rounds do not match")

    paired_deltas = []
    for round_number in sorted(baseline_by_round):
        before = baseline_by_round[round_number]
        after = candidate_by_round[round_number]
        if before["results"] != after["results"]:
            raise AssertionError((load, round_number, before["results"], after["results"]))
        paired_deltas.append(after["samples_s"][load] / before["samples_s"][load] - 1)

    strata = []
    ratios = []
    missing_positions = []
    for position in range(1, len(SOURCES) + 1):
        before_values = [
            row["samples_s"][load]
            for round_number, row in baseline_by_round.items()
            if _row_position(row, round_number, baseline_positions) == position
        ]
        after_values = [
            row["samples_s"][load]
            for round_number, row in candidate_by_round.items()
            if _row_position(row, round_number, candidate_positions) == position
        ]
        if not before_values or not after_values:
            missing_positions.append(position)
            continue
        before_median = statistics.median(before_values)
        after_median = statistics.median(after_values)
        if before_median <= 0:
            raise ValueError("baseline median must be positive for ratio comparison")
        ratio = after_median / before_median
        ratios.append(ratio)
        strata.append(
            {
                "position": position,
                "baseline_samples_s": before_values,
                "candidate_samples_s": after_values,
                "baseline_median_s": before_median,
                "candidate_median_s": after_median,
                "median_ratio": ratio,
                "median_delta": ratio - 1,
            }
        )

    diagnostic_median_delta = statistics.median(paired_deltas)
    if missing_positions:
        return {
            # The legacy values remain visible, but a partial schedule is not
            # allowed to produce a false PASS for the position-stratified gate.
            "paired_deltas": paired_deltas,
            "median_delta": diagnostic_median_delta,
            "unadjusted_paired_median_delta": diagnostic_median_delta,
            "unadjusted_paired_within_5_percent": diagnostic_median_delta
            <= RUNTIME_REGRESSION_LIMIT,
            "gate": {
                "method": "median_of_position_median_ratios",
                "threshold": RUNTIME_REGRESSION_LIMIT,
                "status": "INCONCLUSIVE_INSUFFICIENT_POSITION_COVERAGE",
                "missing_positions": missing_positions,
                "strata": strata,
                "median_ratio": None,
                "median_delta": None,
                "within_5_percent": False,
            },
            "gate_median_ratio": None,
            "gate_median_delta": None,
            "within_5_percent": False,
        }

    gate_median_ratio = statistics.median(ratios)
    gate_median_delta = gate_median_ratio - 1
    return {
        # Kept for historical report consumers.  This is diagnostic only and
        # must not decide the 5% gate because it mixes execution positions.
        "paired_deltas": paired_deltas,
        "median_delta": diagnostic_median_delta,
        "unadjusted_paired_median_delta": diagnostic_median_delta,
        "unadjusted_paired_within_5_percent": diagnostic_median_delta <= RUNTIME_REGRESSION_LIMIT,
        "gate": {
            "method": "median_of_position_median_ratios",
            "threshold": RUNTIME_REGRESSION_LIMIT,
            "status": (
                "PASS" if gate_median_delta <= RUNTIME_REGRESSION_LIMIT else "FAIL_OVER_5_PERCENT"
            ),
            "missing_positions": [],
            "strata": strata,
            "median_ratio": gate_median_ratio,
            "median_delta": gate_median_delta,
            "within_5_percent": gate_median_delta <= RUNTIME_REGRESSION_LIMIT,
        },
        "gate_median_ratio": gate_median_ratio,
        "gate_median_delta": gate_median_delta,
        "within_5_percent": gate_median_delta <= RUNTIME_REGRESSION_LIMIT,
    }


def compare_cold_import_by_position(
    baseline, candidate, baseline_positions=None, candidate_positions=None
):
    """Apply the cold-import budget to like-for-like execution positions."""
    if baseline_positions is None or candidate_positions is None:
        raise ValueError("cold-import comparison requires execution position metadata")
    baseline_by_round = dict(enumerate(baseline, start=1))
    candidate_by_round = dict(enumerate(candidate, start=1))
    if set(baseline_by_round) != set(candidate_by_round):
        raise ValueError("baseline and candidate cold-import rounds do not match")

    strata = []
    baseline_medians = []
    candidate_medians = []
    missing_positions = []
    for position in range(1, len(SOURCES) + 1):
        before_values = [
            value
            for round_number, value in baseline_by_round.items()
            if baseline_positions.get(round_number) == position
        ]
        after_values = [
            value
            for round_number, value in candidate_by_round.items()
            if candidate_positions.get(round_number) == position
        ]
        if not before_values or not after_values:
            missing_positions.append(position)
            continue
        before_median = statistics.median(before_values)
        after_median = statistics.median(after_values)
        baseline_medians.append(before_median)
        candidate_medians.append(after_median)
        strata.append(
            {
                "position": position,
                "baseline_samples_s": before_values,
                "candidate_samples_s": after_values,
                "baseline_median_s": before_median,
                "candidate_median_s": after_median,
                "median_delta_s": after_median - before_median,
            }
        )

    if missing_positions:
        return {
            "method": "position_stratified_median_budget",
            "status": "INCONCLUSIVE_INSUFFICIENT_POSITION_COVERAGE",
            "missing_positions": missing_positions,
            "strata": strata,
            "baseline_median_s": None,
            "candidate_median_s": None,
            "budget_s": None,
            "within_budget": False,
        }

    baseline_median = statistics.median(baseline_medians)
    candidate_median = statistics.median(candidate_medians)
    budget = max(baseline_median * COLD_IMPORT_RELATIVE_LIMIT, COLD_IMPORT_ABSOLUTE_LIMIT_S)
    return {
        "method": "position_stratified_median_budget",
        "status": "PASS" if candidate_median - baseline_median <= budget else "FAIL_OVER_BUDGET",
        "missing_positions": [],
        "strata": strata,
        "baseline_median_s": baseline_median,
        "candidate_median_s": candidate_median,
        "median_delta_s": candidate_median - baseline_median,
        "budget_s": budget,
        "within_budget": candidate_median - baseline_median <= budget,
    }


def release_gate_status(report):
    """Turn the retained report into a fail-closed release decision."""
    failures = []
    if not report["source_snapshots"]["unchanged"]:
        failures.append("source_snapshot_changed")
    if not report["probe_harness"]["unchanged"]:
        failures.append("probe_or_fixture_changed")
    if not report["comparator"]["unchanged"]:
        failures.append("comparator_changed")
    if not report["position_balance"]["recommended_coverage_met"]:
        failures.append("runtime_position_coverage_incomplete")

    for baseline, comparisons in report["comparisons"].items():
        for load, comparison in comparisons.items():
            if load == "rss":
                if not comparison["within_budget"]:
                    failures.append("{}.rss".format(baseline))
            elif not comparison["within_5_percent"]:
                failures.append("{}.{}".format(baseline, load))

    for mode, cold_report in report["cold_import"].items():
        if not cold_report["position_balance"]["exactly_balanced"]:
            failures.append("cold_import.{}.position_coverage".format(mode))
        for baseline, within_budget in cold_report["within_budget"].items():
            if not within_budget:
                failures.append("cold_import.{}.{}".format(mode, baseline))

    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def worker(args):
    import resource

    import backtrader as bt

    source = Path(args.source).resolve()
    assert is_within(bt.__file__, source), bt.__file__
    probe = runpy.run_path(args.probe)
    if args.backend:
        from backtrader.utils.log_message import configure_logging

        configure_logging(
            "INFO",
            console=False,
            log_dir=args.log_dir,
            script_name="iteration_acceptance",
            backend=args.backend,
        )
    results = {}
    samples = {}
    for name, fn in probe["LOADS"].items():
        expected = fn()
        start = time.perf_counter()
        for _ in range(5):
            actual = fn()
            assert expected == actual, (name, expected, actual)
        samples[name] = (time.perf_counter() - start) / 5
        results[name] = actual
    for _ in range(300):
        bt.Cerebro()
    start = time.perf_counter()
    for _ in range(300):
        bt.Cerebro()
    samples["construct_300"] = time.perf_counter() - start
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports KiB.
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    print(
        json.dumps(
            {
                "source": str(source),
                "samples_s": samples,
                "results": results,
                "rss_bytes": rss_bytes,
            }
        )
    )


def invoke(args, source, index, backend=None):
    env = source_environment(source)
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--worker",
        "--source",
        str(source),
        "--probe",
        args.probe,
    ]
    if backend:
        command += [
            "--backend",
            backend,
            "--log-dir",
            str(Path(args.output).parent / "logs" / backend / str(index)),
        ]
    result = subprocess.run(
        command,
        cwd=Path(args.probe).resolve().parent.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def cold(source, light, neutral_cwd):
    env = source_environment(source)
    env.pop("BACKTRADER_LIGHT_IMPORT", None)
    if light:
        env["BACKTRADER_LIGHT_IMPORT"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import time,json; t=time.perf_counter(); "
            "import backtrader; print(json.dumps([time.perf_counter()-t,backtrader.__file__]))",
        ],
        cwd=neutral_cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    duration, origin = json.loads(result.stdout.splitlines()[-1])
    assert is_within(origin, source), origin
    return duration


def main(args):
    args.probe = str(Path(args.probe).resolve())
    args.output = str(Path(args.output).resolve())
    comparator_path = Path(__file__).resolve()
    comparator_before = {"path": str(comparator_path), "sha256": _file_sha256(comparator_path)}
    sources = {
        "pre28": Path(args.pre28).resolve(),
        "pre29": Path(args.pre29).resolve(),
        "candidate": Path(args.source).resolve(),
    }
    source_snapshots_before = {
        name: source_snapshot_manifest(path) for name, path in sources.items()
    }
    probe_harness_before = probe_harness_manifest(args.probe)
    round_orders = build_crossover_orders(args.pairs)
    report = {
        "interpreter": sys.executable,
        "pairs": args.pairs,
        "executions_per_sample": 5,
        "probe_sha256": probe_harness_before["probe"]["sha256"],
        "probe_harness": {
            "before": probe_harness_before,
            "after": None,
            "unchanged": None,
        },
        "comparator": {"before": comparator_before, "after": None, "unchanged": None},
        "source_snapshots": {
            "before": source_snapshots_before,
            "after": None,
            "unchanged": None,
        },
        "cache_policy": {
            "source_snapshot_must_be_cache_free": True,
            "child_python_uses_dash_B": True,
            "environment": RUNTIME_ENVIRONMENT,
        },
        "comparison_policy": {
            "runtime_load_gate": "position-stratified median of position median ratios",
            "runtime_regression_limit": RUNTIME_REGRESSION_LIMIT,
            "median_delta": "legacy within-round diagnostic; not the release gate",
            "within_5_percent": "position-stratified runtime load gate",
        },
        "raw": {name: [] for name in sources},
        "planned_rounds": [
            {
                "round": round_number,
                "order": list(order),
                "positions": [
                    {"position": position, "source": source}
                    for position, source in enumerate(order, start=1)
                ],
            }
            for round_number, order in enumerate(round_orders, start=1)
        ],
        "planned_position_balance": summarize_position_coverage(round_orders),
        "rounds": [],
        "runtime_execution_order": [],
        "comparisons": {},
        "cold_import": {},
        "configured_backends": {},
    }
    output = Path(args.output)

    def save():
        output.write_text(json.dumps(report, indent=2) + "\n")

    for round_number, order in enumerate(round_orders, start=1):
        for position, name in enumerate(order, start=1):
            sample = invoke(args, sources[name], round_number - 1)
            report["raw"][name].append(sample)
            report["runtime_execution_order"].append(
                {
                    "round": round_number,
                    "position": position,
                    "source": name,
                    "order": list(order),
                }
            )
            report["position_balance"] = summarize_execution_position_coverage(
                report["runtime_execution_order"]
            )
            save()
        report["rounds"].append(
            {
                "round": round_number,
                "order": list(order),
                "positions": [
                    {"position": position, "source": source}
                    for position, source in enumerate(order, start=1)
                ],
            }
        )
        report["completed_position_balance"] = summarize_position_coverage(
            round_orders[:round_number]
        )
        save()
    candidate = report["raw"]["candidate"]
    position_maps = execution_position_maps(report["runtime_execution_order"])
    for name in ("pre28", "pre29"):
        baseline = report["raw"][name]
        report["comparisons"][name] = {
            load: compare_load_by_position(
                baseline,
                candidate,
                load,
                baseline_positions=position_maps[name],
                candidate_positions=position_maps["candidate"],
            )
            for load in candidate[0]["samples_s"]
        }
        before = statistics.median(row["rss_bytes"] for row in baseline)
        after = statistics.median(row["rss_bytes"] for row in candidate)
        report["comparisons"][name]["rss"] = {
            "baseline_bytes": before,
            "candidate_bytes": after,
            "within_budget": after - before <= max(before * 0.05, 10 * 1024**2),
        }
    save()
    for light in (False, True):
        raw = {name: [] for name in sources}
        cold_orders = build_crossover_orders(COLD_IMPORT_ROUNDS)
        execution_order = []
        for round_number, order in enumerate(cold_orders, start=1):
            for position, name in enumerate(order, start=1):
                raw[name].append(cold(sources[name], light, probe_harness_before["harness_root"]))
                execution_order.append(
                    {
                        "round": round_number,
                        "position": position,
                        "source": name,
                        "order": list(order),
                    }
                )
        medians = {name: statistics.median(rows) for name, rows in raw.items()}
        cold_position_maps = execution_position_maps(execution_order)
        position_stratified_comparisons = {
            name: compare_cold_import_by_position(
                raw[name],
                raw["candidate"],
                baseline_positions=cold_position_maps[name],
                candidate_positions=cold_position_maps["candidate"],
            )
            for name in ("pre28", "pre29")
        }
        report["cold_import"]["light" if light else "default"] = {
            "raw_s": raw,
            "median_s": medians,
            "rounds": [
                {"round": round_number, "order": list(order)}
                for round_number, order in enumerate(cold_orders, start=1)
            ],
            "position_balance": summarize_position_coverage(cold_orders),
            "execution_order": execution_order,
            "position_stratified_comparisons": position_stratified_comparisons,
            "within_budget": {
                name: position_stratified_comparisons[name]["within_budget"]
                for name in ("pre28", "pre29")
            },
        }
        save()
    for index in range(args.pairs):
        for backend in (("stdlib", "spdlog") if index % 2 == 0 else ("spdlog", "stdlib")):
            report["configured_backends"].setdefault(backend, []).append(
                invoke(args, sources["candidate"], index, backend)
            )
            save()
    source_snapshots_after = {
        name: source_snapshot_manifest(path) for name, path in sources.items()
    }
    report["source_snapshots"]["after"] = source_snapshots_after
    report["source_snapshots"]["unchanged"] = source_snapshots_after == source_snapshots_before
    probe_harness_after = probe_harness_manifest(args.probe)
    report["probe_harness"]["after"] = probe_harness_after
    report["probe_harness"]["unchanged"] = probe_harness_after == probe_harness_before
    comparator_after = {"path": str(comparator_path), "sha256": _file_sha256(comparator_path)}
    report["comparator"]["after"] = comparator_after
    report["comparator"]["unchanged"] = comparator_after == comparator_before
    save()
    if not report["source_snapshots"]["unchanged"]:
        raise RuntimeError("source snapshot changed while runtime comparator was executing")
    if not report["probe_harness"]["unchanged"]:
        raise RuntimeError("runtime probe or shared fixture changed while comparator was executing")
    if not report["comparator"]["unchanged"]:
        raise RuntimeError("runtime comparator changed while it was executing")
    report["release_gate"] = release_gate_status(report)
    save()
    print(
        json.dumps(
            {
                "release_gate": report["release_gate"],
                "comparisons": report["comparisons"],
                "cold_import": report["cold_import"],
            },
            indent=2,
        )
    )
    return 0 if report["release_gate"]["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    for name in ("source", "pre28", "pre29", "probe", "output", "backend", "log-dir"):
        parser.add_argument("--" + name)
    parser.add_argument(
        "--pairs",
        type=int,
        default=9,
        help="paired rounds (minimum 3 for diagnosis; 9 required for a passing release gate)",
    )
    parsed = parser.parse_args()
    if not parsed.worker and parsed.pairs < MIN_PAIRS_FOR_POSITION_COVERAGE:
        parser.error(
            "--pairs must be at least {} to cover all three execution positions".format(
                MIN_PAIRS_FOR_POSITION_COVERAGE
            )
        )
    if parsed.worker:
        worker(parsed)
    else:
        sys.exit(main(parsed))
