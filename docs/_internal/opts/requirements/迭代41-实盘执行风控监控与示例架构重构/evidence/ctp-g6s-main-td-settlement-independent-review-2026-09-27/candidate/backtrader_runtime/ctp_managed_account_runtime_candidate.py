"""Unregistered account-wide composition for the managed CTP candidate.

This module is deliberately opt-in and has no default runtime registration.
The local candidate composes one sealed simulation/live scope, one V20 Store
account-family owner, and the existing I9 session owner.  It does not provide
the external service-owned fence or final native-handle boundary needed for a
deployed writer.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import stat
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from .ctp_managed_action_authority import (
    CtpManagedActionAuthorityAdapter,
    CtpManagedActionAuthorityError,
)


_ACCOUNT_REF_RE = re.compile(r"^ctp-account-ref\.v1:([0-9a-f]{64})$", re.ASCII)


class CtpManagedAccountRuntimeCandidateError(RuntimeError):
    """Redacted failure from the unregistered two-mode CTP composition."""


def _reject() -> None:
    raise CtpManagedAccountRuntimeCandidateError(
        "managed CTP account runtime candidate is unavailable"
    )


class CtpManagedActionAuthorityVerifierSlot:
    """One-shot deferred Store verifier used to break the owner construction cycle.

    The worker is built before the durable callback/session owner exists, so it
    receives this slot as its verifier.  The slot rejects until the exact
    Store-backed authority adapter is installed after session creation.  It
    cannot be rebound and permanently rejects after close.

    This is an in-process composition device, not a security boundary against
    other Python code in the process.  Store claim remains the durable local
    single-use boundary; deployment still needs an external atomic fence and
    sole native-handle owner through the final request.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapter: Optional[CtpManagedActionAuthorityAdapter] = None
        self._bound = False
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def bound(self) -> bool:
        with self._lock:
            return self._bound and not self._closed

    def bind(self, adapter: CtpManagedActionAuthorityAdapter) -> None:
        """Install the exact adapter once, after Store owner/session creation."""

        if type(adapter) is not CtpManagedActionAuthorityAdapter:
            _reject()
        with self._lock:
            if self._closed or self._bound:
                _reject()
            self._adapter = adapter
            self._bound = True

    def close(self) -> None:
        """Permanently revoke this slot and drop its adapter reference."""

        with self._lock:
            self._closed = True
            self._adapter = None

    def verify_action(self, command: Any, *, now_ns: int) -> Any:
        """Forward the Store's single claim-time verification without rewrapping."""

        with self._lock:
            adapter = self._adapter
            if self._closed or not self._bound or adapter is None:
                raise CtpManagedActionAuthorityError(
                    "CTP managed action authority verification failed"
                )
            # Keep the slot lock through the verifier call so close cannot race
            # between selecting the verifier and beginning its Store readback.
            # The Store's transaction remains the claim/consume boundary.
            return adapter.verify_action(command, now_ns=now_ns)


def _account_family_digest(execution_scope: Any) -> str:
    """Return the account-ref suffix used only by the supplemental OS lock."""

    account_ref = getattr(execution_scope, "account_ref", None)
    if type(account_ref) is not str:
        _reject()
    match = _ACCOUNT_REF_RE.fullmatch(account_ref)
    if match is None:
        _reject()
    # This lock is only a same-host concurrency aid. The durable family key is
    # computed and issued only by the execution Store.
    return match.group(1)


class CtpManagedAccountRuntimeCandidate:
    """Unregistered account runtime shared by simulation and live candidates.

    The public factory accepts no Store, path, or state-root override. Startup
    derives the existing shared journal path from a freshly revalidated sealed
    config while holding the legacy account flow lock. It then claims the
    Store-owned account family before acquiring the mode-scoped writer lease.
    This candidate is not registered and does not enable either mode; the
    default runtime remains unavailable and an external final-call fence is
    still a deployment prerequisite.
    """

    _FAMILY_OWNER_ACQUIRE_METHOD = "acquire_ctp_account_family_owner"
    _WRITER_LEASE_ACQUIRE_METHOD = "acquire_or_renew_lease"

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        _reject()

    @classmethod
    def create_for_sealed_scope(
        cls,
        *,
        execution_scope: Any,
        scope_resolver: Any,
        permit_source: Any,
        signature_verifier: Any,
        revocation_source: Any,
        fence_source: Any,
        trusted_clock: Any,
        client_factory: Any,
        lifecycle_supervisor: Any,
        native_field_factory: Any,
        callback_verifier: Any,
        trade_fact_verifier: Any,
    ) -> "CtpManagedAccountRuntimeCandidate":
        """Create the shared candidate without a caller-supplied storage path."""

        if cls is not CtpManagedAccountRuntimeCandidate:
            _reject()
        candidate = cls.__new__(cls)
        candidate._initialize(
            execution_scope=execution_scope,
            store=None,
            scope_resolver=scope_resolver,
            permit_source=permit_source,
            signature_verifier=signature_verifier,
            revocation_source=revocation_source,
            fence_source=fence_source,
            trusted_clock=trusted_clock,
            client_factory=client_factory,
            lifecycle_supervisor=lifecycle_supervisor,
            native_field_factory=native_field_factory,
            callback_verifier=callback_verifier,
            trade_fact_verifier=trade_fact_verifier,
            family_lock_root=None,
        )
        return candidate

    @classmethod
    def _from_store_for_test(
        cls,
        *,
        execution_scope: Any,
        store: Any,
        scope_resolver: Any,
        permit_source: Any,
        signature_verifier: Any,
        revocation_source: Any,
        fence_source: Any,
        trusted_clock: Any,
        client_factory: Any,
        lifecycle_supervisor: Any,
        native_field_factory: Any,
        callback_verifier: Any,
        trade_fact_verifier: Any,
        family_lock_root: Optional[Path],
    ) -> "CtpManagedAccountRuntimeCandidate":
        """Private injected-Store construction seam for tests only."""

        if cls is not CtpManagedAccountRuntimeCandidate:
            _reject()
        candidate = cls.__new__(cls)
        candidate._initialize(
            execution_scope=execution_scope,
            store=store,
            scope_resolver=scope_resolver,
            permit_source=permit_source,
            signature_verifier=signature_verifier,
            revocation_source=revocation_source,
            fence_source=fence_source,
            trusted_clock=trusted_clock,
            client_factory=client_factory,
            lifecycle_supervisor=lifecycle_supervisor,
            native_field_factory=native_field_factory,
            callback_verifier=callback_verifier,
            trade_fact_verifier=trade_fact_verifier,
            family_lock_root=family_lock_root,
        )
        return candidate

    def _initialize(
        self,
        *,
        execution_scope: Any,
        store: Any,
        scope_resolver: Any,
        permit_source: Any,
        signature_verifier: Any,
        revocation_source: Any,
        fence_source: Any,
        trusted_clock: Any,
        client_factory: Any,
        lifecycle_supervisor: Any,
        native_field_factory: Any,
        callback_verifier: Any,
        trade_fact_verifier: Any,
        family_lock_root: Path,
    ) -> None:
        try:
            from bt_api_execution.contracts import ExecutionScope
            from bt_api_execution.store import SqliteExecutionStore
            from .ctp_managed_action_scope_resolver import (
                SealedCtpManagedActionScopeResolverV1,
            )
        except Exception:
            _reject()
        try:
            execution_version = importlib.metadata.version("bt_api_execution")
        except Exception:
            _reject()
        if (
            execution_version != "0.2.0"
            or type(execution_scope) is not ExecutionScope
            or (store is not None and type(store) is not SqliteExecutionStore)
            or (family_lock_root is not None and type(family_lock_root) is not Path)
            or (family_lock_root is not None and not family_lock_root.is_absolute())
            or ((store is None) != (family_lock_root is None))
            or execution_scope.provider != "ctp"
            or execution_scope.environment not in {"simnow", "production"}
            or type(scope_resolver) is not SealedCtpManagedActionScopeResolverV1
            or getattr(scope_resolver, "_execution_scope", None) is not execution_scope
        ):
            _reject()
        family_digest = _account_family_digest(execution_scope)
        self._execution_scope = execution_scope
        self._store = store
        self._scope_resolver = scope_resolver
        self._permit_source = permit_source
        self._signature_verifier = signature_verifier
        self._revocation_source = revocation_source
        self._fence_source = fence_source
        self._trusted_clock = trusted_clock
        self._client_factory = client_factory
        self._lifecycle_supervisor = lifecycle_supervisor
        self._native_field_factory = native_field_factory
        self._callback_verifier = callback_verifier
        self._trade_fact_verifier = trade_fact_verifier
        self._family_digest = family_digest
        self._family_lock_root = family_lock_root
        self._store_path = None
        self._owns_store = store is None
        self._state_root = None
        self._legacy_account_fingerprint = None
        self._flow_lease = None
        self._writer_owner_id = "ctp-account-runtime." + uuid.uuid4().hex
        self._writer_lease = None
        self._authority_slot = CtpManagedActionAuthorityVerifierSlot()
        self._family_owner = None
        self._family_owner_attempted = False
        self._session_candidate = None
        self._authority_adapter = None
        self._worker_candidate = None
        self._started = False
        self._closed = False

    @property
    def authority_verifier_slot(self) -> CtpManagedActionAuthorityVerifierSlot:
        """Return the code-created one-shot slot for worker construction/review."""

        return self._authority_slot

    @property
    def family_digest(self) -> str:
        """Opaque stable local family digest, not an account identity or authority."""

        return self._family_digest

    @property
    def session_candidate(self) -> Any:
        return self._session_candidate

    def start(self) -> Any:
        """Acquire family ownership, create callback owner, then bind authority.

        A missing V20 account-store/family-owner method is an early reject. In particular,
        older mode-scoped V17 ownership is not accepted as equivalent, and no
        Store callback owner or client is created on that path.
        """

        if self._started or self._closed or self._session_candidate is not None:
            _reject()
        try:
            self._revalidate_scope_before_start()
        except Exception:
            self._closed = True
            self._authority_slot.close()
            _reject()
        try:
            # The OS lease is only a same-host aid. The first Store mutation is
            # preceded by the old SimNow lease so an older composition cannot
            # race journal-presence checking and Store family acquisition.
            self._acquire_legacy_flow_and_open_store()
            acquire_family = getattr(self._store, self._FAMILY_OWNER_ACQUIRE_METHOD, None)
            acquire_lease = getattr(self._store, self._WRITER_LEASE_ACQUIRE_METHOD, None)
            if not callable(acquire_family) or not callable(acquire_lease):
                # This check precedes callback owner and SDK/native construction.
                # V18's mode-scoped ownership is not equivalent.
                _reject()
            self._family_owner_attempted = True
            family_owner = acquire_family(self._execution_scope)
            self._validate_family_owner(family_owner)
            self._validate_store_identity(
                self._store.read_ctp_account_store_identity(self._execution_scope),
                expected_path=self._store_path,
                expected_owner=family_owner,
            )
            writer_lease = acquire_lease(
                self._execution_scope,
                self._writer_owner_id,
                ttl_ns=300_000_000_000,
                ctp_account_family_owner=family_owner,
            )
            self._validate_writer_lease(writer_lease, family_owner)
            self._store.assert_writer_lease(self._execution_scope, writer_lease)
            self._writer_lease = writer_lease
            worker = self._worker()
            self._worker_candidate = worker
            from .ctp_i9_account_session_candidate import CtpI9AccountSessionCandidate

            session_candidate = CtpI9AccountSessionCandidate(
                scope=self._execution_scope,
                store=self._store,
                writer_lease=writer_lease,
                worker=worker,
                client_factory=self._client_factory,
                lifecycle_supervisor=self._lifecycle_supervisor,
                native_field_factory=self._native_field_factory,
                callback_verifier=self._callback_verifier,
                trade_fact_verifier=self._trade_fact_verifier,
                native_call_admission=self._verify_final_native_call,
            )
            client = session_candidate.start()
            adapter = CtpManagedActionAuthorityAdapter(
                store=self._store,
                scope=self._execution_scope,
                owner_handle=session_candidate.owner_handle,
                writer_lease=writer_lease,
                scope_resolver=self._scope_resolver,
                permit_source=self._permit_source,
                signature_verifier=self._signature_verifier,
                revocation_source=self._revocation_source,
                fence_source=self._fence_source,
                trusted_clock=self._trusted_clock,
            )
            self._authority_slot.bind(adapter)
        except BaseException:
            self._authority_slot.close()
            candidate = locals().get("session_candidate")
            candidate_stopped = candidate is None
            if candidate is not None:
                try:
                    candidate.stop()
                    candidate_stopped = True
                except BaseException:
                    candidate_stopped = False
            if self._owns_store and candidate_stopped and self._store is not None:
                try:
                    self._store.close()
                except BaseException:
                    pass
            # Once the family claim may have committed, retain the local lock.
            # This slice has no family release/handoff proof.
            if not self._family_owner_attempted:
                try:
                    self._flow_lease.release()
                except BaseException:
                    pass
            self._closed = True
            raise CtpManagedAccountRuntimeCandidateError(
                "managed CTP account startup failed closed"
            ) from None
        self._family_owner = family_owner
        self._session_candidate = session_candidate
        self._authority_adapter = adapter
        self._started = True
        return client

    def _worker(self) -> Any:
        try:
            from bt_api_execution.ctp_single_worker_candidate import (
                CtpManagedSingleWorkerCandidate,
            )

            worker = CtpManagedSingleWorkerCandidate(
                self._store,
                self._execution_scope,
                self._writer_lease,
                self._authority_slot,
            )
        except Exception:
            _reject()
        if getattr(worker, "_authority_verifier", None) is not self._authority_slot:
            _reject()
        return worker

    def _revalidate_scope_before_start(self) -> None:
        """Rerun the exact sealed-config and mode admission before client setup."""

        try:
            baseline = self._scope_resolver._baseline
            current = self._scope_resolver._derive_current_scope()
            if (
                type(current) is not type(baseline)
                or current.to_payload() != baseline.to_payload()
                or current.digest != baseline.digest
            ):
                _reject()
        except Exception:
            _reject()

    def _acquire_legacy_flow_and_open_store(self) -> None:
        """Lock the old account path, then open only its exact V20 ledger.

        The old SimNow writer derives its SQLite filename and flow lock from
        `_simnow_legacy_admission_account_digest`. Reusing that exact helper
        prevents a local legacy candidate from running beside this new Store.
        This is a local process/filesystem measure, not an external account
        fence. The new Store uses the same journal filename, so an old journal
        or unknown SQLite file can never be bypassed by a second database.
        """

        try:
            from .ctp_managed_action_scope_resolver import (
                _simnow_legacy_admission_account_digest,
            )
            from .ctp_simulation_execution import CtpAccountFlowLease, _prepare_state_root

            effective = self._scope_resolver._fresh_effective()
            private = effective.config.ctp
            legacy_fingerprint = _simnow_legacy_admission_account_digest(private)
            state_root = _prepare_state_root()
            expected_lock_root = state_root / "flow-locks"
            if self._family_lock_root is not None and self._family_lock_root != expected_lock_root:
                _reject()
            flow_lease = CtpAccountFlowLease(legacy_fingerprint, expected_lock_root)
            self._flow_lease = flow_lease
            flow_lease.acquire()
            journal_dir = state_root / "journals"
            self._prepare_journal_directory(state_root, journal_dir)
            journal_path = journal_dir / (legacy_fingerprint + ".sqlite3")
            self._store_path = journal_path
            if self._store is None:
                self._open_v20_store(journal_path)
            else:
                self._validate_injected_store_path(journal_path)
            self._legacy_account_fingerprint = legacy_fingerprint
        except CtpManagedAccountRuntimeCandidateError:
            raise
        except Exception:
            _reject()

    @staticmethod
    def _prepare_journal_directory(state_root: Path, journal_dir: Path) -> None:
        try:
            root_info = os.lstat(state_root)
            if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
                _reject()
            try:
                os.mkdir(str(journal_dir), 0o700)
            except FileExistsError:
                pass
            directory_info = os.lstat(journal_dir)
            if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode):
                _reject()
            resolved_root = state_root.resolve(strict=True)
            resolved_directory = journal_dir.resolve(strict=True)
            if os.path.normcase(str(resolved_directory.parent)) != os.path.normcase(
                str(resolved_root)
            ):
                _reject()
            if os.name != "nt":
                os.chmod(str(journal_dir), 0o700)
        except CtpManagedAccountRuntimeCandidateError:
            raise
        except Exception:
            _reject()

    def _open_v20_store(self, journal_path: Path) -> None:
        try:
            from bt_api_execution.store import (
                CtpAccountStoreFileInspection,
                SqliteExecutionStore,
            )

            inspection = SqliteExecutionStore.inspect_ctp_account_store_file(
                str(journal_path), self._execution_scope
            )
            if type(inspection) is not CtpAccountStoreFileInspection or inspection.kind not in {
                "MISSING",
                "CTP_EXECUTION_STORE",
            }:
                _reject()
            if inspection.kind == "CTP_EXECUTION_STORE":
                self._validate_store_identity(
                    inspection.identity,
                    expected_path=journal_path,
                    expected_owner=None,
                )
            store = SqliteExecutionStore.open_ctp_account_store(
                str(journal_path), self._execution_scope
            )
            self._store = store
            self._owns_store = True
            identity = store.read_ctp_account_store_identity(self._execution_scope)
            self._validate_store_identity(
                identity,
                expected_path=journal_path,
                expected_owner=None,
            )
            if inspection.kind == "CTP_EXECUTION_STORE":
                before = inspection.identity
                if (
                    identity.journal_incarnation_id != before.journal_incarnation_id
                    or identity.family_key != before.family_key
                    or identity.account_ref != before.account_ref
                    or identity.database_filename != before.database_filename
                    or identity.file_device != before.file_device
                    or identity.file_id != before.file_id
                ):
                    _reject()
        except CtpManagedAccountRuntimeCandidateError:
            raise
        except Exception:
            _reject()

    def _validate_injected_store_path(self, expected_path: Path) -> None:
        """Keep the private test seam on the same fixed account journal path."""

        try:
            identity = self._store.read_ctp_account_store_identity(self._execution_scope)
        except Exception:
            _reject()
        self._validate_store_identity(identity, expected_path=expected_path, expected_owner=None)

    def _validate_store_identity(
        self,
        identity: Any,
        *,
        expected_path: Path,
        expected_owner: Any,
    ) -> None:
        try:
            from bt_api_execution.store import CtpAccountStoreIdentity

            if type(identity) is not CtpAccountStoreIdentity:
                _reject()
            expected_path = expected_path.resolve(strict=True)
            opened_path = Path(identity.database_filename).resolve(strict=True)
            stat_result = expected_path.stat()
            if (
                identity.ledger_kind != "CTP_EXECUTION_V1"
                or identity.account_ref != self._execution_scope.account_ref
                or re.fullmatch(r"ctp-account-family\.v1:[0-9a-f]{64}", identity.family_key) is None
                or re.fullmatch(r"[0-9a-f]{32}", identity.journal_incarnation_id) is None
                or os.path.normcase(str(opened_path)) != os.path.normcase(str(expected_path))
                or type(identity.file_device) is not int
                or type(identity.file_id) is not int
                or identity.file_device != int(stat_result.st_dev)
                or identity.file_id != int(stat_result.st_ino)
            ):
                _reject()
            if expected_owner is None:
                if (
                    identity.family_owner_state is not None
                    or identity.family_owner_intent_id is not None
                ):
                    _reject()
            elif (
                identity.family_owner_state != "ACTIVE"
                or identity.family_owner_intent_id != expected_owner.owner_intent_id
                or identity.family_key != expected_owner.family_key
            ):
                _reject()
        except CtpManagedAccountRuntimeCandidateError:
            raise
        except Exception:
            _reject()

    def _validate_family_owner(self, owner: Any) -> None:
        try:
            from bt_api_execution.store import CtpAccountFamilyOwnerHandle
        except Exception:
            _reject()
        if (
            type(owner) is not CtpAccountFamilyOwnerHandle
            or type(getattr(owner, "family_key", None)) is not str
            or re.fullmatch(r"ctp-account-family\.v1:[0-9a-f]{64}", owner.family_key) is None
            or owner.account_key != self._execution_scope.account_key
            or owner.scope_key != self._execution_scope.key
            or type(owner.owner_intent_id) is not str
            or not owner.owner_intent_id
        ):
            _reject()

    def _validate_writer_lease(self, lease: Any, family_owner: Any) -> None:
        try:
            from bt_api_execution.store import WriterLease
        except Exception:
            _reject()
        if (
            type(lease) is not WriterLease
            or lease.scope_key != self._execution_scope.account_key
            or lease.owner_id != self._writer_owner_id
            or type(lease.fencing_token) is not int
            or lease.fencing_token <= 0
            or type(lease.expires_at_ns) is not int
            or lease.expires_at_ns <= 0
            or getattr(lease, "family_key", None) != family_owner.family_key
            or getattr(lease, "family_owner_intent_id", None) != family_owner.owner_intent_id
        ):
            _reject()

    def stage_and_queue(self, prepared: Any, *, cancel_target: Any = None) -> Any:
        """Delegate staging only after the one-shot authority slot is bound."""

        if not self._started or not self._authority_slot.bound:
            _reject()
        binding, broker_id, user_id = self._read_session_context()
        self._scope_resolver.validate_prepared_action_context(
            prepared,
            self._execution_scope,
            session_binding=binding,
            session_broker_id=broker_id,
            session_user_id=user_id,
        )
        return self._session_candidate.stage_and_queue(prepared, cancel_target=cancel_target)

    def dispatch_next(self) -> Any:
        """Delegate the exact Store claim and managed SDK lease path."""

        if not self._started or not self._authority_slot.bound:
            _reject()
        return self._session_candidate.dispatch_next()

    def apply_next_ingress(self) -> Any:
        if not self._started:
            _reject()
        return self._session_candidate.apply_next_ingress()

    def _read_session_context(self) -> tuple[Any, str, str]:
        candidate = self._session_candidate
        if candidate is None or candidate.owner_handle is None:
            _reject()
        try:
            binding, broker_id, user_id = self._store.read_ctp_callback_session_context_facts(
                candidate.owner_handle
            )
        except Exception:
            _reject()
        if type(broker_id) is not str or type(user_id) is not str:
            _reject()
        return binding, broker_id, user_id

    def _verify_final_native_call(self, owner_handle: Any, binding: Any, verified: Any) -> None:
        """Recheck sealed request/session identity immediately before SDK Req."""

        candidate = self._session_candidate
        if (
            candidate is None
            or owner_handle is not candidate.owner_handle
            or type(binding) is not type(verified)
            or binding is not verified
            or binding.command_id == ""
        ):
            _reject()
        try:
            from bt_api_execution.store import CtpDispatchCommand, CtpManagedNativeCallBindingV2
            from bt_api_execution.contracts import canonical_json

            command = self._store.read_ctp_dispatch_command(
                self._execution_scope, binding.command_id
            )
        except Exception:
            _reject()
        if (
            type(binding) is not CtpManagedNativeCallBindingV2
            or type(command) is not CtpDispatchCommand
            or command.command_id != binding.command_id
            or command.status != "CLAIMED"
            or command.operation != binding.operation
            or canonical_json(dict(command.request_payload)) != binding.request_payload_json
            or command.request_payload_sha256 != binding.request_payload_sha256
            or command.native_request_payload is None
            or canonical_json(dict(command.native_request_payload))
            != binding.native_request_payload_json
            or command.native_request_payload_sha256 != binding.native_request_payload_sha256
            or command.correlation_key is None
            or command.correlation_key.native_request_id != binding.native_request_id
            or command.correlation_key.native_action_ref != binding.native_action_ref
        ):
            _reject()
        session_binding, broker_id, user_id = self._read_session_context()
        self._scope_resolver.validate_action_context(
            command,
            self._execution_scope,
            session_binding=session_binding,
            session_broker_id=broker_id,
            session_user_id=user_id,
        )
        adapter = self._authority_adapter
        if type(adapter) is not CtpManagedActionAuthorityAdapter:
            _reject()
        try:
            trusted_now_ns = self._trusted_clock.now_ns()
            adapter.verify_claimed_action(
                command,
                binding,
                now_ns=trusted_now_ns,
            )
        except CtpManagedActionAuthorityError:
            raise
        except Exception:
            _reject()

    def close(self) -> None:
        """Close permanently; failed durable fencing retains the local lease."""

        if self._closed:
            return
        self._authority_slot.close()
        candidate = self._session_candidate
        if candidate is None:
            self._closed = True
            if self._flow_lease is not None and not self._family_owner_attempted:
                self._flow_lease.release()
            return
        try:
            candidate.stop()
            if self._owns_store and self._store is not None:
                self._store.close()
        except BaseException:
            self._closed = True
            raise CtpManagedAccountRuntimeCandidateError(
                "managed CTP account close failed closed"
            ) from None
        self._closed = True
        self._started = False
        # No family-owner release or handoff exists in V20. The permanent Store
        # owner continues to block both modes after this local lock is released.
        if self._flow_lease is not None:
            self._flow_lease.release()


__all__ = [
    "CtpManagedAccountRuntimeCandidate",
    "CtpManagedAccountRuntimeCandidateError",
    "CtpManagedActionAuthorityVerifierSlot",
]
