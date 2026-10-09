"""Unexecuted R17 wrapper for the frozen R8 Root QA source overlay."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
import sys
from pathlib import Path
from uuid import uuid4


ROOT = Path("D:/source_code/backtrader").resolve()
EXPECTED_HEAD = "934e30b55c078a42517c1c758a45eacb09a2b740"
R5_BYTES = 90_345
R5_SHA256 = "111249ab79ada95e60ba0e507a6d54fd9c6a46db763db7055ee03f9e71b291a2"
R6_GENERATED_BYTES = 92_476
R6_GENERATED_SHA256 = "86907f00b0fe558a70bb72fd36893be5b2f4dd16982c3b0c12f32625adcb3d1a"
R7_GENERATED_BYTES = 101_091
R7_GENERATED_SHA256 = "a981e34061bbca44348956b78ebe9d3af1128f6d1a29c3f18c8a66bbfb3bb4c2"
R8_RUNNER_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r8_20261009.py"
R8_RUNNER_BYTES = 14_008
R8_RUNNER_SHA256 = "2d7a9b6eaaf54fc36dd350355f58d802d33ecc716e87c7d3a44d5b71518f759d"
R8_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r8_generated_20261009.py"
R8_GENERATED_BYTES = 101_537
R8_GENERATED_SHA256 = "662a3bd7d739f8af679d21ebbd60d53d7b0f74d7834fa7c63d79de45029072d9"
R13_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r13_generated_20261009.py"
R13_GENERATED_BYTES = 129_507
R13_GENERATED_SHA256 = "49c44842ef362ad667c71dda8fef4ba3a60727af26b17bb0b5f1cd4eed2f2227"
R14_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r14_generated_20261009.py"
R14_GENERATED_BYTES = 133_378
R14_GENERATED_SHA256 = "b443af1b0e6fc86e50eafffc8a3db13ca300b4062a300300a1c5ea70cc4d5055"
R15_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r15_generated_20261009.py"
R15_GENERATED_BYTES = 135_891
R15_GENERATED_SHA256 = "6705a88b5a20a4283a6ecde183195e019b6a8f9805b8aba859bd8b2d1857e8ba"
R16_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r16_generated_20261009.py"
R16_GENERATED_BYTES = 140_383
R16_GENERATED_SHA256 = "cb3cbd2bd670c01bb2d04cf69437ed3d39eae926d8d54253f67d473c4eb13e9a"
R17_GENERATED_PATH = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r17_generated_20261009.py"
R17_GENERATED_BYTES = 146_986
R17_GENERATED_SHA256 = "efb8719f571edee6a8139d6d39d83e099669cc4c7d9f24290b4cd66083fc2c75"
RESULT = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r17_20261009.json"
QA_PREFIX = "D:/bafsr2r17_"
EXPECTED_PYEXPAT_ORIGIN = "c:/anaconda3/dlls/pyexpat.pyd"
EXPECTED_PYEXPAT_BOOTSTRAP_BINDING_RECEIPT = {
    "status": "verified",
    "module_name": "pyexpat",
    "module_type": "types.ModuleType",
    "spec_origin": EXPECTED_PYEXPAT_ORIGIN,
    "loader": "ExtensionFileLoader",
    "child_module_names": ["pyexpat.errors", "pyexpat.model"],
    "child_module_type": "types.ModuleType",
    "child_file": "absent",
    "child_spec": "present_none",
    "parent_attribute_and_sys_modules_identity_checked": True,
    "extension_api_calls_performed": False,
}
EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT = {
    "status": "verified",
    "module_name": "winreg",
    "module_type": "types.ModuleType",
    "spec_origin": "built-in",
    "loader": "BuiltinImporter",
    "function_names": [
        "CloseKey", "ConnectRegistry", "CreateKey", "CreateKeyEx", "DeleteKey",
        "DeleteKeyEx", "DeleteValue", "DisableReflectionKey", "EnableReflectionKey",
        "EnumKey", "EnumValue", "ExpandEnvironmentStrings", "FlushKey", "LoadKey",
        "OpenKey", "OpenKeyEx", "QueryInfoKey", "QueryReflectionKey", "QueryValue",
        "QueryValueEx", "SaveKey", "SetValue", "SetValueEx",
    ],
    "class_bindings": {
        "HKEYType": "builtins.type:PyHKEY",
        "error": "builtins.type:OSError",
    },
    "registry_operation_audit_denied": True,
    "registry_api_calls_performed": False,
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_pinned(path: Path, size: int, sha256: str, label: str) -> tuple[bytes, dict[str, object]]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(label + "_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError(label + "_reparse_point_denied")
    raw = path.read_bytes()
    actual = {"bytes": len(raw), "sha256": _sha(raw)}
    if actual != {"bytes": size, "sha256": sha256}:
        raise RuntimeError(label + "_pin_mismatch")
    return raw, actual


def _pin(path: Path, size: int, sha256: str, label: str) -> dict[str, object]:
    return _read_pinned(path, size, sha256, label)[1]


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("r12_overlay_anchor_mismatch:" + label)
    return source.replace(old, new, 1)


def _build_overlay(source: str) -> str:
    source = _replace_once(
        source,
        '"""Unexecuted Root source-fake diagnostic QA harness for Binance account R2.\n\n'
        'The harness materializes an isolated selected-source namespace from exact clean\n'
        'HEAD blobs, the exact pinned R1/R2/test checkout bytes, and one byte-checked\n'
        'optional ``venue`` parameter hunk in the selected clean runner. It runs only\n'
        'the nine named source-fake tests. Root reviews and executes this draft. This\n'
        'R5 successor preserves exact bounded child output and finite phase/type/category\n'
        'diagnostics. It keeps R4\'s trusted stdlib order, pre-third-party hard guards,\n'
        'pytest-config protection, selected-source closure, and scoped Git/index checks.\n'
        '"""',
        '"""Unexecuted R12 Root source-fake diagnostic QA harness for Binance R2.\n\n'
        'It materializes the exact 19-input selected-source closure and runs the nine\n'
        'named fake tests only. Its selected runner and models overlays derive from\n'
        'clean HEAD blobs. It narrowly validates the canonical built-in winreg module\n'
        'needed by Windows stdlib bootstrap while denying imports and registry audit\n'
        'operations. Root reviews and executes this draft once if approved.\n'
        '"""',
        "r12_generated_docstring",
    )
    model_pin_old = '''    "examples/000_live_certification/binance_penetration/_certification/models.py": {
        "bytes": 6228,
        "sha256": "4f791454c7ced5111178a4ee1edfcd8926409ec20854690ef45af5c2e2d61fa3",
        "origin": "head",
        "materialize": True,
    },'''
    model_pin_new = '''    "examples/000_live_certification/binance_penetration/_certification/models.py": {
        "bytes": 6414,
        "sha256": "bb3ec5d580822500b6dc222df3377a5401441c8855e0923bec7108b4b2807f4e",
        "origin": "head_with_selected_model_hunk",
        "head_bytes": 6228,
        "head_sha256": "4f791454c7ced5111178a4ee1edfcd8926409ec20854690ef45af5c2e2d61fa3",
        "head_blob": "8a058db531726420b761ced7ee6fd37fb084a72d",
        "selected_blob": "010f78626b760a306550028695708d17f95b7f53",
        "materialize": True,
    },'''
    source = _replace_once(source, model_pin_old, model_pin_new, "selected_models_pin")

    runner_anchor = '''RUNNER_SIGNATURE_NEW = b"    currency: str,\\n    venue: str | None = None,\\n) -> ActionPlan:"
'''
    model_constants = '''MODEL_PLANNED_OLD = (
    b"    instrument_spec_id: str | None\\n"
    b"\\n"
    b"\\n"
    b"@dataclass(frozen=True)\\n"
    b"class ActionPlan:"
)
MODEL_PLANNED_NEW = (
    b"    instrument_spec_id: str | None\\n"
    b"    position_side: str | None = None\\n"
    b"    time_in_force: str | None = None\\n"
    b"    request_digest: str | None = None\\n"
    b"\\n"
    b"\\n"
    b"@dataclass(frozen=True)\\n"
    b"class ActionPlan:"
)
MODEL_ORDER_STATE_OLD = (
    b"    remaining: Decimal\\n"
    b"\\n"
    b"\\n"
    b"@dataclass(frozen=True)\\n"
    b"class PositionState:"
)
MODEL_ORDER_STATE_NEW = (
    b"    remaining: Decimal\\n"
    b"    position_side: str | None = None\\n"
    b"    time_in_force: str | None = None\\n"
    b"\\n"
    b"\\n"
    b"@dataclass(frozen=True)\\n"
    b"class PositionState:"
)
'''
    source = _replace_once(
        source,
        runner_anchor,
        runner_anchor + model_constants,
        "selected_models_hunk_constants",
    )

    runner_source_branch_old = '''    elif origin == "head_with_selected_venue_hunk":
        base = _git("show", f"HEAD:{relative}")
        if (
            len(base) != expected["head_bytes"]
            or _sha(base) != expected["head_sha256"]
            or base.count(RUNNER_SIGNATURE_OLD) != 1
        ):
            raise RuntimeError("runner_clean_head_or_hunk_mismatch")
        raw = base.replace(RUNNER_SIGNATURE_OLD, RUNNER_SIGNATURE_NEW, 1)
    else:
'''
    runner_source_branch_new = '''    elif origin == "head_with_selected_venue_hunk":
        base = _git("show", f"HEAD:{relative}")
        if (
            len(base) != expected["head_bytes"]
            or _sha(base) != expected["head_sha256"]
            or base.count(RUNNER_SIGNATURE_OLD) != 1
        ):
            raise RuntimeError("runner_clean_head_or_hunk_mismatch")
        raw = base.replace(RUNNER_SIGNATURE_OLD, RUNNER_SIGNATURE_NEW, 1)
    elif origin == "head_with_selected_model_hunk":
        base = _git("show", f"HEAD:{relative}")
        if (
            len(base) != expected["head_bytes"]
            or _sha(base) != expected["head_sha256"]
            or _git("rev-parse", f"HEAD:{relative}").decode("ascii").strip()
            != expected["head_blob"]
            or _git_blob_id(base) != expected["head_blob"]
            or base.count(MODEL_PLANNED_OLD) != 1
            or base.count(MODEL_ORDER_STATE_OLD) != 1
        ):
            raise RuntimeError("models_clean_head_or_hunk_mismatch")
        raw = base.replace(MODEL_PLANNED_OLD, MODEL_PLANNED_NEW, 1)
        raw = raw.replace(MODEL_ORDER_STATE_OLD, MODEL_ORDER_STATE_NEW, 1)
        if _git_blob_id(raw) != expected["selected_blob"]:
            raise RuntimeError("models_selected_blob_mismatch")
    else:
'''
    source = _replace_once(source, runner_source_branch_old, runner_source_branch_new, "models_source_branch")

    git_blob_anchor = '''def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(*arguments: str) -> bytes:
'''
    git_blob_new = '''def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_blob_id(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\\0"
    return hashlib.sha1(header + raw).hexdigest()


def _git(*arguments: str) -> bytes:
'''
    source = _replace_once(source, git_blob_anchor, git_blob_new, "models_git_blob_check")

    source = _replace_once(
        source,
        '    "WinAPI_pipe_function_denied",\n)\nEXPECTED_EARLY_GUARD_CHECKS = (\n',
        '    "WinAPI_pipe_function_denied",\n    "winreg_registry_operation_audit_denied",\n)\nEXPECTED_EARLY_GUARD_CHECKS = (\n',
        "winreg_full_selfcheck_expected",
    )
    source = _replace_once(
        source,
        '    "windll_load_replaced_by_inert_facade_before_qa_packages",\n)\n'
        'CHILD_TRACE_PREFIX =',
        '    "windll_load_replaced_by_inert_facade_before_qa_packages",\n'
        '    "winreg_canonical_binding_verified_before_qa_packages",\n'
        '    "winreg_forged_module_denied_before_qa_packages",\n'
        '    "winreg_nonbuiltin_origin_denied_before_qa_packages",\n'
        '    "winreg_function_rebinding_denied_before_qa_packages",\n'
        '    "winreg_import_denied_before_qa_packages",\n'
        '    "winreg_operation_audit_denied_before_qa_packages",\n)\n'
        'CHILD_TRACE_PREFIX =',
        "winreg_early_selfcheck_expected",
    )
    source = _replace_once(
        source,
        'CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES = {\n',
        'CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES = {\n'
        '    "winreg_builtin_binding_mismatch",\n',
        "winreg_rejection_category",
    )
    source = _replace_once(
        source,
        '    ("typing.re", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        ')\nEXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS = {\n'
        '    "initial": 4,\n'
        '    "post_stdlib": 4,\n'
        '    "post_qa": 4,\n',
        '    ("typing.re", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        '    ("winreg", "canonical_winreg_builtin_binding"),\n'
        ')\nEXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS = {\n'
        '    "initial": 5,\n'
        '    "post_stdlib": 5,\n'
        '    "post_qa": 5,\n',
        "winreg_scan_allowance_counts",
    )

    winreg_block = r'''_WINREG_FUNCTION_NAMES = (
    "CloseKey", "ConnectRegistry", "CreateKey", "CreateKeyEx", "DeleteKey",
    "DeleteKeyEx", "DeleteValue", "DisableReflectionKey", "EnableReflectionKey",
    "EnumKey", "EnumValue", "ExpandEnvironmentStrings", "FlushKey", "LoadKey",
    "OpenKey", "OpenKeyEx", "QueryInfoKey", "QueryReflectionKey", "QueryValue",
    "QueryValueEx", "SaveKey", "SetValue", "SetValueEx",
)
_WINREG_CLASS_NAMES = ("HKEYType", "error")
_WINREG_PUBLIC_NAMES = frozenset(_WINREG_FUNCTION_NAMES + _WINREG_CLASS_NAMES)


def _winreg_binding_shape(module):
    types_module = sys.modules.get("types")
    if (
        module is None
        or types_module is None
        or type(module) is not types_module.ModuleType
        or sys.modules.get("winreg") is not module
        or getattr(module, "__name__", None) != "winreg"
        or getattr(module, "__file__", None) is not None
    ):
        return None
    spec = getattr(module, "__spec__", None)
    builtin_importer = importlib.machinery.BuiltinImporter
    if (
        type(spec) is not importlib.machinery.ModuleSpec
        or getattr(spec, "name", None) != "winreg"
        or getattr(spec, "origin", None) != "built-in"
        or getattr(spec, "loader", None) is not builtin_importer
        or getattr(module, "__loader__", None) is not builtin_importer
    ):
        return None
    canonical_spec = builtin_importer.find_spec("winreg")
    if (
        type(canonical_spec) is not importlib.machinery.ModuleSpec
        or getattr(canonical_spec, "name", None) != "winreg"
        or getattr(canonical_spec, "origin", None) != "built-in"
        or getattr(canonical_spec, "loader", None) is not builtin_importer
    ):
        return None
    namespace = vars(module)
    public_bindings = {
        name: value
        for name, value in namespace.items()
        if not name.startswith("_")
        and (
            type(value) is types_module.BuiltinFunctionType
            or type(value) is type
        )
    }
    if set(public_bindings) != _WINREG_PUBLIC_NAMES:
        return None
    function_bindings = []
    for name in _WINREG_FUNCTION_NAMES:
        value = public_bindings.get(name)
        if (
            type(value) is not types_module.BuiltinFunctionType
            or getattr(value, "__module__", None) != "winreg"
            or getattr(value, "__name__", None) != name
            or getattr(value, "__qualname__", None) != name
            or getattr(value, "__self__", None) is not module
        ):
            return None
        function_bindings.append((name, value))
    hkey_type = public_bindings.get("HKEYType")
    winreg_error = public_bindings.get("error")
    if (
        type(hkey_type) is not type
        or getattr(hkey_type, "__module__", None) != "builtins"
        or getattr(hkey_type, "__name__", None) != "PyHKEY"
        or getattr(hkey_type, "__qualname__", None) != "PyHKEY"
        or getattr(hkey_type, "__bases__", None) != (object,)
        or winreg_error is not OSError
        or type(winreg_error) is not type
        or getattr(winreg_error, "__module__", None) != "builtins"
        or getattr(winreg_error, "__name__", None) != "OSError"
        or getattr(winreg_error, "__qualname__", None) != "OSError"
    ):
        return None
    return (
        module,
        spec,
        builtin_importer,
        tuple(function_bindings),
        (("HKEYType", hkey_type), ("error", winreg_error)),
    )


_WINREG_BOOTSTRAP_BINDING = _winreg_binding_shape(sys.modules.get("winreg"))


def _winreg_binding_is_live(name, module):
    if name != "winreg" or module is None or sys.modules.get("winreg") is not module:
        return False
    held = _WINREG_BOOTSTRAP_BINDING
    current = _winreg_binding_shape(module)
    if held is None or current is None:
        return False
    if current[0] is not held[0] or current[1] is not held[1] or current[2] is not held[2]:
        return False
    return (
        len(current[3]) == len(held[3])
        and all(
            current_name == held_name and current_value is held_value
            for (current_name, current_value), (held_name, held_value)
            in zip(current[3], held[3])
        )
        and len(current[4]) == len(held[4])
        and all(
            current_name == held_name and current_value is held_value
            for (current_name, current_value), (held_name, held_value)
            in zip(current[4], held[4])
        )
    )


_WINREG_BOOTSTRAP_RECEIPT = {
    "status": "verified",
    "module_name": "winreg",
    "module_type": "types.ModuleType",
    "spec_origin": "built-in",
    "loader": "BuiltinImporter",
    "function_names": list(_WINREG_FUNCTION_NAMES),
    "class_bindings": {
        "HKEYType": "builtins.type:PyHKEY",
        "error": "builtins.type:OSError",
    },
    "registry_operation_audit_denied": True,
    "registry_api_calls_performed": False,
}


'''
    source = _replace_once(
        source,
        '_typing_deprecated_type = getattr(_typing_module, "_DeprecatedType", None)\n\n',
        '_typing_deprecated_type = getattr(_typing_module, "_DeprecatedType", None)\n\n'
        + winreg_block,
        "winreg_binding_helpers",
    )

    source = _replace_once(
        source,
        'def _origin_scan_rejection_category(name, origin):\n'
        '    if name == "__mp_main__":\n',
        'def _origin_scan_rejection_category(name, origin):\n'
        '    if name == "winreg":\n'
        '        return "winreg_builtin_binding_mismatch"\n'
        '    if name == "__mp_main__":\n',
        "winreg_rejection_category_function",
    )

    source = _replace_once(
        source,
        '    if _origin_scan_typing_alias_is_live(name, module):\n'
        '        return "typing_deprecated_type_alias_at_trusted_typing_origin"\n'
        '    return None\n',
        '    if _winreg_binding_is_live(name, module):\n'
        '        return "canonical_winreg_builtin_binding"\n'
        '    if _origin_scan_typing_alias_is_live(name, module):\n'
        '        return "typing_deprecated_type_alias_at_trusted_typing_origin"\n'
        '    return None\n',
        "winreg_rescan_category",
    )

    initial_scan_anchor = '''    if _name in {"typing.io", "typing.re"}:
        _alias_name = _name.rsplit(".", 1)[1]
        if _origin_scan_typing_alias_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": _name,
                    "origin_category": "typing_deprecated_type_alias_at_trusted_typing_origin",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
    if _boot_origin_is_trusted(_origin):
'''
    initial_scan_new = '''    if _name in {"typing.io", "typing.re"}:
        _alias_name = _name.rsplit(".", 1)[1]
        if _origin_scan_typing_alias_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": _name,
                    "origin_category": "typing_deprecated_type_alias_at_trusted_typing_origin",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
    if _name == "winreg":
        if _winreg_binding_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": "winreg",
                    "origin_category": "canonical_winreg_builtin_binding",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
        _record_preloaded_origin_rejection(_name, _origin)
    if _boot_origin_is_trusted(_origin):
'''
    source = _replace_once(source, initial_scan_anchor, initial_scan_new, "winreg_initial_allowance")

    source = _replace_once(
        source,
        '        and name.partition(".")[0].casefold() != "_winapi"\n',
        '        and name.partition(".")[0].casefold() != "_winapi"\n'
        '        and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))\n',
        "winreg_early_private_root_filter",
    )
    source = _replace_once(
        source,
        '    forbidden_preload = [name for name in forbidden_preload if name != "_winapi"]\n',
        '    forbidden_preload = [\n'
        '        name for name in forbidden_preload\n'
        '        if name != "_winapi"\n'
        '        and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))\n'
        '    ]\n',
        "winreg_post_qa_private_root_filter",
    )
    source = _replace_once(
        source,
        '        forbidden_loaded = [name for name in forbidden_loaded if name != "_winapi"]\n',
        '        forbidden_loaded = [\n'
        '            name for name in forbidden_loaded\n'
        '            if name != "_winapi"\n'
        '            and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))\n'
        '        ]\n',
        "winreg_final_private_root_filter",
    )

    source = _replace_once(
        source,
        'def audit(event, args):\n'
        '    if event == "import" and args:\n',
        'def audit(event, args):\n'
        '    if isinstance(event, str) and event.startswith("winreg."):\n'
        '        deny("blocked_winreg_operation")\n'
        '    if event == "import" and args:\n',
        "winreg_registry_audit_denial",
    )
    source = _replace_once(
        source,
        '        "winreg.OpenKey", "_winapi.CreateProcess", "_winapi.CreatePipe",\n',
        '        "_winapi.CreateProcess", "_winapi.CreatePipe",\n',
        "remove_single_winreg_event",
    )
    source = _replace_once(
        source,
        '    checks.append("windll_load_replaced_by_inert_facade_before_qa_packages")\n'
        '    expected = (\n',
        '''    checks.append("windll_load_replaced_by_inert_facade_before_qa_packages")
    _winreg_module = sys.modules.get("winreg")
    if not _winreg_binding_is_live("winreg", _winreg_module):
        raise RuntimeError("winreg_bootstrap_binding_not_live")
    checks.append("winreg_canonical_binding_verified_before_qa_packages")
    _winreg_fake = types.ModuleType("winreg")
    try:
        sys.modules["winreg"] = _winreg_fake
        _winreg_forged_module_rejected = not _winreg_binding_is_live("winreg", _winreg_fake)
    finally:
        sys.modules["winreg"] = _winreg_module
    if not _winreg_forged_module_rejected:
        raise RuntimeError("winreg_forged_module_accepted")
    checks.append("winreg_forged_module_denied_before_qa_packages")
    _winreg_spec = _winreg_module.__spec__
    _winreg_origin = _winreg_spec.origin
    try:
        _winreg_spec.origin = "C:/opaque/forged_winreg.py"
        _winreg_wrong_origin_rejected = not _winreg_binding_is_live("winreg", _winreg_module)
    finally:
        _winreg_spec.origin = _winreg_origin
    if not _winreg_wrong_origin_rejected:
        raise RuntimeError("winreg_nonbuiltin_origin_accepted")
    checks.append("winreg_nonbuiltin_origin_denied_before_qa_packages")
    _winreg_open_key = _winreg_module.OpenKey
    try:
        _winreg_module.OpenKey = _winreg_module.CloseKey
        _winreg_rebound_function_rejected = not _winreg_binding_is_live("winreg", _winreg_module)
    finally:
        _winreg_module.OpenKey = _winreg_open_key
    if not _winreg_rebound_function_rejected:
        raise RuntimeError("winreg_function_rebinding_accepted")
    checks.append("winreg_function_rebinding_denied_before_qa_packages")
    expect(
        "winreg_import_denied_before_qa_packages",
        lambda: sys.audit("import", "winreg.source_qa_probe", None),
    )
    expect(
        "winreg_operation_audit_denied_before_qa_packages",
        lambda: sys.audit("winreg.OpenKey", None),
    )
    expected = (
''',
        "winreg_early_selfcheck_body",
    )
    source = _replace_once(
        source,
        '        "windll_load_replaced_by_inert_facade_before_qa_packages",\n'
        '    )\n'
        '    if tuple(checks) != expected:\n',
        '        "windll_load_replaced_by_inert_facade_before_qa_packages",\n'
        '        "winreg_canonical_binding_verified_before_qa_packages",\n'
        '        "winreg_forged_module_denied_before_qa_packages",\n'
        '        "winreg_nonbuiltin_origin_denied_before_qa_packages",\n'
        '        "winreg_function_rebinding_denied_before_qa_packages",\n'
        '        "winreg_import_denied_before_qa_packages",\n'
        '        "winreg_operation_audit_denied_before_qa_packages",\n'
        '    )\n'
        '    if tuple(checks) != expected:\n',
        "winreg_early_selfcheck_expected_order",
    )
    source = _replace_once(
        source,
        '    expect("WinAPI_pipe_function_denied", lambda: winapi.CreatePipe())\n'
        '    if tuple(SELF_CHECKS_DONE) != tuple(EXPECTED_SELF_CHECKS):\n',
        '    expect("WinAPI_pipe_function_denied", lambda: winapi.CreatePipe())\n'
        '    expect("winreg_registry_operation_audit_denied", lambda: sys.audit("winreg.OpenKey", None))\n'
        '    if tuple(SELF_CHECKS_DONE) != tuple(EXPECTED_SELF_CHECKS):\n',
        "winreg_full_selfcheck_body",
    )
    source = _replace_once(
        source,
        '        "forbidden_modules_absent_before_guard_install": not forbidden_before_qa,\n',
        '        "forbidden_modules_absent_before_guard_install": not forbidden_before_qa,\n'
        '        "winreg_bootstrap_binding": dict(_WINREG_BOOTSTRAP_RECEIPT),\n',
        "winreg_preloader_receipt",
    )
    source = _replace_once(
        source,
        '        "preloader": preload,\n',
        '        "preloader": preload,\n'
        '        "winreg_bootstrap_binding": preload.get("winreg_bootstrap_binding"),\n',
        "winreg_summary_receipt",
    )

    source = _replace_once(
        source,
        '        "r8_overlay_source": {\n'
        '            "bytes": R8_OVERLAY_BYTES,\n'
        '            "sha256": R8_OVERLAY_SHA256,\n'
        '            "base_r7_generated_bytes": R7_GENERATED_BYTES,\n'
        '            "base_r7_generated_sha256": R7_GENERATED_SHA256,\n'
        '        },\n',
        '        "r12_overlay_source": {\n'
        '            "bytes": R12_OVERLAY_BYTES,\n'
        '            "sha256": R12_OVERLAY_SHA256,\n'
        '            "base_r8_generated_bytes": R8_GENERATED_BYTES,\n'
        '            "base_r8_generated_sha256": R8_GENERATED_SHA256,\n'
        '        },\n',
        "r12_overlay_receipt",
    )
    source = _replace_once(
        source,
        '                "selected_sha256": PINS[RUNNER_RELATIVE]["sha256"],\n'
        '            },\n'
        '            "dirty_models_config_backends_runner_excluded": True,\n',
        '                "selected_sha256": PINS[RUNNER_RELATIVE]["sha256"],\n'
        '            },\n'
        '            "model_change": {\n'
        '                "relative_path": "examples/000_live_certification/binance_penetration/_certification/models.py",\n'
        '                "change": "five defaulted read-action fields from the frozen clean HEAD blob",\n'
        '                "base_head_bytes": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_bytes"],\n'
        '                "base_head_sha256": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_sha256"],\n'
        '                "base_head_blob": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_blob"],\n'
        '                "selected_bytes": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["bytes"],\n'
        '                "selected_sha256": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["sha256"],\n'
        '                "selected_blob": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["selected_blob"],\n'
        '            },\n'
        '            "selected_source_origins": {\n'
        '                RUNNER_RELATIVE: PINS[RUNNER_RELATIVE]["origin"],\n'
        '                "examples/000_live_certification/binance_penetration/_certification/models.py": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["origin"],\n'
        '            },\n'
        '            "expected_test_entry_count": len(EXPECTED_TEST_NAMES),\n'
        '            "expected_test_names": list(EXPECTED_TEST_NAMES),\n'
        '            "dirty_models_config_backends_runner_excluded": True,\n',
        "r12_selected_origins_and_test_count",
    )
    source = _replace_once(
        source,
        '        "expected_case_count": 9,\n'
        '        "exact_nine_passed": exact_nine,\n',
        '        "expected_case_count": 9,\n'
        '        "focused_test_entries": {\n'
        '            "expected": len(EXPECTED_TEST_NAMES),\n'
        '            "collected": child_summary.get("collected") if child_summary else None,\n'
        '            "passed_call_reports": child_summary.get("passed_call_reports") if child_summary else None,\n'
        '        },\n'
        '        "exact_nine_passed": exact_nine,\n',
        "r12_exact_test_entry_count",
    )
    source = _replace_once(
        source,
        '    and child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("scan_allowance_counts")\n'
        '        == EXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS\n',
        '    and child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("scan_allowance_counts")\n'
        '        == EXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS\n'
        '        and child_summary.get("preloader", {}).get("winreg_bootstrap_binding")\n'
        '        == EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT\n',
        "winreg_parent_receipt_gate",
    )

    source = _replace_once(
        source,
        'CHILD_TRACE_PREFIX = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R8_TRACE:"\n',
        'CHILD_TRACE_PREFIX = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R8_TRACE:"\n',
        "r12_trace_prefix_anchor",
    )
    replacements = (
        ("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R8_SCAN_REJECTED", "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R12_SCAN_REJECTED", "r12_scan_prefix"),
        ("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R8_TRACE", "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R12_TRACE", "r12_trace_prefix"),
        ("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R8", "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R12", "r12_summary_prefix"),
        ("binance_account_full_r2_root_source_qa_r8_20261009.json", "binance_account_full_r2_root_source_qa_r12_20261009.json", "r12_result_path"),
        ("D:/bafsr2r8_", "D:/bafsr2r12_", "r12_qa_prefix"),
        ("iteration41.binance.th01.account_full_snapshot_r2.root_source_qa.r8", "iteration41.binance.th01.account_full_snapshot_r2.root_source_qa.r12", "r12_schema"),
    )
    for old, new, label in replacements:
        if old not in source:
            raise RuntimeError("r12_overlay_version_anchor_mismatch:" + label)
        source = source.replace(old, new)
    source = _replace_once(
        source,
        '    "pickle", "re", "types", "typing", "urllib.parse", "uuid", "weakref",\n',
        '    "pickle", "re", "struct", "types", "typing", "unicodedata", "urllib.parse", "uuid", "weakref",\n',
        "r12_unicodedata_preload",
    )
    source = _replace_once(
        source,
        '    "stat", "sysconfig", "time", "warnings",\n',
        '    "stat", "sysconfig", "time", "warnings", "bisect", "faulthandler",\n'
        '    "xml.etree.ElementTree",\n',
        "r12_pytest_stdlib_dependency_preloads",
    )
    return source


def _build_r13_overlay(source: str) -> str:
    """Add the exact pyexpat bootstrap identity checks to the frozen R12 overlay."""
    source = _replace_once(
        source,
        '    "xml.etree.ElementTree",\n',
        '    "pyexpat",\n    "xml.etree.ElementTree",\n',
        "r13_explicit_pyexpat_preload",
    )
    source = _replace_once(
        source,
        '_stdlib_origins = {}\n_trace("trusted_stdlib_origin_preload", "start")\n',
        '_stdlib_origins = {}\n_PYEXPAT_IMPORTED_PARENT = None\n'
        '_trace("trusted_stdlib_origin_preload", "start")\n',
        "r13_initialize_pyexpat_parent_binding",
    )
    source = _replace_once(
        source,
        '    _stdlib_origins[_name] = str(_origin or "built-in-or-frozen")\n',
        '    _stdlib_origins[_name] = str(_origin or "built-in-or-frozen")\n'
        '    if _name == "pyexpat":\n'
        '        if _PYEXPAT_IMPORTED_PARENT is not None:\n'
        '            raise RuntimeError("pyexpat_import_binding_duplicate")\n'
        '        _PYEXPAT_IMPORTED_PARENT = _module\n',
        "r13_capture_imported_pyexpat_parent",
    )
    source = _replace_once(
        source,
        'CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES = {\n'
        '    "winreg_builtin_binding_mismatch",\n',
        'CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES = {\n'
        '    "winreg_builtin_binding_mismatch",\n'
        '    "pyexpat_synthetic_child_binding_mismatch",\n',
        "r13_pyexpat_rejection_category_inventory",
    )
    source = _replace_once(
        source,
        'EXPECTED_PRELOADED_MODULE_ORIGIN_ALLOWANCES = (\n'
        '    ("__main__", "main_module_at_pinned_child_origin"),\n'
        '    ("__mp_main__", "same_object_main_alias_at_pinned_child_origin"),\n'
        '    ("typing.io", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        '    ("typing.re", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        '    ("winreg", "canonical_winreg_builtin_binding"),\n'
        ')\nEXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS = {\n'
        '    "initial": 5,\n'
        '    "post_stdlib": 5,\n'
        '    "post_qa": 5,\n'
        '}\n',
        'EXPECTED_PRELOADED_MODULE_ORIGIN_ALLOWANCES = (\n'
        '    ("__main__", "main_module_at_pinned_child_origin"),\n'
        '    ("__mp_main__", "same_object_main_alias_at_pinned_child_origin"),\n'
        '    ("pyexpat.errors", "synthetic_child_of_canonical_pyexpat_extension"),\n'
        '    ("pyexpat.model", "synthetic_child_of_canonical_pyexpat_extension"),\n'
        '    ("typing.io", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        '    ("typing.re", "typing_deprecated_type_alias_at_trusted_typing_origin"),\n'
        '    ("winreg", "canonical_winreg_builtin_binding"),\n'
        ')\nEXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS = {\n'
        '    "initial": 7,\n'
        '    "post_stdlib": 7,\n'
        '    "post_qa": 7,\n'
        '}\n',
        "r13_pyexpat_scan_allowances_and_counts",
    )

    pyexpat_helpers = r'''_PYEXPAT_CHILD_BINDINGS = (
    ("pyexpat.errors", "errors"),
    ("pyexpat.model", "model"),
)
_PYEXPAT_CHILD_MODULE_NAMES = frozenset(name for name, _attribute in _PYEXPAT_CHILD_BINDINGS)
_PYEXPAT_EXPECTED_ORIGIN = _boot_norm(
    sys.base_prefix.rstrip("/\\") + "/DLLs/pyexpat.pyd"
)


def _pyexpat_snapshot_candidate():
    parent = _PYEXPAT_IMPORTED_PARENT
    types_module = sys.modules.get("types")
    machinery_module = importlib.machinery
    module_spec_type = getattr(machinery_module, "ModuleSpec", None)
    extension_loader_type = getattr(machinery_module, "ExtensionFileLoader", None)
    if (
        parent is None
        or types_module is None
        or type(types_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(types_module))
        or _boot_norm(_stdlib_origins.get("types", ""))
        != _boot_norm(_boot_origin(types_module))
        or sys.modules.get("importlib.machinery") is not machinery_module
        or type(machinery_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(machinery_module))
        or module_spec_type is not importlib.machinery.ModuleSpec
        or extension_loader_type is not importlib.machinery.ExtensionFileLoader
        or type(parent) is not types_module.ModuleType
        or sys.modules.get("pyexpat") is not parent
        or getattr(parent, "__name__", None) != "pyexpat"
    ):
        return None
    expected_origin = _PYEXPAT_EXPECTED_ORIGIN
    if (
        not isinstance(expected_origin, str)
        or expected_origin != PYEXPAT_ORIGIN_TEXT.casefold()
        or not any(
            _boot_under(expected_origin, root)
            and _boot_norm(root).endswith("/dlls")
            for root in _boot_roots
        )
        or not _boot_origin_is_trusted(expected_origin)
    ):
        return None
    parent_file = getattr(parent, "__file__", None)
    spec = getattr(parent, "__spec__", None)
    loader = getattr(parent, "__loader__", None)
    if (
        not isinstance(parent_file, str)
        or _boot_norm(parent_file) != expected_origin
        or type(spec) is not module_spec_type
        or getattr(spec, "name", None) != "pyexpat"
        or not isinstance(getattr(spec, "origin", None), str)
        or _boot_norm(spec.origin) != expected_origin
        or type(loader) is not extension_loader_type
        or getattr(spec, "loader", None) is not loader
        or getattr(loader, "name", None) != "pyexpat"
        or not isinstance(getattr(loader, "path", None), str)
        or _boot_norm(loader.path) != expected_origin
        or _boot_norm(_stdlib_origins.get("pyexpat", "")) != expected_origin
    ):
        return None
    children = []
    parent_namespace = vars(parent)
    for module_name, attribute in _PYEXPAT_CHILD_BINDINGS:
        child = sys.modules.get(module_name)
        if (
            child is None
            or type(child) is not types_module.ModuleType
            or parent_namespace.get(attribute) is not child
        ):
            return None
        child_namespace = vars(child)
        if (
            child_namespace.get("__name__") != module_name
            or "__file__" in child_namespace
            or "__spec__" not in child_namespace
            or child_namespace["__spec__"] is not None
        ):
            return None
        children.append((module_name, attribute, child, module_name, False, True, None, None))
    return (
        parent,
        spec,
        loader,
        expected_origin,
        tuple(children),
        types_module,
        machinery_module,
        module_spec_type,
        extension_loader_type,
    )


def _pyexpat_snapshot_matches(snapshot):
    if not isinstance(snapshot, tuple) or len(snapshot) != 9:
        return False
    (
        parent, expected_spec, expected_loader, expected_origin, children,
        expected_types_module, expected_machinery_module,
        expected_module_spec_type, expected_extension_loader_type,
    ) = snapshot
    types_module = sys.modules.get("types")
    if (
        types_module is None
        or types_module is not expected_types_module
        or type(types_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(types_module))
        or _boot_norm(_stdlib_origins.get("types", ""))
        != _boot_norm(_boot_origin(types_module))
        or sys.modules.get("importlib.machinery") is not expected_machinery_module
        or importlib.machinery is not expected_machinery_module
        or type(expected_machinery_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(expected_machinery_module))
        or getattr(expected_machinery_module, "ModuleSpec", None)
        is not expected_module_spec_type
        or getattr(expected_machinery_module, "ExtensionFileLoader", None)
        is not expected_extension_loader_type
        or type(parent) is not types_module.ModuleType
        or parent is not _PYEXPAT_IMPORTED_PARENT
        or sys.modules.get("pyexpat") is not parent
        or getattr(parent, "__name__", None) != "pyexpat"
        or getattr(parent, "__file__", None) is None
        or _boot_norm(parent.__file__) != expected_origin
        or expected_origin != _PYEXPAT_EXPECTED_ORIGIN
        or expected_origin != PYEXPAT_ORIGIN_TEXT.casefold()
        or not _boot_origin_is_trusted(expected_origin)
        or not any(
            _boot_under(expected_origin, root)
            and _boot_norm(root).endswith("/dlls")
            for root in _boot_roots
        )
        or _boot_norm(_stdlib_origins.get("pyexpat", "")) != expected_origin
        or getattr(parent, "__spec__", None) is not expected_spec
        or type(expected_spec) is not expected_module_spec_type
        or getattr(expected_spec, "name", None) != "pyexpat"
        or getattr(expected_spec, "origin", None) is None
        or _boot_norm(expected_spec.origin) != expected_origin
        or getattr(parent, "__loader__", None) is not expected_loader
        or getattr(expected_spec, "loader", None) is not expected_loader
        or type(expected_loader) is not expected_extension_loader_type
        or getattr(expected_loader, "name", None) != "pyexpat"
        or getattr(expected_loader, "path", None) is None
        or _boot_norm(expected_loader.path) != expected_origin
        or not isinstance(children, tuple)
        or len(children) != len(_PYEXPAT_CHILD_BINDINGS)
    ):
        return False
    parent_namespace = vars(parent)
    for expected, (module_name, attribute) in zip(children, _PYEXPAT_CHILD_BINDINGS):
        if not isinstance(expected, tuple) or len(expected) != 8:
            return False
        (
            expected_name, expected_attribute, child, child_name,
            child_file_present, child_spec_present, child_file, child_spec,
        ) = expected
        current = sys.modules.get(module_name)
        if (
            expected_name != module_name
            or expected_attribute != attribute
            or child_name != module_name
            or child_file_present is not False
            or child_spec_present is not True
            or child_file is not None
            or child_spec is not None
            or current is not child
            or parent_namespace.get(attribute) is not child
            or type(child) is not types_module.ModuleType
        ):
            return False
        child_namespace = vars(child)
        if (
            child_namespace.get("__name__") != child_name
            or ("__file__" in child_namespace) is not child_file_present
            or ("__spec__" in child_namespace) is not child_spec_present
            or child_namespace.get("__file__") is not child_file
            or child_namespace.get("__spec__") is not child_spec
        ):
            return False
    return True


_PYEXPAT_EXPECTED_BINDING = _pyexpat_snapshot_candidate()


def _pyexpat_binding_is_live(_snapshot=_PYEXPAT_EXPECTED_BINDING):
    return (
        _snapshot is not None
        and _pyexpat_snapshot_matches(_snapshot)
    )


def _pyexpat_child_binding_is_live(
    name, module, _snapshot=_PYEXPAT_EXPECTED_BINDING,
    _binding_check=_pyexpat_binding_is_live,
):
    if name not in _PYEXPAT_CHILD_MODULE_NAMES or not _binding_check():
        return False
    for expected in _snapshot[4]:
        if expected[0] == name:
            return module is expected[2]
    return False


_PYEXPAT_BOOTSTRAP_RECEIPT = {
    "status": "verified",
    "module_name": "pyexpat",
    "module_type": "types.ModuleType",
    "spec_origin": _PYEXPAT_EXPECTED_ORIGIN,
    "loader": "ExtensionFileLoader",
    "child_module_names": ["pyexpat.errors", "pyexpat.model"],
    "child_module_type": "types.ModuleType",
    "child_file": "absent",
    "child_spec": "present_none",
    "parent_attribute_and_sys_modules_identity_checked": True,
    "extension_api_calls_performed": False,
}


'''
    source = _replace_once(
        source,
        'def _origin_scan_rejection_category(name, origin):\n',
        pyexpat_helpers + 'def _origin_scan_rejection_category(name, origin):\n',
        "r13_pyexpat_binding_helpers",
    )
    source = _replace_once(
        source,
        'def _origin_scan_rejection_category(name, origin):\n'
        '    if name == "winreg":\n',
        'def _origin_scan_rejection_category(name, origin):\n'
        '    if name in _PYEXPAT_CHILD_MODULE_NAMES:\n'
        '        return "pyexpat_synthetic_child_binding_mismatch"\n'
        '    if name == "winreg":\n',
        "r13_pyexpat_rejection_category_function",
    )
    source = _replace_once(
        source,
        '    if _winreg_binding_is_live(name, module):\n'
        '        return "canonical_winreg_builtin_binding"\n',
        '    if _pyexpat_child_binding_is_live(name, module):\n'
        '        return "synthetic_child_of_canonical_pyexpat_extension"\n'
        '    if _winreg_binding_is_live(name, module):\n'
        '        return "canonical_winreg_builtin_binding"\n',
        "r13_pyexpat_rescan_category",
    )
    source = _replace_once(
        source,
        '    if _name in {"typing.io", "typing.re"}:\n',
        '    if _name in _PYEXPAT_CHILD_MODULE_NAMES:\n'
        '        if _pyexpat_child_binding_is_live(_name, _module):\n'
        '            _preloaded_module_origin_scan_allowances.append(\n'
        '                {\n'
        '                    "module_name": _name,\n'
        '                    "origin_category": "synthetic_child_of_canonical_pyexpat_extension",\n'
        '                }\n'
        '            )\n'
        '            _preloaded_module_origin_scan_counts["initial"] += 1\n'
        '            continue\n'
        '        _record_preloaded_origin_rejection(_name, _origin)\n'
        '    if _name in {"typing.io", "typing.re"}:\n',
        "r13_pyexpat_initial_scan_allowance",
    )
    source = _replace_once(
        source,
        '    raise RuntimeError("preloaded_module_origin_not_trusted")\n\n'
        'for _name, _module in tuple(sys.modules.items()):\n',
        '    raise RuntimeError("preloaded_module_origin_not_trusted")\n\n'
        'if not _pyexpat_binding_is_live():\n'
        '    _record_preloaded_origin_rejection("pyexpat.errors", None)\n\n'
        'for _name, _module in tuple(sys.modules.items()):\n',
        "r13_pyexpat_initial_snapshot_validation",
    )

    source = _replace_once(
        source,
        '    expect(\n'
        '        "winreg_operation_audit_denied_before_qa_packages",\n'
        '        lambda: sys.audit("winreg.OpenKey", None),\n'
        '    )\n'
        '    expected = (\n',
        '    expect(\n'
        '        "winreg_operation_audit_denied_before_qa_packages",\n'
        '        lambda: sys.audit("winreg.OpenKey", None),\n'
        '    )\n'
        '    if not _pyexpat_binding_is_live():\n'
        '        raise RuntimeError("pyexpat_bootstrap_binding_not_live")\n'
        '    checks.append("pyexpat_canonical_parent_and_children_verified_before_qa_packages")\n'
        '    _pyexpat_fake_child = types.ModuleType("pyexpat.errors")\n'
        '    _pyexpat_original_child = sys.modules["pyexpat.errors"]\n'
        '    try:\n'
        '        sys.modules["pyexpat.errors"] = _pyexpat_fake_child\n'
        '        _pyexpat_forged_child_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        sys.modules["pyexpat.errors"] = _pyexpat_original_child\n'
        '    if not _pyexpat_forged_child_rejected:\n'
        '        raise RuntimeError("pyexpat_forged_child_accepted")\n'
        '    checks.append("pyexpat_forged_sys_modules_child_denied_before_qa_packages")\n'
        '    _pyexpat_parent = _PYEXPAT_EXPECTED_BINDING[0]\n'
        '    try:\n'
        '        _pyexpat_parent.errors = _pyexpat_fake_child\n'
        '        _pyexpat_parent_attribute_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        _pyexpat_parent.errors = _pyexpat_original_child\n'
        '    if not _pyexpat_parent_attribute_rejected:\n'
        '        raise RuntimeError("pyexpat_parent_attribute_rebinding_accepted")\n'
        '    checks.append("pyexpat_parent_attribute_identity_denied_before_qa_packages")\n'
        '    try:\n'
        '        sys.modules["pyexpat"] = _pyexpat_fake_child\n'
        '        _pyexpat_forged_parent_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        sys.modules["pyexpat"] = _pyexpat_parent\n'
        '    if not _pyexpat_forged_parent_rejected:\n'
        '        raise RuntimeError("pyexpat_forged_parent_accepted")\n'
        '    checks.append("pyexpat_parent_sys_modules_identity_denied_before_qa_packages")\n'
        '    _pyexpat_parent_spec = _PYEXPAT_EXPECTED_BINDING[1]\n'
        '    _pyexpat_parent_origin = _pyexpat_parent_spec.origin\n'
        '    try:\n'
        '        _pyexpat_parent_spec.origin = "C:/opaque/pyexpat.pyd"\n'
        '        _pyexpat_wrong_origin_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        _pyexpat_parent_spec.origin = _pyexpat_parent_origin\n'
        '    if not _pyexpat_wrong_origin_rejected:\n'
        '        raise RuntimeError("pyexpat_noncanonical_origin_accepted")\n'
        '    checks.append("pyexpat_parent_origin_mutation_denied_before_qa_packages")\n'
        '    _pyexpat_parent_loader = _PYEXPAT_EXPECTED_BINDING[2]\n'
        '    try:\n'
        '        _pyexpat_parent_spec.loader = _pyexpat_fake_child\n'
        '        _pyexpat_wrong_loader_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        _pyexpat_parent_spec.loader = _pyexpat_parent_loader\n'
        '    if not _pyexpat_wrong_loader_rejected:\n'
        '        raise RuntimeError("pyexpat_noncanonical_loader_accepted")\n'
        '    checks.append("pyexpat_parent_loader_mutation_denied_before_qa_packages")\n'
        '    _pyexpat_original_child_spec = _pyexpat_original_child.__spec__\n'
        '    try:\n'
        '        _pyexpat_original_child.__spec__ = importlib.machinery.ModuleSpec("pyexpat.errors", None)\n'
        '        _pyexpat_child_metadata_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        _pyexpat_original_child.__spec__ = _pyexpat_original_child_spec\n'
        '    if not _pyexpat_child_metadata_rejected:\n'
        '        raise RuntimeError("pyexpat_child_metadata_mutation_accepted")\n'
        '    checks.append("pyexpat_child_spec_mutation_denied_before_qa_packages")\n'
        '    try:\n'
        '        _pyexpat_original_child.__file__ = "C:/opaque/pyexpat_errors.py"\n'
        '        _pyexpat_child_file_rejected = not _pyexpat_binding_is_live()\n'
        '    finally:\n'
        '        delattr(_pyexpat_original_child, "__file__")\n'
        '    if not _pyexpat_child_file_rejected:\n'
        '        raise RuntimeError("pyexpat_child_file_mutation_accepted")\n'
        '    checks.append("pyexpat_child_file_mutation_denied_before_qa_packages")\n'
        '    expected = (\n',
        "r13_pyexpat_live_binding_selfchecks",
    )
    pyexpat_check_names = (
        "pyexpat_canonical_parent_and_children_verified_before_qa_packages",
        "pyexpat_forged_sys_modules_child_denied_before_qa_packages",
        "pyexpat_parent_attribute_identity_denied_before_qa_packages",
        "pyexpat_parent_sys_modules_identity_denied_before_qa_packages",
        "pyexpat_parent_origin_mutation_denied_before_qa_packages",
        "pyexpat_parent_loader_mutation_denied_before_qa_packages",
        "pyexpat_child_spec_mutation_denied_before_qa_packages",
        "pyexpat_child_file_mutation_denied_before_qa_packages",
    )
    top_guard_anchor = (
        '    "winreg_operation_audit_denied_before_qa_packages",\n'
        ')\nCHILD_TRACE_PREFIX ='
    )
    top_guard_replacement = (
        '    "winreg_operation_audit_denied_before_qa_packages",\n'
        + ''.join(f'    "{name}",\n' for name in pyexpat_check_names)
        + ')\nCHILD_TRACE_PREFIX ='
    )
    source = _replace_once(
        source, top_guard_anchor, top_guard_replacement, "r13_top_guard_expected_checks"
    )
    child_guard_anchor = (
        '        "winreg_operation_audit_denied_before_qa_packages",\n'
        '    )\n'
        '    if tuple(checks) != expected:\n'
    )
    child_guard_replacement = (
        '        "winreg_operation_audit_denied_before_qa_packages",\n'
        + ''.join(f'        "{name}",\n' for name in pyexpat_check_names)
        + '    )\n'
        '    if tuple(checks) != expected:\n'
    )
    source = _replace_once(
        source, child_guard_anchor, child_guard_replacement, "r13_child_guard_expected_checks"
    )
    source = _replace_once(
        source,
        '        "winreg_bootstrap_binding": dict(_WINREG_BOOTSTRAP_RECEIPT),\n',
        '        "winreg_bootstrap_binding": dict(_WINREG_BOOTSTRAP_RECEIPT),\n'
        '        "pyexpat_bootstrap_binding": dict(_PYEXPAT_BOOTSTRAP_RECEIPT),\n',
        "r13_pyexpat_preloader_receipt",
    )
    source = _replace_once(
        source,
        '        "winreg_bootstrap_binding": preload.get("winreg_bootstrap_binding"),\n',
        '        "winreg_bootstrap_binding": preload.get("winreg_bootstrap_binding"),\n'
        '        "pyexpat_bootstrap_binding": preload.get("pyexpat_bootstrap_binding"),\n',
        "r13_pyexpat_child_summary_receipt",
    )
    source = _replace_once(
        source,
        '            "EXPECTED_EARLY_GUARD_CHECKS_VALUE = " + repr(EXPECTED_EARLY_GUARD_CHECKS),\n',
        '            "EXPECTED_EARLY_GUARD_CHECKS_VALUE = " + repr(EXPECTED_EARLY_GUARD_CHECKS),\n'
        '            "PYEXPAT_ORIGIN_TEXT = " + repr(EXPECTED_PYEXPAT_ORIGIN),\n',
        "r13_pyexpat_child_header_binding",
    )
    source = _replace_once(
        source,
        '        == EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT\n',
        '        == EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT\n'
        '        and child_summary.get("preloader", {}).get("pyexpat_bootstrap_binding")\n'
        '        == EXPECTED_PYEXPAT_BOOTSTRAP_BINDING_RECEIPT\n',
        "r13_pyexpat_exact_nine_receipt_gate",
    )
    source = _replace_once(
        source,
        '        "child_summary": child_summary,\n',
        '        "child_summary": child_summary,\n'
        '        "pyexpat_bootstrap_binding": (\n'
        '            child_summary.get("preloader", {}).get("pyexpat_bootstrap_binding")\n'
        '            if child_summary else None\n'
        '        ),\n',
        "r13_pyexpat_root_result_receipt",
    )

    # Re-version only after all R12 byte anchors have been applied to the frozen output.
    source = source.replace("R12", "R13").replace("r12", "r13")
    return source


def _build_r14_overlay(source: str) -> str:
    """Reject mismatched pyexpat children in both trusted-origin rescan paths."""
    source = _replace_once(
        source,
        'def _origin_scan_rescan_category(name, module, origin):\n'
        '    origin_key = _boot_norm(origin) if isinstance(origin, str) else ""\n'
        '    if name == "__main__" and module is _main_module and origin_key == _child_origin:\n'
        '        return "main_module_at_pinned_child_origin"\n'
        '    if name == "__mp_main__" and module is _main_module and origin_key == _child_origin:\n'
        '        return "same_object_main_alias_at_pinned_child_origin"\n'
        '    if _pyexpat_child_binding_is_live(name, module):\n'
        '        return "synthetic_child_of_canonical_pyexpat_extension"\n'
        '    if _winreg_binding_is_live(name, module):\n'
        '        return "canonical_winreg_builtin_binding"\n'
        '    if _origin_scan_typing_alias_is_live(name, module):\n'
        '        return "typing_deprecated_type_alias_at_trusted_typing_origin"\n'
        '    return None\n',
        'def _origin_scan_rescan_category(name, module, origin, scan_name):\n'
        '    if scan_name not in {"post_stdlib", "post_qa"}:\n'
        '        raise RuntimeError("origin_rescan_name_invalid")\n'
        '    origin_key = _boot_norm(origin) if isinstance(origin, str) else ""\n'
        '    if name == "__main__" and module is _main_module and origin_key == _child_origin:\n'
        '        return "main_module_at_pinned_child_origin"\n'
        '    if name == "__mp_main__" and module is _main_module and origin_key == _child_origin:\n'
        '        return "same_object_main_alias_at_pinned_child_origin"\n'
        '    if name in _PYEXPAT_CHILD_MODULE_NAMES:\n'
        '        if _pyexpat_child_binding_is_live(name, module):\n'
        '            return "synthetic_child_of_canonical_pyexpat_extension"\n'
        '        return "pyexpat_synthetic_child_binding_mismatch"\n'
        '    if _winreg_binding_is_live(name, module):\n'
        '        return "canonical_winreg_builtin_binding"\n'
        '    if _origin_scan_typing_alias_is_live(name, module):\n'
        '        return "typing_deprecated_type_alias_at_trusted_typing_origin"\n'
        '    return None\n',
        "r14_reserved_pyexpat_rescan_classification",
    )
    source = _replace_once(
        source,
        '        origin = _boot_origin(module)\n'
        '        alias_category = _origin_scan_rescan_category(name, module, origin)\n'
        '        if alias_category is not None:\n'
        '            _preloaded_module_origin_scan_counts["post_stdlib"] += 1\n',
        '        origin = _boot_origin(module)\n'
        '        alias_category = _origin_scan_rescan_category(name, module, origin, "post_stdlib")\n'
        '        if alias_category == "pyexpat_synthetic_child_binding_mismatch":\n'
        '            _record_preloaded_origin_rejection(name, origin)\n'
        '        if alias_category is not None:\n'
        '            _preloaded_module_origin_scan_counts["post_stdlib"] += 1\n',
        "r14_post_stdlib_reject_before_trusted_origin_fallback",
    )
    source = _replace_once(
        source,
        '        origin = _boot_origin(module)\n'
        '        alias_category = _origin_scan_rescan_category(name, module, origin)\n'
        '        if alias_category is not None:\n'
        '            _preloaded_module_origin_scan_counts["post_qa"] += 1\n',
        '        origin = _boot_origin(module)\n'
        '        alias_category = _origin_scan_rescan_category(name, module, origin, "post_qa")\n'
        '        if alias_category == "pyexpat_synthetic_child_binding_mismatch":\n'
        '            _record_preloaded_origin_rejection(name, origin)\n'
        '        if alias_category is not None:\n'
        '            _preloaded_module_origin_scan_counts["post_qa"] += 1\n',
        "r14_post_qa_reject_before_trusted_origin_fallback",
    )

    check_body_anchor = (
        '    checks.append("pyexpat_child_file_mutation_denied_before_qa_packages")\n'
        '    expected = (\n'
    )
    check_body_addition = (
        '    checks.append("pyexpat_child_file_mutation_denied_before_qa_packages")\n'
        '    _pyexpat_trusted_origin = _boot_origin(sys.modules["types"])\n'
        '    if not _boot_origin_is_trusted(_pyexpat_trusted_origin):\n'
        '        raise RuntimeError("pyexpat_trusted_fake_origin_unavailable")\n'
        '    for _scan_name, _check_name in (\n'
        '        ("post_stdlib", "pyexpat_trusted_origin_forgery_rejected_by_all_post_stdlib_children"),\n'
        '        ("post_qa", "pyexpat_trusted_origin_forgery_rejected_by_all_post_qa_children"),\n'
        '    ):\n'
        '        for _child_name, _child_attribute, _held_child, *_child_state in _PYEXPAT_EXPECTED_BINDING[4]:\n'
        '            _pyexpat_fake_child_for_rescan = types.ModuleType(_child_name)\n'
        '            _pyexpat_fake_child_for_rescan.__file__ = _pyexpat_trusted_origin\n'
        '            _pyexpat_fake_child_for_rescan.__spec__ = importlib.machinery.ModuleSpec(\n'
        '                _child_name, None, origin=_pyexpat_trusted_origin\n'
        '            )\n'
        '            _forged_category = _origin_scan_rescan_category(\n'
        '                _child_name, _pyexpat_fake_child_for_rescan, _pyexpat_trusted_origin, _scan_name\n'
        '            )\n'
        '            if (\n'
        '                not _boot_origin_is_trusted(_pyexpat_trusted_origin)\n'
        '                or _forged_category != "pyexpat_synthetic_child_binding_mismatch"\n'
        '            ):\n'
        '                raise RuntimeError("pyexpat_trusted_origin_forgery_not_rejected")\n'
        '        checks.append(_check_name)\n'
        '    for _scan_name, _check_name in (\n'
        '        ("post_stdlib", "pyexpat_parent_binding_rechecked_for_all_post_stdlib_children"),\n'
        '        ("post_qa", "pyexpat_parent_binding_rechecked_for_all_post_qa_children"),\n'
        '    ):\n'
        '        for _child_name, _child_attribute, _held_child, *_child_state in _PYEXPAT_EXPECTED_BINDING[4]:\n'
        '            _pyexpat_fake_child_for_parent = types.ModuleType(_child_name)\n'
        '            _pyexpat_fake_child_for_parent.__file__ = _pyexpat_trusted_origin\n'
        '            _pyexpat_fake_child_for_parent.__spec__ = importlib.machinery.ModuleSpec(\n'
        '                _child_name, None, origin=_pyexpat_trusted_origin\n'
        '            )\n'
        '            _original_parent_child = getattr(_pyexpat_parent, _child_attribute)\n'
        '            try:\n'
        '                setattr(_pyexpat_parent, _child_attribute, _pyexpat_fake_child_for_parent)\n'
        '                _parent_category = _origin_scan_rescan_category(\n'
        '                    _child_name, _held_child, _pyexpat_trusted_origin, _scan_name\n'
        '                )\n'
        '            finally:\n'
        '                setattr(_pyexpat_parent, _child_attribute, _original_parent_child)\n'
        '            if getattr(_pyexpat_parent, _child_attribute, None) is not _original_parent_child:\n'
        '                raise RuntimeError("pyexpat_parent_binding_not_restored")\n'
        '            if _parent_category != "pyexpat_synthetic_child_binding_mismatch":\n'
        '                raise RuntimeError("pyexpat_parent_binding_not_rechecked")\n'
        '        checks.append(_check_name)\n'
        '    expected = (\n'
    )
    source = _replace_once(
        source, check_body_anchor, check_body_addition, "r14_fake_rescan_and_parent_binding_checks"
    )

    r14_checks = (
        "pyexpat_trusted_origin_forgery_rejected_by_all_post_stdlib_children",
        "pyexpat_trusted_origin_forgery_rejected_by_all_post_qa_children",
        "pyexpat_parent_binding_rechecked_for_all_post_stdlib_children",
        "pyexpat_parent_binding_rechecked_for_all_post_qa_children",
    )
    top_anchor = (
        '    "pyexpat_child_file_mutation_denied_before_qa_packages",\n'
        ')\nCHILD_TRACE_PREFIX ='
    )
    top_replacement = (
        '    "pyexpat_child_file_mutation_denied_before_qa_packages",\n'
        + ''.join(f'    "{name}",\n' for name in r14_checks)
        + ')\nCHILD_TRACE_PREFIX ='
    )
    source = _replace_once(source, top_anchor, top_replacement, "r14_top_expected_checks")
    child_anchor = (
        '        "pyexpat_child_file_mutation_denied_before_qa_packages",\n'
        '    )\n'
        '    if tuple(checks) != expected:\n'
    )
    child_replacement = (
        '        "pyexpat_child_file_mutation_denied_before_qa_packages",\n'
        + ''.join(f'        "{name}",\n' for name in r14_checks)
        + '    )\n'
        '    if tuple(checks) != expected:\n'
    )
    source = _replace_once(source, child_anchor, child_replacement, "r14_child_expected_checks")

    source = source.replace("R13", "R14").replace("r13", "r14")
    return source


def _build_r15_overlay(source: str) -> str:
    """Keep pytest logging within QA and expose only finite failure categories."""
    source = _replace_once(
        source,
        '        arguments = [\n'
        '            str(TEST_PATH), "-q", "--tb=short", "--noconftest", "--collect-in-virtualenv",\n'
        '            "--capture=sys", "--assert=plain", "--import-mode=importlib",\n'
        '            "-c", str(QA / "pytest.ini"), "-p", "no:asyncio", "-p", "no:cacheprovider",\n'
        '            "--basetemp", str(PYTEST_BASE_TEMP),\n'
        '        ]\n',
        '        pytest_log_path = QA / "pytest.log"\n'
        '        if not under(norm_path(pytest_log_path), QA_KEY):\n'
        '            raise RuntimeError("pytest_log_path_outside_qa")\n'
        '        arguments = [\n'
        '            str(TEST_PATH), "-q", "--tb=short", "--noconftest", "--collect-in-virtualenv",\n'
        '            "--capture=sys", "--assert=plain", "--import-mode=importlib",\n'
        '            "-c", str(QA / "pytest.ini"), "-p", "no:asyncio", "-p", "no:cacheprovider",\n'
        '            "--basetemp", str(PYTEST_BASE_TEMP),\n'
        '            "--log-file", str(pytest_log_path), "--log-file-level", "CRITICAL",\n'
        '        ]\n',
        "r15_log_target_and_cli_binding",
    )
    source = _replace_once(
        source,
        '        self.pytest_config_binding = None\n\n'
        '    def pytest_configure(self, config):\n',
        '        self.pytest_config_binding = None\n'
        '        self.failure_diagnostics = []\n\n'
        '    def _record_failure_diagnostic(self, phase, fallback_category):\n'
        '        if len(self.failure_diagnostics) >= 4:\n'
        '            return\n'
        '        label = BLOCKED[-1] if BLOCKED else None\n'
        '        categories = {\n'
        '            "write_outside_external_qa": "external_qa_write_denied",\n'
        '            "pytest_config_write_denied": "pytest_config_write_denied",\n'
        '            "write_to_selected_source_denied": "selected_source_write_denied",\n'
        '            "private_or_native_read": "protected_input_read_denied",\n'
        '            "blocked_import": "protected_import_denied",\n'
        '            "native_or_opaque_import": "native_or_opaque_import_denied",\n'
        '        }\n'
        '        self.failure_diagnostics.append(\n'
        '            {"phase": phase, "category": categories.get(label, fallback_category)}\n'
        '        )\n\n'
        '    def pytest_configure(self, config):\n',
        "r15_bounded_failure_recorder",
    )
    source = _replace_once(
        source,
        '    def pytest_warning_recorded(self, warning_message, when, nodeid, location):\n'
        '        self.warnings.append({"when": str(when), "nodeid_present": bool(nodeid)})\n\n'
        '    def pytest_sessionfinish(self, session, exitstatus):\n',
        '    def pytest_warning_recorded(self, warning_message, when, nodeid, location):\n'
        '        self.warnings.append({"when": str(when), "nodeid_present": bool(nodeid)})\n\n'
        '    def pytest_internalerror(self, excrepr, excinfo):\n'
        '        self._record_failure_diagnostic("pytest_internalerror", "pytest_internal_error")\n\n'
        '    def pytest_collectreport(self, report):\n'
        '        if getattr(report, "failed", False):\n'
        '            self._record_failure_diagnostic("pytest_collection", "collection_failure")\n\n'
        '    def pytest_sessionfinish(self, session, exitstatus):\n',
        "r15_finite_pytest_error_hooks",
    )
    source = _replace_once(
        source,
        '    total_expected_reports = expected_calls * 3\n'
        '    all_reports_passed = (\n',
        '    total_expected_reports = expected_calls * 3\n'
        '    if gate.failure_diagnostics:\n'
        '        pytest_failure_diagnostic = gate.failure_diagnostics[0]\n'
        '    elif exit_code != 0 and not gate.items:\n'
        '        pytest_failure_diagnostic = {\n'
        '            "phase": "focused_pytest_execution",\n'
        '            "category": "pytest_nonzero_before_collection",\n'
        '        }\n'
        '    elif exit_code != 0 and failed:\n'
        '        pytest_failure_diagnostic = {"phase": "pytest_test_reports", "category": "test_failure"}\n'
        '    elif exit_code != 0:\n'
        '        pytest_failure_diagnostic = {\n'
        '            "phase": "focused_pytest_execution",\n'
        '            "category": "pytest_nonzero_unclassified",\n'
        '        }\n'
        '    elif gate.problems:\n'
        '        pytest_failure_diagnostic = {\n'
        '            "phase": "pytest_result_gate",\n'
        '            "category": "source_origin_or_collection_gate_problem",\n'
        '        }\n'
        '    else:\n'
        '        pytest_failure_diagnostic = {"phase": None, "category": None}\n'
        '    all_reports_passed = (\n',
        "r15_pytest_result_phase_category",
    )
    source = _replace_once(
        source,
        '        "pytest_exit_code": exit_code,\n'
        '        "collected": len(gate.items),\n',
        '        "pytest_exit_code": exit_code,\n'
        '        "pytest_failure_diagnostic": pytest_failure_diagnostic,\n'
        '        "pytest_failure_diagnostics": list(gate.failure_diagnostics),\n'
        '        "collected": len(gate.items),\n',
        "r15_failure_diagnostic_summary",
    )
    source = _replace_once(
        source,
        '        "child_exception": exception,\n'
        '    }\n\n\ndef _persist_child_log(path: Path, payload: bytes) -> dict[str, object]:\n',
        '        "child_exception": exception,\n'
        '        "pytest_failure_diagnostic": (\n'
        '            child_summary.get("pytest_failure_diagnostic") if child_summary else None\n'
        '        ),\n'
        '    }\n\n\ndef _persist_child_log(path: Path, payload: bytes) -> dict[str, object]:\n',
        "r15_parent_finite_failure_projection",
    )
    source = source.replace("R14", "R15").replace("r14", "r15")
    return source


def _build_r16_overlay(source: str) -> str:
    """Bind owner methods to the pinned owner module instead of dataclass __init__."""
    source = _replace_once(
        source,
        '            owner_code = _code_path(owner.FixedAccountWindowGetV1.__init__)\n'
        '            if owner_code != _canonical(expected_owner):\n'
        '                self.problems.append("owner_code_origin_mismatch")\n',
        '            owner_class = getattr(owner, "FixedAccountWindowGetV1", None)\n'
        '            owner_namespace = getattr(owner, "__dict__", None)\n'
        '            owner_class_namespace = getattr(owner_class, "__dict__", {})\n'
        '            owner_methods = {\n'
        '                "_require": getattr(owner_class, "_require", None),\n'
        '                "_get": getattr(owner_class, "_get", None),\n'
        '            }\n'
        '            owner_method_expectations = {\n'
        '                "_require": (1596, "FixedAccountWindowGetV1._require"),\n'
        '                "_get": (1610, "FixedAccountWindowGetV1._get"),\n'
        '            }\n'
        '            owner_method_bindings = {}\n'
        '            owner_method_origins = {}\n'
        '            for method_name, method in owner_methods.items():\n'
        '                code = getattr(method, "__code__", None)\n'
        '                filename = getattr(code, "co_filename", None)\n'
        '                if filename == "<string>":\n'
        '                    origin_category = "dataclass_generated"\n'
        '                elif isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner):\n'
        '                    origin_category = "pinned_owner_source"\n'
        '                else:\n'
        '                    origin_category = "other_or_missing"\n'
        '                expected_line, expected_qualname = owner_method_expectations[method_name]\n'
        '                method_ok = (\n'
        '                    type(method) is type(_code_path)\n'
        '                    and code is not None\n'
        '                    and owner_class_namespace.get(method_name) is method\n'
        '                    and getattr(method, "__globals__", None) is owner_namespace\n'
        '                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                    and getattr(method, "__name__", None) == method_name\n'
        '                    and getattr(method, "__qualname__", None) == expected_qualname\n'
        '                    and getattr(code, "co_name", None) == method_name\n'
        '                    and getattr(code, "co_qualname", None) == expected_qualname\n'
        '                    and getattr(code, "co_firstlineno", None) == expected_line\n'
        '                    and origin_category == "pinned_owner_source"\n'
        '                )\n'
        '                owner_method_bindings[method_name] = bool(method_ok)\n'
        '                owner_method_origins[method_name] = origin_category\n'
        '            init_code = getattr(getattr(owner_class, "__init__", None), "__code__", None)\n'
        '            init_filename = getattr(init_code, "co_filename", None)\n'
        '            if init_filename == "<string>":\n'
        '                init_origin_category = "dataclass_generated"\n'
        '            elif isinstance(init_filename, str) and _canonical(init_filename) == _canonical(expected_owner):\n'
        '                init_origin_category = "pinned_owner_source"\n'
        '            else:\n'
        '                init_origin_category = "other_or_missing"\n'
        '            owner_class_binding = (\n'
        '                type(owner) is ModuleType\n'
        '                and sys.modules.get("__main__") is owner\n'
        '                and type(owner_class) is type\n'
        '                and isinstance(owner_namespace, dict)\n'
        '                and owner_namespace.get("FixedAccountWindowGetV1") is owner_class\n'
        '                and getattr(owner, "__name__", None) == "__main__"\n'
        '                and getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                and getattr(owner_class, "__qualname__", None) == "FixedAccountWindowGetV1"\n'
        '                and getattr(owner_class, "__bases__", None) == (object,)\n'
        '            )\n'
        '            self.origins.setdefault("owner_code_binding_observations", []).append(\n'
        '                {\n'
        '                    "owner_main_module": bool(type(owner) is ModuleType and getattr(owner, "__name__", None) == "__main__"),\n'
        '                    "owner_sys_modules_identity": bool(sys.modules.get("__main__") is owner),\n'
        '                    "class_global_identity": bool(isinstance(owner_namespace, dict) and owner_namespace.get("FixedAccountWindowGetV1") is owner_class),\n'
        '                    "class_module_identity": bool(type(owner_class) is type and getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None)),\n'
        '                    "require_globals_identity": bool(getattr(owner_methods["_require"], "__globals__", None) is owner_namespace),\n'
        '                    "get_globals_identity": bool(getattr(owner_methods["_get"], "__globals__", None) is owner_namespace),\n'
        '                    "require_code_origin": owner_method_origins["_require"],\n'
        '                    "get_code_origin": owner_method_origins["_get"],\n'
        '                    "dataclass_init_origin": init_origin_category,\n'
        '                }\n'
        '            )\n'
        '            if not owner_class_binding or not all(owner_method_bindings.values()):\n'
        '                self.problems.append("owner_code_origin_mismatch")\n',
        "r16_owner_source_defined_method_binding",
    )
    source = source.replace("R15", "R16").replace("r15", "r16")
    return source


def _build_r17_overlay(source: str) -> str:
    helper_code = (
        '    def _capture_owner_method_bindings(self, owner):\n'
        '        expected_owner = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"\n'
        '        try:\n'
        '            if type(owner) is not ModuleType:\n'
        '                return (\n'
        '                    owner, None, None, (False, False, False),\n'
        '                    (False, False, False, False), (), "other_or_missing",\n'
        '                )\n'
        '            owner_namespace = owner.__dict__\n'
        '            module_checks = (\n'
        '                type(owner) is ModuleType,\n'
        '                getattr(owner, "__name__", None) == "__main__",\n'
        '                sys.modules.get("__main__") is owner,\n'
        '            )\n'
        '            owner_class = owner_namespace.get("FixedAccountWindowGetV1")\n'
        '            if type(owner_class) is not type:\n'
        '                return (\n'
        '                    owner, owner_namespace, owner_class, module_checks,\n'
        '                    (False, False, False, False), (), "other_or_missing",\n'
        '                )\n'
        '            class_namespace = owner_class.__dict__\n'
        '            class_checks = (\n'
        '                owner_namespace.get("FixedAccountWindowGetV1") is owner_class,\n'
        '                getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None),\n'
        '                getattr(owner_class, "__qualname__", None) == "FixedAccountWindowGetV1",\n'
        '                getattr(owner_class, "__bases__", None) == (object,),\n'
        '            )\n'
        '            expectations = (\n'
        '                ("_require", 1596, "FixedAccountWindowGetV1._require"),\n'
        '                ("_get", 1610, "FixedAccountWindowGetV1._get"),\n'
        '            )\n'
        '            method_records = []\n'
        '            for method_name, expected_line, expected_qualname in expectations:\n'
        '                method = class_namespace.get(method_name)\n'
        '                if type(method) is type(_code_path):\n'
        '                    code = method.__code__\n'
        '                    method_globals = method.__globals__\n'
        '                    filename = getattr(code, "co_filename", None)\n'
        '                else:\n'
        '                    code = None\n'
        '                    method_globals = None\n'
        '                    filename = None\n'
        '                if filename == "<string>":\n'
        '                    origin_category = "dataclass_generated"\n'
        '                elif isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner):\n'
        '                    origin_category = "pinned_owner_source"\n'
        '                else:\n'
        '                    origin_category = "other_or_missing"\n'
        '                method_ok = (\n'
        '                    type(method) is type(_code_path)\n'
        '                    and code is not None\n'
        '                    and class_namespace.get(method_name) is method\n'
        '                    and method_globals is owner_namespace\n'
        '                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                    and getattr(method, "__name__", None) == method_name\n'
        '                    and getattr(method, "__qualname__", None) == expected_qualname\n'
        '                    and getattr(code, "co_name", None) == method_name\n'
        '                    and getattr(code, "co_qualname", None) == expected_qualname\n'
        '                    and getattr(code, "co_firstlineno", None) == expected_line\n'
        '                    and origin_category == "pinned_owner_source"\n'
        '                )\n'
        '                method_records.append(\n'
        '                    (method_name, method, code, method_globals, origin_category, bool(method_ok))\n'
        '                )\n'
        '            init_method = class_namespace.get("__init__")\n'
        '            init_code = init_method.__code__ if type(init_method) is type(_code_path) else None\n'
        '            init_filename = getattr(init_code, "co_filename", None)\n'
        '            if init_filename == "<string>":\n'
        '                init_origin = "dataclass_generated"\n'
        '            elif isinstance(init_filename, str) and _canonical(init_filename) == _canonical(expected_owner):\n'
        '                init_origin = "pinned_owner_source"\n'
        '            else:\n'
        '                init_origin = "other_or_missing"\n'
        '            return (\n'
        '                owner, owner_namespace, owner_class, module_checks,\n'
        '                class_checks, tuple(method_records), init_origin,\n'
        '            )\n'
        '        except Exception:\n'
        '            return (\n'
        '                owner, None, None, (False, False, False),\n'
        '                (False, False, False, False), (), "other_or_missing",\n'
        '            )\n'
        '\n'
        '    def _owner_method_bindings_still_match(self, fixture, snapshot):\n'
        '        expected_owner = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"\n'
        '        try:\n'
        '            if type(snapshot) is not tuple or len(snapshot) != 7:\n'
        '                return False\n'
        '            (\n'
        '                captured_owner, owner_namespace, owner_class, module_checks,\n'
        '                class_checks, method_records, init_origin,\n'
        '            ) = snapshot\n'
        '            owner = getattr(fixture, "owner", None)\n'
        '            if (\n'
        '                owner is not captured_owner\n'
        '                or type(owner) is not ModuleType\n'
        '                or owner.__dict__ is not owner_namespace\n'
        '                or not all(module_checks)\n'
        '                or not all(class_checks)\n'
        '                or type(owner_class) is not type\n'
        '                or getattr(owner, "__name__", None) != "__main__"\n'
        '                or owner_namespace.get("FixedAccountWindowGetV1") is not owner_class\n'
        '                or getattr(owner_class, "__module__", None) != getattr(owner, "__name__", None)\n'
        '                or getattr(owner_class, "__qualname__", None) != "FixedAccountWindowGetV1"\n'
        '                or getattr(owner_class, "__bases__", None) != (object,)\n'
        '                or type(method_records) is not tuple\n'
        '                or len(method_records) != 2\n'
        '            ):\n'
        '                return False\n'
        '            class_namespace = owner_class.__dict__\n'
        '            expected = {\n'
        '                "_require": (1596, "FixedAccountWindowGetV1._require"),\n'
        '                "_get": (1610, "FixedAccountWindowGetV1._get"),\n'
        '            }\n'
        '            seen = set()\n'
        '            for record in method_records:\n'
        '                if type(record) is not tuple or len(record) != 6:\n'
        '                    return False\n'
        '                method_name, captured_method, captured_code, captured_globals, captured_origin, captured_ok = record\n'
        '                if method_name not in expected or method_name in seen:\n'
        '                    return False\n'
        '                seen.add(method_name)\n'
        '                expected_line, expected_qualname = expected[method_name]\n'
        '                method = class_namespace.get(method_name)\n'
        '                code = getattr(method, "__code__", None) if type(method) is type(_code_path) else None\n'
        '                filename = getattr(code, "co_filename", None)\n'
        '                origin_category = (\n'
        '                    "dataclass_generated" if filename == "<string>"\n'
        '                    else "pinned_owner_source"\n'
        '                    if isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner)\n'
        '                    else "other_or_missing"\n'
        '                )\n'
        '                if not (\n'
        '                    captured_ok is True\n'
        '                    and captured_origin == "pinned_owner_source"\n'
        '                    and origin_category == captured_origin\n'
        '                    and method is captured_method\n'
        '                    and type(method) is type(_code_path)\n'
        '                    and code is captured_code\n'
        '                    and method.__globals__ is captured_globals is owner_namespace\n'
        '                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                    and getattr(method, "__name__", None) == method_name\n'
        '                    and getattr(method, "__qualname__", None) == expected_qualname\n'
        '                    and getattr(code, "co_name", None) == method_name\n'
        '                    and getattr(code, "co_qualname", None) == expected_qualname\n'
        '                    and getattr(code, "co_firstlineno", None) == expected_line\n'
        '                ):\n'
        '                    return False\n'
        '            return seen == set(expected)\n'
        '        except Exception:\n'
        '            return False\n'
        '\n'
        '    def _owner_method_binding_observation(self, snapshot):\n'
        '        if type(snapshot) is not tuple or len(snapshot) != 7:\n'
        '            return {\n'
        '                "owner_main_module": False,\n'
        '                "owner_sys_modules_identity_during_fixture": False,\n'
        '                "class_global_identity": False,\n'
        '                "class_module_identity": False,\n'
        '                "class_qualname_identity": False,\n'
        '                "class_bases_identity": False,\n'
        '                "require_globals_identity": False,\n'
        '                "get_globals_identity": False,\n'
        '                "require_code_origin": "other_or_missing",\n'
        '                "get_code_origin": "other_or_missing",\n'
        '                "dataclass_init_origin": "other_or_missing",\n'
        '            }\n'
        '        owner, owner_namespace, owner_class, module_checks, class_checks, records, init_origin = snapshot\n'
        '        by_name = {\n'
        '            record[0]: record\n'
        '            for record in records\n'
        '            if type(record) is tuple and len(record) == 6 and isinstance(record[0], str)\n'
        '        }\n'
        '        require = by_name.get("_require")\n'
        '        get_method = by_name.get("_get")\n'
        '        return {\n'
        '            "owner_main_module": bool(len(module_checks) > 1 and module_checks[0] and module_checks[1]),\n'
        '            "owner_sys_modules_identity_during_fixture": bool(len(module_checks) > 2 and module_checks[2]),\n'
        '            "class_global_identity": bool(len(class_checks) > 0 and class_checks[0]),\n'
        '            "class_module_identity": bool(len(class_checks) > 1 and class_checks[1]),\n'
        '            "class_qualname_identity": bool(len(class_checks) > 2 and class_checks[2]),\n'
        '            "class_bases_identity": bool(len(class_checks) > 3 and class_checks[3]),\n'
        '            "require_globals_identity": bool(require is not None and require[3] is owner_namespace),\n'
        '            "get_globals_identity": bool(get_method is not None and get_method[3] is owner_namespace),\n'
        '            "require_code_origin": require[4] if require is not None else "other_or_missing",\n'
        '            "get_code_origin": get_method[4] if get_method is not None else "other_or_missing",\n'
        '            "dataclass_init_origin": init_origin if init_origin in {"dataclass_generated", "pinned_owner_source", "other_or_missing"} else "other_or_missing",\n'
        '        }\n'
    )
    old_init = (
        '        self.fixtures = []\n'
        '        self.test_module = None\n'
    )
    new_init = (
        '        self.fixtures = []\n'
        '        self.owner_binding_snapshots = []\n'
        '        self.test_module = None\n'
    )
    old_capture = (
        '        def capture_fixture(*args, **kwargs):\n'
        '            fixture = original(*args, **kwargs)\n'
        '            gate.fixtures.append(fixture)\n'
        '            return fixture\n'
    )
    new_capture = (
        '        def capture_fixture(*args, **kwargs):\n'
        '            fixture = original(*args, **kwargs)\n'
        '            try:\n'
        '                owner = getattr(fixture, "owner", None)\n'
        '            except Exception:\n'
        '                owner = None\n'
        '            snapshot = gate._capture_owner_method_bindings(owner)\n'
        '            gate.fixtures.append(fixture)\n'
        '            gate.owner_binding_snapshots.append(snapshot)\n'
        '            return fixture\n'
    )
    old_loop = (
        '        for fixture in self.fixtures:\n'
    )
    new_loop = (
        '        if len(self.owner_binding_snapshots) != len(self.fixtures):\n'
        '            self.problems.append("owner_binding_snapshot_count_mismatch")\n'
        '        for fixture, owner_binding_snapshot in zip(self.fixtures, self.owner_binding_snapshots):\n'
    )
    helper_anchor = (
        '    def pytest_collection_finish(self, session):\n'
    )
    old_owner = (
        '            owner_class = getattr(owner, "FixedAccountWindowGetV1", None)\n'
        '            owner_namespace = getattr(owner, "__dict__", None)\n'
        '            owner_class_namespace = getattr(owner_class, "__dict__", {})\n'
        '            owner_methods = {\n'
        '                "_require": getattr(owner_class, "_require", None),\n'
        '                "_get": getattr(owner_class, "_get", None),\n'
        '            }\n'
        '            owner_method_expectations = {\n'
        '                "_require": (1596, "FixedAccountWindowGetV1._require"),\n'
        '                "_get": (1610, "FixedAccountWindowGetV1._get"),\n'
        '            }\n'
        '            owner_method_bindings = {}\n'
        '            owner_method_origins = {}\n'
        '            for method_name, method in owner_methods.items():\n'
        '                code = getattr(method, "__code__", None)\n'
        '                filename = getattr(code, "co_filename", None)\n'
        '                if filename == "<string>":\n'
        '                    origin_category = "dataclass_generated"\n'
        '                elif isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner):\n'
        '                    origin_category = "pinned_owner_source"\n'
        '                else:\n'
        '                    origin_category = "other_or_missing"\n'
        '                expected_line, expected_qualname = owner_method_expectations[method_name]\n'
        '                method_ok = (\n'
        '                    type(method) is type(_code_path)\n'
        '                    and code is not None\n'
        '                    and owner_class_namespace.get(method_name) is method\n'
        '                    and getattr(method, "__globals__", None) is owner_namespace\n'
        '                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                    and getattr(method, "__name__", None) == method_name\n'
        '                    and getattr(method, "__qualname__", None) == expected_qualname\n'
        '                    and getattr(code, "co_name", None) == method_name\n'
        '                    and getattr(code, "co_qualname", None) == expected_qualname\n'
        '                    and getattr(code, "co_firstlineno", None) == expected_line\n'
        '                    and origin_category == "pinned_owner_source"\n'
        '                )\n'
        '                owner_method_bindings[method_name] = bool(method_ok)\n'
        '                owner_method_origins[method_name] = origin_category\n'
        '            init_code = getattr(getattr(owner_class, "__init__", None), "__code__", None)\n'
        '            init_filename = getattr(init_code, "co_filename", None)\n'
        '            if init_filename == "<string>":\n'
        '                init_origin_category = "dataclass_generated"\n'
        '            elif isinstance(init_filename, str) and _canonical(init_filename) == _canonical(expected_owner):\n'
        '                init_origin_category = "pinned_owner_source"\n'
        '            else:\n'
        '                init_origin_category = "other_or_missing"\n'
        '            owner_class_binding = (\n'
        '                type(owner) is ModuleType\n'
        '                and sys.modules.get("__main__") is owner\n'
        '                and type(owner_class) is type\n'
        '                and isinstance(owner_namespace, dict)\n'
        '                and owner_namespace.get("FixedAccountWindowGetV1") is owner_class\n'
        '                and getattr(owner, "__name__", None) == "__main__"\n'
        '                and getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None)\n'
        '                and getattr(owner_class, "__qualname__", None) == "FixedAccountWindowGetV1"\n'
        '                and getattr(owner_class, "__bases__", None) == (object,)\n'
        '            )\n'
        '            self.origins.setdefault("owner_code_binding_observations", []).append(\n'
        '                {\n'
        '                    "owner_main_module": bool(type(owner) is ModuleType and getattr(owner, "__name__", None) == "__main__"),\n'
        '                    "owner_sys_modules_identity": bool(sys.modules.get("__main__") is owner),\n'
        '                    "class_global_identity": bool(isinstance(owner_namespace, dict) and owner_namespace.get("FixedAccountWindowGetV1") is owner_class),\n'
        '                    "class_module_identity": bool(type(owner_class) is type and getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None)),\n'
        '                    "require_globals_identity": bool(getattr(owner_methods["_require"], "__globals__", None) is owner_namespace),\n'
        '                    "get_globals_identity": bool(getattr(owner_methods["_get"], "__globals__", None) is owner_namespace),\n'
        '                    "require_code_origin": owner_method_origins["_require"],\n'
        '                    "get_code_origin": owner_method_origins["_get"],\n'
        '                    "dataclass_init_origin": init_origin_category,\n'
        '                }\n'
        '            )\n'
        '            if not owner_class_binding or not all(owner_method_bindings.values()):\n'
        '                self.problems.append("owner_code_origin_mismatch")\n'
    )
    new_owner = (
        '            owner_binding_ok = self._owner_method_bindings_still_match(\n'
        '                fixture, owner_binding_snapshot\n'
        '            )\n'
        '            owner_observation = self._owner_method_binding_observation(owner_binding_snapshot)\n'
        '            owner_observation["owner_bindings_valid_after_fixture"] = bool(owner_binding_ok)\n'
        '            self.origins.setdefault("owner_code_binding_observations", []).append(owner_observation)\n'
        '            if not owner_binding_ok:\n'
        '                self.problems.append("owner_code_origin_mismatch")\n'
    )
    source = _replace_once(source, old_init, new_init, "r17_capture_storage")
    source = _replace_once(
        source,
        helper_anchor,
        helper_code + helper_anchor,
        "r17_capture_helpers",
    )
    source = _replace_once(source, old_capture, new_capture, "r17_fixture_time_capture")
    source = _replace_once(source, old_loop, new_loop, "r17_snapshot_loop")
    source = _replace_once(source, old_owner, new_owner, "r17_post_teardown_owner_check")
    source = source.replace("R16", "R17").replace("r16", "r17")
    return source


def main() -> int:
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("unexpected_repository_root")
    if RESULT.exists():
        raise RuntimeError("r17_result_path_already_exists")

    r8_runner_pre = _pin(
        R8_RUNNER_PATH, R8_RUNNER_BYTES, R8_RUNNER_SHA256, "r8_runner"
    )
    r8_source_raw, r8_source_pre = _read_pinned(
        R8_GENERATED_PATH,
        R8_GENERATED_BYTES,
        R8_GENERATED_SHA256,
        "r8_generated_source",
    )
    r13_overlay = _build_r13_overlay(_build_overlay(r8_source_raw.decode("utf-8", "strict")))
    r13_overlay_bytes = r13_overlay.encode("utf-8")
    r13_overlay_archive_raw, r13_overlay_pin_pre = _read_pinned(
        R13_GENERATED_PATH,
        R13_GENERATED_BYTES,
        R13_GENERATED_SHA256,
        "r13_generated_source",
    )
    if r13_overlay_archive_raw != r13_overlay_bytes:
        raise RuntimeError("r13_generated_source_transform_mismatch")

    r14_overlay = _build_r14_overlay(r13_overlay)
    r14_overlay_bytes = r14_overlay.encode("utf-8")
    r14_overlay_archive_raw, r14_overlay_pin_pre = _read_pinned(
        R14_GENERATED_PATH,
        R14_GENERATED_BYTES,
        R14_GENERATED_SHA256,
        "r14_generated_source",
    )
    if r14_overlay_archive_raw != r14_overlay_bytes:
        raise RuntimeError("r14_generated_source_transform_mismatch")

    r15_overlay = _build_r15_overlay(r14_overlay)
    r15_overlay_bytes = r15_overlay.encode("utf-8")
    r15_overlay_archive_raw, r15_overlay_pin_pre = _read_pinned(
        R15_GENERATED_PATH,
        R15_GENERATED_BYTES,
        R15_GENERATED_SHA256,
        "r15_generated_source",
    )
    if r15_overlay_archive_raw != r15_overlay_bytes:
        raise RuntimeError("r15_generated_source_transform_mismatch")

    r16_overlay = _build_r16_overlay(r15_overlay)
    r16_overlay_bytes = r16_overlay.encode("utf-8")
    r16_overlay_archive_raw, r16_overlay_pin_pre = _read_pinned(
        R16_GENERATED_PATH,
        R16_GENERATED_BYTES,
        R16_GENERATED_SHA256,
        "r16_generated_source",
    )
    if r16_overlay_archive_raw != r16_overlay_bytes:
        raise RuntimeError("r16_generated_source_transform_mismatch")

    overlay = _build_r17_overlay(r16_overlay)
    overlay_bytes = overlay.encode("utf-8")
    overlay_ast = ast.parse(overlay)
    child_node = next(
        node for node in overlay_ast.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CHILD" for target in node.targets)
    )
    ast.parse(ast.literal_eval(child_node.value))
    overlay_archive_raw, overlay_pin_pre = _read_pinned(
        R17_GENERATED_PATH,
        R17_GENERATED_BYTES,
        R17_GENERATED_SHA256,
        "r17_generated_source",
    )
    if overlay_archive_raw != overlay_bytes:
        raise RuntimeError("r17_generated_source_transform_mismatch")

    namespace = {
        "__name__": "iteration41_binance_account_full_r8_overlay_r17",
        "__file__": str(R17_GENERATED_PATH),
    }
    exec(compile(overlay, str(R17_GENERATED_PATH), "exec"), namespace, namespace)
    namespace.update(
        {
            "EXPECTED_HEAD": EXPECTED_HEAD,
            "R5_BYTES": R5_BYTES,
            "R5_SHA256": R5_SHA256,
            "R6_OVERLAY_BYTES": R6_GENERATED_BYTES,
            "R6_OVERLAY_SHA256": R6_GENERATED_SHA256,
            "R6_GENERATED_BYTES": R6_GENERATED_BYTES,
            "R6_GENERATED_SHA256": R6_GENERATED_SHA256,
            "R7_GENERATED_BYTES": R7_GENERATED_BYTES,
            "R7_GENERATED_SHA256": R7_GENERATED_SHA256,
            "R8_GENERATED_BYTES": R8_GENERATED_BYTES,
            "R8_GENERATED_SHA256": R8_GENERATED_SHA256,
            "R17_OVERLAY_BYTES": len(overlay_bytes),
            "R17_OVERLAY_SHA256": _sha(overlay_bytes),
            "EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT":
                EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT,
            "EXPECTED_PYEXPAT_ORIGIN": EXPECTED_PYEXPAT_ORIGIN,
            "EXPECTED_PYEXPAT_BOOTSTRAP_BINDING_RECEIPT":
                EXPECTED_PYEXPAT_BOOTSTRAP_BINDING_RECEIPT,
        }
    )
    qa_key = str(namespace["QA"]).replace(chr(92), "/").casefold()
    if namespace["RESULT"] != RESULT or not qa_key.startswith(QA_PREFIX.casefold()):
        raise RuntimeError("r17_overlay_output_binding_mismatch")

    exit_code = int(namespace["main"]())
    r8_runner_post = _pin(
        R8_RUNNER_PATH, R8_RUNNER_BYTES, R8_RUNNER_SHA256, "r8_runner"
    )
    r8_source_post = _pin(
        R8_GENERATED_PATH,
        R8_GENERATED_BYTES,
        R8_GENERATED_SHA256,
        "r8_generated_source",
    )
    r13_overlay_pin_post = _pin(
        R13_GENERATED_PATH,
        R13_GENERATED_BYTES,
        R13_GENERATED_SHA256,
        "r13_generated_source",
    )
    r14_overlay_pin_post = _pin(
        R14_GENERATED_PATH,
        R14_GENERATED_BYTES,
        R14_GENERATED_SHA256,
        "r14_generated_source",
    )
    r15_overlay_pin_post = _pin(
        R15_GENERATED_PATH,
        R15_GENERATED_BYTES,
        R15_GENERATED_SHA256,
        "r15_generated_source",
    )
    r16_overlay_pin_post = _pin(
        R16_GENERATED_PATH,
        R16_GENERATED_BYTES,
        R16_GENERATED_SHA256,
        "r16_generated_source",
    )
    overlay_pin_post = _pin(
        R17_GENERATED_PATH,
        R17_GENERATED_BYTES,
        R17_GENERATED_SHA256,
        "r17_generated_source",
    )
    if (
        r8_runner_pre != r8_runner_post
        or r8_source_pre != r8_source_post
        or r13_overlay_pin_pre != r13_overlay_pin_post
        or r14_overlay_pin_pre != r14_overlay_pin_post
        or r15_overlay_pin_pre != r15_overlay_pin_post
        or r16_overlay_pin_pre != r16_overlay_pin_post
        or overlay_pin_pre != overlay_pin_post
    ):
        raise RuntimeError("r8_or_r17_inputs_changed_during_qa")
    print(
        json.dumps(
            {
                "r17_result_path": str(RESULT),
                "r8_runner_pin_pre_post": {"pre": r8_runner_pre, "post": r8_runner_post},
                "r8_generated_source_pin_pre_post": {"pre": r8_source_pre, "post": r8_source_post},
                "r13_generated_source_pin_pre_post": {
                    "pre": r13_overlay_pin_pre, "post": r13_overlay_pin_post
                },
                "r14_generated_source_pin_pre_post": {
                    "pre": r14_overlay_pin_pre, "post": r14_overlay_pin_post
                },
                "r15_generated_source_pin_pre_post": {
                    "pre": r15_overlay_pin_pre, "post": r15_overlay_pin_post
                },
                "r16_generated_source_pin_pre_post": {
                    "pre": r16_overlay_pin_pre, "post": r16_overlay_pin_post
                },
                "r17_generated_source_pin_pre_post": {
                    "pre": overlay_pin_pre, "post": overlay_pin_post
                },
                "candidate_source_tests": 9,
                "selected_model_origin": "head_with_selected_model_hunk",
                "winreg_bootstrap": "canonical_builtin_binding; import and registry audit denied; no API call",
                "root_runtime_public_qa": True,
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
