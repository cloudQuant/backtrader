"""Self-contained clean-install acceptance matrix for seven archetypes and two profiles."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, canonical_hash, file_hash
from .data import ADAPTERS, DataRegistry
from .doctor import run_doctor
from .drafts import DraftManager
from .errors import ExecutionError, IntegrityError
from .ir import ARCHETYPES, OUTPUT_PROFILES, default_strategy_spec
from .repair import preview_spec_repair
from .runner import ControlledRunner
from .runtime import RuntimePaths
from .validation import validate_python

REPAIR_PROFILES = {
    "multi_asset_allocation": "single_test",
    "multi_timeframe": "python_bundle",
    "precomputed_ml": "single_test",
}


def _write_fixture(
    path: Path,
    *,
    adapter: str,
    phase: float = 0.0,
    rows: int = 96,
    step: timedelta = timedelta(days=1),
    custom_signal: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if adapter == "backtrader_csv":
        header = ["date", "open", "high", "low", "close", "volume", "openinterest"]
        delimiter = ","
    elif adapter == "yahoo_csv":
        header = ["Date", "Open", "High", "Low", "Close", "Volume"]
        delimiter = ","
    elif adapter == "mt5_csv":
        header = ["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>"]
        delimiter = "\t"
    else:
        header = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]
        delimiter = ","
    if custom_signal:
        header.append("signal")
    output = [delimiter.join(header)]
    first = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(rows):
        close = 100.0 + math.sin(index / 4.0 + phase) * 8.0 + index * 0.04
        opening = close - math.sin(index / 3.0) * 0.5
        high = max(opening, close) + 1.0
        low = min(opening, close) - 1.0
        timestamp = first + step * index
        if adapter == "mt5_csv":
            record = [
                timestamp.strftime("%Y.%m.%d"),
                timestamp.strftime("%H:%M:%S"),
                f"{opening:.8f}",
                f"{high:.8f}",
                f"{low:.8f}",
                f"{close:.8f}",
                str(1000 + index),
            ]
        elif adapter == "yahoo_csv":
            record = [
                timestamp.strftime("%Y-%m-%d"),
                f"{opening:.8f}",
                f"{high:.8f}",
                f"{low:.8f}",
                f"{close:.8f}",
                str(1000 + index),
            ]
        elif adapter == "backtrader_csv":
            record = [
                timestamp.strftime("%Y-%m-%d"),
                f"{opening:.8f}",
                f"{high:.8f}",
                f"{low:.8f}",
                f"{close:.8f}",
                str(1000 + index),
                "0",
            ]
        else:
            record = [
                timestamp.strftime("%Y-%m-%dT%H:%M:%S%z"),
                f"{opening:.8f}",
                f"{high:.8f}",
                f"{low:.8f}",
                f"{close:.8f}",
                str(1000 + index),
                "0",
            ]
        if custom_signal:
            record.append("1" if math.sin(index / 5.0 + phase) >= 0 else "-1")
        output.append(delimiter.join(record))
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _feed_spec(
    profile_id: str,
    *,
    name: str,
    adapter: str,
    role: str = "execution",
    timeframe: str = "days",
    resample: dict[str, Any] | None = None,
    custom_lines: list[str] | None = None,
    source_type: str = "local_file",
) -> dict[str, Any]:
    suffix = ".tsv" if adapter == "mt5_csv" else ".csv"
    return {
        "name": name,
        "symbol": name.upper(),
        "role": role,
        "tradable": role == "execution",
        "source": {
            "root_id": "acceptance",
            "relative_path": f"{profile_id}/{name}{suffix}",
            "source_type": source_type,
        },
        "format": adapter,
        "columns": {},
        "custom_lines": custom_lines or [],
        "timeframe": timeframe,
        "compression": 1,
        "timezone": "UTC",
        "resample": resample,
        "transforms": [],
    }


def _acceptance_profile_specs(data_root: Path) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {
        "single_data_indicator": {
            "profile_id": "single-generic-daily",
            "feeds": [
                _feed_spec(
                    "single-generic-daily",
                    name="execution",
                    adapter="generic_csv",
                )
            ],
        },
        "multi_indicator_system": {
            "profile_id": "multi-indicator-backtrader-daily",
            "feeds": [
                _feed_spec(
                    "multi-indicator-backtrader-daily",
                    name="execution",
                    adapter="backtrader_csv",
                )
            ],
        },
        "multi_asset_allocation": {
            "profile_id": "multi-asset-yahoo-daily",
            "feeds": [
                _feed_spec(
                    "multi-asset-yahoo-daily",
                    name="execution",
                    adapter="yahoo_csv",
                ),
                _feed_spec(
                    "multi-asset-yahoo-daily",
                    name="signal",
                    adapter="yahoo_csv",
                    role="signal",
                ),
            ],
        },
        "multi_timeframe": {
            "profile_id": "multi-timeframe-mt5-resample",
            "feeds": [
                _feed_spec(
                    "multi-timeframe-mt5-resample",
                    name="execution",
                    adapter="mt5_csv",
                    timeframe="minutes",
                ),
                _feed_spec(
                    "multi-timeframe-mt5-resample",
                    name="higher_timeframe",
                    adapter="mt5_csv",
                    role="signal",
                    timeframe="minutes",
                    resample={"timeframe": "minutes", "compression": 5},
                ),
            ],
        },
        "pairs_spread": {
            "profile_id": "pairs-materialized-pandas",
            "feeds": [
                _feed_spec(
                    "pairs-materialized-pandas",
                    name="leg_a",
                    adapter="pandas",
                    source_type="materialized_dataframe",
                ),
                _feed_spec(
                    "pairs-materialized-pandas",
                    name="leg_b",
                    adapter="pandas",
                    role="hedge",
                    source_type="materialized_dataframe",
                ),
            ],
        },
        "order_risk": {
            "profile_id": "order-risk-generic-daily",
            "feeds": [
                _feed_spec(
                    "order-risk-generic-daily",
                    name="execution",
                    adapter="generic_csv",
                )
            ],
        },
        "precomputed_ml": {
            "profile_id": "precomputed-materialized-custom-signal",
            "feeds": [
                _feed_spec(
                    "precomputed-materialized-custom-signal",
                    name="execution",
                    adapter="pandas_custom_lines",
                    custom_lines=["signal"],
                    source_type="materialized_dataframe",
                )
            ],
        },
    }
    for archetype, definition in definitions.items():
        for index, feed in enumerate(definition["feeds"]):
            source_path = data_root / feed["source"]["relative_path"]
            _write_fixture(
                source_path,
                adapter=feed["format"],
                phase=index * 0.7 + len(archetype) / 20.0,
                rows=180 if archetype == "multi_timeframe" else 96,
                step=timedelta(minutes=1) if archetype == "multi_timeframe" else timedelta(days=1),
                custom_signal=bool(feed["custom_lines"]),
            )
    return definitions


def _profile_evidence(profile_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "dataset_id": manifest["dataset_id"],
        "manifest_hash": manifest["manifest_hash"],
        "feed_count": len(manifest["feeds"]),
        "feeds": [
            {
                "name": feed["name"],
                "role": feed["role"],
                "adapter": feed["adapter"],
                "timeframe": feed["timeframe"],
                "compression": feed["compression"],
                "resample": feed.get("resample"),
                "replay": feed.get("replay"),
                "custom_lines": feed.get("custom_lines", []),
                "rows": feed["summary"]["rows"],
                "modal_interval_seconds": feed["summary"]["modal_interval_seconds"],
                "source_sha256": feed["source"]["sha256"],
                "normalized_sha256": feed["object"]["sha256"],
            }
            for feed in manifest["feeds"]
        ],
    }


def _register_acceptance_profiles(
    registry: DataRegistry, data_root: Path
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for archetype, definition in _acceptance_profile_specs(data_root).items():
        feeds = definition["feeds"]
        manifest = registry.register(
            {
                "schema_version": "data-spec-v1",
                "feeds": feeds,
                "master_feed": feeds[0]["name"],
                "alignment": "intersection",
                "minimum_overlap": 0.9,
                "license": "generated-test-fixture",
                "sensitivity": "public",
            }
        )
        profiles[archetype] = {
            "manifest": manifest,
            "evidence": _profile_evidence(definition["profile_id"], manifest),
        }
    return profiles


def _data_profile_gate(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    adapters = {
        feed["adapter"] for profile in profiles.values() for feed in profile["manifest"]["feeds"]
    }
    dataset_ids = {profile["manifest"]["dataset_id"] for profile in profiles.values()}
    multi_asset_feeds = len(profiles["multi_asset_allocation"]["manifest"]["feeds"])
    pairs_feeds = len(profiles["pairs_spread"]["manifest"]["feeds"])
    timeframe_feeds = profiles["multi_timeframe"]["manifest"]["feeds"]
    ml_feeds = profiles["precomputed_ml"]["manifest"]["feeds"]
    checks = {
        "seven_distinct_dataset_manifests": len(dataset_ids) == len(ARCHETYPES),
        "all_six_declared_adapters": adapters == ADAPTERS,
        "multi_asset_has_distinct_feeds": multi_asset_feeds >= 2,
        "pairs_has_distinct_feeds": pairs_feeds >= 2,
        "multi_timeframe_has_controlled_resample": any(
            feed.get("resample") == {"timeframe": "minutes", "compression": 5}
            for feed in timeframe_feeds
        ),
        "precomputed_ml_has_signal_line": any(
            "signal" in feed.get("custom_lines", []) for feed in ml_feeds
        ),
    }
    return {
        "schema_version": "acceptance-data-profile-gate-v1",
        "declared_adapters": sorted(ADAPTERS),
        "observed_adapters": sorted(adapters),
        "dataset_ids": sorted(dataset_ids),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _write_structured_failure(path: Path, archetype: str) -> dict[str, Any]:
    class_name = "".join(part.title() for part in archetype.split("_")) + "Broken"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import backtrader as bt\n\n\n"
        f"class {class_name}(bt.Strategy):\n"
        "    backtrader_skills_generated = True\n\n"
        "    def next(self):\n"
        "        if self.data.close[1] > 0:\n"
        "            self.buy()\n",
        encoding="utf-8",
    )
    report = validate_python(path)
    diagnostic_codes = sorted(item["code"] for item in report["diagnostics"])
    if report["status"] != "failed" or "BT_LOOKAHEAD_POSITIVE_INDEX" not in diagnostic_codes:
        raise AssertionError("acceptance failure fixture did not produce the required diagnostic")
    return report


def _mode_evidence(result: dict[str, Any]) -> dict[str, Any]:
    return {
        mode: {
            "bar_num": record["metrics"]["bar_num"],
            "event_count": len(record["events"]),
            "metrics_hash": canonical_hash(record["metrics"]),
            "events_hash": canonical_hash(record["events"]),
            "backtrader_version": record["backtrader"]["version"],
        }
        for mode, record in result["modes"].items()
    }


def run_acceptance(
    repository: Path,
    *,
    matrix: str = "all",
    require_no_mcp: bool = False,
    require_no_agent: bool = False,
) -> dict[str, Any]:
    if matrix != "all":
        raise ValueError("P0 acceptance currently exposes the complete 'all' matrix only")
    with tempfile.TemporaryDirectory(prefix="backtrader-skills-acceptance-") as temp:
        workspace = Path(temp)
        target = workspace / "target"
        target.mkdir()
        (target / "backtrader").symlink_to(
            repository.resolve() / "backtrader", target_is_directory=True
        )
        data_root = workspace / "data"
        data_root.mkdir()
        paths = RuntimePaths(target)
        registry = DataRegistry(paths)
        registry.add_root(data_root, root_id="acceptance")
        profiles = _register_acceptance_profiles(registry, data_root)
        data_gate = _data_profile_gate(profiles)
        drafts = DraftManager(paths)
        runner = ControlledRunner(paths)
        cells: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        for archetype in ARCHETYPES:
            dataset_profile = profiles[archetype]
            dataset = dataset_profile["manifest"]
            ir_hashes = {}
            for output_profile in OUTPUT_PROFILES:
                spec = default_strategy_spec(
                    archetype,
                    output_profile,
                    dataset["dataset_id"],
                    feed_count=len(dataset["feeds"]),
                    custom_lines=sorted(
                        {line for feed in dataset["feeds"] for line in feed.get("custom_lines", [])}
                    ),
                )
                ir_hashes[output_profile] = spec["ir"]
                repair_record = None
                if REPAIR_PROFILES.get(archetype) == output_profile:
                    failure = _write_structured_failure(
                        workspace / "repair-inputs" / f"{archetype}.py",
                        archetype,
                    )
                    repair = preview_spec_repair(paths, spec, failure)
                    draft = repair["new_draft"]
                    repair_record = {
                        "archetype": archetype,
                        "output_profile": output_profile,
                        "failure_status": failure["status"],
                        "failure_validation_hash": failure["validation_hash"],
                        "diagnostic_codes": sorted(item["code"] for item in failure["diagnostics"]),
                        "repair_method": repair["method"],
                        "source_validation_hash": repair["source_validation_hash"],
                        "new_draft_id": draft["draft_id"],
                    }
                else:
                    draft = drafts.preview(spec)
                validation = drafts.validate(draft["draft_id"])
                write_token = validation["approval_token"]
                drafts.tokens.approve(write_token["token_id"])
                applied = drafts.apply(draft["draft_id"], write_token["token_id"])
                candidate = next(
                    target / entry["path"]
                    for entry in applied["files"]
                    if entry["path"].endswith(".py")
                )
                prepared = runner.prepare(candidate, dataset["dataset_id"])
                run_token = prepared["approval_token"]
                runner.tokens.approve(run_token["token_id"])
                result = runner.execute(prepared["run_manifest"]["run_id"], run_token["token_id"])
                comparison = result["comparison"]
                cell = {
                    "archetype": archetype,
                    "output_profile": output_profile,
                    "data_profile": profiles[archetype]["evidence"],
                    "status": result["status"],
                    "run_id": result["run_id"],
                    "modes": _mode_evidence(result),
                    "comparison": {
                        "metrics_passed": comparison["metrics"]["passed"],
                        "metrics_comparison_hash": comparison["metrics"]["comparison_hash"],
                        "metric_differences": comparison["metrics"]["differences"],
                        "events_passed": comparison["events"]["passed"],
                        "events_comparison_hash": comparison["events"]["comparison_hash"],
                        "event_differences": comparison["events"]["differences"],
                    },
                    "repair_gate": repair_record is not None,
                }
                cells.append(cell)
                if repair_record is not None:
                    repair_record.update(
                        {
                            "revalidation_status": validation["validation_report"]["status"],
                            "run_id": result["run_id"],
                            "run_status": result["status"],
                            "metrics_comparison_passed": comparison["metrics"]["passed"],
                            "events_comparison_passed": comparison["events"]["passed"],
                        }
                    )
                    repair_record["passed"] = (
                        repair_record["failure_status"] == "failed"
                        and repair_record["revalidation_status"] == "passed"
                        and repair_record["run_status"] == "passed"
                        and repair_record["metrics_comparison_passed"]
                        and repair_record["events_comparison_passed"]
                    )
                    repairs.append(repair_record)
            if ir_hashes["single_test"] != ir_hashes["python_bundle"]:
                raise AssertionError(f"profile IR drift: {archetype}")
        expected_repairs = {(archetype, profile) for archetype, profile in REPAIR_PROFILES.items()}
        observed_repairs = {(item["archetype"], item["output_profile"]) for item in repairs}
        repair_gate = {
            "schema_version": "acceptance-repair-gate-v1",
            "required_scenarios": [
                {"archetype": archetype, "output_profile": profile}
                for archetype, profile in sorted(expected_repairs)
            ],
            "scenarios": repairs,
            "passed": observed_repairs == expected_repairs
            and all(item["passed"] for item in repairs),
        }
        doctor = run_doctor(repository)
        sibling_checks = {
            "mcp_absent": not (repository / "backtrader-mcp").exists()
            and not (repository / "backtrader_mcp").exists(),
            "agent_absent": not (repository / "backtrader-agent").exists()
            and not (repository / "backtrader_agent").exists(),
        }
        isolation_passed = (not require_no_mcp or sibling_checks["mcp_absent"]) and (
            not require_no_agent or sibling_checks["agent_absent"]
        )
        passed = (
            doctor["passed"]
            and isolation_passed
            and data_gate["passed"]
            and repair_gate["passed"]
            and all(
                cell["status"] == "passed"
                and cell["comparison"]["metrics_passed"]
                and cell["comparison"]["events_passed"]
                for cell in cells
            )
        )
        return {
            "schema_version": "acceptance-result-v1",
            "matrix": "7-archetypes-x-2-profiles",
            "dataset_ids": {
                archetype: profiles[archetype]["manifest"]["dataset_id"] for archetype in ARCHETYPES
            },
            "data_profile_gate": data_gate,
            "repair_gate": repair_gate,
            "doctor_passed": doctor["passed"],
            "require_no_mcp": require_no_mcp,
            "require_no_agent": require_no_agent,
            "sibling_checks": sibling_checks,
            "cells": cells,
            "passed": passed,
        }


def run_clean_wheel_acceptance(
    repository: Path,
    product_root: Path,
    *,
    matrix: str,
    require_no_mcp: bool,
    require_no_agent: bool,
) -> dict[str, Any]:
    """Build, install, and execute acceptance with no source checkout on sys.path."""

    with tempfile.TemporaryDirectory(prefix="backtrader-skills-wheel-acceptance-") as temp:
        clean_root = Path(temp)
        wheel_root = clean_root / "wheel"
        install_root = clean_root / "installed"
        clean_repository = clean_root / "repository"
        working = clean_root / "cwd"
        for directory in (wheel_root, install_root, clean_repository, working):
            directory.mkdir()
        (clean_repository / "backtrader").symlink_to(
            repository.resolve() / "backtrader", target_is_directory=True
        )
        build = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_root),
                str(product_root),
            ],
            cwd=working,
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode != 0:
            raise ExecutionError(
                "clean acceptance wheel build failed",
                details={"stderr": build.stderr[-4000:]},
            )
        wheel = next(wheel_root.glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            wheel_names = archive.namelist()
        forbidden_markers = {
            "backtrader-mcp",
            "backtrader_mcp",
            "backtrader-agent",
            "backtrader_agent",
        }
        if any(marker in name.lower() for name in wheel_names for marker in forbidden_markers):
            raise IntegrityError("wheel unexpectedly contains a sibling product")
        install = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(install_root),
                str(wheel),
            ],
            cwd=working,
            capture_output=True,
            text=True,
            check=False,
        )
        if install.returncode != 0:
            raise ExecutionError(
                "clean acceptance wheel install failed",
                details={"stderr": install.stderr[-4000:]},
            )
        installed_names = [
            path.relative_to(install_root).as_posix().lower() for path in install_root.rglob("*")
        ]
        if any(marker in name for name in installed_names for marker in forbidden_markers):
            raise IntegrityError("clean install unexpectedly contains a sibling product")
        inner_code = (
            "import json,sys;"
            "from pathlib import Path;"
            "sys.path.insert(0,sys.argv[1]);"
            "from backtrader_skills.acceptance import run_acceptance;"
            "result=run_acceptance(Path(sys.argv[2]),matrix=sys.argv[3],"
            "require_no_mcp=sys.argv[4]=='1',require_no_agent=sys.argv[5]=='1');"
            "print(json.dumps(result,allow_nan=False))"
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TMPDIR"}
        }
        environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                inner_code,
                str(install_root),
                str(clean_repository),
                matrix,
                "1" if require_no_mcp else "0",
                "1" if require_no_agent else "0",
            ],
            cwd=working,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ExecutionError(
                "clean installed acceptance failed",
                details={"stderr": completed.stderr[-4000:]},
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise ExecutionError("clean installed acceptance returned no JSON")
        result = json.loads(lines[-1])
        result["distribution"] = {
            "mode": "built-wheel-clean-install",
            "wheel_sha256": file_hash(wheel),
            "source_checkout_on_sys_path": False,
            "installed_origin_verified": True,
            "sibling_packages_absent": True,
        }
        result["passed"] = bool(result["passed"])
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--matrix", default="all")
    parser.add_argument("--require-no-mcp", action="store_true")
    parser.add_argument("--require-no-agent", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    product_root = Path(__file__).resolve().parents[2]
    result = run_clean_wheel_acceptance(
        args.repository,
        product_root,
        matrix=args.matrix,
        require_no_mcp=args.require_no_mcp,
        require_no_agent=args.require_no_agent,
    )
    if args.output is not None:
        atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
