"""Root-owned source bindings for the V20 SimNow C01 candidate pipeline.

The module is intentionally small and has no provider, SDK, native, or private
configuration imports.  The fixed Root loader supplies modules that it has
already executed from same-call held byte buffers.  This module derives the
source pins from those buffers and retains exact module, global, function, and
code-object identities for the RootSeal handoff.

Nothing in this module establishes provider authenticity or a certification
PASS.  The pending result is always BLOCKED and the content frame remains
non-authoritative until the independent Root adjudicator completes.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import io
import json
import re
import sys
import tokenize
import uuid
from collections.abc import Mapping
from types import CodeType, FunctionType, MappingProxyType, ModuleType
from typing import Any, Dict, Tuple


_ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_CUSTODY_PATH = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
_HANDOFF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
_VALIDATOR_PATH = "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
_PROTOCOL_PATH = "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
_WORKER_PATH = "backtrader_runtime/certification_simnow_c01_native_v4.py"
_ISSUER_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
_PREDECESSOR_ISSUER_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v19.py"
_SUPERVISOR_PATH = "backtrader_runtime/certification_simnow_c01_v4_supervisor.py"
_FRAME_WRAPPER_PATH = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r1.py"
_FRONT_TRANSPORT_PATH = "backtrader_runtime/certification_simnow_c01_front_transport_v14.py"
_RUNNER_PATH = "examples/000_live_certification/simnow_penetration/cases/C01/run_v20.py"
_OWNER_PATH = "backtrader_runtime/certification_simnow_c01_v7_owner.py"
_ROOT_DRIVER_PATH = "scripts/iteration41_simnow_c01_v20_root_actual_driver_r1.py"
_FORMAL_ADJUDICATOR_PATH = (
    "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py"
)
_FORMAL_COMPLETION_PATH = (
    "examples/000_live_certification/simnow_penetration/common/c01_root_completion_v1.py"
)
_V20_HELPER_PATHS = frozenset(
    {
        "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
        _PROTOCOL_PATH,
        "backtrader_runtime/certification_simnow_c01_v3_contract.py",
        _SUPERVISOR_PATH,
        "backtrader_runtime/certification_roundtrip_private.py",
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        "backtrader_runtime/ctp_front_pair_probe.py",
        "scripts/ctp_000_render_config.py",
        "scripts/ctp_000_paired_front_selector.py",
        "scripts/ctp_000_front_handoff.py",
        "scripts/ctp_i13_i15_outer_watchdog.py",
        "scripts/ctp_i13_i15_windows_job_backend.py",
    }
)
_V20_OWNER_PATH = _OWNER_PATH
_REQUIRED_ROOT_SCOPE_PATHS = frozenset(
    {
        _ROOT_PATH,
        _CUSTODY_PATH,
        _HANDOFF_PATH,
        _VALIDATOR_PATH,
        _PROTOCOL_PATH,
        _WORKER_PATH,
        _ISSUER_PATH,
        _PREDECESSOR_ISSUER_PATH,
        _SUPERVISOR_PATH,
        _FRAME_WRAPPER_PATH,
        _FRONT_TRANSPORT_PATH,
        _RUNNER_PATH,
        _OWNER_PATH,
        *_V20_HELPER_PATHS,
    }
)
_REQUIRED_PARENT_MODULE_PATHS = frozenset(
    _REQUIRED_ROOT_SCOPE_PATHS
    | {_ROOT_DRIVER_PATH, _FORMAL_ADJUDICATOR_PATH, _FORMAL_COMPLETION_PATH}
)
_FIXED_SOURCE_PINS = MappingProxyType({
    _VALIDATOR_PATH: "4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a",
    _PROTOCOL_PATH: "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160",
    _WORKER_PATH: "66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66",
    _ISSUER_PATH: "7118ed43cdc012181546f54f7b302ee51d3704860c5746807217c35087257f71",
    _PREDECESSOR_ISSUER_PATH: "3de1024b233a0eee55fba7c30df69f04afa38746c9a0e88996e0db7df283fd40",
    _OWNER_PATH: "ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9",
    _FRONT_TRANSPORT_PATH: "aa281e122ae4c1e79022dd5b1a9fcbc0afd51f0282aa0e6587671b0d15f8b3a8",
    _RUNNER_PATH: "a2fed5ca72c61ab03795963f3d08f0575972d571fc4ddca7e7f1f79f9645926b",
    "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494",
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": "19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0",
    _SUPERVISOR_PATH: "daf2cf99cbc5d977e27f59efb0f27087abdf3493c9d959d5c3d253744f869da1",
    _FORMAL_COMPLETION_PATH: "1d5e1183368b5bb1c4363056673a483d21e6e02b1bf342b6ac69b12a9b891f90",
    "backtrader_runtime/certification_roundtrip_private.py": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
    "backtrader_runtime/ctp_front_pair_probe.py": "d6f92c7d2f6df13480cebcee2c7f864ac305d34d4cda37d1a22c466932d2905f",
    "scripts/ctp_000_render_config.py": "34bf2a99872f43f0d915bafcb0284827a8ac0c4baf70a2ce5f1046888223eac9",
    "scripts/ctp_000_paired_front_selector.py": "08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb",
    "scripts/ctp_000_front_handoff.py": "b08e70e723a5d31f18809129387455dfee3645e6ad9f2b516d7aa2789ffd19f7",
    "scripts/ctp_i13_i15_outer_watchdog.py": "31c945c77c7e147a296e66f4f1ec075e0a23f1a88b94fd339884268e79ca251c",
    "scripts/ctp_i13_i15_windows_job_backend.py": "2566dd55d1a96285473850b1e2c63174696347da56e07d69fb72aa3a6285e381",
})
_EXPECTED_MODULE_NAMES = {
    _ROOT_PATH: "backtrader_runtime.certification_simnow_c01_root_v17",
    _CUSTODY_PATH: "backtrader_runtime.certification_simnow_c01_root_custody_v17",
    _HANDOFF_PATH: "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1",
    _VALIDATOR_PATH: "common.c01_root_ledger_v1",
    _PROTOCOL_PATH: "backtrader_runtime.certification_simnow_c01_v3_protocol",
    _WORKER_PATH: "backtrader_runtime.certification_simnow_c01_native_v4",
    _PREDECESSOR_ISSUER_PATH: "backtrader_runtime.certification_simnow_c01_native_td_read_v19",
    _SUPERVISOR_PATH: "backtrader_runtime.certification_simnow_c01_v4_supervisor",
    _FRAME_WRAPPER_PATH: "scripts.run_simnow_c01_native_td_read_v20_root_activation_r1",
    _FRONT_TRANSPORT_PATH: "backtrader_runtime.certification_simnow_c01_front_transport_v14",
    _RUNNER_PATH: "examples.000_live_certification.simnow_penetration.cases.C01.run_v20",
    _OWNER_PATH: "backtrader_runtime._c01_native_td_read_v7_owner",
    "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py": "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
    "backtrader_runtime/certification_simnow_c01_v3_contract.py": "backtrader_runtime.certification_simnow_c01_v3_contract",
    "backtrader_runtime/certification_roundtrip_private.py": "backtrader_runtime.certification_roundtrip_private",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": "backtrader_runtime.certification_binance_roundtrip_r3_cli",
    "backtrader_runtime/ctp_front_pair_probe.py": "backtrader_runtime.ctp_front_pair_probe",
    "scripts/ctp_000_render_config.py": "scripts.ctp_000_render_config",
    "scripts/ctp_000_paired_front_selector.py": "scripts.ctp_000_paired_front_selector",
    "scripts/ctp_000_front_handoff.py": "scripts.ctp_000_front_handoff",
    "scripts/ctp_i13_i15_outer_watchdog.py": "scripts.ctp_i13_i15_outer_watchdog",
    "scripts/ctp_i13_i15_windows_job_backend.py": "scripts.ctp_i13_i15_windows_job_backend",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SCOPE_FACTORY = object()
_NAMESPACE_FACTORY = object()
_PENDING_FACTORY = object()
_FRAME_WRITER_FACTORY = object()
_INVOCATION_RECEIPT_FACTORY = object()
_USED_GENERATIONS = set()
_USED_ROOT_CALL_NONCES = set()
_USED_ROOT_INVOCATION_IDS = set()
_USED_ROOT_NAMESPACE_GENERATIONS = set()
_RETAINED_ROOT_INVOCATION_RECEIPTS = []
_MISSING_MODULE = object()


class C01RootV17Error(ValueError):
    """Fixed, non-sensitive error code for the C01 Root ownership bridge."""

    def __init__(self, code: str = "root_v17_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "root_v17_blocked"
        self.code = code
        super().__init__(code)


class C01NamespaceFreshnessReceipt:
    """Factory-only binding to one newly created Root invocation namespace."""

    __slots__ = (
        "generation",
        "_scope",
        "_nonce",
        "_module_map",
        "_object_map",
        "_source_bytes",
        "_source_pins",
        "_source_pin_items",
        "_module_bindings",
        "_function_states",
        "_factory",
    )

    def __init__(self, scope: "C01RootInvocationScope", generation: str, *, _factory: Any = None):
        if _factory is not _NAMESPACE_FACTORY:
            raise C01RootV17Error("namespace_receipt_factory_required")
        if type(scope) is not C01RootInvocationScope or type(generation) is not str:
            raise C01RootV17Error("namespace_receipt_binding_invalid")
        self.generation = generation
        self._scope = scope
        self._nonce = scope.nonce
        self._module_map = scope.verified_source_modules
        self._object_map = scope.verified_source_objects
        self._source_bytes = scope.held_source_bytes
        self._source_pins = scope.source_pins
        self._source_pin_items = scope.source_pin_items
        self._module_bindings = scope.verified_source_module_bindings
        self._function_states = scope._function_state_snapshot
        self._factory = _NAMESPACE_FACTORY

    def __repr__(self) -> str:
        return "C01NamespaceFreshnessReceipt(<same-call source namespace>)"


class C01CandidatePendingRootAdmission:
    """One-use BLOCKED result correlated to the exact staged V20 candidate."""

    __slots__ = ("status", "reason", "profile", "case_id", "writes", "_scope", "_nonce", "_refs", "_factory")

    def __init__(self, scope: "C01RootInvocationScope", refs: tuple, *, _factory: Any = None):
        if _factory is not _PENDING_FACTORY:
            raise C01RootV17Error("pending_result_factory_required")
        if (
            type(scope) is not C01RootInvocationScope
            or scope.issuer_returned is not True
            or scope.pending is not None
            or scope.consumed is not False
            or type(refs) is not tuple
            or scope.candidate_refs is not refs
        ):
            raise C01RootV17Error("pending_result_binding_invalid")
        self.status = "BLOCKED"
        self.reason = "candidate_complete_pending_root_admission"
        self.profile = "C01_NATIVE_TD_READ_V20"
        self.case_id = "C01"
        self.writes = 0
        self._scope = scope
        self._nonce = scope.nonce
        self._refs = refs
        self._factory = _PENDING_FACTORY

    def __repr__(self) -> str:
        return "C01CandidatePendingRootAdmission(<BLOCKED; private references redacted>)"

    def to_dict(self) -> Dict[str, Any]:
        if self._factory is not _PENDING_FACTORY:
            raise C01RootV17Error("pending_result_invalid")
        return {
            "case_id": "C01",
            "profile": "C01_NATIVE_TD_READ_V20",
            "status": "BLOCKED",
            "reason": "candidate_complete_pending_root_admission",
            "writes": 0,
            "case_receipt_authority": "none",
        }


class C01RootContentFrameWriter:
    """Root-issued one-use capability for the fixed child-to-Root frame pipe."""

    __slots__ = (
        "_scope",
        "_stream",
        "_channel_receipt",
        "_channel",
        "_channel_nonce",
        "_channel_process_id",
        "_channel_direction",
        "_nonce",
        "_used",
        "_factory",
    )

    def __init__(
        self,
        scope: "C01RootInvocationScope",
        stream: io.FileIO,
        channel_receipt: Any,
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _FRAME_WRITER_FACTORY:
            raise C01RootV17Error("frame_writer_factory_required")
        if (
            type(scope) is not C01RootInvocationScope
            or scope.active is not True
            or scope.consumed is not False
            or type(stream) is not io.FileIO
            or stream.closed
            or not stream.writable()
        ):
            raise C01RootV17Error("frame_writer_binding_invalid")
        self._scope = scope
        self._stream = stream
        self._channel_receipt = channel_receipt
        self._channel = channel_receipt.channel
        self._channel_nonce = channel_receipt.nonce
        self._channel_process_id = channel_receipt.process_id
        self._channel_direction = channel_receipt.direction
        self._nonce = scope.nonce
        self._used = False
        self._factory = _FRAME_WRITER_FACTORY

    def __repr__(self) -> str:
        return "C01RootContentFrameWriter(<one-use Root pipe capability>)"


class C01RootInvocationScope:
    """Held source and one-use candidate state for a single Root call.

    The public maps have the exact shapes consumed by RootSeal.  Their backing
    objects are retained privately and rechecked before every exported API
    operation.  Dynamic modules need not be present in ``sys.modules``.
    """

    __slots__ = (
        "root_module",
        "root_custody_module",
        "verified_source_modules",
        "verified_source_objects",
        "verified_source_module_bindings",
        "held_source_bytes",
        "source_pins",
        "source_pin_items",
        "namespace_generation",
        "namespace_freshness_receipt",
        "invocation_id",
        "expected_worker_source_sha256",
        "nonce",
        "active",
        "issuer_returned",
        "candidate_refs",
        "pending",
        "stage_count",
        "validated_content",
        "root_content_stage",
        "root_content_seal",
        "content_frame_sent",
        "consumed",
        "root_content_custody_receipt",
        "_root_module_ref",
        "_custody_module_ref",
        "_module_map_ref",
        "_object_map_ref",
        "_module_bindings_ref",
        "_function_state_snapshot",
        "_source_bytes_ref",
        "_source_pins_ref",
        "_source_pin_items_ref",
        "_namespace_generation_ref",
        "_frame_writer",
        "_factory",
    )

    def __init__(
        self,
        root_module: ModuleType,
        source_modules: Dict[str, ModuleType],
        source_objects: Dict[str, Mapping[str, Any]],
        source_bytes: Mapping[str, bytes],
        source_pins: Mapping[str, str],
        generation: str,
        invocation_id: str,
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _SCOPE_FACTORY:
            raise C01RootV17Error("root_scope_factory_required")
        self.root_module = root_module
        self.root_custody_module = source_modules[_CUSTODY_PATH]
        self.verified_source_modules = source_modules
        self.verified_source_objects = source_objects
        self.verified_source_module_bindings = MappingProxyType(
            {
                relative: (
                    module.__name__,
                    module.__file__,
                    module.__package__,
                    module.__dict__,
                    module.__dict__.get("__c01_source_sha256__"),
                )
                for relative, module in source_modules.items()
            }
        )
        self._function_state_snapshot = _capture_module_function_states(source_modules)
        self.held_source_bytes = source_bytes
        self.source_pins = source_pins
        self.source_pin_items = tuple(sorted(source_pins.items()))
        self.namespace_generation = generation
        self.invocation_id = invocation_id
        self.expected_worker_source_sha256 = source_pins[_WORKER_PATH]
        self.nonce = object()
        self.active = True
        self.issuer_returned = False
        self.candidate_refs = None
        self.pending = None
        self.stage_count = 0
        self.validated_content = None
        self.root_content_stage = None
        self.root_content_seal = None
        self.content_frame_sent = False
        self.consumed = False
        self.root_content_custody_receipt = None
        self._root_module_ref = root_module
        self._custody_module_ref = source_modules[_CUSTODY_PATH]
        self._module_map_ref = source_modules
        self._object_map_ref = source_objects
        self._module_bindings_ref = self.verified_source_module_bindings
        self._source_bytes_ref = source_bytes
        self._source_pins_ref = source_pins
        self._source_pin_items_ref = self.source_pin_items
        self._namespace_generation_ref = generation
        self._frame_writer = None
        self._factory = _SCOPE_FACTORY
        self.namespace_freshness_receipt = C01NamespaceFreshnessReceipt(
            self, generation, _factory=_NAMESPACE_FACTORY
        )

    def __repr__(self) -> str:
        state = "active" if self.active else "closed"
        return "C01RootInvocationScope(<{}; source and candidate references redacted>)".format(
            state
        )


class C01RootInvocationReceipt:
    """Factory-only parent receipt for the closed child frame and source lease."""

    __slots__ = (
        "frame",
        "parent_process_receipt",
        "wrapper_call_receipt",
        "outer_close_receipt",
        "source_modules",
        "source_objects",
        "source_pins",
        "held_source_bytes",
        "source_pin_items",
        "frame_source_pin_items",
        "call_nonce",
        "invocation_id",
        "namespace_generation",
        "worker_source_sha256",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "_frame_ref",
        "_process_receipt_ref",
        "_wrapper_receipt_ref",
        "_outer_receipt_ref",
        "_source_modules_ref",
        "_source_objects_ref",
        "_source_pins_ref",
        "_source_bytes_ref",
        "_call_nonce_ref",
        "_invocation_id_ref",
        "_namespace_generation_ref",
        "_worker_source_sha256_ref",
        "_pair_binding_items",
        "_account_scope_sha256_ref",
        "_credential_binding_sha256_ref",
        "_factory",
    )

    def __init__(
        self,
        *,
        frame: Any,
        parent_process_receipt: Any,
        wrapper_call_receipt: Any,
        outer_close_receipt: Any,
        source_modules: Mapping[str, ModuleType],
        source_objects: Mapping[str, Mapping[str, Any]],
        source_pins: Mapping[str, str],
        held_source_bytes: Mapping[str, bytes],
        metadata: Mapping[str, Any],
        call_nonce: object,
        _factory: Any = None,
    ) -> None:
        if _factory is not _INVOCATION_RECEIPT_FACTORY:
            raise C01RootV17Error("invocation_receipt_factory_required")
        if type(metadata) is not dict or type(call_nonce) is not object:
            raise C01RootV17Error("invocation_receipt_binding_invalid")
        invocation_id = metadata["invocation_id"]
        namespace_generation = metadata["namespace_generation"]
        worker_source_sha256 = metadata["worker_source_sha256"]
        pair_binding = MappingProxyType(dict(metadata["pair_binding"]))
        account_scope_sha256 = metadata["account_scope_sha256"]
        credential_binding_sha256 = metadata["credential_binding_sha256"]
        source_pin_items = tuple(sorted(source_pins.items()))
        frame_source_pin_items = tuple(sorted(metadata["source_pins"].items()))
        values = {
            "frame": frame,
            "parent_process_receipt": parent_process_receipt,
            "wrapper_call_receipt": wrapper_call_receipt,
            "outer_close_receipt": outer_close_receipt,
            "source_modules": source_modules,
            "source_objects": source_objects,
            "source_pins": source_pins,
            "held_source_bytes": held_source_bytes,
            "source_pin_items": source_pin_items,
            "frame_source_pin_items": frame_source_pin_items,
            "call_nonce": call_nonce,
            "invocation_id": invocation_id,
            "namespace_generation": namespace_generation,
            "worker_source_sha256": worker_source_sha256,
            "pair_binding": pair_binding,
            "account_scope_sha256": account_scope_sha256,
            "credential_binding_sha256": credential_binding_sha256,
            "_frame_ref": frame,
            "_process_receipt_ref": parent_process_receipt,
            "_wrapper_receipt_ref": wrapper_call_receipt,
            "_outer_receipt_ref": outer_close_receipt,
            "_source_modules_ref": source_modules,
            "_source_objects_ref": source_objects,
            "_source_pins_ref": source_pins,
            "_source_bytes_ref": held_source_bytes,
            "_call_nonce_ref": call_nonce,
            "_invocation_id_ref": invocation_id,
            "_namespace_generation_ref": namespace_generation,
            "_worker_source_sha256_ref": worker_source_sha256,
            "_pair_binding_items": tuple(pair_binding.items()),
            "_account_scope_sha256_ref": account_scope_sha256,
            "_credential_binding_sha256_ref": credential_binding_sha256,
            "_factory": _INVOCATION_RECEIPT_FACTORY,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01RootInvocationReceipt is immutable")

    def __repr__(self) -> str:
        return "C01RootInvocationReceipt(<closed same-call source lease; bindings redacted>)"


def create_c01_root_invocation_scope(
    root_module: ModuleType,
    held_source_modules: Dict[str, ModuleType],
    held_source_bytes: Dict[str, bytes],
) -> C01RootInvocationScope:
    """Create a scope from the exact modules and byte buffers held by Root.

    ``held_source_modules`` and ``held_source_bytes`` must have identical
    repository-relative keys.  The pins are calculated here from the bytes;
    caller-supplied pins, module markers, and ``sys.modules`` are not accepted
    as authority.  The fixed V20 admission owner, accepted V19 predecessor,
    and V4 supervisor are also
    held so candidate object classes can be checked against their source.
    """

    if type(root_module) is not ModuleType or root_module.__dict__ is not globals():
        raise C01RootV17Error("root_module_unbound")
    if (
        type(held_source_modules) is not dict
        or type(held_source_bytes) is not dict
        or not _REQUIRED_ROOT_SCOPE_PATHS.issubset(held_source_modules)
        or not set(held_source_modules).issubset(_REQUIRED_ROOT_SCOPE_PATHS)
        or set(held_source_modules) != set(held_source_bytes)
    ):
        raise C01RootV17Error("source_closure_invalid")

    modules: Dict[str, ModuleType] = {}
    raw_sources: Dict[str, bytes] = {}
    pins: Dict[str, str] = {}
    for relative in sorted(held_source_modules):
        _validate_relative_path(relative)
        module = held_source_modules[relative]
        raw = held_source_bytes[relative]
        if (
            type(module) is not ModuleType
            or module.__dict__ is not vars(module)
            or type(raw) is not bytes
            or not raw
            or type(module.__name__) is not str
            or type(module.__file__) is not str
            or not _module_file_matches(module.__file__, relative)
            or (
                module.__package__ != module.__name__.rpartition(".")[0]
                and not (
                    relative in {_ISSUER_PATH, _OWNER_PATH}
                    and module.__package__ in ("", "backtrader_runtime")
                )
            )
        ):
            raise C01RootV17Error("source_module_binding_invalid")
        expected_name = _EXPECTED_MODULE_NAMES.get(relative)
        if expected_name is not None and module.__name__ != expected_name:
            raise C01RootV17Error("source_module_name_invalid")
        if relative == _ISSUER_PATH and module.__name__ not in (
            "backtrader_runtime.certification_simnow_c01_native_td_read_v20",
            "_c01_front_transport_v14_v20_source",
        ):
            raise C01RootV17Error("source_module_name_invalid")
        digest = hashlib.sha256(raw).hexdigest()
        if _FIXED_SOURCE_PINS.get(relative, digest) != digest:
            raise C01RootV17Error("source_bytes_unaccepted")
        if module.__dict__.get("__c01_source_sha256__") != digest:
            raise C01RootV17Error("source_module_bytes_mismatch")
        if not _validate_module_functions(module, relative, raw):
            raise C01RootV17Error("source_code_binding_invalid")
        modules[relative] = module
        raw_sources[relative] = raw
        pins[relative] = digest

    if modules[_ROOT_PATH] is not root_module:
        raise C01RootV17Error("root_module_binding_invalid")
    if (
        modules[_PROTOCOL_PATH].__dict__.get("C01PairBinding") is None
        or modules[_PROTOCOL_PATH].__dict__.get("C01CandidateValidation") is None
        or modules[_ISSUER_PATH].__dict__.get("_C01V20Admission") is None
        or modules[_ISSUER_PATH].__dict__.get("C01NativeTdReadV20Result") is None
        or modules[_PREDECESSOR_ISSUER_PATH].__dict__.get("_C01V19Admission") is None
        or modules[_SUPERVISOR_PATH].__dict__.get("C01SupervisorResult") is None
    ):
        raise C01RootV17Error("candidate_type_sources_missing")

    object_maps = {
        relative: MappingProxyType(_capture_module_objects(module))
        for relative, module in modules.items()
    }
    immutable_bytes = MappingProxyType(raw_sources)
    immutable_pins = MappingProxyType(pins)
    generation, invocation_id = _fresh_ids()
    scope = C01RootInvocationScope(
        root_module,
        modules,
        object_maps,
        immutable_bytes,
        immutable_pins,
        generation,
        invocation_id,
        _factory=_SCOPE_FACTORY,
    )
    if verify_namespace_freshness_receipt(scope, scope.namespace_freshness_receipt) is not True:
        raise C01RootV17Error("namespace_initialization_failed")
    return scope


def verify_namespace_freshness_receipt(
    scope: Any, receipt: Any
) -> bool:
    """Return true only for the exact fresh receipt and unchanged held source."""

    try:
        if (
            type(scope) is not C01RootInvocationScope
            or scope._factory is not _SCOPE_FACTORY
            or type(receipt) is not C01NamespaceFreshnessReceipt
            or receipt._factory is not _NAMESPACE_FACTORY
            or receipt._scope is not scope
            or receipt._nonce is not scope.nonce
            or receipt._module_map is not scope.verified_source_modules
            or receipt._object_map is not scope.verified_source_objects
            or receipt._source_bytes is not scope.held_source_bytes
            or receipt._source_pins is not scope.source_pins
            or receipt._source_pin_items is not scope.source_pin_items
            or receipt._module_bindings is not scope.verified_source_module_bindings
            or receipt._function_states is not scope._function_state_snapshot
            or receipt.generation is not scope.namespace_generation
            or scope.namespace_generation is not scope._namespace_generation_ref
            or scope.root_module is not scope._root_module_ref
            or scope.root_custody_module is not scope._custody_module_ref
            or scope.verified_source_modules is not scope._module_map_ref
            or scope.verified_source_objects is not scope._object_map_ref
            or scope.verified_source_module_bindings is not scope._module_bindings_ref
            or scope.held_source_bytes is not scope._source_bytes_ref
            or scope.source_pins is not scope._source_pins_ref
            or scope.source_pin_items is not scope._source_pin_items_ref
            or type(scope.verified_source_modules) is not dict
            or type(scope.verified_source_objects) is not dict
            or type(scope.verified_source_module_bindings) is not MappingProxyType
            or type(scope.held_source_bytes) is not MappingProxyType
            or type(scope.source_pins) is not MappingProxyType
            or type(scope.source_pin_items) is not tuple
            or type(scope.namespace_generation) is not str
            or not scope.namespace_generation
            or type(scope.invocation_id) is not str
            or not _CALL_ID_RE.fullmatch(scope.invocation_id)
            or receipt.generation != scope.namespace_generation
            or tuple(sorted(scope.source_pins.items())) != scope.source_pin_items
            or set(scope.verified_source_modules) != set(scope.source_pins)
            or set(scope.verified_source_objects) != set(scope.source_pins)
            or set(scope.verified_source_module_bindings) != set(scope.source_pins)
            or set(scope.held_source_bytes) != set(scope.source_pins)
        ):
            return False
        if not _module_bindings_unchanged(scope) or not _module_object_maps_unchanged(scope):
            return False
        if not _module_function_states_unchanged(scope):
            return False
        return True
    except Exception:
        return False


def validate_c01_candidate_refs(scope: Any, refs: Any) -> bool:
    """Validate one five-member candidate against exact held V20/V3/V4 types."""

    try:
        if not verify_namespace_freshness_receipt(
            scope, getattr(scope, "namespace_freshness_receipt", None)
        ):
            return False
        if type(refs) is not tuple or len(refs) != 5:
            return False
        if scope.candidate_refs is not None and scope.candidate_refs is not refs:
            return False
        if scope.consumed is not False or scope.active is not True:
            return False
        modules = scope.verified_source_modules
        issuer = modules[_ISSUER_PATH]
        protocol = modules[_PROTOCOL_PATH]
        supervisor = modules[_SUPERVISOR_PATH]
        admission, pair_binding, process, validation, artifacts = refs
        if (
            type(admission) is not issuer.__dict__.get("_C01V20Admission")
            or type(pair_binding) is not protocol.__dict__.get("C01PairBinding")
            or type(process) is not supervisor.__dict__.get("C01SupervisorResult")
            or type(validation) is not protocol.__dict__.get("C01CandidateValidation")
            or type(artifacts) is not dict
            or set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}
            or any(type(value) is not bytes or not value or len(value) > 8 * 1024 * 1024 for value in artifacts.values())
            or type(getattr(process, "worker_receipt", None))
            is not protocol.__dict__.get("C01WorkerReceipt")
        ):
            return False
        bindings = getattr(admission, "bindings", None)
        if type(bindings) not in (dict, MappingProxyType):
            return False
        for name in ("account_scope_sha256", "credential_binding_sha256"):
            value = bindings.get(name)
            if type(value) is not str or not _SHA256_RE.fullmatch(value):
                return False
        if type(getattr(admission, "configured_front_pair_count", None)) is not int:
            return False
        pair_ref = c01_pair_binding_ref_dict(scope, pair_binding)
        if type(pair_ref) is not dict:
            return False
        if scope.candidate_refs is not None and scope.candidate_refs is not refs:
            return False
        return verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        ) is True
    except Exception:
        return False


def c01_pair_binding_ref_dict(scope: Any, pair_binding: Any) -> Dict[str, Any]:
    """Project the held protocol pair binding to its hash-only public receipt."""

    if not verify_namespace_freshness_receipt(
        scope, getattr(scope, "namespace_freshness_receipt", None)
    ):
        raise C01RootV17Error("namespace_source_binding_invalid")
    protocol = scope.verified_source_modules[_PROTOCOL_PATH]
    objects = scope.verified_source_objects[_PROTOCOL_PATH]
    binding_type = objects.get("C01PairBinding")
    pair_ref_type = objects.get("C01PairBindingRef")
    to_ref = objects.get("C01PairBinding.to_receipt_ref")
    ref_to_dict = objects.get("C01PairBindingRef.to_dict")
    if (
        type(pair_binding) is not binding_type
        or type(binding_type) is not type
        or type(pair_ref_type) is not type
        or type(to_ref) is not FunctionType
        or type(ref_to_dict) is not FunctionType
        or to_ref.__code__ is not objects.get("C01PairBinding.to_receipt_ref.__code__")
        or ref_to_dict.__code__ is not objects.get("C01PairBindingRef.to_dict.__code__")
    ):
        raise C01RootV17Error("pair_binding_source_invalid")
    try:
        ref = to_ref(pair_binding)
        if type(ref) is not pair_ref_type:
            raise ValueError
        value = ref_to_dict(ref)
        if (
            type(value) is not dict
            or set(value)
            != {
                "selected_index",
                "selection_sha256",
                "md_front_sha256",
                "td_front_sha256",
                "selected_at_utc",
            }
            or type(value.get("selected_index")) is not int
            or value["selected_index"] < 0
            or any(
                type(value.get(name)) is not str or not _SHA256_RE.fullmatch(value[name])
                for name in ("selection_sha256", "md_front_sha256", "td_front_sha256")
            )
            or type(value.get("selected_at_utc")) is not str
            or not value["selected_at_utc"]
        ):
            raise ValueError
        if verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        ) is not True:
            raise ValueError
        return value
    except Exception:
        raise C01RootV17Error("pair_binding_projection_invalid") from None


def issue_c01_candidate_pending_result(
    scope: Any, issuer_result: Any
) -> C01CandidatePendingRootAdmission:
    """Create the one-use BLOCKED pending result after the exact V20 return."""

    if (
        type(scope) is not C01RootInvocationScope
        or scope._factory is not _SCOPE_FACTORY
        or scope.active is not True
        or scope.consumed is not False
        or scope.issuer_returned is not False
        or scope.stage_count != 1
        or scope.candidate_refs is None
        or scope.pending is not None
        or scope.root_content_stage is None
        or not verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        )
        or not validate_c01_candidate_refs(scope, scope.candidate_refs)
    ):
        raise C01RootV17Error("pending_candidate_unavailable")
    issuer = scope.verified_source_modules[_ISSUER_PATH]
    result_type = issuer.__dict__.get("C01NativeTdReadV20Result")
    if (
        type(issuer_result) is not result_type
        or getattr(issuer_result, "status", None) != "PASS"
        or getattr(issuer_result, "reason", None) != "read_only_candidate_complete"
        or getattr(issuer_result, "profile", None) != "C01_NATIVE_TD_READ_V20"
        or getattr(issuer_result, "case_id", None) != "C01"
        or type(getattr(issuer_result, "writes", None)) is not int
        or issuer_result.writes != 0
        or getattr(issuer_result, "admission_failure_stage", None) != "none"
        or getattr(issuer_result, "admission_failure_class", None) != "none"
        or getattr(issuer_result, "post_worker_failure_stage", None) != "none"
        or getattr(issuer_result, "post_worker_failure_code", None) != "none"
    ):
        raise C01RootV17Error("issuer_candidate_not_complete")
    scope.issuer_returned = True
    pending = C01CandidatePendingRootAdmission(
        scope, scope.candidate_refs, _factory=_PENDING_FACTORY
    )
    scope.pending = pending
    if not verify_namespace_freshness_receipt(scope, scope.namespace_freshness_receipt):
        # Keep the uncertain result and all held references.  Never clear or
        # recreate a pending result after a failed postcreation check.
        raise C01RootV17Error("pending_candidate_postcheck_failed")
    return pending


def close_c01_root_invocation_scope(scope: Any) -> None:
    """Mark a completed Root scope inactive while retaining every held ref."""

    if (
        type(scope) is not C01RootInvocationScope
        or scope._factory is not _SCOPE_FACTORY
        or scope.active is not True
        or not verify_namespace_freshness_receipt(scope, scope.namespace_freshness_receipt)
    ):
        raise C01RootV17Error("root_scope_close_invalid")
    scope.active = False


def create_c01_root_invocation_receipt(
    frame: Any,
    parent_process_receipt: Any,
    wrapper_call_receipt: Any,
    outer_close_receipt: Any,
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
    *,
    held_source_bytes: Mapping[str, bytes],
) -> C01RootInvocationReceipt:
    """Mint the parent-local receipt after frame, process, and source close.

    All parent receipts must already be factory-created by the fixed wrapper
    and driver.  This function rechecks their exact types and object links, then
    compiles every retained source byte buffer and compares all captured
    function, code, descriptor, and globals identities before retaining a
    receipt.  It makes no process, pipe, provider, SDK, or WinAPI calls.
    """

    metadata, call_nonce = _derive_parent_invocation_context(
        frame,
        parent_process_receipt,
        wrapper_call_receipt,
        outer_close_receipt,
        source_modules,
        source_objects,
        source_pins,
        held_source_bytes,
    )
    if (
        call_nonce in _USED_ROOT_CALL_NONCES
        or metadata["invocation_id"] in _USED_ROOT_INVOCATION_IDS
        or metadata["namespace_generation"] in _USED_ROOT_NAMESPACE_GENERATIONS
    ):
        raise C01RootV17Error("parent_invocation_replayed")
    _USED_ROOT_CALL_NONCES.add(call_nonce)
    _USED_ROOT_INVOCATION_IDS.add(metadata["invocation_id"])
    _USED_ROOT_NAMESPACE_GENERATIONS.add(metadata["namespace_generation"])
    receipt = C01RootInvocationReceipt(
        frame=frame,
        parent_process_receipt=parent_process_receipt,
        wrapper_call_receipt=wrapper_call_receipt,
        outer_close_receipt=outer_close_receipt,
        source_modules=source_modules,
        source_objects=source_objects,
        source_pins=source_pins,
        held_source_bytes=held_source_bytes,
        metadata=metadata,
        call_nonce=call_nonce,
        _factory=_INVOCATION_RECEIPT_FACTORY,
    )
    # Retain immediately.  A failed post-mint verification is uncertain and
    # must not permit a second receipt for this invocation.
    _RETAINED_ROOT_INVOCATION_RECEIPTS.append(receipt)
    if validate_c01_root_invocation_receipt(receipt) is not True:
        raise C01RootV17Error("parent_invocation_postcheck_failed")
    return receipt


def validate_c01_root_invocation_receipt(receipt: Any) -> bool:
    """Recheck the exact parent receipts, source bytes, and frame binding."""

    try:
        if (
            type(receipt) is not C01RootInvocationReceipt
            or receipt._factory is not _INVOCATION_RECEIPT_FACTORY
            or receipt.frame is not receipt._frame_ref
            or receipt.parent_process_receipt is not receipt._process_receipt_ref
            or receipt.wrapper_call_receipt is not receipt._wrapper_receipt_ref
            or receipt.outer_close_receipt is not receipt._outer_receipt_ref
            or receipt.source_modules is not receipt._source_modules_ref
            or receipt.source_objects is not receipt._source_objects_ref
            or receipt.source_pins is not receipt._source_pins_ref
            or receipt.held_source_bytes is not receipt._source_bytes_ref
            or receipt.call_nonce is not receipt._call_nonce_ref
            or type(receipt.call_nonce) is not object
            or receipt.invocation_id is not receipt._invocation_id_ref
            or receipt.namespace_generation is not receipt._namespace_generation_ref
            or receipt.worker_source_sha256 is not receipt._worker_source_sha256_ref
            or receipt.account_scope_sha256 is not receipt._account_scope_sha256_ref
            or receipt.credential_binding_sha256
            is not receipt._credential_binding_sha256_ref
            or type(receipt.pair_binding) is not MappingProxyType
            or tuple(receipt.pair_binding.items()) != receipt._pair_binding_items
            or tuple(sorted(receipt.source_pins.items())) != receipt.source_pin_items
            or tuple(sorted(receipt.frame_source_pin_items))
            != receipt.frame_source_pin_items
        ):
            return False
        metadata, call_nonce = _derive_parent_invocation_context(
            receipt.frame,
            receipt.parent_process_receipt,
            receipt.wrapper_call_receipt,
            receipt.outer_close_receipt,
            receipt.source_modules,
            receipt.source_objects,
            receipt.source_pins,
            receipt.held_source_bytes,
        )
        return bool(
            call_nonce is receipt.call_nonce
            and metadata["invocation_id"] == receipt.invocation_id
            and metadata["namespace_generation"] == receipt.namespace_generation
            and metadata["worker_source_sha256"] == receipt.worker_source_sha256
            and metadata["pair_binding"] == dict(receipt.pair_binding)
            and metadata["account_scope_sha256"] == receipt.account_scope_sha256
            and metadata["credential_binding_sha256"]
            == receipt.credential_binding_sha256
            and tuple(sorted(metadata["source_pins"].items()))
            == receipt.frame_source_pin_items
        )
    except Exception:
        return False


def c01_formal_adjudication_context(receipt: Any) -> Dict[str, Any]:
    """Return source-derived private bindings for the same-call adjudicator."""

    if validate_c01_root_invocation_receipt(receipt) is not True:
        raise C01RootV17Error("parent_invocation_receipt_invalid")
    metadata, _call_nonce = _derive_parent_invocation_context(
        receipt.frame,
        receipt.parent_process_receipt,
        receipt.wrapper_call_receipt,
        receipt.outer_close_receipt,
        receipt.source_modules,
        receipt.source_objects,
        receipt.source_pins,
        receipt.held_source_bytes,
    )
    return {
        "invocation_id": metadata["invocation_id"],
        "namespace_generation": metadata["namespace_generation"],
        "worker_source_sha256": metadata["worker_source_sha256"],
        "pair_binding": dict(metadata["pair_binding"]),
        "account_scope_sha256": metadata["account_scope_sha256"],
        "credential_binding_sha256": metadata["credential_binding_sha256"],
        "source_authenticity_verified": True,
        "account_binding_verified": True,
        "source_closure_verified": True,
        "root_postverify_verified": True,
        "frame_source_pins": dict(metadata["source_pins"]),
    }


def _derive_parent_invocation_context(
    frame: Any,
    parent_process_receipt: Any,
    wrapper_call_receipt: Any,
    outer_close_receipt: Any,
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
    held_source_bytes: Mapping[str, bytes],
) -> tuple[dict[str, Any], object]:
    if not _parent_source_closure_is_current(
        source_modules, source_objects, source_pins, held_source_bytes
    ):
        raise C01RootV17Error("parent_source_closure_invalid")
    modules = source_modules
    objects = source_objects
    wrapper_module = modules[_FRAME_WRAPPER_PATH]
    driver_module = modules[_ROOT_DRIVER_PATH]
    handoff_module = modules[_HANDOFF_PATH]
    handoff_objects = objects[_HANDOFF_PATH]
    frame_type = handoff_objects.get("RootContentFrame")
    if type(frame) is not frame_type or type(frame_type) is not type:
        raise C01RootV17Error("parent_frame_type_invalid")
    driver_objects = objects[_ROOT_DRIVER_PATH]
    wrapper_objects = objects[_FRAME_WRAPPER_PATH]
    process_type = driver_objects.get("C01V20ParentProcessReceipt")
    outer_type = driver_objects.get("C01V20OuterCloseReceipt")
    wrapper_receipt_type = wrapper_objects.get("C01V20WrapperCallReceipt")
    if (
        type(parent_process_receipt) is not process_type
        or type(outer_close_receipt) is not outer_type
        or type(wrapper_call_receipt) is not wrapper_receipt_type
        or type(process_type) is not type
        or type(outer_type) is not type
        or type(wrapper_receipt_type) is not type
        or parent_process_receipt.frame is not frame
        or parent_process_receipt.handoff_module is not handoff_module
        or wrapper_call_receipt.frame is not frame
        or wrapper_call_receipt.parent_process_receipt is not parent_process_receipt
        or wrapper_call_receipt.call_nonce is not parent_process_receipt.call_nonce
        or outer_close_receipt.parent_process_receipt is not parent_process_receipt
        or wrapper_call_receipt.parent_driver_module is not driver_module
        or wrapper_call_receipt.parent_driver_objects is not driver_objects
        or outer_close_receipt.source_modules is not source_modules
        or outer_close_receipt.source_objects is not source_objects
        or outer_close_receipt.module_source_pins is not source_pins
        or outer_close_receipt.module_held_source_bytes is not held_source_bytes
        or type(parent_process_receipt.call_nonce) is not object
        or outer_close_receipt.call_nonce is not parent_process_receipt.call_nonce
        or type(wrapper_call_receipt.projection_raw) is not bytes
        or not wrapper_call_receipt.projection_raw
        or type(parent_process_receipt.child_pid) is not int
        or parent_process_receipt.child_pid <= 0
        or wrapper_call_receipt.child_pid != parent_process_receipt.child_pid
    ):
        raise C01RootV17Error("parent_receipt_link_invalid")

    validate_process = _captured_function(
        driver_module, driver_objects, "validate_c01_v20_parent_process_receipt"
    )
    validate_outer = _captured_function(
        driver_module, driver_objects, "validate_c01_v20_outer_close_receipt"
    )
    validate_wrapper = _captured_function(
        wrapper_module, wrapper_objects, "validate_c01_v20_wrapper_call_receipt"
    )
    if (
        validate_process(parent_process_receipt) is not True
        or validate_wrapper(wrapper_call_receipt) is not True
        or validate_outer(outer_close_receipt) is not True
    ):
        raise C01RootV17Error("parent_receipt_validation_failed")

    decode = _captured_function(handoff_module, handoff_objects, "_decode_raw_frame")
    metadata, _worker, _baseline, _final = decode(frame._raw)
    if (
        type(metadata) is not dict
        or set(metadata.get("source_pins", {})) != _REQUIRED_ROOT_SCOPE_PATHS
        or any(
            source_pins.get(path) != digest
            for path, digest in metadata["source_pins"].items()
        )
    ):
        raise C01RootV17Error("parent_frame_source_pins_invalid")
    revalidate = _captured_function(
        handoff_module, handoff_objects, "revalidate_c01_root_content_frame"
    )
    content = revalidate(
        frame,
        validator_module=modules[_VALIDATOR_PATH],
        protocol_module=modules[_PROTOCOL_PATH],
        worker_module=modules[_WORKER_PATH],
        expected_source_pins=metadata["source_pins"],
        expected_source_modules=modules,
        expected_source_objects=objects,
        expected_invocation_id=metadata["invocation_id"],
        expected_namespace_generation=metadata["namespace_generation"],
        expected_worker_source_sha256=metadata["worker_source_sha256"],
        expected_pair_binding=metadata["pair_binding"],
        expected_account_scope_sha256=metadata["account_scope_sha256"],
        expected_credential_binding_sha256=metadata["credential_binding_sha256"],
    )
    if (
        getattr(content, "authority", None) != "NONE"
        or getattr(content, "status", None) != "CONTENT_VALIDATED_ONLY"
        or getattr(content, "certification_pass", None) is not False
        or getattr(content, "source_authenticity_verified", None) is not False
        or type(metadata.get("invocation_id")) is not str
        or not _CALL_ID_RE.fullmatch(metadata["invocation_id"])
        or type(metadata.get("namespace_generation")) is not str
        or not _CALL_ID_RE.fullmatch(metadata["namespace_generation"])
        or metadata["worker_source_sha256"] != metadata["source_pins"].get(_WORKER_PATH)
    ):
        raise C01RootV17Error("parent_frame_content_invalid")
    projection = json.loads(wrapper_call_receipt.projection_raw)
    if (
        type(projection) is not dict
        or projection.get("receipt_verified") is not True
        or projection.get("source_closure_verified") is not True
        or projection.get("root_postverify_verified") is not True
    ):
        raise C01RootV17Error("parent_wrapper_projection_invalid")
    return metadata, parent_process_receipt.call_nonce


def _parent_source_closure_is_current(
    source_modules: Any,
    source_objects: Any,
    source_pins: Any,
    held_source_bytes: Any,
) -> bool:
    try:
        if any(
            type(value) is not MappingProxyType
            for value in (source_modules, source_objects, source_pins, held_source_bytes)
        ):
            return False
        if (
            set(source_modules) != _REQUIRED_PARENT_MODULE_PATHS
            or set(source_modules) != set(source_objects)
            or set(source_modules) != set(source_pins)
            or set(source_modules) != set(held_source_bytes)
        ):
            return False
        if source_modules[_ROOT_PATH].__dict__ is not globals():
            return False
        for relative, raw in held_source_bytes.items():
            digest = source_pins[relative]
            if (
                type(relative) is not str
                or type(raw) is not bytes
                or not raw
                or type(digest) is not str
                or not _SHA256_RE.fullmatch(digest)
                or hashlib.sha256(raw).hexdigest() != digest
                or _FIXED_SOURCE_PINS.get(relative, digest) != digest
            ):
                return False
        expected_names = dict(_EXPECTED_MODULE_NAMES)
        expected_names[_ROOT_DRIVER_PATH] = "_c01_v20_root_actual_driver"
        expected_names[_FORMAL_ADJUDICATOR_PATH] = (
            "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"
        )
        expected_names[_FORMAL_COMPLETION_PATH] = "common.c01_root_completion_v1"
        for relative, module in source_modules.items():
            raw = held_source_bytes[relative]
            digest = source_pins[relative]
            rows = source_objects[relative]
            if (
                type(module) is not ModuleType
                or type(raw) is not bytes
                or not raw
                or type(digest) is not str
                or not _SHA256_RE.fullmatch(digest)
                or type(rows) is not MappingProxyType
                or module.__dict__ is not vars(module)
                or type(module.__file__) is not str
                or not _module_file_matches(module.__file__, relative)
                or type(module.__package__) is not str
                or (
                    module.__package__ != module.__name__.rpartition(".")[0]
                    and not (
                        relative in {_ISSUER_PATH, _OWNER_PATH}
                        and module.__package__ in ("", "backtrader_runtime")
                    )
                )
                or module.__dict__.get("__c01_source_sha256__") != digest
                or not _same_module_object_map(module, rows)
                or not _validate_module_functions(module, relative, raw)
            ):
                return False
            expected_name = expected_names.get(relative)
            if expected_name is not None and module.__name__ != expected_name:
                if not (
                    relative == _ISSUER_PATH
                    and module.__name__ == "_c01_front_transport_v14_v20_source"
                ):
                    return False
            if _FIXED_SOURCE_PINS.get(relative, digest) != digest:
                return False
        return True
    except Exception:
        return False


def _captured_function(
    module: ModuleType, objects: Mapping[str, Any], name: str
) -> FunctionType:
    function = objects.get(name)
    if (
        type(function) is not FunctionType
        or module.__dict__.get(name) is not function
        or function.__code__ is not objects.get(name + ".__code__")
        or function.__globals__ is not objects.get(name + ".__globals__")
        or function.__globals__ is not module.__dict__
    ):
        raise C01RootV17Error("parent_source_function_unbound")
    return function


def create_c01_root_content_frame_writer(
    scope: Any, channel_receipt: Any
) -> C01RootContentFrameWriter:
    """Consume the fixed V20 wrapper receipt and bind its exact FileIO stream."""

    if (
        type(scope) is not C01RootInvocationScope
        or scope._factory is not _SCOPE_FACTORY
        or scope.active is not True
        or scope.consumed is not False
        or scope._frame_writer is not None
        or not verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        )
    ):
        raise C01RootV17Error("frame_channel_unavailable")
    wrapper_objects = scope.verified_source_objects[_FRAME_WRAPPER_PATH]
    receipt_type = wrapper_objects.get("C01V20FrameChannelReceipt")
    consume = wrapper_objects.get("C01V20FrameChannelReceipt.consume_root_frame_writer")
    if (
        type(channel_receipt) is not receipt_type
        or type(receipt_type) is not type
        or type(consume) is not FunctionType
        or consume.__code__
        is not wrapper_objects.get("C01V20FrameChannelReceipt.consume_root_frame_writer.__code__")
        or consume.__globals__
        is not wrapper_objects.get(
            "C01V20FrameChannelReceipt.consume_root_frame_writer.__globals__"
        )
        or consume.__globals__ is not scope.verified_source_modules[_FRAME_WRAPPER_PATH].__dict__
        or channel_receipt.scope is not scope
        or channel_receipt._factory
        is not wrapper_objects.get("_C01_V20_FRAME_CHANNEL_FACTORY")
        or type(channel_receipt.nonce) is not object
        or channel_receipt.used is not False
        or channel_receipt.direction != "child_to_root"
        or type(channel_receipt.process_id) is not int
        or channel_receipt.process_id <= 0
        or channel_receipt.channel is not channel_receipt.stream
        or type(channel_receipt.stream) is not io.FileIO
        or channel_receipt.stream.closed
        or not channel_receipt.stream.writable()
    ):
        raise C01RootV17Error("frame_channel_receipt_invalid")
    try:
        stream = consume(channel_receipt, scope)
    except Exception:
        raise C01RootV17Error("frame_channel_receipt_invalid") from None
    if (
        type(stream) is not io.FileIO
        or stream.closed
        or not stream.writable()
        or channel_receipt.scope is not scope
        or channel_receipt.used is not True
        or channel_receipt.stream is not stream
        or channel_receipt.channel is not stream
        or channel_receipt.direction != "child_to_root"
        or type(channel_receipt.process_id) is not int
        or channel_receipt.process_id <= 0
        or type(channel_receipt.nonce) is not object
        or not verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        )
    ):
        raise C01RootV17Error("frame_channel_stream_invalid")
    writer = C01RootContentFrameWriter(
        scope,
        stream,
        channel_receipt,
        _factory=_FRAME_WRITER_FACTORY,
    )
    scope._frame_writer = writer
    return writer


def write_c01_root_content_frame(
    scope: Any, frame_bytes: Any, writer_capability: Any
) -> None:
    """Write exactly the staged frame through its Root-issued pipe capability.

    The one-use state is committed before the first write.  A short write,
    exception, or uncertain flush leaves the scope consumed and the capability
    unusable so the frame cannot be retried on a different channel.
    """

    if (
        type(scope) is not C01RootInvocationScope
        or scope._factory is not _SCOPE_FACTORY
        or not verify_namespace_freshness_receipt(
            scope, scope.namespace_freshness_receipt
        )
        or scope.active is not True
        or scope.issuer_returned is not True
        or scope.consumed is not False
        or scope.content_frame_sent is not False
        or scope.pending is None
        or writer_capability is not scope._frame_writer
        or type(writer_capability) is not C01RootContentFrameWriter
        or writer_capability._factory is not _FRAME_WRITER_FACTORY
        or writer_capability._scope is not scope
        or writer_capability._nonce is not scope.nonce
        or writer_capability._used is not False
        or writer_capability._channel_receipt.scope is not scope
        or writer_capability._channel_receipt.used is not True
        or writer_capability._channel_receipt.channel is not writer_capability._channel
        or writer_capability._channel_receipt.stream is not writer_capability._stream
        or writer_capability._channel_receipt.nonce is not writer_capability._channel_nonce
        or writer_capability._channel_receipt.process_id
        != writer_capability._channel_process_id
        or writer_capability._channel_receipt.direction
        != writer_capability._channel_direction
        or writer_capability._channel_direction != "child_to_root"
        or writer_capability._channel is not writer_capability._stream
        or writer_capability._channel_receipt._factory
        is not scope.verified_source_objects[_FRAME_WRAPPER_PATH].get(
            "_C01_V20_FRAME_CHANNEL_FACTORY"
        )
        or type(writer_capability._stream) is not io.FileIO
        or writer_capability._stream.closed
        or not writer_capability._stream.writable()
        or type(frame_bytes) is not bytes
        or not frame_bytes
        or scope.root_content_stage is None
        or scope.root_content_seal is None
        or getattr(scope.root_content_seal, "_frame", None) is not frame_bytes
        or getattr(scope.root_content_seal, "stage", None) is not scope.root_content_stage
        or getattr(scope.root_content_seal, "_used", None) is not False
        or scope.root_content_custody_receipt is None
    ):
        raise C01RootV17Error("frame_writer_binding_invalid")
    helper_objects = scope.verified_source_objects[_HANDOFF_PATH]
    seal_type = helper_objects.get("C01RootContentSeal")
    if (
        type(scope.root_content_seal) is not seal_type
        or getattr(scope.root_content_seal, "_factory", None)
        is not helper_objects.get("_SEAL_FACTORY")
    ):
        raise C01RootV17Error("frame_seal_binding_invalid")
    custody_objects = scope.verified_source_objects[_CUSTODY_PATH]
    validate_receipt = custody_objects.get("validate_c01_root_content_custody_receipt")
    if (
        type(validate_receipt) is not FunctionType
        or validate_receipt.__code__
        is not custody_objects.get("validate_c01_root_content_custody_receipt.__code__")
        or validate_receipt(
            scope.root_content_custody_receipt,
            scope,
            scope.pending,
            scope.root_content_stage,
        )
        is not True
    ):
        raise C01RootV17Error("frame_custody_receipt_invalid")
    max_frame = helper_objects.get("_MAX_FRAME_BYTES")
    if type(max_frame) is not int or len(frame_bytes) > max_frame:
        raise C01RootV17Error("frame_size_invalid")

    # Consume both capabilities before touching the pipe.  On any later
    # failure the original stream and candidate references remain retained.
    writer_capability._used = True
    scope.root_content_seal._used = True
    scope.content_frame_sent = True
    scope.consumed = True
    try:
        written = writer_capability._stream.write(frame_bytes)
        if type(written) is not int or written != len(frame_bytes):
            raise OSError
        writer_capability._stream.flush()
    except Exception:
        raise C01RootV17Error("frame_transport_failed") from None


def _fresh_ids() -> Tuple[str, str]:
    for _ in range(8):
        generation = uuid.uuid4().hex
        invocation = uuid.uuid4().hex
        if generation not in _USED_GENERATIONS and _CALL_ID_RE.fullmatch(invocation):
            _USED_GENERATIONS.add(generation)
            return generation, invocation
    raise C01RootV17Error("namespace_generation_unavailable")


def _module_bindings_unchanged(scope: C01RootInvocationScope) -> bool:
    try:
        bindings = scope.verified_source_module_bindings
        for relative, module in scope.verified_source_modules.items():
            row = bindings.get(relative)
            if type(row) is not tuple or len(row) != 5:
                return False
            name, file_name, package, module_dict, marker = row
            expected_name = _EXPECTED_MODULE_NAMES.get(relative)
            if expected_name is not None and name != expected_name:
                if not (
                    relative == _ISSUER_PATH
                    and name
                    in (
                        "backtrader_runtime.certification_simnow_c01_native_td_read_v20",
                        "_c01_front_transport_v14_v20_source",
                    )
                ):
                    return False
            if (
                module.__name__ is not name
                or module.__file__ is not file_name
                or module.__package__ is not package
                or module.__dict__ is not module_dict
                or module.__dict__.get("__c01_source_sha256__") is not marker
                or type(name) is not str
                or type(file_name) is not str
                or not _module_file_matches(file_name, relative)
                or package != name.rpartition(".")[0]
                and not (
                    relative in {_ISSUER_PATH, _OWNER_PATH}
                    and package in ("", "backtrader_runtime")
                )
            ):
                return False
        return True
    except Exception:
        return False


def _module_object_maps_unchanged(scope: C01RootInvocationScope) -> bool:
    try:
        pins = scope.source_pins
        for relative, module in scope.verified_source_modules.items():
            raw = scope.held_source_bytes[relative]
            pin = pins[relative]
            if (
                type(module) is not ModuleType
                or module.__dict__ is not vars(module)
                or module.__dict__.get("__c01_source_sha256__") != pin
                or hashlib.sha256(raw).hexdigest() != pin
                or not _module_file_matches(module.__file__, relative)
                or type(scope.verified_source_objects.get(relative)) is not MappingProxyType
                or not _same_module_object_map(
                    module, scope.verified_source_objects[relative]
                )
                or not _validate_module_functions(module, relative, raw)
            ):
                return False
        return True
    except Exception:
        return False


def _capture_module_objects(module: ModuleType) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name, value in tuple(module.__dict__.items()):
        if name.startswith("__") or name == "__c01_source_sha256__":
            continue
        result[name] = value
        if type(value) is FunctionType:
            result[name + ".__code__"] = value.__code__
            result[name + ".__globals__"] = value.__globals__
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for attribute, member in tuple(value.__dict__.items()):
                key = name + "." + attribute
                result[key] = member
                if type(member) is FunctionType:
                    result[key + ".__code__"] = member.__code__
                    result[key + ".__globals__"] = member.__globals__
                elif isinstance(member, (classmethod, staticmethod)):
                    function = member.__func__
                    result[key + ".__func__"] = function
                    result[key + ".__code__"] = function.__code__
                    result[key + ".__globals__"] = function.__globals__
                elif isinstance(member, property):
                    for accessor_name in ("fget", "fset", "fdel"):
                        function = getattr(member, accessor_name)
                        if type(function) is FunctionType:
                            accessor_key = key + "." + accessor_name
                            result[accessor_key] = function
                            result[accessor_key + ".__code__"] = function.__code__
                            result[accessor_key + ".__globals__"] = function.__globals__
    return result


def _same_module_object_map(module: ModuleType, snapshot: Mapping[str, Any]) -> bool:
    current = _capture_module_objects(module)
    if set(current) != set(snapshot):
        return False
    return all(current[name] is snapshot[name] for name in current)


def _function_mapping_items(value: Any) -> Any:
    if value is None:
        return None
    if type(value) is not dict or any(type(key) is not str for key in value):
        return False
    return tuple((key, value[key]) for key in sorted(value))


def _function_state_row(function: FunctionType) -> tuple:
    closure = function.__closure__
    try:
        closure_contents = tuple(cell.cell_contents for cell in (closure or ()))
    except ValueError:
        closure_contents = False
    return (
        function,
        function.__module__,
        function.__name__,
        function.__qualname__,
        function.__doc__,
        function.__code__,
        function.__globals__,
        function.__defaults__,
        tuple(function.__defaults__ or ()),
        function.__kwdefaults__,
        _function_mapping_items(function.__kwdefaults__),
        function.__annotations__,
        _function_mapping_items(function.__annotations__),
        closure,
        closure_contents,
        function.__dict__,
        _function_mapping_items(function.__dict__),
    )


def _capture_module_function_states(
    modules: Mapping[str, ModuleType],
) -> MappingProxyType:
    result = {}
    for relative, module in modules.items():
        functions = {}

        def add_function(key: str, function: Any) -> None:
            current = function
            current_key = key
            seen = set()
            while type(current) is FunctionType and id(current) not in seen:
                seen.add(id(current))
                functions[current_key] = _function_state_row(current)
                wrapped = current.__dict__.get("__wrapped__")
                if type(wrapped) is not FunctionType:
                    break
                current = wrapped
                current_key += ".__wrapped__"

        for name, value in tuple(module.__dict__.items()):
            if type(value) is FunctionType:
                add_function(name, value)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                for attribute, member in tuple(value.__dict__.items()):
                    key = name + "." + attribute
                    if type(member) is FunctionType:
                        add_function(key, member)
                    elif isinstance(member, (classmethod, staticmethod)):
                        add_function(key + ".__func__", member.__func__)
                    elif isinstance(member, property):
                        for accessor_name in ("fget", "fset", "fdel"):
                            accessor = getattr(member, accessor_name)
                            if type(accessor) is FunctionType:
                                add_function(key + "." + accessor_name, accessor)
        result[relative] = MappingProxyType(functions)
    return MappingProxyType(result)


def _same_function_state_row(current: tuple, captured: tuple) -> bool:
    if len(current) != 17 or len(captured) != 17:
        return False
    identity_indexes = (0, 5, 6, 7, 9, 11, 13, 15)
    if any(current[index] is not captured[index] for index in identity_indexes):
        return False
    if any(current[index] is not captured[index] for index in (1, 2, 3, 4)):
        return False
    for index in (8, 10, 12, 14, 16):
        left, right = current[index], captured[index]
        if left is right:
            continue
        if type(left) is not tuple or type(right) is not tuple or len(left) != len(right):
            return False
        for left_item, right_item in zip(left, right):
            if type(left_item) is tuple and type(right_item) is tuple:
                if len(left_item) != len(right_item):
                    return False
                if left_item[0] is not right_item[0] or left_item[1] is not right_item[1]:
                    return False
            elif left_item is not right_item:
                return False
    return True


def _module_function_states_unchanged(scope: C01RootInvocationScope) -> bool:
    try:
        current = _capture_module_function_states(scope.verified_source_modules)
        expected = scope._function_state_snapshot
        if type(expected) is not MappingProxyType or set(current) != set(expected):
            return False
        for relative, current_functions in current.items():
            expected_functions = expected[relative]
            if type(expected_functions) is not MappingProxyType or set(current_functions) != set(expected_functions):
                return False
            for key, current_row in current_functions.items():
                if not _same_function_state_row(current_row, expected_functions[key]):
                    return False
        return True
    except Exception:
        return False


def _validate_module_functions(module: ModuleType, relative: str, source: bytes) -> bool:
    try:
        code_root = compile(source, module.__file__, "exec", dont_inherit=True)
        source_codes: Dict[Tuple[str, int, str], CodeType] = {}
        pending_codes = [code_root]
        while pending_codes:
            code = pending_codes.pop()
            qualname = getattr(code, "co_qualname", code.co_name)
            source_codes[(qualname, code.co_firstlineno, code.co_name)] = code
            pending_codes.extend(value for value in code.co_consts if type(value) is CodeType)
        function_names, class_nodes = _source_module_definitions(source, module)
        dataclass_classes = _source_dataclass_classes(source, module, class_nodes)

        def validate(function: FunctionType, **context: Any) -> None:
            _validate_function_source(
                function,
                module,
                relative,
                source_codes,
                **context,
            )

        for name in function_names:
            value = module.__dict__.get(name)
            if (
                type(value) is not FunctionType
                or value.__module__ != module.__name__
                or value.__qualname__ != name
            ):
                return False
            validate(value)

        for name, node in class_nodes.items():
            owner = module.__dict__.get(name)
            if (
                not isinstance(owner, type)
                or owner.__module__ != module.__name__
                or owner.__qualname__ != name
            ):
                return False
            dataclass_row = dataclass_classes.get(name)
            generated = (
                _expected_dataclass_methods(owner, dataclass_row, module)
                if dataclass_row is not None
                else {}
            )
            for attribute, expected in generated.items():
                member = owner.__dict__.get(attribute)
                if type(member) is not FunctionType or not _function_state_matches(
                    member, expected, owner=owner, module=module,
                    source_class=dataclass_row["class"],
                ):
                    return False
            if dataclass_row is not None and not _dataclass_class_matches(
                owner, generated, dataclass_row, module
            ):
                return False
            for attribute in _class_source_method_names(node):
                member = owner.__dict__.get(attribute)
                if type(member) is FunctionType:
                    validate(member, owner=owner, attribute=attribute)
                elif isinstance(member, (classmethod, staticmethod)):
                    validate(member.__func__, owner=owner, attribute=attribute)
                elif isinstance(member, property):
                    for accessor_name in ("fget", "fset", "fdel"):
                        accessor = getattr(member, accessor_name)
                        if type(accessor) is FunctionType:
                            validate(
                                accessor, owner=owner, attribute=attribute,
                                accessor=accessor_name,
                            )
                else:
                    return False

        for name, value in tuple(module.__dict__.items()):
            if type(value) is FunctionType and value.__module__ == module.__name__:
                if name not in function_names:
                    validate(value)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                if name not in class_nodes:
                    return False
        return True
    except C01RootV17Error:
        return False
    except Exception:
        return False


def _validate_function_source(
    function: FunctionType,
    module: ModuleType,
    relative: str,
    source_codes: Mapping[Tuple[str, int, str], CodeType],
    *,
    owner: type | None = None,
    attribute: str | None = None,
    accessor: str | None = None,
    source_dataclass_classes: frozenset[str] = frozenset(),
) -> None:
    expected_qualname = None
    if isinstance(owner, type) and type(attribute) is str:
        expected_qualname = owner.__qualname__ + "." + attribute
    if expected_qualname is None:
        expected_qualname = function.__qualname__
    if type(accessor) is str and function.__qualname__ != expected_qualname:
        raise C01RootV17Error("source_function_qualname_invalid")
    if function.__module__ != module.__name__:
        raise C01RootV17Error("source_function_module_invalid")

    current = function
    seen = set()
    while type(current) is FunctionType and id(current) not in seen:
        seen.add(id(current))
        code = current.__code__
        key = (current.__qualname__, code.co_firstlineno, code.co_name)
        if (
            current.__globals__ is module.__dict__
            and _module_file_matches(code.co_filename, relative)
            and code == source_codes.get(key)
        ):
            return
        current = getattr(current, "__wrapped__", None)
    raise C01RootV17Error("source_function_binding_invalid")


def _source_module_definitions(
    source: bytes, module: ModuleType
) -> Tuple[frozenset[str], Dict[str, ast.ClassDef]]:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    tree = ast.parse(source.decode(encoding))
    functions = set()
    classes: Dict[str, ast.ClassDef] = {}
    def walk(body: Any, required: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if required or node.name in module.__dict__:
                    functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                if required or node.name in module.__dict__:
                    classes[node.name] = node
            elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                walk(node.body, False)
                walk(node.orelse, False)
            elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                walk(node.body, False)
                walk(node.orelse, False)
                walk(node.finalbody, False)
                for handler in node.handlers:
                    walk(handler.body, False)
            elif hasattr(ast, "Match") and isinstance(node, ast.Match):
                for case in node.cases:
                    walk(case.body, False)

    walk(tree.body, True)
    return frozenset(functions), classes


def _class_source_method_names(node: ast.ClassDef) -> Tuple[str, ...]:
    return tuple(
        item.name
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _resolve_ast_object(module: ModuleType, node: ast.expr) -> Any:
    if isinstance(node, ast.Name):
        return module.__dict__.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve_ast_object(module, node.value)
        try:
            return getattr(base, node.attr)
        except Exception:
            return None
    return None


def _safe_dataclass_expression(node: ast.expr, module: ModuleType) -> bool:
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _safe_dataclass_expression(node.value, module)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_safe_dataclass_expression(item, module) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is None or _safe_dataclass_expression(key, module) for key in node.keys
        ) and all(_safe_dataclass_expression(value, module) for value in node.values)
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub, ast.Not, ast.Invert)) and _safe_dataclass_expression(
            node.operand, module
        )
    if isinstance(node, ast.Call):
        if _resolve_ast_object(module, node.func) is not dataclasses.field or node.args:
            return False
        allowed = {"default", "default_factory", "init", "repr", "hash", "compare", "metadata", "kw_only"}
        return all(
            keyword.arg in allowed
            and _safe_dataclass_expression(keyword.value, module)
            for keyword in node.keywords
        )
    return False


def _source_dataclass_classes(
    source: bytes, module: ModuleType, class_nodes: Mapping[str, ast.ClassDef]
) -> Dict[str, Dict[str, Any]]:
    """Rebuild source-declared dataclasses with the exact stdlib decorator.

    The held class AST supplies fields and decorator options. The generated
    methods are compared to those from a fresh stdlib dataclass application;
    a ``<string>`` filename alone never authenticates a generated method.
    """

    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    tree = ast.parse(source.decode(encoding))
    future_annotations = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    result: Dict[str, Dict[str, Any]] = {}
    for name, node in class_nodes.items():
        dataclass_decorators = [
            item
            for item in node.decorator_list
            if _resolve_ast_object(
                module, item.func if isinstance(item, ast.Call) else item
            )
            is dataclasses.dataclass
        ]
        if not dataclass_decorators:
            continue
        if len(dataclass_decorators) != 1 or len(node.decorator_list) != 1:
            raise ValueError("unsupported dataclass decorator stack")
        decorator = dataclass_decorators[0]
        if node.bases or node.keywords:
            raise ValueError("unsupported dataclass base class")
        if isinstance(decorator, ast.Call):
            seen_options = set()
            allowed_options = {
                "init", "repr", "eq", "order", "unsafe_hash", "frozen",
                "match_args", "kw_only", "slots", "weakref_slot",
            }
            if decorator.args:
                raise ValueError("unsupported dataclass positional options")
            for keyword in decorator.keywords:
                if (
                    keyword.arg not in allowed_options
                    or keyword.arg in seen_options
                    or not isinstance(keyword.value, ast.Constant)
                    or type(keyword.value.value) is not bool
                ):
                    raise ValueError("unsupported dataclass option")
                seen_options.add(keyword.arg)

        explicit_names = set()
        safe_body = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                if not isinstance(item.target, ast.Name):
                    raise ValueError("unsupported dataclass field target")
                if item.value is not None and not _safe_dataclass_expression(
                    item.value, module
                ):
                    raise ValueError("unsafe dataclass field default")
                safe_body.append(copy.deepcopy(item))
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                explicit_names.add(item.name)
                # Only method presence affects dataclasses code generation;
                # method bodies and decorators are separately source-bound.
                placeholder = ast.FunctionDef(
                    name=item.name,
                    args=ast.arguments(
                        posonlyargs=[], args=[ast.arg(arg="self")], vararg=None,
                        kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
                    ),
                    body=[ast.Pass()], decorator_list=[], returns=None,
                    type_comment=None,
                )
                safe_body.append(placeholder)
            elif (
                isinstance(item, ast.Expr)
                and isinstance(item.value, ast.Constant)
                and type(item.value.value) is str
            ):
                safe_body.append(copy.deepcopy(item))
            elif isinstance(item, ast.Pass):
                safe_body.append(ast.Pass())
            else:
                raise ValueError("unsupported dataclass class body")

        shadow_node = copy.deepcopy(node)
        shadow_node.body = safe_body
        shadow_node.decorator_list = [copy.deepcopy(decorator)]
        shadow_module = ast.Module(body=[shadow_node], type_ignores=[])
        if future_annotations:
            shadow_module.body.insert(
                0,
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations", asname=None)],
                    level=0,
                ),
            )
        ast.fix_missing_locations(shadow_module)
        namespace = dict(module.__dict__)
        name_before = sys.modules.get(module.__name__, _MISSING_MODULE)
        sys.modules[module.__name__] = module
        try:
            exec(
                compile(shadow_module, module.__file__, "exec", dont_inherit=True),
                namespace,
                namespace,
            )
        finally:
            if name_before is _MISSING_MODULE:
                sys.modules.pop(module.__name__, None)
            else:
                sys.modules[module.__name__] = name_before
        expected_class = namespace.get(name)
        if (
            type(expected_class) is not type
            or expected_class.__module__ != module.__name__
            or expected_class.__qualname__ != name
        ):
            raise ValueError("source dataclass rebuild failed")
        result[name] = {
            "class": expected_class,
            "explicit_names": frozenset(explicit_names),
        }
    return result


def _expected_dataclass_methods(
    owner: type, dataclass_row: Mapping[str, Any], module: ModuleType
) -> Dict[str, FunctionType]:
    if type(dataclass_row) is not dict:
        raise ValueError("missing source dataclass definition")
    expected_class = dataclass_row["class"]
    explicit_names = dataclass_row["explicit_names"]
    generated = {}
    for name in (
        "__init__", "__repr__", "__eq__", "__lt__", "__le__", "__gt__",
        "__ge__", "__setattr__", "__delattr__", "__hash__",
    ):
        candidate = expected_class.__dict__.get(name)
        if name not in explicit_names and type(candidate) is FunctionType:
            generated[name] = candidate
    return generated


def _dataclass_class_matches(
    owner: type,
    generated: Mapping[str, FunctionType],
    dataclass_row: Mapping[str, Any],
    module: ModuleType,
) -> bool:
    expected = dataclass_row["class"]
    if (
        owner.__bases__ != expected.__bases__
        or owner.__annotations__ != expected.__annotations__
        or type(owner.__dict__.get("__dataclass_fields__")) is not dict
        or type(expected.__dict__.get("__dataclass_fields__")) is not dict
    ):
        return False
    actual_fields = owner.__dict__["__dataclass_fields__"]
    expected_fields = expected.__dict__["__dataclass_fields__"]
    if tuple(actual_fields) != tuple(expected_fields):
        return False
    for name, expected_field in expected_fields.items():
        actual_field = actual_fields.get(name)
        if type(actual_field) is not dataclasses.Field or type(expected_field) is not dataclasses.Field:
            return False
        for attribute in (
            "name", "type", "default", "default_factory", "init", "repr",
            "hash", "compare", "metadata", "kw_only", "_field_type",
        ):
            actual_value = getattr(actual_field, attribute, dataclasses.MISSING)
            expected_value = getattr(expected_field, attribute, dataclasses.MISSING)
            if actual_value is expected_value:
                continue
            if (
                type(actual_value) in (str, int, bool, float, bytes, tuple, type(None))
                and type(actual_value) is type(expected_value)
                and actual_value == expected_value
            ):
                continue
            if (
                attribute == "metadata"
                and isinstance(actual_value, Mapping)
                and isinstance(expected_value, Mapping)
                and dict(actual_value) == dict(expected_value)
            ):
                continue
            return False
    actual_params = owner.__dict__.get("__dataclass_params__")
    expected_params = expected.__dict__.get("__dataclass_params__")
    if type(actual_params) is not type(expected_params):
        return False
    for name in ("init", "repr", "eq", "order", "unsafe_hash", "frozen"):
        if getattr(actual_params, name, None) is not getattr(expected_params, name, None):
            return False
    for name in generated:
        actual_method = owner.__dict__.get(name)
        expected_method = expected.__dict__.get(name)
        if type(actual_method) is not FunctionType or type(expected_method) is not FunctionType:
            return False
        if not _function_state_matches(
            actual_method, expected_method, owner=owner, module=module,
            source_class=expected,
        ):
            return False
    return True


def _function_state_matches(
    actual: FunctionType,
    expected: FunctionType,
    *,
    owner: type,
    module: ModuleType,
    source_class: type | None = None,
) -> bool:
    expected_global_name = expected.__globals__.get("__name__")
    expected_wrapped = expected.__dict__.get("__wrapped__")
    recursive_repr_generated = (
        type(source_class) is type
        and expected.__name__ == "__repr__"
        and expected.__module__ == module.__name__
        and expected.__qualname__ == source_class.__qualname__ + ".__repr__"
        and type(expected_wrapped) is FunctionType
        and expected.__globals__ is dataclasses._recursive_repr.__globals__
        and any(
            type(value) is CodeType and expected.__code__ is value
            for value in dataclasses._recursive_repr.__code__.co_consts
        )
    )
    generated_external_global_binding = (
        expected.__globals__ is not module.__dict__
        and type(expected.__module__) is str
        and expected_global_name == expected.__module__
        and expected.__module__ != module.__name__
        and actual.__globals__ is expected.__globals__
    )
    generated_global_binding = (
        actual.__globals__ is module.__dict__
        or generated_external_global_binding
        or (recursive_repr_generated and actual.__globals__ is expected.__globals__)
    )
    checks = (
        type(actual) is not FunctionType
        or type(expected) is not FunctionType
        or actual.__code__ != expected.__code__
        or not generated_global_binding
        or actual.__name__ != expected.__name__
        or actual.__qualname__ != expected.__qualname__
        or actual.__module__ != module.__name__
        or not _same_default_values(actual.__defaults__, expected.__defaults__)
        or not _same_mapping_values(actual.__kwdefaults__, expected.__kwdefaults__)
        or not _same_mapping_values(actual.__annotations__, expected.__annotations__)
    )
    if checks:
        return False
    actual_dict, expected_dict = actual.__dict__, expected.__dict__
    if set(actual_dict) != set(expected_dict):
        return False
    for key in actual_dict:
        left, right = actual_dict[key], expected_dict[key]
        if key == "__wrapped__" and type(left) is FunctionType and type(right) is FunctionType:
            if not _function_state_matches(
                left, right, owner=owner, module=module, source_class=source_class
            ):
                return False
        elif left is not right and not (
            type(left) in (str, int, bool, float, bytes, type(None))
            and type(left) is type(right)
            and left == right
        ):
            return False
    actual_closure = actual.__closure__ or ()
    expected_closure = expected.__closure__ or ()
    if (
        actual.__code__.co_freevars != expected.__code__.co_freevars
        or len(actual_closure) != len(expected_closure)
    ):
        return False
    for actual_cell, expected_cell in zip(actual_closure, expected_closure):
        try:
            left = actual_cell.cell_contents
            right = expected_cell.cell_contents
        except ValueError:
            return False
        if not _same_generated_closure_value(
            left, right, owner, module, source_class
        ):
            return False
    return True


def _same_default_values(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if type(left) is not tuple or type(right) is not tuple or len(left) != len(right):
        return False
    return all(
        a is b
        or (
            type(a) in (str, int, bool, float, bytes, type(None))
            and type(a) is type(b)
            and a == b
        )
        for a, b in zip(left, right)
    )


def _same_mapping_values(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if type(left) is not dict or type(right) is not dict or set(left) != set(right):
        return False
    return all(
        left[key] is right[key]
        or (
            type(left[key]) in (str, int, bool, float, bytes, type(None))
            and type(left[key]) is type(right[key])
            and left[key] == right[key]
        )
        for key in left
    )


def _same_generated_closure_value(
    actual: Any,
    expected: Any,
    owner: type,
    module: ModuleType,
    source_class: type | None,
) -> bool:
    if source_class is not None and expected is source_class:
        return actual is owner
    if type(expected) is FunctionType:
        return type(actual) is FunctionType and _function_state_matches(
            actual, expected, owner=owner, module=module, source_class=source_class
        )
    if type(expected) is set:
        return type(actual) is set and not actual and not expected
    if type(expected) is tuple:
        return type(actual) is tuple and len(actual) == len(expected) and all(
            _same_generated_closure_value(a, b, owner, module, source_class)
            if type(b) in (FunctionType, tuple, set)
            or (source_class is not None and b is source_class)
            else a is b
            or (
                type(a) in (str, int, bool, float, bytes, type(None))
                and type(a) is type(b)
                and a == b
            )
            for a, b in zip(actual, expected)
        )
    return actual is expected or (
        type(actual) in (str, int, bool, float, bytes, type(None))
        and type(actual) is type(expected)
        and actual == expected
    )


def _module_file_matches(value: Any, relative: str) -> bool:
    if type(value) is not str or type(relative) is not str:
        return False
    normalized = value.replace("\\", "/").casefold()
    target = relative.casefold()
    return normalized == target or normalized.endswith("/" + target)


def _validate_relative_path(value: Any) -> None:
    if type(value) is not str or not value or "\\" in value or ":" in value:
        raise C01RootV17Error("source_path_invalid")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise C01RootV17Error("source_path_invalid")


__all__ = [
    "C01CandidatePendingRootAdmission",
    "C01NamespaceFreshnessReceipt",
    "C01RootContentFrameWriter",
    "C01RootInvocationReceipt",
    "C01RootInvocationScope",
    "C01RootV17Error",
    "c01_formal_adjudication_context",
    "close_c01_root_invocation_scope",
    "c01_pair_binding_ref_dict",
    "create_c01_root_invocation_receipt",
    "create_c01_root_invocation_scope",
    "create_c01_root_content_frame_writer",
    "issue_c01_candidate_pending_result",
    "validate_c01_candidate_refs",
    "validate_c01_root_invocation_receipt",
    "verify_namespace_freshness_receipt",
    "write_c01_root_content_frame",
]
