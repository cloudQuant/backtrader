"""Same-call custody receipt binding for the V20 C01 RootSeal handoff.

The fixed Root producer must complete its source, runtime, artifact, account,
and process custody checks before it asks this module to mint a receipt.  The
receipt only binds those already-produced checks to one held Root scope and
candidate; it is not a case result or a certification authority.
"""

from __future__ import annotations

from types import FunctionType, ModuleType
from typing import Any


_ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_CUSTODY_PATH = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
_HANDOFF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
_SUPERVISOR_PATH = "backtrader_runtime/certification_simnow_c01_v4_supervisor.py"
_RECEIPT_FACTORY = object()


class C01RootCustodyV17Error(ValueError):
    """Fixed, non-sensitive error code for a same-call custody receipt."""

    def __init__(self, code: str = "root_custody_v17_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "root_custody_v17_blocked"
        self.code = code
        super().__init__(code)


class C01RootContentCustodyReceipt:
    """Factory-only one-call binding to completed Root custody evidence."""

    __slots__ = (
        "scope",
        "pending",
        "candidate_refs",
        "validated_content",
        "namespace_freshness_receipt",
        "custody_evidence",
        "consumed",
        "_nonce",
        "_factory",
    )

    def __init__(
        self,
        scope: Any,
        pending: Any,
        stage: Any,
        custody_evidence: Any,
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _RECEIPT_FACTORY:
            raise C01RootCustodyV17Error("custody_receipt_factory_required")
        if not _valid_context(scope, pending, stage, custody_evidence):
            raise C01RootCustodyV17Error("custody_receipt_binding_invalid")
        self.scope = scope
        self.pending = pending
        self.candidate_refs = stage.candidate_refs
        self.validated_content = stage.validated_content
        self.namespace_freshness_receipt = scope.namespace_freshness_receipt
        self.custody_evidence = custody_evidence
        self.consumed = False
        self._nonce = scope.nonce
        self._factory = _RECEIPT_FACTORY

    def __repr__(self) -> str:
        return "C01RootContentCustodyReceipt(<same-call checks; evidence redacted>)"


def issue_c01_root_content_custody_receipt(
    scope: Any, pending: Any, stage: Any, custody_evidence: Any
) -> C01RootContentCustodyReceipt:
    """Bind Root's completed custody evidence to its exact staged content.

    ``custody_evidence`` is an opaque Root-owned proof bundle.  This function
    does not interpret caller booleans or perform OS access; its trusted caller
    must have completed all physical checks before requesting the receipt.
    """

    if not _valid_context(scope, pending, stage, custody_evidence):
        raise C01RootCustodyV17Error("custody_evidence_unavailable")
    if scope.root_content_custody_receipt is not None:
        raise C01RootCustodyV17Error("custody_receipt_reused")
    receipt = C01RootContentCustodyReceipt(
        scope,
        pending,
        stage,
        custody_evidence,
        _factory=_RECEIPT_FACTORY,
    )
    scope.root_content_custody_receipt = receipt
    if validate_c01_root_content_custody_receipt(receipt, scope, pending, stage) is not True:
        # Retain the uncertain receipt and its evidence; never retry minting.
        raise C01RootCustodyV17Error("custody_receipt_postcheck_failed")
    return receipt


def validate_c01_root_content_custody_receipt(
    receipt: Any, scope: Any, pending: Any, stage: Any
) -> bool:
    """Validate exact receipt, scope, pending result, stage, and source state."""

    try:
        if (
            type(receipt) is not C01RootContentCustodyReceipt
            or receipt._factory is not _RECEIPT_FACTORY
            or receipt.scope is not scope
            or receipt.pending is not pending
            or scope.root_content_custody_receipt is not receipt
            or receipt.candidate_refs is not stage.candidate_refs
            or receipt.validated_content is not stage.validated_content
            or receipt.namespace_freshness_receipt is not scope.namespace_freshness_receipt
            or receipt._nonce is not scope.nonce
            or receipt.consumed is not False
            or not _valid_context(scope, pending, stage, receipt.custody_evidence)
        ):
            return False
        return True
    except Exception:
        return False


def _valid_context(scope: Any, pending: Any, stage: Any, custody_evidence: Any) -> bool:
    try:
        if globals().get("__name__") != "backtrader_runtime.certification_simnow_c01_root_custody_v17":
            return False
        root = getattr(scope, "root_module", None)
        if (
            type(root) is not ModuleType
            or root.__dict__ is not vars(root)
            or root.__dict__.get("C01RootInvocationScope")
            is not scope.__class__
        ):
            return False
        modules = getattr(scope, "verified_source_modules", None)
        objects = getattr(scope, "verified_source_objects", None)
        if (
            type(modules) is not dict
            or type(objects) is not dict
            or modules.get(_ROOT_PATH) is not root
            or modules.get(_CUSTODY_PATH) is None
            or modules.get(_SUPERVISOR_PATH) is None
            or modules[_CUSTODY_PATH].__dict__ is not globals()
            or getattr(scope, "root_custody_module", None) is not modules[_CUSTODY_PATH]
            or objects[_CUSTODY_PATH].get("C01RootContentCustodyReceipt")
            is not C01RootContentCustodyReceipt
            or objects[_CUSTODY_PATH].get("validate_c01_root_content_custody_receipt")
            is not validate_c01_root_content_custody_receipt
            or objects[_CUSTODY_PATH].get(
                "validate_c01_root_content_custody_receipt.__code__"
            )
            is not validate_c01_root_content_custody_receipt.__code__
        ):
            return False
        root_objects = objects.get(_ROOT_PATH)
        if type(root_objects) not in (dict, type(objects[_CUSTODY_PATH])):
            return False
        verify_freshness = root_objects.get("verify_namespace_freshness_receipt")
        validate_candidate = root_objects.get("validate_c01_candidate_refs")
        if (
            type(verify_freshness) is not FunctionType
            or type(validate_candidate) is not FunctionType
            or root.__dict__.get("verify_namespace_freshness_receipt") is not verify_freshness
            or root.__dict__.get("validate_c01_candidate_refs") is not validate_candidate
            or verify_freshness.__code__
            is not root_objects.get("verify_namespace_freshness_receipt.__code__")
            or validate_candidate.__code__
            is not root_objects.get("validate_c01_candidate_refs.__code__")
            or verify_freshness(scope, scope.namespace_freshness_receipt) is not True
            or scope.active is not True
            or scope.issuer_returned is not True
            or scope.consumed is not False
            or scope.pending is not pending
            or type(pending) is not root_objects.get("C01CandidatePendingRootAdmission")
            or pending._scope is not scope
            or pending._nonce is not scope.nonce
            or pending._refs is not scope.candidate_refs
            or scope.candidate_refs is not stage.candidate_refs
            or scope.root_content_stage is not stage
            or type(stage) is not modules[_HANDOFF_PATH].__dict__.get("C01RootContentStage")
            or stage.scope is not scope
            or stage._factory
            is not objects[_HANDOFF_PATH].get("_STAGE_FACTORY")
            or stage.validated_content is not scope.validated_content
            or type(scope.candidate_refs) is not tuple
            or len(scope.candidate_refs) != 5
            or custody_evidence is not scope.candidate_refs[2]
            or type(custody_evidence)
            is not objects[_SUPERVISOR_PATH].get("C01SupervisorResult")
            or validate_candidate(scope, scope.candidate_refs) is not True
        ):
            return False
        return verify_freshness(scope, scope.namespace_freshness_receipt) is True
    except Exception:
        return False


__all__ = [
    "C01RootContentCustodyReceipt",
    "C01RootCustodyV17Error",
    "issue_c01_root_content_custody_receipt",
    "validate_c01_root_content_custody_receipt",
]
