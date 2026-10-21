#!/usr/bin/env python3
"""Prepare/run a narrow installed-wheel native + offline regression for 025/026.

This helper is intentionally not run during preparation. By default it prints a
read-only plan. Pass --execute only after the reviewed wheel is installed and
the intended source commit has been provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


EXAMPLES: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("025", "025_factor_single", "close_ma_factor_strategy.py", ("close_ma",)),
    (
        "026",
        "026_factor_multi",
        "multi_factor_strategy.py",
        ("close_ma", "kdj_j", "roc"),
    ),
)
EXAMPLE_FILES = ("run.py", "README.md", "config.yaml")
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
PERIODS = (1,)
HARNESS_DEFAULT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代45-Indicator因子研究与多因子合成"
    / "evidence"
    / "iteration45-offline-20261022"
    / "scripts"
    / "iteration45_offline_reevaluation_acceptance_r4.py"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_fingerprint(root: Path) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "file_count": len(files),
        "files": files,
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object: %s" % path)
    return value


def _git_source_facts(source_root: Path) -> Dict[str, Any]:
    head = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "-C", str(source_root), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"head": head, "branch": branch}


def _package_probe(python: Path, source_root: Path) -> Dict[str, Any]:
    probe = r"""
import json, pathlib, sys, sysconfig
import backtrader, fincore
prefix = pathlib.Path(sys.prefix).resolve()
purelib = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
def inside(path, root):
    try:
        pathlib.Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False
items = {
    "python": sys.version.split()[0],
    "prefix": str(prefix),
    "purelib": str(purelib),
    "backtrader": {
        "origin": str(pathlib.Path(backtrader.__file__).resolve()),
        "version": getattr(backtrader, "__version__", None),
    },
    "fincore": {
        "origin": str(pathlib.Path(fincore.__file__).resolve()),
        "version": getattr(fincore, "__version__", None),
    },
}
items["installed_origins"] = all(
    inside(items[name]["origin"], purelib) for name in ("backtrader", "fincore")
)
print(json.dumps(items, sort_keys=True))
if not items["installed_origins"]:
    raise SystemExit(2)
"""
    result = subprocess.run(
        [str(python), "-I", "-c", probe],
        cwd=str(source_root.parent),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "installed-package origin preflight failed: %s" % (result.stderr.strip() or result.stdout.strip())
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("installed-package origin preflight returned no JSON")
    value = json.loads(lines[-1])
    if value.get("installed_origins") is not True:
        raise RuntimeError("Backtrader and fincore must both resolve from installed site-packages")
    return value


def _prepare_inputs(
    source_root: Path,
    output_root: Path,
    harness: Path,
    examples: Sequence[Tuple[str, str, str, Tuple[str, ...]]],
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    for _, example_name, strategy_name, _ in examples:
        source_dir = source_root / "examples" / "backtest" / example_name
        copy_dir = output_root / "examples" / "backtest" / example_name
        copy_dir.mkdir(parents=True, exist_ok=True)
        for name in (strategy_name, *EXAMPLE_FILES):
            source = source_dir / name
            if not source.is_file():
                raise FileNotFoundError("missing public example input: %s" % source)
            copied = copy_dir / name
            shutil.copyfile(source, copied)
            source_hash = _sha256_file(source)
            copied_hash = _sha256_file(copied)
            if source_hash != copied_hash:
                raise RuntimeError("source/copy hash mismatch: %s" % source)
            files.append(
                {
                    "source": str(source),
                    "copy": str(copied),
                    "bytes": source.stat().st_size,
                    "sha256": source_hash,
                }
            )

    support_dir = output_root / "scripts"
    support_dir.mkdir(parents=True, exist_ok=True)
    copied_harness = support_dir / "iteration45_offline_reevaluation_acceptance_r4.py"
    if not harness.is_file():
        raise FileNotFoundError("reviewed offline worker harness is unavailable: %s" % harness)
    shutil.copyfile(harness, copied_harness)
    support = {
        "source": str(harness),
        "copy": str(copied_harness),
        "bytes": copied_harness.stat().st_size,
        "sha256": _sha256_file(copied_harness),
    }
    return {"examples": files, "offline_worker_harness": support}


def _run_logged(
    command: Sequence[str],
    *,
    cwd: Path,
    output_dir: Path,
    timeout_seconds: int,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        timed_out = False
        return_code: Optional[int] = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = time.monotonic() - started
    (output_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (output_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    record = {
        "command": list(command),
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": elapsed,
        "return_code": return_code,
        "timed_out": timed_out,
    }
    _json_write(output_dir / "process.json", record)
    if timed_out or return_code != 0:
        raise RuntimeError(
            "command failed or timed out; see %s" % output_dir
        )
    return record


def _table_records(manifest: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = manifest.get("files")
    if not isinstance(raw, dict):
        raise ValueError("evaluation manifest has no files mapping")
    expected = {name + suffix for name in TABLES for suffix in (".csv", ".json")}
    records: Dict[str, Dict[str, Any]] = {}
    for name in expected:
        record = raw.get(name)
        if not isinstance(record, dict):
            raise ValueError("evaluation manifest is missing %s" % name)
        records[name] = {
            "bytes": record.get("bytes"),
            "rows": record.get("rows"),
            "sha256": record.get("sha256"),
        }
    if set(records) != expected:
        raise ValueError("evaluation table inventory is incomplete")
    return records


def _verify_native_run(
    run_dir: Path,
    probe: Mapping[str, Any],
    *,
    expected_case: str,
    expected_example: str,
    expected_factors: Sequence[str],
) -> Dict[str, Any]:
    manifest = _read_json(run_dir / "run_manifest.json")
    evaluation = _read_json(run_dir / "evaluation" / "manifest.json")
    if manifest.get("status") != "COMPLETED" or manifest.get("exit_code") != 0:
        raise RuntimeError("native example did not complete cleanly: %s" % run_dir)
    if manifest.get("example_id") != expected_example:
        raise RuntimeError("native example ID does not match its copied runner")
    if manifest.get("mode") != "native_cerebro_collection":
        raise RuntimeError("example did not perform native Cerebro collection")
    if manifest.get("acceptance_status") != "NOT_CLAIMED":
        raise RuntimeError("native example changed its evidence status")
    if manifest.get("evaluation_id") != evaluation.get("evaluation_id"):
        raise RuntimeError("native run and evaluation IDs differ")
    if evaluation.get("complete") is not True:
        raise RuntimeError("native evaluation export is incomplete")
    broker = manifest.get("broker", {})
    if broker.get("observed") is not True or broker.get("submit") != 0 or broker.get("cancel") != 0:
        raise RuntimeError("native research run did not observe zero broker submit/cancel calls")
    package_versions = manifest.get("versions", {})
    for name in ("backtrader", "fincore"):
        record = package_versions.get(name, {})
        origin = record.get("module_file")
        if not origin or not Path(origin).resolve().is_relative_to(Path(probe["purelib"]).resolve()):
            raise RuntimeError("native %s origin is outside installed site-packages" % name)
    dataset_dir = Path(manifest["dataset"]["dataset_path"]).resolve()
    if tuple(manifest["dataset"].get("factor_names", ())) != tuple(expected_factors):
        raise RuntimeError("native factor dataset does not contain the expected factors")
    if manifest["dataset"].get("grid_rows") != 301:
        raise RuntimeError("native dataset does not preserve the minimum 301-bar grid")
    dataset_manifest = _read_json(dataset_dir / "manifest.json")
    if dataset_manifest.get("dataset_id") != manifest["dataset"]["dataset_id"]:
        raise RuntimeError("native saved dataset ID does not match run manifest")
    records = _table_records(evaluation)
    if len(records) != 22:
        raise RuntimeError("native evaluation did not export all 22 CSV/JSON table files")
    if run_dir.name != expected_case or run_dir.parent.name != "native":
        raise RuntimeError("native output is outside its unique case directory")
    if manifest.get("required_output_validation", {}).get("passed") is not True:
        raise RuntimeError("native required-output validation failed")
    return {
        "run_manifest": manifest,
        "evaluation_manifest": evaluation,
        "table_records": records,
        "dataset_dir": str(dataset_dir),
        "dataset_tree_before_offline": _tree_fingerprint(dataset_dir),
    }


def _offline_spec(
    *,
    output_root: Path,
    case: str,
    example_name: str,
    dataset_dir: Path,
    periods: Sequence[int],
) -> Tuple[Path, Path]:
    example_dir = output_root / "examples" / "backtest" / example_name
    scenario_dir = output_root / "offline" / case
    scenario_dir.mkdir(parents=True, exist_ok=False)
    spec_path = scenario_dir / "worker_spec.json"
    _json_write(
        spec_path,
        {
            "scenario": "iteration46_%s_same_config" % case,
            "example_id": "025_factor_single" if case == "025" else "026_factor_multi",
            "periods": list(periods),
            "repo_root": str(output_root),
            "example_dir": str(example_dir),
            "dataset_dir": str(dataset_dir),
            "scenario_dir": str(scenario_dir),
            "runner_path": str(example_dir / "run.py"),
            "config_path": str(example_dir / "config.yaml"),
            "module_name": "iteration46_offline_runner_%s" % case,
        },
    )
    return scenario_dir, spec_path


def _verify_offline_run(
    scenario_dir: Path,
    native: Mapping[str, Any],
) -> Dict[str, Any]:
    report = _read_json(scenario_dir / "worker_report.json")
    run_manifest = report.get("run_manifest")
    evaluation = report.get("evaluation_manifest")
    if not isinstance(run_manifest, dict) or not isinstance(evaluation, dict):
        raise RuntimeError("offline worker did not produce run/evaluation manifests")
    if report.get("passed") is not True or report.get("runner_exit_code") != 0:
        raise RuntimeError("guarded offline worker did not pass: %s" % scenario_dir)
    if run_manifest.get("status") != "COMPLETED" or run_manifest.get("exit_code") != 0:
        raise RuntimeError("offline CLI did not complete cleanly")
    if run_manifest.get("acceptance_status") != "NOT_CLAIMED":
        raise RuntimeError("offline CLI changed its evidence status")
    if run_manifest.get("evaluation_id") != native["run_manifest"].get("evaluation_id"):
        raise RuntimeError("native/offline evaluation IDs differ")
    if run_manifest.get("dataset", {}).get("dataset_id") != native["run_manifest"].get("dataset", {}).get("dataset_id"):
        raise RuntimeError("native/offline dataset IDs differ")
    if report.get("dataset_id_before") != report.get("dataset_id_after"):
        raise RuntimeError("offline evaluation changed the saved dataset identity")
    if report.get("dataset_fingerprint_before") != report.get("dataset_fingerprint_after"):
        raise RuntimeError("offline evaluation changed saved dataset bytes")
    counters = report.get("guards", {}).get("counters", {})
    if not counters or any(value != 0 for value in counters.values()):
        raise RuntimeError("offline evaluation crossed a Cerebro/indicator execution guard")
    offline_records = _table_records(evaluation)
    if offline_records != native["table_records"]:
        raise RuntimeError("native/offline table value identity differs by hash/bytes/rows")
    if run_manifest.get("required_output_validation", {}).get("passed") is not True:
        raise RuntimeError("offline required-output validation failed")
    if report.get("table_files_verified_against_manifest") is not True:
        raise RuntimeError("offline table artifacts do not match their manifest")
    return {
        "worker_report": report,
        "evaluation_id": run_manifest["evaluation_id"],
        "dataset_id": run_manifest["dataset"]["dataset_id"],
        "table_records_equal_native": True,
        "dataset_bytes_unchanged": True,
        "guards": counters,
    }


def _copy_and_run(args: argparse.Namespace) -> int:
    source_root = args.source_root.resolve(strict=True)
    output_root = args.output_root.resolve()
    try:
        output_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("--output-root must be outside the source repository")
    if output_root.exists():
        raise FileExistsError("output directory already exists; refusing to overwrite")
    if not args.expected_source_commit:
        raise ValueError("--expected-source-commit is required with --execute")
    selected_cases = set(args.cases or (item[0] for item in EXAMPLES))
    selected_examples = tuple(item for item in EXAMPLES if item[0] in selected_cases)
    if not selected_examples or {item[0] for item in selected_examples} != selected_cases:
        raise ValueError("--cases must select one or more configured examples")
    git_facts = _git_source_facts(source_root)
    if git_facts["head"].lower() != args.expected_source_commit.lower():
        raise RuntimeError("source HEAD does not match --expected-source-commit")
    python = args.python.resolve(strict=True)
    harness = args.offline_harness.resolve(strict=True)
    probe = _package_probe(python, source_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir()
    summary: Dict[str, Any] = {
        "schema": "iteration46-examples-installed-regression-v1",
        "status": "RUNNING",
        "acceptance_status": "LOCAL_INSTALLED_EXAMPLE_REGRESSION_ONLY",
        "evidence_level": "INSTALLED_WHEEL_SYNTHETIC_NATIVE_AND_OFFLINE",
        "source_root": str(source_root),
        "source_git": git_facts,
        "python": str(python),
        "installed_packages": probe,
        "periods": list(PERIODS),
        "cases": [item[0] for item in selected_examples],
        "charts": False,
        "started_at_utc": _utc_now(),
        "scenarios": {},
    }
    _json_write(output_root / "summary.json", summary)
    try:
        input_manifest = _prepare_inputs(source_root, output_root, harness, selected_examples)
        input_manifest.update(
            {
                "schema": "iteration46-example-copy-inputs-v1",
                "source_git": git_facts,
                "source_root": str(source_root),
                "prepared_at_utc": _utc_now(),
            }
        )
        _json_write(output_root / "inputs_manifest.json", input_manifest)
        summary["inputs_manifest_sha256"] = _sha256_file(output_root / "inputs_manifest.json")
        _json_write(output_root / "summary.json", summary)

        for case, example_name, _, expected_factors in selected_examples:
            example_dir = output_root / "examples" / "backtest" / example_name
            native_dir = output_root / "native" / case
            if native_dir.exists():
                raise FileExistsError("native output already exists: %s" % native_dir)
            command = [
                str(python),
                "-E",
                "-s",
                str(example_dir / "run.py"),
                "--periods",
                *[str(value) for value in PERIODS],
                "--no-charts",
                "--output-dir",
                str(native_dir),
            ]
            native_process = _run_logged(
                command,
                cwd=example_dir,
                output_dir=output_root / "logs" / ("native_" + case),
                timeout_seconds=args.timeout_seconds,
            )
            native = _verify_native_run(
                native_dir,
                probe,
                expected_case=case,
                expected_example=example_name,
                expected_factors=expected_factors,
            )
            summary["scenarios"][case] = {
                "native_process": native_process,
                "native_evaluation_id": native["run_manifest"]["evaluation_id"],
                "dataset_id": native["run_manifest"]["dataset"]["dataset_id"],
                "native_status": native["run_manifest"]["status"],
                "evaluation_status": native["run_manifest"].get("evaluation_status"),
                "table_file_count": len(native["table_records"]),
            }
            _json_write(output_root / "summary.json", summary)

            scenario_dir, spec_path = _offline_spec(
                output_root=output_root,
                case=case,
                example_name=example_name,
                dataset_dir=Path(native["dataset_dir"]),
                periods=PERIODS,
            )
            offline_command = [
                str(python),
                "-E",
                "-s",
                str(output_root / "scripts" / "iteration45_offline_reevaluation_acceptance_r4.py"),
                "--_worker-spec",
                str(spec_path),
            ]
            offline_process = _run_logged(
                offline_command,
                cwd=output_root,
                output_dir=output_root / "logs" / ("offline_" + case),
                timeout_seconds=args.timeout_seconds,
            )
            offline = _verify_offline_run(scenario_dir, native)
            summary["scenarios"][case].update(
                {
                    "offline_process": offline_process,
                    "offline_evaluation_id": offline["evaluation_id"],
                    "offline_table_hashes_match": offline["table_records_equal_native"],
                    "offline_dataset_bytes_unchanged": offline["dataset_bytes_unchanged"],
                    "offline_execution_guards": offline["guards"],
                    "required_output_validation": True,
                }
            )
            _json_write(output_root / "summary.json", summary)

        summary["status"] = "PASS"
        summary["finished_at_utc"] = _utc_now()
        summary["performance_acceptance"] = False
        _json_write(output_root / "summary.json", summary)
        print(
            "PASS: %s native collection + same-config offline table identity"
            % "/".join(item[0] for item in selected_examples)
        )
        return 0
    except BaseException as exc:
        summary["status"] = "FAILED"
        summary["finished_at_utc"] = _utc_now()
        summary["failure_type"] = type(exc).__name__
        summary["failure"] = str(exc)
        _json_write(output_root / "summary.json", summary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run only after the wheel is installed and the source commit is pinned")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True, help="new external D:/temp evidence directory")
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=tuple(item[0] for item in EXAMPLES),
        help="optional subset; defaults to both examples",
    )
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="installed environment Python")
    parser.add_argument("--expected-source-commit", help="required with --execute; prevents running against a different source revision")
    parser.add_argument("--offline-harness", type=Path, default=HARNESS_DEFAULT)
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="per native/offline case, not a performance threshold")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    selected_cases = set(args.cases or (item[0] for item in EXAMPLES))
    selected_examples = tuple(item for item in EXAMPLES if item[0] in selected_cases)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY",
                    "source_root": str(args.source_root.resolve()),
                    "output_root": str(args.output_root.resolve()),
                    "periods": list(PERIODS),
                    "native_examples": [item[1] for item in selected_examples],
                    "offline_cases": [item[0] for item in selected_examples],
                    "fixture_contract": {
                        "minimum_assets": 20,
                        "research_bars": 260,
                        "warmup_bars": 20,
                        "tail_bars": 21,
                        "grid_bars": 301,
                    },
                    "note": "No directories, files, runs, or evaluations were created.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return _copy_and_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
