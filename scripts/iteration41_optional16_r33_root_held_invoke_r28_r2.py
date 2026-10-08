"""R28_r2 source-only adapter for the frozen R27 public root chain.

The adapter keeps activation disabled. Its source-fake entrypoints exercise the
real R27 child binder, R15 glue, complete held-source verification, and root
review. Custody bytes come only from indexed public snapshots; the protected
material creation leaf is replaced with an explicit refusal seam.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.machinery
import json
import ntpath
import os
from pathlib import Path
import sys
import types


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
R27_INVOKE = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
R27_INVOKE_SHA256 = "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339"
R27_WHOLE = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py"
R27_WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
R27_TEST = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
R27_TEST_SHA256 = "d1794b07e9f742dc7ee893bf31194ca16729542d6936a303bc05b1ed55f4039f"
R19_DRIVER = ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
R2_GLUE_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_glue_r15.py"
R2_GLUE_SHA256 = "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98"
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_PUBLIC_SNAPSHOT = (
    EVIDENCE / "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
R25_SUPPLEMENT_BUNDLE = (
    EVIDENCE
    / "iteration41-optional16-installed-matrix-r25-cold-chain-supplement-independent-review-r1-2026-10-04/candidate/source-bundle-r1.zip"
)
R25_SUPPLEMENT_BUNDLE_SHA256 = "b80fc6b6d6851fbc0fa31cbd5efda91ce8dcf9c323cda65c2a09e9d718ad3b7e"
R25_PUBLIC_PINS_SHA256 = "99251a5d7225cf4334d927563b4915bafdbc2caa6bded7488c8a503d97ae51da"
R25_STAGE_ADAPT_SHA256 = "4e4c641b42bb3e3f6389ebef60362f32cfe8eda58344d06d3a6fe852ccaedc85"

ROOT_ACTUAL_ENABLED = False
ROOT_REVIEW_READY = False
ROOT_REVIEWED_ACTIVATION = False
ROOT_NATIVE_ENABLED = False
ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED = False
WHOLE_CALL_SECONDS = 100.0
CLEANUP_SECONDS = 5.0
EXPECTED_COLD_REQUEST_PATHS = 518
EXPECTED_R2_BASE_COLD_PATHS = 515
EXPECTED_R2_OUTER_EXTRA_PATHS = 14
EXPECTED_R2_COLD_OUTER_OVERLAPS = 11
EXPECTED_ACTIVE_PATHS = 575
EXPECTED_OUTER_ONLY_PATHS = 7
EXPECTED_FULL_PATHS = 582
EXPECTED_SOFTWARE_PATHS = 5
EXPECTED_ACTIVE_ALIASES = 19
EXPECTED_ACTIVE_ONLY_PATHS = 64

_HASH = frozenset("0123456789abcdef")
_R2_REVIEW_PIN_FIELDS = frozenset(
    {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json"}
)
_R19_REVIEW_PIN_FIELDS = _R2_REVIEW_PIN_FIELDS | {"README.md"}


class SourceContractError(RuntimeError):
    """A bounded source-contract failure with no caller data attached."""


class _PinnedR19ActiveMap:
    """Result of deriving active pins from the exact held R19 source."""

    __slots__ = (
        "raw",
        "path",
        "name",
        "module",
        "source_reader",
        "pins",
        "software",
        "aliases",
        "module_code_fingerprint",
        "expected_pins_fingerprint",
        "packet_path",
        "packet_pins",
        "review_path",
        "review_pins",
        "test_path",
        "test_digest",
    )

    def __init__(
        self,
        *,
        raw: bytes,
        path: Path,
        name: str,
        module: types.ModuleType,
        source_reader,
        pins: dict[str, str],
        software: dict[str, str],
        aliases: int,
        packet_path: Path,
        packet_pins: dict[str, str],
        review_path: Path,
        review_pins: dict[str, str],
        test_path: Path,
        test_digest: str,
    ) -> None:
        self.raw = raw
        self.path = path
        self.name = name
        self.module = module
        self.source_reader = source_reader
        self.pins = dict(pins)
        self.software = dict(software)
        self.aliases = aliases
        self.module_code_fingerprint = _module_code_fingerprint(module)
        self.expected_pins_fingerprint = _code_fingerprint(module._expected_pins.__code__)
        self.packet_path = packet_path
        self.packet_pins = dict(packet_pins)
        self.review_path = review_path
        self.review_pins = dict(review_pins)
        self.test_path = test_path
        self.test_digest = test_digest


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise SourceContractError(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HASH for character in value)
    )


def path_key(path: str | os.PathLike[str]) -> str:
    _need(isinstance(path, (str, os.PathLike)), "path_type_invalid")
    return ntpath.normcase(ntpath.normpath(os.fspath(path)))


def _constant_fingerprint(value: object) -> object:
    if isinstance(value, types.CodeType):
        return ("code", _code_fingerprint(value))
    if type(value) is tuple:
        return ("tuple", tuple(_constant_fingerprint(item) for item in value))
    if type(value) is frozenset:
        items = [_constant_fingerprint(item) for item in value]
        return ("frozenset", tuple(sorted(items, key=repr)))
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", str(value))
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", value.real.hex(), value.imag.hex())
    if type(value) is str:
        return ("str", value)
    if type(value) is bytes:
        return ("bytes", value.hex())
    if value is Ellipsis:
        return ("ellipsis",)
    raise SourceContractError("module_constant_type_unsupported")


def _code_fingerprint(code: types.CodeType) -> str:
    fields = (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code.hex(),
        tuple(_constant_fingerprint(value) for value in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_filename,
        code.co_name,
        code.co_qualname,
        code.co_firstlineno,
        code.co_linetable.hex(),
        code.co_exceptiontable.hex(),
        code.co_freevars,
        code.co_cellvars,
    )
    canonical = json.dumps(fields, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _module_code_fingerprint(module: types.ModuleType) -> tuple[tuple[str, str], ...]:
    rows = []
    for name, value in vars(module).items():
        if isinstance(value, types.FunctionType):
            rows.append((name, _code_fingerprint(value.__code__)))
    return tuple(sorted(rows))


def _record_verified_module_code(module: types.ModuleType) -> None:
    module.__r28_verified_code_fingerprint__ = _module_code_fingerprint(module)


def _reference_code_fingerprint(raw: bytes, path: Path, name: str) -> tuple[tuple[str, str], ...]:
    probe = types.ModuleType(name)
    probe.__file__ = str(path)
    probe.__package__ = ""
    probe.__cached__ = None
    probe.__loader__ = None
    probe.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    exec(compile(raw, str(path), "exec", dont_inherit=True), probe.__dict__)
    return _module_code_fingerprint(probe)


def _verify_loaded_module(
    module: object,
    raw: bytes,
    path: Path,
    name: str,
) -> types.ModuleType:
    _need(type(module) is types.ModuleType and module.__name__ == name, "module_alias_unbound")
    expected = sha256(raw)
    _need(
        _valid_hash(expected)
        and getattr(module, "__file__", None) == str(path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(path),
        "module_origin_unbound",
    )
    declared = getattr(module, "__verified_source_sha256__", None)
    if declared is not None:
        _need(declared == expected, "module_digest_unbound")
    if getattr(module, "__r28_verified_source_sha256__", None) == expected:
        _need(
            getattr(module, "__r28_verified_path__", None) == str(path),
            "module_reuse_origin_changed",
        )
        _need(
            getattr(module, "__r28_verified_code_fingerprint__", None)
            == _module_code_fingerprint(module),
            "module_reuse_code_changed",
        )
        return module
    actual_code = dict(_module_code_fingerprint(module))
    expected_code = dict(_reference_code_fingerprint(raw, path, name))
    if actual_code != expected_code:
        _need(False, "module_code_unbound")
    module.__verified_source_sha256__ = expected
    module.__r28_verified_source_sha256__ = expected
    module.__r28_verified_path__ = str(path)
    _record_verified_module_code(module)
    return module


def _install_exact_nested_loaders(module: types.ModuleType, source_reader=None) -> None:
    if getattr(module, "__r28_nested_loaders_installed__", False) is True:
        return
    module.__r28_nested_reuse_audit__ = []
    nested = getattr(module, "_load_declared", None)
    if callable(nested):
        original_nested = nested

        def verified_declared(raw: bytes, path: Path, name: str):
            reused = name in sys.modules
            result = _verified_load(original_nested, raw, path, name, source_reader)
            if reused:
                module.__r28_nested_reuse_audit__.append(name)
            return result

        verified_declared.__r28_loader__ = True
        module._load_declared = verified_declared

    load_r16 = getattr(module, "_load_r16_helper", None)
    if callable(load_r16):
        original_load_r16 = load_r16

        def verified_r16(raw: bytes | None = None):
            helper_path = Path(module.R16_HELPER_PATH)
            expected = module.R16_HELPER_SHA256
            if raw is None:
                _need(callable(source_reader), "r16_reuse_requires_pinned_reader")
                raw = source_reader(helper_path, expected)
            _need(type(raw) is bytes, "r16_reuse_requires_held_bytes")
            _need(sha256(raw) == expected and _valid_hash(expected), "r16_helper_digest_invalid")
            name = "_iteration41_optional16_r33_r16_frozen_binding_" + expected[:12]
            prior = sys.modules.get(name)
            if prior is not None:
                result = _verify_loaded_module(prior, raw, helper_path, name)
                module.__r28_nested_reuse_audit__.append(name)
                return result
            result = original_load_r16(raw)
            return _verify_loaded_module(result, raw, helper_path, name)

        verified_r16.__r28_loader__ = True
        module._load_r16_helper = verified_r16
    module.__r28_nested_loaders_installed__ = True
    _record_verified_module_code(module)


def _verified_load(original_loader, raw: bytes, path: Path, name: str, source_reader=None) -> types.ModuleType:
    _need(type(raw) is bytes and isinstance(path, Path) and type(name) is str, "module_load_shape")
    digest = sha256(raw)
    _need(_valid_hash(digest), "module_source_digest_invalid")
    prior = sys.modules.get(name)
    if prior is not None:
        module = _verify_loaded_module(prior, raw, path, name)
    else:
        module = original_loader(raw, path, name)
        module = _verify_loaded_module(module, raw, path, name)
    _install_exact_nested_loaders(module, source_reader)
    return module


def install_verified_module_reuse(invoke: types.ModuleType, source_reader=None) -> None:
    """Allow only byte- and origin-matched reuse of frozen helper aliases."""
    original_loader = invoke._load_declarations
    invoke.__r28_module_reuse_audit__ = []

    def exact_loader(raw: bytes, path: Path, name: str) -> types.ModuleType:
        reused = name in sys.modules
        result = _verified_load(original_loader, raw, path, name, source_reader)
        if reused:
            invoke.__r28_module_reuse_audit__.append(name)
        return result

    exact_loader.__r28_loader__ = True
    invoke._load_declarations = exact_loader


def install_verified_exact_reuse(module: types.ModuleType) -> None:
    """Reuse an already-loaded fixed alias only after exact byte/origin checks."""
    original_loader = module._load_exact
    module.__r28_exact_reuse_audit__ = []

    def exact_loader(raw: bytes, path: Path, name: str, pin: str) -> types.ModuleType:
        _need(type(raw) is bytes and _valid_hash(pin) and sha256(raw) == pin,
              "exact_module_source_pin_invalid")
        prior = sys.modules.get(name)
        if prior is not None:
            loaded = _verify_loaded_module(prior, raw, path, name)
            module.__r28_exact_reuse_audit__.append(name)
        else:
            loaded = original_loader(raw, path, name, pin)
            loaded = _verify_loaded_module(loaded, raw, path, name)
        _install_exact_nested_loaders(loaded)
        return loaded

    exact_loader.__r28_loader__ = True
    module._load_exact = exact_loader
    _record_verified_module_code(module)


def _normalize_map(mapping: object, code: str) -> dict[str, str]:
    _need(type(mapping) is dict, code)
    result: dict[str, str] = {}
    for path, digest in mapping.items():
        key = path_key(path)
        _need(_valid_hash(digest), "pin_digest_invalid")
        prior = result.get(key)
        _need(prior is None or prior == digest, "path_digest_conflict")
        result[key] = digest
    return result


def project_r19_review_pins(
    review_pins: object,
    readme_digest: object,
    review_path: object,
    held_pins: object,
    expected_review_path: object,
    expected_readme_digest: object,
) -> dict[str, str]:
    """Join R2's four pins with its separately bound, held README pin."""
    _need(type(review_pins) is dict and set(review_pins) == _R2_REVIEW_PIN_FIELDS,
          "r2_review_projection_four_pin_shape")
    _need(all(_valid_hash(value) for value in review_pins.values()), "r2_review_projection_pin_invalid")
    _need(_valid_hash(readme_digest), "r2_review_projection_readme_digest_invalid")
    _need(isinstance(review_path, (str, os.PathLike)), "r2_review_projection_path_type")
    raw_path = os.fspath(review_path)
    _need(type(raw_path) is str and ntpath.isabs(raw_path), "r2_review_projection_path_invalid")
    _need(
        isinstance(expected_review_path, (str, os.PathLike))
        and ntpath.isabs(os.fspath(expected_review_path))
        and path_key(review_path) == path_key(expected_review_path),
        "r2_review_projection_context_path_mismatch",
    )
    _need(
        _valid_hash(expected_readme_digest) and readme_digest == expected_readme_digest,
        "r2_review_projection_context_readme_mismatch",
    )
    _need(type(held_pins) is dict, "r2_review_projection_held_map_type")
    result = dict(review_pins)
    _need("README.md" not in result, "r2_review_projection_readme_already_present")
    result["README.md"] = readme_digest
    _need(set(result) == _R19_REVIEW_PIN_FIELDS, "r19_review_projection_five_pin_shape")
    root = path_key(review_path)
    for name, digest in result.items():
        held_digest = held_pins.get(path_key(Path(review_path) / name))
        _need(held_digest == digest, "r2_review_projection_path_digest_mismatch")
    _need(bool(root), "r2_review_projection_path_context_invalid")
    return result


def install_r2_review_projection(r2: types.ModuleType, context: dict[str, object]) -> None:
    """Patch one exact, source-pinned R2 copy site to pass the full R19 review map.

    R2 validates four review files plus a separate README digest. Its frozen
    caller then copies only the four fields to R19, whose unchanged activation
    validator requires five. This transformation replaces only that exact
    assignment RHS with a checked adapter call; all R2 and R19 validators stay
    intact.
    """
    raw = context.get("r2_raw")
    original = getattr(r2, "main", None)
    code = getattr(original, "__code__", None)
    _need(type(raw) is bytes and sha256(raw) == R2_GLUE_SHA256, "r2_projection_source_pin_invalid")
    _need(
        type(r2) is types.ModuleType
        and getattr(r2, "__verified_source_sha256__", None) == R2_GLUE_SHA256
        and type(original) is types.FunctionType
        and original.__globals__ is r2.__dict__
        and type(code) is types.CodeType
        and code.co_name == "main"
        and not code.co_freevars,
        "r2_projection_main_identity_invalid",
    )
    try:
        tree = ast.parse(raw.decode("utf-8", "strict"))
    except (UnicodeError, SyntaxError):
        raise SourceContractError("r2_projection_source_parse_invalid") from None
    main_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"]
    _need(len(main_nodes) == 1 and isinstance(main_nodes[0], ast.FunctionDef), "r2_projection_main_ast_invalid")
    original_node = main_nodes[0]
    transformed_node = copy.deepcopy(original_node)
    anchors = []
    for node in ast.walk(transformed_node):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "active"
            and target.attr == "ROOT_DRIVER_REVIEW_PINS"
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id == "ROOT_REVIEW_PINS"
            and not value.keywords
        ):
            anchors.append(node)
    _need(len(anchors) == 1, "r2_projection_exact_anchor_count_invalid")
    callsite = anchors[0]
    callsite.value = ast.Call(
        func=ast.Name(id="_r28_project_r19_review_pins", ctx=ast.Load()),
        args=[
            callsite.value,
            ast.Name(id="ROOT_REVIEW_README_SHA", ctx=ast.Load()),
            ast.Name(id="REVIEW", ctx=ast.Load()),
        ],
        keywords=[],
    )
    ast.fix_missing_locations(transformed_node)
    transformed_module = ast.Module(body=[transformed_node], type_ignores=[])
    try:
        compiled = compile(
            transformed_module,
            code.co_filename,
            "exec",
            dont_inherit=True,
        )
    except (SyntaxError, TypeError, ValueError):
        raise SourceContractError("r2_projection_compile_invalid") from None
    scratch: dict[str, object] = {"__builtins__": __builtins__}
    exec(compiled, scratch)
    transformed_main = scratch.get("main")
    transformed_code = getattr(transformed_main, "__code__", None)
    _need(
        type(transformed_main) is types.FunctionType
        and type(transformed_code) is types.CodeType
        and transformed_code.co_name == code.co_name
        and transformed_code.co_filename == code.co_filename
        and transformed_code.co_argcount == code.co_argcount
        and transformed_code.co_kwonlyargcount == code.co_kwonlyargcount
        and transformed_code.co_freevars == code.co_freevars,
        "r2_projection_transformed_code_invalid",
    )

    def project(review_pins, readme_digest, review_path):
        _need(context.get("mode") == "actual", "r2_review_projection_wrong_mode")
        held_pins = context.get("expected_pins")
        projected = project_r19_review_pins(
            review_pins,
            readme_digest,
            review_path,
            held_pins,
            r2.REVIEW,
            r2.ROOT_REVIEW_README_SHA,
        )
        context["r2_review_projection_runtime"] = {
            "four_review_pins_validated": True,
            "separate_readme_path_and_digest_validated": True,
            "same_review_directory_validated": True,
            "projected_pin_count": len(projected),
        }
        return projected

    r2._r28_project_r19_review_pins = project
    prior_fingerprint = _code_fingerprint(code)
    transformed_fingerprint = _code_fingerprint(transformed_code)
    original.__code__ = transformed_code
    context["r2_review_projection_install"] = {
        "source_sha256": R2_GLUE_SHA256,
        "source_function": "main",
        "exact_anchor_count": 1,
        "changed_assignment": "active.ROOT_DRIVER_REVIEW_PINS",
        "original_code_fingerprint": prior_fingerprint,
        "transformed_code_fingerprint": transformed_fingerprint,
        "r2_r19_validators_changed": False,
    }


def derive_review_required_paths(invoke: types.ModuleType) -> set[str]:
    """Rebuild the binder's exact source/artifact input set from frozen helpers."""
    r19_binding = sys.modules.get("_iteration41_optional16_r33_r19_driver_validate")
    driver = sys.modules.get("_iteration41_optional16_r33_r19_child_driver_activation")
    r17 = sys.modules.get("_iteration41_optional16_r33_r17_driver_validate")
    r18 = sys.modules.get("_iteration41_optional16_r33_r18_driver_validate")
    _need(
        all(type(module) is types.ModuleType for module in (r19_binding, driver, r17, r18)),
        "review_helper_aliases_missing",
    )
    r16_name = "_iteration41_optional16_r33_r16_frozen_binding_" + r17.R16_HELPER_SHA256[:12]
    r16 = sys.modules.get(r16_name)
    _need(type(r16) is types.ModuleType, "r16_review_helper_missing")

    source_names = (
        set(r16.SUCCESSOR_ROLE_PATHS.values())
        | {r16.SUCCESSOR_TEST_PATH}
        | set(r17.R17_ROLE_PATHS.values())
        | {r17.R17_TEST_PATH}
        | set(r18.R18_ROLE_PATHS.values())
        | {r18.R18_TEST_PATH}
        | set(r19_binding.R19_ROLE_PATHS.values())
        | {r19_binding.R19_TEST_PATH}
    )
    result = {path_key(invoke.ROOT / name) for name in source_names}
    for folder, mapping in (
        (r19_binding.R16_PACKET, r19_binding.R16_PACKET_PINS),
        (r19_binding.R16_REVIEW, r19_binding.R16_REVIEW_PINS),
        (r19_binding.R17_PACKET, r19_binding.R17_PACKET_PINS),
        (r19_binding.R17_REVIEW, r19_binding.R17_REVIEW_PINS),
        (r19_binding.R18_PACKET, r19_binding.R18_PACKET_PINS),
        (r19_binding.R18_REVIEW, r19_binding.R18_REVIEW_PINS),
        (driver.DRIVER_PACKET, driver.ROOT_DRIVER_PACKET_PINS),
        (driver.DRIVER_REVIEW, driver.ROOT_DRIVER_REVIEW_PINS),
    ):
        result.update(path_key(folder / name) for name in mapping)
    return result


def build_full_hold_map(
    cold_request: dict[str | Path, str],
    active_pins: dict[str | Path, str],
    r27_outer_pins: dict[str | Path, str],
    software_pins: dict[str | Path, str],
    active_software_pins: dict[str | Path, str],
    *,
    active_aliases: int,
) -> tuple[dict[str, str], dict[str, int]]:
    """Derive the complete request from the real cold map and validated map.

    The seven outer-only rows are computed from set differences. Their path
    names are never supplied as a hand-authored allowlist.
    """
    cold = _normalize_map(cold_request, "cold_map_shape_invalid")
    active = _normalize_map(active_pins, "active_map_shape_invalid")
    extra = _normalize_map(r27_outer_pins, "outer_map_shape_invalid")
    software = _normalize_map(software_pins, "software_map_shape_invalid")
    active_software = _normalize_map(active_software_pins, "active_software_shape_invalid")
    _need(len(cold) == EXPECTED_COLD_REQUEST_PATHS, "cold_request_count_mismatch")
    _need(len(active) == EXPECTED_ACTIVE_PATHS, "active_map_count_mismatch")
    _need(len(software) == EXPECTED_SOFTWARE_PATHS, "software_map_count_mismatch")
    _need(software == active_software, "software_map_binding_mismatch")
    _need(type(active_aliases) is int and active_aliases == EXPECTED_ACTIVE_ALIASES, "active_alias_count_mismatch")

    for key in cold.keys() & active.keys():
        _need(cold[key] == active[key], "shared_pin_digest_conflict")
    for key in extra.keys() & active.keys():
        _need(extra[key] == active[key], "outer_pin_digest_conflict")
    for key in extra.keys() & cold.keys():
        _need(extra[key] == cold[key], "cold_outer_digest_conflict")

    cold_missing_active = set(active) - set(cold)
    _need(len(cold_missing_active) == EXPECTED_ACTIVE_ONLY_PATHS, "active_difference_count_mismatch")
    union_outer = dict(cold)
    union_outer.update(extra)
    outer_only = {key: digest for key, digest in union_outer.items() if key not in active}
    _need(len(outer_only) == EXPECTED_OUTER_ONLY_PATHS, "outer_difference_count_mismatch")

    full = dict(active)
    full.update(outer_only)
    _need(len(full) == EXPECTED_FULL_PATHS, "complete_hold_count_mismatch")
    _need(set(full) == set(active) | set(outer_only), "complete_hold_set_mismatch")
    metrics = {
        "cold_request_paths": len(cold),
        "validated_active_paths": len(active),
        "active_missing_from_cold": len(cold_missing_active),
        "outer_only_paths": len(outer_only),
        "complete_public_paths": len(full),
        "software_paths": len(software),
        "active_aliases": active_aliases,
        "review_required_paths": 0,
        "review_required_missing_from_cold": 0,
    }
    return full, metrics


def derive_pinned_r19_active_map(
    payload: dict[str, object],
    *,
    source_reader,
    artifact_reader,
) -> _PinnedR19ActiveMap:
    """Derive the R19 active map from its exact source and payload-bound review.

    This caller-side derivation runs before the unchanged R27 binder. Both the
    source and every packet/review artifact are read through pinned public
    readers; no candidate-supplied map is treated as authoritative.
    """
    _need(type(payload) is dict and type(payload.get("driver")) is dict, "r19_derivation_payload_invalid")
    driver = payload["driver"]
    _need(
        path_key(driver.get("path", "")) == path_key(R19_DRIVER)
        and driver.get("sha256") == R19_DRIVER_SHA256,
        "r19_derivation_source_pin_invalid",
    )
    active_path_value = driver.get("active_path")
    _need(type(active_path_value) is str and ntpath.isabs(active_path_value), "r19_derivation_active_path_invalid")
    active_path = Path(active_path_value)
    _need(callable(source_reader) and callable(artifact_reader), "r19_derivation_readers_missing")
    raw = source_reader(R19_DRIVER, R19_DRIVER_SHA256)
    _need(type(raw) is bytes and sha256(raw) == R19_DRIVER_SHA256, "r19_derivation_source_digest_invalid")
    name = "_r28_r2_source_derived_r19_active_map"
    module = types.ModuleType(name)
    module.__file__ = str(active_path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(active_path))
    module.__verified_source_sha256__ = R19_DRIVER_SHA256
    try:
        exec(compile(raw, str(active_path), "exec", dont_inherit=True), module.__dict__)
    except (SyntaxError, TypeError, ValueError):
        raise SourceContractError("r19_derivation_source_compile_invalid") from None
    module = _verify_loaded_module(module, raw, active_path, name)

    packet_value = driver.get("packet_dir")
    review_value = driver.get("review_dir")
    packet_pins_value = driver.get("packet_pins")
    review_pins_value = driver.get("review_pins")
    test_path_value = driver.get("test_path")
    test_digest = driver.get("test_sha256")
    _need(
        isinstance(packet_value, (str, os.PathLike))
        and isinstance(review_value, (str, os.PathLike))
        and isinstance(test_path_value, (str, os.PathLike))
        and _valid_hash(test_digest),
        "r19_derivation_artifact_paths_invalid",
    )
    packet_path = Path(packet_value)
    review_path = Path(review_value)
    test_path = Path(test_path_value)
    packet_pins_normalized = _normalize_map(
        packet_pins_value, "r19_derivation_packet_pins_invalid"
    )
    review_pins_normalized = _normalize_map(
        review_pins_value, "r19_derivation_review_pins_invalid"
    )
    packet_pins = dict(packet_pins_value)
    review_pins = dict(review_pins_value)
    _need(
        set(packet_pins_normalized)
        == {
            path_key("source-bundle.zip"),
            path_key("source-index.json"),
            path_key("source-pins.json"),
            path_key("checkpoint.json"),
            path_key("README.md"),
            path_key("qa/qa-summary.json"),
        },
        "r19_derivation_packet_pin_shape_invalid",
    )
    _need(
        set(review_pins_normalized) == {path_key(name) for name in _R19_REVIEW_PIN_FIELDS},
        "r19_derivation_review_pin_shape_invalid",
    )
    _need(
        driver.get("review_readme_sha256") == review_pins.get("README.md"),
        "r19_derivation_readme_binding_invalid",
    )
    _need(
        path_key(packet_path) == path_key(module.DRIVER_PACKET)
        and path_key(review_path) == path_key(module.DRIVER_REVIEW)
        and path_key(test_path) == path_key(module.DRIVER_TEST),
        "r19_derivation_artifact_context_mismatch",
    )
    _need(
        path_key(test_path) == path_key(module.DRIVER_TEST),
        "r19_derivation_test_path_mismatch",
    )
    for folder, mapping in ((packet_path, packet_pins), (review_path, review_pins)):
        for name_part, digest in mapping.items():
            artifact_path = folder / name_part
            raw_artifact = artifact_reader(artifact_path)
            _need(
                type(raw_artifact) is bytes and sha256(raw_artifact) == digest,
                "r19_derivation_artifact_digest_mismatch",
            )
    raw_test = artifact_reader(test_path)
    _need(type(raw_test) is bytes and sha256(raw_test) == test_digest, "r19_derivation_test_digest_invalid")

    module.ROOT_DRIVER_PATH = active_path
    module.ROOT_DRIVER_SHA256 = R19_DRIVER_SHA256
    module.DRIVER_TEST_SHA256 = test_digest
    module.ROOT_DRIVER_REVIEW_READY = True
    module.ROOT_DRIVER_REVIEW_PINS = dict(review_pins)
    module.ROOT_DRIVER_PACKET_PINS = dict(packet_pins)
    module.ROOT_ENABLED = True
    module.ROOT_REVIEWED_ACTIVATION = True
    module._read_pin = source_reader
    _need(module._activation_ready() is True, "r19_derivation_activation_fields_invalid")
    try:
        pins, software, aliases = module._expected_pins()
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError("r19_derivation_map_builder_failed") from None
    normalized_pins = _normalize_map(pins, "r19_derivation_public_map_invalid")
    normalized_software = _normalize_map(software, "r19_derivation_software_map_invalid")
    expected_counts = payload.get("counts")
    _need(
        type(expected_counts) is dict
        and expected_counts.get("active_public_paths") == len(normalized_pins) == EXPECTED_ACTIVE_PATHS
        and expected_counts.get("software_paths") == len(normalized_software) == EXPECTED_SOFTWARE_PATHS
        and expected_counts.get("path_aliases") == aliases == EXPECTED_ACTIVE_ALIASES,
        "r19_derivation_counts_invalid",
    )
    for path, digest in normalized_pins.items():
        _need(_valid_hash(digest), "r19_derivation_public_digest_invalid")
        _need(path_key(path) == path, "r19_derivation_public_path_not_canonical")
    for path, digest in normalized_software.items():
        _need(_valid_hash(digest), "r19_derivation_software_digest_invalid")
        _need(path_key(path) == path, "r19_derivation_software_path_not_canonical")
    return _PinnedR19ActiveMap(
        raw=raw,
        path=active_path,
        name=name,
        module=module,
        source_reader=source_reader,
        pins=normalized_pins,
        software=normalized_software,
        aliases=aliases,
        packet_path=packet_path,
        packet_pins=packet_pins,
        review_path=review_path,
        review_pins=review_pins,
        test_path=test_path,
        test_digest=test_digest,
    )


def validate_active_map_candidate(
    derivation: object,
    active_pins: object,
    active_software_pins: object,
    active_aliases: object,
) -> tuple[dict[str, str], dict[str, str], int]:
    """Reject any caller map that diverges from the held production builder."""
    _need(type(derivation) is _PinnedR19ActiveMap, "r19_derivation_unbound")
    module = derivation.module
    _need(
        type(derivation.raw) is bytes
        and sha256(derivation.raw) == R19_DRIVER_SHA256
        and path_key(derivation.path) == path_key(module.ROOT_DRIVER_PATH)
        and module.__name__ == derivation.name
        and module.__file__ == str(derivation.path)
        and getattr(getattr(module, "__spec__", None), "origin", None) == str(derivation.path)
        and getattr(module, "__verified_source_sha256__", None) == R19_DRIVER_SHA256
        and module._read_pin is derivation.source_reader
        and _module_code_fingerprint(module) == derivation.module_code_fingerprint
        and _code_fingerprint(module._expected_pins.__code__) == derivation.expected_pins_fingerprint,
        "r19_derivation_source_identity_changed",
    )
    _need(
        module._activation_ready() is True
        and path_key(module.DRIVER_PACKET) == path_key(derivation.packet_path)
        and path_key(module.DRIVER_REVIEW) == path_key(derivation.review_path)
        and module.ROOT_DRIVER_SHA256 == R19_DRIVER_SHA256
        and module.DRIVER_TEST_SHA256 == derivation.test_digest
        and module.ROOT_DRIVER_PACKET_PINS == derivation.packet_pins
        and module.ROOT_DRIVER_REVIEW_PINS == derivation.review_pins,
        "r19_derivation_context_changed",
    )
    try:
        fresh_pins, fresh_software, fresh_aliases = module._expected_pins()
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError("r19_derivation_recheck_failed") from None
    expected_pins = _normalize_map(fresh_pins, "r19_derivation_recheck_map_invalid")
    expected_software = _normalize_map(fresh_software, "r19_derivation_recheck_software_invalid")
    _need(
        expected_pins == derivation.pins
        and expected_software == derivation.software
        and fresh_aliases == derivation.aliases,
        "r19_derivation_recheck_changed",
    )
    candidate_pins = _normalize_map(active_pins, "active_map_candidate_shape_invalid")
    candidate_software = _normalize_map(active_software_pins, "active_software_candidate_shape_invalid")
    _need(candidate_pins == expected_pins, "active_map_candidate_source_mismatch")
    _need(candidate_software == expected_software, "active_software_candidate_source_mismatch")
    _need(
        type(active_aliases) is int and active_aliases == fresh_aliases,
        "active_alias_candidate_source_mismatch",
    )
    return expected_pins, expected_software, fresh_aliases


def bind_child_activation_with_production_map(
    invoke: types.ModuleType,
    payload: dict[str, object],
    *,
    derivation: _PinnedR19ActiveMap,
    active_pins: dict[str | Path, str],
    active_software_pins: dict[str | Path, str],
    active_aliases: int,
    artifact_reader,
    source_reader=None,
) -> tuple[dict[str, object], dict[str, str], dict[str, str], int]:
    """Run the unchanged R27 binder and bind its result to a source-derived map.

    The source-derived module is rechecked, and each caller-supplied map row is
    compared to a fresh call to its exact production ``_expected_pins`` code.
    R27 then runs its own unchanged validator and reports its validated counts.
    """
    active, software, aliases = validate_active_map_candidate(
        derivation, active_pins, active_software_pins, active_aliases
    )
    install_verified_module_reuse(invoke, source_reader=source_reader)
    binding = invoke.bind_child_activation(payload, artifact_reader=artifact_reader)
    _need(binding.get("activation_enabled") is True, "production_child_binding_failed")
    _need(len(active) == EXPECTED_ACTIVE_PATHS, "validated_active_count_invalid")
    _need(len(software) == EXPECTED_SOFTWARE_PATHS, "validated_software_count_invalid")
    _need(type(aliases) is int and aliases == EXPECTED_ACTIVE_ALIASES, "validated_alias_count_invalid")
    _need(
        binding.get("driver_expected_public_pin_count") == len(active)
        and binding.get("driver_software_pin_count") == len(software)
        and binding.get("driver_path_alias_count") == aliases,
        "production_binder_counts_do_not_match_map",
    )
    return binding, active, software, aliases, derivation


def install_full_hold_adaptation(invoke: types.ModuleType, context: dict[str, object]) -> None:
    """Extend the real R27 adaptation before its R2 main call reaches custody."""
    original_install = invoke._install_adaptation

    def install(r2: types.ModuleType, active_context: dict[str, object]) -> None:
        original_install(r2, active_context)
        active_context["r2_module_under_test"] = r2
        install_r2_review_projection(r2, active_context)
        original_load = r2.load
        original_read_pin = r2.read_pin

        def load_with_full_hold(raw: bytes, path: Path, name: str):
            module = original_load(raw, path, name)
            if (
                path_key(path) == path_key(r2.ACTIVE_SOURCE)
                and name == getattr(r2, "_R2_ACTIVE_DRIVER_ALIAS", None)
            ):
                install_verified_exact_reuse(module)
                # Keep the active R19 map builder on the same bounded reader
                # used by the enclosing R27 binder.  Its map derivation stays
                # production code; only the source-byte leaf is redirected.
                module._read_pin = public_read_pin
            elif (
                path_key(path) == path_key(r2.SOURCE)
                and name == getattr(r2, "_R2_INERT_DRIVER_ALIAS", None)
            ):
                # The R2 cold map uses the identical fixed R19 source.  Route
                # its public metadata reads through the catalog as well, so a
                # sourcefake cannot fall through to ambient file reads.
                module._read_pin = public_read_pin
            if path_key(path) == path_key(r2.CU):
                _need(
                    type(raw) is bytes and sha256(raw) == r2.CU_SHA,
                    "cuv2_source_pin_invalid",
                )
                original_holder = active_context.get("captured_cuv2_source_factory")
                _need(callable(original_holder), "cuv2_holder_not_captured")

                def full_hold(cold_pins, software_pins):
                    invoke._set_diagnostic_phase(active_context, "public_map_assembly")
                    active_pins = active_context.get("validated_active_pins")
                    active_software = active_context.get("validated_active_software")
                    active_aliases = active_context.get("validated_active_aliases")
                    _need(type(active_pins) is dict, "validated_active_map_missing")
                    outer = invoke._extra_pins(active_context["mode"])
                    outer_normalized = _normalize_map(outer, "outer_map_shape_invalid")
                    base_cold = _normalize_map(cold_pins, "cold_map_shape_invalid")
                    active_context["r2_base_cold_paths_observed"] = len(base_cold)
                    active_context["r2_outer_extra_paths_observed"] = len(outer_normalized)
                    _need(len(base_cold) == EXPECTED_R2_BASE_COLD_PATHS, "r2_base_cold_count_mismatch")
                    _need(
                        len(outer_normalized) == EXPECTED_R2_OUTER_EXTRA_PATHS,
                        "r2_outer_extra_count_mismatch",
                    )
                    overlap = set(base_cold) & set(outer_normalized)
                    _need(
                        len(overlap) == EXPECTED_R2_COLD_OUTER_OVERLAPS,
                        "r2_cold_outer_overlap_count_mismatch",
                    )
                    cold_normalized = dict(base_cold)
                    for key, digest in outer_normalized.items():
                        prior = cold_normalized.get(key)
                        _need(prior is None or prior == digest, "r2_cold_outer_pin_conflict")
                        cold_normalized[key] = digest
                    full, metrics = build_full_hold_map(
                        cold_normalized,
                        active_pins,
                        outer_normalized,
                        software_pins,
                        active_software,
                        active_aliases=active_aliases,
                    )
                    # The review requirements are derived from the exact helper
                    # roles and artifact maps used by R27's production binder.
                    required = active_context.get("review_required_paths")
                    _need(type(required) is set and len(required) == 64, "review_required_set_missing")
                    cold_keys = set(cold_normalized)
                    active_context["review_required_missing_from_cold_observed"] = len(required - cold_keys)
                    metrics["review_required_paths"] = len(required)
                    metrics["review_required_missing_from_cold"] = len(required - cold_keys)
                    _need(metrics["review_required_missing_from_cold"] == 49, "review_difference_count_mismatch")
                    active_context["expected_pins"] = full
                    active_context["expected_software"] = _normalize_map(
                        software_pins, "software_map_shape_invalid"
                    )
                    active_context["cold_request_pins"] = cold_normalized
                    active_context["r2_base_cold_paths"] = len(base_cold)
                    active_context["r2_outer_extra_paths"] = len(outer_normalized)
                    active_context["r2_cold_outer_overlap_paths"] = len(overlap)
                    active_context["outer_pins"] = outer_normalized
                    active_context["outer_only_path_keys"] = set(full) - set(active_pins)
                    active_context["full_alias_count"] = active_aliases
                    active_context["full_hold_metrics"] = metrics
                    fake_factory = active_context.get("source_fake_scope_factory")
                    if active_context.get("source_fake_mode") is True and callable(fake_factory):
                        raw_scope = fake_factory(full, active_context["expected_software"])
                    else:
                        raw_scope = original_holder(full, active_context["expected_software"])
                    scope = invoke._DeferredScope(raw_scope, active_context, r2)
                    active_context["scope"] = scope
                    return scope

                module.held_public_sources = full_hold
            return module

        def public_read_pin(path: Path, digest: str) -> bytes:
            _need(active_context.get("source_fake_mode") is True, "sourcefake_snapshot_reader_required")
            reader = active_context.get("source_snapshot_reader")
            _need(callable(reader), "source_snapshot_reader_missing")
            raw = reader(path, digest)
            _need(type(raw) is bytes and sha256(raw) == digest, "source_snapshot_pin_mismatch")
            return raw

        r2.load = load_with_full_hold
        r2.read_pin = public_read_pin

    invoke._install_adaptation = install


def build_child_payload(invoke: types.ModuleType, whole: types.ModuleType, deadline: float) -> dict[str, object]:
    """Build the exact frozen R27 child payload without changing activation flags."""
    return {
        "schema": invoke._CHILD_ACTIVATION_SCHEMA,
        "invoke": {
            "path": str(invoke.ROOT_SELF_PATH),
            "sha256": R27_INVOKE_SHA256,
            "test_path": str(invoke.ROOT_TEST_PATH),
            "test_sha256": R27_TEST_SHA256,
            "packet_dir": str(invoke.ROOT_PACKET),
            "packet_pins": dict(whole.R19_PACKET_PINS),
            "review_dir": str(invoke.ROOT_REVIEW),
            "review_pins": dict(whole.R19_REVIEW_PINS),
            "review_readme_sha256": whole.R19_REVIEW_PINS["README.md"],
        },
        "driver": {
            "path": str(invoke.DRIVER),
            "sha256": R19_DRIVER_SHA256,
            "test_path": str(invoke.DRIVER_TEST),
            "test_sha256": whole.R19_TEST_SHA256,
            "packet_dir": str(whole.R19_PACKET),
            "packet_pins": dict(whole.R19_PACKET_PINS),
            "review_dir": str(whole.R19_REVIEW),
            "review_pins": dict(whole.R19_REVIEW_PINS),
            "review_readme_sha256": whole.R19_REVIEW_PINS["README.md"],
            "active_path": str(invoke.DRIVER_ACTIVE_PATH),
        },
        "counts": {
            "inert_public_paths": 379,
            "active_public_paths": EXPECTED_ACTIVE_PATHS,
            "software_paths": EXPECTED_SOFTWARE_PATHS,
            "path_aliases": EXPECTED_ACTIVE_ALIASES,
        },
        "fresh_paths": {
            "ROOT_CONTROL": str(invoke.ROOT_CONTROL),
            "ROOT_SCRATCH": str(invoke.ROOT_SCRATCH),
            "ROOT_DRIVER_CONTROL": str(invoke.ROOT_DRIVER_CONTROL),
            "ROOT_DRIVER_SCRATCH": str(invoke.ROOT_DRIVER_SCRATCH),
            "ROOT_OUTPUT": str(invoke.ROOT_OUTPUT),
            "ROOT_PRECHECK_OUTPUT": str(invoke.ROOT_PRECHECK_OUTPUT),
        },
        "parent_deadline_monotonic": deadline,
        "parent_deadline_domain": invoke.PARENT_DEADLINE_CLOCK_DOMAIN,
    }
