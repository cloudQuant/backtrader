"""Isolated BM57 direct Store microbenchmark with a local fake provider only.

This script is a benchmark harness, not a runtime entry point.  It resolves a
synthetic schema-v4 ``simulation/replay`` registration and a non-authorizing
``TestExecutionProfile`` observation, then explicitly exercises the public
``BtApiStore`` synchronous methods against an in-process fake API.  The fake
has no network, credentials, SDK, or account side effects.  No runtime route or
production authorization is added by this file.

``--smoke`` checks the harness and source pair with tiny samples.  ``--full``
uses the frozen BM57 sample protocol (1000 warmups, five paired rounds, 10000
samples per operation) but still records ``NOT_ACCEPTED_FULL_MATRIX`` because
platform coverage and independent acceptance are outside this script.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


BASELINE_REVISION = "ad2c142b9a8b42cede85886528c681abdfcb8096"
BASELINE_TREE_SHA256 = "a40c1e275921be31e70dcc1285e2a50102e721c30caeb77dcf6b864bcc4397d1"
SCHEMA = "iteration41_bm57_direct_benchmark_result.v1"
ACCEPTANCE_STATUS = "NOT_ACCEPTED_FULL_MATRIX"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_PREFIXES = (
    "bt_api_py",
    "bt_api_execution",
    "bt_api_risk",
    "bt_api_monitor",
    "bt_api_gateway",
    "bt_api_transport",
    "bt_api_ctp",
)
_PROFILE_MARKER = "iteration41-bm57-fake-only-profile-v1"
PERFORMANCE_RATIO_LIMIT = 1.05


class BenchmarkContractError(RuntimeError):
    """The synthetic benchmark contract or observed product path is invalid."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tree_sha256(source_root: Path) -> Tuple[str, int]:
    """Hash the exact sorted Python source files under ``backtrader/``."""

    root = source_root.resolve(strict=True)
    package = root / "backtrader"
    if not package.is_dir() or not (package / "__init__.py").is_file():
        raise BenchmarkContractError("source_root_backtrader_package_missing")
    files = sorted(package.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix())
    if not files:
        raise BenchmarkContractError("source_tree_empty")
    digest = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise BenchmarkContractError("source_tree_symlink_rejected")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest(), len(files)


def runtime_contract_sha256(runtime_root: Path) -> str:
    """Hash the runtime config/profile sources shared by both benchmark sides."""

    root = runtime_root.resolve(strict=True)
    names = (
        "backtrader_runtime/config.py",
        "backtrader_runtime/registry.py",
        "backtrader_runtime/policy.py",
        "backtrader_runtime/test_execution_profile.py",
    )
    digest = hashlib.sha256()
    for name in names:
        path = root / Path(*name.split("/"))
        if not path.is_file() or path.is_symlink():
            raise BenchmarkContractError("runtime_contract_source_missing")
        data = path.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _revision_for(source_root: Path, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip()


def _safe_child_environment() -> Dict[str, str]:
    """Keep interpreter launch essentials while dropping ambient app settings."""

    allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    # Keep optional numerical libraries from creating a large ambient worker
    # pool before the measured Store path starts.
    environment.update(
        {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "POLARS_MAX_THREADS": "1",
            "RAYON_NUM_THREADS": "1",
        }
    )
    return environment


def _process_thread_count() -> Optional[int]:
    """Observe OS thread count where the platform exposes a stdlib route."""

    if os.name == "posix":
        task_directory = Path("/proc/self/task")
        if task_directory.is_dir():
            try:
                return sum(1 for entry in task_directory.iterdir() if entry.is_dir())
            except OSError:
                return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _THREADENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD),
                    ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG),
                    ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            snapshot = kernel32.CreateToolhelp32Snapshot
            snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            snapshot.restype = wintypes.HANDLE
            first = kernel32.Thread32First
            first.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
            first.restype = wintypes.BOOL
            next_entry = kernel32.Thread32Next
            next_entry.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
            next_entry.restype = wintypes.BOOL
            close = kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            handle = snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
            invalid = ctypes.c_void_p(-1).value
            if not handle or handle == invalid:
                return None
            count = 0
            entry = _THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            try:
                available = bool(first(handle, ctypes.byref(entry)))
                while available:
                    if entry.th32OwnerProcessID == os.getpid():
                        count += 1
                    entry.dwSize = ctypes.sizeof(entry)
                    available = bool(next_entry(handle, ctypes.byref(entry)))
            finally:
                close(handle)
            return count
        except Exception:
            return None
    return None


def _install_activity_guards() -> Dict[str, Any]:
    """Count and block socket/thread creation during the worker process."""

    import _thread
    import socket
    import threading

    socket_attempts: List[str] = []
    thread_attempts: List[str] = []

    def deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        socket_attempts.append("socket_api")
        raise BenchmarkContractError("socket_activity_forbidden")

    def deny_thread(*_args: Any, **_kwargs: Any) -> Any:
        thread_attempts.append("thread_api")
        raise BenchmarkContractError("thread_activity_forbidden")

    socket_type = socket.socket

    class _GuardedSocket(socket_type):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            socket_attempts.append("socket_constructor")
            raise BenchmarkContractError("socket_activity_forbidden")

    socket.socket = _GuardedSocket  # type: ignore[assignment]
    socket.create_connection = deny_socket  # type: ignore[assignment]
    socket.socketpair = deny_socket  # type: ignore[assignment]
    socket.fromfd = deny_socket  # type: ignore[assignment]
    threading.Thread.start = deny_thread  # type: ignore[assignment]
    threading._start_new_thread = deny_thread  # type: ignore[attr-defined,assignment]
    _thread.start_new_thread = deny_thread  # type: ignore[assignment]
    return {
        "socket_attempts": socket_attempts,
        "thread_attempts": thread_attempts,
        "threading": threading,
    }


def _fixture_registration(runtime_dir: Path, *, strategy_id: str) -> Any:
    from backtrader_runtime.registry import RegisteredRuntime

    return RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=strategy_id,
        allowed_presets=("replay",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("none",),
        available_capabilities=(),
    )


def _config_text() -> str:
    return (
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: benchmark.iteration41.bm57.direct.fake\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: replay\n"
        "parameters: {}\n"
        "secrets_ref: none\n"
    )


def _resolve_fixture_config(runtime_root: Path, runtime_dir: Path) -> Tuple[Any, int, int, List[int]]:
    """Load one synthetic v4 replay config and return the sealed effective view."""

    from backtrader_runtime.errors import RuntimeConfigError
    from backtrader_runtime.registry import RuntimeRegistry, resolve_runtime_config
    from backtrader_runtime import config as config_module

    del runtime_root  # The caller has already placed its reviewed source on sys.path.
    config_load_calls = [0]
    original_load_runtime_config = config_module.load_runtime_config

    def counted_load_runtime_config(*args: Any, **kwargs: Any) -> Any:
        config_load_calls[0] += 1
        return original_load_runtime_config(*args, **kwargs)

    config_module.load_runtime_config = counted_load_runtime_config
    strategy_id = "benchmark.iteration41.bm57.direct.fake"
    missing_dir = runtime_dir.with_name("missing-config")
    missing_dir.mkdir()
    missing_registry = RuntimeRegistry(
        (_fixture_registration(missing_dir, strategy_id=strategy_id),),
        registry_id="iteration41.bm57.missing-config.v1",
    )
    missing_started_ns = time.perf_counter_ns()
    try:
        config_module.load_runtime_config(missing_dir, registry=missing_registry)
    except (RuntimeConfigError, OSError):
        missing_rejection_ns = time.perf_counter_ns() - missing_started_ns
    else:
        raise BenchmarkContractError("missing_config_was_accepted")
    if "backtrader.stores.btapistore" in sys.modules:
        raise BenchmarkContractError("missing_config_imported_store_before_rejection")

    registration = _fixture_registration(runtime_dir, strategy_id=strategy_id)
    registry = RuntimeRegistry((registration,), registry_id="iteration41.bm57.fixture.v1")
    started_ns = time.perf_counter_ns()
    config = config_module.load_runtime_config(runtime_dir, registry=registry)
    effective = resolve_runtime_config(config, registry)
    elapsed_ns = time.perf_counter_ns() - started_ns
    if (
        effective.config.mode != "simulation"
        or effective.config.preset != "replay"
        or effective.order_route is not None
        or effective.account_access is not None
        or effective.required_capabilities
        or effective.allows_network
        or effective.allows_external_writes
        or effective.allows_production_writes
        or effective.requires_approval
    ):
        raise BenchmarkContractError("fixture_registry_not_all_disabled_replay")
    if config_load_calls[0] != 2:
        raise BenchmarkContractError("fixture_config_load_count_invalid")
    return effective, elapsed_ns, missing_rejection_ns, config_load_calls


class _FakeOfflineVerifier:
    def __init__(self, expected_payload: bytes) -> None:
        self._expected_payload = expected_payload

    def verify(self, _profile: Any, canonical_payload: bytes) -> bool:
        return hmac.compare_digest(self._expected_payload, canonical_payload)


def _validate_fake_profile(effective: Any, backtrader_tree_hash: str) -> Tuple[Any, int]:
    from backtrader_runtime.test_execution_profile import (
        TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
        TestExecutionPreflightContext,
        canonical_test_execution_profile,
        parse_test_execution_profile,
        validate_test_execution_profile,
    )

    now = time.time()
    def digest(value: str) -> str:
        return _sha256(value.encode("utf-8"))

    account_digest = digest(_PROFILE_MARKER + ":synthetic-account")
    approval_digest = digest(_PROFILE_MARKER + ":no-authority-marker")
    capability_digest = digest(_PROFILE_MARKER + ":fixture-only")
    profile_wire = {
        "account_fingerprint_sha256": account_digest,
        "allowed_instruments": ["FIXTURE"],
        "approval_receipt_digest": approval_digest,
        "artifact_sha256": backtrader_tree_hash,
        "capability_receipt_digest": capability_digest,
        "cleanup_required": True,
        "created_at": now - 1.0,
        "effective_config_digest": effective.effective_digest,
        "environment": "sandbox",
        "expires_at": now + 60.0,
        "max_external_writes": 0,
        "max_quantity": "1",
        "profile_id": "iteration41.bm57.fake-only",
        "provider": "fixture",
        "reconciliation_required": True,
        "schema_version": TEST_EXECUTION_PROFILE_SCHEMA_VERSION,
        "valid_from": now,
    }
    context = TestExecutionPreflightContext(
        provider="fixture",
        environment="sandbox",
        account_fingerprint_sha256=account_digest,
        approval_receipt_digest=approval_digest,
        effective_config_digest=effective.effective_digest,
        artifact_sha256=backtrader_tree_hash,
        capability_receipt_digest=capability_digest,
        instrument="FIXTURE",
        quantity="1",
        requested_external_writes=0,
        cleanup_ready=True,
        reconciliation_ready=True,
    )
    untrusted_profile = parse_test_execution_profile(profile_wire)
    expected_payload = canonical_test_execution_profile(untrusted_profile)
    verifier = _FakeOfflineVerifier(expected_payload)
    started_ns = time.perf_counter_ns()
    observation = validate_test_execution_profile(profile_wire, context=context, verifier=verifier)
    elapsed_ns = time.perf_counter_ns() - started_ns
    if (
        observation.profile_verifier_accepted is not True
        or observation.profile_binding_valid is not True
        or observation.preflight_authorized is not False
        or observation.execution_authorized is not False
        or observation.provider_preflight_started is not False
        or observation.provider_connected is not False
        or observation.external_writes_started is not False
    ):
        raise BenchmarkContractError("test_profile_observation_authority_flags_invalid")
    try:
        bool(observation)
    except TypeError:
        pass
    else:
        raise BenchmarkContractError("test_profile_observation_became_truthy")
    return observation, elapsed_ns


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    if not values or percentile < 1 or percentile > 100:
        raise ValueError("nearest-rank percentile requires samples and p in [1, 100]")
    ordered = sorted(values)
    index = (percentile * len(ordered) + 99) // 100 - 1
    return ordered[index]


def _distribution(values: Sequence[int]) -> Dict[str, int]:
    return {
        "count": len(values),
        "max_ns": max(values),
        "p50_ns": _nearest_rank(values, 50),
        "p95_ns": _nearest_rank(values, 95),
        "p99_ns": _nearest_rank(values, 99),
    }


def _evaluate_performance_gate(comparisons: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply the BM57 five-paired-round 5% ceiling to p50 and p99 ratios."""

    operations: Dict[str, Dict[str, Any]] = {}
    for operation in ("submit", "cancel"):
        if operation not in comparisons:
            raise BenchmarkContractError("performance_comparison_missing_operation")
        operation_result: Dict[str, Any] = {}
        for percentile in ("p50", "p99"):
            metric = comparisons[operation].get(percentile)
            if not isinstance(metric, Mapping):
                raise BenchmarkContractError("performance_comparison_missing_percentile")
            ratios = metric.get("per_round_candidate_over_baseline")
            median_ratio = metric.get("median_ratio")
            if (
                not isinstance(ratios, list)
                or len(ratios) != 5
                or any(type(ratio) not in (int, float) or ratio <= 0 for ratio in ratios)
                or type(median_ratio) not in (int, float)
                or median_ratio <= 0
            ):
                raise BenchmarkContractError("performance_comparison_invalid_ratio")
            operation_result[percentile] = {
                "median_candidate_over_baseline": median_ratio,
                "limit": PERFORMANCE_RATIO_LIMIT,
                "passed": median_ratio <= PERFORMANCE_RATIO_LIMIT,
            }
        operations[operation] = operation_result
    return {
        "method": "median of five paired candidate/baseline percentile ratios",
        "ratio_limit": PERFORMANCE_RATIO_LIMIT,
        "operations": operations,
        "passed": all(
            metric["passed"]
            for operation in operations.values()
            for metric in operation.values()
        ),
    }


def _make_order(order_base: Any, reference: int) -> Any:
    from types import SimpleNamespace

    class _Order:
        exectype = order_base.Limit
        size = 1
        price = 10.0
        pricelimit = None
        valid = None
        tradeid = 0

        def __init__(self) -> None:
            self.ref = reference
            self.data = SimpleNamespace(_name="FIXTURE")
            self.created = SimpleNamespace(price=10.0)
            self.info = _OrderInfo()

        def isbuy(self) -> bool:
            return True

        def issell(self) -> bool:
            return False

        def getordername(self) -> str:
            return "Limit"

    return _Order()


class _OrderInfo(dict):
    """Order info compatible with both legacy attribute and current mapping reads."""

    def __getattr__(self, name: str) -> Any:
        return self.get(name)


def _run_worker(
    *,
    source_root: Path,
    runtime_root: Path,
    side: str,
    revision: str,
    round_index: int,
    warmup: int,
    samples: int,
) -> Dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    runtime_root = runtime_root.resolve(strict=True)
    before_tree_hash, source_file_count = source_tree_sha256(source_root)
    runtime_hash = runtime_contract_sha256(runtime_root)
    script_hash = _sha256(Path(__file__).read_bytes())
    sys.path[:0] = [str(source_root), str(runtime_root)]
    activity = _install_activity_guards()
    thread_count_before = _process_thread_count()
    thread_ids_before = {thread.ident for thread in activity["threading"].enumerate()}
    initial_modules = set(sys.modules)
    valid_samples: Dict[str, List[int]] = {"submit": [], "cancel": []}
    with tempfile.TemporaryDirectory(prefix="iteration41-bm57-") as raw_temp:
        temp_root = Path(raw_temp)
        runtime_dir = temp_root / "runtime"
        runtime_dir.mkdir()
        (runtime_dir / "config.yaml").write_text(_config_text(), encoding="utf-8")
        effective, config_seal_ns, missing_config_rejection_ns, config_load_calls = (
            _resolve_fixture_config(runtime_root, runtime_dir)
        )
        observation, test_profile_ns = _validate_fake_profile(effective, before_tree_hash)

        if "talib" in sys.modules:
            raise BenchmarkContractError("ambient_talib_module_preloaded")
        # Backtrader imports its optional TA-Lib adapter at package import time.
        # Mark only that optional third-party module unavailable so the
        # hermetic Store benchmark cannot pull in ambient native/scientific
        # extensions. The product source and measured methods are unchanged.
        sys.modules["talib"] = None
        try:
            import backtrader
            from backtrader.order import OrderBase
            from backtrader_runtime import config as config_module
            from backtrader.stores.btapistore import BtApiStore
        finally:
            sys.modules.pop("talib", None)

        expected_package = (source_root / "backtrader").resolve(strict=True)
        expected_runtime = runtime_root.resolve(strict=True)
        actual_package = Path(backtrader.__file__).resolve(strict=True).parent
        actual_store = Path(sys.modules[BtApiStore.__module__].__file__).resolve(strict=True)
        actual_config = Path(config_module.__file__).resolve(strict=True)
        if (
            actual_package != expected_package
            or actual_store != (expected_package / "stores" / "btapistore.py")
            or actual_config != (expected_runtime / "backtrader_runtime" / "config.py")
        ):
            raise BenchmarkContractError("benchmark_import_origin_mismatch")

        class _FakeApi:
            def __init__(self) -> None:
                self.submissions: List[Tuple[int, str]] = []
                self.cancellations: List[Tuple[str, Optional[str]]] = []
                self.connected = False

            def connect(self) -> None:
                self.connected = True

            def disconnect(self) -> None:
                self.connected = False

            def get_balance(self) -> Mapping[str, float]:
                return {"cash": 100_000.0, "value": 100_000.0}

            def submit_order(self, payload: Mapping[str, Any]) -> Mapping[str, str]:
                if (
                    payload.get("symbol") != "FIXTURE"
                    or payload.get("side") != "buy"
                    or payload.get("size") != 1
                    or payload.get("order_type") != "limit"
                ):
                    raise BenchmarkContractError("fake_submit_payload_mismatch")
                reference = payload.get("bt_order_ref")
                external_id = "fake-order-{}".format(reference)
                self.submissions.append((reference, external_id))
                return {"status": "accepted", "id": external_id}

            def cancel_order(
                self, order_ref: str, *, dataname: Optional[str] = None
            ) -> Mapping[str, str]:
                if type(order_ref) is not str or not order_ref.startswith("fake-order-"):
                    raise BenchmarkContractError("fake_cancel_identity_mismatch")
                if dataname != "FIXTURE":
                    raise BenchmarkContractError("fake_cancel_scope_mismatch")
                self.cancellations.append((order_ref, dataname))
                return {"status": "accepted", "id": order_ref}

        api = _FakeApi()
        store = BtApiStore(provider="btapi", api=api, autostart=False)
        if side == "candidate":
            if not hasattr(store, "managed_execution_active") or store.managed_execution_active:
                raise BenchmarkContractError("candidate_managed_route_unexpectedly_attached")
        elif hasattr(store, "managed_execution_active") and store.managed_execution_active:
            raise BenchmarkContractError("baseline_managed_route_unexpectedly_attached")
        store_ready_started = time.perf_counter_ns()
        balance = store.get_balance(force=True)
        store_ready_ns = time.perf_counter_ns() - store_ready_started
        if balance.get("cash") != 100_000.0 or balance.get("value") != 100_000.0:
            raise BenchmarkContractError("fake_store_readiness_invalid")

        def exercise_one(reference: int, *, measured: bool) -> Tuple[int, int]:
            order = _make_order(OrderBase, reference)
            started = time.perf_counter_ns()
            submit_result = store.submit_order(order)
            submit_elapsed = time.perf_counter_ns() - started
            expected_id = "fake-order-{}".format(reference)
            if not isinstance(submit_result, Mapping) or submit_result.get("id") != expected_id:
                raise BenchmarkContractError("public_submit_result_invalid")
            order.info["external_order_id"] = expected_id
            started = time.perf_counter_ns()
            cancel_result = store.cancel_order(order)
            cancel_elapsed = time.perf_counter_ns() - started
            if not isinstance(cancel_result, Mapping) or cancel_result.get("id") != expected_id:
                raise BenchmarkContractError("public_cancel_result_invalid")
            if measured:
                valid_samples["submit"].append(submit_elapsed)
                valid_samples["cancel"].append(cancel_elapsed)
            return submit_elapsed, cancel_elapsed

        config_calls_before_hot_loop = config_load_calls[0]
        thread_count_before_hot_loop = _process_thread_count()
        thread_ids_before_hot_loop = {
            thread.ident for thread in activity["threading"].enumerate()
        }
        for index in range(warmup):
            exercise_one(-1_000_000 - index, measured=False)
        for index in range(samples):
            exercise_one(round_index * 1_000_000 + index + 1, measured=True)
        thread_count_after_hot_loop = _process_thread_count()
        thread_ids_after_hot_loop = {
            thread.ident for thread in activity["threading"].enumerate()
        }
        new_hot_loop_thread_ids = sorted(
            str(thread_id)
            for thread_id in thread_ids_after_hot_loop - thread_ids_before_hot_loop
            if thread_id is not None
        )
        if config_load_calls[0] != config_calls_before_hot_loop:
            raise BenchmarkContractError("config_loaded_during_direct_store_samples")
        expected_count = warmup + samples
        if len(api.submissions) != expected_count or len(api.cancellations) != expected_count:
            raise BenchmarkContractError("fake_provider_call_count_mismatch")
        if len({reference for reference, _ in api.submissions}) != expected_count:
            raise BenchmarkContractError("fake_submit_reference_duplicate")
        if len({order_ref for order_ref, _ in api.cancellations}) != expected_count:
            raise BenchmarkContractError("fake_cancel_reference_duplicate")
        if any(
            not observation_flag
            for observation_flag in (
                observation.preflight_authorized is False,
                observation.execution_authorized is False,
                observation.external_writes_started is False,
            )
        ):
            raise BenchmarkContractError("test_profile_observation_became_authority")
        store.stop()

    after_tree_hash, after_file_count = source_tree_sha256(source_root)
    plugin_modules = sorted(
        name
        for name in set(sys.modules) - initial_modules
        if name == _PLUGIN_PREFIXES[0]
        or name.startswith(tuple(prefix + "." for prefix in _PLUGIN_PREFIXES))
        or name in _PLUGIN_PREFIXES[1:]
    )
    thread_count_after = _process_thread_count()
    thread_ids_after = {thread.ident for thread in activity["threading"].enumerate()}
    new_thread_ids = sorted(
        str(thread_id) for thread_id in thread_ids_after - thread_ids_before if thread_id is not None
    )
    worker_checks = {
        "source_tree_stable": after_tree_hash == before_tree_hash and after_file_count == source_file_count,
        "plugin_modules_empty": not plugin_modules,
        "socket_attempts_empty": not activity["socket_attempts"],
        "thread_attempts_empty": not activity["thread_attempts"],
        "new_python_thread_ids_empty": not new_thread_ids,
        "hot_loop_new_python_thread_ids_empty": not new_hot_loop_thread_ids,
        "thread_count_before": thread_count_before,
        "thread_count_after": thread_count_after,
        "thread_count_before_hot_loop": thread_count_before_hot_loop,
        "thread_count_after_hot_loop": thread_count_after_hot_loop,
        "thread_count_stable": (
            thread_count_before_hot_loop is None
            or thread_count_after_hot_loop is None
            or thread_count_after_hot_loop == thread_count_before_hot_loop
        ),
        "socket_attempts": list(activity["socket_attempts"]),
        "thread_attempts": list(activity["thread_attempts"]),
        "new_python_thread_ids": new_thread_ids,
        "new_python_thread_ids_hot_loop": new_hot_loop_thread_ids,
        "new_plugin_modules": plugin_modules,
    }
    if (
        after_tree_hash != before_tree_hash
        or after_file_count != source_file_count
        or plugin_modules
        or activity["socket_attempts"]
        or activity["thread_attempts"]
        or new_thread_ids
        or new_hot_loop_thread_ids
        or (
            thread_count_before_hot_loop is not None
            and thread_count_after_hot_loop is not None
            and thread_count_after_hot_loop != thread_count_before_hot_loop
        )
    ):
        raise BenchmarkContractError(
            "worker_activity_or_source_stability_check_failed:{}".format(
                json.dumps(worker_checks, sort_keys=True)
            )
        )

    return {
        "schema": SCHEMA,
        "acceptance_status": ACCEPTANCE_STATUS,
        "run_kind": "SMOKE" if samples < 10_000 else "FULL_CANDIDATE",
        "side": side,
        "round_index": round_index,
        "source_revision": revision,
        "source_tree_sha256": before_tree_hash,
        "source_python_file_count": source_file_count,
        "runtime_contract_sha256": runtime_hash,
        "benchmark_script_sha256": script_hash,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "sqlite_version": sqlite3.sqlite_version,
        "config_seal_ns": config_seal_ns,
        "missing_config_rejection_ns": missing_config_rejection_ns,
        "test_profile_validation_ns": test_profile_ns,
        "store_ready_ns": store_ready_ns,
        # One valid load plus one missing-config rejection are deliberately
        # measured before importing the Store; neither occurs in the hot loop.
        "config_load_calls": config_load_calls[0],
        "valid_config_load_calls": 1,
        "missing_config_rejection_checks": 1,
        "config_load_calls_before_hot_loop": config_calls_before_hot_loop,
        "config_load_calls_after_hot_loop": config_load_calls[0],
        "import_origins": {
            "backtrader_package": str(actual_package),
            "btapistore_module": str(actual_store),
            "runtime_config_module": str(actual_config),
        },
        "effective_mode": effective.config.mode,
        "effective_preset": effective.config.preset,
        "effective_order_route": effective.order_route,
        "effective_required_capabilities": list(effective.required_capabilities),
        "effective_allows_network": effective.allows_network,
        "effective_allows_external_writes": effective.allows_external_writes,
        "test_profile_preflight_authorized": observation.preflight_authorized,
        "test_profile_execution_authorized": observation.execution_authorized,
        "test_profile_external_writes_started": observation.external_writes_started,
        "warmup_per_operation": warmup,
        "samples_per_operation": samples,
        "submit_samples_ns": valid_samples["submit"],
        "cancel_samples_ns": valid_samples["cancel"],
        "submit_distribution": _distribution(valid_samples["submit"]),
        "cancel_distribution": _distribution(valid_samples["cancel"]),
        "fake_provider_calls": {
            "submit": len(api.submissions),
            "cancel": len(api.cancellations),
        },
        "socket_api_attempts": list(activity["socket_attempts"]),
        "thread_api_attempts": list(activity["thread_attempts"]),
        "thread_count_before": thread_count_before,
        "thread_count_after": thread_count_after,
        "thread_count_before_hot_loop": thread_count_before_hot_loop,
        "thread_count_after_hot_loop": thread_count_after_hot_loop,
        "new_python_thread_ids": new_thread_ids,
        "new_python_thread_ids_hot_loop": new_hot_loop_thread_ids,
        "new_plugin_modules": plugin_modules,
        "optional_talib_integration_disabled": True,
        "source_tree_stable": True,
        "result_checks_passed": True,
    }


def _worker_main(args: argparse.Namespace) -> int:
    try:
        result = _run_worker(
            source_root=Path(args.source_root),
            runtime_root=Path(args.runtime_root),
            side=args.side,
            revision=args.revision,
            round_index=args.round_index,
            warmup=args.warmup,
            samples=args.samples,
        )
        destination = Path(args.result_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as exc:
        error = {
            "schema": SCHEMA,
            "acceptance_status": ACCEPTANCE_STATUS,
            "side": args.side,
            "round_index": args.round_index,
            "worker_error_type": type(exc).__name__,
            "worker_error": str(exc),
        }
        try:
            Path(args.result_file).write_text(
                json.dumps(error, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception:
            pass
        print("BM57 worker failed: {}".format(type(exc).__name__), file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    return 0


def _validate_campaign_inputs(args: argparse.Namespace) -> Tuple[Path, Path, Path, str, str, str]:
    baseline_root = Path(args.baseline_source_root).resolve(strict=True)
    candidate_root = Path(args.candidate_source_root).resolve(strict=True)
    output_root = Path(args.output_dir).resolve()
    if args.baseline_revision != BASELINE_REVISION:
        raise BenchmarkContractError("baseline_revision_not_the_reviewed_pre_i41_commit")
    baseline_hash, _ = source_tree_sha256(baseline_root)
    if baseline_hash != BASELINE_TREE_SHA256:
        raise BenchmarkContractError("baseline_source_tree_pin_mismatch")
    if baseline_root == candidate_root:
        raise BenchmarkContractError("baseline_and_candidate_source_roots_must_differ")
    if output_root.exists():
        raise BenchmarkContractError("output_directory_must_be_new")
    candidate_hash, _ = source_tree_sha256(candidate_root)
    candidate_revision = _revision_for(candidate_root, args.candidate_revision)
    runtime_hash = runtime_contract_sha256(_PROJECT_ROOT)
    if not candidate_revision or not runtime_hash or not candidate_hash:
        raise BenchmarkContractError("benchmark_source_identity_incomplete")
    return baseline_root, candidate_root, output_root, candidate_revision, runtime_hash, candidate_hash


def _launch_worker(
    *,
    source_root: Path,
    runtime_root: Path,
    side: str,
    revision: str,
    round_index: int,
    warmup: int,
    samples: int,
    result_file: Path,
    cwd: Path,
) -> Tuple[Dict[str, Any], Mapping[str, Any]]:
    command = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--_worker",
        "--source-root",
        str(source_root),
        "--runtime-root",
        str(runtime_root),
        "--side",
        side,
        "--revision",
        revision,
        "--round-index",
        str(round_index),
        "--warmup",
        str(warmup),
        "--samples",
        str(samples),
        "--result-file",
        str(result_file),
    ]
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=_safe_child_environment(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    elapsed = time.perf_counter_ns() - started
    process_metadata = {
        "exit_code": completed.returncode,
        "wall_elapsed_ns": elapsed,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if not result_file.is_file():
        return {
            "schema": SCHEMA,
            "acceptance_status": ACCEPTANCE_STATUS,
            "side": side,
            "round_index": round_index,
            "worker_error": "worker_result_file_missing",
        }, process_metadata
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {
            "schema": SCHEMA,
            "acceptance_status": ACCEPTANCE_STATUS,
            "side": side,
            "round_index": round_index,
            "worker_error": "worker_result_invalid",
        }
    return result, process_metadata


def _campaign_main(args: argparse.Namespace) -> int:
    try:
        (
            baseline_root,
            candidate_root,
            output_root,
            candidate_revision,
            runtime_hash,
            candidate_hash_before,
        ) = _validate_campaign_inputs(args)
    except Exception as exc:
        print("BM57 campaign rejected: {}".format(type(exc).__name__), file=sys.stderr)
        return 2

    script_hash_before = _sha256(Path(__file__).read_bytes())
    smoke = args.smoke
    rounds = 1 if smoke else 5
    warmup = 2 if smoke else 1000
    samples = 7 if smoke else 10_000
    output_root.mkdir(parents=True, exist_ok=False)
    run_started = time.time()
    baseline_revision = args.baseline_revision
    source_pairs = {
        "baseline": (baseline_root, baseline_revision),
        "candidate": (candidate_root, candidate_revision),
    }
    rows: List[Dict[str, Any]] = []
    failed = False
    for round_index in range(1, rounds + 1):
        side_order = ("baseline", "candidate") if round_index % 2 else ("candidate", "baseline")
        for side in side_order:
            source_root, revision = source_pairs[side]
            result_file = output_root / "round-{:02d}-{}.json".format(round_index, side)
            result, process_metadata = _launch_worker(
                source_root=source_root,
                runtime_root=_PROJECT_ROOT,
                side=side,
                revision=revision,
                round_index=round_index,
                warmup=warmup,
                samples=samples,
                result_file=result_file,
                cwd=output_root,
            )
            if process_metadata["stdout"] or process_metadata["stderr"]:
                (output_root / "round-{:02d}-{}.stdout.txt".format(round_index, side)).write_text(
                    str(process_metadata["stdout"]), encoding="utf-8"
                )
                (output_root / "round-{:02d}-{}.stderr.txt".format(round_index, side)).write_text(
                    str(process_metadata["stderr"]), encoding="utf-8"
                )
            result["worker_process"] = {
                "exit_code": process_metadata["exit_code"],
                "wall_elapsed_ns": process_metadata["wall_elapsed_ns"],
            }
            if result.get("result_checks_passed") is not True or process_metadata["exit_code"] != 0:
                failed = True
            if result_file.is_file():
                result["raw_result_sha256"] = _sha256(result_file.read_bytes())
            rows.append(result)

    comparisons: Dict[str, Any] = {}
    if rounds == 5 and not failed:
        for operation in ("submit", "cancel"):
            round_ratios: Dict[str, List[float]] = {"p50": [], "p99": []}
            for round_index in range(1, rounds + 1):
                baseline = next(
                    row for row in rows if row["round_index"] == round_index and row["side"] == "baseline"
                )
                candidate = next(
                    row for row in rows if row["round_index"] == round_index and row["side"] == "candidate"
                )
                for percentile in ("p50", "p99"):
                    base_ns = baseline[operation + "_distribution"][percentile + "_ns"]
                    candidate_ns = candidate[operation + "_distribution"][percentile + "_ns"]
                    round_ratios[percentile].append(candidate_ns / base_ns)
            comparisons[operation] = {
                key: {
                    "per_round_candidate_over_baseline": values,
                    "median_ratio": sorted(values)[len(values) // 2],
                }
                for key, values in round_ratios.items()
            }

    baseline_hash, baseline_count = source_tree_sha256(baseline_root)
    candidate_hash_after, candidate_count_after = source_tree_sha256(candidate_root)
    runtime_hash_after = runtime_contract_sha256(_PROJECT_ROOT)
    script_hash_after = _sha256(Path(__file__).read_bytes())
    if any(
        row.get("source_tree_sha256")
        != (baseline_hash if row.get("side") == "baseline" else candidate_hash_after)
        for row in rows
        if "source_tree_sha256" in row
    ):
        failed = True
    if any(
        row.get("runtime_contract_sha256") != runtime_hash
        or row.get("benchmark_script_sha256") != script_hash_before
        for row in rows
        if "source_tree_sha256" in row
    ):
        failed = True
    if (
        runtime_hash_after != runtime_hash
        or script_hash_after != script_hash_before
        or candidate_hash_after != candidate_hash_before
    ):
        failed = True
    performance_gate: Optional[Dict[str, Any]] = None
    if not smoke and not failed:
        performance_gate = _evaluate_performance_gate(comparisons)
    performance_failed = performance_gate is not None and not performance_gate["passed"]
    if failed:
        performance_status = "NOT_EVALUATED_HARNESS_FAILURE"
    elif smoke:
        performance_status = "NOT_EVALUATED_SMOKE"
    elif performance_failed:
        performance_status = "PERFORMANCE_NOT_ADMITTED"
    else:
        performance_status = "THRESHOLD_PASSED_NOT_ACCEPTED_FULL_MATRIX"
    campaign = {
        "schema": SCHEMA,
        "acceptance_status": ACCEPTANCE_STATUS,
        "run_kind": "SMOKE" if smoke else "FULL_CANDIDATE",
        "started_at_utc_epoch_seconds": run_started,
        "finished_at_utc_epoch_seconds": time.time(),
        "mode": "simulation/replay",
        "sample_protocol": {
            "warmup_per_operation": warmup,
            "samples_per_operation_per_round": samples,
            "paired_rounds": rounds,
            "nearest_rank_percentiles": [50, 95, 99, 100],
            "operation_rate_limit_hz": None,
        },
        "python_executable": sys.executable,
        "python_version": sys.version,
        "runtime_contract_sha256": runtime_hash,
        "runtime_contract_sha256_after": runtime_hash_after,
        "benchmark_script_sha256": script_hash_before,
        "benchmark_script_sha256_after": script_hash_after,
        "baseline": {
            "revision": baseline_revision,
            "source_tree_sha256": baseline_hash,
            "source_python_file_count": baseline_count,
            "source_root": str(baseline_root),
        },
        "candidate": {
            "revision": candidate_revision,
            "source_tree_sha256_before": candidate_hash_before,
            "source_tree_sha256_after": candidate_hash_after,
            "source_python_file_count_after": candidate_count_after,
            "source_root": str(candidate_root),
        },
        "rounds": rows,
        "comparisons": comparisons,
        "performance_gate": performance_gate,
        "performance_status": performance_status,
        "harness_status": "FAILED" if failed else "PASS",
        "fail_closed": failed,
        "status": (
            "SMOKE_ONLY"
            if smoke and not failed
            else (
                "FAILED"
                if failed
                else ("PERFORMANCE_NOT_ADMITTED" if performance_failed else "THRESHOLD_PASSED_NOT_ACCEPTED_FULL_MATRIX")
            )
        ),
        "limitations": [
            "synthetic replay fixture and in-process fake API only",
            "test profile observation is not a dispatch permit",
            "does not enable a runtime or production direct route",
            "does not include the required Windows/Linux full matrix unless separately run",
        ],
    }
    result_path = output_root / "campaign-result.json"
    result_path.write_text(
        json.dumps(campaign, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(json.dumps({"result": str(result_path), "status": campaign["status"], "acceptance_status": ACCEPTANCE_STATUS}))
    return 2 if failed else (3 if performance_failed else 0)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="small fake-only correctness smoke")
    mode.add_argument("--full", action="store_true", help="BM57 sample count; never self-accepts")
    parser.add_argument("--baseline-source-root")
    parser.add_argument("--candidate-source-root", default=str(_PROJECT_ROOT))
    parser.add_argument("--baseline-revision", default=BASELINE_REVISION)
    parser.add_argument("--candidate-revision")
    parser.add_argument("--output-dir")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-root", help=argparse.SUPPRESS)
    parser.add_argument("--side", choices=("baseline", "candidate"), help=argparse.SUPPRESS)
    parser.add_argument("--revision", help=argparse.SUPPRESS)
    parser.add_argument("--round-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--warmup", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--samples", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--result-file", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argument_parser().parse_args(argv)
    if args._worker:
        required = (
            args.source_root,
            args.runtime_root,
            args.side,
            args.revision,
            args.round_index,
            args.warmup,
            args.samples,
            args.result_file,
        )
        if any(value is None for value in required) or args.warmup < 0 or args.samples < 1:
            print("BM57 worker arguments invalid", file=sys.stderr)
            return 2
        return _worker_main(args)
    if args.smoke is args.full:
        print("select exactly one of --smoke or --full", file=sys.stderr)
        return 2
    if not args.baseline_source_root or not args.output_dir:
        print("--baseline-source-root and --output-dir are required", file=sys.stderr)
        return 2
    return _campaign_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
