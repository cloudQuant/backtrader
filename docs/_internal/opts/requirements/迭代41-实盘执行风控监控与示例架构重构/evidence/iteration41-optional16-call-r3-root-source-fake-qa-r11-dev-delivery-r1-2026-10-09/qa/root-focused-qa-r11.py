"""Root-only, source-fake QA for the Optional16 Call R3 audit regression.

Run only as a standalone process with the pinned CPython and ten pinned public source inputs.
``-I -S -B -X utf8``. The parent verifies the public inputs, installs
operation guards, and launches one fixed synthetic child. It records finite
phase and exception categories, fixed child guard counts and milestone booleans,
and source-bound function/path/line locations. It discards exception text,
locals, and raw child stdout or stderr.
"""

from __future__ import annotations

import sys

_R11_DIAGNOSTIC_PREFIX = "OPTIONAL16_R11_CHILD_DIAG:"
_R11_RESULT_BOOTSTRAP_PATH = "D:/source_code/backtrader/.codex-tmp/optional16_call_r3_root_focused_qa_result_r11_20261009.json"


def _r11_exception_name(exc: BaseException) -> str:
    name = type(exc).__name__
    allowed = {
        "AssertionError",
        "FileExistsError",
        "FileNotFoundError",
        "ImportError",
        "JSONDecodeError",
        "ModuleNotFoundError",
        "OSError",
        "RuntimeError",
        "TimeoutExpired",
        "ValueError",
    }
    return name if name in allowed else "OtherException"


def _r11_bootstrap_failure(exc: BaseException, bootstrap_phase: str) -> None:
    # This path uses built-ins only so import failures still produce a finite
    # diagnostic. It never includes exception text or tracebacks.
    exception_type = _r11_exception_name(exc)
    is_path_setup = bootstrap_phase == "module_path_setup"
    child_phase = "child_module_path_setup" if is_path_setup else "child_module_imports"
    parent_phase = "parent_module_path_setup" if is_path_setup else "parent_module_imports"
    failure_category = "script_path_initialization_failure" if is_path_setup else "module_bootstrap_failure"
    if sys.argv[1:] == ["--regression-child"]:
        record = (
            '{"schema":"iteration41.optional16.call-r3.root-focused-qa.child-diagnostic.r11",'
            '"status":"failed","phase":"'
            + child_phase
            + '",'
            '"last_completed_phase":null,"exception_type":"'
            + exception_type
            + '","failure_category":"'
            + failure_category
            + '",'
            '"focused_case_entered":false,"pinned_r1_helper_called":false,'
            '"qa_origin_verified":false,"child_guard_counts":null,'
            '"child_milestones":null,"source_failure_locations":[]}'
        )
        try:
            print(_R11_DIAGNOSTIC_PREFIX + record, flush=True)
        except BaseException:
            pass
        return

    record = (
        '{"schema":"iteration41.optional16.call-r3.root-focused-qa.r11",'
        '"status":"FAIL_DIAGNOSTIC_ONLY","evidence_scope":"SOURCE_FAKE_ORIGINAL_AUDIT_REFERENCE_BINDING_WITH_PINNED_PUBLIC_HELPER_BOOTSTRAP_ONLY",'
        '"parent":{"phase":"'
        + parent_phase
        + '","failure_phase":"'
        + parent_phase
        + '","last_completed_phase":null,'
        '"exception_type":"'
        + exception_type
        + '","failure_category":"'
        + failure_category
        + '"},'
        '"child":{"entry_observed":false,"phase":"unobserved",'
        '"diagnostic_status":"not_started","child_guard_counts":null,'
        '"child_milestones":null,"source_failure_locations":[]},'
        '"raw_exception_text_included":false}'
    )
    try:
        with open(_R11_RESULT_BOOTSTRAP_PATH, "x", encoding="ascii") as stream:
            stream.write(record + "\n")
    except BaseException:
        pass


try:
    import hashlib
    import importlib.util
    import json
    import os
    from pathlib import Path
    import subprocess

    # The fake fixture imports ctypes to install OS/file-leaf substitutes.
    # Import the stdlib wrapper before the audit guard; native loads remain denied.
    import ctypes  # noqa: F401
except BaseException as _r11_bootstrap_exc:
    _r11_bootstrap_failure(_r11_bootstrap_exc, "module_imports")
    raise SystemExit(1)


try:
    ROOT = Path(__file__).resolve().parents[1]
    SCRIPT = Path(__file__).resolve()
    RESULT = ROOT / ".codex-tmp/optional16_call_r3_root_focused_qa_result_r11_20261009.json"
except BaseException as _r11_path_setup_exc:
    _r11_bootstrap_failure(_r11_path_setup_exc, "module_path_setup")
    raise SystemExit(1)
QA_SITE = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
CASE = "test_call_r3_uses_exact_v4_source_under_original_root_audit"
DIAGNOSTIC_SCHEMA = "iteration41.optional16.call-r3.root-focused-qa.child-diagnostic.r11"
CREATEPROCESS_SOURCE_PROJECTION = (
    "CPython-3.11.5 _winapi.CreateProcess audit uses format uuu while the second C argument is PyObject*"
)
CREATEPROCESS_ALLOWED_SHAPE = (
    "after one exact Popen event, accept one native tuple of three exact strings: "
    "exact executable, one-character command projection, exact cwd"
)
PARENT_PHASES = frozenset(
    {
        "parent_runtime_validation",
        "parent_module_imports",
        "parent_module_path_setup",
        "parent_argument_validation",
        "parent_unhandled",
        "parent_result_freshness",
        "parent_source_preverify",
        "parent_environment_setup",
        "parent_guard_contract_selfcheck",
        "parent_guard_install",
        "parent_child_launch",
        "parent_child_diagnostic",
        "parent_source_postverify",
        "parent_result_write",
    }
)
CHILD_PHASES = frozenset(
    {
        "child_runtime_validation",
        "child_preload_check",
        "child_guard_install",
        "child_qa_path_add",
        "child_pytest_import",
        "child_pytest_origin_check",
        "child_source_preverify",
        "child_test_module_load",
        "child_focused_case",
        "child_source_postverify",
        "child_guard_postverify",
        "child_complete",
        "child_module_imports",
        "child_module_path_setup",
    }
)
CHILD_BOOTSTRAP_PHASES = frozenset({"child_module_imports", "child_module_path_setup"})
CHILD_MILESTONE_PHASES = (
    ("runtime_validated", "child_runtime_validation"),
    ("preload_checked", "child_preload_check"),
    ("guard_installed", "child_guard_install"),
    ("qa_path_added", "child_qa_path_add"),
    ("pytest_imported", "child_pytest_import"),
    ("pytest_origin_verified", "child_pytest_origin_check"),
    ("source_preverified", "child_source_preverify"),
    ("test_module_loaded", "child_test_module_load"),
    ("focused_case_completed", "child_focused_case"),
    ("source_postverified", "child_source_postverify"),
    ("guard_postverified", "child_guard_postverify"),
    ("child_completed", "child_complete"),
)
CHILD_MILESTONE_NAMES = frozenset(name for name, _phase in CHILD_MILESTONE_PHASES)
SAFE_EXCEPTION_TYPES = frozenset(
    {
        "AssertionError",
        "FileExistsError",
        "FileNotFoundError",
        "ImportError",
        "JSONDecodeError",
        "ModuleNotFoundError",
        "OSError",
        "RuntimeError",
        "TimeoutExpired",
        "ValueError",
        "OtherException",
        "PytestFailed",
        "PytestSkipped",
    }
)
FAILURE_CATEGORIES = frozenset(
    {
        "child_timeout",
        "runtime_contract_failure",
        "source_pin_or_read_failure",
        "result_path_or_write_failure",
        "child_launch_or_guard_failure",
        "child_diagnostic_failure",
        "focused_sourcefake_regression_failure",
        "qa_bootstrap_or_test_load_failure",
        "guard_or_postcondition_failure",
        "phase_failure",
        "module_bootstrap_failure",
        "child_postcondition_failure",
        "child_diagnostic_missing_or_invalid",
        "child_not_started",
        "invalid_invocation",
        "parent_unhandled_failure",
        "script_path_initialization_failure",
    }
)

INPUTS = {
    "scripts/iteration41_optional16_r33_root_preparation_call_r3.py": {
        "size_bytes": 26388,
        "sha256": "fe3a4548ff05bce6beb3b504b9dcbc71fa9a5e5e91be0f154882a9bb50c1b324",
    },
    "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r3_original_audit_source_fake.py": {
        "size_bytes": 9124,
        "sha256": "76eff7d694257f776afe2498ab33f5be35872cb7ff826ae7933868bf69b21f81",
    },
    "scripts/iteration41_optional16_r33_root_preparation_call_r2.py": {
        "size_bytes": 26580,
        "sha256": "f569bf401ee164758000f49bd3c98c0bafd67beda3d3fed05b91fd76c1faf5b2",
    },
    "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r2_source_fake.py": {
        "size_bytes": 12998,
        "sha256": "f4b3bcb2bbf951c2df2b9c37d414bad1aeaa270813b95a98c7db3e3c95690300",
    },
    "scripts/iteration41_optional16_r33_root_preparation_r1.py": {
        "size_bytes": 18324,
        "sha256": "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4",
    },
    "scripts/iteration41_root_held_source_scope_v3.py": {
        "size_bytes": 42252,
        "sha256": "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677",
    },
    "scripts/iteration41_root_held_source_scope_v4.py": {
        "size_bytes": 31692,
        "sha256": "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830",
    },
    ".codex-tmp/optional16_root_preparation_actual_20261009.py": {
        "size_bytes": 9404,
        "sha256": "5fb9fb55fbfbfda43687b6020d40db9653269a422dae5478dc7ede3ee8f7dd35",
    },
    "backtrader_runtime/certification_roundtrip_private.py": {
        "size_bytes": 17537,
        "sha256": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    },
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": {
        "size_bytes": 33887,
        "sha256": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    },
}

PROTECTED_FILES = (
    "backtrader_runtime/certification_roundtrip_private.py",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
    "C:/anaconda3/python.exe",
    "C:/anaconda3/python311.dll",
    "D:/temp/iteration41-root-public-custody-v2.py",
)
SAFE_ENV_KEYS = frozenset(
    {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC", "PYTHONDONTWRITEBYTECODE"}
)
NETWORK_EVENTS = frozenset(
    {
        "socket.__new__",
        "socket.connect",
        "socket.connect_ex",
        "socket.bind",
        "socket.listen",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.sendto",
        "socket.sendmsg",
    }
)
NATIVE_EVENTS = frozenset(
    {
        "ctypes.dlopen",
        "ctypes.dlsym",
        "_ctypes.dlopen",
        "os.add_dll_directory",
        "_winapi.LoadLibrary",
    }
)
PROCESS_EVENTS = frozenset(
    {
        "os.system",
        "os.startfile",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.exec",
        "_winapi.CreateProcess",
    }
)

MODE = "child" if sys.argv[1:] == ["--regression-child"] else "parent"
CHILD_ENV: dict[str, str] | None = None
COUNTS = {
    "private_file_denied": 0,
    "protected_software_denied": 0,
    "sdk_import_denied": 0,
    "network_denied": 0,
    "native_load_denied": 0,
    "unexpected_process_denied": 0,
    "allowed_child_launches": 0,
    "allowed_createprocess_events": 0,
    "createprocess_projection_denied": 0,
}
CREATEPROCESS_PENDING = False


def _norm(value: str) -> str:
    result = value.replace("\\", "/").casefold()
    while result.startswith("//?/"):
        result = result[4:]
    return result


PINNED_PUBLIC_HELPER_SOURCE_PATHS = frozenset(
    _norm(str(ROOT / relative))
    for relative in (
        "backtrader_runtime/certification_roundtrip_private.py",
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
    )
)
PUBLIC_HELPER_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
)


def _is_exact_public_helper_read_open(args: object) -> bool:
    return (
        type(args) is tuple
        and len(args) == 3
        and type(args[1]) is str
        and args[1] == "r"
        and type(args[2]) is int
        and args[2] == PUBLIC_HELPER_READ_FLAGS
    )


TRACEBACK_SOURCE_LABELS = {_norm(str(ROOT / relative)): relative for relative in INPUTS}
TRACEBACK_SOURCE_LABELS[_norm(str(SCRIPT))] = "harness"
TRACEBACK_SOURCE_PATH_LABELS = frozenset(TRACEBACK_SOURCE_LABELS.values())


def _safe_child_guard_counts() -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for name, value in COUNTS.items():
        result[name] = value if type(value) is int and 0 <= value <= 1000000 else None
    return result


def _child_milestones(record: dict[str, object]) -> dict[str, bool]:
    phases = [phase for _name, phase in CHILD_MILESTONE_PHASES]
    last_completed = record.get("last_completed_phase")
    try:
        last_index = phases.index(last_completed)
    except ValueError:
        last_index = -1
    return {
        name: last_index >= index
        for index, (name, _phase) in enumerate(CHILD_MILESTONE_PHASES)
    }


def _safe_traceback_locations(exc: BaseException) -> list[dict[str, object]]:
    locations: list[dict[str, object]] = []
    traceback_node = exc.__traceback__
    depth = 0
    while traceback_node is not None and depth < 64 and len(locations) < 12:
        frame = traceback_node.tb_frame
        code = frame.f_code
        filename = code.co_filename
        label = TRACEBACK_SOURCE_LABELS.get(_norm(filename)) if type(filename) is str else None
        function = code.co_name
        line = traceback_node.tb_lineno
        if (
            label in TRACEBACK_SOURCE_PATH_LABELS
            and type(function) is str
            and 0 < len(function) <= 128
            and all(character.isprintable() for character in function)
            and type(line) is int
            and 0 < line <= 1000000
        ):
            locations.append({"path": label, "function": function, "line": line})
        traceback_node = traceback_node.tb_next
        depth += 1
    return locations


def _pytest_outcome_label(exc: BaseException) -> str | None:
    name = type(exc).__name__
    if name not in {"Failed", "Skipped"}:
        return None
    outcomes_module = sys.modules.get("_pytest.outcomes")
    if outcomes_module is None:
        return None
    label = "PytestFailed" if name == "Failed" else "PytestSkipped"
    expected_type = getattr(outcomes_module, name, None)
    if type(exc) is expected_type and type(exc).__module__ == "_pytest.outcomes":
        return label
    return None


def _safe_exception_type(exc: BaseException) -> str:
    name = type(exc).__name__
    outcome_label = _pytest_outcome_label(exc)
    if outcome_label is not None:
        return outcome_label
    if name in {"PytestFailed", "PytestSkipped"}:
        return "OtherException"
    return name if name in SAFE_EXCEPTION_TYPES else "OtherException"


def _matches_createprocess_projection(args: object) -> bool:
    """Match only the observed CPython 3.11.5 event shape after exact Popen."""
    return (
        type(args) is tuple
        and len(args) == 3
        and type(args[0]) is str
        and args[0] == sys.executable
        and type(args[1]) is str
        and len(args[1]) == 1
        and type(args[2]) is str
        and args[2] == str(ROOT)
    )


def _failure_category(phase: str, exc: BaseException) -> str:
    if _safe_exception_type(exc) == "TimeoutExpired":
        return "child_timeout"
    if phase.endswith("runtime_validation"):
        return "runtime_contract_failure"
    if "source_preverify" in phase or "source_postverify" in phase:
        return "source_pin_or_read_failure"
    if phase in {"parent_result_freshness", "parent_result_write"}:
        return "result_path_or_write_failure"
    if phase == "parent_child_launch":
        return "child_launch_or_guard_failure"
    if phase == "parent_child_diagnostic":
        return "child_diagnostic_failure"
    if phase == "child_focused_case":
        return "focused_sourcefake_regression_failure"
    if "pytest" in phase or phase == "child_test_module_load":
        return "qa_bootstrap_or_test_load_failure"
    if "guard" in phase:
        return "guard_or_postcondition_failure"
    return "phase_failure"


def _mark_phase(record: dict[str, object], phase: str) -> None:
    record["phase"] = phase


def _mark_completed(record: dict[str, object], phase: str) -> None:
    record["last_completed_phase"] = phase


def _set_failure(record: dict[str, object], phase: str, exc: BaseException) -> None:
    record["phase"] = phase
    record["failure_phase"] = phase
    record["exception_type"] = _safe_exception_type(exc)
    record["failure_category"] = _failure_category(phase, exc)


def _deny(counter: str) -> None:
    COUNTS[counter] += 1
    raise RuntimeError("optional16_root_focused_qa_guard_denied")


def _safe_environment() -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        normalized = key.upper()
        if normalized in SAFE_ENV_KEYS and normalized not in result:
            result[normalized] = value
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def _argv() -> list[str]:
    return [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(SCRIPT), "--regression-child"]


def _audit(event: str, args: tuple[object, ...]) -> None:
    global CREATEPROCESS_PENDING
    if event == "open" and args:
        raw_path = args[0]
        if isinstance(raw_path, (str, bytes, os.PathLike)):
            try:
                path_text = os.fsdecode(raw_path)
            except (TypeError, ValueError):
                path_text = ""
            normalized = _norm(path_text)
            if (
                normalized == ".env"
                or normalized.endswith("/.env")
                or normalized in {"config.yaml", "config.yml"}
                or normalized.endswith("/config.yaml")
                or normalized.endswith("/config.yml")
                or "private-capture" in normalized
                or "private_capture" in normalized
            ):
                _deny("private_file_denied")
            for item in PROTECTED_FILES:
                protected = _norm(item)
                absolute = _norm(str(ROOT / item)) if not item.startswith(("C:/", "D:/")) else protected
                # Exact repo-root helper source paths are pinned public inputs, with an exact
                # read-only mode/flags exception. Relative aliases, suffix matches, and writes
                # remain denied, as do all other protected software paths.
                if (
                    normalized == absolute
                    and absolute in PINNED_PUBLIC_HELPER_SOURCE_PATHS
                    and _is_exact_public_helper_read_open(args)
                ):
                    continue
                if normalized == protected or normalized == absolute or normalized.endswith("/" + protected):
                    _deny("protected_software_denied")

    if event == "import" and args and isinstance(args[0], str):
        name = args[0].casefold()
        if name.startswith(("bt_api", "backtrader_runtime", "backtrader", "py_ctp", "vnpy")):
            _deny("sdk_import_denied")

    if event in NETWORK_EVENTS:
        _deny("network_denied")
    if event in NATIVE_EVENTS:
        _deny("native_load_denied")

    if event == "subprocess.Popen":
        if MODE != "parent" or COUNTS["allowed_child_launches"] != 0:
            _deny("unexpected_process_denied")
        if len(args) != 4:
            _deny("unexpected_process_denied")
        executable, command, cwd, environment = args[:4]
        expected_line = subprocess.list2cmdline(_argv())
        if (
            type(executable) is not str
            or executable != sys.executable
            or type(command) is not str
            or command != expected_line
            or type(cwd) is not str
            or cwd != str(ROOT)
            or type(environment) is not dict
            or CHILD_ENV is None
            or environment != CHILD_ENV
        ):
            _deny("unexpected_process_denied")
        COUNTS["allowed_child_launches"] += 1
        CREATEPROCESS_PENDING = True
        return

    if event == "_winapi.CreateProcess":
        if (
            MODE != "parent"
            or COUNTS["allowed_child_launches"] != 1
            or not CREATEPROCESS_PENDING
            or COUNTS["allowed_createprocess_events"] != 0
            or not _matches_createprocess_projection(args)
        ):
            COUNTS["createprocess_projection_denied"] += 1
            _deny("unexpected_process_denied")
        CREATEPROCESS_PENDING = False
        COUNTS["allowed_createprocess_events"] += 1
        return

    if event in PROCESS_EVENTS:
        _deny("unexpected_process_denied")


def _audit_contract_selfcheck() -> int:
    """Exercise the audit matcher with synthetic tuples; never launch a process."""
    global MODE, CHILD_ENV, COUNTS, CREATEPROCESS_PENDING

    saved_mode = MODE
    saved_environment = CHILD_ENV
    saved_counts = COUNTS
    saved_pending = CREATEPROCESS_PENDING
    cases = 0

    def fresh_parent_state() -> None:
        global MODE, CHILD_ENV, COUNTS, CREATEPROCESS_PENDING
        MODE = "parent"
        CHILD_ENV = {"PATH": "synthetic", "PYTHONDONTWRITEBYTECODE": "1"}
        COUNTS = {
            "private_file_denied": 0,
            "protected_software_denied": 0,
            "sdk_import_denied": 0,
            "network_denied": 0,
            "native_load_denied": 0,
            "unexpected_process_denied": 0,
            "allowed_child_launches": 0,
            "allowed_createprocess_events": 0,
            "createprocess_projection_denied": 0,
        }
        CREATEPROCESS_PENDING = False

    def exact_popen_args() -> tuple[object, ...]:
        assert CHILD_ENV is not None
        return (sys.executable, subprocess.list2cmdline(_argv()), str(ROOT), dict(CHILD_ENV))

    def expect_denied(event: str, args: tuple[object, ...]) -> None:
        nonlocal cases
        before = COUNTS["unexpected_process_denied"]
        try:
            _audit(event, args)
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise
        else:
            raise AssertionError("synthetic audit event unexpectedly accepted")
        if COUNTS["unexpected_process_denied"] != before + 1:
            raise AssertionError("synthetic audit denial count mismatch")
        cases += 1

    try:
        # Permit only the exact two repo-root helper sources that V3 pins and
        # reads during its constructor; aliases and suffix matches stay denied.
        for relative in (
            "backtrader_runtime/certification_roundtrip_private.py",
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        ):
            fresh_parent_state()
            before = COUNTS["protected_software_denied"]
            _audit("open", (str(ROOT / relative), "r", PUBLIC_HELPER_READ_FLAGS))
            if COUNTS["protected_software_denied"] != before:
                raise AssertionError("exact_pinned_public_helper_source_was_denied")
            cases += 1

        unsupported_binary_mode = (
            str(ROOT / "backtrader_runtime/certification_roundtrip_private.py"),
            "rb",
            PUBLIC_HELPER_READ_FLAGS,
        )
        fresh_parent_state()
        try:
            _audit("open", unsupported_binary_mode)
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise
        else:
            raise AssertionError("public_helper_binary_audit_mode_was_accepted")
        if COUNTS["protected_software_denied"] != 1:
            raise AssertionError("public_helper_binary_mode_denial_count_mismatch")
        cases += 1

        fresh_parent_state()
        try:
            _audit(
                "open",
                (
                    str(ROOT / "backtrader_runtime/certification_roundtrip_private.py"),
                    "r",
                    PUBLIC_HELPER_READ_FLAGS ^ 1,
                ),
            )
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise
        else:
            raise AssertionError("public_helper_wrong_read_flags_were_accepted")
        if COUNTS["protected_software_denied"] != 1:
            raise AssertionError("public_helper_wrong_flags_denial_count_mismatch")
        cases += 1
        write_modes = (
            (
                "backtrader_runtime/certification_roundtrip_private.py",
                "wb",
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
            ),
            (
                "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
                "r+b",
                os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
            ),
        )
        for relative, mode, flags in write_modes:
            fresh_parent_state()
            try:
                _audit("open", (str(ROOT / relative), mode, flags))
            except RuntimeError as exc:
                if type(exc) is not RuntimeError:
                    raise
            else:
                raise AssertionError("public_helper_write_mode_was_accepted")
            if COUNTS["protected_software_denied"] != 1:
                raise AssertionError("public_helper_write_mode_denial_count_mismatch")
            cases += 1

        fresh_parent_state()
        try:
            _audit(
                "open",
                ("D:/elsewhere/backtrader_runtime/certification_roundtrip_private.py", "r", PUBLIC_HELPER_READ_FLAGS),
            )
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise
        else:
            raise AssertionError("public_helper_source_suffix_alias_was_accepted")
        if COUNTS["protected_software_denied"] != 1:
            raise AssertionError("public_helper_source_alias_denial_count_mismatch")
        cases += 1

        # The one allowed pair binds the full command, executable, cwd and env
        # at subprocess.Popen, then consumes exactly one bounded native event.
        fresh_parent_state()
        _audit("subprocess.Popen", exact_popen_args())
        if not CREATEPROCESS_PENDING or COUNTS["allowed_child_launches"] != 1:
            raise AssertionError("synthetic Popen binding was not recorded")
        _audit("_winapi.CreateProcess", (sys.executable, "x", str(ROOT)))
        if CREATEPROCESS_PENDING or COUNTS["allowed_createprocess_events"] != 1:
            raise AssertionError("synthetic native event was not consumed")
        cases += 1

        # A native event has no allowance without a preceding exact Popen.
        fresh_parent_state()
        expect_denied("_winapi.CreateProcess", (sys.executable, "x", str(ROOT)))

        # The Popen event binds the exact full command and environment.
        for mutation in ("command", "executable", "cwd", "environment"):
            fresh_parent_state()
            args = list(exact_popen_args())
            if mutation == "command":
                args[1] = str(args[1]) + " extra"
            elif mutation == "executable":
                args[0] = str(args[0]) + ".other"
            elif mutation == "cwd":
                args[2] = str(args[2]) + "/other"
            else:
                args[3] = {"PATH": "different"}
            expect_denied("subprocess.Popen", tuple(args))

        # The native projection is restricted to exact executable/cwd and one
        # character, follows the accepted Popen once, and cannot repeat.
        invalid_native_args = (
            ("C:/other/python.exe", "x", str(ROOT)),
            (sys.executable, "", str(ROOT)),
            (sys.executable, "xx", str(ROOT)),
            (sys.executable, "x", str(ROOT) + "/other"),
        )
        for native_args in invalid_native_args:
            fresh_parent_state()
            _audit("subprocess.Popen", exact_popen_args())
            expect_denied("_winapi.CreateProcess", native_args)

        fresh_parent_state()
        _audit("subprocess.Popen", exact_popen_args())
        _audit("_winapi.CreateProcess", (sys.executable, "x", str(ROOT)))
        expect_denied("_winapi.CreateProcess", (sys.executable, "x", str(ROOT)))

        fresh_parent_state()
        _audit("subprocess.Popen", exact_popen_args())
        expect_denied("subprocess.Popen", exact_popen_args())
        return cases
    finally:
        MODE = saved_mode
        CHILD_ENV = saved_environment
        COUNTS = saved_counts
        CREATEPROCESS_PENDING = saved_pending


def _verify_runtime() -> None:
    if (
        os.name != "nt"
        or sys.version_info[:3] != (3, 11, 5)
        or not sys.flags.isolated
        or not sys.flags.no_site
        or sys.flags.utf8_mode != 1
        or not sys.dont_write_bytecode
        or _norm(str(Path(sys.executable).resolve())) != "c:/anaconda3/python.exe"
    ):
        raise RuntimeError("optional16_root_focused_qa_runtime_mismatch")
    if MODE == "child" and not set(os.environ).issubset(SAFE_ENV_KEYS):
        raise RuntimeError("optional16_root_focused_qa_child_environment_mismatch")


def _ensure_no_sdk_modules_loaded() -> None:
    forbidden = ("bt_api", "backtrader_runtime", "backtrader", "py_ctp", "vnpy")
    if any(name.casefold().startswith(forbidden) for name in sys.modules):
        raise RuntimeError("optional16_root_focused_qa_sdk_preload_detected")


class _InertDllFunction:
    def __call__(self, *_args: object, **_kwargs: object) -> int:
        return 0


class _InertDllFacade:
    def __getattr__(self, _name: str) -> _InertDllFunction:
        return _InertDllFunction()


def _install_inert_ctypes_facades() -> None:
    # Colorama can probe Win32 APIs while pytest imports. Keep that bootstrap
    # inert and prevent every route back to the real ctypes DLL loaders.
    inert = _InertDllFacade()
    ctypes.WinDLL = lambda *_args, **_kwargs: inert
    ctypes.OleDLL = lambda *_args, **_kwargs: inert
    ctypes.CDLL = lambda *_args, **_kwargs: inert
    ctypes.windll = inert
    ctypes.oledll = inert
    ctypes.cdll = inert


def _read_exact(relative: str, expected: dict[str, object]) -> bytes:
    path = ROOT / relative
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    if not path.is_file() or attributes & 0x400 or info.st_size != expected["size_bytes"]:
        raise RuntimeError("optional16_root_focused_qa_input_shape_mismatch")
    if info.st_size <= 0 or info.st_size > 256 * 1024:
        raise RuntimeError("optional16_root_focused_qa_input_bound_mismatch")
    with path.open("rb") as stream:
        raw = stream.read(info.st_size + 1)
    if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise RuntimeError("optional16_root_focused_qa_input_pin_mismatch")
    return raw


def _verify_inputs() -> dict[str, bytes]:
    return {relative: _read_exact(relative, expected) for relative, expected in INPUTS.items()}


def _load_test(test_raw: bytes):
    test_path = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r3_original_audit_source_fake.py"
    spec = importlib.util.spec_from_file_location("_optional16_call_r3_original_audit_focus", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("optional16_root_focused_qa_test_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    # Execute precisely the bytes verified above; this is the sole focused case.
    exec(compile(test_raw, str(test_path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _child(record: dict[str, object]) -> int:
    phase = "child_runtime_validation"
    _mark_phase(record, phase)
    _verify_runtime()
    _mark_completed(record, phase)

    phase = "child_preload_check"
    _mark_phase(record, phase)
    _ensure_no_sdk_modules_loaded()
    _mark_completed(record, phase)

    phase = "child_guard_install"
    _mark_phase(record, phase)
    sys.addaudithook(_audit)
    _install_inert_ctypes_facades()
    _mark_completed(record, phase)

    phase = "child_qa_path_add"
    _mark_phase(record, phase)
    # -S excludes site-packages by default. Add only the fixed QA directory
    # after guards; the later origin check is lexical and performs no metadata
    # or realpath probe against the QA path.
    sys.path.insert(0, QA_SITE.as_posix())
    _mark_completed(record, phase)

    phase = "child_pytest_import"
    _mark_phase(record, phase)
    import pytest  # noqa: F401
    _mark_completed(record, phase)

    phase = "child_pytest_origin_check"
    _mark_phase(record, phase)
    pytest_file = getattr(pytest, "__file__", None)
    site_prefix = _norm(QA_SITE.as_posix()).rstrip("/") + "/"
    if not isinstance(pytest_file, str) or not _norm(pytest_file).startswith(site_prefix):
        raise RuntimeError("optional16_root_focused_qa_pytest_origin_mismatch")
    record["qa_origin_verified"] = True
    _mark_completed(record, phase)

    phase = "child_source_preverify"
    _mark_phase(record, phase)
    pinned = _verify_inputs()
    _mark_completed(record, phase)

    phase = "child_test_module_load"
    _mark_phase(record, phase)
    module = _load_test(
        pinned[
            "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r3_original_audit_source_fake.py"
        ]
    )
    _mark_completed(record, phase)

    phase = "child_focused_case"
    _mark_phase(record, phase)
    record["focused_case_entered"] = True
    record["pinned_r1_helper_called"] = False
    module._run_original_audit_case()
    _mark_completed(record, phase)

    phase = "child_source_postverify"
    _mark_phase(record, phase)
    _verify_inputs()
    _mark_completed(record, phase)

    phase = "child_guard_postverify"
    _mark_phase(record, phase)
    if any(COUNTS[key] for key in COUNTS if key.endswith("_denied")):
        raise RuntimeError("optional16_root_focused_qa_guard_postcondition_failed")
    if any(name.startswith(("bt_api", "backtrader_runtime")) for name in sys.modules):
        raise RuntimeError("optional16_root_focused_qa_sdk_postcondition_failed")
    _mark_completed(record, phase)

    phase = "child_complete"
    _mark_phase(record, phase)
    _mark_completed(record, phase)
    return 0


def _emit_child_diagnostic(record: dict[str, object]) -> None:
    phase = record.get("phase")
    if phase not in CHILD_PHASES:
        phase = "child_module_imports"
    last_completed = record.get("last_completed_phase")
    if last_completed not in CHILD_PHASES:
        last_completed = None
    exception_type = record.get("exception_type")
    if exception_type not in SAFE_EXCEPTION_TYPES:
        exception_type = None
    category = record.get("failure_category")
    if category not in FAILURE_CATEGORIES:
        category = None
    payload = {
        "schema": DIAGNOSTIC_SCHEMA,
        "status": "completed" if record.get("status") == "completed" else "failed",
        "phase": phase,
        "last_completed_phase": last_completed,
        "exception_type": exception_type,
        "failure_category": category,
        "focused_case_entered": record.get("focused_case_entered") is True,
        "pinned_r1_helper_called": False,
        "qa_origin_verified": record.get("qa_origin_verified") is True,
        "child_guard_counts": _safe_child_guard_counts(),
        "child_milestones": _child_milestones(record),
        "source_failure_locations": record.get("source_failure_locations", []),
    }
    print(_R11_DIAGNOSTIC_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _valid_child_guard_counts(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == set(COUNTS)
        and all(type(count) is int and 0 <= count <= 1000000 for count in value.values())
    )


def _valid_child_milestones(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == set(CHILD_MILESTONE_NAMES)
        and all(type(completed) is bool for completed in value.values())
    )


def _valid_source_failure_locations(value: object) -> bool:
    if type(value) is not list or len(value) > 12:
        return False
    for row in value:
        if type(row) is not dict or set(row) != {"path", "function", "line"}:
            return False
        function = row["function"]
        path = row["path"]
        line = row["line"]
        if (
            type(path) is not str
            or path not in TRACEBACK_SOURCE_PATH_LABELS
            or type(function) is not str
            or not 0 < len(function) <= 128
            or not all(character.isprintable() for character in function)
            or type(line) is not int
            or not 0 < line <= 1000000
        ):
            return False
    return True


def _invalid_child_diagnostic(status: str) -> dict[str, object]:
    return {
        "diagnostic_status": status,
        "entry_observed": False,
        "phase": "unobserved",
        "last_completed_phase": None,
        "exception_type": None,
        "failure_category": "child_diagnostic_missing_or_invalid",
        "focused_case_entered": False,
        "pinned_r1_helper_called": False,
        "qa_origin_verified": False,
        "child_guard_counts": None,
        "child_milestones": None,
        "source_failure_locations": [],
    }


def _parse_child_diagnostic(stdout: bytes) -> dict[str, object]:
    decoded = stdout.decode("utf-8", errors="replace")
    lines = [line[len(_R11_DIAGNOSTIC_PREFIX) :] for line in decoded.splitlines() if line.startswith(_R11_DIAGNOSTIC_PREFIX)]
    if len(lines) != 1:
        return _invalid_child_diagnostic("missing" if not lines else "multiple_markers")
    try:
        payload = json.loads(lines[0])
    except BaseException:
        payload = None
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "schema",
            "status",
            "phase",
            "last_completed_phase",
            "exception_type",
            "failure_category",
            "focused_case_entered",
            "pinned_r1_helper_called",
            "qa_origin_verified",
            "child_guard_counts",
            "child_milestones",
            "source_failure_locations",
        }
        or payload.get("schema") != DIAGNOSTIC_SCHEMA
        or payload.get("status") not in {"completed", "failed"}
        or payload.get("phase") not in CHILD_PHASES
        or payload.get("last_completed_phase") not in CHILD_PHASES | {None}
        or payload.get("exception_type") not in SAFE_EXCEPTION_TYPES | {None}
        or type(payload.get("focused_case_entered")) is not bool
        or payload.get("failure_category") not in FAILURE_CATEGORIES | {None}
        or type(payload.get("qa_origin_verified")) is not bool
        or payload.get("pinned_r1_helper_called") is not False
        or not _valid_source_failure_locations(payload.get("source_failure_locations"))
    ):
        return _invalid_child_diagnostic("invalid")
    if payload["phase"] in CHILD_BOOTSTRAP_PHASES:
        extra_fields_valid = (
            payload.get("child_guard_counts") is None
            and payload.get("child_milestones") is None
            and payload.get("source_failure_locations") == []
        )
    else:
        extra_fields_valid = _valid_child_guard_counts(payload.get("child_guard_counts")) and _valid_child_milestones(
            payload.get("child_milestones")
        )
    if not extra_fields_valid:
        return _invalid_child_diagnostic("invalid")
    category = payload.get("failure_category")
    if category is not None and not isinstance(category, str):
        category = None
    return {
        "diagnostic_status": "observed",
        "entry_observed": True,
        "status": payload["status"],
        "phase": payload["phase"],
        "last_completed_phase": payload["last_completed_phase"],
        "exception_type": payload["exception_type"],
        "failure_category": category,
        "focused_case_entered": payload["focused_case_entered"],
        "pinned_r1_helper_called": False,
        "qa_origin_verified": payload["qa_origin_verified"],
        "child_guard_counts": payload["child_guard_counts"],
        "child_milestones": payload["child_milestones"],
        "source_failure_locations": payload["source_failure_locations"],
    }


def _write_result(record: dict[str, object]) -> None:
    parent = record.get("parent")
    if isinstance(parent, dict):
        if parent.get("phase") not in PARENT_PHASES:
            parent["phase"] = "parent_unhandled"
        failure_phase = parent.get("failure_phase")
        if failure_phase is not None and failure_phase not in PARENT_PHASES:
            parent["failure_phase"] = "parent_unhandled"
    encoded = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with RESULT.open("xb") as stream:
        stream.write(encoded)


def _write_main_fallback(phase: str, exc: BaseException, category: str) -> None:
    record = {
        "schema": "iteration41.optional16.call-r3.root-focused-qa.r11",
        "status": "FAIL_DIAGNOSTIC_ONLY",
        "evidence_scope": "SOURCE_FAKE_ORIGINAL_AUDIT_REFERENCE_BINDING_WITH_PINNED_PUBLIC_HELPER_BOOTSTRAP_ONLY",
        "parent": {
            "phase": phase,
            "failure_phase": phase,
            "last_completed_phase": None,
            "exception_type": _safe_exception_type(exc),
            "failure_category": category,
            "result_write_attempted": True,
        },
        "child": {
            "launch_state": "not_started",
            "process_returned": False,
            "return_code": None,
            "diagnostic_status": "not_started",
            "entry_observed": False,
            "phase": "unobserved",
            "last_completed_phase": None,
            "exception_type": None,
            "failure_category": "child_not_started",
            "focused_case_entered": False,
            "pinned_r1_helper_called": False,
            "child_guard_counts": None,
            "child_milestones": None,
            "source_failure_locations": [],
            "raw_stdio_included": False,
        },
        "raw_exception_text_included": False,
    }
    try:
        _write_result(record)
    except BaseException:
        pass


def _parent() -> int:
    global CHILD_ENV
    parent = {
        "phase": "parent_runtime_validation",
        "failure_phase": None,
        "last_completed_phase": None,
        "exception_type": None,
        "failure_category": None,
        "result_write_attempted": False,
        "source_preverify_status": "not_attempted",
        "source_postverify_status": "not_attempted",
    }
    child_record: dict[str, object] = {
        "launch_state": "not_started",
        "process_returned": False,
        "return_code": None,
        "diagnostic_status": "not_started",
        "entry_observed": False,
        "phase": "unobserved",
        "last_completed_phase": None,
        "exception_type": None,
        "failure_category": "child_not_started",
        "focused_case_entered": False,
        "pinned_r1_helper_called": False,
        "qa_origin_verified": False,
        "stdout_byte_count": None,
        "stderr_byte_count": None,
        "stdout_nonempty": None,
        "stderr_nonempty": None,
        "child_guard_counts": None,
        "child_milestones": None,
        "source_failure_locations": [],
        "raw_stdio_included": False,
    }
    record: dict[str, object] = {
        "schema": "iteration41.optional16.call-r3.root-focused-qa.r11",
        "status": "FAIL_DIAGNOSTIC_ONLY",
        "evidence_scope": "SOURCE_FAKE_ORIGINAL_AUDIT_REFERENCE_BINDING_WITH_PINNED_PUBLIC_HELPER_BOOTSTRAP_ONLY",
        "case": CASE,
        "head_precheck_required": "5a4b3c0e2664875f8609137b3cf3530e651d8cf8",
        "parent": parent,
        "child": child_record,
        "runtime": {
            "python": "3.11.5",
            "executable": "C:/anaconda3/python.exe",
            "isolated": True,
            "site_disabled": True,
            "utf8_mode": True,
            "bytecode_disabled": True,
        },
        "guarded_qa_bootstrap": {
            "site_packages": "D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages",
            "lexical_pytest_origin_verified_in_child": False,
            "site_path_added_after_guard": True,
            "inert_ctypes_loader_facades_installed_before_pytest": True,
            "qa_path_metadata_probed": False,
        },
        "inputs": INPUTS,
        "synthetic_child": {
            "popen_audit_event_accepted": False,
            "createprocess_audit_event_accepted": False,
            "createprocess_pending_after_attempt": False,
            "createprocess_projection": CREATEPROCESS_SOURCE_PROJECTION,
            "createprocess_allowed_shape": CREATEPROCESS_ALLOWED_SHAPE,
            "raw_stdout_stderr_included": False,
        },
        "guard_contract_selfcheck": {
            "status": "not_run",
            "synthetic_cases": 0,
            "processes_launched": False,
        },
        "guard_counts": COUNTS.copy(),
        "child_diagnostic_contract": {
            "pytest_outcome_identity_only": ["PytestFailed", "PytestSkipped"],
            "traceback_depth_limit": 64,
            "source_frame_limit": 12,
            "source_labels": sorted(TRACEBACK_SOURCE_PATH_LABELS),
            "frame_fields": ["path", "function", "line"],
            "milestone_names": sorted(CHILD_MILESTONE_NAMES),
            "child_guard_count_names": sorted(COUNTS),
            "exception_text_included": False,
            "frame_locals_included": False,
            "raw_child_stdio_included": False,
        },
        "raw_exception_text_included": False,
        "limitations": [
            "The child runs only the exact original-audit reference-binding regression with public source and fake OS/file leaves.",
            "The pinned R1 helper is not reached: the focused test stops at its test_only source-scope refusal before production reread or preparation.",
            "No installer, worker, account, credential, protected software payload, native SDK, network, or actual Root preparation is exercised.",
            "CPython and standard-library bootstrap occur before audit hooks; this finite harness does not claim hostwide native-operation absence.",
            "The QA site path is not statted or resolved; only pytest.__file__ lexical containment under the fixed import root is checked.",
            "If the interpreter fails before script entry or the fixed result path cannot be written, no in-process diagnostic can be guaranteed.",
            "This result cannot establish Optional16 acceptance; formal Optional16 remains 0/16.",
        ],
    }
    passed = False
    result_code = 1
    try:
        _mark_phase(parent, "parent_runtime_validation")
        _verify_runtime()
        _mark_completed(parent, "parent_runtime_validation")

        _mark_phase(parent, "parent_result_freshness")
        if RESULT.exists():
            raise FileExistsError("optional16_root_focused_qa_result_path_not_fresh")
        _mark_completed(parent, "parent_result_freshness")

        _mark_phase(parent, "parent_source_preverify")
        _verify_inputs()
        parent["source_preverify_status"] = "passed"
        _mark_completed(parent, "parent_source_preverify")

        _mark_phase(parent, "parent_guard_contract_selfcheck")
        selfcheck_cases = _audit_contract_selfcheck()
        record["guard_contract_selfcheck"] = {
            "status": "passed",
            "synthetic_cases": selfcheck_cases,
            "processes_launched": False,
        }
        _mark_completed(parent, "parent_guard_contract_selfcheck")

        _mark_phase(parent, "parent_environment_setup")
        _ensure_no_sdk_modules_loaded()
        CHILD_ENV = _safe_environment()
        _mark_completed(parent, "parent_environment_setup")

        _mark_phase(parent, "parent_guard_install")
        sys.addaudithook(_audit)
        _mark_completed(parent, "parent_guard_install")

        _mark_phase(parent, "parent_child_launch")
        child_record["launch_state"] = "call_started_unconfirmed"
        child = subprocess.run(
            _argv(),
            executable=sys.executable,
            cwd=str(ROOT),
            env=CHILD_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        child_record["launch_state"] = "process_returned"
        child_record["process_returned"] = True
        child_record["return_code"] = child.returncode
        child_stdout = child.stdout if isinstance(child.stdout, bytes) else b""
        child_stderr = child.stderr if isinstance(child.stderr, bytes) else b""
        child_record["stdout_byte_count"] = len(child_stdout)
        child_record["stderr_byte_count"] = len(child_stderr)
        child_record["stdout_nonempty"] = bool(child_stdout)
        child_record["stderr_nonempty"] = bool(child_stderr)
        _mark_completed(parent, "parent_child_launch")

        _mark_phase(parent, "parent_child_diagnostic")
        child_record.update(_parse_child_diagnostic(child_stdout))
        _mark_completed(parent, "parent_child_diagnostic")

        _mark_phase(parent, "parent_source_postverify")
        _verify_inputs()
        parent["source_postverify_status"] = "passed"
        _mark_completed(parent, "parent_source_postverify")

        expected_createprocess = 1 if os.name == "nt" else 0
        # Windows emits CreateProcess for this Popen; any other process event is denied.
        passed = (
            child.returncode == 0
            and child_record["diagnostic_status"] == "observed"
            and child_record.get("status") == "completed"
            and COUNTS["allowed_child_launches"] == 1
            and COUNTS["allowed_createprocess_events"] == expected_createprocess
            and not CREATEPROCESS_PENDING
            and record["guard_contract_selfcheck"]["status"] == "passed"
            and not any(COUNTS[key] for key in COUNTS if key.endswith("_denied"))
        )
        record["status"] = "PASS_SOURCE_FAKE_ORIGINAL_AUDIT_REFERENCE_BINDING_WITH_PINNED_PUBLIC_HELPER_BOOTSTRAP_ONLY" if passed else "FAIL_DIAGNOSTIC_ONLY"
        record["guarded_qa_bootstrap"]["lexical_pytest_origin_verified_in_child"] = (
            child_record.get("qa_origin_verified") is True
        )
        record["synthetic_child"] = {
            "popen_audit_event_accepted": COUNTS["allowed_child_launches"] == 1,
            "createprocess_audit_event_accepted": COUNTS["allowed_createprocess_events"] == expected_createprocess,
            "createprocess_pending_after_attempt": CREATEPROCESS_PENDING,
            "createprocess_projection": CREATEPROCESS_SOURCE_PROJECTION,
            "createprocess_allowed_shape": CREATEPROCESS_ALLOWED_SHAPE,
            "raw_stdout_stderr_included": False,
        }
        record["guard_counts"] = COUNTS.copy()
        result_code = 0 if passed else 1
    except BaseException as exc:
        _set_failure(parent, str(parent["phase"]), exc)
        record["status"] = "FAIL_DIAGNOSTIC_ONLY"
        record["guard_counts"] = COUNTS.copy()
        result_code = 1
    finally:
        if parent["source_preverify_status"] == "passed" and parent["source_postverify_status"] != "passed":
            parent["phase"] = "parent_source_postverify"
            try:
                _verify_inputs()
                parent["source_postverify_status"] = "passed"
                _mark_completed(parent, "parent_source_postverify")
            except BaseException as postverify_exc:
                parent["source_postverify_status"] = "failed"
                parent["source_postverify_exception_type"] = _safe_exception_type(postverify_exc)
                parent["source_postverify_failure_category"] = "source_pin_or_read_failure"
                if parent["failure_phase"] is None:
                    _set_failure(parent, "parent_source_postverify", postverify_exc)
                record["status"] = "FAIL_DIAGNOSTIC_ONLY"
                result_code = 1
        parent["phase"] = "parent_result_write"
        parent["result_write_attempted"] = True
        expected_createprocess = 1 if os.name == "nt" else 0
        record["synthetic_child"] = {
            "popen_audit_event_count": COUNTS["allowed_child_launches"],
            "createprocess_audit_event_count": COUNTS["allowed_createprocess_events"],
            "createprocess_count_matches_platform": COUNTS["allowed_createprocess_events"] == expected_createprocess,
            "createprocess_pending_after_attempt": CREATEPROCESS_PENDING,
            "createprocess_projection": CREATEPROCESS_SOURCE_PROJECTION,
            "createprocess_allowed_shape": CREATEPROCESS_ALLOWED_SHAPE,
            "raw_stdout_stderr_included": False,
        }
        record["guard_counts"] = COUNTS.copy()
        try:
            _write_result(record)
        except BaseException as exc:
            # A small fixed fallback is attempted without including exception text.
            fallback = {
                "schema": "iteration41.optional16.call-r3.root-focused-qa.r11",
                "status": "FAIL_DIAGNOSTIC_ONLY",
                "evidence_scope": "SOURCE_FAKE_ORIGINAL_AUDIT_REFERENCE_BINDING_WITH_PINNED_PUBLIC_HELPER_BOOTSTRAP_ONLY",
                "parent": {
                    "phase": "parent_result_write",
                    "failure_phase": "parent_result_write",
                    "last_completed_phase": parent.get("last_completed_phase"),
                    "exception_type": _safe_exception_type(exc),
                    "failure_category": "result_path_or_write_failure",
                    "result_write_attempted": True,
                },
                "child": child_record,
                "raw_exception_text_included": False,
            }
            try:
                with open(RESULT, "xb") as stream:
                    stream.write((json.dumps(fallback, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            except BaseException:
                result_code = 2
    return result_code


def main() -> int:
    if sys.argv[1:] == ["--regression-child"]:
        child_record: dict[str, object] = {
            "status": "running",
            "phase": "child_runtime_validation",
            "last_completed_phase": None,
            "exception_type": None,
            "failure_category": None,
            "focused_case_entered": False,
            "pinned_r1_helper_called": False,
            "qa_origin_verified": False,
            "source_failure_locations": [],
        }
        try:
            result = _child(child_record)
            if result == 0:
                child_record["status"] = "completed"
            else:
                child_record["status"] = "failed"
                if child_record.get("failure_category") is None:
                    child_record["failure_category"] = "child_postcondition_failure"
            return_code = result
        except BaseException as exc:
            _set_failure(child_record, str(child_record["phase"]), exc)
            try:
                child_record["source_failure_locations"] = _safe_traceback_locations(exc)
            except BaseException:
                child_record["source_failure_locations"] = []
            child_record["status"] = "failed"
            return_code = 1
        finally:
            try:
                _emit_child_diagnostic(child_record)
            except BaseException:
                pass
        return return_code
    if sys.argv[1:]:
        _write_main_fallback(
            "parent_argument_validation",
            ValueError("optional16_root_focused_qa_unexpected_arguments"),
            "invalid_invocation",
        )
        return 2
    try:
        return _parent()
    except BaseException as exc:
        _write_main_fallback("parent_unhandled", exc, "parent_unhandled_failure")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
