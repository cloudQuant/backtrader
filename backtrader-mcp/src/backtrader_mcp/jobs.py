"""Durable product-owned asynchronous job API."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .data import DatasetService
from .drafts import DraftService
from .errors import Conflict, InvalidRequest, NotFound
from .locks import LockManager
from .security import TokenSigner
from .settings import Settings
from .state import StateStore
from .util import file_hash, sha256_json, utc_now

TERMINAL_STATES = {"CANCELLED", "SUCCEEDED", "FAILED", "TIMED_OUT", "ORPHANED"}
ACTIVE_STATES = {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}
RUN_PROFILES = {"runonce", "runnext", "runonce_runnext_compare", "fixed_tests"}


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid < 2:
        return False
    try:
        waited_pid, _ = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class JobService:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        locks: LockManager,
        drafts: DraftService,
        datasets: DatasetService,
        signer: TokenSigner,
    ):
        self.settings = settings
        self.state = state
        self.locks = locks
        self.drafts = drafts
        self.datasets = datasets
        self.signer = signer

    def prepare_strategy_run(
        self,
        draft_id: str,
        validation_token: str,
        dataset_id: str,
        runtime_id: str,
        timeout_seconds: int,
        run_profile_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(timeout_seconds, int)
            or timeout_seconds < 1
            or timeout_seconds > self.settings.max_run_seconds
        ):
            raise InvalidRequest(
                f"timeout_seconds must be between 1 and {self.settings.max_run_seconds}"
            )
        if run_profile_id not in RUN_PROFILES:
            raise InvalidRequest("run_profile_id is not a fixed P0 profile")
        request = {
            "draft_id": draft_id,
            "validation_token_hash": sha256_json(validation_token),
            "dataset_id": dataset_id,
            "runtime_id": runtime_id,
            "timeout_seconds": timeout_seconds,
            "run_profile_id": run_profile_id,
        }
        prior = self.state.idempotent_get("prepare_strategy_run", idempotency_key, request)
        if prior is not None:
            return prior
        verified = self.drafts.verify_validation(draft_id, validation_token)
        dataset = self.datasets.get_dataset(dataset_id)
        if verified["draft"]["strategy_spec"]["dataset_id"] != dataset_id:
            raise Conflict("run dataset does not match the canonical StrategySpec dataset_id")
        runtime = self.settings.runtimes.get(runtime_id)
        if runtime is None:
            raise NotFound(f"Backtrader runtime not registered: {runtime_id}")
        runtime = runtime.resolve(strict=True)
        if not (runtime / "backtrader" / "__init__.py").is_file():
            raise InvalidRequest("registered runtime does not contain a Backtrader source package")
        run_plan_id = f"runplan_{uuid.uuid4().hex}"
        plan_binding = {
            "run_plan_id": run_plan_id,
            "draft_id": draft_id,
            "draft_revision": verified["draft"]["revision"],
            "draft_manifest_hash": verified["draft"]["manifest_hash"],
            "artifact_hash": verified["draft"]["artifact_manifest"]["artifact_hash"],
            "validation_id": verified["validation"]["validation_id"],
            "validation_hash": verified["validation"]["validation_hash"],
            "dataset_id": dataset_id,
            "dataset_semantic_hash": dataset["semantic_hash"],
            "dataset_content_hashes": {
                name: item["sha256"]
                for name, item in sorted(dataset["extensions"]["feed_objects"].items())
            },
            "runtime_id": runtime_id,
            "runtime_version_file_hash": file_hash(runtime / "backtrader" / "version.py"),
            "timeout_seconds": timeout_seconds,
            "run_profile_id": run_profile_id,
            "run_modes": verified["draft"]["strategy_spec"]["run_modes"],
            "output_profile": verified["draft"]["profile"],
        }
        run_plan_hash = sha256_json(plan_binding)
        run_token = self.signer.issue(
            "run_plan",
            {"run_plan_id": run_plan_id, "run_plan_hash": run_plan_hash},
            ttl_seconds=1800,
        )
        plan = {
            **plan_binding,
            "run_plan_hash": run_plan_hash,
            "status": "prepared",
            "created_at": utc_now(),
        }
        self.state.put("run_plan", run_plan_id, plan)
        response = {
            "run_plan_id": run_plan_id,
            "run_token": run_token,
            "run_plan_hash": run_plan_hash,
            "frozen_inputs": plan_binding,
            "approval_command": f"backtrader-mcp approve --run-plan {run_plan_id} "
            f"--run-token '{run_token}'",
        }
        self.state.idempotent_put("prepare_strategy_run", idempotency_key, request, response)
        self.state.audit("run_plan.prepared", run_plan_id, {"run_plan_hash": run_plan_hash})
        return response

    def approve_run_plan(self, run_plan_id: str, run_token: str) -> dict[str, Any]:
        claims = self.signer.verify(run_token, "run_plan")
        plan = self.state.get("run_plan", run_plan_id)
        if (
            claims.get("run_plan_id") != run_plan_id
            or claims.get("run_plan_hash") != plan["run_plan_hash"]
            or plan["status"] != "prepared"
        ):
            raise Conflict("run token does not bind the prepared run plan")
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        return self.state.create_approval(
            "run",
            run_plan_id,
            plan["run_plan_hash"],
            expires.isoformat(),
        )

    def start_strategy_run(
        self,
        run_plan_id: str,
        run_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "run_plan_id": run_plan_id,
            "run_token_hash": sha256_json(run_token),
            "approval_id": approval_id,
        }
        prior = self.state.idempotent_get("start_strategy_run", idempotency_key, request)
        if prior is not None:
            return prior
        claims = self.signer.verify(run_token, "run_plan")
        with self.locks.acquire(f"run-plan:{run_plan_id}"):
            plan = self.state.get("run_plan", run_plan_id)
            if (
                claims.get("run_plan_id") != run_plan_id
                or claims.get("run_plan_hash") != plan["run_plan_hash"]
                or plan["status"] != "prepared"
            ):
                raise Conflict("run token is stale or does not bind this run plan")
            draft = self.drafts.get_draft(plan["draft_id"])
            dataset = self.datasets.get_dataset(plan["dataset_id"])
            runtime = self.settings.runtimes.get(plan["runtime_id"])
            if runtime is None:
                raise NotFound(f"Backtrader runtime not registered: {plan['runtime_id']}")
            runtime = runtime.resolve(strict=True)
            current = {
                "draft_revision": draft["revision"],
                "draft_manifest_hash": draft["manifest_hash"],
                "artifact_hash": draft["artifact_manifest"]["artifact_hash"],
                "dataset_semantic_hash": dataset["semantic_hash"],
                "dataset_content_hashes": {
                    name: item["sha256"]
                    for name, item in sorted(dataset["extensions"]["feed_objects"].items())
                },
                "runtime_version_file_hash": file_hash(runtime / "backtrader" / "version.py"),
            }
            if any(plan[key] != value for key, value in current.items()):
                raise Conflict("run inputs changed after prepare")
            self.state.consume_approval(approval_id, "run", run_plan_id, plan["run_plan_hash"])
            job_id = f"job_{uuid.uuid4().hex}"
            job_root = self.settings.state_root / "jobs" / job_id
            job_root.mkdir(mode=0o700)
            entrypoint = "test_strategy.py" if plan["output_profile"] == "single_test" else "run.py"
            run_manifest_core = {
                "schema_version": "run-manifest-v1",
                "run_id": job_id,
                "artifact_hash": plan["artifact_hash"],
                "dataset_id": plan["dataset_id"],
                "engine": {
                    "id": plan["runtime_id"],
                    "version_file_hash": plan["runtime_version_file_hash"],
                },
                "environment_hash": sha256_json(
                    {
                        "python": sys.version,
                        "runtime_id": plan["runtime_id"],
                        "runtime_version_file_hash": plan["runtime_version_file_hash"],
                    }
                ),
                "run_profile": {
                    "timeout_seconds": plan["timeout_seconds"],
                    "run_modes": plan["run_modes"],
                    "profile_id": plan["run_profile_id"],
                },
                "approval_id": approval_id,
            }
            run_manifest = {
                **run_manifest_core,
                "manifest_hash": sha256_json(run_manifest_core),
            }
            job = {
                "job_id": job_id,
                "state": "QUEUED",
                "run_plan_id": run_plan_id,
                "draft_id": plan["draft_id"],
                "draft_revision": plan["draft_revision"],
                "draft_manifest_hash": plan["draft_manifest_hash"],
                "validation_id": plan["validation_id"],
                "dataset_id": plan["dataset_id"],
                "dataset_semantic_hash": plan["dataset_semantic_hash"],
                "dataset_content_hashes": plan["dataset_content_hashes"],
                "runtime_id": plan["runtime_id"],
                "runtime_root": str(runtime),
                "entrypoint": entrypoint,
                "timeout_seconds": plan["timeout_seconds"],
                "run_profile_id": plan["run_profile_id"],
                "worker_pid": None,
                "child_pid": None,
                "created_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "heartbeat_at": None,
                "error": None,
                "result": None,
                "run_manifest": run_manifest,
            }
            self.state.put("job", job_id, job)
            self.state.update(
                "run_plan",
                run_plan_id,
                lambda current_plan: {
                    **current_plan,
                    "status": "started",
                    "job_id": job_id,
                    "approval_id": approval_id,
                },
            )
        package_src = str(Path(__file__).resolve().parents[1])
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONPATH": os.pathsep.join([package_src, str(runtime)]),
        }
        supervisor_stdout = (job_root / "supervisor.stdout.log").open("ab")
        supervisor_stderr = (job_root / "supervisor.stderr.log").open("ab")
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "backtrader_mcp.worker",
                    "--state-root",
                    str(self.settings.state_root),
                    "--job-id",
                    job_id,
                ],
                cwd=job_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=supervisor_stdout,
                stderr=supervisor_stderr,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            error_message = f"worker launch failed: {exc}"
            self.state.update(
                "job",
                job_id,
                lambda current: {
                    **current,
                    "state": "FAILED",
                    "finished_at": utc_now(),
                    "error": error_message,
                },
            )
            raise InvalidRequest("could not launch the controlled worker") from exc
        finally:
            supervisor_stdout.close()
            supervisor_stderr.close()
        self.state.update("job", job_id, lambda current: {**current, "worker_pid": process.pid})
        response = {
            "job_id": job_id,
            "run_id": job_id,
            "state": "QUEUED",
            "status_uri": f"backtrader-mcp://jobs/{job_id}",
            "result_uri": f"backtrader-mcp://jobs/{job_id}/result",
        }
        self.state.idempotent_put("start_strategy_run", idempotency_key, request, response)
        self.state.audit("job.started", job_id, response)
        return response

    def get_run_status(self, job_id: str) -> dict[str, Any]:
        with self.locks.acquire(f"job:{job_id}"):
            job = self.state.get("job", job_id)
            if job["state"] in ACTIVE_STATES and not _pid_alive(job.get("worker_pid")):
                job = self.state.update(
                    "job",
                    job_id,
                    lambda current: {
                        **current,
                        "state": "ORPHANED",
                        "finished_at": utc_now(),
                        "error": "worker process disappeared before a terminal state was persisted",
                    },
                )
            return {key: value for key, value in job.items() if key not in {"runtime_root"}}

    def cancel_strategy_run(self, job_id: str, idempotency_key: str) -> dict[str, Any]:
        request = {"job_id": job_id}
        prior = self.state.idempotent_get("cancel_strategy_run", idempotency_key, request)
        if prior is not None:
            return prior
        with self.locks.acquire(f"job:{job_id}"):
            job = self.state.get("job", job_id)
            if job["state"] in TERMINAL_STATES:
                response = {"job_id": job_id, "state": job["state"], "already_terminal": True}
            else:
                self.state.update(
                    "job",
                    job_id,
                    lambda current: {**current, "state": "CANCEL_REQUESTED"},
                )
                child_pid = job.get("child_pid")
                worker_pid = job.get("worker_pid")
                for pid in (child_pid, worker_pid):
                    if _pid_alive(pid):
                        try:
                            os.killpg(pid, signal.SIGTERM)
                        except (OSError, ProcessLookupError):
                            pass
                self.state.update(
                    "job",
                    job_id,
                    lambda current: {
                        **current,
                        "state": "CANCELLED",
                        "finished_at": utc_now(),
                        "error": "cancelled by local client request",
                    },
                )
                response = {"job_id": job_id, "state": "CANCELLED", "already_terminal": False}
            self.state.idempotent_put("cancel_strategy_run", idempotency_key, request, response)
            self.state.audit("job.cancelled", job_id, response)
            return response

    def get_run_result(self, job_id: str) -> dict[str, Any]:
        job = self.get_run_status(job_id)
        if job["state"] != "SUCCEEDED" or not isinstance(job.get("result"), dict):
            raise Conflict(f"job has no successful result: {job['state']}")
        return job["result"]

    def recover_jobs(self) -> list[str]:
        recovered: list[str] = []
        for job in self.state.list("job"):
            if job["state"] in ACTIVE_STATES and not _pid_alive(job.get("worker_pid")):
                self.state.update(
                    "job",
                    job["job_id"],
                    lambda current: {
                        **current,
                        "state": "ORPHANED",
                        "finished_at": utc_now(),
                        "error": "worker was absent during startup recovery",
                    },
                )
                recovered.append(job["job_id"])
        return recovered
