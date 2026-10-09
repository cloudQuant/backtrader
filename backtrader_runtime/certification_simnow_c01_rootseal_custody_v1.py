"""Same-call C01 content handoff for the fixed Root source closure.

The child-side helpers capture and revalidate one V20 issuer invocation while
its Root scope and held source lease are active. They transfer a bounded,
private binary frame; the frame is data and never authority. The Root parent
must retain the returned :class:`RootContentFrame` in memory through outer
postverify and normal source-lease close, then revalidate it with its own
already-held, exact V3/V4/validator modules. No function in this module opens a
path, reads a private capture, imports an SDK/native module, or mints a formal
C01 pass.
"""

from __future__ import annotations

import io
import json
import re
import struct
from dataclasses import dataclass, field
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, BinaryIO, Mapping


SCHEMA = "iteration41.simnow.c01.root-content-handoff.v1"
_ROOT_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_v17"
_ROOT_MODULE_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_CUSTODY_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v17"
_CUSTODY_MODULE_PATH = "backtrader_runtime/certification_simnow_c01_root_custody_v17.py"
_SELF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
_VALIDATOR_MODULE_NAME = "common.c01_root_ledger_v1"
_VALIDATOR_PATH = "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
_PROTOCOL_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_v3_protocol"
_PROTOCOL_PATH = "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
_WORKER_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_native_v4"
_WORKER_PATH = "backtrader_runtime/certification_simnow_c01_native_v4.py"
_VALIDATOR_SHA256 = "4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a"
_PROTOCOL_SHA256 = "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160"
_WORKER_SHA256 = "66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66"
_HEADER = struct.Struct("!8sIIIII")
_MAGIC = b"C01RSL01"
_MAX_METADATA_BYTES = 256 * 1024
_MAX_WORKER_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_FRAME_BYTES = _HEADER.size + _MAX_METADATA_BYTES + _MAX_WORKER_BYTES + 2 * _MAX_ARTIFACT_BYTES
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STAGE_FACTORY = object()
_SEAL_FACTORY = object()
_FRAME_FACTORY = object()


class RootSealCustodyError(RuntimeError):
    """Fixed-code failure that cannot include private values or exception text."""

    def __init__(self, code: str = "rootseal_custody_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "rootseal_custody_blocked"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class RootContentFrame:
    """Opaque immutable frame. Parsing it establishes no source or account trust."""

    _raw: bytes = field(repr=False)
    _factory: Any = field(repr=False)

    def __repr__(self) -> str:
        return "RootContentFrame(<private same-call content; no authority>)"

    def safe_summary(self) -> dict[str, Any]:
        metadata, worker, baseline, final = _decode_raw_frame(self._raw)
        requests = worker.get("requests")
        callbacks = worker.get("callbacks")
        snapshots = worker.get("snapshots")
        return {
            "schema": SCHEMA,
            "authority": "NONE",
            "request_count": len(requests) if type(requests) is list else 0,
            "callback_count": len(callbacks) if type(callbacks) is list else 0,
            "snapshot_count": len(snapshots) if type(snapshots) is list else 0,
            "baseline_bytes": len(baseline),
            "final_bytes": len(final),
            "content_validated": False,
            "certification_pass": False,
        }


class C01RootContentStage:
    """Private one-call reference bundle captured before issuer ExitStack close."""

    __slots__ = (
        "scope",
        "candidate_refs",
        "source_modules",
        "source_objects",
        "source_pin_items",
        "validated_content",
        "worker_receipt",
        "worker_projection",
        "pair_projection",
        "artifact_items",
        "_factory",
    )

    def __init__(self, *, values: Mapping[str, Any], _factory: Any = None) -> None:
        if _factory is not _STAGE_FACTORY or type(values) is not dict:
            raise RootSealCustodyError("rootseal_factory_required")
        for name, value in values.items():
            setattr(self, name, value)
        self._factory = _STAGE_FACTORY

    def __repr__(self) -> str:
        return "C01RootContentStage(<same-call private refs redacted>)"


class C01RootContentSeal:
    """One-use child-side frame handoff, not a formal C01 result."""

    __slots__ = ("stage", "custody_receipt", "_frame", "_factory", "_used")

    def __init__(
        self,
        *,
        stage: C01RootContentStage,
        custody_receipt: Any,
        frame: bytes,
        _factory: Any = None,
    ) -> None:
        if _factory is not _SEAL_FACTORY:
            raise RootSealCustodyError("rootseal_factory_required")
        if (
            type(stage) is not C01RootContentStage
            or stage._factory is not _STAGE_FACTORY
            or type(frame) is not bytes
            or not frame
            or len(frame) > _MAX_FRAME_BYTES
        ):
            raise RootSealCustodyError("rootseal_binding_invalid")
        self.stage = stage
        self.custody_receipt = custody_receipt
        self._frame = frame
        self._factory = _SEAL_FACTORY
        self._used = False

    def __repr__(self) -> str:
        return "C01RootContentSeal(<private same-call content; no authority>)"


def stage_c01_content(
    *,
    root_module: ModuleType,
    custody_module: ModuleType,
    scope: Any,
    admission: Any,
    pair_binding: Any,
    process: Any,
    validation: Any,
    artifacts: dict[str, bytes],
    validator_module: ModuleType,
    protocol_module: ModuleType,
    worker_module: ModuleType,
) -> C01RootContentStage:
    """Validate and retain the exact V20 candidate while its issuer is active.

    The Root scope's fixed source loader must populate ``verified_source_modules``,
    ``verified_source_objects``, ``source_pins``, and ``source_pin_items`` from
    the currently held source bytes before the issuer hook calls this function.
    """

    _validate_root_scope(root_module, custody_module, scope, require_issuer_returned=False)
    if (
        type(scope.stage_count) is not int
        or scope.stage_count != 0
        or scope.candidate_refs is not None
        or scope.root_content_stage is not None
        or scope.pending is not None
    ):
        raise RootSealCustodyError("rootseal_stage_reused")
    refs = (admission, pair_binding, process, validation, artifacts)
    _validate_candidate_refs(root_module, scope, refs, protocol_module)
    modules = (root_module, custody_module, validator_module, protocol_module, worker_module)
    objects = _validate_held_modules(scope, modules)
    content = _validate_content(
        scope=scope,
        candidate_refs=refs,
        validator_module=validator_module,
        protocol_module=protocol_module,
        worker_module=worker_module,
    )
    _require_complete_content(content)
    receipt = process.worker_receipt
    worker_projection = _canonical_json(_receipt_projection(protocol_module, receipt, scope))
    pair_projection = _canonical_json(
        _captured_function(scope, _ROOT_MODULE_PATH, "c01_pair_binding_ref_dict")(
            scope, pair_binding
        )
    )
    artifact_items = tuple(
        (name, artifacts[name]) for name in ("snapshots/baseline.json", "snapshots/final.json")
    )
    stage = C01RootContentStage(
        values={
            "scope": scope,
            "candidate_refs": refs,
            "source_modules": modules,
            "source_objects": objects,
            "source_pin_items": tuple(scope.source_pin_items),
            "validated_content": content,
            "worker_receipt": receipt,
            "worker_projection": worker_projection,
            "pair_projection": pair_projection,
            "artifact_items": artifact_items,
        },
        _factory=_STAGE_FACTORY,
    )
    scope.candidate_refs = refs
    scope.validated_content = content
    scope.root_content_stage = stage
    scope.stage_count = 1
    return stage


def mint_c01_root_content_seal(
    *,
    root_module: ModuleType,
    custody_module: ModuleType,
    stage: C01RootContentStage,
    pending: Any,
    custody_receipt: Any,
) -> C01RootContentSeal:
    """Revalidate staged content after Root postverify, before scope exit.

    ``custody_receipt`` must be the exact typed receipt produced by the pinned
    V17 custody module after it checked source/runtime/artifact/account/process
    custody for this same scope and candidate. The receipt itself is not a C01
    pass and cannot bypass the second content validation here.
    """

    if type(stage) is not C01RootContentStage or stage._factory is not _STAGE_FACTORY:
        raise RootSealCustodyError("rootseal_stage_invalid")
    scope = stage.scope
    _validate_root_scope(root_module, custody_module, scope, require_issuer_returned=True)
    if (
        scope.root_content_stage is not stage
        or scope.pending is not pending
        or getattr(pending, "_scope", None) is not scope
        or getattr(pending, "_nonce", None) is not scope.nonce
        or type(scope.stage_count) is not int
        or scope.stage_count != 1
        or scope.root_content_seal is not None
        or scope.content_frame_sent is not False
        or scope.consumed is not False
    ):
        raise RootSealCustodyError("rootseal_binding_invalid")
    modules = stage.source_modules
    if len(modules) != 5 or modules[0] is not root_module or modules[1] is not custody_module:
        raise RootSealCustodyError("rootseal_source_module_mismatch")
    _validate_held_modules(scope, modules, expected_objects=stage.source_objects)
    _validate_candidate_refs(root_module, scope, stage.candidate_refs, modules[3])
    _validate_custody_receipt(custody_module, scope, stage, custody_receipt)
    content = _validate_content(
        scope=scope,
        candidate_refs=stage.candidate_refs,
        validator_module=modules[2],
        protocol_module=modules[3],
        worker_module=modules[4],
    )
    _require_complete_content(content)
    _require_content_matches(stage.validated_content, content)
    if (
        process_receipt := stage.candidate_refs[2].worker_receipt
    ) is not stage.worker_receipt or _canonical_json(
        _receipt_projection(modules[3], process_receipt, scope)
    ) != stage.worker_projection:
        raise RootSealCustodyError("rootseal_worker_receipt_changed")
    artifacts = stage.candidate_refs[4]
    if type(artifacts) is not dict or any(
        artifacts.get(name) is not original for name, original in stage.artifact_items
    ):
        raise RootSealCustodyError("rootseal_artifacts_changed")
    if (
        _canonical_json(
            _captured_function(scope, _ROOT_MODULE_PATH, "c01_pair_binding_ref_dict")(
                scope, stage.candidate_refs[1]
            )
        )
        != stage.pair_projection
    ):
        raise RootSealCustodyError("rootseal_pair_binding_changed")
    frame = _encode_frame(scope, stage, content)
    seal = C01RootContentSeal(
        stage=stage,
        custody_receipt=custody_receipt,
        frame=frame,
        _factory=_SEAL_FACTORY,
    )
    scope.root_content_seal = seal
    return seal


def write_c01_root_content_frame(seal: C01RootContentSeal, writer: Any) -> None:
    """Write exactly one private frame to a dedicated binary child pipe."""

    if type(seal) is not C01RootContentSeal or seal._factory is not _SEAL_FACTORY:
        raise RootSealCustodyError("rootseal_invalid")
    stage = seal.stage
    scope = stage.scope
    root_module, custody_module = stage.source_modules[:2]
    if (
        seal._used
        or scope.root_content_seal is not seal
        or scope.content_frame_sent is not False
        or scope.consumed is not False
    ):
        raise RootSealCustodyError("rootseal_transfer_replayed")
    _validate_root_scope(root_module, custody_module, scope, require_issuer_returned=True)
    _validate_held_modules(scope, stage.source_modules, expected_objects=stage.source_objects)
    root_objects = _scope_objects(scope)[_ROOT_MODULE_PATH]
    writer_type = root_objects.get("C01RootContentFrameWriter")
    root_write = _captured_function(scope, _ROOT_MODULE_PATH, "write_c01_root_content_frame")
    if (
        scope.candidate_refs is not stage.candidate_refs
        or scope.pending is None
        or scope.content_frame_sent is not False
        or scope.consumed is not False
        or type(writer_type) is not type
        or type(writer) is not writer_type
        or getattr(writer, "_scope", None) is not scope
        or getattr(writer, "_nonce", None) is not scope.nonce
        or getattr(writer, "_used", None) is not False
        or type(getattr(writer, "_stream", None)) is not io.FileIO
        or getattr(writer, "_factory", None) is not root_objects.get("_FRAME_WRITER_FACTORY")
    ):
        raise RootSealCustodyError("rootseal_transfer_replayed")
    try:
        root_write(scope, seal._frame, writer)
    except Exception:
        raise RootSealCustodyError("rootseal_transport_failed") from None


def read_c01_root_content_frame(reader: BinaryIO) -> RootContentFrame:
    """Read one bounded frame and EOF; return opaque, non-authoritative bytes."""

    if type(reader) not in (io.BufferedReader, io.FileIO, io.BytesIO):
        raise RootSealCustodyError("rootseal_transport_invalid")
    header = _read_exact(reader, _HEADER.size)
    magic, metadata_size, worker_size, baseline_size, final_size, total_size = _HEADER.unpack(
        header
    )
    expected_total = _HEADER.size + metadata_size + worker_size + baseline_size + final_size
    if (
        magic != _MAGIC
        or not 0 < metadata_size <= _MAX_METADATA_BYTES
        or not 0 < worker_size <= _MAX_WORKER_BYTES
        or not 0 < baseline_size <= _MAX_ARTIFACT_BYTES
        or not 0 < final_size <= _MAX_ARTIFACT_BYTES
        or total_size != expected_total
        or total_size > _MAX_FRAME_BYTES
    ):
        raise RootSealCustodyError("rootseal_frame_invalid")
    body = _read_exact(reader, total_size - _HEADER.size)
    if reader.read(1) != b"":
        raise RootSealCustodyError("rootseal_frame_trailing_data")
    metadata, worker, _baseline, _final = _decode_raw_frame(header + body)
    if metadata.get("schema") != SCHEMA or worker.get("case_id") != "C01":
        raise RootSealCustodyError("rootseal_frame_invalid")
    return RootContentFrame(header + body, _FRAME_FACTORY)


def revalidate_c01_root_content_frame(
    frame: RootContentFrame,
    *,
    validator_module: ModuleType,
    protocol_module: ModuleType,
    worker_module: ModuleType,
    expected_source_pins: Mapping[str, str],
    expected_source_modules: Mapping[str, ModuleType],
    expected_source_objects: Mapping[str, Mapping[str, Any]],
    expected_invocation_id: str,
    expected_namespace_generation: str,
    expected_worker_source_sha256: str,
    expected_pair_binding: dict[str, Any],
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
) -> Any:
    """Recompute all content from the opaque frame using already-held modules.

    The caller must get the expected private bindings from an exact typed Root
    invocation receipt and must keep the same frame object until after outer
    source close. This function does not mint an authority or a C01 pass.
    """

    if type(frame) is not RootContentFrame or frame._factory is not _FRAME_FACTORY:
        raise RootSealCustodyError("rootseal_frame_invalid")
    metadata, worker, baseline, final = _decode_raw_frame(frame._raw)
    _validate_expected_frame_context(
        metadata,
        expected_source_pins=expected_source_pins,
        expected_invocation_id=expected_invocation_id,
        expected_namespace_generation=expected_namespace_generation,
        expected_worker_source_sha256=expected_worker_source_sha256,
        expected_pair_binding=expected_pair_binding,
        expected_account_scope_sha256=expected_account_scope_sha256,
        expected_credential_binding_sha256=expected_credential_binding_sha256,
    )
    modules = {
        _VALIDATOR_PATH: validator_module,
        _PROTOCOL_PATH: protocol_module,
        _WORKER_PATH: worker_module,
    }
    module_contracts = {
        _VALIDATOR_PATH: (
            _VALIDATOR_MODULE_NAME,
            ("validate_c01_ledger_content_v1",),
            ("C01ValidatedContent",),
            (),
        ),
        _PROTOCOL_PATH: (
            _PROTOCOL_MODULE_NAME,
            (
                "encode_worker_frame",
                "parse_worker_frame",
                "parse_private_snapshot_artifact",
                "canonical_value_sha256",
            ),
            ("C01WorkerReceipt", "C01PrivateSnapshot"),
            (("C01WorkerReceipt", "to_dict"), ("C01PrivateSnapshot", "to_dict")),
        ),
        _WORKER_PATH: (
            _WORKER_MODULE_NAME,
            (
                "project_order_economics",
                "project_open_order_refs",
                "project_gross_positions",
                "project_funds",
            ),
            (),
            (),
        ),
    }
    for path, module in modules.items():
        module_name, functions, types, methods = module_contracts[path]
        _validate_pinned_module(
            module,
            path=path,
            expected_pin=expected_source_pins.get(path),
            expected_module=expected_source_modules.get(path),
            expected_objects=expected_source_objects.get(path),
            expected_name=module_name,
            required_functions=functions,
            required_types=types,
            required_methods=methods,
        )
    artifacts = {
        "snapshots/baseline.json": baseline,
        "snapshots/final.json": final,
    }
    try:
        content = expected_source_objects[_VALIDATOR_PATH]["validate_c01_ledger_content_v1"](
            worker,
            artifacts,
            protocol_module=protocol_module,
            worker_module=worker_module,
            expected_worker_source_sha256=expected_worker_source_sha256,
            expected_protocol_source_sha256=_PROTOCOL_SHA256,
            expected_worker_module_source_sha256=_WORKER_SHA256,
            expected_pair_binding=expected_pair_binding,
            expected_account_scope_sha256=expected_account_scope_sha256,
            expected_credential_binding_sha256=expected_credential_binding_sha256,
        )
    except Exception:
        raise RootSealCustodyError("rootseal_content_invalid") from None
    _require_complete_content(content)
    _require_commitments_match_metadata(content, metadata)
    return content


def _validate_root_scope(
    root_module: ModuleType,
    custody_module: ModuleType,
    scope: Any,
    *,
    require_issuer_returned: bool,
) -> None:
    modules = _scope_modules(scope)
    if modules.get(_ROOT_MODULE_PATH) is not root_module:
        raise RootSealCustodyError("rootseal_root_module_mismatch")
    if modules.get(_CUSTODY_MODULE_PATH) is not custody_module:
        raise RootSealCustodyError("rootseal_custody_module_mismatch")
    root_pin = _pin(scope, _ROOT_MODULE_PATH)
    custody_pin = _pin(scope, _CUSTODY_MODULE_PATH)
    objects = _scope_objects(scope)
    _validate_pinned_module(
        root_module,
        path=_ROOT_MODULE_PATH,
        expected_pin=root_pin,
        expected_module=root_module,
        expected_objects=objects.get(_ROOT_MODULE_PATH),
        required_functions=(
            "verify_namespace_freshness_receipt",
            "validate_c01_candidate_refs",
            "c01_pair_binding_ref_dict",
            "write_c01_root_content_frame",
        ),
        required_types=(
            "C01RootInvocationScope",
            "C01NamespaceFreshnessReceipt",
            "C01RootContentFrameWriter",
        ),
    )
    _validate_pinned_module(
        custody_module,
        path=_CUSTODY_MODULE_PATH,
        expected_pin=custody_pin,
        expected_module=custody_module,
        expected_objects=objects.get(_CUSTODY_MODULE_PATH),
        required_functions=("validate_c01_root_content_custody_receipt",),
        required_types=("C01RootContentCustodyReceipt",),
    )
    self_module = modules.get(_SELF_PATH)
    if (
        type(self_module) is not ModuleType
        or self_module.__dict__ is not stage_c01_content.__globals__
    ):
        raise RootSealCustodyError("rootseal_self_module_unbound")
    self_pin = _pin(scope, _SELF_PATH)
    _validate_pinned_module(
        self_module,
        path=_SELF_PATH,
        expected_pin=self_pin,
        expected_module=self_module,
        expected_objects=objects.get(_SELF_PATH),
        required_functions=(
            "stage_c01_content",
            "mint_c01_root_content_seal",
            "write_c01_root_content_frame",
            "read_c01_root_content_frame",
            "revalidate_c01_root_content_frame",
        ),
    )
    scope_type = root_module.C01RootInvocationScope
    receipt_type = root_module.C01NamespaceFreshnessReceipt
    receipt = getattr(scope, "namespace_freshness_receipt", None)
    if (
        type(scope) is not scope_type
        or getattr(scope, "root_module", None) is not root_module
        or getattr(scope, "root_custody_module", None) is not custody_module
        or getattr(scope, "active", None) is not True
        or getattr(scope, "consumed", None) is not False
        or type(getattr(scope, "verified_source_modules", None)) is not dict
        or type(getattr(scope, "verified_source_objects", None)) is not dict
        or type(getattr(scope, "source_pin_items", None)) is not tuple
        or type(getattr(scope, "source_pins", None)) not in (dict, MappingProxyType)
        or type(receipt) is not receipt_type
        or getattr(scope, "namespace_generation", None) != getattr(receipt, "generation", None)
        or (require_issuer_returned and getattr(scope, "issuer_returned", None) is not True)
        or (not require_issuer_returned and getattr(scope, "issuer_returned", None) is not False)
    ):
        raise RootSealCustodyError("rootseal_scope_invalid")
    if (
        _captured_function(scope, _ROOT_MODULE_PATH, "verify_namespace_freshness_receipt")(
            scope, receipt
        )
        is not True
    ):
        raise RootSealCustodyError("rootseal_namespace_freshness_invalid")
    _validate_pin_map(scope.source_pins)
    if tuple(sorted(scope.source_pins.items())) != scope.source_pin_items:
        raise RootSealCustodyError("rootseal_source_pins_changed")


def _validate_candidate_refs(
    root_module: ModuleType,
    scope: Any,
    refs: tuple[Any, ...],
    protocol_module: ModuleType,
) -> None:
    if (
        type(refs) is not tuple
        or len(refs) != 5
        or scope.candidate_refs is not None
        and scope.candidate_refs is not refs
    ):
        raise RootSealCustodyError("rootseal_candidate_refs_invalid")
    if (
        _captured_function(scope, _ROOT_MODULE_PATH, "validate_c01_candidate_refs")(scope, refs)
        is not True
    ):
        raise RootSealCustodyError("rootseal_candidate_refs_invalid")
    admission, pair_binding, process, _validation, artifacts = refs
    if (
        type(artifacts) is not dict
        or set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}
        or any(type(raw) is not bytes for raw in artifacts.values())
        or len(artifacts["snapshots/baseline.json"]) > _MAX_ARTIFACT_BYTES
        or len(artifacts["snapshots/final.json"]) > _MAX_ARTIFACT_BYTES
        or type(getattr(process, "worker_receipt", None)) is not protocol_module.C01WorkerReceipt
        or type(getattr(admission, "bindings", None)) not in (dict, MappingProxyType)
    ):
        raise RootSealCustodyError("rootseal_candidate_content_invalid")
    for key in ("account_scope_sha256", "credential_binding_sha256"):
        value = admission.bindings.get(key)
        if type(value) is not str or not _SHA256_RE.fullmatch(value):
            raise RootSealCustodyError("rootseal_candidate_binding_invalid")
    pair_ref = _captured_function(scope, _ROOT_MODULE_PATH, "c01_pair_binding_ref_dict")(
        scope, pair_binding
    )
    if type(pair_ref) is not dict:
        raise RootSealCustodyError("rootseal_pair_binding_invalid")


def _validate_held_modules(
    scope: Any,
    modules: tuple[ModuleType, ...],
    *,
    expected_objects: tuple[Mapping[str, Any], ...] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    if type(modules) is not tuple or len(modules) != 5:
        raise RootSealCustodyError("rootseal_source_module_mismatch")
    paths = (
        _ROOT_MODULE_PATH,
        _CUSTODY_MODULE_PATH,
        _VALIDATOR_PATH,
        _PROTOCOL_PATH,
        _WORKER_PATH,
    )
    names = (
        _ROOT_MODULE_NAME,
        _CUSTODY_MODULE_NAME,
        _VALIDATOR_MODULE_NAME,
        _PROTOCOL_MODULE_NAME,
        _WORKER_MODULE_NAME,
    )
    pins = (
        _pin(scope, _ROOT_MODULE_PATH),
        _pin(scope, _CUSTODY_MODULE_PATH),
        _VALIDATOR_SHA256,
        _PROTOCOL_SHA256,
        _WORKER_SHA256,
    )
    function_names = (
        (
            "verify_namespace_freshness_receipt",
            "validate_c01_candidate_refs",
            "c01_pair_binding_ref_dict",
            "write_c01_root_content_frame",
        ),
        ("validate_c01_root_content_custody_receipt",),
        ("validate_c01_ledger_content_v1",),
        (
            "encode_worker_frame",
            "parse_worker_frame",
            "parse_private_snapshot_artifact",
            "canonical_value_sha256",
        ),
        (
            "project_order_economics",
            "project_open_order_refs",
            "project_gross_positions",
            "project_funds",
        ),
    )
    type_names = (
        (
            "C01RootInvocationScope",
            "C01NamespaceFreshnessReceipt",
            "C01RootContentFrameWriter",
        ),
        ("C01RootContentCustodyReceipt",),
        ("C01ValidatedContent",),
        ("C01WorkerReceipt", "C01PrivateSnapshot"),
        (),
    )
    method_names = (
        (),
        (),
        (),
        (("C01WorkerReceipt", "to_dict"), ("C01PrivateSnapshot", "to_dict")),
        (),
    )
    source_objects: list[Mapping[str, Any]] = []
    for index, (module, path, name, pin) in enumerate(zip(modules, paths, names, pins)):
        current_objects = _scope_objects(scope).get(path)
        if expected_objects is None:
            objects = _object_map_snapshot(current_objects)
        else:
            if index >= len(expected_objects):
                raise RootSealCustodyError("rootseal_source_object_map_changed")
            objects = expected_objects[index]
            if not _same_object_map(current_objects, objects):
                raise RootSealCustodyError("rootseal_source_object_map_changed")
        _validate_pinned_module(
            module,
            path=path,
            expected_pin=pin,
            expected_module=module,
            expected_objects=objects,
            expected_name=name,
            required_functions=function_names[index],
            required_types=type_names[index],
            required_methods=method_names[index],
        )
        source_objects.append(objects)
    self_objects = _scope_objects(scope).get(_SELF_PATH)
    if expected_objects is None:
        pinned_self_objects = _object_map_snapshot(self_objects)
    else:
        if len(expected_objects) != 6 or not _same_object_map(self_objects, expected_objects[5]):
            raise RootSealCustodyError("rootseal_source_object_map_changed")
        pinned_self_objects = expected_objects[5]
    self_module = _scope_modules(scope).get(_SELF_PATH)
    if (
        type(self_module) is not ModuleType
        or self_module.__dict__ is not stage_c01_content.__globals__
    ):
        raise RootSealCustodyError("rootseal_self_module_unbound")
    _validate_pinned_module(
        self_module,
        path=_SELF_PATH,
        expected_pin=_pin(scope, _SELF_PATH),
        expected_module=self_module,
        expected_objects=pinned_self_objects,
        required_functions=(
            "stage_c01_content",
            "mint_c01_root_content_seal",
            "write_c01_root_content_frame",
            "read_c01_root_content_frame",
            "revalidate_c01_root_content_frame",
        ),
    )
    source_objects.append(pinned_self_objects)
    return tuple(source_objects)


def _validate_content(
    *,
    scope: Any,
    candidate_refs: tuple[Any, ...],
    validator_module: ModuleType,
    protocol_module: ModuleType,
    worker_module: ModuleType,
) -> Any:
    admission, pair_binding, process, _validation, artifacts = candidate_refs
    receipt = process.worker_receipt
    worker = _receipt_projection(protocol_module, receipt, scope)
    try:
        content = _captured_function(scope, _VALIDATOR_PATH, "validate_c01_ledger_content_v1")(
            worker,
            artifacts,
            protocol_module=protocol_module,
            worker_module=worker_module,
            expected_worker_source_sha256=scope.expected_worker_source_sha256,
            expected_protocol_source_sha256=_PROTOCOL_SHA256,
            expected_worker_module_source_sha256=_WORKER_SHA256,
            expected_pair_binding=_captured_function(
                scope, _ROOT_MODULE_PATH, "c01_pair_binding_ref_dict"
            )(scope, pair_binding),
            expected_account_scope_sha256=admission.bindings["account_scope_sha256"],
            expected_credential_binding_sha256=admission.bindings["credential_binding_sha256"],
        )
    except Exception:
        raise RootSealCustodyError("rootseal_content_invalid") from None
    _require_validated_content(validator_module, content)
    return content


def _validate_custody_receipt(
    custody_module: ModuleType, scope: Any, stage: C01RootContentStage, receipt: Any
) -> None:
    receipt_type = _scope_objects(scope)[_CUSTODY_MODULE_PATH].get("C01RootContentCustodyReceipt")
    validate_receipt = _captured_function(
        scope, _CUSTODY_MODULE_PATH, "validate_c01_root_content_custody_receipt"
    )
    if (
        type(receipt_type) is not type
        or custody_module.__dict__.get("C01RootContentCustodyReceipt") is not receipt_type
        or type(receipt) is not receipt_type
        or receipt.scope is not scope
        or receipt.pending is not scope.pending
        or receipt.candidate_refs is not stage.candidate_refs
        or receipt.validated_content is not stage.validated_content
        or receipt.namespace_freshness_receipt is not scope.namespace_freshness_receipt
        or receipt.consumed is not False
        or validate_receipt(receipt, scope, scope.pending, stage) is not True
    ):
        raise RootSealCustodyError("rootseal_custody_receipt_invalid")


def _validate_pinned_module(
    module: ModuleType,
    *,
    path: str,
    expected_pin: Any,
    expected_module: ModuleType,
    expected_objects: Mapping[str, Any] | None,
    expected_name: str | None = None,
    required_functions: tuple[str, ...] = (),
    required_types: tuple[str, ...] = (),
    required_methods: tuple[tuple[str, str], ...] = (),
) -> None:
    if (
        type(module) is not ModuleType
        or module is not expected_module
        or type(expected_pin) is not str
        or not _SHA256_RE.fullmatch(expected_pin)
        or module.__dict__.get("__c01_source_sha256__") != expected_pin
        or type(module.__dict__.get("__file__")) is not str
        or not _path_matches(module.__dict__["__file__"], path)
        or (expected_name is not None and module.__name__ != expected_name)
        or type(expected_objects) not in (dict, MappingProxyType)
    ):
        raise RootSealCustodyError("rootseal_source_module_mismatch")
    for key, expected in expected_objects.items():
        current = _resolve_source_object(module, key)
        if current is not expected:
            raise RootSealCustodyError("rootseal_source_global_binding_mismatch")
    for name in required_functions:
        current = module.__dict__.get(name)
        captured = expected_objects.get(name)
        if (
            type(current) is not FunctionType
            or current is not captured
            or current.__code__ is not expected_objects.get(name + ".__code__")
            or current.__globals__ is not module.__dict__
            or current.__module__ != module.__name__
            or current.__qualname__ != name
        ):
            raise RootSealCustodyError("rootseal_source_callable_mismatch")
    for name in required_types:
        current = module.__dict__.get(name)
        if not isinstance(current, type) or current is not expected_objects.get(name):
            raise RootSealCustodyError("rootseal_source_type_mismatch")
    for class_name, method_name in required_methods:
        cls = module.__dict__.get(class_name)
        descriptor = (
            type.__getattribute__(cls, "__dict__").get(method_name)
            if isinstance(cls, type)
            else None
        )
        current = (
            object.__getattribute__(descriptor, "__func__")
            if isinstance(descriptor, (classmethod, staticmethod))
            else descriptor
        )
        captured = expected_objects.get("{}.{}".format(class_name, method_name))
        if (
            descriptor is not captured
            or type(current) is not FunctionType
            or current
            is not expected_objects.get("{}.{}.__func__".format(class_name, method_name), current)
            or current.__code__
            is not expected_objects.get("{}.{}.__code__".format(class_name, method_name))
            or current.__globals__ is not module.__dict__
            or current.__module__ != module.__name__
        ):
            raise RootSealCustodyError("rootseal_source_method_mismatch")


def _validate_expected_frame_context(
    metadata: dict[str, Any],
    *,
    expected_source_pins: Mapping[str, str],
    expected_invocation_id: str,
    expected_namespace_generation: str,
    expected_worker_source_sha256: str,
    expected_pair_binding: dict[str, Any],
    expected_account_scope_sha256: str,
    expected_credential_binding_sha256: str,
) -> None:
    _validate_pin_map(expected_source_pins)
    if (
        type(expected_invocation_id) is not str
        or not _CALL_ID_RE.fullmatch(expected_invocation_id)
        or type(expected_namespace_generation) is not str
        or not expected_namespace_generation
        or type(expected_worker_source_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_worker_source_sha256)
        or type(expected_pair_binding) is not dict
        or type(expected_account_scope_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_account_scope_sha256)
        or type(expected_credential_binding_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_credential_binding_sha256)
        or metadata["invocation_id"] != expected_invocation_id
        or metadata["namespace_generation"] != expected_namespace_generation
        or metadata["worker_source_sha256"] != expected_worker_source_sha256
        or metadata["account_scope_sha256"] != expected_account_scope_sha256
        or metadata["credential_binding_sha256"] != expected_credential_binding_sha256
        or metadata["source_pins"] != dict(expected_source_pins)
        or _canonical_json(metadata["pair_binding"]) != _canonical_json(expected_pair_binding)
    ):
        raise RootSealCustodyError("rootseal_frame_binding_mismatch")


def _encode_frame(scope: Any, stage: C01RootContentStage, content: Any) -> bytes:
    admission, pair_binding, process, _validation, artifacts = stage.candidate_refs
    worker_raw = stage.worker_projection
    baseline = artifacts["snapshots/baseline.json"]
    final = artifacts["snapshots/final.json"]
    if (
        len(worker_raw) > _MAX_WORKER_BYTES
        or len(baseline) > _MAX_ARTIFACT_BYTES
        or len(final) > _MAX_ARTIFACT_BYTES
    ):
        raise RootSealCustodyError("rootseal_frame_oversized")
    metadata = {
        "schema": SCHEMA,
        "invocation_id": scope.invocation_id,
        "namespace_generation": scope.namespace_generation,
        "worker_source_sha256": scope.expected_worker_source_sha256,
        "protocol_source_sha256": _PROTOCOL_SHA256,
        "worker_module_source_sha256": _WORKER_SHA256,
        "validator_source_sha256": _VALIDATOR_SHA256,
        "account_scope_sha256": admission.bindings["account_scope_sha256"],
        "credential_binding_sha256": admission.bindings["credential_binding_sha256"],
        "pair_binding": _captured_function(scope, _ROOT_MODULE_PATH, "c01_pair_binding_ref_dict")(
            scope, pair_binding
        ),
        "source_pins": dict(scope.source_pins),
        "content_commitment_sha256": content._content_commitment_sha256,
        "baseline_artifact_sha256": content._baseline_artifact_sha256,
        "final_artifact_sha256": content._final_artifact_sha256,
    }
    _validate_frame_metadata(metadata)
    metadata_raw = _canonical_json(metadata)
    if len(metadata_raw) > _MAX_METADATA_BYTES:
        raise RootSealCustodyError("rootseal_metadata_oversized")
    total = _HEADER.size + len(metadata_raw) + len(worker_raw) + len(baseline) + len(final)
    if total > _MAX_FRAME_BYTES:
        raise RootSealCustodyError("rootseal_frame_oversized")
    header = _HEADER.pack(
        _MAGIC, len(metadata_raw), len(worker_raw), len(baseline), len(final), total
    )
    return header + metadata_raw + worker_raw + baseline + final


def _decode_raw_frame(raw: bytes) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    if type(raw) is not bytes or not _HEADER.size <= len(raw) <= _MAX_FRAME_BYTES:
        raise RootSealCustodyError("rootseal_frame_invalid")
    header = raw[: _HEADER.size]
    magic, metadata_size, worker_size, baseline_size, final_size, total_size = _HEADER.unpack(
        header
    )
    if (
        magic != _MAGIC
        or not 0 < metadata_size <= _MAX_METADATA_BYTES
        or not 0 < worker_size <= _MAX_WORKER_BYTES
        or not 0 < baseline_size <= _MAX_ARTIFACT_BYTES
        or not 0 < final_size <= _MAX_ARTIFACT_BYTES
        or total_size != len(raw)
        or total_size != _HEADER.size + metadata_size + worker_size + baseline_size + final_size
    ):
        raise RootSealCustodyError("rootseal_frame_invalid")
    body = raw[_HEADER.size :]
    metadata_end = metadata_size
    worker_end = metadata_end + worker_size
    baseline_end = worker_end + baseline_size
    metadata = _strict_json_object(body[:metadata_end], "rootseal_metadata_invalid")
    worker = _strict_json_object(body[metadata_end:worker_end], "rootseal_worker_invalid")
    baseline = body[worker_end:baseline_end]
    final = body[baseline_end:]
    _validate_frame_metadata(metadata)
    if (
        set(worker) != _WORKER_FRAME_KEYS
        or worker.get("case_id") != "C01"
        or type(worker.get("requests")) is not list
        or type(worker.get("callbacks")) is not list
        or type(worker.get("snapshots")) is not list
    ):
        raise RootSealCustodyError("rootseal_worker_invalid")
    return metadata, worker, baseline, final


_WORKER_FRAME_KEYS = frozenset(
    {
        "protocol",
        "message_type",
        "version",
        "case_id",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "worker_source_sha256",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "client",
        "requests",
        "callbacks",
        "snapshots",
        "write_counters",
        "native_close",
        "terminal_state",
    }
)


def _validate_frame_metadata(metadata: Mapping[str, Any]) -> None:
    exact = {
        "schema",
        "invocation_id",
        "namespace_generation",
        "worker_source_sha256",
        "protocol_source_sha256",
        "worker_module_source_sha256",
        "validator_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
        "pair_binding",
        "source_pins",
        "content_commitment_sha256",
        "baseline_artifact_sha256",
        "final_artifact_sha256",
    }
    if type(metadata) is not dict or set(metadata) != exact:
        raise RootSealCustodyError("rootseal_metadata_invalid")
    if (
        metadata.get("schema") != SCHEMA
        or type(metadata.get("invocation_id")) is not str
        or not _CALL_ID_RE.fullmatch(metadata["invocation_id"])
        or type(metadata.get("namespace_generation")) is not str
        or not metadata["namespace_generation"]
        or any(
            type(metadata.get(key)) is not str or not _SHA256_RE.fullmatch(metadata[key])
            for key in (
                "worker_source_sha256",
                "protocol_source_sha256",
                "worker_module_source_sha256",
                "validator_source_sha256",
                "account_scope_sha256",
                "credential_binding_sha256",
                "content_commitment_sha256",
                "baseline_artifact_sha256",
                "final_artifact_sha256",
            )
        )
        or metadata["protocol_source_sha256"] != _PROTOCOL_SHA256
        or metadata["worker_module_source_sha256"] != _WORKER_SHA256
        or metadata["validator_source_sha256"] != _VALIDATOR_SHA256
        or type(metadata.get("pair_binding")) is not dict
        or type(metadata.get("source_pins")) is not dict
    ):
        raise RootSealCustodyError("rootseal_metadata_invalid")
    _validate_pin_map(metadata["source_pins"])
    if (
        metadata["source_pins"].get(_VALIDATOR_PATH) != _VALIDATOR_SHA256
        or metadata["source_pins"].get(_PROTOCOL_PATH) != _PROTOCOL_SHA256
        or metadata["source_pins"].get(_WORKER_PATH) != _WORKER_SHA256
    ):
        raise RootSealCustodyError("rootseal_source_pins_invalid")


def _validate_pin_map(pins: Mapping[str, str]) -> None:
    if type(pins) not in (dict, MappingProxyType) or not pins:
        raise RootSealCustodyError("rootseal_source_pins_invalid")
    if any(
        type(path) is not str
        or not path
        or type(digest) is not str
        or not _SHA256_RE.fullmatch(digest)
        for path, digest in pins.items()
    ):
        raise RootSealCustodyError("rootseal_source_pins_invalid")


def _require_validated_content(validator_module: ModuleType, content: Any) -> None:
    content_type = getattr(validator_module, "C01ValidatedContent", None)
    if (
        type(content_type) is not type
        or type(content) is not content_type
        or content.authority != "NONE"
        or content.status != "CONTENT_VALIDATED_ONLY"
        or content.certification_pass is not False
        or content.source_authenticity_verified is not False
        or type(content.provider_source_sequence) is not int
        or content.provider_source_sequence != 0
    ):
        raise RootSealCustodyError("rootseal_content_authority_invalid")


def _require_complete_content(content: Any) -> None:
    expected = {
        "request_count": 8,
        "auth_login_callback_count": 2,
        "query_request_count": 6,
        "snapshot_count": 2,
        "activity_callback_count": 0,
        "write_invocation_count": 0,
    }
    if any(
        type(getattr(content, key, None)) is not int or getattr(content, key) != value
        for key, value in expected.items()
    ):
        raise RootSealCustodyError("rootseal_content_incomplete")
    if (
        type(content.query_callback_count) is not int
        or not 6 <= content.query_callback_count <= 8
        or type(content.requests) is not tuple
        or len(content.requests) != 8
        or type(content.callbacks) is not tuple
        or len(content.callbacks) < 8
        or type(content.query_receipts) is not tuple
        or len(content.query_receipts) != 6
        or type(content._snapshot_facts) is not tuple
        or len(content._snapshot_facts) != 2
        or content.native_close_complete is not True
        or content.native_released is not True
        or content.native_thread_alive is not False
        or content.native_timed_out is not False
    ):
        raise RootSealCustodyError("rootseal_content_incomplete")


def _require_content_matches(expected: Any, actual: Any) -> None:
    for name in (
        "_content_commitment_sha256",
        "_baseline_artifact_sha256",
        "_final_artifact_sha256",
    ):
        left = getattr(expected, name, None)
        right = getattr(actual, name, None)
        if (
            type(left) is not str
            or type(right) is not str
            or not _SHA256_RE.fullmatch(left)
            or not _SHA256_RE.fullmatch(right)
            or left != right
        ):
            raise RootSealCustodyError("rootseal_content_commitment_mismatch")


def _require_commitments_match_metadata(content: Any, metadata: Mapping[str, Any]) -> None:
    names = (
        ("_content_commitment_sha256", "content_commitment_sha256"),
        ("_baseline_artifact_sha256", "baseline_artifact_sha256"),
        ("_final_artifact_sha256", "final_artifact_sha256"),
    )
    if any(getattr(content, left, None) != metadata.get(right) for left, right in names):
        raise RootSealCustodyError("rootseal_content_commitment_mismatch")


def _receipt_projection(protocol_module: ModuleType, receipt: Any, scope: Any) -> dict[str, Any]:
    if type(receipt) is not protocol_module.C01WorkerReceipt:
        raise RootSealCustodyError("rootseal_worker_receipt_invalid")
    method = protocol_module.C01WorkerReceipt.__dict__.get("to_dict")
    captured = _scope_objects(scope)[_PROTOCOL_PATH].get("C01WorkerReceipt.to_dict")
    if (
        type(method) is not FunctionType
        or method is not captured
        or method.__code__
        is not _scope_objects(scope)[_PROTOCOL_PATH].get("C01WorkerReceipt.to_dict.__code__")
        or method.__globals__ is not protocol_module.__dict__
    ):
        raise RootSealCustodyError("rootseal_worker_receipt_method_invalid")
    try:
        value = method(receipt)
    except Exception:
        raise RootSealCustodyError("rootseal_worker_receipt_invalid") from None
    if type(value) is not dict:
        raise RootSealCustodyError("rootseal_worker_receipt_invalid")
    return value


def _scope_modules(scope: Any) -> Mapping[str, ModuleType]:
    value = getattr(scope, "verified_source_modules", None)
    if type(value) is not dict:
        raise RootSealCustodyError("rootseal_source_module_mismatch")
    return value


def _scope_objects(scope: Any) -> Mapping[str, Mapping[str, Any]]:
    value = getattr(scope, "verified_source_objects", None)
    if type(value) is not dict:
        raise RootSealCustodyError("rootseal_source_object_map_invalid")
    return value


def _pin(scope: Any, path: str) -> str:
    pins = getattr(scope, "source_pins", None)
    value = pins.get(path) if type(pins) in (dict, MappingProxyType) else None
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise RootSealCustodyError("rootseal_source_pin_missing")
    return value


def _captured_function(scope: Any, path: str, name: str) -> FunctionType:
    module = _scope_modules(scope).get(path)
    objects = _scope_objects(scope).get(path)
    function = objects.get(name) if type(objects) in (dict, MappingProxyType) else None
    if (
        type(module) is not ModuleType
        or type(function) is not FunctionType
        or module.__dict__.get(name) is not function
        or function.__globals__ is not module.__dict__
        or function.__code__ is not objects.get(name + ".__code__")
    ):
        raise RootSealCustodyError("rootseal_source_callable_mismatch")
    return function


def _object_map_snapshot(value: Any) -> Mapping[str, Any]:
    if type(value) not in (dict, MappingProxyType):
        raise RootSealCustodyError("rootseal_source_object_map_invalid")
    return MappingProxyType(dict(value))


def _same_object_map(current: Any, captured: Any) -> bool:
    if type(current) not in (dict, MappingProxyType) or type(captured) not in (
        dict,
        MappingProxyType,
    ):
        return False
    if set(current) != set(captured):
        return False
    return all(current[key] is captured[key] for key in current)


def _module_or_class_attribute(module: ModuleType, name: str) -> Any:
    """Resolve captured module/class/descriptor paths without invoking getters."""

    if type(name) is not str or not name:
        return None
    parts = name.split(".")
    current = module.__dict__.get(parts[0])
    for part in parts[1:]:
        if isinstance(current, type):
            # Bypass a custom metaclass's __getattribute__; the source object
            # map must be resolved without running user-defined access hooks.
            current = type.__getattribute__(current, "__dict__").get(part)
        elif isinstance(current, (classmethod, staticmethod)):
            current = (
                object.__getattribute__(current, "__func__")
                if part == "__func__"
                else None
            )
        elif isinstance(current, property):
            current = (
                object.__getattribute__(current, part)
                if part in {"fget", "fset", "fdel"}
                else None
            )
        else:
            return None
        if current is None:
            return None
    return current


def _resolve_source_object(module: ModuleType, name: str) -> Any:
    """Resolve module/class identities and descriptor function state."""

    suffixes = (".__code__", ".__globals__", ".__func__")
    suffix = next((item for item in suffixes if name.endswith(item)), None)
    if suffix is None:
        return _module_or_class_attribute(module, name)
    target = _module_or_class_attribute(module, name[: -len(suffix)])
    if suffix == ".__func__":
        return (
            object.__getattribute__(target, "__func__")
            if isinstance(target, (classmethod, staticmethod))
            else None
        )
    if isinstance(target, (classmethod, staticmethod)):
        target = object.__getattribute__(target, "__func__")
    if type(target) is not FunctionType:
        return None
    return target.__code__ if suffix == ".__code__" else target.__globals__


def _path_matches(path: str, relative: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    target = relative.casefold()
    return normalized == target or normalized.endswith("/" + target)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        raise RootSealCustodyError("rootseal_json_invalid") from None


def _strict_json_object(raw: bytes, code: str) -> dict[str, Any]:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except Exception:
        raise RootSealCustodyError(code) from None
    if type(value) is not dict:
        raise RootSealCustodyError(code)
    return value


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        block = stream.read(count - len(chunks))
        if type(block) is not bytes or not block:
            raise RootSealCustodyError("rootseal_frame_truncated")
        chunks.extend(block)
    return bytes(chunks)


__all__ = [
    "C01RootContentSeal",
    "C01RootContentStage",
    "RootContentFrame",
    "RootSealCustodyError",
    "mint_c01_root_content_seal",
    "read_c01_root_content_frame",
    "revalidate_c01_root_content_frame",
    "stage_c01_content",
    "write_c01_root_content_frame",
]
