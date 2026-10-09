"""Consume one Root-adjudicated C01 proof at the registered entry boundary.

The pre-existing tracker, decision engine, and completion evaluator remain
fail-closed. This small seam accepts only the exact one-use proof type from the
fixed Root adjudicator source and returns a finite C01 result after that proof
has been consumed. It never promotes a caller-supplied count, dict, flag, or
source-fake object.
"""

from __future__ import annotations

import re
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping


_ADJUDICATOR_PATH = "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py"
# Exact public source pin for the Root adjudicator used by this completion
# adapter.  The parent source lease independently retains and checks both
# modules before the one-use proof is consumed.
_ADJUDICATOR_SHA256 = "743e9507157092d7f3c9b284e5775d895cbe42c1caf1da6fb9e1cbb8e1eb2db7"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESULT_FACTORY = object()


class C01RootCompletionError(ValueError):
    """Fixed-code rejection from the Root formal-completion boundary."""

    def __init__(self, code: str = "root_formal_completion_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "root_formal_completion_blocked"
        super().__init__(code)
        self.code = code


class C01FormalCompletionResult:
    """Finite formal result produced only after proof consumption."""

    __slots__ = (
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "formal_c01_pass",
        "official_c01_pass_count",
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

    def __init__(self, *, values: dict[str, Any], _factory: Any = None) -> None:
        if _factory is not _RESULT_FACTORY or type(values) is not dict:
            raise C01RootCompletionError("formal_result_factory_required")
        exact = {
            "case_id",
            "certification",
            "mode",
            "profile",
            "reason",
            "write_policy",
            "writes",
            "formal_c01_pass",
            "official_c01_pass_count",
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
        if set(values) != exact:
            raise C01RootCompletionError("formal_result_invalid")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _RESULT_FACTORY)

    def __repr__(self) -> str:
        return "C01FormalCompletionResult(<Root proof consumed; private fields omitted>)"

    def to_dict(self) -> dict[str, Any]:
        if self._factory is not _RESULT_FACTORY:
            raise C01RootCompletionError("formal_result_invalid")
        self._validate()
        return {
            "case_id": self.case_id,
            "certification": self.certification,
            "mode": self.mode,
            "profile": self.profile,
            "reason": self.reason,
            "write_policy": self.write_policy,
            "writes": self.writes,
            "formal_c01_pass": self.formal_c01_pass,
            "official_c01_pass_count": self.official_c01_pass_count,
            "request_count": self.request_count,
            "query_callback_count": self.query_callback_count,
            "snapshot_count": self.snapshot_count,
            "write_invocation_count": self.write_invocation_count,
            "source_authenticity_verified": self.source_authenticity_verified,
            "account_binding_verified": self.account_binding_verified,
            "source_closure_verified": self.source_closure_verified,
            "root_postverify_verified": self.root_postverify_verified,
            "outer_postverify_verified": self.outer_postverify_verified,
            "outer_close_verified": self.outer_close_verified,
            "cleanup_verified": self.cleanup_verified,
        }

    def exit_code(self) -> int:
        self._validate()
        return 0

    def _validate(self) -> None:
        if (
            self._factory is not _RESULT_FACTORY
            or self.case_id != "C01"
            or self.certification != "PASS"
            or self.mode != "C01_NATIVE_TD_READ_V20"
            or self.profile != "C01_NATIVE_TD_READ_V20"
            or self.reason != "root_formal_proof_consumed"
            or self.write_policy != "NO_WRITE"
            or type(self.writes) is not int
            or self.writes != 0
            or self.formal_c01_pass is not True
            or type(self.official_c01_pass_count) is not int
            or self.official_c01_pass_count != 1
            or type(self.request_count) is not int
            or self.request_count != 8
            or type(self.query_callback_count) is not int
            or not 6 <= self.query_callback_count <= 8
            or type(self.snapshot_count) is not int
            or self.snapshot_count != 2
            or type(self.write_invocation_count) is not int
            or self.write_invocation_count != 0
            or any(
                getattr(self, key) is not True
                for key in (
                    "source_authenticity_verified",
                    "account_binding_verified",
                    "source_closure_verified",
                    "root_postverify_verified",
                    "outer_postverify_verified",
                    "outer_close_verified",
                    "cleanup_verified",
                )
            )
        ):
            raise C01RootCompletionError("formal_result_invalid")


def consume_c01_root_formal_pass(
    proof: Any,
    *,
    adjudicator_module: ModuleType,
    adjudicator_source_objects: Mapping[str, Any],
) -> C01FormalCompletionResult:
    """Consume the exact one-use Root proof and project its finite result.

    The caller must pass the module and object map from the same held source
    closure. The fixed source digest is maintained here as a second binding;
    the sentinel blocks use until an independently reviewed adjudicator is
    frozen.
    """

    _validate_adjudicator_module(adjudicator_module, adjudicator_source_objects)
    proof_type = adjudicator_module.__dict__.get("C01RootFormalPassProof")
    evidence_type = adjudicator_module.__dict__.get("C01RootFormalPassEvidence")
    consume = _captured_function(
        adjudicator_module,
        adjudicator_source_objects,
        "consume_c01_root_formal_pass_proof",
    )
    validate = _captured_function(
        adjudicator_module,
        adjudicator_source_objects,
        "validate_c01_formal_pass_evidence",
    )
    if type(proof_type) is not type or type(proof) is not proof_type:
        raise C01RootCompletionError("formal_proof_type_invalid")
    if getattr(proof, "_factory", None) is not getattr(adjudicator_module, "_FACTORY", None):
        raise C01RootCompletionError("formal_proof_factory_invalid")
    try:
        evidence = consume(proof)
    except Exception:
        raise C01RootCompletionError("formal_proof_consumption_failed") from None
    if (
        type(evidence_type) is not type
        or type(evidence) is not evidence_type
        or validate(evidence) is not True
    ):
        raise C01RootCompletionError("formal_evidence_invalid")
    return C01FormalCompletionResult(
        values={
            "case_id": "C01",
            "certification": "PASS",
            "mode": "C01_NATIVE_TD_READ_V20",
            "profile": "C01_NATIVE_TD_READ_V20",
            "reason": "root_formal_proof_consumed",
            "write_policy": "NO_WRITE",
            "writes": 0,
            "formal_c01_pass": True,
            "official_c01_pass_count": 1,
            "request_count": evidence.request_count,
            "query_callback_count": evidence.query_callback_count,
            "snapshot_count": evidence.snapshot_count,
            "write_invocation_count": evidence.write_invocation_count,
            "source_authenticity_verified": True,
            "account_binding_verified": True,
            "source_closure_verified": True,
            "root_postverify_verified": True,
            "outer_postverify_verified": True,
            "outer_close_verified": True,
            "cleanup_verified": True,
        },
        _factory=_RESULT_FACTORY,
    )


def _validate_adjudicator_module(module: ModuleType, objects: Mapping[str, Any]) -> None:
    if (
        type(module) is not ModuleType
        or module.__name__
        != "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"
        or type(module.__dict__.get("__file__")) is not str
        or not _source_path_matches(module.__dict__["__file__"], _ADJUDICATOR_PATH)
        or type(module.__dict__.get("__c01_source_sha256__")) is not str
        or not _SHA256_RE.fullmatch(module.__dict__["__c01_source_sha256__"])
        or _ADJUDICATOR_SHA256 == "0" * 64
        or module.__dict__["__c01_source_sha256__"] != _ADJUDICATOR_SHA256
        or type(objects) not in (dict, MappingProxyType)
    ):
        raise C01RootCompletionError("adjudicator_source_invalid")
    for name, expected in objects.items():
        current = _resolve_adjudicator_object(module, name)
        if current is not expected:
            raise C01RootCompletionError("adjudicator_object_binding_invalid")


def _resolve_adjudicator_object(module: ModuleType, name: str) -> Any:
    if name == "__module_object__":
        return module
    suffix = next(
        (
            item
            for item in (".__code__", ".__globals__", ".__func__")
            if name.endswith(item)
        ),
        None,
    )
    base_name = name[: -len(suffix)] if suffix else name
    current: Any = module.__dict__.get(base_name.split(".", 1)[0])
    for part in base_name.split(".")[1:]:
        if type(current) is type:
            current = current.__dict__.get(part)
        elif isinstance(current, (classmethod, staticmethod)) and part == "__func__":
            current = current.__func__
        elif isinstance(current, property) and part in {"fget", "fset", "fdel"}:
            current = getattr(current, part)
        else:
            return None
        if current is None:
            return None
    if suffix == ".__func__":
        return current.__func__ if isinstance(current, (classmethod, staticmethod)) else None
    if isinstance(current, (classmethod, staticmethod)):
        current = current.__func__
    if suffix == ".__code__":
        return current.__code__ if type(current) is FunctionType else None
    if suffix == ".__globals__":
        return current.__globals__ if type(current) is FunctionType else None
    return current


def _captured_function(
    module: ModuleType,
    objects: Mapping[str, Any],
    name: str,
) -> FunctionType:
    function = module.__dict__.get(name)
    if (
        type(function) is not FunctionType
        or function is not objects.get(name)
        or function.__code__ is not objects.get(name + ".__code__")
        or function.__globals__ is not module.__dict__
        or function.__module__ != module.__name__
        or function.__qualname__ != name
    ):
        raise C01RootCompletionError("adjudicator_callable_invalid")
    return function


def _source_path_matches(source_path: str, relative: str) -> bool:
    normalized = source_path.replace("\\", "/").casefold()
    target = relative.casefold()
    return normalized == target or normalized.endswith("/" + target)


__all__ = [
    "C01FormalCompletionResult",
    "C01RootCompletionError",
    "consume_c01_root_formal_pass",
]
