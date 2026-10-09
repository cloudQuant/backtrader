"""Root-owned, one-use C01 formal adjudication over a closed same-call handoff.

This module is deliberately an adapter, not a provider verifier.  Its caller
must supply the exact held Root, wrapper, driver, validator, V3, V4, and
handoff modules together with their source-object snapshots.  The authority
comes from the fixed source-bound receipt validators and the Root-owned typed
invocation receipt, never from this module's public counters or a JSON shape.

The child content frame is revalidated only from bytes already retained in
memory.  This module performs no file, private-config, capture, SDK, native,
provider, process, or WinAPI operation.
"""

from __future__ import annotations

import json
import re
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FACTORY = object()
_EVIDENCE_FACTORY = object()
_ROLE_NAMES = {
    "root": "backtrader_runtime.certification_simnow_c01_root_v17",
    "custody": "backtrader_runtime.certification_simnow_c01_root_custody_v17",
    "validator": "common.c01_root_ledger_v1",
    "protocol": "backtrader_runtime.certification_simnow_c01_v3_protocol",
    "worker": "backtrader_runtime.certification_simnow_c01_native_v4",
    "handoff": "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1",
    "wrapper": "scripts.run_simnow_c01_native_td_read_v20_root_activation_r1",
    "driver": "_c01_v20_root_actual_driver",
    "adjudicator": "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1",
    "owner": "backtrader_runtime._c01_native_td_read_v7_owner",
}
_ROLE_PATHS = {
    "root": "backtrader_runtime/certification_simnow_c01_root_v17.py",
    "custody": "backtrader_runtime/certification_simnow_c01_root_custody_v17.py",
    "validator": "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py",
    "protocol": "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
    "worker": "backtrader_runtime/certification_simnow_c01_native_v4.py",
    "handoff": "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py",
    "wrapper": "scripts/run_simnow_c01_native_td_read_v20_root_activation_r1.py",
    "driver": "scripts/iteration41_simnow_c01_v20_root_actual_driver_r1.py",
    "adjudicator": "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py",
    "owner": "backtrader_runtime/certification_simnow_c01_v7_owner.py",
}

_WRAPPER_PROJECTION_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "receipt_type",
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)


class C01RootFormalAdjudicationError(ValueError):
    """Fixed-code, non-sensitive failure while evaluating a formal proof."""

    def __init__(self, code: str = "root_formal_adjudication_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "root_formal_adjudication_blocked"
        super().__init__(code)
        self.code = code


class C01RootFormalPassEvidence:
    """Private result returned only after consuming a Root formal proof."""

    __slots__ = (
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "source_authenticity_verified",
        "account_binding_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "outer_postverify_verified",
        "outer_close_verified",
        "cleanup_verified",
        "_factory",
    )

    def __init__(self, *, values: Mapping[str, Any], _factory: Any = None) -> None:
        exact = {
            "request_count",
            "query_callback_count",
            "snapshot_count",
            "write_invocation_count",
            "source_authenticity_verified",
            "account_binding_verified",
            "source_closure_verified",
            "root_postverify_verified",
            "outer_postverify_verified",
            "outer_close_verified",
            "cleanup_verified",
        }
        if _factory is not _EVIDENCE_FACTORY or type(values) is not dict or set(values) != exact:
            raise C01RootFormalAdjudicationError("formal_evidence_factory_required")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _EVIDENCE_FACTORY)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01RootFormalPassEvidence is immutable")

    def __repr__(self) -> str:
        return "C01RootFormalPassEvidence(<Root adjudicated; private bindings redacted>)"


class C01RootFormalPassProof:
    """Opaque one-use proof. Construction is reserved for this module."""

    __slots__ = (
        "frame",
        "content",
        "root_invocation_receipt",
        "wrapper_call_receipt",
        "outer_close_receipt",
        "source_modules",
        "source_objects",
        "source_pins",
        "expected_frame_source_pins",
        "expected_invocation_id",
        "expected_namespace_generation",
        "expected_worker_source_sha256",
        "expected_pair_binding",
        "expected_account_scope_sha256",
        "expected_credential_binding_sha256",
        "_factory",
        "_used",
    )

    def __init__(
        self,
        *,
        frame: Any,
        content: Any,
        root_invocation_receipt: Any,
        wrapper_call_receipt: Any,
        outer_close_receipt: Any,
        source_modules: Mapping[str, ModuleType],
        source_objects: Mapping[str, Mapping[str, Any]],
        source_pins: Mapping[str, str],
        expected_frame_source_pins: Mapping[str, str],
        expected_invocation_id: str,
        expected_namespace_generation: str,
        expected_worker_source_sha256: str,
        expected_pair_binding: dict[str, Any],
        expected_account_scope_sha256: str,
        expected_credential_binding_sha256: str,
        _factory: Any = None,
    ) -> None:
        if _factory is not _FACTORY:
            raise C01RootFormalAdjudicationError("formal_proof_factory_required")
        self.frame = frame
        self.content = content
        self.root_invocation_receipt = root_invocation_receipt
        self.wrapper_call_receipt = wrapper_call_receipt
        self.outer_close_receipt = outer_close_receipt
        self.source_modules = MappingProxyType(dict(source_modules))
        self.source_objects = MappingProxyType(
            {path: MappingProxyType(dict(rows)) for path, rows in source_objects.items()}
        )
        self.source_pins = MappingProxyType(dict(source_pins))
        self.expected_frame_source_pins = MappingProxyType(dict(expected_frame_source_pins))
        self.expected_invocation_id = expected_invocation_id
        self.expected_namespace_generation = expected_namespace_generation
        self.expected_worker_source_sha256 = expected_worker_source_sha256
        self.expected_pair_binding = MappingProxyType(dict(expected_pair_binding))
        self.expected_account_scope_sha256 = expected_account_scope_sha256
        self.expected_credential_binding_sha256 = expected_credential_binding_sha256
        self._factory = _FACTORY
        self._used = False

    def __repr__(self) -> str:
        return "C01RootFormalPassProof(<opaque one-use proof; no public authority>)"


def mint_c01_root_formal_pass_proof(
    *,
    frame: Any,
    root_invocation_receipt: Any,
    wrapper_call_receipt: Any,
    outer_close_receipt: Any,
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
) -> C01RootFormalPassProof:
    """Mint one proof after the source lease has closed cleanly.

    Root, wrapper, and parent-driver receipt validators are called directly from
    the exact modules captured by the held-source loader.  A caller boolean,
    counter, profile label, or source-fake result is not sufficient.
    """

    modules, objects, pins = _snapshot_source_closure(source_modules, source_objects, source_pins)
    root_module = _module_by_role(modules, "root")
    wrapper_module = _module_by_role(modules, "wrapper")
    driver_module = _module_by_role(modules, "driver")
    root_validate = _require_captured_function(
        root_module,
        objects,
        "validate_c01_root_invocation_receipt",
    )
    wrapper_validate = _require_captured_function(
        wrapper_module,
        objects,
        "validate_c01_v20_wrapper_call_receipt",
    )
    driver_validate = _require_captured_function(
        driver_module,
        objects,
        "validate_c01_v20_outer_close_receipt",
    )
    if root_validate(root_invocation_receipt) is not True:
        raise C01RootFormalAdjudicationError("root_invocation_receipt_invalid")
    if wrapper_validate(wrapper_call_receipt) is not True:
        raise C01RootFormalAdjudicationError("wrapper_call_receipt_invalid")
    if driver_validate(outer_close_receipt) is not True:
        raise C01RootFormalAdjudicationError("outer_close_receipt_invalid")
    _validate_wrapper_projection(wrapper_call_receipt)
    _validate_outer_close_receipt(outer_close_receipt, wrapper_call_receipt)

    context = _require_captured_function(root_module, objects, "c01_formal_adjudication_context")(
        root_invocation_receipt
    )
    if type(context) is not dict or set(context) != {
        "invocation_id",
        "namespace_generation",
        "worker_source_sha256",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "frame_source_pins",
        "source_authenticity_verified",
        "account_binding_verified",
        "source_closure_verified",
        "root_postverify_verified",
    }:
        raise C01RootFormalAdjudicationError("root_invocation_context_invalid")
    _validate_context(context)

    validator = _module_by_role(modules, "validator")
    protocol = _module_by_role(modules, "protocol")
    worker = _module_by_role(modules, "worker")
    helper = _module_by_role(modules, "handoff")
    if type(frame) is not helper.RootContentFrame:
        raise C01RootFormalAdjudicationError("same_call_frame_invalid")
    revalidate = _require_captured_function(helper, objects, "revalidate_c01_root_content_frame")
    frame_pins = context["frame_source_pins"]
    frame_modules = _source_subset(modules, frame_pins)
    frame_objects = _source_subset(objects, frame_pins)
    try:
        content = revalidate(
            frame,
            validator_module=validator,
            protocol_module=protocol,
            worker_module=worker,
            expected_source_pins=frame_pins,
            expected_source_modules=frame_modules,
            expected_source_objects=frame_objects,
            expected_invocation_id=context["invocation_id"],
            expected_namespace_generation=context["namespace_generation"],
            expected_worker_source_sha256=context["worker_source_sha256"],
            expected_pair_binding=context["pair_binding"],
            expected_account_scope_sha256=context["account_scope_sha256"],
            expected_credential_binding_sha256=context["credential_binding_sha256"],
        )
    except Exception:
        raise C01RootFormalAdjudicationError("same_call_content_revalidation_failed") from None
    if not _complete_content(content):
        raise C01RootFormalAdjudicationError("same_call_content_incomplete")
    if (
        content.authority != "NONE"
        or content.status != "CONTENT_VALIDATED_ONLY"
        or content.certification_pass is not False
        or content.source_authenticity_verified is not False
    ):
        raise C01RootFormalAdjudicationError("content_validator_authority_invalid")
    if (
        context["source_authenticity_verified"] is not True
        or context["account_binding_verified"] is not True
        or context["source_closure_verified"] is not True
        or context["root_postverify_verified"] is not True
    ):
        raise C01RootFormalAdjudicationError("root_evidence_not_adjudicated")
    proof = C01RootFormalPassProof(
        frame=frame,
        content=content,
        root_invocation_receipt=root_invocation_receipt,
        wrapper_call_receipt=wrapper_call_receipt,
        outer_close_receipt=outer_close_receipt,
        source_modules=modules,
        source_objects=objects,
        source_pins=pins,
        expected_frame_source_pins=frame_pins,
        expected_invocation_id=context["invocation_id"],
        expected_namespace_generation=context["namespace_generation"],
        expected_worker_source_sha256=context["worker_source_sha256"],
        expected_pair_binding=context["pair_binding"],
        expected_account_scope_sha256=context["account_scope_sha256"],
        expected_credential_binding_sha256=context["credential_binding_sha256"],
        _factory=_FACTORY,
    )
    return proof


def consume_c01_root_formal_pass_proof(
    proof: C01RootFormalPassProof,
) -> C01RootFormalPassEvidence:
    """Consume once and recheck every fixed receipt and content binding."""

    if (
        type(proof) is not C01RootFormalPassProof
        or proof._factory is not _FACTORY
        or proof._used is not False
    ):
        raise C01RootFormalAdjudicationError("formal_proof_invalid_or_replayed")
    proof._used = True
    helper = _module_by_role(proof.source_modules, "handoff")
    if type(proof.frame) is not helper.RootContentFrame:
        raise C01RootFormalAdjudicationError("formal_frame_invalid")
    modules, objects, pins = _snapshot_source_closure(
        proof.source_modules, proof.source_objects, proof.source_pins
    )
    root_module = _module_by_role(modules, "root")
    wrapper_module = _module_by_role(modules, "wrapper")
    driver_module = _module_by_role(modules, "driver")
    if (
        _require_captured_function(root_module, objects, "validate_c01_root_invocation_receipt")(
            proof.root_invocation_receipt
        )
        is not True
        or _require_captured_function(
            wrapper_module, objects, "validate_c01_v20_wrapper_call_receipt"
        )(proof.wrapper_call_receipt)
        is not True
        or _require_captured_function(
            driver_module, objects, "validate_c01_v20_outer_close_receipt"
        )(proof.outer_close_receipt)
        is not True
    ):
        raise C01RootFormalAdjudicationError("formal_receipt_changed")
    _validate_wrapper_projection(proof.wrapper_call_receipt)
    _validate_outer_close_receipt(proof.outer_close_receipt, proof.wrapper_call_receipt)
    context = _require_captured_function(root_module, objects, "c01_formal_adjudication_context")(
        proof.root_invocation_receipt
    )
    _validate_context(context)
    if (
        context["invocation_id"] != proof.expected_invocation_id
        or context["namespace_generation"] != proof.expected_namespace_generation
        or context["worker_source_sha256"] != proof.expected_worker_source_sha256
        or context["pair_binding"] != dict(proof.expected_pair_binding)
        or context["account_scope_sha256"] != proof.expected_account_scope_sha256
        or context["credential_binding_sha256"] != proof.expected_credential_binding_sha256
        or context["frame_source_pins"] != dict(proof.expected_frame_source_pins)
        or any(
            context[field] is not True
            for field in (
                "source_authenticity_verified",
                "account_binding_verified",
                "source_closure_verified",
                "root_postverify_verified",
            )
        )
    ):
        raise C01RootFormalAdjudicationError("formal_context_changed")
    helper = _module_by_role(modules, "handoff")
    frame_modules = _source_subset(modules, proof.expected_frame_source_pins)
    frame_objects = _source_subset(objects, proof.expected_frame_source_pins)
    content = _require_captured_function(helper, objects, "revalidate_c01_root_content_frame")(
        proof.frame,
        validator_module=_module_by_role(modules, "validator"),
        protocol_module=_module_by_role(modules, "protocol"),
        worker_module=_module_by_role(modules, "worker"),
        expected_source_pins=proof.expected_frame_source_pins,
        expected_source_modules=frame_modules,
        expected_source_objects=frame_objects,
        expected_invocation_id=proof.expected_invocation_id,
        expected_namespace_generation=proof.expected_namespace_generation,
        expected_worker_source_sha256=proof.expected_worker_source_sha256,
        expected_pair_binding=dict(proof.expected_pair_binding),
        expected_account_scope_sha256=proof.expected_account_scope_sha256,
        expected_credential_binding_sha256=proof.expected_credential_binding_sha256,
    )
    if not _complete_content(content) or not _same_content(content, proof.content):
        raise C01RootFormalAdjudicationError("formal_content_changed")
    return C01RootFormalPassEvidence(
        values={
            "request_count": content.request_count,
            "query_callback_count": content.query_callback_count,
            "snapshot_count": content.snapshot_count,
            "write_invocation_count": content.write_invocation_count,
            "source_authenticity_verified": True,
            "account_binding_verified": True,
            "source_closure_verified": True,
            "root_postverify_verified": True,
            "outer_postverify_verified": True,
            "outer_close_verified": True,
            "cleanup_verified": True,
        },
        _factory=_EVIDENCE_FACTORY,
    )


def validate_c01_formal_pass_evidence(
    evidence: C01RootFormalPassEvidence,
) -> bool:
    """Validate an adjudicator result without serializing its private inputs."""

    return bool(
        type(evidence) is C01RootFormalPassEvidence
        and evidence._factory is _EVIDENCE_FACTORY
        and type(evidence.request_count) is int
        and evidence.request_count == 8
        and type(evidence.query_callback_count) is int
        and 6 <= evidence.query_callback_count <= 8
        and type(evidence.snapshot_count) is int
        and evidence.snapshot_count == 2
        and type(evidence.write_invocation_count) is int
        and evidence.write_invocation_count == 0
        and evidence.source_authenticity_verified is True
        and evidence.account_binding_verified is True
        and evidence.source_closure_verified is True
        and evidence.root_postverify_verified is True
        and evidence.outer_postverify_verified is True
        and evidence.outer_close_verified is True
        and evidence.cleanup_verified is True
    )


def _snapshot_source_closure(
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
) -> tuple[Mapping[str, ModuleType], Mapping[str, Mapping[str, Any]], Mapping[str, str]]:
    if (
        type(source_modules) not in (dict, MappingProxyType)
        or type(source_objects) not in (dict, MappingProxyType)
        or type(source_pins) not in (dict, MappingProxyType)
        or set(source_modules) != set(source_objects)
        or set(source_modules) != set(source_pins)
        or not source_modules
    ):
        raise C01RootFormalAdjudicationError("source_closure_invalid")
    modules: dict[str, ModuleType] = {}
    objects: dict[str, Mapping[str, Any]] = {}
    pins: dict[str, str] = {}
    for path, module in source_modules.items():
        digest = source_pins[path]
        rows = source_objects[path]
        if (
            type(path) is not str
            or not path
            or type(module) is not ModuleType
            or type(digest) is not str
            or not _SHA256_RE.fullmatch(digest)
            or type(rows) not in (dict, MappingProxyType)
            or module.__dict__.get("__c01_source_sha256__") != digest
        ):
            raise C01RootFormalAdjudicationError("source_closure_invalid")
        required_role = next(
            (role for role, role_path in _ROLE_PATHS.items() if role_path == path), None
        )
        expected_suffix = module.__name__.replace(".", "/") + ".py"
        path_name_matches = (
            module.__name__ == _ROLE_NAMES[required_role]
            if required_role is not None
            else path.endswith(expected_suffix)
        )
        if not path_name_matches or not _source_path_matches(
            module.__dict__.get("__file__"), path
        ):
            raise C01RootFormalAdjudicationError("source_module_path_mismatch")
        modules[path] = module
        objects[path] = MappingProxyType(dict(rows))
        pins[path] = digest
        _validate_captured_objects(module, objects[path])
    _require_roles(modules)
    return MappingProxyType(modules), MappingProxyType(objects), MappingProxyType(pins)


def _require_roles(modules: Mapping[str, ModuleType]) -> None:
    for role, expected_name in _ROLE_NAMES.items():
        path = _ROLE_PATHS[role]
        module = modules.get(path)
        if module is None or module.__name__ != expected_name:
            raise C01RootFormalAdjudicationError("source_role_mismatch")


def _module_by_role(modules: Mapping[str, ModuleType], role: str) -> ModuleType:
    path = _ROLE_PATHS.get(role)
    module = modules.get(path) if path is not None else None
    if module is None or module.__name__ != _ROLE_NAMES[role]:
        raise C01RootFormalAdjudicationError("source_role_mismatch")
    return module


def _validate_captured_objects(module: ModuleType, objects: Mapping[str, Any]) -> None:
    for name, expected in objects.items():
        if name == "__module_object__":
            current = module
        else:
            current = _resolve_source_object(module, name)
        if current is not expected:
            if name.endswith(".__code__"):
                raise C01RootFormalAdjudicationError("source_object_code_changed")
            if name.endswith(".__globals__"):
                raise C01RootFormalAdjudicationError("source_object_globals_changed")
            raise C01RootFormalAdjudicationError("source_object_changed")


def _require_captured_function(
    module: ModuleType,
    objects: Mapping[str, Mapping[str, Any]],
    name: str,
) -> FunctionType:
    path = _module_path_for(module, objects)
    rows = objects[path]
    function = module.__dict__.get(name)
    if (
        type(function) is not FunctionType
        or function is not rows.get(name)
        or function.__code__ is not rows.get(name + ".__code__")
        or function.__globals__ is not module.__dict__
        or function.__module__ != module.__name__
        or function.__qualname__ != name
    ):
        raise C01RootFormalAdjudicationError("source_callable_changed")
    return function


def _module_path_for(module: ModuleType, objects: Mapping[str, Mapping[str, Any]]) -> str:
    # Root V17 deliberately captures source-owned objects only; adding a
    # synthetic module-object row would break its exact object-map check.
    # Resolve one of the fixed role paths by the module's already-validated
    # name, then use the role's exact path.  Non-role modules use their
    # canonical package path and must match one unique entry in the held map.
    role_paths = [
        path for role, name in _ROLE_NAMES.items() if name == module.__name__
        for path in (_ROLE_PATHS[role],) if path in objects
    ]
    if len(role_paths) == 1:
        return role_paths[0]
    if role_paths:
        raise C01RootFormalAdjudicationError("source_module_binding_missing")
    suffix = module.__name__.replace(".", "/") + ".py"
    paths = [path for path in objects if path == suffix or path.endswith("/" + suffix)]
    if len(paths) != 1:
        raise C01RootFormalAdjudicationError("source_module_binding_missing")
    return paths[0]


def _module_or_class_attribute(module: ModuleType, name: str) -> Any:
    if type(name) is not str or not name:
        return None
    parts = name.split(".")
    current = module.__dict__.get(parts[0])
    for part in parts[1:]:
        if isinstance(current, type):
            current = type.__getattribute__(current, "__dict__").get(part)
        elif isinstance(current, (classmethod, staticmethod)):
            current = current.__func__ if part == "__func__" else None
        elif isinstance(current, property):
            current = getattr(current, part, None) if part in {"fget", "fset", "fdel"} else None
        else:
            return None
        if current is None:
            return None
    return current


def _resolve_source_object(module: ModuleType, name: str) -> Any:
    suffix = next(
        (item for item in (".__code__", ".__globals__", ".__func__") if name.endswith(item)),
        None,
    )
    if suffix is None:
        return _module_or_class_attribute(module, name)
    target = _module_or_class_attribute(module, name[: -len(suffix)])
    if suffix == ".__func__":
        return target.__func__ if isinstance(target, (classmethod, staticmethod)) else None
    if isinstance(target, (classmethod, staticmethod)):
        target = target.__func__
    if type(target) is not FunctionType:
        return None
    return target.__code__ if suffix == ".__code__" else target.__globals__


def _source_path_matches(source_path: Any, relative: str) -> bool:
    if type(source_path) is not str or not source_path:
        return False
    normalized = source_path.replace("\\", "/").casefold()
    target = relative.casefold()
    return normalized == target or normalized.endswith("/" + target)


def _validate_wrapper_projection(receipt: Any) -> None:
    raw = getattr(receipt, "projection_raw", None)
    process_receipt = getattr(receipt, "parent_process_receipt", None)
    if type(raw) is not bytes:
        raise C01RootFormalAdjudicationError("wrapper_projection_invalid")
    projection = _decode_candidate_projection(raw)
    if (
        type(projection) is not dict
        or set(projection) != _WRAPPER_PROJECTION_KEYS
        or type(process_receipt) is not getattr(
            getattr(receipt, "parent_driver_module", None),
            "C01V20ParentProcessReceipt",
            None,
        )
        or getattr(process_receipt, "frame", None) is not getattr(receipt, "frame", None)
        or type(getattr(process_receipt, "exit_code", None)) is not int
        or process_receipt.exit_code != 0
    ):
        raise C01RootFormalAdjudicationError("wrapper_projection_invalid")
    expected = {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": "C01_NATIVE_TD_READ_V20",
        "profile": "C01_NATIVE_TD_READ_V20",
        "reason": "candidate_root_handoff_written",
        "write_policy": "NO_WRITE",
        "receipt_type": "C01RootContentCustodyReceipt",
    }
    if any(projection.get(key) != value for key, value in expected.items()):
        raise C01RootFormalAdjudicationError("wrapper_projection_invalid")
    if any(
        projection.get(key) is not True
        for key in (
            "receipt_verified",
            "source_closure_verified",
            "root_postverify_verified",
        )
    ):
        raise C01RootFormalAdjudicationError("wrapper_candidate_invalid")
    if any(
        projection.get(key) is not None
        for key in (
            "outer_job_empty",
            "stdout_eof",
            "stderr_eof",
            "stderr_empty",
            "job_handles_closed",
            "reader_threads_joined",
            "cleanup_verified",
        )
    ):
        raise C01RootFormalAdjudicationError("wrapper_parent_fields_invalid")
    if (
        type(projection.get("writes")) is not int
        or projection["writes"] != 0
        or type(projection.get("write_invocation_count")) is not int
        or projection["write_invocation_count"] != 0
        or type(projection.get("request_count")) is not int
        or projection["request_count"] != 8
        or type(projection.get("query_callback_count")) is not int
        or not 6 <= projection["query_callback_count"] <= 8
        or type(projection.get("snapshot_count")) is not int
        or projection["snapshot_count"] != 2
    ):
        raise C01RootFormalAdjudicationError("wrapper_projection_counts_invalid")


def _validate_outer_close_receipt(receipt: Any, wrapper_receipt: Any) -> None:
    expected = {
        "outer_postverify_verified": True,
        "normal_close_verified": True,
        "source_postclose_pins_verified": True,
        "retained_reference_count": 0,
        "outer_exit_code": 0,
        "outer_job_empty": True,
        "stdout_eof": True,
        "stderr_eof": True,
        "stderr_empty": True,
        "frame_eof": True,
        "job_handles_closed": True,
        "reader_threads_joined": True,
        "cleanup_verified": True,
    }
    for field_name, value in expected.items():
        actual = getattr(receipt, field_name, None)
        if type(value) is int:
            if type(actual) is not int or actual != value:
                raise C01RootFormalAdjudicationError("outer_close_receipt_invalid")
        elif actual is not value:
            raise C01RootFormalAdjudicationError("outer_close_receipt_invalid")
    public_pins = getattr(receipt, "public_source_pins", None)
    software_pins = getattr(receipt, "software_source_pins", None)
    if (
        type(public_pins) is not MappingProxyType
        or type(software_pins) is not MappingProxyType
        or not public_pins
        or not software_pins
        or any(
            type(path) is not str
            or not path
            or type(pin) is not str
            or not _SHA256_RE.fullmatch(pin)
            for mapping in (public_pins, software_pins)
            for path, pin in mapping.items()
        )
    ):
        raise C01RootFormalAdjudicationError("outer_close_source_pins_invalid")
    expected_counts = {
        "observed_held_public_count": len(public_pins),
        "observed_held_software_count": len(software_pins),
        "observed_held_count": len(public_pins) + len(software_pins),
    }
    for field_name, expected_count in expected_counts.items():
        actual = getattr(receipt, field_name, None)
        if type(actual) is not int or actual != expected_count:
            raise C01RootFormalAdjudicationError("outer_close_count_mismatch")
    parent_process = getattr(receipt, "parent_process_receipt", None)
    if (
        parent_process is not getattr(wrapper_receipt, "parent_process_receipt", None)
        or getattr(parent_process, "frame", None) is not getattr(wrapper_receipt, "frame", None)
        or type(getattr(receipt, "call_nonce", None)) is not object
        or receipt.call_nonce is not getattr(parent_process, "call_nonce", None)
    ):
        raise C01RootFormalAdjudicationError("outer_close_call_binding_invalid")


def _decode_candidate_projection(raw: bytes) -> dict[str, Any]:
    """Decode the exact canonical child candidate frame without promoting it."""

    if type(raw) is not bytes or not 0 < len(raw) <= 64 * 1024:
        raise C01RootFormalAdjudicationError("wrapper_projection_invalid")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        projection = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
        canonical = json.dumps(
            projection,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        raise C01RootFormalAdjudicationError("wrapper_projection_invalid") from None
    if type(projection) is not dict or canonical != raw:
        raise C01RootFormalAdjudicationError("wrapper_projection_noncanonical")
    return projection


def _validate_context(context: Any) -> None:
    if type(context) is not dict or set(context) != {
        "invocation_id",
        "namespace_generation",
        "worker_source_sha256",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "frame_source_pins",
        "source_authenticity_verified",
        "account_binding_verified",
        "source_closure_verified",
        "root_postverify_verified",
    }:
        raise C01RootFormalAdjudicationError("root_invocation_context_invalid")
    if (
        type(context["invocation_id"]) is not str
        or not _CALL_ID_RE.fullmatch(context["invocation_id"])
        or type(context["namespace_generation"]) is not str
        or not context["namespace_generation"]
        or any(
            type(context[key]) is not str or not _SHA256_RE.fullmatch(context[key])
            for key in (
                "worker_source_sha256",
                "account_scope_sha256",
                "credential_binding_sha256",
            )
        )
        or type(context["pair_binding"]) is not dict
        or type(context["frame_source_pins"]) not in (dict, MappingProxyType)
        or not context["frame_source_pins"]
        or any(
            type(path) is not str
            or not path
            or type(pin) is not str
            or not _SHA256_RE.fullmatch(pin)
            for path, pin in context["frame_source_pins"].items()
        )
        or any(
            type(context[key]) is not bool
            for key in (
                "source_authenticity_verified",
                "account_binding_verified",
                "source_closure_verified",
                "root_postverify_verified",
            )
        )
    ):
        raise C01RootFormalAdjudicationError("root_invocation_context_invalid")


def _source_subset(source: Mapping[str, Any], pins: Mapping[str, str]) -> Mapping[str, Any]:
    if type(pins) not in (dict, MappingProxyType) or not pins or not set(pins).issubset(source):
        raise C01RootFormalAdjudicationError("frame_source_subset_invalid")
    return MappingProxyType({path: source[path] for path in pins})


def _complete_content(content: Any) -> bool:
    return bool(
        type(getattr(content, "request_count", None)) is int
        and content.request_count == 8
        and type(getattr(content, "auth_login_callback_count", None)) is int
        and content.auth_login_callback_count == 2
        and type(getattr(content, "query_request_count", None)) is int
        and content.query_request_count == 6
        and type(getattr(content, "query_callback_count", None)) is int
        and 6 <= content.query_callback_count <= 8
        and type(getattr(content, "snapshot_count", None)) is int
        and content.snapshot_count == 2
        and type(getattr(content, "activity_callback_count", None)) is int
        and content.activity_callback_count == 0
        and type(getattr(content, "write_invocation_count", None)) is int
        and content.write_invocation_count == 0
        and type(getattr(content, "requests", None)) is tuple
        and len(content.requests) == 8
        and type(getattr(content, "callbacks", None)) is tuple
        and len(content.callbacks) >= 8
        and type(getattr(content, "query_receipts", None)) is tuple
        and len(content.query_receipts) == 6
        and type(getattr(content, "_snapshot_facts", None)) is tuple
        and len(content._snapshot_facts) == 2
        and content.native_close_complete is True
        and content.native_released is True
        and content.native_thread_alive is False
        and content.native_timed_out is False
    )


def _same_content(left: Any, right: Any) -> bool:
    private_fields = (
        "_content_commitment_sha256",
        "_baseline_artifact_sha256",
        "_final_artifact_sha256",
    )
    if any(getattr(left, name, None) != getattr(right, name, None) for name in private_fields):
        return False
    return (
        left.requests == right.requests
        and left.callbacks == right.callbacks
        and left.query_receipts == right.query_receipts
        and left._snapshot_facts == right._snapshot_facts
        and left.safe_summary() == right.safe_summary()
    )


__all__ = [
    "C01RootFormalAdjudicationError",
    "C01RootFormalPassEvidence",
    "C01RootFormalPassProof",
    "consume_c01_root_formal_pass_proof",
    "mint_c01_root_formal_pass_proof",
    "validate_c01_formal_pass_evidence",
]
