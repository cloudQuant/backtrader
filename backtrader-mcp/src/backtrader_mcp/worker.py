"""Controlled worker process; the MCP server never imports candidate modules."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .errors import InvalidRequest
from .reports import compare_metrics, normalize_metrics, render_markdown
from .state import StateStore
from .util import atomic_write, file_hash, sha256_json, utc_now


def _update(store: StateStore, job_id: str, **values: Any) -> dict[str, Any]:
    return store.update("job", job_id, lambda current: {**current, **values})


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def _validate_result(value: Any, expected_feed_configs: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != "run-result-v1":
        raise ValueError("candidate result does not implement run-result-v1")
    mode = value.get("run_mode")
    if mode not in {"runonce", "runnext"}:
        raise ValueError("candidate result run_mode is invalid")
    try:
        metrics = normalize_metrics(value.get("metrics"))
    except InvalidRequest as exc:
        raise ValueError(str(exc)) from exc
    evidence = value.get("feed_runtime")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("candidate result has no typed feed runtime evidence")
    expected = {item["name"]: item for item in expected_feed_configs}
    sanitized: list[dict[str, Any]] = []
    strategy_names: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("typed feed runtime evidence must contain objects")
        dataset_feed = item.get("dataset_feed")
        strategy_feed = item.get("strategy_feed")
        config = expected.get(dataset_feed)
        if config is None or not isinstance(strategy_feed, str) or not strategy_feed:
            raise ValueError("typed feed runtime evidence names an unknown feed")
        if strategy_feed in strategy_names:
            raise ValueError("typed feed runtime evidence repeats a strategy feed")
        strategy_names.add(strategy_feed)
        if (
            item.get("input_format") != config["input_format"]
            or item.get("adapter") != config["adapter"]
            or item.get("bar_operation") != config["bar_operation"]
        ):
            raise ValueError("typed feed runtime evidence does not match the frozen DataSpec")
        source_rows = item.get("source_row_count")
        output_bars = item.get("output_bar_count")
        if (
            not isinstance(source_rows, int)
            or isinstance(source_rows, bool)
            or source_rows < 1
            or not isinstance(output_bars, int)
            or isinstance(output_bars, bool)
            or output_bars < 1
        ):
            raise ValueError("typed feed runtime evidence has invalid row counts")
        constructed = item.get("constructed_class")
        registered = item.get("registered_class")
        if not isinstance(constructed, str) or not constructed or not isinstance(registered, str):
            raise ValueError("typed feed runtime evidence has invalid adapter classes")
        sanitized.append(
            {
                "dataset_feed": dataset_feed,
                "strategy_feed": strategy_feed,
                "input_format": config["input_format"],
                "adapter": config["adapter"],
                "constructed_class": constructed,
                "registered_class": registered,
                "bar_operation": config["bar_operation"],
                "source_row_count": source_rows,
                "output_bar_count": output_bars,
            }
        )
    return {
        "schema_version": "run-result-v1",
        "run_mode": mode,
        "metrics": metrics,
        "feed_runtime": sanitized,
    }


def run_worker(state_root: Path, job_id: str) -> int:
    state = StateStore(state_root)
    job = state.get("job", job_id)
    job_root = state_root / "jobs" / job_id
    draft = state.get("draft", job["draft_id"])
    dataset = state.get("dataset", job["dataset_id"])
    draft_root = state_root / "drafts" / job["draft_id"]
    feed_objects = dataset["extensions"]["feed_objects"]
    dataset_paths: dict[str, str] = {}
    feed_configs: list[dict[str, Any]] = []
    for feed in dataset["feeds"]:
        name = feed["name"]
        item = feed_objects[name]
        dataset_path = state_root / item["cas_relative_path"]
        if (
            file_hash(dataset_path) != item["sha256"]
            or job["dataset_content_hashes"].get(name) != item["sha256"]
        ):
            _update(
                state,
                job_id,
                state="FAILED",
                finished_at=utc_now(),
                error=f"dataset CAS content failed its hash check: {name}",
            )
            return 2
        dataset_paths[name] = str(dataset_path)
        feed_configs.append(
            {
                "name": name,
                "canonical_csv_path": str(dataset_path),
                "content_sha256": item["sha256"],
                "input_format": item["input_format"],
                "adapter": item["adapter"],
                "source_timeframe": item["source_timeframe"],
                "source_compression": item["source_compression"],
                "custom_lines": item["custom_lines"],
                "bar_operation": item["bar_operation"],
            }
        )
    master_dataset_path = dataset_paths[dataset["master_feed"]]
    for relative, digest in draft["manifest"].items():
        if file_hash(draft_root / relative) != digest:
            _update(
                state,
                job_id,
                state="FAILED",
                finished_at=utc_now(),
                error="draft content failed its hash check",
            )
            return 2
    entrypoint = draft_root / job["entrypoint"]
    profile_modes = {
        "runonce": ["runonce"],
        "runnext": ["runnext"],
        "runonce_runnext_compare": ["runonce", "runnext"],
        "fixed_tests": ["runonce", "runnext"],
    }
    modes = profile_modes[job["run_profile_id"]]
    _update(
        state,
        job_id,
        state="RUNNING",
        started_at=utc_now(),
        heartbeat_at=utc_now(),
        worker_pid=os.getpid(),
    )
    deadline = time.monotonic() + job["timeout_seconds"]
    mode_results: dict[str, dict[str, Any]] = {}
    candidate_artifacts: list[dict[str, Any]] = []
    package_src = str(Path(__file__).resolve().parents[1])
    for mode in modes:
        result_path = job_root / f"result.{mode}.candidate.json"
        stdout_path = job_root / f"candidate.{mode}.stdout.log"
        stderr_path = job_root / f"candidate.{mode}.stderr.log"
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONPATH": os.pathsep.join([job["runtime_root"], package_src]),
            "BACKTRADER_MCP_DATASET": master_dataset_path,
            "BACKTRADER_MCP_DATASETS_JSON": json.dumps(
                dataset_paths, sort_keys=True, separators=(",", ":")
            ),
            "BACKTRADER_MCP_FEEDS_JSON": json.dumps(
                feed_configs, sort_keys=True, separators=(",", ":")
            ),
            "BACKTRADER_MCP_RESULT": str(result_path),
            "BACKTRADER_MCP_RUN_MODE": mode,
        }
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                [sys.executable, str(entrypoint)],
                cwd=draft_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            _update(
                state,
                job_id,
                child_pid=process.pid,
                heartbeat_at=utc_now(),
                active_mode=mode,
            )
            while process.poll() is None:
                current = state.get("job", job_id)
                if current["state"] == "CANCEL_REQUESTED":
                    _terminate(process)
                    _update(
                        state,
                        job_id,
                        state="CANCELLED",
                        finished_at=utc_now(),
                        heartbeat_at=utc_now(),
                        error="cancelled while running",
                    )
                    return 3
                if time.monotonic() >= deadline:
                    _terminate(process)
                    _update(
                        state,
                        job_id,
                        state="TIMED_OUT",
                        finished_at=utc_now(),
                        heartbeat_at=utc_now(),
                        error=f"run exceeded {job['timeout_seconds']} seconds",
                    )
                    return 4
                _update(state, job_id, heartbeat_at=utc_now())
                time.sleep(0.1)
        if process.returncode != 0:
            error = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            _update(
                state,
                job_id,
                state="FAILED",
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
                error=f"{mode} candidate exited {process.returncode}: {error}",
            )
            return process.returncode or 1
        try:
            if result_path.stat().st_size > 1024 * 1024:
                raise ValueError("candidate result exceeds 1 MiB")
            candidate = _validate_result(
                json.loads(result_path.read_text(encoding="utf-8")),
                feed_configs,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _update(
                state,
                job_id,
                state="FAILED",
                finished_at=utc_now(),
                heartbeat_at=utc_now(),
                error=f"{mode} result validation failed: {exc}",
            )
            return 5
        mode_results[mode] = candidate
        candidate_artifacts.extend(
            [
                {
                    "role": f"{mode}_candidate_result",
                    "path": result_path.name,
                    "bytes": result_path.stat().st_size,
                    "sha256": file_hash(result_path),
                },
                {
                    "role": f"{mode}_stderr",
                    "path": stderr_path.name,
                    "bytes": stderr_path.stat().st_size,
                    "sha256": file_hash(stderr_path),
                },
            ]
        )
    try:
        primary_mode = "runonce" if "runonce" in mode_results else modes[0]
        comparison = (
            compare_metrics(
                mode_results["runonce"]["metrics"],
                mode_results["runnext"]["metrics"],
            )
            if {"runonce", "runnext"} <= set(mode_results)
            else None
        )
        normalized_path = job_root / "result.json"
        normalized_core = {
            "schema_version": "run-result-v1",
            "run_id": job_id,
            "status": (
                "failed"
                if comparison is not None and comparison["status"] == "mismatched"
                else "passed"
            ),
            "metrics": mode_results[primary_mode]["metrics"],
            "diagnostics": comparison["diagnostics"] if comparison else [],
            "artifacts": candidate_artifacts,
            "extensions": {
                "draft_id": job["draft_id"],
                "draft_revision": job["draft_revision"],
                "artifact_hash": job["run_manifest"]["artifact_hash"],
                "dataset_id": job["dataset_id"],
                "dataset_semantic_hash": job["dataset_semantic_hash"],
                "dataset_content_hashes": job["dataset_content_hashes"],
                "runtime_id": job["runtime_id"],
                "run_manifest_hash": job["run_manifest"]["manifest_hash"],
                "run_profile_id": job["run_profile_id"],
                "mode_results": mode_results,
                "runonce_runnext_comparison": comparison,
            },
        }
        normalized = {
            **normalized_core,
            "result_hash": sha256_json(normalized_core),
        }
        report = render_markdown(normalized)
        report_path = job_root / "report.md"
        atomic_write(report_path, report.encode("utf-8"), mode=0o600)
        atomic_write(
            normalized_path,
            json.dumps(normalized, sort_keys=True, default=str).encode("utf-8"),
            mode=0o600,
        )
        result = {
            **normalized,
            "extensions": {
                **normalized["extensions"],
                "result_sha256": file_hash(normalized_path),
                "report_sha256": file_hash(report_path),
                "report_markdown": report,
            },
        }
    except (OSError, ValueError, json.JSONDecodeError, InvalidRequest) as exc:
        _update(
            state,
            job_id,
            state="FAILED",
            finished_at=utc_now(),
            heartbeat_at=utc_now(),
            error=f"result validation failed: {exc}",
        )
        return 5
    _update(
        state,
        job_id,
        state="SUCCEEDED",
        finished_at=utc_now(),
        heartbeat_at=utc_now(),
        result=result,
        error=None,
    )
    state.audit(
        "job.succeeded",
        job_id,
        {"result_hash": result["result_hash"]},
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--job-id", required=True)
    arguments = parser.parse_args(argv)
    return run_worker(Path(arguments.state_root), arguments.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
