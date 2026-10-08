"""Finite Root custody checks for the SimNow C01 V18 admission path.

This module is loaded from Root-held public source bytes.  It does not perform
work at import time.  The Root entry opens public source/runtime leases around
one invocation; the issuer calls :func:`prepare_candidate_custody` inside its
existing credential/private-run ExitStack; Root then runs
:func:`verify_and_mint_postverify` after that stack has closed cleanly.

The five receipts below are exact, one-call objects.  They carry no account or
credential values and cannot be built from a caller dictionary or boolean.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from importlib.machinery import ModuleSpec
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Iterator, Mapping, Optional


_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
_ROOT_BRIDGE_NAME = "backtrader_runtime.certification_simnow_c01_root_v16"
_ROOT_ENTRY_NAME = "backtrader_runtime.certification_simnow_c01_root_entry_v18"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_NAMES = frozenset({".env", "config.yaml", "secrets.yaml"})
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
_MAX_DLL_BYTES = 128 * 1024 * 1024
_MAX_EXTENSION_BYTES = 128 * 1024 * 1024
_DIRECTORY_READ_ACCESS = 0x80020080

_C01_ROOT_POSTVERIFY_FACTORY = object()
_CURRENT_SOURCE_RUNTIME_LEASE: ContextVar["C01RootSourceRuntimeLease | None"] = ContextVar(
    "c01_root_v16_source_runtime_lease", default=None
)
_CURRENT_CANDIDATE_CUSTODY: ContextVar["_CandidateCustody | None"] = ContextVar(
    "c01_root_v16_candidate_custody", default=None
)


class C01RootCustodyV16Error(ValueError):
    """A fixed, value-free Root custody failure category."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or any(ord(char) < 32 for char in code):
            code = "root_custody_invalid"
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class _HeldFile:
    path: Path
    pin: str
    role: str
    handle: Any
    identity: tuple[int, int]
    raw: bytes

    def __repr__(self) -> str:
        return "_HeldFile(<path, bytes, and identity redacted>)"


@dataclass(frozen=True, repr=False)
class _HeldDirectory:
    path: Path
    handle: Any
    identity: tuple[int, int]

    def __repr__(self) -> str:
        return "_HeldDirectory(<path and identity redacted>)"


class C01RootSourceRuntimeLease:
    """One active set of pinned public-source and runtime file handles."""

    __slots__ = (
        "private_module",
        "cli_module",
        "root_entry_module",
        "root",
        "api",
        "_stack",
        "_source_files",
        "_software_files",
        "_directories",
        "_active",
        "_consumed",
        "_bound_scope",
        "_bound_root_bridge",
        "_helper_bindings",
        "_context_token",
        "_factory",
    )

    def __init__(
        self,
        private_module: ModuleType,
        cli_module: ModuleType,
        root_entry_module: ModuleType,
        exact_public_pins: Mapping[str, str],
        exact_software_pins: Mapping[Any, str],
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _C01_ROOT_POSTVERIFY_FACTORY:
            raise C01RootCustodyV16Error("source_runtime_factory_required")
        self.private_module = private_module
        self.cli_module = cli_module
        self.root_entry_module = root_entry_module
        self.root = _repository_root(private_module)
        self.api = None
        self._stack: Optional[ExitStack] = None
        self._source_files = _normalize_public_pins(self.root, exact_public_pins)
        self._software_files = _normalize_software_pins(exact_software_pins)
        self._directories: dict[str, _HeldDirectory] = {}
        self._active = False
        self._consumed = False
        self._bound_scope = None
        self._bound_root_bridge = None
        self._helper_bindings = None
        self._context_token = None
        self._factory = _C01_ROOT_POSTVERIFY_FACTORY

    def __repr__(self) -> str:
        return "C01RootSourceRuntimeLease(<held source/runtime files; values redacted>)"

    def __enter__(self) -> "C01RootSourceRuntimeLease":
        if self._active or self._consumed or _CURRENT_SOURCE_RUNTIME_LEASE.get() is not None:
            raise C01RootCustodyV16Error("source_runtime_lease_reused")
        _validate_helper_modules(self.private_module, self.cli_module)
        _validate_root_entry_module(self.root_entry_module, self.root)
        _validate_entry_owned_pins(
            self.root_entry_module, self.root, self._source_files, self._software_files
        )
        self._consumed = True
        self.api = self.private_module._api()
        _validate_private_api(self.api)
        stack = ExitStack()
        self._stack = stack
        try:
            all_paths = [path for path, _pin in self._source_files]
            all_paths.extend(path for path, _pin in self._software_files)
            self._open_ancestor_handles(stack, all_paths)
            self._source_files = self._open_files(stack, self._source_files, "public_source")
            self._software_files = self._open_files(stack, self._software_files, "software")
            self._active = True
            self._context_token = _CURRENT_SOURCE_RUNTIME_LEASE.set(self)
            self.verify()
            return self
        except Exception:
            self._active = False
            if self._context_token is not None:
                try:
                    _CURRENT_SOURCE_RUNTIME_LEASE.reset(self._context_token)
                except Exception:
                    pass
                self._context_token = None
            try:
                stack.close()
            except Exception:
                pass
            raise C01RootCustodyV16Error("source_runtime_lease_open_failed") from None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        failure = None
        try:
            current = _CURRENT_CANDIDATE_CUSTODY.get()
            if current is not None and current.source_runtime_lease is self:
                try:
                    _release_candidate_custody(current)
                except Exception:
                    failure = "candidate_custody_close_failed"
            if exc_type is None:
                try:
                    self.verify()
                except Exception:
                    failure = "source_runtime_postverify_failed"
        finally:
            self._active = False
            stack = self._stack
            self._stack = None
            if stack is not None:
                try:
                    stack.close()
                except Exception:
                    failure = failure or "source_runtime_close_failed"
            if self._context_token is not None:
                try:
                    _CURRENT_SOURCE_RUNTIME_LEASE.reset(self._context_token)
                except Exception:
                    failure = failure or "source_runtime_context_invalid"
                self._context_token = None
        if failure is not None and exc_type is None:
            raise C01RootCustodyV16Error(failure) from None
        return False

    def verify(self) -> None:
        if not self._active or self._factory is not _C01_ROOT_POSTVERIFY_FACTORY:
            raise C01RootCustodyV16Error("source_runtime_lease_inactive")
        try:
            self._verify_ancestor_handles()
            self._verify_file_group(self._source_files)
            self._verify_file_group(self._software_files)
            if self._bound_scope is not None:
                _validate_root_entry_module(self.root_entry_module, self.root)
                _validate_entry_owned_pins(
                    self.root_entry_module,
                    self.root,
                    self._source_files,
                    self._software_files,
                )
                expected = _expected_source_bindings(
                    self._bound_scope,
                    self._bound_root_bridge,
                    self.root_entry_module,
                    self,
                    require_active_helpers=False,
                )
                held = {_path_key(item.path): item for item in self._source_files}
                if any(
                    key not in held
                    or held[key].pin != pin
                    or hashlib.sha256(held[key].raw).hexdigest() != pin
                    for key, pin in expected.items()
                ):
                    raise C01RootCustodyV16Error("source_bundle_postverify_failed")
                _validate_runtime_pin_binding(self._bound_scope, self)
        except C01RootCustodyV16Error:
            raise
        except Exception:
            raise C01RootCustodyV16Error("source_runtime_identity_invalid") from None

    def verify_scope_sources(self, scope: Any, root_bridge_module: Optional[ModuleType]) -> None:
        """Bind currently held public bytes to every active source module."""

        if not self._active:
            raise C01RootCustodyV16Error("source_runtime_lease_inactive")
        require_active_helpers = self._bound_scope is None
        expected = _expected_source_bindings(
            scope,
            root_bridge_module,
            self.root_entry_module,
            self,
            require_active_helpers=require_active_helpers,
        )
        held = {_path_key(item.path): item for item in self._source_files}
        for key, pin in expected.items():
            entry = held.get(key)
            if entry is None or entry.pin != pin or hashlib.sha256(entry.raw).hexdigest() != pin:
                raise C01RootCustodyV16Error("source_bundle_postverify_failed")
        _validate_runtime_pin_binding(scope, self)
        self._bound_scope = scope
        self._bound_root_bridge = root_bridge_module

    def _open_ancestor_handles(self, stack: ExitStack, paths: list[Path]) -> None:
        assert self.api is not None
        parents: dict[str, Path] = {}
        for path in paths:
            if not path.is_absolute():
                raise C01RootCustodyV16Error("source_runtime_path_invalid")
            for ancestor in path.parents:
                parents[_path_key(ancestor)] = ancestor
        for key, path in sorted(
            parents.items(), key=lambda row: (len(row[1].parts), str(row[1]).casefold())
        ):
            handle = stack.enter_context(
                self.api.opened(path, directory=True, access=_DIRECTORY_READ_ACCESS)
            )
            identity = self.api.info(handle, directory=True)
            _validate_identity(identity)
            self._directories[key] = _HeldDirectory(path, handle, identity)

    def _open_files(
        self,
        stack: ExitStack,
        pins: list[tuple[Path, str]],
        role: str,
    ) -> list[_HeldFile]:
        assert self.api is not None
        result: list[_HeldFile] = []
        for path, pin in pins:
            handle, identity = stack.enter_context(
                self.cli_module._locked_readonly_file(
                    path, self.private_module, self.api, allow_hardlinks=True
                )
            )
            _validate_identity(identity)
            raw = self.cli_module._read_bounded_handle(
                self.api, handle, _max_bytes(path, role)
            )
            if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != pin:
                raise C01RootCustodyV16Error("source_runtime_pin_mismatch")
            result.append(_HeldFile(path, pin, role, handle, identity, raw))
        return result

    def _verify_ancestor_handles(self) -> None:
        assert self.api is not None
        for item in self._directories.values():
            current = self.api.info(item.handle, directory=True)
            if current != item.identity:
                raise C01RootCustodyV16Error("source_runtime_ancestor_changed")

    def _verify_file_group(self, files: list[_HeldFile]) -> None:
        assert self.api is not None
        for item in files:
            held_identity = self.cli_module._locked_file_identity(
                self.api, item.handle, self.private_module, allow_hardlinks=True
            )
            if held_identity != item.identity:
                raise C01RootCustodyV16Error("source_runtime_file_identity_changed")
            if self._bound_scope is not None:
                held_raw = _read_rewound_held_handle(
                    self._bound_scope,
                    self.private_module,
                    self.cli_module,
                    self.api,
                    item.handle,
                    _max_bytes(item.path, item.role),
                )
                if held_raw != item.raw:
                    raise C01RootCustodyV16Error("source_runtime_held_bytes_changed")
                if self.cli_module._locked_file_identity(
                    self.api, item.handle, self.private_module, allow_hardlinks=True
                ) != item.identity:
                    raise C01RootCustodyV16Error("source_runtime_file_identity_changed")
            with self.cli_module._locked_readonly_file(
                item.path, self.private_module, self.api, allow_hardlinks=True
            ) as (current_handle, current_identity):
                current_identity = self.cli_module._locked_file_identity(
                    self.api, current_handle, self.private_module, allow_hardlinks=True
                )
                if current_identity != item.identity:
                    raise C01RootCustodyV16Error("source_runtime_path_identity_changed")
                current_raw = self.cli_module._read_bounded_handle(
                    self.api, current_handle, _max_bytes(item.path, item.role)
                )
                if type(current_raw) is not bytes or current_raw != item.raw:
                    raise C01RootCustodyV16Error("source_runtime_bytes_changed")
            if (
                hashlib.sha256(item.raw).hexdigest() != item.pin
                or self.cli_module._locked_file_identity(
                    self.api, item.handle, self.private_module, allow_hardlinks=True
                )
                != item.identity
            ):
                raise C01RootCustodyV16Error("source_runtime_postverify_failed")


class _CandidateCustody:
    """Private state retained from issuer validation through Root postverify."""

    __slots__ = (
        "scope",
        "source_runtime_lease",
        "private_module",
        "cli_module",
        "api",
        "stack",
        "directories",
        "acl_directory_keys",
        "artifact_files",
        "candidate_refs",
        "account_scope_sha256",
        "credential_binding_sha256",
        "active",
        "context_token",
        "factory",
    )

    def __init__(
        self,
        scope: Any,
        source_runtime_lease: C01RootSourceRuntimeLease,
        private_module: ModuleType,
        cli_module: ModuleType,
        api: Any,
        stack: ExitStack,
        directories: dict[str, _HeldDirectory],
        acl_directory_keys: frozenset[str],
        artifact_files: list[_HeldFile],
        candidate_refs: tuple[Any, Any, Any, Any, dict[str, bytes]],
        account_scope_sha256: str,
        credential_binding_sha256: str,
    ) -> None:
        self.scope = scope
        self.source_runtime_lease = source_runtime_lease
        self.private_module = private_module
        self.cli_module = cli_module
        self.api = api
        self.stack = stack
        self.directories = directories
        self.acl_directory_keys = acl_directory_keys
        self.artifact_files = artifact_files
        self.candidate_refs = candidate_refs
        self.account_scope_sha256 = account_scope_sha256
        self.credential_binding_sha256 = credential_binding_sha256
        self.active = True
        self.context_token = None
        self.factory = _C01_ROOT_POSTVERIFY_FACTORY

    def __repr__(self) -> str:
        return "_CandidateCustody(<scope, account, and artifact references redacted>)"


class _RootReceipt:
    __slots__ = ("_scope", "_pending", "_nonce", "_factory")

    def __init__(self, scope: Any, pending: Any, *, _factory: Any = None) -> None:
        if _factory is not _C01_ROOT_POSTVERIFY_FACTORY:
            raise C01RootCustodyV16Error("postverify_receipt_factory_required")
        _validate_receipt_binding(scope, pending)
        self._scope = scope
        self._pending = pending
        self._nonce = scope.nonce
        self._factory = _C01_ROOT_POSTVERIFY_FACTORY

    def __repr__(self) -> str:
        return "{}(<scope, nonce, and private values redacted>)".format(type(self).__name__)


class C01RootSourcePostverifyReceipt(_RootReceipt):
    __slots__ = ("source_file_count",)

    def __init__(self, scope: Any, pending: Any, source_file_count: int, *, _factory=None):
        super().__init__(scope, pending, _factory=_factory)
        if type(source_file_count) is not int or source_file_count < 1:
            raise C01RootCustodyV16Error("source_postverify_invalid")
        self.source_file_count = source_file_count


class C01RootRuntimePostverifyReceipt(_RootReceipt):
    __slots__ = ("runtime_file_count",)

    def __init__(self, scope: Any, pending: Any, runtime_file_count: int, *, _factory=None):
        super().__init__(scope, pending, _factory=_factory)
        if type(runtime_file_count) is not int or runtime_file_count < 2:
            raise C01RootCustodyV16Error("runtime_postverify_invalid")
        self.runtime_file_count = runtime_file_count


class C01RootArtifactPostverifyReceipt(_RootReceipt):
    __slots__ = ("snapshot_count", "write_invocation_count")

    def __init__(self, scope: Any, pending: Any, *, _factory=None):
        super().__init__(scope, pending, _factory=_factory)
        self.snapshot_count = 2
        self.write_invocation_count = 0


class C01RootAccountBindingReceipt(_RootReceipt):
    __slots__ = ()


class C01RootNativeLedgerReceipt(_RootReceipt):
    __slots__ = (
        "_projection",
        "_source_bundle",
        "_issuer",
        "_owner",
        "_helpers",
        "_candidate_refs",
        "request_count",
        "auth_login_callback_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
    )

    def __init__(self, scope: Any, pending: Any, *, _factory=None):
        super().__init__(scope, pending, _factory=_factory)
        refs = scope.candidate_refs
        stage = scope.stage
        if (
            type(refs) is not tuple
            or len(refs) != 5
            or stage is None
            or any(
                type(getattr(stage, name, None)) is not int
                for name in (
                    "request_count",
                    "auth_login_callback_count",
                    "query_callback_count",
                    "snapshot_count",
                    "write_invocation_count",
                )
            )
            or stage.request_count != 8
            or stage.auth_login_callback_count != 2
            or stage.query_callback_count < 6
            or stage.snapshot_count != 2
            or stage.write_invocation_count != 0
        ):
            raise C01RootCustodyV16Error("native_ledger_receipt_invalid")
        self._projection = scope.projection
        self._source_bundle = scope.bundle
        self._issuer = scope.issuer
        self._owner = scope.owner
        self._helpers = scope.helpers
        self._candidate_refs = refs
        self.request_count = 8
        self.auth_login_callback_count = 2
        self.query_callback_count = stage.query_callback_count
        self.snapshot_count = 2
        self.write_invocation_count = 0

    def __repr__(self) -> str:
        return "C01RootNativeLedgerReceipt(<eight requests; private references redacted>)"


@contextmanager
def open_source_runtime_leases(
    private_module: ModuleType,
    cli_module: ModuleType,
    exact_public_pins: Mapping[str, str],
    exact_software_pins: Mapping[Any, str],
    *,
    root_entry_module: ModuleType,
) -> Iterator[C01RootSourceRuntimeLease]:
    """Hold exact public source and `.exe`/`.dll` bytes for one Root call.

    Public keys are repository-relative paths.  Software keys are absolute
    local paths; at least one executable and one DLL are required.  The same
    read-only file handles stay open through issuer completion and Root
    postverify, and are rechecked before the context exits.
    """

    lease = C01RootSourceRuntimeLease(
        private_module,
        cli_module,
        root_entry_module,
        exact_public_pins,
        exact_software_pins,
        _factory=_C01_ROOT_POSTVERIFY_FACTORY,
    )
    with lease:
        yield lease


def prepare_candidate_custody(
    scope: Any,
    admission: Any,
    pair_binding: Any,
    process: Any,
    validation: Any,
    artifacts: dict[str, bytes],
    credentials: Any,
    private_paths: Any,
) -> None:
    """Stage one validated issuer candidate and retain its private evidence.

    The V18 issuer calls this from its current process, after contract
    validation and before its original ExitStack closes.  Credentials are
    reduced to account and credential digests here; neither values nor digests
    are returned or serialized.
    """

    source_lease = _CURRENT_SOURCE_RUNTIME_LEASE.get()
    root_bridge_module = _root_bridge_for_scope(scope)
    _validate_active_scope(root_bridge_module, scope)
    if (
        type(source_lease) is not C01RootSourceRuntimeLease
        or not source_lease._active
        or source_lease._factory is not _C01_ROOT_POSTVERIFY_FACTORY
        or source_lease.private_module is not scope.helpers.get("private")
        or source_lease.cli_module is not scope.helpers.get("r3_cli")
    ):
        raise C01RootCustodyV16Error("source_runtime_binding_invalid")
    if _CURRENT_CANDIDATE_CUSTODY.get() is not None:
        raise C01RootCustodyV16Error("candidate_custody_reused")

    private_module = source_lease.private_module
    cli_module = source_lease.cli_module
    api = source_lease.api
    stack = ExitStack()
    try:
        source_lease.verify()
        source_lease.verify_scope_sources(scope, root_bridge_module)
        _validate_candidate_refs(
            scope,
            admission,
            pair_binding,
            process,
            validation,
            artifacts,
            credentials,
            private_paths,
        )
        account_digest, credential_digest = _compute_and_check_account_binding(
            scope, admission, process, credentials
        )
        directories, acl_directory_keys, artifact_files = _open_and_check_artifacts(
            scope, private_paths, artifacts, stack, api
        )

        # This bridge hook runs in the issuer process because the Root scope's
        # ContextVar is deliberately process local.  It retains the exact five
        # objects that will be checked again after issuer cleanup.
        root_bridge_module.stage_current_c01_candidate(
            admission=admission,
            pair_binding=pair_binding,
            process=process,
            validation=validation,
            artifacts=artifacts,
        )
        refs = scope.candidate_refs
        if (
            type(refs) is not tuple
            or len(refs) != 5
            or any(actual is not expected for actual, expected in zip(
                refs, (admission, pair_binding, process, validation, artifacts)
            ))
        ):
            raise C01RootCustodyV16Error("candidate_stage_binding_invalid")
        prepared = _CandidateCustody(
            scope,
            source_lease,
            private_module,
            cli_module,
            api,
            stack,
            directories,
            acl_directory_keys,
            artifact_files,
            refs,
            account_digest,
            credential_digest,
        )
        token = _CURRENT_CANDIDATE_CUSTODY.set(prepared)
        prepared.context_token = token
        return None
    except C01RootCustodyV16Error:
        try:
            stack.close()
        except Exception:
            pass
        raise
    except Exception:
        try:
            stack.close()
        except Exception:
            pass
        raise C01RootCustodyV16Error("candidate_custody_prepare_failed") from None


def verify_and_mint_postverify(
    root_bridge_module: ModuleType,
    scope: Any,
    pending: Any,
) -> Any:
    """Recheck physical custody, validate the finite ledger, and mint proof."""

    custody_module = _loaded_module()
    _validate_bridge_module(root_bridge_module)
    _validate_active_scope(root_bridge_module, scope)
    pending_type = _pending_result_type(root_bridge_module)
    prepared = _CURRENT_CANDIDATE_CUSTODY.get()
    if (
        type(pending_type) is not type
        or type(pending) is not pending_type
        or type(prepared) is not _CandidateCustody
        or not prepared.active
        or prepared.factory is not _C01_ROOT_POSTVERIFY_FACTORY
        or prepared.scope is not scope
        or prepared.source_runtime_lease is not _CURRENT_SOURCE_RUNTIME_LEASE.get()
        or scope.pending is not pending
        or pending._scope is not scope
        or pending._nonce is not scope.nonce
        or not scope.issuer_returned
        or scope.root_custody_module is not custody_module
        or not root_bridge_module._root_custody_module_is_pinned(custody_module)
    ):
        raise C01RootCustodyV16Error("postverify_binding_invalid")
    if (
        type(scope.candidate_refs) is not tuple
        or len(scope.candidate_refs) != 5
        or any(actual is not expected for actual, expected in zip(
            scope.candidate_refs, prepared.candidate_refs
        ))
    ):
        raise C01RootCustodyV16Error("candidate_refs_changed")

    proof = None
    try:
        prepared.source_runtime_lease.verify()
        prepared.source_runtime_lease.verify_scope_sources(scope, root_bridge_module)
        _verify_prepared_artifacts(prepared)
        _verify_account_ledger_binding(prepared)

        # This API is intentionally a finite validator, not a truthy receipt
        # factory.  No typed native receipt is constructed until it returns.
        root_bridge_module.verify_current_c01_request_ledger(scope, pending)
        native_receipt = C01RootNativeLedgerReceipt(
            scope, pending, _factory=_C01_ROOT_POSTVERIFY_FACTORY
        )
        root_bridge_module.record_root_native_ledger_receipt(
            scope,
            pending,
            root_custody_module=custody_module,
            receipt=native_receipt,
        )

        source_receipt = C01RootSourcePostverifyReceipt(
            scope,
            pending,
            len(prepared.source_runtime_lease._source_files),
            _factory=_C01_ROOT_POSTVERIFY_FACTORY,
        )
        runtime_receipt = C01RootRuntimePostverifyReceipt(
            scope,
            pending,
            len(prepared.source_runtime_lease._software_files),
            _factory=_C01_ROOT_POSTVERIFY_FACTORY,
        )
        artifact_receipt = C01RootArtifactPostverifyReceipt(
            scope, pending, _factory=_C01_ROOT_POSTVERIFY_FACTORY
        )
        account_receipt = C01RootAccountBindingReceipt(
            scope, pending, _factory=_C01_ROOT_POSTVERIFY_FACTORY
        )
        proof = root_bridge_module._mint_root_postverify_proof(
            scope=scope,
            pending=pending,
            source_postverify_receipt=source_receipt,
            runtime_postverify_receipt=runtime_receipt,
            artifact_postverify_receipt=artifact_receipt,
            account_binding_receipt=account_receipt,
            native_ledger_receipt=native_receipt,
        )
        return proof
    except C01RootCustodyV16Error:
        raise
    except Exception:
        raise C01RootCustodyV16Error("postverify_checks_failed") from None
    finally:
        _release_candidate_custody(prepared)


def _validate_candidate_refs(
    scope: Any,
    admission: Any,
    pair_binding: Any,
    process: Any,
    validation: Any,
    artifacts: Any,
    credentials: Any,
    private_paths: Any,
) -> None:
    if type(admission) is not getattr(scope.issuer, "_C01V18Admission", None):
        raise C01RootCustodyV16Error("candidate_admission_type_invalid")
    protocol = scope.protocol
    supervisor = scope.supervisor
    if (
        type(pair_binding) is not getattr(protocol, "C01PairBinding", None)
        or type(process) is not getattr(supervisor, "C01SupervisorResult", None)
        or type(validation) is not getattr(protocol, "C01CandidateValidation", None)
        or type(artifacts) is not dict
        or set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}
        or any(type(value) is not bytes or not value for value in artifacts.values())
        or type(credentials) is not getattr(scope.owner, "_Credentials", None)
        or type(private_paths) is not getattr(scope.owner, "_PrivateRun", None)
    ):
        raise C01RootCustodyV16Error("candidate_typed_binding_invalid")
    if (
        scope.stage_count != 0
        or scope.candidate_refs is not None
        or scope.verification is not None
        or scope.consumed
    ):
        raise C01RootCustodyV16Error("candidate_stage_reused")


def _compute_and_check_account_binding(
    scope: Any, admission: Any, process: Any, credentials: Any
) -> tuple[str, str]:
    try:
        protocol = scope.protocol
        worker_receipt_type = getattr(protocol, "C01WorkerReceipt", None)
        worker_receipt = getattr(process, "worker_receipt", None)
        if (
            type(worker_receipt_type) is not type
            or type(worker_receipt) is not worker_receipt_type
        ):
            raise ValueError
        account_digest = protocol.compute_account_scope_sha256(
            credentials.broker_id, credentials.user_id
        )
        credential_digest = protocol.compute_credential_binding_sha256(
            credentials.broker_id,
            credentials.user_id,
            credentials.password,
            credentials.app_id,
            credentials.auth_code,
            credentials.product_info,
        )
        bindings = admission.bindings
        worker = worker_receipt.to_dict()
        if (
            type(account_digest) is not str
            or not _SHA256_RE.fullmatch(account_digest)
            or type(credential_digest) is not str
            or not _SHA256_RE.fullmatch(credential_digest)
            or type(bindings) is not dict
            or type(worker) is not dict
            or bindings.get("account_scope_sha256") != account_digest
            or bindings.get("credential_binding_sha256") != credential_digest
            or worker.get("account_scope_sha256") != account_digest
            or worker.get("credential_binding_sha256") != credential_digest
        ):
            raise ValueError
        _check_worker_account_rows(worker, account_digest, credential_digest)
        return account_digest, credential_digest
    except Exception:
        raise C01RootCustodyV16Error("account_binding_invalid") from None


def _check_worker_account_rows(
    worker: Mapping[str, Any], account_digest: str, credential_digest: str
) -> None:
    requests = worker.get("requests")
    callbacks = worker.get("callbacks")
    if type(requests) is not list or type(callbacks) is not list:
        raise ValueError
    for row in requests + callbacks:
        if (
            type(row) is not dict
            or row.get("account_scope_sha256") != account_digest
            or row.get("credential_binding_sha256") != credential_digest
        ):
            raise ValueError


def _open_and_check_artifacts(
    scope: Any,
    private_paths: Any,
    artifacts: dict[str, bytes],
    stack: ExitStack,
    api: Any,
) -> tuple[dict[str, _HeldDirectory], frozenset[str], list[_HeldFile]]:
    private_module = scope.helpers["private"]
    cli_module = scope.helpers["r3_cli"]
    sid = api.current_sid()
    private_directory_type = getattr(private_module, "PrivateArtifactDirectory", None)
    if type(private_directory_type) is not type:
        raise C01RootCustodyV16Error("private_directory_type_invalid")

    directory_objects = (
        private_paths.root,
        private_paths.native_flow,
        private_paths.evidence,
    )
    directories: dict[str, _HeldDirectory] = {}
    paths_to_lock: list[Path] = []
    for directory in directory_objects:
        if type(directory) is not private_directory_type:
            raise C01RootCustodyV16Error("private_directory_type_invalid")
        directory.verify()
        path = directory.path
        if not isinstance(path, Path) or not path.is_absolute():
            raise C01RootCustodyV16Error("private_directory_path_invalid")
        paths_to_lock.append(path)
        paths_to_lock.extend(path.parents)

    snapshot_dir = private_paths.evidence.path / "snapshots"
    paths_to_lock.append(snapshot_dir)
    paths_to_lock.extend(snapshot_dir.parents)
    parent_map = {_path_key(path): path for path in paths_to_lock}
    acl_directory_keys = frozenset(
        _path_key(directory.path) for directory in directory_objects
    ) | frozenset({_path_key(snapshot_dir)})
    for key, path in sorted(
        parent_map.items(), key=lambda row: (len(row[1].parts), str(row[1]).casefold())
    ):
        handle = stack.enter_context(
            api.opened(path, directory=True, access=_DIRECTORY_READ_ACCESS)
        )
        identity = api.info(handle, directory=True)
        _validate_identity(identity)
        if key in acl_directory_keys:
            api.verify_acl(handle, sid, directory=True)
        directories[key] = _HeldDirectory(path, handle, identity)

    for directory in directory_objects:
        item = directories.get(_path_key(directory.path))
        if item is None or item.identity != (directory.device, directory.inode):
            raise C01RootCustodyV16Error("private_directory_identity_invalid")
    snapshot_directory = directories.get(_path_key(snapshot_dir))
    if snapshot_directory is None:
        raise C01RootCustodyV16Error("snapshot_directory_unavailable")
    entries = scope.owner._directory_entries(snapshot_dir)
    if {entry.name for entry in entries} != {"baseline.json", "final.json"}:
        raise C01RootCustodyV16Error("snapshot_directory_shape_invalid")

    max_bytes = getattr(scope.protocol, "MAX_PRIVATE_SNAPSHOT_BYTES", None)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise C01RootCustodyV16Error("snapshot_limit_invalid")
    result: list[_HeldFile] = []
    for name in ("baseline", "final"):
        relative = "snapshots/{}.json".format(name)
        path = private_paths.evidence.path / relative.replace("/", os.sep)
        handle, identity = stack.enter_context(
            cli_module._locked_readonly_file(path, private_module, api, allow_hardlinks=False)
        )
        _validate_identity(identity)
        api.verify_acl(handle, sid, directory=False, inherited=True)
        raw = cli_module._read_bounded_handle(api, handle, max_bytes)
        if (
            type(raw) is not bytes
            or not raw
            or len(raw) > max_bytes
            or raw != artifacts.get(relative)
        ):
            raise C01RootCustodyV16Error("snapshot_artifact_bytes_mismatch")
        result.append(_HeldFile(path, hashlib.sha256(raw).hexdigest(), "snapshot", handle, identity, raw))
    return directories, acl_directory_keys, result


def _verify_prepared_artifacts(prepared: _CandidateCustody) -> None:
    if not prepared.active:
        raise C01RootCustodyV16Error("artifact_custody_inactive")
    try:
        artifacts = prepared.candidate_refs[4]
        if (
            type(artifacts) is not dict
            or set(artifacts) != {"snapshots/baseline.json", "snapshots/final.json"}
            or any(
                artifacts.get("snapshots/{}.json".format(item.path.stem)) != item.raw
                for item in prepared.artifact_files
            )
        ):
            raise C01RootCustodyV16Error("snapshot_candidate_bytes_changed")
        sid = prepared.api.current_sid()
        for key, item in prepared.directories.items():
            if prepared.api.info(item.handle, directory=True) != item.identity:
                raise C01RootCustodyV16Error("artifact_ancestor_identity_changed")
            if key in prepared.acl_directory_keys:
                prepared.api.verify_acl(item.handle, sid, directory=True)
        for item in prepared.artifact_files:
            held_identity = prepared.cli_module._locked_file_identity(
                prepared.api, item.handle, prepared.private_module, allow_hardlinks=False
            )
            if held_identity != item.identity:
                raise C01RootCustodyV16Error("snapshot_identity_changed")
            prepared.api.verify_acl(item.handle, sid, directory=False, inherited=True)
            held_raw = _read_rewound_held_handle(
                prepared.scope,
                prepared.private_module,
                prepared.cli_module,
                prepared.api,
                item.handle,
                prepared.scope.protocol.MAX_PRIVATE_SNAPSHOT_BYTES,
            )
            if type(held_raw) is not bytes or held_raw != item.raw:
                raise C01RootCustodyV16Error("snapshot_held_bytes_changed")
            if prepared.cli_module._locked_file_identity(
                prepared.api,
                item.handle,
                prepared.private_module,
                allow_hardlinks=False,
            ) != item.identity:
                raise C01RootCustodyV16Error("snapshot_identity_changed")
            with prepared.cli_module._locked_readonly_file(
                item.path, prepared.private_module, prepared.api, allow_hardlinks=False
            ) as (current_handle, current_identity):
                current_identity = prepared.cli_module._locked_file_identity(
                    prepared.api,
                    current_handle,
                    prepared.private_module,
                    allow_hardlinks=False,
                )
                if current_identity != item.identity:
                    raise C01RootCustodyV16Error("snapshot_path_identity_changed")
                prepared.api.verify_acl(
                    current_handle, sid, directory=False, inherited=True
                )
                current = prepared.cli_module._read_bounded_handle(
                    prepared.api,
                    current_handle,
                    prepared.scope.protocol.MAX_PRIVATE_SNAPSHOT_BYTES,
                )
                if type(current) is not bytes or current != item.raw:
                    raise C01RootCustodyV16Error("snapshot_bytes_changed")
            if prepared.cli_module._locked_file_identity(
                prepared.api,
                item.handle,
                prepared.private_module,
                allow_hardlinks=False,
            ) != item.identity:
                raise C01RootCustodyV16Error("snapshot_identity_changed")
        expected_names = {"baseline.json", "final.json"}
        artifact_parent = prepared.artifact_files[0].path.parent
        current_names = {
            entry.name for entry in prepared.scope.owner._directory_entries(artifact_parent)
        }
        if current_names != expected_names:
            raise C01RootCustodyV16Error("snapshot_directory_shape_changed")
    except C01RootCustodyV16Error:
        raise
    except Exception:
        raise C01RootCustodyV16Error("artifact_postverify_failed") from None


def _verify_account_ledger_binding(prepared: _CandidateCustody) -> None:
    try:
        admission, pair_binding, process, _validation, _artifacts = prepared.candidate_refs
        bindings = admission.bindings
        worker = process.worker_receipt.to_dict()
        if (
            bindings.get("account_scope_sha256") != prepared.account_scope_sha256
            or bindings.get("credential_binding_sha256")
            != prepared.credential_binding_sha256
            or worker.get("account_scope_sha256") != prepared.account_scope_sha256
            or worker.get("credential_binding_sha256")
            != prepared.credential_binding_sha256
            or worker.get("pair_binding") != pair_binding.to_receipt_ref().to_dict()
        ):
            raise ValueError
        _check_worker_account_rows(
            worker,
            prepared.account_scope_sha256,
            prepared.credential_binding_sha256,
        )
    except Exception:
        raise C01RootCustodyV16Error("account_ledger_binding_invalid") from None


def _release_candidate_custody(prepared: _CandidateCustody) -> None:
    if type(prepared) is not _CandidateCustody or not prepared.active:
        return
    prepared.active = False
    failure = None
    try:
        prepared.stack.close()
    except Exception:
        failure = "artifact_handle_close_failed"
    if prepared.context_token is not None:
        try:
            _CURRENT_CANDIDATE_CUSTODY.reset(prepared.context_token)
        except Exception:
            failure = failure or "candidate_custody_context_invalid"
        prepared.context_token = None
    if failure is not None:
        raise C01RootCustodyV16Error(failure) from None


def _read_rewound_held_handle(
    scope: Any,
    private_module: ModuleType,
    cli_module: ModuleType,
    api: Any,
    handle: Any,
    maximum: int,
) -> bytes:
    issuer = scope.issuer
    rewind = getattr(issuer, "_rewind_locked_read_handle", None)
    if (
        type(issuer) is not ModuleType
        or type(rewind) is not FunctionType
        or rewind.__module__ != issuer.__name__
        or rewind.__qualname__ != "_rewind_locked_read_handle"
        or rewind.__globals__ is not issuer.__dict__
    ):
        raise C01RootCustodyV16Error("held_handle_rewind_helper_invalid")
    try:
        result = rewind(private_module, api, handle)
        if type(result) is not bool or not result:
            raise ValueError
        raw = cli_module._read_bounded_handle(api, handle, maximum)
        if type(raw) is not bytes or len(raw) > maximum:
            raise ValueError
        return raw
    except C01RootCustodyV16Error:
        raise
    except Exception:
        raise C01RootCustodyV16Error("held_handle_rewind_read_failed") from None


def _validate_receipt_binding(scope: Any, pending: Any) -> None:
    if (
        type(scope) is not getattr(_root_bridge_for_scope(scope), "_C01RootInvocationScope", None)
        or not scope.active
        or not scope.issuer_returned
        or scope.pending is not pending
        or pending._scope is not scope
        or pending._nonce is not scope.nonce
    ):
        raise C01RootCustodyV16Error("postverify_receipt_binding_invalid")


def _root_bridge_for_scope(scope: Any) -> ModuleType:
    module_name = type(scope).__module__
    module = sys.modules.get(module_name)
    if type(module) is not ModuleType:
        # Root may execute an exact held module under a private namespace.
        # In that case the active source/runtime lease is still the source of
        # identity, while verify_and_mint performs the exact module check.
        return _current_root_bridge_module()
    return module


def _current_root_bridge_module() -> ModuleType:
    lease = _CURRENT_SOURCE_RUNTIME_LEASE.get()
    if type(lease) is not C01RootSourceRuntimeLease or not lease._active:
        raise C01RootCustodyV16Error("source_runtime_lease_unavailable")
    # The V16 root module owns the current ContextVar and is installed by the
    # Root source loader under this exact public name.
    module = sys.modules.get(_ROOT_BRIDGE_NAME)
    if type(module) is not ModuleType:
        raise C01RootCustodyV16Error("root_bridge_module_unavailable")
    return module


def _pending_result_type(root_bridge_module: ModuleType) -> Any:
    value = getattr(root_bridge_module, "C01NativeTdReadV16CandidatePendingRootAdmission", None)
    return value if type(value) is type else None


def _validate_active_scope(root_bridge_module: ModuleType, scope: Any) -> None:
    _validate_bridge_module(root_bridge_module)
    bundle = getattr(scope, "bundle", None)
    front = getattr(scope, "front", None)
    bundle_type = getattr(front, "VerifiedC01V18SourceBundle", None)
    helpers = getattr(scope, "helpers", None)
    if (
        type(scope) is not getattr(root_bridge_module, "_C01RootInvocationScope", None)
        or scope.active is not True
        or type(front) is not ModuleType
        or type(bundle_type) is not type
        or type(bundle) is not bundle_type
        or bundle._active is not True
        or bundle._factory is not getattr(front, "_BUNDLE_FACTORY", None)
        or type(helpers) not in (dict, MappingProxyType)
        or bundle.issuer is not scope.issuer
        or bundle.owner is not scope.owner
        or bundle.helpers is not helpers
        or scope.protocol is not helpers.get("protocol")
        or scope.contract is not helpers.get("contract")
        or scope.supervisor is not helpers.get("supervisor")
        or type(scope.bridge) is not ModuleType
        or scope.bridge.__name__ != "common.c01_root_admission_bridge"
        or sys.modules.get(scope.bridge.__name__) is not scope.bridge
        or type(scope.certification_module) is not ModuleType
        or scope.certification_module.__name__ != "common.certification"
        or sys.modules.get(scope.certification_module.__name__)
        is not scope.certification_module
        or scope.root_custody_module is not _loaded_module()
        or root_bridge_module._CURRENT_SCOPE.get() is not scope
    ):
        raise C01RootCustodyV16Error("root_scope_binding_invalid")


def _validate_bridge_module(module: ModuleType) -> None:
    if (
        type(module) is not ModuleType
        or module.__name__ != _ROOT_BRIDGE_NAME
        or sys.modules.get(_ROOT_BRIDGE_NAME) is not module
        or module.__dict__ is not vars(module)
        or not callable(getattr(module, "stage_current_c01_candidate", None))
        or not callable(getattr(module, "verify_current_c01_request_ledger", None))
        or not callable(getattr(module, "record_root_native_ledger_receipt", None))
        or not callable(getattr(module, "_mint_root_postverify_proof", None))
        or not callable(getattr(module, "_root_custody_module_is_pinned", None))
    ):
        raise C01RootCustodyV16Error("root_bridge_module_invalid")


def _expected_source_bindings(
    scope: Any,
    root_bridge_module: Optional[ModuleType],
    root_entry_module: ModuleType,
    lease: C01RootSourceRuntimeLease,
    *,
    require_active_helpers: bool,
) -> dict[str, str]:
    expected: dict[str, str] = {}
    bundle_root = getattr(scope.bundle, "root", None)
    if (
        not isinstance(bundle_root, Path)
        or not bundle_root.is_absolute()
        or _path_key(bundle_root) != _path_key(lease.root)
    ):
        raise C01RootCustodyV16Error("source_bundle_root_invalid")

    modules = [
        scope.front,
        scope.issuer,
        scope.bridge,
        scope.certification_module,
        root_entry_module,
    ]
    if root_bridge_module is not None:
        modules.append(root_bridge_module)
    modules.append(_loaded_module())
    for module in modules:
        _validate_loaded_module_source(module, bundle_root)
        _add_module_pin(expected, module, getattr(module, "__c01_source_sha256__", None))

    custody_module = _loaded_module()

    owner = scope.owner
    owner_pins = getattr(owner, "_SOURCE_PINS", None)
    if type(owner_pins) not in (dict, MappingProxyType):
        raise C01RootCustodyV16Error("source_pin_manifest_invalid")
    try:
        normalized_owner_pins: dict[str, str] = {}
        for relative, pin in owner_pins.items():
            if type(relative) is not str or type(pin) is not str or not _SHA256_RE.fullmatch(pin):
                raise ValueError
            normalized_owner_pins[relative.replace("\\", "/")] = pin
            _add_path_pin(expected, bundle_root / Path(relative), pin)
    except Exception:
        raise C01RootCustodyV16Error("source_pin_manifest_invalid") from None

    issuer = scope.issuer
    owner_path = getattr(owner, "__file__", None)
    owner_pin = getattr(issuer, "_OWNER_SHA256", None)
    if owner_pin is None:
        owner_pin = getattr(owner, "__c01_source_sha256__", None)
    if type(owner_path) is str and type(owner_pin) is str and _SHA256_RE.fullmatch(owner_pin):
        owner_source_path = Path(owner_path)
        _relative_source_path(bundle_root, owner_source_path)
        _validate_owner_module_source(owner, issuer, bundle_root, owner_pin)
        _add_path_pin(expected, owner_source_path, owner_pin)
    else:
        raise C01RootCustodyV16Error("owner_source_pin_missing")

    _verify_front_owner_source_links(
        scope,
        bundle_root,
        normalized_owner_pins,
        lease,
        require_active_helpers=require_active_helpers,
    )

    manifest_path = _relative_declared_path(
        bundle_root, issuer, "_SOURCE_MANIFEST_PATH"
    )
    manifest_pin = _declared_pin(issuer, "_SOURCE_MANIFEST_SHA256")
    _add_path_pin(expected, manifest_path, manifest_pin)
    admission_schema_path = _relative_declared_path(
        bundle_root, issuer, "_ADMISSION_SCHEMA_PATH"
    )
    admission_schema_pin = _declared_pin(issuer, "_ADMISSION_SCHEMA_SHA256")
    _add_path_pin(expected, admission_schema_path, admission_schema_pin)

    fixed_paths = (
        ("_CASE_CONTRACT_PATH", "_CASE_CONTRACT_SHA256"),
        ("_CASE_STRATEGY_PATH", "_CASE_STRATEGY_SHA256"),
        ("_ENVREF_TEMPLATE_PATH", "_ENVREF_TEMPLATE_SHA256"),
    )
    for path_attr, pin_attr in fixed_paths:
        declared = getattr(issuer, path_attr, None)
        if declared is None:
            default_paths = {
                "_CASE_CONTRACT_PATH": "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml",
                "_CASE_STRATEGY_PATH": "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py",
                "_ENVREF_TEMPLATE_PATH": "examples/000_live_certification/simnow_penetration/config.private.yaml.template",
            }
            declared = default_paths[path_attr]
        pin = _declared_pin(issuer, pin_attr)
        _add_path_pin(expected, _absolute_source_path(bundle_root, declared), pin)

    _verify_issuer_manifest_rows(
        issuer,
        owner,
        bundle_root,
        manifest_path,
        manifest_pin,
        normalized_owner_pins,
        lease,
        expected,
    )

    _add_module_pin(expected, custody_module, getattr(custody_module, "__c01_source_sha256__", None))
    _add_module_pin(
        expected,
        root_entry_module,
        getattr(root_entry_module, "__c01_source_sha256__", None),
    )

    return expected


def _verify_issuer_manifest_rows(
    issuer: ModuleType,
    owner: ModuleType,
    root: Path,
    manifest_path: Path,
    manifest_pin: str,
    owner_pins: dict[str, str],
    lease: C01RootSourceRuntimeLease,
    expected: dict[str, str],
) -> None:
    held = {_path_key(item.path): item for item in lease._source_files}
    manifest_file = held.get(_path_key(manifest_path))
    if (
        manifest_file is None
        or manifest_file.pin != manifest_pin
        or hashlib.sha256(manifest_file.raw).hexdigest() != manifest_pin
    ):
        raise C01RootCustodyV16Error("source_manifest_handle_missing")
    try:
        document = json.loads(
            manifest_file.raw.decode("ascii"), object_pairs_hook=_strict_source_object
        )
        if type(document) is not dict or set(document) != {
            "schema",
            "profile_id",
            "source_files",
            "admission_bound_files",
        }:
            raise ValueError
        profile_id = getattr(issuer, "PROFILE_ID", None)
        if type(profile_id) is not str or not profile_id.startswith("C01_NATIVE_TD_READ_V"):
            raise ValueError
        profile_suffix = profile_id.rsplit("_", 1)[-1].lower()
        if (
            document.get("schema") != "simnow.c01.native_td_read_{}.source_manifest.v1".format(
                profile_suffix
            )
            or document.get("profile_id") != profile_id
            or type(document.get("source_files")) is not dict
        ):
            raise ValueError

        expected_manifest_rows = dict(owner_pins)
        owner_path = getattr(owner, "__file__", None)
        if type(owner_path) is not str:
            raise ValueError
        owner_relative = _relative_source_path(root, Path(owner_path))
        expected_manifest_rows[owner_relative] = _declared_pin(issuer, "_OWNER_SHA256")
        known_rows = (
            ("_CASE_CONTRACT_PATH", "_CASE_CONTRACT_SHA256", "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml"),
            ("_CASE_STRATEGY_PATH", "_CASE_STRATEGY_SHA256", "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py"),
            ("_ENVREF_TEMPLATE_PATH", "_ENVREF_TEMPLATE_SHA256", "examples/000_live_certification/simnow_penetration/config.private.yaml.template"),
            ("_ADMISSION_SCHEMA_PATH", "_ADMISSION_SCHEMA_SHA256", None),
        )
        for path_attr, pin_attr, default_path in known_rows:
            relative = getattr(issuer, path_attr, None)
            if relative is None:
                relative = default_path
            if type(relative) is not str:
                raise ValueError
            normalized = relative.replace("\\", "/")
            expected_manifest_rows[normalized] = _declared_pin(issuer, pin_attr)
        if document["source_files"] != expected_manifest_rows:
            raise ValueError

        admission_bound_files = getattr(issuer, "_ADMISSION_BOUND_SOURCE_PATHS", None)
        if (
            type(admission_bound_files) is not tuple
            or len(admission_bound_files) != 2
            or any(type(item) is not str for item in admission_bound_files)
            or document.get("admission_bound_files") != list(admission_bound_files)
        ):
            raise ValueError
        declared_pins = {_path_key(item.path): item.pin for item in lease._source_files}
        for relative in admission_bound_files:
            path = _absolute_source_path(root, relative)
            if _path_key(path) not in declared_pins:
                raise ValueError
            row_pin = expected_manifest_rows.get(relative)
            if row_pin is not None and declared_pins[_path_key(path)] != row_pin:
                raise ValueError
            if _path_key(path) == _path_key(Path(getattr(issuer, "__file__", ""))):
                if declared_pins[_path_key(path)] != getattr(issuer, "__c01_source_sha256__", None):
                    raise ValueError
            _add_path_pin(expected, path, declared_pins[_path_key(path)])
    except C01RootCustodyV16Error:
        raise
    except Exception:
        raise C01RootCustodyV16Error("source_manifest_rows_invalid") from None


def _verify_front_owner_source_links(
    scope: Any,
    root: Path,
    owner_pins: dict[str, str],
    lease: C01RootSourceRuntimeLease,
    *,
    require_active_helpers: bool,
) -> None:
    """Tie active front, issuer, owner, and helper globals to held pin rows."""

    front = scope.front
    issuer = scope.issuer
    owner = scope.owner
    expected_issuer_path = getattr(front, "_V18_RELATIVE", None)
    expected_issuer_pin = getattr(front, "_V18_SHA256", None)
    if (
        type(expected_issuer_path) is not str
        or expected_issuer_path != "backtrader_runtime/certification_simnow_c01_native_td_read_v18.py"
        or type(expected_issuer_pin) is not str
        or not _SHA256_RE.fullmatch(expected_issuer_pin)
        or getattr(front, "_V18_MODULE_NAME", None) != issuer.__name__
        or getattr(issuer, "__c01_source_sha256__", None) != expected_issuer_pin
        or _path_key(Path(issuer.__file__)) != _path_key(_absolute_source_path(root, expected_issuer_path))
        or getattr(issuer, "_OWNER_MODULE_NAME", None) != owner.__name__
    ):
        raise C01RootCustodyV16Error("front_issuer_source_binding_invalid")

    declared_owner = _declared_pin(issuer, "_OWNER_SHA256")
    owner_relative = _relative_source_path(root, Path(owner.__file__))
    if (
        owner_relative != "backtrader_runtime/certification_simnow_c01_v7_owner.py"
        or getattr(owner, "__c01_source_sha256__", None) not in (None, declared_owner)
    ):
        raise C01RootCustodyV16Error("issuer_owner_source_pin_mismatch")
    _validate_owner_module_source(owner, issuer, root, declared_owner)

    issuer_owner_rows = (
        ("_WORKER_SHA256", "backtrader_runtime/certification_simnow_c01_native_v4.py"),
        ("_PROTOCOL_SHA256", "backtrader_runtime/certification_simnow_c01_v3_protocol.py"),
        ("_CONTRACT_SHA256", "backtrader_runtime/certification_simnow_c01_v3_contract.py"),
        ("_SUPERVISOR_SHA256", "backtrader_runtime/certification_simnow_c01_v4_supervisor.py"),
        ("_DEPENDENCY_MANIFEST_SHA256", "backtrader_runtime/certification_simnow_c01_dependencies_v1.json"),
        ("_PRIVATE_HELPER_SHA256", "backtrader_runtime/certification_roundtrip_private.py"),
        ("_R3_CLI_HELPER_SHA256", "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"),
        ("_INTERPRETER_BINDING_SHA256", "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"),
    )
    for pin_name, relative in issuer_owner_rows:
        if _declared_pin(issuer, pin_name) != owner_pins.get(relative):
            raise C01RootCustodyV16Error("issuer_helper_source_pin_mismatch")

    module_paths = getattr(owner, "_MODULE_PATHS", None)
    if type(module_paths) not in (dict, MappingProxyType):
        raise C01RootCustodyV16Error("owner_helper_source_map_invalid")
    _verify_owner_helper_modules(
        scope,
        root,
        owner_pins,
        module_paths,
        lease,
        require_active=require_active_helpers,
    )

    bridge = scope.root_bridge_module if hasattr(scope, "root_bridge_module") else None
    if bridge is None:
        bridge = sys.modules.get(_ROOT_BRIDGE_NAME)
    if type(bridge) is not ModuleType:
        raise C01RootCustodyV16Error("root_bridge_module_unavailable")
    if (
        getattr(bridge, "_FRONT_MODULE_SHA256", None) != getattr(front, "__c01_source_sha256__", None)
        or getattr(bridge, "_BRIDGE_SHA256", None) != getattr(scope.bridge, "__c01_source_sha256__", None)
        or getattr(bridge, "_CERTIFICATION_MODULE_SHA256", None)
        != getattr(scope.certification_module, "__c01_source_sha256__", None)
        or getattr(bridge, "_ROOT_CUSTODY_MODULE_SHA256", None)
        != getattr(_loaded_module(), "__c01_source_sha256__", None)
    ):
        raise C01RootCustodyV16Error("root_source_pin_links_invalid")


def _validate_owner_module_source(
    owner: ModuleType, issuer: ModuleType, root: Path, expected_pin: str
) -> None:
    name = getattr(issuer, "_OWNER_MODULE_NAME", None)
    path = root / "backtrader_runtime" / "certification_simnow_c01_v7_owner.py"
    marker = getattr(owner, "__c01_source_sha256__", None)
    spec = getattr(owner, "__spec__", None)
    if (
        type(owner) is not ModuleType
        or type(name) is not str
        or owner.__name__ != name
        or sys.modules.get(name) is not owner
        or owner.__dict__ is not vars(owner)
        or _path_key(Path(owner.__file__)) != _path_key(path)
        or owner.__package__ != "backtrader_runtime"
        or owner.__loader__ is not None
        or type(spec) is not ModuleSpec
        or spec.name != name
        or spec.loader is not None
        or marker not in (None, expected_pin)
    ):
        raise C01RootCustodyV16Error("owner_module_loader_binding_invalid")


def _verify_owner_helper_modules(
    scope: Any,
    root: Path,
    owner_pins: dict[str, str],
    module_paths: Mapping[str, str],
    lease: C01RootSourceRuntimeLease,
    *,
    require_active: bool,
) -> None:
    try:
        helpers = scope.helpers
        loaded = {
            module.__name__: module
            for module in helpers.values()
            if type(module) is ModuleType
        }
        expected_names = set(module_paths)
        if set(loaded) != expected_names:
            raise ValueError
        snapshots = dict(lease._helper_bindings or ())
        if require_active and snapshots:
            raise ValueError
        if not require_active and set(snapshots) != expected_names:
            raise ValueError
        for module_name, relative in module_paths.items():
            if type(module_name) is not str or type(relative) is not str:
                raise ValueError
            normalized = relative.replace("\\", "/")
            pin = owner_pins.get(normalized)
            path = _absolute_source_path(root, normalized)
            module = loaded[module_name]
            package_name, _, child_name = module_name.rpartition(".")
            spec = getattr(module, "__spec__", None)
            marker = getattr(module, "__c01_source_sha256__", None)
            if (
                type(module) is not ModuleType
                or module.__dict__ is not vars(module)
                or _path_key(Path(module.__file__)) != _path_key(path)
                or module.__package__ != package_name
                or module.__loader__ is not None
                or type(spec) is not ModuleSpec
                or spec.name != module_name
                or spec.loader is not None
                or marker not in (None, pin)
                or pin is None
            ):
                raise ValueError
            if require_active:
                parent = sys.modules.get(package_name)
                expected_package_path = root.joinpath(*package_name.split(".")).resolve(
                    strict=True
                )
                parent_spec = getattr(parent, "__spec__", None)
                if (
                    sys.modules.get(module_name) is not module
                    or type(parent) is not ModuleType
                    or getattr(parent, "__path__", None)
                    != [str(expected_package_path)]
                    or type(parent_spec) is not ModuleSpec
                    or parent_spec.name != package_name
                    or parent_spec.loader is not None
                    or getattr(parent, child_name, None) is not module
                ):
                    raise ValueError
            elif snapshots.get(module_name) is not module:
                raise ValueError
            _verify_module_defined_functions(module, path)

        owner = scope.owner
        owner_now_utc = helpers.get("owner_now_utc")
        _verify_module_defined_function(owner, "_now_utc", owner_now_utc, Path(owner.__file__))
        if require_active:
            lease._helper_bindings = tuple(sorted(loaded.items()))
    except C01RootCustodyV16Error:
        raise
    except Exception:
        raise C01RootCustodyV16Error("owner_helper_source_binding_invalid") from None


def _verify_module_defined_functions(module: ModuleType, path: Path) -> None:
    for value in vars(module).values():
        if type(value) is not FunctionType or value.__module__ != module.__name__:
            continue
        _verify_module_defined_function(module, value.__name__, value, path)


def _verify_module_defined_function(
    module: ModuleType, name: str, function: Any, path: Path
) -> None:
    if type(function) is not FunctionType:
        raise ValueError
    target = function
    if function.__globals__ is not module.__dict__:
        wrapped = getattr(function, "__wrapped__", None)
        contextlib_module = sys.modules.get("contextlib")
        if (
            type(wrapped) is not FunctionType
            or contextlib_module is None
            or function.__globals__ is not contextlib_module.__dict__
            or Path(function.__code__.co_filename).name != "contextlib.py"
            or function.__module__ != module.__name__
            or function.__qualname__ != wrapped.__qualname__
            or function.__name__ != wrapped.__name__
        ):
            raise ValueError
        target = wrapped
    if (
        target.__module__ != module.__name__
        or target.__qualname__ != name
        or target.__globals__ is not module.__dict__
        or _path_key(Path(target.__code__.co_filename)) != _path_key(path)
    ):
        raise ValueError


def _strict_source_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_source_key")
        result[key] = value
    return result


def _validate_loaded_module_source(module: ModuleType, root: Path) -> None:
    if type(module) is not ModuleType or module.__dict__ is not vars(module):
        raise C01RootCustodyV16Error("source_module_identity_invalid")
    name = getattr(module, "__name__", None)
    path_text = getattr(module, "__file__", None)
    marker = getattr(module, "__c01_source_sha256__", None)
    if (
        type(name) is not str
        or sys.modules.get(name) is not module
        or type(path_text) is not str
        or type(marker) is not str
        or not _SHA256_RE.fullmatch(marker)
    ):
        raise C01RootCustodyV16Error("source_module_identity_invalid")
    _relative_source_path(root, Path(path_text))


def _relative_source_path(root: Path, path: Path) -> str:
    if not isinstance(path, Path) or not path.is_absolute():
        raise C01RootCustodyV16Error("source_module_path_invalid")
    try:
        relative = path.relative_to(root).as_posix()
    except Exception:
        raise C01RootCustodyV16Error("source_module_path_invalid") from None
    if not relative or relative.startswith("../"):
        raise C01RootCustodyV16Error("source_module_path_invalid")
    return relative


def _absolute_source_path(root: Path, value: Any) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise C01RootCustodyV16Error("source_path_pin_invalid")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise C01RootCustodyV16Error("source_path_pin_invalid")
    result = root / path
    _relative_source_path(root, result)
    return result


def _relative_declared_path(root: Path, module: ModuleType, attr: str) -> Path:
    value = getattr(module, attr, None)
    return _absolute_source_path(root, value)


def _declared_pin(module: ModuleType, attr: str) -> str:
    value = getattr(module, attr, None)
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise C01RootCustodyV16Error("issuer_source_pin_invalid")
    return value


def _add_issuer_declared_pin(
    expected: dict[str, str], bundle_root: Path, issuer: ModuleType, path_name: str, pin_name: str
) -> None:
    relative = getattr(issuer, path_name, None)
    pin = getattr(issuer, pin_name, None)
    if relative is None and pin is None:
        return
    if type(relative) is not str or type(pin) is not str or not _SHA256_RE.fullmatch(pin):
        raise C01RootCustodyV16Error("issuer_source_pin_invalid")
    _add_path_pin(expected, bundle_root / Path(relative), pin)


def _add_module_pin(expected: dict[str, str], module: ModuleType, pin: Any) -> None:
    if type(module) is not ModuleType or type(pin) is not str or not _SHA256_RE.fullmatch(pin):
        raise C01RootCustodyV16Error("module_source_pin_invalid")
    module_path = getattr(module, "__file__", None)
    if type(module_path) is not str:
        raise C01RootCustodyV16Error("module_source_path_missing")
    _add_path_pin(expected, Path(module_path), pin)


def _add_path_pin(expected: dict[str, str], path: Path, pin: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or type(pin) is not str or not _SHA256_RE.fullmatch(pin):
        raise C01RootCustodyV16Error("source_path_pin_invalid")
    key = _path_key(path)
    prior = expected.get(key)
    if prior is not None and prior != pin:
        raise C01RootCustodyV16Error("source_path_pin_conflict")
    expected[key] = pin


def _repository_root(private_module: ModuleType) -> Path:
    if type(private_module) is not ModuleType:
        raise C01RootCustodyV16Error("private_helper_module_invalid")
    module_path = getattr(private_module, "__file__", None)
    if type(module_path) is not str:
        raise C01RootCustodyV16Error("private_helper_source_path_missing")
    path = Path(module_path)
    if not path.is_absolute() or len(path.parents) < 2:
        raise C01RootCustodyV16Error("private_helper_source_path_invalid")
    root = path.parents[1]
    if path.name != "certification_roundtrip_private.py" or path.parent.name != "backtrader_runtime":
        raise C01RootCustodyV16Error("private_helper_source_path_invalid")
    return root


def _normalize_public_pins(root: Path, pins: Mapping[str, str]) -> list[tuple[Path, str]]:
    if type(pins) is not dict:
        raise C01RootCustodyV16Error("public_pins_mapping_invalid")
    if not pins:
        raise C01RootCustodyV16Error("public_pins_empty")
    result: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for relative, pin in pins.items():
        if type(relative) is not str or type(pin) is not str or not _SHA256_RE.fullmatch(pin):
            raise C01RootCustodyV16Error("public_pin_invalid")
        posix = relative.replace("\\", "/")
        parts = posix.split("/")
        if (
            not posix
            or posix.startswith("/")
            or ":" in posix
            or any(part in {"", ".", ".."} for part in parts)
            or parts[-1].lower() in _PRIVATE_NAMES
        ):
            raise C01RootCustodyV16Error("public_path_invalid")
        path = root.joinpath(*parts)
        key = _path_key(path)
        if key in seen:
            raise C01RootCustodyV16Error("public_path_duplicate")
        seen.add(key)
        result.append((path, pin))
    result.sort(key=lambda row: _path_key(row[0]))
    return result


def _normalize_software_pins(pins: Mapping[Any, str]) -> list[tuple[Path, str]]:
    if type(pins) is not dict or not pins:
        raise C01RootCustodyV16Error("software_pins_mapping_invalid")
    result: list[tuple[Path, str]] = []
    seen: set[str] = set()
    suffixes: set[str] = set()
    for raw_path, pin in pins.items():
        if type(raw_path) not in (str, Path) and not isinstance(raw_path, Path):
            raise C01RootCustodyV16Error("software_path_invalid")
        if type(pin) is not str or not _SHA256_RE.fullmatch(pin):
            raise C01RootCustodyV16Error("software_pin_invalid")
        path = Path(raw_path)
        suffix = path.suffix.lower()
        if not path.is_absolute() or suffix not in {".exe", ".dll", ".pyd"}:
            raise C01RootCustodyV16Error("software_path_invalid")
        if ".." in path.parts:
            raise C01RootCustodyV16Error("software_path_invalid")
        key = _path_key(path)
        if key in seen:
            raise C01RootCustodyV16Error("software_path_duplicate")
        seen.add(key)
        suffixes.add(suffix)
        result.append((path, pin))
    if ".exe" not in suffixes or ".dll" not in suffixes:
        raise C01RootCustodyV16Error("software_runtime_set_incomplete")
    result.sort(key=lambda row: _path_key(row[0]))
    return result


def _validate_helper_modules(private_module: ModuleType, cli_module: ModuleType) -> None:
    if (
        type(private_module) is not ModuleType
        or type(cli_module) is not ModuleType
        or not callable(getattr(private_module, "_api", None))
        or not callable(getattr(cli_module, "_locked_readonly_file", None))
        or not callable(getattr(cli_module, "_locked_file_identity", None))
        or not callable(getattr(cli_module, "_read_bounded_handle", None))
    ):
        raise C01RootCustodyV16Error("private_helper_api_invalid")


def _validate_private_api(api: Any) -> None:
    if any(
        not callable(getattr(api, name, None))
        for name in ("opened", "info", "verify_acl", "current_sid")
    ):
        raise C01RootCustodyV16Error("private_helper_api_invalid")


def _validate_root_entry_module(module: ModuleType, root: Path) -> None:
    try:
        if (
            type(module) is not ModuleType
            or module.__name__ != _ROOT_ENTRY_NAME
            or sys.modules.get(_ROOT_ENTRY_NAME) is not module
            or module.__dict__ is not vars(module)
            or type(getattr(module, "__c01_source_sha256__", None)) is not str
            or not _SHA256_RE.fullmatch(module.__c01_source_sha256__)
        ):
            raise ValueError
        path_text = getattr(module, "__file__", None)
        if type(path_text) is not str:
            raise ValueError
        path = Path(path_text)
        expected = root / "backtrader_runtime" / "certification_simnow_c01_root_entry_v18.py"
        if _path_key(path) != _path_key(expected):
            raise ValueError
        function = getattr(module, "_C01_ROOT_ENTRY_CALLABLE", None)
        if not callable(function) or getattr(function, "__globals__", None) is not module.__dict__:
            raise ValueError
    except Exception:
        raise C01RootCustodyV16Error("root_entry_module_binding_invalid") from None


def _validate_entry_owned_pins(
    module: ModuleType,
    root: Path,
    source_files: list[_HeldFile],
    software_files: list[_HeldFile],
) -> None:
    try:
        source_rows = getattr(module, "_EXACT_PUBLIC_SOURCE_PINS", None)
        software_rows = getattr(module, "_EXACT_SOFTWARE_PINS", None)
        if type(source_rows) is not dict or type(software_rows) is not dict:
            raise ValueError
        declared = _normalize_public_pins(root, source_rows)
        entry_path = Path(module.__file__)
        entry_relative = _relative_source_path(root, entry_path)
        if entry_relative in source_rows:
            raise ValueError
        exact_source_rows = {_path_key(path): pin for path, pin in declared}
        exact_source_rows[_path_key(entry_path)] = module.__c01_source_sha256__
        actual_source_rows = {
            _path_key(path): pin for path, pin in _pin_pairs(source_files)
        }
        if actual_source_rows != exact_source_rows:
            raise ValueError
        declared_software = _normalize_software_pins(software_rows)
        exact_software_rows = {_path_key(path): pin for path, pin in declared_software}
        actual_software_rows = {
            _path_key(path): pin for path, pin in _pin_pairs(software_files)
        }
        if actual_software_rows != exact_software_rows:
            raise ValueError
    except Exception:
        raise C01RootCustodyV16Error("root_entry_pin_map_mismatch") from None


def _pin_pairs(items: list[Any]) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    for item in items:
        if type(item) is _HeldFile:
            result.append((item.path, item.pin))
        elif type(item) is tuple and len(item) == 2 and isinstance(item[0], Path):
            result.append((item[0], item[1]))
        else:
            raise C01RootCustodyV16Error("source_pin_rows_invalid")
    return result


def _validate_runtime_pin_binding(scope: Any, lease: C01RootSourceRuntimeLease) -> None:
    try:
        binding = scope.helpers["interpreter_binding"]
        issuer = scope.issuer
        binding_path = _relative_declared_path(
            lease.root, issuer, "_INTERPRETER_BINDING_PATH"
        )
        binding_pin = _declared_pin(issuer, "_INTERPRETER_BINDING_SHA256")
        owner_pins = getattr(scope.owner, "_SOURCE_PINS", None)
        relative = _relative_source_path(lease.root, Path(binding.__file__))
        if (
            relative != "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
            or _path_key(Path(binding.__file__)) != _path_key(binding_path)
            or type(owner_pins) not in (dict, MappingProxyType)
            or owner_pins.get(relative) != binding_pin
            or getattr(binding, "__c01_source_sha256__", None) not in (None, binding_pin)
            or lease._helper_bindings is None
            or dict(lease._helper_bindings).get(binding.__name__) is not binding
        ):
            raise ValueError
        expected = {
            _path_key(Path(binding.CPYTHON_EXECUTABLE)): binding.CPYTHON_EXECUTABLE_SHA256,
            _path_key(Path(binding.CPYTHON_DLL)): binding.CPYTHON_DLL_SHA256,
        }
        actual = {_path_key(item.path): item.pin for item in lease._software_files}
        if (
            actual != expected
            or len(expected) != 2
            or type(binding.CPYTHON_EXECUTABLE_SHA256) is not str
            or not _SHA256_RE.fullmatch(binding.CPYTHON_EXECUTABLE_SHA256)
            or type(binding.CPYTHON_DLL_SHA256) is not str
            or not _SHA256_RE.fullmatch(binding.CPYTHON_DLL_SHA256)
        ):
            raise ValueError
    except Exception:
        raise C01RootCustodyV16Error("software_interpreter_binding_invalid") from None


def _max_bytes(path: Path, role: str) -> int:
    if role == "public_source":
        return _MAX_SOURCE_BYTES
    suffix = path.suffix.lower()
    if suffix == ".dll":
        return _MAX_DLL_BYTES
    if suffix == ".pyd":
        return _MAX_EXTENSION_BYTES
    return _MAX_EXECUTABLE_BYTES


def _validate_identity(identity: Any) -> None:
    if (
        type(identity) is not tuple
        or len(identity) != 2
        or any(type(value) is not int or value < 0 for value in identity)
    ):
        raise C01RootCustodyV16Error("file_identity_invalid")


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _loaded_module() -> ModuleType:
    module = sys.modules.get(_MODULE_NAME)
    if type(module) is not ModuleType:
        raise C01RootCustodyV16Error("root_custody_module_unavailable")
    marker = getattr(module, "__c01_source_sha256__", None)
    if type(marker) is not str or not _SHA256_RE.fullmatch(marker):
        raise C01RootCustodyV16Error("root_custody_source_marker_invalid")
    return module


__all__ = [
    "C01RootAccountBindingReceipt",
    "C01RootArtifactPostverifyReceipt",
    "C01RootCustodyV16Error",
    "C01RootNativeLedgerReceipt",
    "C01RootRuntimePostverifyReceipt",
    "C01RootSourcePostverifyReceipt",
    "C01RootSourceRuntimeLease",
    "open_source_runtime_leases",
    "prepare_candidate_custody",
    "verify_and_mint_postverify",
]
