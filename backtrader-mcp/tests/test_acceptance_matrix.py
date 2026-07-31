from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import backtrader_mcp
from backtrader_mcp.contracts import ARCHETYPES, SCAFFOLD_PROFILES
from backtrader_mcp.data import BASE_COLUMNS, INPUT_FORMAT_ADAPTERS
from backtrader_mcp.util import sha256_json

from conftest import canonical_spec

CELL_FORMATS = {
    "single_data_indicator": ("generic_csv", "backtrader_csv"),
    "multi_indicator_system": ("yahoo_csv", "mt5_csv"),
    "multi_asset_allocation": ("generic_csv", "pandas"),
    "multi_timeframe": ("generic_csv", "generic_csv"),
    "pairs_spread": ("backtrader_csv", "yahoo_csv"),
    "order_risk": ("pandas", "mt5_csv"),
    "precomputed_ml": ("pandas_custom_lines", "pandas_custom_lines"),
}


def _execution_environment() -> dict[str, Any]:
    source_src = (Path(__file__).resolve().parents[1] / "src").resolve()
    installed_origin = Path(backtrader_mcp.__file__).resolve()
    resolved_paths: list[str] = []
    for value in sys.path:
        try:
            resolved_paths.append(str(Path(value or ".").resolve()))
        except OSError:
            resolved_paths.append(value)
    expected_target = os.environ.get("BACKTRADER_MCP_EXPECTED_INSTALLED_TARGET")
    return {
        "installed_origin": str(installed_origin),
        "source_checkout_on_sys_path": str(source_src) in resolved_paths,
        "origin_is_expected_installed_target": (
            expected_target is not None
            and installed_origin.is_relative_to(Path(expected_target).resolve())
        ),
        "sibling_checks": {
            "skills_absent": importlib.util.find_spec("backtrader_skills") is None,
            "agent_absent": importlib.util.find_spec("backtrader_agent") is None,
        },
    }


def _wait(service: Any, job_id: str, timeout: float = 25.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.get_run_status(job_id)
        if status["state"] in {
            "CANCELLED",
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
            "ORPHANED",
        }:
            return status
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not become terminal")


def _write_source(
    source_root: Path,
    relative_path: str,
    input_format: str,
    *,
    price_shift: float = 0.0,
    intraday: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    path = source_root / relative_path
    start = datetime(2023, 1, 1, 9, 30)
    row_count = 360 if intraday else 180
    custom = input_format == "pandas_custom_lines"
    if input_format == "yahoo_csv":
        header = "Date,Open,High,Low,Close,Adj Close,Volume"
    elif input_format in {"backtrader_csv", "mt5_csv"}:
        header = "Date,Time,Open,High,Low,Close,Volume,OpenInterest"
    else:
        header = "datetime,open,high,low,close,volume,openinterest"
        if custom:
            header += ",signal"
    lines = [header]
    for index in range(row_count):
        moment = start + (timedelta(minutes=index) if intraday else timedelta(days=index))
        close = 100.0 + price_shift + index * 0.08 + ((index % 12) - 6) * 0.45
        values = {
            "open": f"{close - 0.2:.6f}",
            "high": f"{close + 1.0:.6f}",
            "low": f"{close - 1.0:.6f}",
            "close": f"{close:.6f}",
            "volume": str(1000 + index),
            "openinterest": "0",
        }
        if input_format == "yahoo_csv":
            lines.append(
                ",".join(
                    [
                        moment.date().isoformat(),
                        values["open"],
                        values["high"],
                        values["low"],
                        values["close"],
                        values["close"],
                        values["volume"],
                    ]
                )
            )
        elif input_format in {"backtrader_csv", "mt5_csv"}:
            date_text = (
                moment.strftime("%Y.%m.%d")
                if input_format == "mt5_csv"
                else moment.strftime("%Y-%m-%d")
            )
            lines.append(
                ",".join(
                    [
                        date_text,
                        moment.strftime("%H:%M:%S"),
                        values["open"],
                        values["high"],
                        values["low"],
                        values["close"],
                        values["volume"],
                        values["openinterest"],
                    ]
                )
            )
        else:
            row = [
                moment.isoformat(timespec="seconds"),
                values["open"],
                values["high"],
                values["low"],
                values["close"],
                values["volume"],
                values["openinterest"],
            ]
            if custom:
                row.append("1" if (index // 8) % 2 == 0 else "-1")
            lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if input_format == "yahoo_csv":
        columns = {
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    elif input_format in {"backtrader_csv", "mt5_csv"}:
        columns = {
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "openinterest": "OpenInterest",
        }
    else:
        columns = {column: column for column in BASE_COLUMNS}
        if custom:
            columns["signal"] = "signal"
    extensions: dict[str, Any] = {}
    if input_format in {"backtrader_csv", "mt5_csv"}:
        extensions["adapter_options"] = {"time_column": "Time"}
    return columns, extensions


def _register_cell_dataset(
    service: Any,
    source_root: Path,
    archetype: str,
    profile: str,
    input_format: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    multi_feed = archetype in {
        "multi_asset_allocation",
        "multi_timeframe",
        "pairs_spread",
    }
    intraday = input_format == "mt5_csv" or archetype == "multi_timeframe"
    feeds: list[dict[str, Any]] = []
    inspections: list[dict[str, Any]] = []
    for index in range(2 if multi_feed else 1):
        name = "primary" if index == 0 else "secondary"
        relative = f"{archetype}-{profile}-{name}.csv"
        columns, extensions = _write_source(
            source_root,
            relative,
            input_format,
            price_shift=index * 7.0,
            intraday=intraday,
        )
        inspections.append(service.inspect_dataset("market", relative))
        operation = {"mode": "direct"}
        if archetype == "multi_timeframe" and index == 1:
            operation = {
                "mode": "resample" if profile == "python_bundle" else "replay",
                "timeframe": "minutes",
                "compression": 5,
            }
        extensions["bar_operation"] = operation
        custom_lines = ["signal"] if input_format == "pandas_custom_lines" else []
        feeds.append(
            {
                "name": name,
                "role": "execution" if index == 0 else "signal",
                "symbol": name.upper(),
                "source": {
                    "root_id": "market",
                    "relative_path": relative,
                    "source_type": (
                        "materialized_dataframe"
                        if input_format in {"pandas", "pandas_custom_lines"}
                        else "local_file"
                    ),
                },
                "format": input_format,
                "timeframe": "minutes" if intraday else "days",
                "compression": 1,
                "timezone": "UTC",
                "columns": columns,
                "lines": [*BASE_COLUMNS, *custom_lines],
                "extensions": extensions,
            }
        )
    core = {
        "schema_version": "data-spec-v1",
        "feeds": feeds,
        "master_feed": "primary",
        "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
        "transforms": [],
    }
    return (
        service.register_local_dataset({**core, "spec_hash": sha256_json(core)}),
        inspections,
    )


def _run_cell(
    service: Any,
    source_root: Path,
    archetype: str,
    profile: str,
    input_format: str,
) -> dict[str, Any]:
    cell_id = f"{archetype}-{profile}"
    stages: dict[str, Any] = {}
    dataset, inspections = _register_cell_dataset(
        service, source_root, archetype, profile, input_format
    )
    stages["inspect"] = {
        "status": "passed",
        "sources": len(inspections),
        "source_hashes": [item["source_sha256"] for item in inspections],
    }
    stages["register"] = {
        "status": "passed",
        "dataset_id": dataset["dataset_id"],
        "feed_count": len(dataset["feeds"]),
    }
    preview = service.preview_dataset(dataset["dataset_id"], 3)
    stages["preview"] = {"status": "passed", "rows": len(preview["rows"])}
    spec = canonical_spec(dataset["dataset_id"], archetype, profile)
    if archetype == "precomputed_ml":
        spec["feeds"][0]["lines"] = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "signal",
        ]
    spec_validation = service.validate_strategy_spec(spec)
    assert spec_validation["status"] == "passed", spec_validation
    draft = service.create_strategy_draft(spec)
    stages["draft"] = {
        "status": "passed",
        "draft_id": draft["draft_id"],
        "profile": draft["profile"],
    }
    validation = service.validate_strategy_draft(draft["draft_id"], draft["revision"])
    assert validation["report"]["status"] == "passed", validation["report"]
    stages["validate"] = {
        "status": "passed",
        "validation_id": validation["validation_id"],
    }
    prepared_change = service.prepare_strategy_changes(
        draft["draft_id"],
        validation["validation_token"],
        "strategies",
        f"acceptance/{cell_id}",
        {},
        f"prepare-change-{cell_id}",
    )
    stages["prepare_changes"] = {
        "status": "passed",
        "change_set_id": prepared_change["change_set_id"],
    }
    change_approval = service.changes.approve_change(
        prepared_change["change_set_id"], prepared_change["change_token"]
    )
    applied = service.apply_strategy_changes(
        prepared_change["change_set_id"],
        prepared_change["change_token"],
        change_approval["approval_id"],
        f"apply-change-{cell_id}",
    )
    stages["apply_changes"] = {
        "status": "passed",
        "change_set_id": applied["change_set_id"],
    }
    plan = service.prepare_strategy_run(
        draft["draft_id"],
        validation["validation_token"],
        dataset["dataset_id"],
        "default",
        25,
        "fixed_tests",
        f"prepare-run-{cell_id}",
    )
    stages["prepare_run"] = {
        "status": "passed",
        "run_plan_id": plan["run_plan_id"],
    }
    run_approval = service.jobs.approve_run_plan(plan["run_plan_id"], plan["run_token"])
    started = service.start_strategy_run(
        plan["run_plan_id"],
        plan["run_token"],
        run_approval["approval_id"],
        f"start-run-{cell_id}",
    )
    status = _wait(service, started["job_id"])
    assert status["state"] == "SUCCEEDED", status.get("error")
    result = service.get_run_result(started["job_id"])
    parity = result["extensions"]["runonce_runnext_comparison"]
    assert parity["status"] == "matched", parity
    for mode in ("runonce", "runnext"):
        evidence = result["extensions"]["mode_results"][mode]["feed_runtime"]
        assert evidence
        assert all(item["adapter"] == INPUT_FORMAT_ADAPTERS[input_format] for item in evidence)
        if archetype == "multi_timeframe":
            expected_operation = "resample" if profile == "python_bundle" else "replay"
            assert evidence[1]["bar_operation"]["mode"] == expected_operation
            assert evidence[1]["output_bar_count"] < evidence[1]["source_row_count"]
        if archetype == "precomputed_ml":
            assert evidence[0]["constructed_class"] == "MaterializedPandasCustomLines"
    stages["run"] = {
        "status": "passed",
        "run_id": started["job_id"],
        "mode_results": {
            mode: {
                "metrics_hash": sha256_json(result["extensions"]["mode_results"][mode]["metrics"]),
                "feed_runtime": result["extensions"]["mode_results"][mode]["feed_runtime"],
            }
            for mode in ("runonce", "runnext")
        },
    }
    comparison = service.compare_strategy_runs(started["job_id"], started["job_id"])
    assert comparison["status"] == "matched"
    stages["compare"] = {"status": "passed", "comparison_status": comparison["status"]}
    return {
        "cell_id": cell_id,
        "archetype": archetype,
        "profile": profile,
        "dataset_profile": {
            "input_format": input_format,
            "adapter": INPUT_FORMAT_ADAPTERS[input_format],
        },
        "status": "passed",
        "stages": stages,
    }


def test_structured_fourteen_cell_acceptance_matrix(service_env):
    service, source_root, _ = service_env
    records: list[dict[str, Any]] = []
    for archetype in ARCHETYPES:
        for profile_index, profile in enumerate(SCAFFOLD_PROFILES):
            input_format = CELL_FORMATS[archetype][profile_index]
            try:
                records.append(_run_cell(service, source_root, archetype, profile, input_format))
            except Exception as exc:  # keep evidence for all remaining cells
                records.append(
                    {
                        "cell_id": f"{archetype}-{profile}",
                        "archetype": archetype,
                        "profile": profile,
                        "dataset_profile": {
                            "input_format": input_format,
                            "adapter": INPUT_FORMAT_ADAPTERS[input_format],
                        },
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "stages": {},
                    }
                )
    artifact = {
        "schema_version": "backtrader-mcp-matrix-v1",
        "expected_cells": len(ARCHETYPES) * len(SCAFFOLD_PROFILES),
        "executed_cells": len(records),
        "passed_cells": sum(record["status"] == "passed" for record in records),
        "execution_environment": _execution_environment(),
        "cells": records,
    }
    output_path = os.environ.get("BACKTRADER_MCP_ACCEPTANCE_OUTPUT")
    if output_path:
        Path(output_path).write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    assert artifact["executed_cells"] == 14
    assert artifact["passed_cells"] == 14, json.dumps(artifact, ensure_ascii=False, indent=2)
