"""Run the Iteration 45 saved-dataset offline re-evaluation acceptance matrix.

Each scenario starts a fresh isolated interpreter and invokes the example
runner's public ``main --dataset`` path. The report distinguishes the source
runner from the installed Backtrader and fincore import origins.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
from typing import Any, Dict, Mapping, Optional, Sequence


SCRIPT_PATH = Path(__file__).resolve()
TABLES = (
    "signals",
    "labels",
    "ic",
    "ic_summary",
    "quantile_returns",
    "spreads",
    "stability",
    "correlation",
    "comparisons",
    "coverage",
    "diagnostics",
)
GUARD_KEYS = ("cerebro_run", "factor_construct", "factor_next", "factor_once")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_fingerprint(root: Path) -> Dict[str, Any]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("dataset path must be a directory: %s" % root)
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("dataset contains a symlink: %s" % path)
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files.append(
                {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256_file(path)}
            )
    if not files:
        raise ValueError("dataset directory contains no files")
    digest = hashlib.sha256(_json_bytes(files)).hexdigest()
    return {"sha256": digest, "file_count": len(files), "files": files}


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _installed_import_facts(repo_root: Path) -> Dict[str, Any]:
    import backtrader
    import fincore

    bt_path = Path(backtrader.__file__).resolve()
    fincore_path = Path(fincore.__file__).resolve()
    site_prefix = Path(sys.prefix).resolve(strict=True)
    for label, module_path in (("Backtrader", bt_path), ("fincore", fincore_path)):
        if not _is_within(module_path, site_prefix):
            raise RuntimeError("%s did not resolve inside the active Python prefix" % label)
        if "site-packages" not in {part.casefold() for part in module_path.parts}:
            raise RuntimeError("%s did not resolve from site-packages" % label)
        if _is_within(module_path, repo_root):
            raise RuntimeError("%s resolved from the Backtrader source checkout" % label)
    try:
        bt_version = importlib.metadata.version("backtrader")
    except importlib.metadata.PackageNotFoundError:
        bt_version = None
    try:
        fincore_version = importlib.metadata.version("fincore")
    except importlib.metadata.PackageNotFoundError:
        fincore_version = None
    return {
        "python": sys.version.split()[0],
        "executable": str(Path(sys.executable).resolve()),
        "sys_prefix": str(site_prefix),
        "backtrader": {"origin": str(bt_path), "version": bt_version},
        "fincore": {"origin": str(fincore_path), "version": fincore_version},
    }


def _load_runner(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source runner: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _install_no_execution_guards(repo_root: Path, example_dir: Path) -> Dict[str, Any]:
    """Make any backtest/indicator execution attempt fail and count it."""
    import backtrader
    from backtrader.cerebro import Cerebro
    from backtrader.research import FactorIndicator

    counters = dict.fromkeys(GUARD_KEYS, 0)

    def blocked(key: str, detail: str):
        def reject(*args: Any, **kwargs: Any) -> Any:
            counters[key] += 1
            raise RuntimeError("offline acceptance guard blocked %s" % detail)

        return reject

    for method_name in ("run", "runstrategies", "_runonce", "_runnext"):
        if hasattr(Cerebro, method_name):
            setattr(
                Cerebro,
                method_name,
                blocked("cerebro_run", "Cerebro.%s" % method_name),
            )
    FactorIndicator.__init__ = blocked("factor_construct", "FactorIndicator.__init__")
    FactorIndicator.next = blocked("factor_next", "FactorIndicator.next")
    FactorIndicator.once = blocked("factor_once", "FactorIndicator.once")
    FactorIndicator.bind = classmethod(blocked("factor_construct", "FactorIndicator.bind"))
    FactorIndicator._bind_for_research = classmethod(
        blocked("factor_construct", "FactorIndicator._bind_for_research")
    )

    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(example_dir))
        if example_dir.name == "025_factor_single":
            factor_module = importlib.import_module("close_ma_factor_strategy")
            factor_classes = (factor_module.CloseMAFactor,)
        else:
            factor_module = importlib.import_module("multi_factor_strategy")
            factor_classes = (
                factor_module.CloseMAFactor,
                factor_module.ROCFactor,
                factor_module.KDJFactor,
            )
    finally:
        sys.path[:] = old_path

    for factor_class in factor_classes:
        factor_class.__init__ = blocked("factor_construct", factor_class.__name__ + ".__init__")
        factor_class.next = blocked("factor_next", factor_class.__name__ + ".next")
        factor_class.once = blocked("factor_once", factor_class.__name__ + ".once")

    return {
        "counters": counters,
        "guarded_types": {
            "cerebro": "%s.%s" % (Cerebro.__module__, Cerebro.__name__),
            "factor_base": "%s.%s" % (FactorIndicator.__module__, FactorIndicator.__name__),
            "factor_classes": [
                "%s.%s" % (item.__module__, item.__name__) for item in factor_classes
            ],
        },
        "backtrader_package_origin": str(Path(backtrader.__file__).resolve()),
    }


def _worker(spec_path: Path) -> int:
    spec = _read_json(spec_path)
    repo_root = Path(spec["repo_root"]).resolve(strict=True)
    example_dir = Path(spec["example_dir"]).resolve(strict=True)
    dataset_dir = Path(spec["dataset_dir"]).resolve(strict=True)
    scenario_dir = Path(spec["scenario_dir"]).resolve()
    run_dir = scenario_dir / "run"
    report_path = scenario_dir / "worker_report.json"
    report: Dict[str, Any] = {
        "scenario": spec["scenario"],
        "example_id": spec["example_id"],
        "periods": spec["periods"],
        "dataset_path": str(dataset_dir),
        "source_runner": str((example_dir / "run.py").resolve()),
        "worker_python": sys.version.split()[0],
    }
    try:
        # Isolated mode ignores ambient PYTHONPATH. Also remove the checkout
        # from sys.path so all package imports must resolve from the installed wheel.
        clean_path = []
        for entry in sys.path:
            if not entry:
                continue
            candidate = Path(entry)
            if candidate.exists() and _is_within(candidate, repo_root):
                continue
            clean_path.append(entry)
        sys.path[:] = clean_path

        imports = _installed_import_facts(repo_root)
        before = _tree_fingerprint(dataset_dir)
        from backtrader.research.storage import load_dataset

        dataset = load_dataset(dataset_dir)
        dataset_id = str(dataset.dataset_id)
        if not dataset_id:
            raise RuntimeError("loaded ResearchDataset has no dataset_id")
        report["dataset_id_before"] = dataset_id
        report["dataset_fingerprint_before"] = before
        report["imports"] = imports

        runner = _load_runner(Path(spec["runner_path"]).resolve(strict=True), spec["module_name"])
        config_path = Path(spec["config_path"]).resolve(strict=True)
        original_load_config = runner._load_config

        def load_selected_config(path: Path = config_path) -> Dict[str, Any]:
            return original_load_config(path)

        config = load_selected_config()
        if config.get("example_id") != spec["example_id"]:
            raise ValueError("scenario config identity does not match its runner")
        # The runner's own loader and summary hash both use CONFIG_PATH.
        runner.CONFIG_PATH = config_path
        runner._load_config = load_selected_config
        guard = _install_no_execution_guards(repo_root, example_dir)
        if run_dir.exists():
            raise FileExistsError("scenario output already exists: %s" % run_dir)
        argv = [
            "--dataset",
            str(dataset_dir),
            "--periods",
            *[str(int(item)) for item in spec["periods"]],
            "--output-dir",
            str(run_dir),
            "--no-charts",
        ]
        exit_code = int(runner.main(argv))
        run_manifest_path = run_dir / "run_manifest.json"
        summary_path = run_dir / "summary.json"
        run_manifest = _read_json(run_manifest_path) if run_manifest_path.is_file() else None
        summary = _read_json(summary_path) if summary_path.is_file() else None
        evaluation_manifest_path = run_dir / "evaluation" / "manifest.json"
        evaluation_manifest = (
            _read_json(evaluation_manifest_path) if evaluation_manifest_path.is_file() else None
        )
        after = _tree_fingerprint(dataset_dir)
        dataset_after = load_dataset(dataset_dir)
        dataset_id_after = str(dataset_after.dataset_id)
        file_records = (
            evaluation_manifest.get("files", {})
            if isinstance(evaluation_manifest, dict)
            else {}
        )
        evaluation_files = {}
        table_files_verified = True
        for name in TABLES:
            for suffix in (".csv", ".json"):
                key = name + suffix
                record = file_records.get(key) if isinstance(file_records, dict) else None
                table_path = run_dir / "evaluation" / key
                if isinstance(record, dict) and table_path.is_file():
                    actual = {
                        "sha256": _sha256_file(table_path),
                        "bytes": table_path.stat().st_size,
                        "rows": record.get("rows"),
                    }
                    matches = (
                        actual["sha256"] == record.get("sha256")
                        and actual["bytes"] == record.get("bytes")
                    )
                    table_files_verified = table_files_verified and matches
                    evaluation_files[key] = {
                        **actual,
                        "manifest_sha256": record.get("sha256"),
                        "manifest_bytes": record.get("bytes"),
                        "matches_manifest": matches,
                    }
                else:
                    table_files_verified = False

        report.update(
            {
                "cli": ["main", *argv],
                "runner_exit_code": exit_code,
                "run_manifest": run_manifest,
                "summary": summary,
                "evaluation_manifest": evaluation_manifest,
                "evaluation_files": evaluation_files,
                "table_files_verified_against_manifest": table_files_verified,
                "dataset_id_after": dataset_id_after,
                "dataset_fingerprint_after": after,
                "guards": guard,
            }
        )
        report["passed"] = bool(
            exit_code == 0
            and isinstance(run_manifest, dict)
            and run_manifest.get("status") == "COMPLETED"
            and run_manifest.get("exit_code") == 0
            and run_manifest.get("evaluation_id")
            and run_manifest.get("required_output_validation", {}).get("passed") is True
            and run_manifest.get("export_validation", {}).get("passed") is True
            and isinstance(evaluation_manifest, dict)
            and evaluation_manifest.get("complete") is True
            and evaluation_manifest.get("evaluation_id") == run_manifest.get("evaluation_id")
            and set(evaluation_files) == {name + suffix for name in TABLES for suffix in (".csv", ".json")}
            and table_files_verified
            and dataset_id_after == dataset_id
            and before == after
            and all(value == 0 for value in guard["counters"].values())
        )
        if not report["passed"]:
            report["failure"] = "runner, manifest, dataset immutability, or execution guard check failed"
        _write_json(report_path, report)
        return 0 if report["passed"] else 1
    except BaseException as exc:
        report.update(
            {
                "passed": False,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        if "guard" in locals():
            report["guards"] = guard
        try:
            _write_json(report_path, report)
        except OSError:
            pass
        return 1


def _baseline_reference(
    run_dir: Path, short: str, example_id: str, dataset_id: str
) -> Dict[str, Any]:
    """Read and verify an already completed native run as the offline reference."""
    run_dir = run_dir.resolve(strict=True)
    if not run_dir.is_dir():
        raise ValueError("baseline run path must be a directory: %s" % run_dir)
    run_manifest = _read_json(run_dir / "run_manifest.json")
    evaluation_dir = run_dir / "evaluation"
    evaluation = _read_json(evaluation_dir / "manifest.json")
    if run_manifest.get("status") != "COMPLETED" or run_manifest.get("exit_code") != 0:
        raise ValueError("%s baseline must be a COMPLETED zero-exit run" % short)
    if run_manifest.get("example_id") != example_id:
        raise ValueError("%s baseline example_id mismatch" % short)
    if run_manifest.get("mode") != "native_cerebro_collection":
        raise ValueError("%s baseline is not a native Cerebro collection run" % short)
    if run_manifest.get("dataset", {}).get("dataset_id") != dataset_id:
        raise ValueError("%s baseline dataset_id does not match the supplied snapshot" % short)
    if evaluation.get("complete") is not True:
        raise ValueError("%s baseline evaluation manifest is incomplete" % short)
    if evaluation.get("evaluation_id") != run_manifest.get("evaluation_id"):
        raise ValueError("%s baseline run/evaluation ids do not match" % short)
    if evaluation.get("status") != run_manifest.get("evaluation_status"):
        raise ValueError("%s baseline run/evaluation statuses do not match" % short)

    expected = {name + suffix for name in TABLES for suffix in (".csv", ".json")}
    table_map = evaluation.get("tables")
    file_map = evaluation.get("files")
    if not isinstance(table_map, dict) or set(table_map) != set(TABLES):
        raise ValueError("%s baseline table inventory mismatch" % short)
    if not isinstance(file_map, dict) or set(file_map) != expected:
        raise ValueError("%s baseline must contain all 22 table summaries" % short)

    tables: Dict[str, Dict[str, Any]] = {}
    for name in TABLES:
        if table_map.get(name) != {"csv": name + ".csv", "json": name + ".json"}:
            raise ValueError("%s baseline table map mismatch: %s" % (short, name))
        for suffix in (".csv", ".json"):
            filename = name + suffix
            record = file_map[filename]
            if not isinstance(record, dict):
                raise ValueError("%s baseline summary missing for %s" % (short, filename))
            table_path = evaluation_dir / filename
            actual = {"bytes": table_path.stat().st_size, "sha256": _sha256_file(table_path)}
            if actual["bytes"] != record.get("bytes") or actual["sha256"] != record.get("sha256"):
                raise ValueError("%s baseline table bytes do not match manifest: %s" % (short, filename))
            rows = record.get("rows")
            if not isinstance(rows, int) or rows < 0:
                raise ValueError("%s baseline row summary is invalid: %s" % (short, filename))
            tables[filename] = {**actual, "rows": rows}

    return {
        "path": str(run_dir),
        "example_id": example_id,
        "status": run_manifest["status"],
        "exit_code": run_manifest["exit_code"],
        "mode": run_manifest["mode"],
        "evaluation_status": evaluation["status"],
        "evaluation_id": run_manifest["evaluation_id"],
        "dataset_id": dataset_id,
        "config_sha256": run_manifest.get("config_sha256"),
        "strategy_sha256": run_manifest.get("strategy_sha256"),
        "requested_periods": run_manifest.get("requested_periods"),
        "tables": tables,
    }


def _report_table_projection(report: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    files = report.get("evaluation_files")
    if not isinstance(files, dict):
        return {}
    projection = {}
    for filename, record in files.items():
        if isinstance(record, dict):
            projection[filename] = {
                "bytes": record.get("bytes"),
                "sha256": record.get("sha256"),
                "rows": record.get("rows"),
            }
    return projection


def _validate_scenario_matrix(
    reports: Mapping[str, Mapping[str, Any]],
    baselines: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    problems = []
    names = tuple(reports)
    for name, report in reports.items():
        if report.get("passed") is not True:
            problems.append("scenario_failed:%s" % name)
        guards = report.get("guards", {}).get("counters", {})
        if any(guards.get(key) != 0 for key in GUARD_KEYS):
            problems.append("execution_guard_nonzero:%s" % name)

    baseline_comparisons = {}
    expected_files = {name + suffix for name in TABLES for suffix in (".csv", ".json")}
    for short, baseline in baselines.items():
        scenario_name = short + "_same_config"
        report = reports.get(scenario_name, {})
        run = report.get("run_manifest")
        if not isinstance(run, dict):
            run = {}
        cli_tables = _report_table_projection(report)
        baseline_tables = baseline.get("tables", {})
        table_mismatches = [
            filename
            for filename in sorted(expected_files)
            if cli_tables.get(filename) != baseline_tables.get(filename)
        ]
        id_equal = run.get("evaluation_id") == baseline.get("evaluation_id")
        config_equal = run.get("config_sha256") == baseline.get("config_sha256")
        strategy_equal = run.get("strategy_sha256") == baseline.get("strategy_sha256")
        tables_equal = set(cli_tables) == expected_files and not table_mismatches
        comparison_passed = bool(
            report.get("passed") is True
            and id_equal
            and config_equal
            and strategy_equal
            and tables_equal
        )
        baseline_comparisons[short] = {
            "scenario": scenario_name,
            "baseline_evaluation_id": baseline.get("evaluation_id"),
            "reevaluation_evaluation_id": run.get("evaluation_id"),
            "evaluation_id_equal": id_equal,
            "config_sha256_equal": config_equal,
            "strategy_sha256_equal": strategy_equal,
            "table_files_equal": tables_equal,
            "table_mismatches": table_mismatches,
            "passed": comparison_passed,
        }
        if not comparison_passed:
            problems.append("baseline_comparison_failed:%s" % short)

    def eval_id(name: str) -> Optional[str]:
        run = reports.get(name, {}).get("run_manifest")
        return run.get("evaluation_id") if isinstance(run, dict) else None

    changed_pairs = tuple(
        pair
        for pair in (
            ("025_same_config", "025_periods_1_10"),
            ("026_same_config", "026_periods_1_10"),
            ("026_same_config", "026_weights_variant"),
        )
        if pair[0] in reports and pair[1] in reports
    )
    id_changes = {}
    for baseline, changed in changed_pairs:
        left_id, right_id = eval_id(baseline), eval_id(changed)
        id_changes[baseline + "__" + changed] = {
            "baseline": left_id,
            "changed": right_id,
            "different": bool(left_id and right_id and left_id != right_id),
        }
        if not left_id or not right_id or left_id == right_id:
            problems.append("evaluation_id_not_changed:%s:%s" % (baseline, changed))

    dataset_ids = {}
    dataset_fingerprints = {}
    for name, report in reports.items():
        dataset_ids.setdefault(name[:3], set()).add(report.get("dataset_id_before"))
        fingerprint = report.get("dataset_fingerprint_before")
        dataset_fingerprints.setdefault(name[:3], set()).add(
            fingerprint.get("sha256") if isinstance(fingerprint, dict) else None
        )
        if report.get("dataset_id_before") != report.get("dataset_id_after"):
            problems.append("dataset_id_changed_during_scenario:%s" % name)
        if report.get("dataset_fingerprint_before") != report.get("dataset_fingerprint_after"):
            problems.append("dataset_bytes_changed_during_scenario:%s" % name)
    for key in sorted(dataset_ids):
        if len(dataset_ids.get(key, set())) != 1 or None in dataset_ids.get(key, set()):
            problems.append("dataset_id_not_stable:%s" % key)
        if len(dataset_fingerprints.get(key, set())) != 1 or None in dataset_fingerprints.get(key, set()):
            problems.append("dataset_bytes_not_stable:%s" % key)
    return {
        "passed": not problems,
        "problems": problems,
        "scenario_count": len(names),
        "baseline_comparisons": baseline_comparisons,
        "variant_evaluation_id_comparisons": id_changes,
        "dataset_ids_by_example": {key: sorted(value) for key, value in dataset_ids.items()},
        "dataset_fingerprints_by_example": {
            key: sorted(value) for key, value in dataset_fingerprints.items()
        },
    }


def _read_example_config(config_path: Path, expected_id: str) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("the installed runner environment requires PyYAML") from exc
    with config_path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict) or value.get("example_id") != expected_id:
        raise ValueError("unexpected public example config: %s" % config_path)
    return value


def _make_scenarios(
    repo_root: Path,
    output_root: Path,
    dataset_paths: Mapping[str, Path],
    selected_examples: Sequence[str],
) -> Sequence[Dict[str, Any]]:
    specs = []
    examples = (
        ("025", "025_factor_single", "examples/backtest/025_factor_single", "close_ma_factor_strategy.py"),
        ("026", "026_factor_multi", "examples/backtest/026_factor_multi", "multi_factor_strategy.py"),
    )
    config_dir = output_root / "configs"
    config_dir.mkdir(parents=True, exist_ok=False)
    for short, example_id, relative, strategy_file in examples:
        if short not in selected_examples:
            continue
        example_dir = (repo_root / relative).resolve(strict=True)
        config_path = example_dir / "config.yaml"
        config = _read_example_config(config_path, example_id)
        baseline_periods = [int(value) for value in config["evaluation"]["periods"]]
        names = [
            (short + "_same_config", baseline_periods, config_path),
            (short + "_periods_1_10", [1, 10], config_path),
        ]
        if short == "026":
            variant = copy.deepcopy(config)
            combinations = variant["evaluation"].get("combinations", {})
            if tuple(combinations) != ("equal_weight",):
                raise ValueError("026 configuration does not contain the expected single combination")
            weights = combinations["equal_weight"]
            if tuple(weights) != ("close_ma", "roc", "kdj_j"):
                raise ValueError("026 equal_weight members do not match the documented factor set")
            changed_weights = dict(weights)
            changed_weights["close_ma"] = float(changed_weights["close_ma"]) * 2.0
            if math.isclose(changed_weights["close_ma"], float(weights["close_ma"])):
                raise ValueError("weight variant did not alter a factor weight")
            variant["evaluation"]["combinations"]["equal_weight"] = changed_weights
            variant_path = config_dir / "026_factor_multi_weights_variant.yaml"
            import yaml

            variant_path.write_text(
                yaml.safe_dump(variant, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            names.append(("026_weights_variant", baseline_periods, variant_path))

        for scenario_name, periods, selected_config in names:
            scenario_dir = output_root / "scenarios" / scenario_name
            control_dir = output_root / "control"
            control_dir.mkdir(parents=True, exist_ok=True)
            runner_path = example_dir / "run.py"
            spec = {
                "scenario": scenario_name,
                "example_id": example_id,
                "repo_root": str(repo_root),
                "example_dir": str(example_dir),
                "runner_path": str(runner_path),
                "strategy_file": strategy_file,
                "module_name": "iteration45_runner_" + scenario_name,
                "dataset_dir": str(dataset_paths[short]),
                "scenario_dir": str(scenario_dir),
                "config_path": str(selected_config.resolve()),
                "periods": periods,
            }
            spec_path = control_dir / (scenario_name + ".json")
            _write_json(spec_path, spec)
            specs.append({"scenario": scenario_name, "spec_path": spec_path, "scenario_dir": scenario_dir})
    return specs


def _run_matrix(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve(strict=True)
    selected_examples = tuple(dict.fromkeys(args.examples))
    if not selected_examples or any(item not in {"025", "026"} for item in selected_examples):
        raise ValueError("examples must select 025, 026, or both")
    requested_dataset_paths = {
        "025": args.single_dataset,
        "026": args.multi_dataset,
    }
    datasets = {
        key: Path(requested_dataset_paths[key]).resolve(strict=True)
        for key in selected_examples
        if requested_dataset_paths[key]
    }
    missing_dataset_args = set(selected_examples) - set(datasets)
    if missing_dataset_args:
        raise ValueError("missing dataset arguments for: %s" % sorted(missing_dataset_args))
    for key, path in datasets.items():
        if not path.is_dir() or not (path / "manifest.json").is_file():
            raise ValueError("%s dataset must be a saved ResearchDataset directory with manifest.json" % key)
    baseline_paths = list(args.baseline_run or ())
    if len(baseline_paths) != len(selected_examples):
        raise ValueError("pass one --baseline-run directory per selected example, in example order")
    baseline_refs = {}
    example_ids = {"025": "025_factor_single", "026": "026_factor_multi"}
    for short, raw_path in zip(selected_examples, baseline_paths):
        dataset_manifest = _read_json(datasets[short] / "manifest.json")
        dataset_id = dataset_manifest.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("%s dataset manifest has no dataset_id" % short)
        baseline_refs[short] = _baseline_reference(
            Path(raw_path), short, example_ids[short], dataset_id
        )
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError("output root already exists; choose a fresh evidence directory: %s" % output_root)
    output_root.mkdir(parents=True)
    dataset_before = {key: _tree_fingerprint(path) for key, path in datasets.items()}
    specs = _make_scenarios(repo_root, output_root, datasets, selected_examples)
    reports: Dict[str, Dict[str, Any]] = {}

    def run_scenario(item: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        scenario = item["scenario"]
        command = [
            sys.executable,
            "-I",
            str(SCRIPT_PATH),
            "--_worker-spec",
            str(item["spec_path"]),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(output_root),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=args.timeout_seconds,
                check=False,
            )
            item["scenario_dir"].mkdir(parents=True, exist_ok=True)
            (item["scenario_dir"] / "worker.stdout.txt").write_text(
                completed.stdout, encoding="utf-8"
            )
            (item["scenario_dir"] / "worker.stderr.txt").write_text(
                completed.stderr, encoding="utf-8"
            )
            worker_path = item["scenario_dir"] / "worker_report.json"
            report = _read_json(worker_path) if worker_path.is_file() else {
                "scenario": scenario,
                "passed": False,
                "failure": "worker_report_missing",
                "process_exit_code": completed.returncode,
            }
            report["worker_process_exit_code"] = completed.returncode
        except subprocess.TimeoutExpired as exc:
            report = {
                "scenario": scenario,
                "passed": False,
                "failure": "worker_timeout",
                "timeout_seconds": args.timeout_seconds,
                "stdout_tail": (exc.stdout or b"")[-4000:].decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else str(exc.stdout or "")[-4000:],
                "stderr_tail": (exc.stderr or b"")[-4000:].decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr or "")[-4000:],
            }
        except Exception as exc:
            report = {
                "scenario": scenario,
                "passed": False,
                "failure": "worker_launcher_error",
                "exception_type": type(exc).__name__,
            }
        _write_json(output_root / "scenario_reports" / (scenario + ".json"), report)
        return scenario, report

    with ThreadPoolExecutor(
        max_workers=min(2, len(specs)), thread_name_prefix="iteration45-offline"
    ) as executor:
        futures = [executor.submit(run_scenario, item) for item in specs]
        for future in as_completed(futures):
            scenario, report = future.result()
            reports[scenario] = report

    dataset_after = {key: _tree_fingerprint(path) for key, path in datasets.items()}
    matrix = _validate_scenario_matrix(reports, baseline_refs)
    dataset_unchanged = dataset_before == dataset_after
    result = {
        "schema": "iteration45-offline-reevaluation-acceptance-v1",
        "status": "PASS" if matrix["passed"] and dataset_unchanged else "FAIL",
        "evidence_level": "INSTALLED_BACKTRADER_OFFLINE_DATASET_REEVALUATION_ONLY",
        "acceptance_status": "LOCAL_ACCEPTANCE_SCRIPT_RESULT",
        "runner_contract": "examples/backtest/{025_factor_single,026_factor_multi}/run.py main --dataset",
        "examples": list(selected_examples),
        "repo_root": str(repo_root),
        "python": sys.version.split()[0],
        "python_executable": str(Path(sys.executable).resolve()),
        "datasets": {
            key: {
                "path": str(datasets[key]),
                "before": dataset_before[key],
                "after": dataset_after[key],
                "unchanged": dataset_before[key] == dataset_after[key],
            }
            for key in datasets
        },
        "baseline_runs": baseline_refs,
        "scenarios": reports,
        "matrix_validation": matrix,
        "all_input_dataset_bytes_unchanged": dataset_unchanged,
    }
    _write_json(output_root / "acceptance_report.json", result)
    print("%s: %s (%d scenarios)" % (output_root, result["status"], len(reports)))
    return 0 if result["status"] == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, help="Backtrader source checkout used for example runner files")
    parser.add_argument("--examples", nargs="+", choices=("025", "026"), default=("025",), help="which saved example datasets to exercise")
    parser.add_argument("--single-dataset", help="saved 025 ResearchDataset directory")
    parser.add_argument("--multi-dataset", help="saved 026 ResearchDataset directory")
    parser.add_argument(
        "--baseline-run",
        action="append",
        required=True,
        help="completed native run directory; repeat once per selected example in the same order",
    )
    parser.add_argument("--output-root", required=True, help="new external evidence directory; must not exist")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="per-scenario subprocess timeout")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 2 and arguments[0] == "--_worker-spec":
        return _worker(Path(arguments[1]).resolve(strict=True))
    args = _parser().parse_args(arguments)
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    try:
        return _run_matrix(args)
    except BaseException as exc:
        print("ACCEPTANCE_HARNESS_ERROR: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
