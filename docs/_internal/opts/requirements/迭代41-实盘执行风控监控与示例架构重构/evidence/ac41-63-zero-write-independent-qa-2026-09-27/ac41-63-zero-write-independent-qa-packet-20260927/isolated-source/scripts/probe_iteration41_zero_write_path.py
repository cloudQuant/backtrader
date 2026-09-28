"""Probe one registered local-backtest path without network, SDKs, or writes.

The result is a route-scoped runtime observation and candidate difference.  It
does not claim that unobserved examples or runtime paths are closed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


SCHEMA_VERSION = "iteration41.zero-write-runtime-probe.v1"
LOCAL_BACKTEST_RUNTIME_ID = "backtrader.iteration41.local_backtest_fixture"
DEFAULT_INVENTORY = Path("evidence/ac41-63/live-execution-inventory-candidates.json")
STATIC_RUNTIME_SCOPE = ("backtrader_runtime", "backtrader/brokers", "backtrader/stores")
BLOCKED_NATIVE_MODULES = frozenset(
    (
        "bt_api_py",
        "bt_api_base",
        "bt_api_ctp",
        "bt_api_execution",
        "bt_api_risk",
        "bt_api_monitor",
        "PyCTP",
        "thosttraderapi",
        "ctp",
        "ccxt",
        "okx",
        "binance",
        "ibapi",
        "xtquant",
    )
)
BLOCKED_PROCESS_EVENTS = frozenset(
    (
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.system",
        "subprocess.Popen",
    )
)
BLOCKED_FILESYSTEM_EVENTS = frozenset(
    (
        "os.chmod",
        "os.chown",
        "os.link",
        "os.mkdir",
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.symlink",
        "os.truncate",
        "os.utime",
    )
)
WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_RDWR
    | os.O_CREAT
    | os.O_TRUNC
    | getattr(os, "O_APPEND", 0)
)


class ProbeBlockedEvent(RuntimeError):
    """An operation was stopped by the local-only probe boundary."""


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    stable = {
        name: candidate.get(name)
        for name in (
            "kind",
            "path",
            "line",
            "call",
            "method",
            "dynamic_reason",
        )
    }
    return json.dumps(stable, sort_keys=True, separators=(",", ":"))


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    return hashlib.sha256(_candidate_key(candidate).encode("utf-8")).hexdigest()[:16]


def _all_candidates(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidates = list(payload.get("writer_candidates", ()))
    candidates.extend(payload.get("dynamic_execution_candidates", ()))
    for candidate in candidates:
        path = candidate.get("path")
        if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("inventory candidate path is not repository-relative")
        candidate["candidate_id"] = _candidate_id(candidate)
    candidate_ids = [str(candidate["candidate_id"]) for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("inventory contains duplicate stable candidate identities")
    return candidates


def _load_inventory(path: Path) -> Tuple[Dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "CANDIDATE_DISCOVERY_ONLY"
        or payload.get("source_root") != "."
        or payload.get("counts", {}).get("parse_errors") != 0
    ):
        raise ValueError("static inventory is not the expected redacted candidate artifact")
    return payload, hashlib.sha256(raw).hexdigest()


def _relative_source(filename: object, source_root: str) -> Optional[str]:
    if not isinstance(filename, str) or not filename or filename.startswith("<"):
        return None
    try:
        absolute = os.path.normcase(os.path.realpath(os.path.abspath(filename)))
        root = os.path.normcase(source_root)
        if os.path.commonpath((absolute, root)) != root:
            return None
        relative = os.path.relpath(absolute, root)
    except (OSError, ValueError):
        return None
    if relative == "." or relative.startswith(".." + os.sep):
        return None
    return relative.replace("\\", "/")


def _load_collector(source_root: Path) -> Any:
    collector_path = source_root / "scripts" / "collect_iteration41_writer_inventory.py"
    spec = importlib.util.spec_from_file_location("iteration41_static_collector", collector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("static collector could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _component_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if candidate["path"].startswith(STATIC_RUNTIME_SCOPE)
    ]


def _group_candidates_by_path(
    candidates: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate["path"])].append(candidate)
    return dict(grouped)


def _is_known_config_descriptor_cleanup(candidate: Mapping[str, Any]) -> bool:
    """Exclude one reviewed resource close from trading-writer interception."""
    return (
        candidate.get("kind") == "writer_call_candidate"
        and candidate.get("path") == "backtrader_runtime/config.py"
        and candidate.get("line") == 576
        and candidate.get("function_name") == "_read_config_text"
        and candidate.get("call") == "os.close"
        and candidate.get("method") == "close"
    )


def _is_action_writer_candidate(candidate: Mapping[str, Any]) -> bool:
    if candidate.get("kind") != "writer_call_candidate":
        return False
    if candidate.get("method") == "close":
        return candidate.get("call") in (
            "self.close",
            "broker.close",
            "self.broker.close",
        )
    return bool(candidate.get("method"))


def _static_scope_comparison(
    source_root: Path, candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    collector = _load_collector(source_root)
    scoped = collector.collect_inventory(source_root, STATIC_RUNTIME_SCOPE)
    frozen_slice = _component_candidates(candidates)
    current_slice = _component_candidates(
        list(scoped["writer_candidates"]) + list(scoped["dynamic_execution_candidates"])
    )
    frozen_keys = {_candidate_key(row) for row in frozen_slice}
    current_keys = {_candidate_key(row) for row in current_slice}
    return {
        "scope_paths": list(STATIC_RUNTIME_SCOPE),
        "frozen_candidate_count": len(frozen_slice),
        "current_candidate_count": len(current_slice),
        "matches_frozen_inventory": frozen_keys == current_keys,
        "added_since_frozen_inventory": len(current_keys - frozen_keys),
        "missing_from_current_source": len(frozen_keys - current_keys),
        "writer_candidates": len(scoped["writer_candidates"]),
        "dynamic_candidates": len(scoped["dynamic_execution_candidates"]),
        "parse_errors": len(scoped["parse_errors"]),
    }


def _audit_boundary(
    source_root: str,
    counters: Dict[str, List[str]],
    local_system_observations: List[Dict[str, Any]],
    file_write_observations: List[Dict[str, Any]],
    local_sink_observations: List[Dict[str, Any]],
    process_observations: List[Dict[str, Any]],
):
    def audit(event: str, args: Tuple[Any, ...]) -> None:
        if event.startswith("socket."):
            if event == "socket.gethostname":
                frame = sys._getframe(1)
                try:
                    caller_filename = os.path.realpath(frame.f_code.co_filename)
                    caller_path = os.path.relpath(caller_filename, source_root).replace("\\", "/")
                    if caller_path == ".." or caller_path.startswith("../"):
                        caller_path = "<external>"
                except (OSError, ValueError):
                    caller_path = "<unknown>"
                local_system_observations.append(
                    {
                        "event": event,
                        "classification": "LOCAL_HOST_IDENTITY_QUERY_NO_NETWORK_IO",
                        "caller_path": caller_path,
                        "caller_line": frame.f_lineno,
                        "caller_function": frame.f_code.co_name,
                        "argument_types": [type(value).__name__ for value in args],
                    }
                )
                return
            counters["network_attempts"].append(event)
            raise ProbeBlockedEvent("network entry blocked")
        if event in BLOCKED_PROCESS_EVENTS or event.startswith("subprocess."):
            counters["process_attempts"].append(event)
            frame = sys._getframe(1)
            stack: List[Dict[str, Any]] = []
            for _depth in range(12):
                try:
                    absolute = os.path.realpath(frame.f_code.co_filename)
                    relative = os.path.relpath(absolute, source_root).replace("\\", "/")
                    if relative == ".." or relative.startswith("../"):
                        relative = "<external>"
                except (OSError, ValueError):
                    relative = "<unknown>"
                stack.append(
                    {
                        "path": relative,
                        "line": frame.f_lineno,
                        "function": frame.f_code.co_name,
                        "module": str(frame.f_globals.get("__name__", "<unknown>")),
                    }
                )
                if frame.f_back is None:
                    break
                frame = frame.f_back
            process_observations.append(
                {
                    "event": event,
                    "stack": stack,
                    "argument_types": [type(value).__name__ for value in args],
                }
            )
            raise ProbeBlockedEvent("process launch blocked")
        if event == "import" and args:
            module_name = args[0]
            if isinstance(module_name, str) and module_name.split(".", 1)[0] in BLOCKED_NATIVE_MODULES:
                counters["native_import_attempts"].append(module_name.split(".", 1)[0])
                raise ProbeBlockedEvent("provider or native module import blocked")
        if event in BLOCKED_FILESYSTEM_EVENTS:
            counters["filesystem_mutations"].append(event)
            raise ProbeBlockedEvent("filesystem mutation blocked")
        if event != "open" or not args:
            return

        path_value = args[0]
        try:
            path_text = os.fsdecode(os.fspath(path_value))
        except (TypeError, ValueError):
            path_text = ""
        normalized = path_text.replace("\\", "/").lower()
        leaf = normalized.rsplit("/", 1)[-1]
        if "runtime-ctp-private" in normalized or leaf == ".env" or leaf.startswith(".env."):
            counters["protected_input_attempts"].append("protected-path-read")
            raise ProbeBlockedEvent("private configuration input blocked")

        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        mode_writes = isinstance(mode, str) and any(marker in mode for marker in "wax+")
        flags_write = isinstance(flags, int) and bool(flags & WRITE_FLAGS)
        if mode_writes or flags_write:
            frame = sys._getframe(1)
            leaf = path_text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
            non_create_flags = flags & (
                getattr(os, "O_CREAT", 0)
                | getattr(os, "O_TRUNC", 0)
                | getattr(os, "O_APPEND", 0)
            ) if isinstance(flags, int) else -1
            if (
                leaf == "nul"
                and frame.f_code.co_name == "_get_devnull"
                and mode is None
                and isinstance(flags, int)
                and bool(flags & os.O_RDWR)
                and non_create_flags == 0
            ):
                local_sink_observations.append(
                    {
                        "device": "windows_null_device",
                        "classification": "NON_PERSISTENT_NULL_SINK_OPEN",
                        "caller_path": "<external>",
                        "caller_line": frame.f_lineno,
                        "caller_function": frame.f_code.co_name,
                        "mode": None,
                        "flags": flags,
                        "argument_types": [type(value).__name__ for value in args],
                    }
                )
                return
            counters["file_write_attempts"].append("open-write")
            try:
                path_absolute = os.path.realpath(os.path.abspath(path_text))
                relative_path = os.path.relpath(path_absolute, source_root).replace("\\", "/")
                if relative_path == ".." or relative_path.startswith("../"):
                    relative_path = "<external>"
                elif "runtime-ctp-private" in relative_path.lower():
                    relative_path = "<protected>"
            except (OSError, ValueError):
                relative_path = "<unknown>"
            try:
                caller_absolute = os.path.realpath(frame.f_code.co_filename)
                caller_path = os.path.relpath(caller_absolute, source_root).replace("\\", "/")
                if caller_path == ".." or caller_path.startswith("../"):
                    caller_path = "<external>"
            except (OSError, ValueError):
                caller_path = "<unknown>"
            file_write_observations.append(
                {
                    "path": relative_path,
                    "mode": mode if isinstance(mode, str) else None,
                    "flags": flags if isinstance(flags, int) else None,
                    "caller_path": caller_path,
                    "caller_line": frame.f_lineno,
                    "caller_function": frame.f_code.co_name,
                    "argument_types": [type(value).__name__ for value in args],
                }
            )
            raise ProbeBlockedEvent("file write blocked")

    return audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--inventory", type=Path, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    source_root = args.source_root.resolve()
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    inventory_path = (
        args.inventory if args.inventory is not None else source_root / DEFAULT_INVENTORY
    ).resolve()
    try:
        inventory_path.relative_to(source_root)
    except ValueError:
        print(json.dumps({"status": "REJECTED", "reason": "inventory_outside_source_root"}))
        return 2

    try:
        inventory, inventory_sha256 = _load_inventory(inventory_path)
        candidates = _all_candidates(inventory)
        static_comparison = _static_scope_comparison(source_root, candidates)
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {"status": "REJECTED", "reason": type(error).__name__}, sort_keys=True
            )
        )
        return 2

    relative_inventory = inventory_path.relative_to(source_root).as_posix()
    counters: Dict[str, List[str]] = {
        "network_attempts": [],
        "process_attempts": [],
        "native_import_attempts": [],
        "protected_input_attempts": [],
        "file_write_attempts": [],
        "filesystem_mutations": [],
        "blocked_writer_entry_calls": [],
        "runtime_only_writer_entry_calls": [],
    }
    local_system_observations: List[Dict[str, Any]] = []
    file_write_observations: List[Dict[str, Any]] = []
    local_sink_observations: List[Dict[str, Any]] = []
    process_observations: List[Dict[str, Any]] = []
    platform_stub_observations: List[Dict[str, Any]] = []
    optional_import_stubs: List[Dict[str, str]] = []
    known_resource_cleanup_observations: List[Dict[str, Any]] = []
    try:
        writer_method_names = {
            str(candidate["method"])
            for candidate in candidates
            if _is_action_writer_candidate(candidate)
        }
        candidates_by_site: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            line = candidate.get("line")
            if isinstance(line, int):
                candidates_by_site[(candidate["path"], line)].append(candidate)

        loaded_source_files: Set[str] = set()
        called_candidate_ids: Set[str] = set()
        callsite_observations: Dict[str, Dict[str, Any]] = {}
        relative_cache: Dict[str, Optional[str]] = {}

        def relative(filename: object) -> Optional[str]:
            if not isinstance(filename, str):
                return None
            if filename not in relative_cache:
                relative_cache[filename] = _relative_source(filename, str(source_root))
            return relative_cache[filename]

        def trace(frame: Any, event: str, _arg: Any) -> Any:
            if event == "line":
                relative_path = relative(frame.f_code.co_filename)
                if relative_path is not None:
                    loaded_source_files.add(relative_path)
            return trace

        def profile(frame: Any, event: str, arg: Any) -> None:
            if event == "call":
                caller = frame.f_back
                callee_path = relative(frame.f_code.co_filename)
                callee_name = frame.f_code.co_name
                site_line = caller.f_lineno if caller is not None else 0
                site_path = relative(caller.f_code.co_filename) if caller is not None else None
            elif event == "c_call":
                caller = frame
                callee_path = None
                callee_name = getattr(arg, "__name__", type(arg).__name__)
                site_line = caller.f_lineno
                site_path = relative(caller.f_code.co_filename)
            else:
                return

            matched = (
                candidates_by_site.get((site_path, site_line), ())
                if site_path is not None
                else ()
            )
            if matched:
                for candidate in matched:
                    candidate_id = str(candidate["candidate_id"])
                    called_candidate_ids.add(candidate_id)
                    observation = {
                        "candidate_id": candidate_id,
                        "path": candidate["path"],
                        "line": candidate["line"],
                        "kind": candidate["kind"],
                        "call": candidate["call"],
                        "callee_name": str(callee_name),
                        "event": event,
                    }
                    if event == "c_call":
                        observation["callee_module"] = getattr(arg, "__module__", None)
                        observation["argument_local_types"] = {
                            name: type(caller.f_locals[name]).__name__
                            for name in ("descriptor",)
                            if caller is not None and name in caller.f_locals
                        }
                    callsite_observations[candidate_id] = observation
                    if _is_known_config_descriptor_cleanup(candidate):
                        known_resource_cleanup_observations.append(observation)
                    elif _is_action_writer_candidate(candidate):
                        counters["blocked_writer_entry_calls"].append(candidate_id)
                        raise ProbeBlockedEvent("static writer entry call blocked")
                return

            if (
                event == "call"
                and callee_path is not None
                and callee_name in writer_method_names
                and site_path is not None
            ):
                observation = {
                    "caller_path": site_path,
                    "caller_line": site_line,
                    "callee_path": callee_path,
                    "callee_name": callee_name,
                }
                counters["runtime_only_writer_entry_calls"].append(
                    "{0}:{1}:{2}".format(site_path, site_line, callee_name)
                )
                raise ProbeBlockedEvent("runtime-only writer-like entry call blocked")

        sys.dont_write_bytecode = True
        sys.addaudithook(
            _audit_boundary(
                str(source_root),
                counters,
                local_system_observations,
                file_write_observations,
                local_sink_observations,
                process_observations,
            )
        )
        import platform

        original_syscmd_ver = getattr(platform, "_syscmd_ver", None)
        if not callable(original_syscmd_ver):
            raise RuntimeError("platform_syscmd_ver_unavailable")

        def deterministic_platform_version_stub(*args: Any, **kwargs: Any):
            del args, kwargs
            frame = sys._getframe(1)
            platform_stub_observations.append(
                {
                    "event": "platform._syscmd_ver",
                    "classification": "STUBBED_TO_PREVENT_PROCESS_LAUNCH",
                    "caller_module": str(frame.f_globals.get("__name__", "<unknown>")),
                    "caller_function": frame.f_code.co_name,
                    "caller_line": frame.f_lineno,
                    "return_value": ["", "", "", ""],
                }
            )
            return "", "", "", ""

        platform._syscmd_ver = deterministic_platform_version_stub
        sys.settrace(trace)
        sys.setprofile(profile)
        # TA-Lib is an optional native extension.  This fixture does not use
        # TA-Lib, and importing it in this host also imports NumPy's testing
        # helpers, which try to spawn a CPU-feature probe process.  Model the
        # supported "TA-Lib unavailable" environment without importing it.
        sys.modules["talib"] = None
        optional_import_stubs.append(
            {
                "module": "talib",
                "classification": "OPTIONAL_NATIVE_EXTENSION_MARKED_UNAVAILABLE",
            }
        )
        os.environ["BACKTRADER_LIGHT_IMPORT"] = "1"
        import backtrader as bt

        from backtrader.feeds.csvgeneric import GenericCSVData

        bt.feeds.GenericCSVData = GenericCSVData
        optional_import_stubs.append(
            {
                "module": "backtrader.feeds.GenericCSVData",
                "classification": "EXACT_PACKAGE_CSV_FEED_EXPORT_BOUND_FOR_LIGHT_IMPORT",
            }
        )
        run_result: Optional[Dict[str, Any]] = None
        run_error_type: Optional[str] = None
        run_error_details: Optional[Dict[str, Any]] = None
        try:
            # Install guards before importing route code.  The only project
            # route imported below is the package-owned local fixture.
            from backtrader_runtime.inventory import (
                ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID,
                iteration41_backtest_fixture_registry,
            )

            from backtrader_runtime.runner import dispatch_configured_runtime

            registry = iteration41_backtest_fixture_registry()
            if len(registry.registrations) != 1:
                raise ValueError("fixture_registry_not_singleton")
            registration = registry.registrations[0]
            if not (
                registration.runtime_id == LOCAL_BACKTEST_RUNTIME_ID
                == ITERATION41_PACKAGE_LOCAL_BACKTEST_RUNTIME_ID
                and registration.strategy_id == LOCAL_BACKTEST_RUNTIME_ID
                and registration.allowed_presets == ("local_backtest",)
                and registration.capability_modules == ()
                and registration.available_capabilities == ()
            ):
                raise ValueError("fixture_registration_not_zero_capability")
            runtime_relative = (
                registration.runtime_dir.resolve().relative_to(source_root).as_posix()
            )
            run_result = dispatch_configured_runtime(registration.runtime_dir, registry)
        except Exception as error:
            run_error_type = type(error).__name__
            as_dict = getattr(error, "as_dict", None)
            if callable(as_dict):
                details = as_dict()
                if isinstance(details, dict):
                    run_error_details = {
                        key: details[key]
                        for key in ("error_code", "field_path", "reason")
                        if key in details
                    }
            cause = getattr(error, "__cause__", None)
            if cause is not None:
                run_error_details = run_error_details or {}
                run_error_details["cause_type"] = type(cause).__name__
                cause_frames: List[Dict[str, Any]] = []
                traceback = getattr(cause, "__traceback__", None)
                while traceback is not None and len(cause_frames) < 8:
                    frame = traceback.tb_frame
                    cause_frames.append(
                        {
                            "path": relative(frame.f_code.co_filename) or "<external>",
                            "line": traceback.tb_lineno,
                            "function": frame.f_code.co_name,
                            "module": str(frame.f_globals.get("__name__", "<unknown>")),
                        }
                    )
                    traceback = traceback.tb_next
                run_error_details["cause_frames"] = cause_frames
                cause_as_dict = getattr(cause, "as_dict", None)
                if callable(cause_as_dict):
                    cause_details = cause_as_dict()
                    run_error_details["cause_error_code"] = cause_details.get("error_code")
                    run_error_details["cause_reason"] = cause_details.get("reason")
        finally:
            sys.setprofile(None)
            sys.settrace(None)
            platform._syscmd_ver = original_syscmd_ver

        loaded_candidates = [
            candidate for candidate in candidates if candidate["path"] in loaded_source_files
        ]
        uncalled_loaded = [
            candidate
            for candidate in loaded_candidates
            if candidate["candidate_id"] not in called_candidate_ids
        ]
        unloaded_by_path: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            if candidate["path"] not in loaded_source_files:
                unloaded_by_path[str(candidate["path"])].append(candidate)

        provider_modules_loaded = sorted(
            name
            for name in sys.modules
            if name.split(".", 1)[0] in BLOCKED_NATIVE_MODULES
        )
        counters["native_import_attempts"].extend(provider_modules_loaded)
        runtime_config_value = (
            {} if run_result is None else run_result.get("runtime_config", {})
        )
        runtime_config = (
            runtime_config_value if isinstance(runtime_config_value, Mapping) else {}
        )
        result_passed = bool(
            run_result
            and run_result.get("status") == "LOCAL_BACKTEST_CEREBRO_PASS"
            and run_result.get("data_bars") == 4
            and run_result.get("external_network_requests") == 0
            and run_result.get("external_write_requests") == 0
            and run_result.get("provider_submissions") == 0
            and run_result.get("actual_fills") == 0
            and not run_result.get("network_guard_attempts")
            and runtime_config.get("strategy_id") == LOCAL_BACKTEST_RUNTIME_ID
            and runtime_config.get("mode") == "backtest"
            and runtime_config.get("preset") == "local_backtest"
            and runtime_config.get("environment") == "local"
            and runtime_config.get("allows_network") is False
            and runtime_config.get("allows_external_writes") is False
            and runtime_config.get("allows_production_writes") is False
            and not provider_modules_loaded
        )
        guard_counts = {name: len(values) for name, values in counters.items()}
        guard_clean = all(count == 0 for count in guard_counts.values())
        status = (
            "LOCAL_BACKTEST_TRACE_WITH_STUBS"
            if result_passed and guard_clean and static_comparison["matches_frozen_inventory"]
            else "LOCAL_BACKTEST_PROBE_BLOCKED_OR_INCOMPLETE"
        )

        report = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "acceptance_boundary": "CANDIDATE_EVIDENCE_ONLY_NOT_WRITER_CLOSURE",
            "source_root": ".",
            "static_inventory": {
                "path": relative_inventory,
                "sha256": inventory_sha256,
                "status": inventory["status"],
                "counts": inventory["counts"],
                "candidate_count": len(candidates),
            },
            "registered_route": {
                "runtime_id": registration.runtime_id,
                "strategy_id": registration.strategy_id,
                "registry_id": "backtrader.iteration41.local-backtest-fixture",
                "runtime_path": runtime_relative,
                "mode": "backtest",
                "preset": "local_backtest",
                "capabilities": [],
                "secrets_ref": "none",
            },
            "static_scope_source_recheck": static_comparison,
            "runtime_observation": {
                "runner_status": None if run_result is None else run_result.get("status"),
                "runner_error_type": run_error_type,
                "runner_error_details": run_error_details,
                "data_bars": None if run_result is None else run_result.get("data_bars"),
                "runner_network_requests": None
                if run_result is None
                else run_result.get("external_network_requests"),
                "runner_external_write_requests": None
                if run_result is None
                else run_result.get("external_write_requests"),
                "runner_provider_submissions": None
                if run_result is None
                else run_result.get("provider_submissions"),
                "runner_actual_fills": None if run_result is None else run_result.get("actual_fills"),
                "runtime_config": {
                    key: runtime_config.get(key)
                    for key in (
                        "strategy_id",
                        "mode",
                        "preset",
                        "environment",
                        "allows_network",
                        "allows_external_writes",
                        "allows_production_writes",
                    )
                },
                "loaded_source_file_count": len(loaded_source_files),
                "loaded_source_files": sorted(loaded_source_files),
                "provider_modules_loaded": provider_modules_loaded,
                "optional_import_stubs": optional_import_stubs,
                "backtrader_import_profile": os.environ.get("BACKTRADER_LIGHT_IMPORT"),
                "platform_version_process_stub_installed": True,
                "platform_version_process_stub_invoked": bool(platform_stub_observations),
                "route_result_passed_under_stubs": result_passed,
            },
            "candidate_difference": {
                "static_candidates_in_loaded_source_files": len(loaded_candidates),
                "static_candidate_callsites_invoked": len(callsite_observations),
                "static_writer_callsites_invoked": sum(
                    1
                    for item in callsite_observations.values()
                    if any(
                        candidate.get("candidate_id") == item["candidate_id"]
                        and _is_action_writer_candidate(candidate)
                        for candidate in candidates
                    )
                ),
                "invoked_candidate_callsites": sorted(
                    callsite_observations.values(),
                    key=lambda item: (item["path"], item["line"], item["candidate_id"]),
                ),
                "known_non_writer_resource_cleanup_calls": known_resource_cleanup_observations,
                "static_candidates_in_loaded_files_not_invoked": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "path": candidate["path"],
                        "line": candidate.get("line"),
                        "kind": candidate.get("kind"),
                        "call": candidate.get("call"),
                        "status": "NOT_EXERCISED_NOT_ADMITTED",
                    }
                    for candidate in uncalled_loaded
                ],
                "static_candidates_outside_loaded_source_files": len(candidates)
                - len(loaded_candidates),
                "not_exercised_paths": [
                    {
                        "path": path,
                        "candidate_count": len(rows),
                        "candidate_kinds": sorted({str(row["kind"]) for row in rows}),
                        "status": "NOT_EXERCISED_NOT_ADMITTED",
                    }
                    for path, rows in sorted(unloaded_by_path.items())
                ],
                "unexercised_candidate_paths": [
                    {
                        "path": path,
                        "candidate_count": len(rows),
                        "candidate_kinds": sorted({str(row["kind"]) for row in rows}),
                        "source_file_loaded": path in loaded_source_files,
                        "status": "NOT_EXERCISED_NOT_ADMITTED",
                    }
                    for path, rows in sorted(
                        _group_candidates_by_path(
                            candidate
                            for candidate in candidates
                            if candidate["candidate_id"] not in called_candidate_ids
                        ).items()
                    )
                ],
                "unexercised_candidate_count": len(candidates) - len(called_candidate_ids),
                "runtime_only_writer_like_calls": counters[
                    "runtime_only_writer_entry_calls"
                ],
                "static_scope_matches_frozen_inventory": static_comparison[
                    "matches_frozen_inventory"
                ],
                "writer_closure_established": False,
            },
            "guard_event_counts": guard_counts,
            "local_system_observations": local_system_observations,
            "file_write_observations": file_write_observations,
            "local_sink_observations": local_sink_observations,
            "process_observations": process_observations,
            "platform_version_process_stub_observations": platform_stub_observations,
            "guard_events": {
                "network_attempts": list(counters["network_attempts"]),
                "process_attempts": list(counters["process_attempts"]),
                "native_import_attempts": list(counters["native_import_attempts"]),
                "protected_input_attempts": list(counters["protected_input_attempts"]),
                "file_write_attempts": list(counters["file_write_attempts"]),
                "filesystem_mutations": list(counters["filesystem_mutations"]),
                "blocked_writer_entry_calls": list(counters["blocked_writer_entry_calls"]),
            },
            "limitations": [
                "Only the exact package-owned backtest/local_backtest fixture was dispatched.",
                "No example replay, public shadow, managed L2, CTP sandbox, or live route was executed.",
                "Static candidates outside files loaded by this route remain explicitly unexercised and not admitted.",
                "Python audit/profile hooks are test-process probes, not OS isolation or a proof against arbitrary native code.",
                "The standard-library platform._syscmd_ver helper was stubbed to prevent its Windows cmd.exe version query; Backtrader's lightweight import profile was used, the packaged GenericCSVData class was bound to the fixture's expected export, and optional native TA-Lib was marked unavailable to avoid NumPy's subprocess CPU probe.",
                "This is a route trace with deterministic environment stubs, not an unmodified-host acceptance run; process-boundary behavior remains untested.",
                "This route-scoped difference cannot establish mathematical completeness or writer closure.",
            ],
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if status == "LOCAL_BACKTEST_TRACE_WITH_STUBS" else 2
    except Exception as error:
        sys.setprofile(None)
        sys.settrace(None)
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "LOCAL_BACKTEST_PROBE_BLOCKED_OR_INCOMPLETE",
            "failure_type": type(error).__name__,
            "guard_event_counts": {name: len(values) for name, values in counters.items()},
            "acceptance_boundary": "CANDIDATE_EVIDENCE_ONLY_NOT_WRITER_CLOSURE",
        }
        print(json.dumps(failure, sort_keys=True))
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
