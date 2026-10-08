"""Root-held physical source scope V4 (unregistered, closed by default).

V4 adds two fixed-consumer byte-lending routes to the frozen V3 physical
scope. Raw opaque/software bytes are read only from the scope's already-held
handles and are passed directly to the exact pinned R21 plan loader or R2
profiler source-equivalence proof. The bytes are never returned by these
methods. Declarations, row counts, and hashes remain caller-validated inputs;
this module establishes neither provider nor account authority.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import ntpath
import os
from pathlib import Path
import re
import sys
import threading
import types


ROOT = Path(__file__).resolve().parents[1]
ROOT_HELD_SCOPE_V4_SCHEMA = "iteration41.root-held-source-scope.v4"
ROOT_HELD_SCOPE_V4_ENABLED = False

V3_SOURCE_REL = Path("scripts/iteration41_root_held_source_scope_v3.py")
V3_SOURCE_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
_V3_SOURCE_MAX_BYTES = 256 * 1024
_V3_MODULE_NAME = "_iteration41_root_held_source_scope_v3_pinned_for_v4"

R21_PREPARER_REL = Path(
    "scripts/iteration41_okx_l03_l04_v7_r21_root_r4_v7/root_preparer.py"
)
R21_PREPARER_SHA256 = "4f4985b6d4c611259b94fd142eef6e0cb4d4ba6b759bd2e2db021f84bfc47154"
R21_COORDINATOR_REL = Path(
    "scripts/iteration41_okx_l03_l04_v7_r21_root_r4_v7/root_coordinator.py"
)
R21_COORDINATOR_SHA256 = "14681d8c955c46217c2ea4af2b9d26f73e0594e14160f3d851e519319b234c73"
R21_CALLER_REL = Path("scripts/iteration41_okx_l04_r21_root_caller_r1.py")
R21_CALLER_MODULE_NAME = "scripts.iteration41_okx_l04_r21_root_caller_r1"

R2_MODULE_REL = Path("D:/temp/iteration41-optional16-r32-root-held-invoke-r3.py")
R2_MODULE_SHA256 = "c93a20753db03df0710b86262b3e4a95d9a49ac5c86fe6aad055acfc945f162e"
R2_MODULE_NAME = "_root_r32_r12_enclosing"
PROFILER_PROOF_REL = Path("D:/temp/iteration41-r29-profiler-bytecode-source-proof-r1.py")
PROFILER_PROOF_SHA256 = "7c7de3f15710f5f1b3fc8047bb35b50454d2ed6e5382bfb4096827dca405a913"
PROFILER_PROOF_MODULE_NAME = "_root_r32_r2_held_profiler_proof"

PROFILER_SOURCE_PINS = {
    "cProfile": (
        "C:/anaconda3/Lib/cProfile.py",
        "0a97cf92d0e3efd2e08c2f9b0f0fb8e52a2b26978550804d8e59435201f3fa84",
    ),
    "profile": (
        "C:/anaconda3/Lib/profile.py",
        "4d87bdc8b85bf0a9bdee3e9d975a8a1a0c7360cb264fb68c4c48a102e718e3a3",
    ),
    "pstats": (
        "C:/anaconda3/Lib/pstats.py",
        "d62d1e6a626ebd92187419bfe075a76997cce26fe99dd4520786d4a82b6ff10c",
    ),
}
PROFILER_CACHE_PINS = {
    "C:/anaconda3/Lib/__pycache__/cProfile.cpython-311.pyc":
        "9d9a26a0e0aefd28a28dcd09bf97fd66072f8d537d18431f609485e16fb206b3",
    "C:/anaconda3/Lib/__pycache__/profile.cpython-311.pyc":
        "97408337b11e2c3b44bfb68c6e1f5e84de2536d4185049fec7038ecefc22a346",
    "C:/anaconda3/Lib/__pycache__/pstats.cpython-311.pyc":
        "8e66b028e50b31e7fbc7de63fcfe77025304aeb63b84e085ce13db784dca77ad",
}
PROFILER_CACHE_PATHS = {
    "cProfile": "C:/anaconda3/Lib/__pycache__/cProfile.cpython-311.pyc",
    "profile": "C:/anaconda3/Lib/__pycache__/profile.cpython-311.pyc",
    "pstats": "C:/anaconda3/Lib/__pycache__/pstats.cpython-311.pyc",
}
_R2_PROFILER_PINS = {
    "C:/anaconda3/Lib/__pycache__/cProfile.cpython-311.pyc":
        "9d9a26a0e0aefd28a28dcd09bf97fd66072f8d537d18431f609485e16fb206b3",
    "C:/anaconda3/Lib/__pycache__/profile.cpython-311.pyc":
        "97408337b11e2c3b44bfb68c6e1f5e84de2536d4185049fec7038ecefc22a346",
    "C:/anaconda3/Lib/__pycache__/pstats.cpython-311.pyc":
        "8e66b028e50b31e7fbc7de63fcfe77025304aeb63b84e085ce13db784dca77ad",
}

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_V3_MODULE = None
_RETAINED_LENDING: list[tuple[object, ...]] = []


class RootHeldScopeV4Error(RuntimeError):
    """Fixed safe error codes; no external path or artifact bytes are included."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise RootHeldScopeV4Error(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(path: object) -> str:
    _need(type(path) in (str, type(Path())), "source_path_type_invalid")
    value = str(path)
    _need(0 < len(value) <= 4096 and "\x00" not in value, "source_path_invalid")
    value = value.replace("/", "\\")
    drive, tail = ntpath.splitdrive(value)
    _need(bool(drive) and tail.startswith("\\"), "source_path_invalid")
    _need(".." not in tail.split("\\"), "source_path_traversal_rejected")
    return ntpath.normcase(ntpath.normpath(drive + tail))


def _read_fixed_repo_source(relative: Path, maximum: int, expected_sha256: str) -> tuple[Path, bytes]:
    expected_path = ROOT / relative
    _need(expected_path.is_absolute(), "fixed_source_path_invalid")
    try:
        with expected_path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except BaseException:
        raise RootHeldScopeV4Error("fixed_source_unavailable") from None
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "fixed_source_size_invalid")
    _need(_sha(raw) == expected_sha256, "fixed_source_pin_mismatch")
    return expected_path, raw


def _load_v3_module() -> types.ModuleType:
    global _V3_MODULE
    if _V3_MODULE is not None:
        return _V3_MODULE
    path, raw = _read_fixed_repo_source(V3_SOURCE_REL, _V3_SOURCE_MAX_BYTES, V3_SOURCE_SHA256)
    prior = sys.modules.get(_V3_MODULE_NAME)
    if prior is not None:
        _need(
            type(prior) is types.ModuleType
            and _canonical(prior.__file__) == _canonical(path)
            and prior.__dict__.get("__verified_source_sha256__") == V3_SOURCE_SHA256,
            "pinned_v3_module_conflict",
        )
        _V3_MODULE = prior
        return prior
    module = types.ModuleType(_V3_MODULE_NAME)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(
        _V3_MODULE_NAME, loader=None, origin=str(path)
    )
    module.__verified_source_sha256__ = V3_SOURCE_SHA256
    sys.modules[_V3_MODULE_NAME] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(_V3_MODULE_NAME, None)
        raise RootHeldScopeV4Error("pinned_v3_bootstrap_failed") from None
    _need(
        module.__dict__.get("ROOT_HELD_SCOPE_V3_SCHEMA") == "iteration41.root-held-source-scope.v3"
        and type(module.__dict__.get("RootHeldScopeV3")) is type,
        "pinned_v3_api_invalid",
    )
    _V3_MODULE = module
    return module


_V3_MODULE = _load_v3_module()


class _OpaqueHeldProof:
    __slots__ = ("_scope", "_key", "_digest", "owner_pid", "owner_thread_id", "_seal")

    def __init__(self, token, scope, key, digest, owner_pid, owner_thread_id):
        _need(token is _PROOF_SEAL, "held_proof_constructor_closed")
        self._scope = scope
        self._key = key
        self._digest = digest
        self.owner_pid = owner_pid
        self.owner_thread_id = owner_thread_id
        self._seal = token


_PROOF_SEAL = object()


def _normalize_v4_bindings(bindings: object, private: types.ModuleType):
    """Normalize through frozen V3 policy, allowing explicitly bound temp support."""
    _need(type(bindings) in (list, tuple), "source_binding_rows_invalid")
    adapted = []
    original_categories = {}
    for item in bindings:
        _need(type(item) is dict, "source_binding_row_shape_invalid")
        category = item.get("category")
        raw_path = item.get("physical_path")
        temp_support = False
        if category == "support" and (type(raw_path) is str or type(raw_path) is type(Path())):
            parts = tuple(part.casefold() for part in Path(raw_path).parts)
            temp_support = any(part in {"temp", "tmp"} for part in parts)
        clone = dict(item)
        if temp_support:
            # The row is still held as support. This permits the frozen V3 path
            # policy's explicitly declared D:\temp public-source exception,
            # while its credential, capture, and authority checks still run.
            clone["category"] = "public"
        adapted.append(clone)
        logical = item.get("logical_origin")
        if type(logical) is str:
            original_categories[logical.casefold()] = (category, temp_support)
    rows = list(_V3_MODULE._normalize_bindings(adapted, private))
    _need(len(rows) == len(original_categories), "source_binding_rows_invalid")
    for row in rows:
        category, temp_support = original_categories[row.logical_origin.casefold()]
        if temp_support:
            _need(category == "support", "source_category_invalid")
            row.category = "support"
        elif row.category != category:
            raise RootHeldScopeV4Error("source_category_invalid")
    return tuple(rows)


def _new_reference_module(name: str, path: Path, raw: bytes, optimize: int) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    try:
        exec(
            compile(raw, str(path), "exec", dont_inherit=True, optimize=optimize),
            module.__dict__,
            module.__dict__,
        )
    except BaseException:
        raise RootHeldScopeV4Error("fixed_consumer_reference_compile_failed") from None
    return module


def _verify_module_origin(module: object, name: str, path: Path, digest: str) -> types.ModuleType:
    _need(type(module) is types.ModuleType, "fixed_consumer_module_type_invalid")
    try:
        actual_file = module.__file__
        actual_spec = module.__spec__
        actual_origin = actual_spec.origin
    except BaseException:
        raise RootHeldScopeV4Error("fixed_consumer_origin_invalid") from None
    _need(
        module.__name__ == name
        and _canonical(actual_file) == _canonical(path)
        and _canonical(actual_origin) == _canonical(path)
        and module.__dict__.get("__verified_source_sha256__") == digest,
        "fixed_consumer_origin_invalid",
    )
    return module


def _verify_source_function(
    module: types.ModuleType,
    reference: types.ModuleType,
    function_name: str,
    *,
    shared_globals: tuple[str, ...] = (),
) -> types.FunctionType:
    actual = module.__dict__.get(function_name)
    expected = reference.__dict__.get(function_name)
    _need(type(actual) is types.FunctionType, "fixed_consumer_callable_invalid")
    _need(type(expected) is types.FunctionType, "fixed_consumer_source_callable_missing")
    for name in shared_globals:
        _need(name in module.__dict__ and name in reference.__dict__, "fixed_consumer_global_missing")
        reference.__dict__[name] = module.__dict__[name]
    try:
        _V3_MODULE._verify_function_globals(actual, expected, module, reference, set())
    except BaseException as error:
        reason = getattr(error, "args", ("unknown",))[0]
        if type(reason) is not str or not re.fullmatch(r"[a-z0-9_:]{1,96}", reason):
            reason = "unknown"
        raise RootHeldScopeV4Error("fixed_consumer_callable_mismatch:" + reason) from None
    return actual


class RootHeldScopeV4(_V3_MODULE.RootHeldScopeV3):
    """One-owner V3 handle scope with only the two fixed lending consumers."""

    def __init__(self, bindings=(), *, enabled: bool = ROOT_HELD_SCOPE_V4_ENABLED):
        _need(type(enabled) is bool and enabled is True, "root_held_scope_activation_unset")
        super().__init__((), enabled=enabled)
        self.schema = ROOT_HELD_SCOPE_V4_SCHEMA
        self._initial_rows = _normalize_v4_bindings(bindings, self._private)
        self._proofs: dict[str, _OpaqueHeldProof] = {}
        self._lending = False

    def resolve_and_hold(self, bindings):
        self._require_owner_open()
        _V3_MODULE._need(self._state == "OPEN", "source_scope_not_extendable")
        _V3_MODULE._need(self._postverified is False, "source_scope_already_postverified")
        rows = _normalize_v4_bindings(bindings, self._private)
        return self._hold_rows(rows)

    def _held_row(self, path: object, digest: str, category: str | None = None):
        row = self._find_row(path)
        _need(type(digest) is str and digest == row.digest, "held_row_digest_mismatch")
        if category is not None:
            _need(row.category == category, "held_row_category_mismatch")
        return row

    def _read_verified_row(self, row):
        self._require_owner_open()
        _need(row.key in self._rows and self._rows[row.key] is row, "held_row_identity_mismatch")
        return self._read_row_handle(row, row.maximum)

    def _retain_lending_failure(self, reason: str, *references: object) -> None:
        self._state = "RETAINED"
        self._failure = reason
        _V3_MODULE._retain_scope(self)
        _RETAINED_LENDING.append((self, *references))

    def assert_held(self, path, digest):
        """Return a stable opaque proof after same-handle identity/hash checks."""
        self._require_owner_open()
        row = self._held_row(path, digest)
        self.verify_pin(row.path, row.digest)
        proof = self._proofs.get(row.key)
        if proof is None:
            proof = _OpaqueHeldProof(
                _PROOF_SEAL,
                self,
                row.key,
                row.digest,
                os.getpid(),
                threading.get_ident(),
            )
            self._proofs[row.key] = proof
        _need(
            type(proof) is _OpaqueHeldProof
            and proof._scope is self
            and proof._key == row.key
            and proof._digest == row.digest
            and proof.owner_pid == os.getpid()
            and proof.owner_thread_id == threading.get_ident()
            and proof._seal is _PROOF_SEAL,
            "held_proof_identity_invalid",
        )
        return proof

    def _authenticate_r21_context(self, caller, identity_context, keepalive):
        _need(type(keepalive) is tuple and len(keepalive) >= 3, "r21_keepalive_shape_invalid")
        _need(any(value is self for value in keepalive), "r21_scope_not_retained")
        _need(type(caller) is types.ModuleType, "r21_caller_module_invalid")
        expected_path = ROOT / R21_CALLER_REL
        _need(
            caller.__name__ == R21_CALLER_MODULE_NAME
            and _canonical(caller.__file__) == _canonical(expected_path)
            and _canonical(caller.__spec__.origin) == _canonical(expected_path),
            "r21_caller_origin_invalid",
        )
        caller_digest = caller.__dict__.get("__verified_source_sha256__")
        _need(type(caller_digest) is str and _HEX64.fullmatch(caller_digest), "r21_caller_pin_invalid")
        caller_row = self._held_row(expected_path, caller_digest, "public")
        _need(type(self._read_verified_row(caller_row)) is bytes, "r21_caller_source_unreadable")
        _need(any(value is caller for value in keepalive), "r21_caller_not_retained")
        retention_type = caller.__dict__.get("_InvocationRetention")
        retention_seal = caller.__dict__.get("_RETENTION_SEAL")
        _need(type(retention_type) is type and retention_seal is not None, "r21_retention_type_missing")
        _need(type(identity_context) is retention_type, "r21_retention_type_invalid")
        try:
            valid_retention = (
                identity_context._seal is retention_seal
                and identity_context.owner_pid == os.getpid()
                and identity_context.owner_thread_id == threading.get_ident()
            )
        except BaseException:
            valid_retention = False
        _need(valid_retention, "r21_retention_owner_invalid")
        _need(any(value is identity_context for value in keepalive), "r21_retention_not_retained")
        _need(not isinstance(identity_context, bool), "r21_retention_type_invalid")

    def _selected_raw_map(self, mapping, category):
        _need(type(mapping) is dict, "r21_row_map_invalid")
        result = {}
        for path, digest in mapping.items():
            row = self._held_row(path, digest, category)
            canonical_path = _V3_MODULE._canonical_path(row.path)
            _need(_canonical(path) == canonical_path, "r21_row_path_not_canonical")
            key = canonical_path.casefold()
            _need(key not in result, "r21_row_path_duplicate")
            result[key] = (canonical_path, row)
        ordered = sorted(result.values(), key=lambda pair: pair[0].casefold())
        return {path: row.digest for path, row in ordered}, ordered

    def invoke_r21_load_plan(
        self,
        preparer_module,
        public_rows,
        software_rows,
        support_rows,
        *,
        invocation_nonce,
        keepalive,
        caller,
        identity_context,
        coordinator_path=None,
    ):
        try:
            return self._invoke_r21_load_plan_impl(
                preparer_module,
                public_rows,
                software_rows,
                support_rows,
                invocation_nonce=invocation_nonce,
                keepalive=keepalive,
                caller=caller,
                identity_context=identity_context,
                coordinator_path=coordinator_path,
            )
        except RootHeldScopeV4Error:
            if self._state != "RETAINED":
                self._retain_lending_failure(
                    "r21_plan_lending_failed", preparer_module, caller, identity_context, keepalive
                )
            raise
        except BaseException:
            if self._state != "RETAINED":
                self._retain_lending_failure(
                    "r21_plan_lending_failed", preparer_module, caller, identity_context, keepalive
                )
            raise RootHeldScopeV4Error("r21_plan_lending_failed") from None

    def _invoke_r21_load_plan_impl(
        self,
        preparer_module,
        public_rows,
        software_rows,
        support_rows,
        *,
        invocation_nonce,
        keepalive,
        caller,
        identity_context,
        coordinator_path=None,
    ):
        """Lend selected held rows only to the pinned R21 `load_plan` callable."""
        self._require_owner_open()
        _need(self._state == "OPEN" and self._postverified is False, "r21_scope_not_open")
        _need(not self._lending, "r21_lending_reentry_rejected")
        self._authenticate_r21_context(caller, identity_context, keepalive)
        preparer_path = ROOT / R21_PREPARER_REL
        preparer_row = self._held_row(preparer_path, R21_PREPARER_SHA256, "public")
        preparer_raw = self._read_verified_row(preparer_row)
        _verify_module_origin(
            preparer_module,
            "scripts.iteration41_okx_l03_l04_v7_r21_root_r4_v7.root_preparer",
            preparer_path,
            R21_PREPARER_SHA256,
        )
        _need(_sha(preparer_raw) == R21_PREPARER_SHA256, "r21_preparer_source_pin_mismatch")
        reference = _new_reference_module(
            preparer_module.__name__, preparer_path, preparer_raw, optimize=2
        )
        _need(
            preparer_module.__dict__.get("ROOT_PREPARER_ENABLED") is False
            and preparer_module.__dict__.get("SOURCE_FAKE_PREPARE_SEAM_ENABLED") is False,
            "r21_preparer_activation_not_closed",
        )
        _need(
            type(preparer_module.__dict__.get("_PLAN_SEAL")) is object
            and type(preparer_module.__dict__.get("_RETAINED")) is list,
            "r21_preparer_private_state_invalid",
        )
        _need(not preparer_module.__dict__["_RETAINED"], "r21_preparer_retained_state")
        _need(
            _canonical(preparer_module.__dict__.get("COORDINATOR_PATH"))
            == _canonical(ROOT / R21_COORDINATOR_REL),
            "r21_preparer_coordinator_path_mismatch",
        )
        reference.__dict__["_PLAN_SEAL"] = preparer_module.__dict__["_PLAN_SEAL"]
        reference.__dict__["_RETAINED"] = preparer_module.__dict__["_RETAINED"]
        reference.__dict__["COORDINATOR_PATH"] = preparer_module.__dict__["COORDINATOR_PATH"]
        load_plan = _verify_source_function(preparer_module, reference, "load_plan")
        source_check = _verify_source_function(preparer_module, reference, "source_check")
        source_result = source_check()
        _need(
            type(source_result) is dict
            and source_result
            == {
                "schema": "iteration41.okx.l04.r21.root-preparer.source-check.v1",
                "status": "SOURCE_FAKE_ONLY_DISABLED",
                "root_preparer_enabled": False,
                "component_review_schema": "iteration41.okx.l04.r16.root-activation-independent-review.v1",
                "root_review_sha256": None,
                "physical_custody_verified": False,
                "route_authorized": False,
                "strict_cases_passed": 0,
                "actual_provider_or_sdk_use": False,
            },
            "r21_preparer_source_check_not_closed",
        )

        public, public_items = self._selected_raw_map(public_rows, "public")
        software, software_items = self._selected_raw_map(software_rows, "software")
        support, support_items = self._selected_raw_map(support_rows, "support")
        public_keys = set(public)
        software_keys = set(software)
        support_keys = set(support)
        _need(
            not (public_keys & software_keys or public_keys & support_keys or software_keys & support_keys),
            "r21_row_map_overlap",
        )

        path = ROOT / R21_COORDINATOR_REL if coordinator_path is None else Path(coordinator_path)
        coordinator_row = self._held_row(path, R21_COORDINATOR_SHA256, "public")
        coordinator_raw = self._read_verified_row(coordinator_row)
        _need(
            type(coordinator_raw) is bytes
            and len(coordinator_raw) <= 2 * 1024 * 1024
            and _sha(coordinator_raw) == R21_COORDINATOR_SHA256,
            "r21_coordinator_source_pin_mismatch",
        )

        total = 0
        raw_by_path = {}
        support_raw_by_path = {}
        self._lending = True
        try:
            for mapping, items, target in (
                (public, public_items, raw_by_path),
                (software, software_items, raw_by_path),
                (support, support_items, support_raw_by_path),
            ):
                for canonical_path, row in items:
                    raw = self._read_verified_row(row)
                    _need(len(raw) <= 128 * 1024 * 1024, "r21_file_byte_limit")
                    total += len(raw)
                    _need(total <= 1024 * 1024 * 1024, "r21_total_byte_limit")
                    _need(_sha(raw) == mapping[canonical_path], "r21_lent_row_digest_mismatch")
                    target[canonical_path] = raw
            _need(type(invocation_nonce) is str and re.fullmatch(r"[0-9a-f]{32}", invocation_nonce), "r21_invocation_nonce_invalid")
            plan = load_plan(
                coordinator_raw,
                public,
                software,
                raw_by_path,
                support,
                support_raw_by_path,
                invocation_nonce=invocation_nonce,
                keepalive=keepalive,
            )
            _need(
                type(plan) is preparer_module.RootPreparationPlan
                and type(plan.hold_plan) is plan.coordinator.RootHoldPlan
                and plan.hold_plan.physical_custody_verified is False,
                "r21_plan_dto_invalid",
            )
            _need(
                dict(plan.hold_plan.public_rows) == public
                and dict(plan.hold_plan.software_rows) == software
                and dict(plan.hold_plan.support_rows) == support,
                "r21_plan_map_mismatch",
            )
            return plan
        except RootHeldScopeV4Error:
            self._retain_lending_failure(
                "r21_plan_lending_failed", preparer_module, caller, identity_context, keepalive
            )
            raise
        except BaseException:
            self._retain_lending_failure(
                "r21_plan_lending_failed",
                preparer_module,
                caller,
                identity_context,
                keepalive,
            )
            raise RootHeldScopeV4Error("r21_plan_lending_failed") from None
        finally:
            self._lending = False

    def verify_profiler_module_cache(self, proof_module, r2_module, module_name):
        try:
            return self._verify_profiler_module_cache_impl(proof_module, r2_module, module_name)
        except RootHeldScopeV4Error:
            if self._state != "RETAINED":
                self._retain_lending_failure(
                    "profiler_lending_failed", proof_module, r2_module, module_name
                )
            raise
        except BaseException:
            if self._state != "RETAINED":
                self._retain_lending_failure(
                    "profiler_lending_failed", proof_module, r2_module, module_name
                )
            raise RootHeldScopeV4Error("profiler_lending_failed") from None

    def _verify_profiler_module_cache_impl(self, proof_module, r2_module, module_name):
        """Run the exact R2-pinned profiler proof over same-handle bytes.

        The proof result contains only fixed metadata. Source/cache bytes are
        never returned to the caller or placed in `raw_held` by this method.
        """
        self._require_owner_open()
        _need(self._state == "OPEN" and self._postverified is False, "profiler_scope_not_open")
        _need(not self._lending, "profiler_lending_reentry_rejected")
        _need(type(module_name) is str and module_name in PROFILER_SOURCE_PINS, "profiler_module_not_fixed")

        r2_path = Path(str(R2_MODULE_REL))
        r2_row = self._held_row(r2_path, R2_MODULE_SHA256, "public")
        r2_raw = self._read_verified_row(r2_row)
        _verify_module_origin(r2_module, R2_MODULE_NAME, r2_path, R2_MODULE_SHA256)
        _need(_sha(r2_raw) == R2_MODULE_SHA256, "profiler_r2_source_pin_mismatch")
        pins = r2_module.__dict__.get("PROFILER_CACHE_PINS")
        _need(type(pins) is dict, "profiler_cache_map_invalid")
        normalized_pins = {_canonical(path): digest for path, digest in pins.items()}
        expected_pins = {_canonical(path): digest for path, digest in _R2_PROFILER_PINS.items()}
        _need(normalized_pins == expected_pins, "profiler_cache_map_mismatch")

        proof_path = Path(str(PROFILER_PROOF_REL))
        proof_row = self._held_row(proof_path, PROFILER_PROOF_SHA256, "public")
        proof_raw = self._read_verified_row(proof_row)
        _verify_module_origin(
            proof_module,
            PROFILER_PROOF_MODULE_NAME,
            proof_path,
            PROFILER_PROOF_SHA256,
        )
        _need(_sha(proof_raw) == PROFILER_PROOF_SHA256, "profiler_proof_source_pin_mismatch")
        reference = _new_reference_module(
            proof_module.__name__, proof_path, proof_raw, optimize=0
        )
        sources = proof_module.__dict__.get("SOURCES")
        _need(type(sources) is dict and set(sources) == set(PROFILER_SOURCE_PINS), "profiler_source_map_invalid")
        for name, (expected_path, expected_digest) in PROFILER_SOURCE_PINS.items():
            value = sources.get(name)
            _need(
                type(value) is tuple
                and len(value) == 2
                and _canonical(value[0]) == _canonical(expected_path)
                and value[1] == expected_digest,
                "profiler_source_map_mismatch",
            )
        _need(proof_module.__dict__.get("MAX_CACHE_BYTES") == 2 * 1024 * 1024, "profiler_cache_limit_mismatch")
        reference.__dict__["SOURCES"] = sources
        verifier = _verify_source_function(
            proof_module,
            reference,
            "verify_module_cache",
            shared_globals=("SOURCES",),
        )

        source_path, source_digest = PROFILER_SOURCE_PINS[module_name]
        cache_path = PROFILER_CACHE_PATHS[module_name]
        cache_digest = PROFILER_CACHE_PINS[cache_path]
        source_row = self._held_row(Path(source_path), source_digest)
        cache_row = self._held_row(Path(cache_path), cache_digest)
        _need(source_row.category in {"public", "software"}, "profiler_source_category_invalid")
        _need(cache_row.category in {"public", "software"}, "profiler_cache_category_invalid")
        _need(source_row.maximum <= 128 * 1024 * 1024, "profiler_source_limit_invalid")
        _need(cache_row.maximum <= 128 * 1024 * 1024, "profiler_cache_limit_invalid")

        self._lending = True
        try:
            source_raw = self._read_verified_row(source_row)
            cache_raw = self._read_verified_row(cache_row)
            _need(_sha(source_raw) == source_digest, "profiler_source_pin_mismatch")
            _need(_sha(cache_raw) == cache_digest, "profiler_cache_pin_mismatch")
            _need(len(cache_raw) <= 2 * 1024 * 1024, "profiler_cache_limit_invalid")
            result = verifier(module_name, source_raw, cache_raw)
            expected_keys = {
                "module",
                "source_path",
                "source_sha256",
                "source_bytes",
                "cache_path",
                "cache_sha256",
                "cache_bytes",
                "cache_flags",
                "source_code_graph_equal",
                "normalized_code_graph_sha256",
                "only_code_filename_ignored",
            }
            _need(type(result) is dict and set(result) == expected_keys, "profiler_result_shape_invalid")
            _need(
                result.get("module") == module_name
                and _canonical(result.get("source_path")) == _canonical(source_path)
                and result.get("source_sha256") == source_digest
                and result.get("source_bytes") == len(source_raw)
                and _canonical(result.get("cache_path")) == _canonical(cache_path)
                and result.get("cache_sha256") == cache_digest
                and result.get("cache_bytes") == len(cache_raw)
                and type(result.get("cache_flags")) is int
                and result.get("source_code_graph_equal") is True
                and type(result.get("normalized_code_graph_sha256")) is str
                and _HEX64.fullmatch(result["normalized_code_graph_sha256"]) is not None
                and result.get("only_code_filename_ignored") is True,
                "profiler_result_binding_mismatch",
            )
            _need(
                not any(type(value) is bytes for value in result.values()),
                "profiler_result_raw_bytes_rejected",
            )
            return dict(result)
        except RootHeldScopeV4Error:
            self._retain_lending_failure(
                "profiler_lending_failed", proof_module, r2_module, module_name
            )
            raise
        except BaseException:
            self._retain_lending_failure(
                "profiler_lending_failed", proof_module, r2_module, module_name
            )
            raise RootHeldScopeV4Error("profiler_lending_failed") from None
        finally:
            self._lending = False


__all__ = (
    "ROOT_HELD_SCOPE_V4_SCHEMA",
    "ROOT_HELD_SCOPE_V4_ENABLED",
    "RootHeldScopeV4",
    "RootHeldScopeV4Error",
    "V3_SOURCE_SHA256",
    "R21_PREPARER_SHA256",
    "R21_COORDINATOR_SHA256",
    "PROFILER_PROOF_SHA256",
    "R2_MODULE_SHA256",
)
