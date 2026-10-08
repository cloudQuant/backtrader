"""Root-held three-phase Binance TH01 account-window snapshot candidate.

The callable is deliberately unregistered.  It collects source-bound account
snapshots through the frozen R1 reader and the additive full-snapshot adapter;
it does not run the generic TH01 case or create a certification PASS.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import _GeneratorContextManager
from dataclasses import dataclass, field
from dataclasses import replace
from decimal import Decimal
import ast
import contextlib
import hashlib
from importlib.machinery import ModuleSpec
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import re
import sys
import time
from types import CodeType, FunctionType, ModuleType
from typing import Any, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DRIVER_RELATIVE = "scripts/iteration41_binance_th01_account_window_candidate_r2.py"
OWNER_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/"
    "th01_root_protected_owner_r1.py"
)
CANDIDATE_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/"
    "th01_account_window_candidate_r2.py"
)
ROOT_READONLY_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/" "th01_root_readonly.py"
)
CASES_RELATIVE = "examples/000_live_certification/binance_penetration/_certification/cases.py"
RUNNER_RELATIVE = "examples/000_live_certification/binance_penetration/_certification/runner.py"
MODELS_RELATIVE = "examples/000_live_certification/binance_penetration/_certification/models.py"
ADAPTER_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/"
    "th01_account_full_snapshot_r1.py"
)
FORCE_EXTENSION_R1_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/"
    "th01_force_orders_transport_r1.py"
)
FORCE_EXTENSION_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/"
    "th01_force_orders_transport_r2.py"
)
WRAPPER_RELATIVE = "scripts/iteration41_binance_th01_root_account_window_call_r1.py"
CERTIFICATION_PACKAGE = "examples.000_live_certification.binance_penetration._certification"
# The current force-orders successor is under independent review.  Keep the
# runtime installer unreachable until a reviewed successor pin is bound here.
FORCE_EXTENSION_INTEGRATION_ENABLED = False
R3_BOOTSTRAP_RELATIVE = "backtrader_runtime/certification_roundtrip_r3_bootstrap.py"
CUV2_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/"
    "evidence/iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)

DRIVER_SHA256 = "698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6"
DRIVER_SIZE = 11_391
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
OWNER_SIZE = 92_566
CANDIDATE_SHA256 = "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63"
CANDIDATE_SIZE = 62_664
ROOT_READONLY_SHA256 = "2b5e055aff27a07c3d28b6499a45ebf1c7546e7a8f0710ea60feb68d2561ca0f"
ROOT_READONLY_SIZE = 51_587
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_SIZE = 2_344
R3_CLOSURE_SHA256 = "d4ece913aee90282f9bab4f053f778b128936619b230dc70d6018e93d21e21d2"
R3_CHANGED_MEMBER_SHA256 = {
    "case_models": "8dd1ca6cbf5cf26a07449f3cebc5dfb488ec74cf4cb5afa97894b31a49f2f011",
    "certification_binance": "abdc7fcb23a999dd25cb981d74dd28415df85d77cbe17da240e0ff1c7391346e",
    "certification_direct": "15721a6d7ec8ae5eb00a66b766db3b48d0dfd427680785c527e6c622aca2feb4",
}
CASES_SHA256 = "0e0d7618846975db37551222f3c902ceee2b975f4be0b8236dcf021508492762"
CASES_SIZE = 5_569
MODELS_SHA256 = "8dd1ca6cbf5cf26a07449f3cebc5dfb488ec74cf4cb5afa97894b31a49f2f011"
MODELS_SIZE = 6_802
RUNNER_SHA256 = "987dde04e5983530b04fe6bfe88909c9dcd5b3255a86c09e9a024d35ae4f0623"
RUNNER_SIZE = 84_465
PYTHON_EXE = r"C:\anaconda3\python.exe"
PYTHON_EXE_SIZE = 92_160
PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PYTHON_DLL = r"C:\anaconda3\python311.dll"
PYTHON_DLL_SIZE = 5_991_424
PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"

ADDITIVE_SOURCE_PINS: Mapping[str, tuple[str, int]] = {
    CASES_RELATIVE: (CASES_SHA256, CASES_SIZE),
    MODELS_RELATIVE: (MODELS_SHA256, MODELS_SIZE),
    RUNNER_RELATIVE: (RUNNER_SHA256, RUNNER_SIZE),
    ADAPTER_RELATIVE: (
        "049ef44814d2131b53a5b32dfdd5519b5c4607cb3db9922d330c1282c01d93c5",
        60_349,
    ),
    FORCE_EXTENSION_R1_RELATIVE: (
        "aaa2e10d2c37ea4cfbb69d18d860db12569b4043b7b45c70a0bbf65f22bd7f6e",
        35_986,
    ),
    FORCE_EXTENSION_RELATIVE: (
        "a00736367d4eec41b8603c13e8f282c764a223c0c40fffcd1af24ccbae8de102",
        47_299,
    ),
}

MAX_REQUESTS = 64
MAX_ROWS = 5_000
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_MS = 120_000
MAX_HISTORY_MS = 72 * 60 * 60 * 1000
PHASES = ("baseline", "before_cleanup", "after_cleanup")
CURRENT_METHODS = (
    ("account_configuration", "account_configuration"),
    ("account_v2", "account_v2"),
    ("standard_open_orders", "open_orders"),
    ("algo_open_orders", "open_algo_orders"),
)
_SAFE_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_ACTIVE_SESSIONS: list[Any] = []


class RootAccountWindowCallBlocked(ValueError):
    """Safe, non-sensitive reason for a source or collection block."""

    def __init__(self, code: str):
        self.code = (
            code if type(code) is str and _SAFE_CODE.fullmatch(code) else "account_window_blocked"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True, repr=False)
class RootForceOrdersAttemptTicketV1:
    """One Root-reserved force-orders interval passed to the fixed extension."""

    ledger: Any = field(repr=False, compare=False)
    auth: Any = field(repr=False, compare=False)
    sequence: int
    start_ms: int
    end_ms: int
    nonce: str

    def __repr__(self) -> str:
        return "RootForceOrdersAttemptTicketV1(<Root-held one-use reservation>)"


@dataclass(frozen=True, slots=True, repr=False)
class _RootForceOrdersAttemptEventV1:
    ticket: RootForceOrdersAttemptTicketV1 = field(repr=False, compare=False)
    auth: Any = field(repr=False, compare=False)
    sequence: int
    start_ms: int
    end_ms: int
    nonce: str
    phase: str
    state: str
    outcome_code: str | None


class RootForceOrdersAttemptLedgerV1:
    """Root-owned append-only force-orders attempt history for one auth."""

    __slots__ = ("_auth", "_events", "_next_sequence", "_phase", "_phase_index")

    _OUTCOMES = frozenset({"page_received", "blocked", "transport_error", "interrupted"})
    _STATES = frozenset({"reserved", "dispatching", "terminal"})

    def __init__(self, auth: Any):
        if type(getattr(auth, "history_start_ms", None)) is not int:
            _block("force_orders_attempt_auth_invalid")
        self._auth = auth
        self._events: tuple[_RootForceOrdersAttemptEventV1, ...] = ()
        self._next_sequence = 0
        self._phase: str | None = None
        self._phase_index = 0

    def __repr__(self) -> str:
        return "RootForceOrdersAttemptLedgerV1(<Root-held append-only state>)"

    def _row(self, event: _RootForceOrdersAttemptEventV1) -> tuple[Any, ...]:
        return (
            event.ticket,
            event.auth,
            event.sequence,
            event.start_ms,
            event.end_ms,
            event.nonce,
            event.phase,
            event.state,
            event.outcome_code,
        )

    def _valid_event(self, event: Any) -> bool:
        if type(event) is not _RootForceOrdersAttemptEventV1:
            return False
        ticket = event.ticket
        return (
            type(ticket) is RootForceOrdersAttemptTicketV1
            and ticket.ledger is self
            and ticket.auth is self._auth
            and event.auth is self._auth
            and ticket.sequence == event.sequence
            and ticket.start_ms == event.start_ms
            and ticket.end_ms == event.end_ms
            and ticket.nonce == event.nonce
            and type(event.phase) is str
            and event.phase in PHASES[1:]
            and type(event.state) is str
            and event.state in self._STATES
            and (
                event.state == "terminal"
                and type(event.outcome_code) is str
                and event.outcome_code in self._OUTCOMES
                or event.state != "terminal"
                and event.outcome_code is None
            )
        )

    def snapshot(self) -> tuple[Any, ...]:
        if type(self._events) is not tuple or any(
            not self._valid_event(event) for event in self._events
        ):
            _block("force_orders_attempt_ledger_invalid")
        return (
            self,
            self._auth,
            self._phase,
            tuple(self._row(event) for event in self._events),
        )

    def _matches_snapshot(self, snapshot: Any, *, prefix: bool) -> bool:
        expected_phase_index = (
            0
            if self._phase is None
            else PHASES.index(self._phase)
            if type(self._phase) is str and self._phase in PHASES
            else -1
        )
        reserved_count = (
            sum(event.state == "reserved" for event in self._events)
            if type(self._events) is tuple
            and all(type(event) is _RootForceOrdersAttemptEventV1 for event in self._events)
            else -1
        )
        if (
            type(snapshot) is not tuple
            or len(snapshot) != 4
            or snapshot[0] is not self
            or snapshot[1] is not self._auth
            or snapshot[2] != self._phase
            or (snapshot[2] is not None and snapshot[2] not in PHASES[1:])
            or type(snapshot[3]) is not tuple
            or type(self._events) is not tuple
            or type(self._phase_index) is not int
            or self._phase_index != expected_phase_index
            or type(self._next_sequence) is not int
            or self._next_sequence != reserved_count
            or len(snapshot[3]) > len(self._events)
            or not prefix
            and len(snapshot[3]) != len(self._events)
        ):
            return False
        for index, held_row in enumerate(snapshot[3]):
            if (
                type(held_row) is not tuple
                or len(held_row) != 9
                or not self._valid_event(self._events[index])
            ):
                return False
            current_row = self._row(self._events[index])
            if (
                current_row[0] is not held_row[0]
                or current_row[1] is not held_row[1]
                or current_row[2:] != held_row[2:]
            ):
                return False
        return True

    def verify_snapshot(self, snapshot: tuple[Any, ...]) -> bool:
        """Check the Root-held snapshot against every event, including values."""
        return self._matches_snapshot(snapshot, prefix=False)

    def verify_transition(
        self,
        snapshot: tuple[Any, ...],
        ticket: RootForceOrdersAttemptTicketV1,
        expected_state: str,
        outcome_code: str | None = None,
    ) -> bool:
        """Check one exact append-only transition after a held prefix."""
        if (
            not self._matches_snapshot(snapshot, prefix=True)
            or any(not self._valid_event(event) for event in self._events)
            or type(ticket) is not RootForceOrdersAttemptTicketV1
            or ticket.ledger is not self
            or ticket.auth is not self._auth
            or expected_state not in self._STATES
        ):
            return False
        suffix = self._events[len(snapshot[3]) :]
        ticket_events = tuple(event for event in self._events if event.ticket is ticket)
        if expected_state == "reserved":
            return (
                len(suffix) == 1
                and len(ticket_events) == 1
                and suffix[0].ticket is ticket
                and suffix[0].phase == self._phase
                and suffix[0].state == "reserved"
                and suffix[0].outcome_code is None
                and outcome_code is None
            )
        if expected_state == "dispatching":
            return (
                len(suffix) == 1
                and len(ticket_events) >= 2
                and suffix[0].ticket is ticket
                and suffix[0].phase == self._phase
                and suffix[0].state == "dispatching"
                and suffix[0].outcome_code is None
                and outcome_code is None
            )
        if outcome_code not in self._OUTCOMES or not ticket_events:
            return False
        if len(suffix) not in (2, 3):
            return False
        first = suffix[0]
        terminal = suffix[-1]
        if first.ticket is not ticket or first.phase != self._phase or first.state != "reserved":
            return False
        if len(suffix) == 3 and (
            suffix[1].ticket is not ticket
            or suffix[1].phase != self._phase
            or suffix[1].state != "dispatching"
        ):
            return False
        return (
            terminal.ticket is ticket
            and terminal.state == "terminal"
            and terminal.outcome_code == outcome_code
            and terminal.auth is self._auth
        )

    def _latest_state(self, ticket: RootForceOrdersAttemptTicketV1) -> str | None:
        for event in reversed(self._events):
            if event.ticket is ticket:
                return event.state
        return None

    def set_phase(self, phase: str) -> tuple[Any, ...]:
        """Advance the Root-owned history phase after prior attempts terminate."""
        expected_index = self._phase_index + 1
        if (
            type(phase) is not str
            or expected_index >= len(PHASES)
            or phase != PHASES[expected_index]
            or not self._matches_snapshot(self.snapshot(), prefix=False)
            or any(self._latest_state(event.ticket) != "terminal" for event in self._events)
        ):
            _block("force_orders_attempt_phase_invalid")
        self._phase = phase
        self._phase_index = expected_index
        return self.snapshot()

    def verify(
        self,
        ticket: RootForceOrdersAttemptTicketV1,
        auth: Any,
        start_ms: int,
        end_ms: int,
        *,
        expected_state: str,
    ) -> bool:
        return (
            type(ticket) is RootForceOrdersAttemptTicketV1
            and self._matches_snapshot(self.snapshot(), prefix=False)
            and auth is self._auth
            and ticket.ledger is self
            and ticket.auth is auth
            and ticket.start_ms == start_ms
            and ticket.end_ms == end_ms
            and type(start_ms) is int
            and type(end_ms) is int
            and self._latest_state(ticket) == expected_state
            and expected_state in self._STATES
        )

    def reserve(self, auth: Any, start_ms: int, end_ms: int) -> RootForceOrdersAttemptTicketV1:
        if (
            auth is not self._auth
            or type(start_ms) is not int
            or type(end_ms) is not int
            or start_ms < auth.history_start_ms
            or end_ms <= start_ms
            or self._phase not in PHASES[1:]
            or not self._matches_snapshot(self.snapshot(), prefix=False)
        ):
            _block("force_orders_attempt_scope_invalid")
        if any(
            event.auth is auth
            and event.phase == self._phase
            and event.start_ms == start_ms
            and event.end_ms == end_ms
            for event in self._events
        ):
            _block("force_orders_attempt_replay")
        sequence = self._next_sequence
        ticket = RootForceOrdersAttemptTicketV1(
            ledger=self,
            auth=auth,
            sequence=sequence,
            start_ms=start_ms,
            end_ms=end_ms,
            nonce=uuid4().hex,
        )
        event = _RootForceOrdersAttemptEventV1(
            ticket,
            auth,
            sequence,
            start_ms,
            end_ms,
            ticket.nonce,
            self._phase,
            "reserved",
            None,
        )
        self._events = (*self._events, event)
        self._next_sequence += 1
        return ticket

    def consume(
        self,
        ticket: RootForceOrdersAttemptTicketV1,
        auth: Any,
        start_ms: int,
        end_ms: int,
    ) -> bool:
        if not self.verify(ticket, auth, start_ms, end_ms, expected_state="reserved"):
            return False
        event = _RootForceOrdersAttemptEventV1(
            ticket,
            auth,
            ticket.sequence,
            start_ms,
            end_ms,
            ticket.nonce,
            self._phase,
            "dispatching",
            None,
        )
        self._events = (*self._events, event)
        return True

    def finish(self, ticket: RootForceOrdersAttemptTicketV1, outcome_code: str) -> None:
        if (
            not self._matches_snapshot(self.snapshot(), prefix=False)
            or type(outcome_code) is not str
            or outcome_code not in self._OUTCOMES
            or type(ticket) is not RootForceOrdersAttemptTicketV1
            or ticket.ledger is not self
            or ticket.auth is not self._auth
            or self._latest_state(ticket) not in {"reserved", "dispatching"}
        ):
            _block("force_orders_attempt_finish_invalid")
        event = _RootForceOrdersAttemptEventV1(
            ticket,
            self._auth,
            ticket.sequence,
            ticket.start_ms,
            ticket.end_ms,
            ticket.nonce,
            self._phase,
            "terminal",
            outcome_code,
        )
        self._events = (*self._events, event)


def _block(code: str) -> None:
    raise RootAccountWindowCallBlocked(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixed_public_pin_rows() -> dict[str, tuple[str, int]]:
    rows = {
        DRIVER_RELATIVE: (DRIVER_SHA256, DRIVER_SIZE),
        OWNER_RELATIVE: (OWNER_SHA256, OWNER_SIZE),
        CANDIDATE_RELATIVE: (CANDIDATE_SHA256, CANDIDATE_SIZE),
        ROOT_READONLY_RELATIVE: (ROOT_READONLY_SHA256, ROOT_READONLY_SIZE),
        CUV2_RELATIVE: (CUV2_SHA256, CUV2_SIZE),
    }
    # Root supplies the external expected wrapper pin.  The public map stores
    # the exact same bytes that produced this running function.
    wrapper_raw = _read_public_source(ROOT, WRAPPER_RELATIVE)
    rows[WRAPPER_RELATIVE] = (_sha(wrapper_raw), len(wrapper_raw))
    return rows


def _read_public_source(root: Path, relative: str, maximum: int = 8 * 1024 * 1024) -> bytes:
    try:
        path = root / relative
        path.relative_to(root)
        info = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not 0 < info.st_size <= maximum
        ):
            _block("public_source_shape_invalid")
        raw = path.read_bytes()
        if len(raw) != info.st_size or len(raw) > maximum:
            _block("public_source_changed_during_read")
        return raw
    except RootAccountWindowCallBlocked:
        raise
    except Exception:
        _block("public_source_unavailable")


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except Exception:
                _block("r3_source_manifest_invalid")
    _block("r3_source_manifest_missing")


def _r3_source_rows(
    root: Path, *, use_held: Mapping[str, bytes] | None = None
) -> dict[str, tuple[str, int]]:
    bootstrap_raw = (
        use_held.get(str(root / R3_BOOTSTRAP_RELATIVE))
        if use_held is not None
        else _read_public_source(root, R3_BOOTSTRAP_RELATIVE)
    )
    if (
        type(bootstrap_raw) is not bytes
        or _sha(bootstrap_raw) != "6ecf2060558753d3a9f5b4fe9d2e4329659e9b9c00879d539ff4408c9778b4da"
    ):
        _block("r3_bootstrap_pin_mismatch")
    try:
        tree = ast.parse(bootstrap_raw, filename=str(root / R3_BOOTSTRAP_RELATIVE))
        names = _literal_assignment(tree, "NAMES")
        case_paths = _literal_assignment(tree, "CASE_SOURCE_PATHS")
    except RootAccountWindowCallBlocked:
        raise
    except Exception:
        _block("r3_source_manifest_invalid")
    if type(names) is not tuple or len(names) != 39 or type(case_paths) is not dict:
        _block("r3_source_manifest_invalid")
    rows: dict[str, tuple[str, int]] = {}
    hashes: dict[str, str] = {}
    for name in names:
        if type(name) is not str or not re.fullmatch(r"[a-z0-9_]+", name):
            _block("r3_source_manifest_invalid")
        relative = case_paths.get(name, f"backtrader_runtime/{name}.py")
        if type(relative) is not str:
            _block("r3_source_manifest_invalid")
        if relative not in rows:
            if use_held is None:
                raw = _read_public_source(root, relative)
            else:
                raw = use_held.get(str(root / relative))
                if type(raw) is not bytes:
                    _block("r3_held_source_missing")
            rows[relative] = (_sha(raw), len(raw))
        hashes[name] = rows[relative][0]
    digest = _sha(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("ascii"))
    if digest != R3_CLOSURE_SHA256:
        _block("r3_source_closure_mismatch")
    for name, expected in R3_CHANGED_MEMBER_SHA256.items():
        if hashes.get(name) != expected:
            _block("r3_source_member_mismatch")
    return rows


def required_public_source_pins(root: Path = ROOT) -> dict[str, str]:
    """Return repo-relative source pins for the Root's CUv2 public map.

    The 39-member R3 closure is bound by its fixed digest. The remaining
    additive files use exact frozen byte pins and are rejected until both
    source owners have supplied their final reviewed hashes.
    """
    checked_root = Path(root).resolve()
    if checked_root != ROOT.resolve():
        _block("source_root_mismatch")
    if (
        not ADDITIVE_SOURCE_PINS
        or ADAPTER_RELATIVE not in ADDITIVE_SOURCE_PINS
        or FORCE_EXTENSION_RELATIVE not in ADDITIVE_SOURCE_PINS
    ):
        _block("additive_source_not_frozen")
    rows = _fixed_public_pin_rows()
    rows.update(_r3_source_rows(checked_root))
    for relative in (CASES_RELATIVE, RUNNER_RELATIVE, MODELS_RELATIVE):
        if relative not in rows:
            raw = _read_public_source(checked_root, relative)
            rows[relative] = (_sha(raw), len(raw))
    rows.update(ADDITIVE_SOURCE_PINS)
    return {relative: digest for relative, (digest, _size) in rows.items()}


def required_software_source_pins(root: Path = ROOT) -> dict[str, str]:
    """Return the fixed Python runtime and CUv2 source pins for Root custody."""
    cu_path = str(Path(root).resolve() / CUV2_RELATIVE)
    return {
        cu_path: CUV2_SHA256,
        PYTHON_EXE: PYTHON_EXE_SHA256,
        PYTHON_DLL: PYTHON_DLL_SHA256,
    }


def _all_expected_pins(root: Path) -> dict[str, str]:
    public = required_public_source_pins(root)
    software = required_software_source_pins(root)
    combined = {str(root / relative): digest for relative, digest in public.items()}
    for path, digest in software.items():
        combined[path] = digest
    return combined


def _code_fingerprint(code: CodeType) -> tuple[Any, ...]:
    def constant(value: Any) -> Any:
        if type(value) is CodeType:
            return ("code", _code_fingerprint(value))
        if type(value) is tuple:
            return ("tuple", tuple(constant(item) for item in value))
        if type(value) is frozenset:
            return ("frozenset", tuple(sorted((constant(item) for item in value), key=repr)))
        return (type(value).__name__, value)

    return (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        tuple(constant(value) for value in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_firstlineno,
        code.co_qualname,
    )


def _code_objects(code: CodeType):
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield value
            yield from _code_objects(value)


def _expected_code_by_qualname(raw: bytes, path: Path) -> dict[str, tuple[Any, ...]]:
    try:
        code = compile(raw, str(path), "exec", dont_inherit=True)
    except Exception:
        _block("source_compile_invalid")
    return {item.co_qualname: _code_fingerprint(item) for item in _code_objects(code)}


def _verify_loaded_source_module(
    module: ModuleType,
    *,
    path: Path,
    raw: bytes,
    expected_sha256: str,
) -> None:
    if (
        type(module) is not ModuleType
        or type(getattr(module, "__name__", None)) is not str
        or sys.modules.get(module.__name__) is not module
        or Path(getattr(module, "__file__", "")).resolve() != path.resolve()
        or getattr(module, "__th01_held_source_sha256__", None) != expected_sha256
        or _sha(raw) != expected_sha256
    ):
        _block("loaded_source_module_binding_invalid")
    expected = _expected_code_by_qualname(raw, path)
    for name, value in module.__dict__.items():
        if type(value) is FunctionType and value.__module__ == module.__name__:
            if value.__globals__ is module.__dict__ and _code_fingerprint(
                value.__code__
            ) == expected.get(value.__qualname__):
                continue
            wrapped = getattr(value, "__wrapped__", None)
            if (
                type(wrapped) is not FunctionType
                or wrapped.__globals__ is not module.__dict__
                or wrapped.__qualname__ != value.__qualname__
                or _code_fingerprint(wrapped.__code__) != expected.get(value.__qualname__)
            ):
                _block("loaded_source_function_binding_invalid")
            try:
                expected_wrapper = contextlib.contextmanager(wrapped)
            except Exception:
                _block("loaded_source_function_binding_invalid")
            actual_cells = value.__closure__ or ()
            expected_cells = expected_wrapper.__closure__ or ()
            if (
                value.__code__ is not expected_wrapper.__code__
                or value.__globals__ is not expected_wrapper.__globals__
                or value.__defaults__ != expected_wrapper.__defaults__
                or value.__kwdefaults__ != expected_wrapper.__kwdefaults__
                or value.__wrapped__ is not wrapped
                or len(actual_cells) != len(expected_cells)
                or any(
                    left.cell_contents is not right.cell_contents
                    for left, right in zip(actual_cells, expected_cells)
                )
            ):
                _block("loaded_source_function_binding_invalid")
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for member_name, member in vars(value).items():
                if isinstance(member, (classmethod, staticmethod)):
                    member = member.__func__
                code = getattr(member, "__code__", None)
                if (
                    code is not None
                    and getattr(member, "__module__", None) == module.__name__
                    and code.co_qualname in expected
                ):
                    if getattr(
                        member, "__globals__", None
                    ) is not module.__dict__ or _code_fingerprint(code) != expected.get(
                        code.co_qualname
                    ):
                        _block("loaded_source_method_binding_invalid")


def _closure_value_shape(value: Any, seen: frozenset[int]) -> Any:
    if type(value) is FunctionType:
        return ("function", _function_binding_shape(value, seen))
    value_type = type(value)
    if value_type in (tuple, frozenset, list, set):
        identity = id(value)
        if identity in seen:
            return (value_type.__name__, identity, "cycle")
        next_seen = seen | {identity}
        members = tuple(
            part
            for part in (
                _closure_value_shape(item, next_seen)
                for item in (value if value_type is not frozenset else sorted(value, key=id))
            )
            if part is not None
        )
        return (value_type.__name__, identity, members)
    if value_type is dict:
        identity = id(value)
        if identity in seen:
            return ("dict", identity, "cycle")
        next_seen = seen | {identity}
        nested = []
        for key, item in value.items():
            key_shape = _closure_value_shape(key, next_seen)
            item_shape = _closure_value_shape(item, next_seen)
            if key_shape is not None or item_shape is not None:
                nested.append((key_shape, item_shape))
        return ("dict", identity, tuple(nested))
    return ("identity", value_type.__module__, value_type.__qualname__, id(value))


def _function_binding_shape(
    function: FunctionType, seen: frozenset[int] = frozenset()
) -> tuple[Any, ...]:
    if type(function) is not FunctionType:
        return ("not_function", type(function).__qualname__, id(function))
    identity = id(function)
    if identity in seen:
        return ("function_cycle", identity)
    next_seen = seen | {identity}
    closure = function.__closure__ or ()
    closure_shape = []
    for cell in closure:
        try:
            content = cell.cell_contents
        except ValueError:
            content = None
        closure_shape.append((id(cell), _closure_value_shape(content, next_seen)))
    return (
        id(function),
        id(function.__code__),
        id(function.__globals__),
        id(function.__closure__),
        tuple(closure_shape),
        id(function.__defaults__),
        id(function.__kwdefaults__),
        id(function.__annotations__),
        _binding_shape(function.__defaults__),
        _binding_shape(function.__kwdefaults__),
        _binding_shape(function.__annotations__),
    )


def _binding_shape(value: Any, seen: frozenset[int] = frozenset()) -> Any:
    value_type = type(value)
    if value is None or value_type in (bool, int, float, str, bytes):
        return (value_type.__name__, value)
    if value_type is tuple:
        return ("tuple", tuple(_binding_shape(item, seen) for item in value))
    if value_type is frozenset:
        parts = tuple(sorted((_binding_shape(item, seen) for item in value), key=repr))
        return ("frozenset", parts)
    identity = id(value)
    if identity in seen:
        return ("cycle", identity)
    next_seen = seen | {identity}
    if value_type is dict:
        return (
            "dict",
            tuple(
                sorted(
                    (
                        (_binding_shape(key, next_seen), _binding_shape(item, next_seen))
                        for key, item in value.items()
                    ),
                    key=repr,
                )
            ),
        )
    if value_type is list:
        return ("list_identity", identity)
    if value_type is set:
        return ("set_identity", identity)
    if value_type is FunctionType:
        return ("function", _function_binding_shape(value, seen))
    if isinstance(value, type):
        members = tuple(
            sorted(
                (
                    name,
                    _binding_shape(member, next_seen),
                )
                for name, member in vars(value).items()
                if name not in {"__dict__", "__weakref__"}
            )
        )
        return ("type", identity, members)
    return ("identity", value_type.__module__, value_type.__qualname__, identity)


def _module_binding_snapshot(
    module: ModuleType, *, mutable_globals: frozenset[str]
) -> tuple[Any, ...]:
    if type(module) is not ModuleType:
        _block("source_module_type_invalid")
    rows = []
    for name, value in module.__dict__.items():
        if name.startswith("__"):
            continue
        shape = (
            ("mutable_identity", id(value)) if name in mutable_globals else _binding_shape(value)
        )
        rows.append((name, shape))
    return tuple(sorted(rows, key=lambda item: item[0]))


def _capture_source_binding_snapshots(
    *,
    wrapper: ModuleType,
    owner: ModuleType,
    candidate: ModuleType,
    source_modules: Mapping[str, ModuleType],
    mutable_global_overrides: Mapping[str, frozenset[str]] | None = None,
) -> tuple[tuple[ModuleType, frozenset[str], tuple[Any, ...]], ...]:
    mutable_by_name = {
        wrapper.__name__: frozenset({"_ACTIVE_SESSIONS"}),
        "__main__": frozenset(
            {
                "_ACTIVE_ROOT_ACCOUNT_AUTH",
                "_ACTIVE_ROOT_FIXED_WORKERS",
                "_ACTIVE_ROOT_PROBE_RECEIPTS",
            }
        ),
    }
    if mutable_global_overrides is not None:
        mutable_by_name.update(mutable_global_overrides)
    modules = [wrapper, owner, candidate, *source_modules.values()]
    snapshots = []
    seen: set[int] = set()
    for module in modules:
        if id(module) in seen:
            continue
        seen.add(id(module))
        mutable = mutable_by_name.get(module.__name__, frozenset())
        snapshots.append(
            (module, mutable, _module_binding_snapshot(module, mutable_globals=mutable))
        )
    return tuple(snapshots)


def _verify_source_binding_snapshots(
    snapshots: tuple[tuple[ModuleType, frozenset[str], tuple[Any, ...]], ...]
) -> None:
    for module, mutable, snapshot in snapshots:
        if sys.modules.get(module.__name__) is not module:
            _block("source_module_global_binding_changed")
        if _module_binding_snapshot(module, mutable_globals=mutable) != snapshot:
            _block("source_module_global_binding_changed")


def _pre_action_mutable_globals(adapter: ModuleType) -> Mapping[str, frozenset[str]]:
    """Allow only the adapter's expected one-time action registry insertion."""
    return {adapter.__name__: frozenset({"_ISSUED_ACTIONS"})}


def _verify_wrapper_namespace(root: Path, held: Mapping[str, bytes]) -> ModuleType:
    wrapper_path = root / WRAPPER_RELATIVE
    module = sys.modules.get(__name__)
    raw = held.get(str(wrapper_path))
    if type(raw) is not bytes:
        _block("wrapper_held_source_missing")
    _verify_loaded_source_module(
        module,
        path=wrapper_path,
        raw=raw,
        expected_sha256=_sha(raw),
    )
    return module


def _verify_cuv2_scope(
    cuv2_module: ModuleType,
    lease: Any,
    yielded: Any,
    public_pins: Mapping[str, str],
    software_pins: Mapping[str, str],
    root: Path,
) -> dict[str, bytes]:
    cu_path = root / CUV2_RELATIVE
    expected_keys = _all_expected_pins(root)
    expected_public = required_public_source_pins(root)
    expected_software = required_software_source_pins(root)
    if (
        type(cuv2_module) is not ModuleType
        or Path(getattr(cuv2_module, "__file__", "")).resolve() != cu_path.resolve()
        or type(lease) is not _GeneratorContextManager
        or type(yielded) is not tuple
        or len(yielded) != 3
        or getattr(lease, "func", None)
        is not getattr(cuv2_module.held_public_sources, "__wrapped__", None)
    ):
        _block("cuv2_scope_binding_invalid")
    generator = getattr(lease, "gen", None)
    frame = getattr(generator, "gi_frame", None)
    if (
        frame is None
        or frame.f_globals is not cuv2_module.__dict__
        or frame.f_locals.get("pins") is not public_pins
        or frame.f_locals.get("software_pins") is not software_pins
        or frame.f_locals.get("raw_bytes") is not yielded[2]
        or frame.f_locals.get("private") is not yielded[0]
        or frame.f_locals.get("cli") is not yielded[1]
        or type(yielded[2]) is not dict
        or set(yielded[2]) != set(expected_keys)
        or dict(public_pins) != expected_public
        or dict(software_pins) != expected_software
    ):
        _block("cuv2_scope_state_invalid")
    raw_map = yielded[2]
    for path, expected_sha in expected_keys.items():
        raw = raw_map.get(path)
        if type(raw) is not bytes or _sha(raw) != expected_sha:
            _block("held_source_pin_mismatch")
    # Bind the generator code to the source bytes, not to filename/name markers.
    cu_raw = raw_map.get(str(cu_path))
    if type(cu_raw) is not bytes or _sha(cu_raw) != CUV2_SHA256:
        _block("cuv2_source_pin_mismatch")
    try:
        module_code = compile(cu_raw, str(cu_path), "exec", dont_inherit=True)
        expected_functions = {
            item.co_name: item
            for item in _code_objects(module_code)
            if item.co_name in {"held_public_sources", "load", "sha", "check"}
        }
        expected_function_code = expected_functions["held_public_sources"]
    except Exception:
        _block("cuv2_source_shape_invalid")
    if _code_fingerprint(generator.gi_code) != _code_fingerprint(expected_function_code):
        _block("cuv2_generator_code_mismatch")
    function = getattr(cuv2_module, "held_public_sources", None)
    wrapped = getattr(function, "__wrapped__", None)
    if (
        not callable(function)
        or not callable(wrapped)
        or getattr(wrapped, "__code__", None) is None
        or getattr(function, "__globals__", None) is not cuv2_module.__dict__
        or wrapped is not lease.func
        or root != cuv2_module.ROOT
        or cuv2_module.PRIVATE != "backtrader_runtime/certification_roundtrip_private.py"
        or cuv2_module.CLI != "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
        or cuv2_module.ExitStack is not contextlib.ExitStack
        or cuv2_module.contextmanager is not contextlib.contextmanager
        or cuv2_module.Path is not Path
        or cuv2_module.hashlib is not hashlib
        or cuv2_module.sys is not sys
        or _code_fingerprint(wrapped.__code__) != _code_fingerprint(expected_function_code)
        or any(
            not callable(getattr(cuv2_module, name, None))
            or getattr(cuv2_module, name).__globals__ is not cuv2_module.__dict__
            or _code_fingerprint(getattr(cuv2_module, name).__code__)
            != _code_fingerprint(expected_functions[name])
            for name in ("load", "sha", "check")
        )
        or not isinstance(yielded[0], ModuleType)
        or not isinstance(yielded[1], ModuleType)
        or Path(getattr(yielded[0], "__file__", "")).resolve()
        != (root / "backtrader_runtime/certification_roundtrip_private.py").resolve()
        or Path(getattr(yielded[1], "__file__", "")).resolve()
        != (root / "backtrader_runtime/certification_binance_roundtrip_r3_cli.py").resolve()
    ):
        _block("cuv2_module_binding_invalid")
    return raw_map


def _verify_runtime(root: Path) -> None:
    executable = str(Path(sys.executable).resolve())
    if (
        os.name != "nt"
        or sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 11, 5)
        or Path(executable).resolve() != Path(PYTHON_EXE).resolve()
        or not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.dont_write_bytecode
        or not sys.flags.interactive
        or sys.flags.utf8_mode != 1
        or Path(root).resolve() != ROOT.resolve()
    ):
        _block("root_runtime_binding_invalid")


def _verify_source_map(root: Path, expected: Mapping[str, str], held: Mapping[str, bytes]) -> None:
    for absolute, digest in expected.items():
        try:
            path = Path(absolute)
            relative = path.relative_to(root)
            raw = _read_public_source(root, relative.as_posix())
        except ValueError:
            # Runtime and CU paths are software pins. Their live identity is
            # enforced by CUv2 while the scope is open.
            continue
        if _sha(raw) != digest or raw != held.get(absolute):
            _block("postflight_source_pin_mismatch")


def _load_source_module(name: str, path: Path, raw: bytes, package: str) -> ModuleType:
    if name in sys.modules:
        module = sys.modules[name]
        if (
            type(module) is not ModuleType
            or Path(getattr(module, "__file__", "")).resolve() != path.resolve()
            or getattr(module, "__th01_held_source_sha256__", None) != _sha(raw)
        ):
            _block("source_module_collision")
        return module
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = package
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = ModuleSpec(name, loader=None, origin=str(path))
    module.__dict__["__th01_held_source_sha256__"] = _sha(raw)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except Exception:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        _block("source_module_load_failed")
    return module


def _blocked_runner_write_helper(*_args: Any, **_kwargs: Any) -> Any:
    _block("generic_runner_not_loaded")


def _fixed_th01_read_plan(
    case_id: str,
    params: dict[str, object],
    spec: Any,
    ref: Any,
    currency: str,
    venue: str | None = None,
) -> Any:
    """Constrain the source-selected R3 planner to the one TH01 READ plan."""
    if (
        case_id != "TH01"
        or type(params) is not dict
        or set(params)
        != {"external_ref", "evidence_window_id", "expected_threshold", "config_snapshot_id"}
        or type(params.get("expected_threshold")) is not int
        or params.get("expected_threshold") != 5
        or type(params.get("external_ref")) is not str
        or type(params.get("evidence_window_id")) is not str
        or type(params.get("config_snapshot_id")) is not str
        or spec is not None
        or ref is not None
        or currency != "USDT"
        or venue != "binance"
    ):
        _block("read_action_plan_scope_invalid")
    external_ref = params["external_ref"]
    if not external_ref.startswith("root-account-window:"):
        _block("read_action_plan_scope_invalid")
    invocation_id = external_ref.removeprefix("root-account-window:")
    if (
        re.fullmatch(r"[0-9a-f]{32}", invocation_id) is None
        or params["evidence_window_id"] != "th01-window:" + invocation_id
        or params["config_snapshot_id"]
        != globals().get("_ROOT_ACTIVE_TRADELOGGER_CONFIG_SNAPSHOT_ID")
    ):
        _block("read_action_plan_scope_invalid")
    source_plan = globals().get("_source_plan")
    if not callable(source_plan):
        _block("source_read_plan_unavailable")
    return source_plan(case_id, params, spec, ref, currency, venue)


def _verify_source_selected_plan_module(
    module: ModuleType,
    *,
    root: Path,
    held: Mapping[str, bytes],
    cases_module: ModuleType,
    models_module: ModuleType,
) -> None:
    runner_path = root / RUNNER_RELATIVE
    runner_raw = held.get(str(runner_path))
    wrapper_raw = held.get(str(root / WRAPPER_RELATIVE))
    if (
        type(runner_raw) is not bytes
        or type(wrapper_raw) is not bytes
        or type(module) is not ModuleType
        or sys.modules.get(module.__name__) is not module
        or Path(getattr(module, "__file__", "")).resolve() != runner_path.resolve()
        or getattr(module, "__package__", None) != CERTIFICATION_PACKAGE
        or getattr(module, "__loader__", object()) is not None
        or getattr(getattr(module, "__spec__", None), "loader", object()) is not None
        or getattr(module, "__th01_held_source_sha256__", None) != RUNNER_SHA256
        or _sha(runner_raw) != RUNNER_SHA256
        or _sha(wrapper_raw) != _sha(_read_public_source(root, WRAPPER_RELATIVE))
    ):
        _block("selected_read_plan_module_binding_invalid")
    expected_runner = _expected_code_by_qualname(runner_raw, runner_path).get("_plan")
    expected_wrapper = _expected_code_by_qualname(wrapper_raw, root / WRAPPER_RELATIVE).get(
        "_fixed_th01_read_plan"
    )
    source_plan = getattr(module, "_source_plan", None)
    fixed_plan = getattr(module, "_plan", None)
    if (
        type(source_plan) is not FunctionType
        or type(fixed_plan) is not FunctionType
        or source_plan.__globals__ is not module.__dict__
        or fixed_plan.__globals__ is not module.__dict__
        or _code_fingerprint(source_plan.__code__) != expected_runner
        or _code_fingerprint(fixed_plan.__code__) != expected_wrapper
        or Path(source_plan.__code__.co_filename).resolve() != runner_path.resolve()
        or Path(fixed_plan.__code__.co_filename).resolve() != (root / WRAPPER_RELATIVE).resolve()
        or getattr(module, "CASES", None) is not cases_module.CASES
        or getattr(module, "Risk", None) is not models_module.Risk
        or getattr(module, "PlannedOperation", None) is not models_module.PlannedOperation
        or getattr(module, "ActionPlan", None) is not models_module.ActionPlan
        or getattr(module, "CertificationError", None) is not models_module.CertificationError
        or getattr(module, "Decimal", None) is not Decimal
        or getattr(module, "replace", None) is not replace
        or getattr(module, "uuid4", None) is not uuid4
        or getattr(module, "_block", None) is not _block
        or getattr(module, "_notional", None) is not _blocked_runner_write_helper
        or getattr(module, "_operation_request_digest", None) is not _blocked_runner_write_helper
    ):
        _block("selected_read_plan_binding_invalid")


def _load_source_selected_plan_module(
    name: str,
    path: Path,
    raw: bytes,
    package: str,
    *,
    cases_module: ModuleType,
    models_module: ModuleType,
) -> ModuleType:
    """Compile only the pinned runner `_plan` AST node into a sealed module.

    The normal runner imports config parsing and PyYAML, which are outside the
    pinned `-S` READ path. The selected function's code object is checked
    against the complete pinned runner source. A local guard allows only the
    exact TH01 READ plan; no generic runner or config loader is imported.
    """
    if name in sys.modules:
        module = sys.modules[name]
        _verify_source_selected_plan_module(
            module,
            root=ROOT,
            held={
                str(path): raw,
                str(ROOT / WRAPPER_RELATIVE): _read_public_source(ROOT, WRAPPER_RELATIVE),
            },
            cases_module=cases_module,
            models_module=models_module,
        )
        return module
    try:
        tree = ast.parse(raw, filename=str(path))
        selected = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_plan"
        ]
        if len(selected) != 1 or isinstance(selected[0], ast.AsyncFunctionDef):
            _block("selected_read_plan_source_missing")
        module_tree = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                selected[0],
            ],
            type_ignores=[],
        )
        ast.fix_missing_locations(module_tree)
        selected_code = compile(module_tree, str(path), "exec", dont_inherit=True)
    except RootAccountWindowCallBlocked:
        raise
    except Exception:
        _block("selected_read_plan_compile_invalid")
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = package
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = ModuleSpec(name, loader=None, origin=str(path))
    module.__dict__["__th01_held_source_sha256__"] = _sha(raw)
    module.__dict__["__th01_selected_source_qualname__"] = "_plan"
    module.__dict__["CASES"] = cases_module.CASES
    module.__dict__["Risk"] = models_module.Risk
    module.__dict__["PlannedOperation"] = models_module.PlannedOperation
    module.__dict__["ActionPlan"] = models_module.ActionPlan
    module.__dict__["CertificationError"] = models_module.CertificationError
    module.__dict__["Decimal"] = Decimal
    module.__dict__["replace"] = replace
    module.__dict__["uuid4"] = uuid4
    module.__dict__["_block"] = _block
    module.__dict__["_notional"] = _blocked_runner_write_helper
    module.__dict__["_operation_request_digest"] = _blocked_runner_write_helper
    sys.modules[name] = module
    try:
        exec(selected_code, module.__dict__)
        source_plan = module.__dict__.pop("_plan")
        source_plan.__name__ = "_source_plan"
        source_plan.__qualname__ = "_source_plan"
        module.__dict__["_source_plan"] = source_plan
        fixed_plan = FunctionType(_fixed_th01_read_plan.__code__, module.__dict__, name="_plan")
        fixed_plan.__module__ = name
        module.__dict__["_plan"] = fixed_plan
        _verify_source_selected_plan_module(
            module,
            root=ROOT,
            held={
                str(path): raw,
                str(ROOT / WRAPPER_RELATIVE): _read_public_source(ROOT, WRAPPER_RELATIVE),
            },
            cases_module=cases_module,
            models_module=models_module,
        )
    except Exception:
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        if isinstance(sys.exc_info()[1], RootAccountWindowCallBlocked):
            raise
        _block("selected_read_plan_load_failed")
    return module


def _install_source_package(
    root: Path, held: Mapping[str, bytes]
) -> tuple[ModuleType, ModuleType, ModuleType]:
    package_name = "examples.000_live_certification.binance_penetration._certification"
    package_parts = package_name.split(".")
    parent_name = ""
    for part in package_parts:
        parent_name = part if not parent_name else parent_name + "." + part
        module = sys.modules.get(parent_name)
        if module is None:
            module = ModuleType(parent_name)
            module.__package__ = parent_name
            module.__path__ = []
            module.__loader__ = None
            module.__spec__ = ModuleSpec(parent_name, loader=None, origin=None, is_package=True)
            module.__spec__.submodule_search_locations = []
            sys.modules[parent_name] = module
        elif (
            type(module) is not ModuleType
            or getattr(module, "__name__", None) != parent_name
            or getattr(module, "__package__", None) != parent_name
            or getattr(module, "__path__", None) != []
            or hasattr(module, "__file__")
        ):
            _block("source_package_collision")
    paths = {
        "models": MODELS_RELATIVE,
        "cases": CASES_RELATIVE,
        "th01_root_readonly": ROOT_READONLY_RELATIVE,
        "th01_account_full_snapshot_r1": ADAPTER_RELATIVE,
        "th01_force_orders_transport_r1": FORCE_EXTENSION_R1_RELATIVE,
        "th01_force_orders_transport_r2": FORCE_EXTENSION_RELATIVE,
    }
    modules: dict[str, ModuleType] = {}
    for name in ("models", "cases"):
        relative = paths[name]
        path = root / relative
        raw = held[str(path)]
        modules[name] = _load_source_module(package_name + "." + name, path, raw, package_name)
        expected_sha = MODELS_SHA256 if name == "models" else CASES_SHA256
        _verify_loaded_source_module(
            modules[name], path=path, raw=raw, expected_sha256=expected_sha
        )
        setattr(sys.modules[package_name], name, modules[name])

    runner_path = root / RUNNER_RELATIVE
    runner_raw = held[str(runner_path)]
    modules["runner"] = _load_source_selected_plan_module(
        package_name + ".runner",
        runner_path,
        runner_raw,
        package_name,
        cases_module=modules["cases"],
        models_module=modules["models"],
    )
    setattr(sys.modules[package_name], "runner", modules["runner"])

    for name, relative in paths.items():
        if name in {"models", "cases"}:
            continue
        path = root / relative
        raw = held[str(path)]
        modules[name] = _load_source_module(package_name + "." + name, path, raw, package_name)
        expected_sha = _sha(raw)
        if relative == ROOT_READONLY_RELATIVE:
            expected_sha = ROOT_READONLY_SHA256
        _verify_loaded_source_module(
            modules[name], path=path, raw=raw, expected_sha256=expected_sha
        )
        setattr(sys.modules[package_name], name, modules[name])
    return (
        modules["th01_root_readonly"],
        modules["th01_account_full_snapshot_r1"],
        modules["th01_force_orders_transport_r2"],
    )


def _verify_loaded_source_package(root: Path, held: Mapping[str, bytes]) -> dict[str, ModuleType]:
    package_name = CERTIFICATION_PACKAGE
    parent_name = ""
    for part in package_name.split("."):
        parent_name = part if not parent_name else parent_name + "." + part
        package = sys.modules.get(parent_name)
        if (
            type(package) is not ModuleType
            or getattr(package, "__name__", None) != parent_name
            or getattr(package, "__package__", None) != parent_name
            or getattr(package, "__path__", None) != []
            or hasattr(package, "__file__")
            or getattr(getattr(package, "__spec__", None), "loader", object()) is not None
        ):
            _block("source_package_postflight_invalid")
    package = sys.modules[package_name]
    paths = {
        "models": MODELS_RELATIVE,
        "cases": CASES_RELATIVE,
        "th01_root_readonly": ROOT_READONLY_RELATIVE,
        "th01_account_full_snapshot_r1": ADAPTER_RELATIVE,
        "th01_force_orders_transport_r1": FORCE_EXTENSION_R1_RELATIVE,
        "th01_force_orders_transport_r2": FORCE_EXTENSION_RELATIVE,
    }
    modules: dict[str, ModuleType] = {}
    for name, relative in paths.items():
        module = sys.modules.get(package_name + "." + name)
        path = root / relative
        raw = held.get(str(path))
        if type(raw) is not bytes or getattr(package, name, None) is not module:
            _block("source_package_member_postflight_invalid")
        expected_sha = _sha(raw)
        if relative == MODELS_RELATIVE:
            expected_sha = MODELS_SHA256
        elif relative == CASES_RELATIVE:
            expected_sha = CASES_SHA256
        elif relative == ROOT_READONLY_RELATIVE:
            expected_sha = ROOT_READONLY_SHA256
        elif relative == ADAPTER_RELATIVE:
            expected_sha = ADDITIVE_SOURCE_PINS[ADAPTER_RELATIVE][0]
        elif relative == FORCE_EXTENSION_RELATIVE:
            expected_sha = ADDITIVE_SOURCE_PINS[FORCE_EXTENSION_RELATIVE][0]
        elif relative == FORCE_EXTENSION_R1_RELATIVE:
            expected_sha = ADDITIVE_SOURCE_PINS[FORCE_EXTENSION_R1_RELATIVE][0]
        _verify_loaded_source_module(module, path=path, raw=raw, expected_sha256=expected_sha)
        modules[name] = module
    runner = sys.modules.get(package_name + ".runner")
    if getattr(package, "runner", None) is not runner:
        _block("source_package_runner_postflight_invalid")
    _verify_source_selected_plan_module(
        runner,
        root=root,
        held=held,
        cases_module=modules["cases"],
        models_module=modules["models"],
    )
    modules["runner"] = runner
    return modules


def _expected_owner_code(held: Mapping[str, bytes], root: Path) -> dict[str, tuple[Any, ...]]:
    raw = held[str(root / OWNER_RELATIVE)]
    try:
        code = compile(raw, str(root / OWNER_RELATIVE), "exec", dont_inherit=True)
    except Exception:
        _block("owner_source_compile_invalid")
    result = {item.co_qualname: _code_fingerprint(item) for item in _code_objects(code)}
    return result


def _verify_windows_spawn_replayed_worker(
    root: Path,
    held: Mapping[str, bytes],
    replayed_module: ModuleType,
) -> FunctionType:
    """Bind the standard R1 worker after CPython's Windows main-module replay.

    The worker has no relative imports, so its spawn replay keeps the empty
    package produced by ``runpy.run_path``.  Its source, globals, and module
    origin are checked separately from the canonical package binding required
    by the parent account-window collector and the force-orders trampoline.
    """
    expected_path = (root / DRIVER_RELATIVE).resolve()
    launcher_raw = held.get(str(root / DRIVER_RELATIVE))
    owner_raw = held.get(str(root / OWNER_RELATIVE))
    if (
        type(launcher_raw) is not bytes
        or len(launcher_raw) != DRIVER_SIZE
        or _sha(launcher_raw) != DRIVER_SHA256
        or type(owner_raw) is not bytes
        or len(owner_raw) != OWNER_SIZE
        or _sha(owner_raw) != OWNER_SHA256
    ):
        _block("spawn_replayed_source_pin_invalid")
    if (
        type(replayed_module) is not ModuleType
        or replayed_module.__name__ != "__mp_main__"
        or sys.modules.get("__mp_main__") is not replayed_module
        or sys.modules.get("__main__") is not replayed_module
        or Path(getattr(replayed_module, "__file__", "")).resolve() != expected_path
        or getattr(replayed_module, "__package__", None) != ""
        or getattr(replayed_module, "__spec__", object()) is not None
    ):
        _block("spawn_replayed_main_origin_invalid")

    worker = replayed_module.__dict__.get("_root_fixed_signed_get_worker")
    expected = _expected_owner_code(held, root)
    expected_worker = expected.get("_root_fixed_signed_get_worker")
    namespace = getattr(worker, "__globals__", None)
    replay_globals = replayed_module.__dict__
    if (
        type(worker) is not FunctionType
        or worker.__module__ != "__mp_main__"
        or worker.__globals__ is replay_globals
        or type(namespace) is not dict
        or worker.__code__.co_filename != str(root / OWNER_RELATIVE)
        or expected_worker is None
        or _code_fingerprint(worker.__code__) != expected_worker
        or namespace.get("_root_fixed_signed_get_worker") is not worker
        or set(namespace) != set(replay_globals)
        or any(namespace[name] is not replay_globals[name] for name in namespace)
        or namespace.get("__name__") != "__mp_main__"
        or Path(namespace.get("__file__", "")).resolve() != expected_path
        or namespace.get("ROOT") != root
        or namespace.get("OWNER_PATH") != root / OWNER_RELATIVE
        or namespace.get("OWNER_SHA256") != OWNER_SHA256
        or namespace.get("__th01_verified_owner_source_sha256__") != OWNER_SHA256
        or namespace.get("__th01_verified_owner_source_path__") != str(root / OWNER_RELATIVE)
    ):
        _block("spawn_replayed_worker_binding_invalid")

    candidate = namespace.get("_CANDIDATE_MODULE")
    if (
        type(candidate) is not ModuleType
        or Path(getattr(candidate, "__file__", "")).resolve()
        != (root / CANDIDATE_RELATIVE).resolve()
        or getattr(candidate, "__th01_verified_candidate_source_sha256__", None) != CANDIDATE_SHA256
        or getattr(candidate, "DRIVER_PATH", None) != expected_path
        or namespace.get("_CANDIDATE_MODULE") is not replay_globals.get("_CANDIDATE_MODULE")
    ):
        _block("spawn_replayed_candidate_binding_invalid")
    return worker


def _verify_owner_namespace(
    root: Path,
    held: Mapping[str, bytes],
    *,
    force_extension_installed: bool = False,
    package_bound: bool = False,
) -> tuple[ModuleType, ModuleType]:
    owner = sys.modules.get("__main__")
    if (
        not isinstance(owner, ModuleType)
        or owner.__name__ != "__main__"
        or Path(getattr(owner, "__file__", "")).resolve() != (root / DRIVER_RELATIVE).resolve()
        or (
            getattr(owner, "__package__", None) != CERTIFICATION_PACKAGE
            if package_bound
            else getattr(owner, "__package__", None) not in (None, "", CERTIFICATION_PACKAGE)
        )
        or getattr(owner, "OWNER_PATH", None) != (root / OWNER_RELATIVE)
        or getattr(owner, "OWNER_SHA256", None) != OWNER_SHA256
        or getattr(owner, "__th01_verified_owner_source_sha256__", None) != OWNER_SHA256
        or getattr(owner, "__th01_verified_owner_source_path__", None) != str(root / OWNER_RELATIVE)
        or getattr(owner, "ROOT", None) != root
    ):
        _block("canonical_launcher_namespace_invalid")
    candidate = getattr(owner, "_CANDIDATE_MODULE", None)
    if (
        not isinstance(candidate, ModuleType)
        or Path(getattr(candidate, "__file__", "")).resolve()
        != (root / CANDIDATE_RELATIVE).resolve()
        or getattr(candidate, "__th01_verified_candidate_source_sha256__", None) != CANDIDATE_SHA256
        or getattr(candidate, "DRIVER_PATH", None) != (root / DRIVER_RELATIVE).resolve()
    ):
        _block("candidate_module_binding_invalid")
    try:
        if not force_extension_installed and candidate._verify_owner_namespace(owner) is not owner:
            _block("candidate_owner_binding_invalid")
        if candidate._verify_candidate_source_binding() != CANDIDATE_SHA256:
            _block("candidate_source_binding_invalid")
        candidate.source_preflight(root)
    except RootAccountWindowCallBlocked:
        raise
    except Exception:
        _block("candidate_preflight_failed")
    expected = _expected_owner_code(held, root)
    exact_names = (
        "_root_fixed_signed_get_worker",
        "_run_root_fixed_signed_get",
        "_fixed_request_path",
        "FixedAccountWindowGetV1._get",
        "FixedAccountWindowGetV1.account_configuration",
        "FixedAccountWindowGetV1.account_v2",
        "FixedAccountWindowGetV1.open_orders",
        "FixedAccountWindowGetV1.open_algo_orders",
        "FixedAccountWindowGetV1.all_orders",
        "FixedAccountWindowGetV1.user_trades",
        "FixedAccountWindowGetV1.income",
        "_make_root_account_window_auth",
        "_root_th01_credential_context",
        "create_root_protected_writer",
    )
    live = {
        "_root_fixed_signed_get_worker": owner._root_fixed_signed_get_worker,
        "_run_root_fixed_signed_get": owner._run_root_fixed_signed_get,
        "_fixed_request_path": owner._fixed_request_path,
        "FixedAccountWindowGetV1._get": owner.FixedAccountWindowGetV1._get,
        "FixedAccountWindowGetV1.account_configuration": owner.FixedAccountWindowGetV1.account_configuration,
        "FixedAccountWindowGetV1.account_v2": owner.FixedAccountWindowGetV1.account_v2,
        "FixedAccountWindowGetV1.open_orders": owner.FixedAccountWindowGetV1.open_orders,
        "FixedAccountWindowGetV1.open_algo_orders": owner.FixedAccountWindowGetV1.open_algo_orders,
        "FixedAccountWindowGetV1.all_orders": owner.FixedAccountWindowGetV1.all_orders,
        "FixedAccountWindowGetV1.user_trades": owner.FixedAccountWindowGetV1.user_trades,
        "FixedAccountWindowGetV1.income": owner.FixedAccountWindowGetV1.income,
        "_make_root_account_window_auth": owner._make_root_account_window_auth,
        "_root_th01_credential_context": owner._root_th01_credential_context,
        "create_root_protected_writer": owner.create_root_protected_writer,
    }
    patched_names = {"_run_root_fixed_signed_get", "_fixed_request_path"}
    for name in exact_names:
        if force_extension_installed and name in patched_names:
            continue
        function = live.get(name)
        if (
            not callable(function)
            or getattr(function, "__globals__", None) is not owner.__dict__
            or _code_fingerprint(function.__code__) != expected.get(name)
        ):
            _block("owner_function_binding_invalid")
    if getattr(owner._root_fixed_signed_get_worker, "__module__", None) != "__main__":
        _block("owner_worker_module_invalid")
    if force_extension_installed:
        verifier = getattr(owner, "verify_force_orders_owner_binding", None)
        if not callable(verifier):
            _block("force_orders_postflight_verifier_missing")
        try:
            bound = verifier(owner)
        except Exception:
            _block("force_orders_owner_postflight_failed")
        if bound is not True:
            _block("force_orders_owner_postflight_failed")
    return owner, candidate


class _ProcessRecord:
    def __init__(
        self,
        process: Any,
        *,
        owner: ModuleType | None = None,
        worker: FunctionType | None = None,
        worker_code_fingerprint: tuple[Any, ...] | None = None,
    ):
        self.process = process
        self.owner = owner
        self.worker = worker
        self.worker_code_fingerprint = worker_code_fingerprint
        self.start_attempted = False
        self.start_returned = False
        self.join_returned = False
        self.terminate_returned = False
        self.kill_returned = False
        self.close_returned = False
        self.exit_code: int | None = None
        self.import_path_restored = False
        self.error = False

    def verify_target(self) -> None:
        if self.owner is None and self.worker is None and self.worker_code_fingerprint is None:
            return
        try:
            _verify_standard_worker_target(
                self.process,
                owner=self.owner,
                worker=self.worker,
                expected_code=self.worker_code_fingerprint,
            )
        except BaseException:
            self.error = True
            raise


def _verify_standard_worker_target(
    process: Any,
    *,
    owner: ModuleType | None,
    worker: FunctionType | None,
    expected_code: tuple[Any, ...] | None,
) -> None:
    if (
        type(owner) is not ModuleType
        or type(worker) is not FunctionType
        or expected_code is None
        or sys.modules.get("__main__") is not owner
        or owner.__name__ != "__main__"
        or getattr(owner, "__package__", None) != CERTIFICATION_PACKAGE
        or Path(getattr(owner, "__file__", "")).resolve()
        != (owner.ROOT / DRIVER_RELATIVE).resolve()
        or getattr(process, "_target", None) is not worker
        or worker.__module__ != "__main__"
        or worker.__globals__ is not owner.__dict__
        or worker.__code__.co_filename != str(owner.ROOT / OWNER_RELATIVE)
        or _code_fingerprint(worker.__code__) != expected_code
    ):
        _block("spawn_worker_target_binding_invalid")


class _ProcessProxy:
    """Transparent parent-side Process delegate with a retained lifecycle record."""

    def __init__(self, process: Any, record: _ProcessRecord, import_root: Path):
        self._process = process
        self._record = record
        self._import_root = str(import_root.resolve())

    def start(self):
        self._record.verify_target()
        self._record.start_attempted = True
        original_path = list(sys.path)
        try:
            sys.path.insert(0, self._import_root)
            result = self._process.start()
        except BaseException:
            self._record.error = True
            raise
        finally:
            try:
                sys.path[:] = original_path
                self._record.import_path_restored = sys.path == original_path
            except BaseException:
                self._record.error = True
        self._record.start_returned = True
        return result

    def join(self, *args: Any, **kwargs: Any):
        try:
            result = self._process.join(*args, **kwargs)
        except BaseException:
            self._record.error = True
            raise
        self._record.join_returned = True
        return result

    def terminate(self):
        try:
            result = self._process.terminate()
        except BaseException:
            self._record.error = True
            raise
        self._record.terminate_returned = True
        return result

    def kill(self):
        try:
            result = self._process.kill()
        except BaseException:
            self._record.error = True
            raise
        self._record.kill_returned = True
        return result

    def close(self):
        try:
            result = self._process.close()
        except BaseException:
            self._record.error = True
            raise
        self._record.close_returned = True
        return result

    @property
    def exitcode(self):
        try:
            value = self._process.exitcode
        except BaseException:
            self._record.error = True
            raise
        if type(value) is int:
            self._record.exit_code = value
        return value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._process, name)


class _ObservedContext:
    def __init__(self, context: Any, ledger: "_TransportLedger", import_root: Path):
        self._context = context
        self._ledger = ledger
        self._import_root = import_root

    def Pipe(self, *args: Any, **kwargs: Any):
        result = self._context.Pipe(*args, **kwargs)
        if type(result) is not tuple or len(result) != 2:
            _block("pipe_factory_shape_invalid")
        self._ledger.connections.extend(result)
        self._ledger.pipes.append(result)
        return result

    def Process(self, *args: Any, **kwargs: Any):
        process = self._context.Process(*args, **kwargs)
        record = _ProcessRecord(
            process,
            owner=self._ledger.owner,
            worker=self._ledger.standard_worker,
            worker_code_fingerprint=self._ledger.standard_worker_code,
        )
        self._ledger.processes.append(record)
        record.verify_target()
        return _ProcessProxy(process, record, self._import_root)


class _ObservedMultiprocessing:
    def __init__(self, module: Any, ledger: "_TransportLedger", import_root: Path):
        self._module = module
        self._ledger = ledger
        self._import_root = import_root

    def get_context(self, *args: Any, **kwargs: Any):
        context = self._module.get_context(*args, **kwargs)
        return _ObservedContext(context, self._ledger, self._import_root)


class _TransportLedger:
    def __init__(
        self,
        import_root: Path,
        *,
        owner: ModuleType | None = None,
        worker_code_fingerprint: tuple[Any, ...] | None = None,
    ):
        self.processes: list[_ProcessRecord] = []
        self.pipes: list[tuple[Any, Any]] = []
        self.connections: list[Any] = []
        self.recv_frames = 0
        self.eof_observed = False
        self.wait_calls = 0
        self.wait_ready = 0
        self.source_restore_ok = True
        self.import_root = import_root
        self.owner = owner
        self.standard_worker = (
            getattr(owner, "_root_fixed_signed_get_worker", None) if owner is not None else None
        )
        self.standard_worker_code = worker_code_fingerprint
        self.error = False

    def clean(self) -> bool:
        if not self.processes:
            return False
        return (
            self.source_restore_ok
            and not self.error
            and all(
                item.start_attempted
                and item.start_returned
                and item.import_path_restored
                and item.join_returned
                and item.exit_code == 0
                and item.close_returned
                and not item.error
                for item in self.processes
            )
            and self.eof_observed
            and self.recv_frames == len(self.processes)
            and self.wait_calls == len(self.processes)
            and self.wait_ready == len(self.processes)
            and all(_connection_closed(item) for item in self.connections)
        )


class _RootCallRetention:
    """Keep partial Root allocations alive if call construction or cleanup blocks."""

    __slots__ = (
        "credential_context",
        "writer",
        "auth",
        "force_reader",
        "force_attempt_ledger",
        "action",
        "session",
    )

    def __init__(self):
        self.credential_context = None
        self.writer = None
        self.auth = None
        self.force_reader = None
        self.force_attempt_ledger = None
        self.action = None
        self.session = None

    def __repr__(self) -> str:
        return "_RootCallRetention(<private references retained>)"


def _connection_closed(connection: Any) -> bool:
    try:
        if type(getattr(connection, "closed", None)) is bool:
            return connection.closed
        handle = getattr(connection, "_handle", object())
        return handle is None
    except Exception:
        return False


@contextlib.contextmanager
def _observe_transport(owner: ModuleType, ledger: _TransportLedger):
    original_multiprocessing = owner.multiprocessing
    original_wait = owner.wait_for_connections
    original_recv = Connection.recv

    def observed_wait(connections: Any, timeout: float | None = None):
        result = original_wait(connections, timeout=timeout)
        ledger.wait_calls += 1
        if result:
            ledger.wait_ready += 1
        return result

    def observed_recv(connection: Any, *args: Any, **kwargs: Any):
        try:
            value = original_recv(connection, *args, **kwargs)
        except EOFError:
            ledger.eof_observed = True
            raise
        ledger.recv_frames += 1
        return value

    restore_ok = True
    try:
        owner.multiprocessing = _ObservedMultiprocessing(
            original_multiprocessing, ledger, ledger.import_root
        )
        owner.wait_for_connections = observed_wait
        Connection.recv = observed_recv
        yield
    finally:
        try:
            Connection.recv = original_recv
            owner.wait_for_connections = original_wait
            owner.multiprocessing = original_multiprocessing
        except Exception:
            restore_ok = False
        ledger.source_restore_ok = ledger.source_restore_ok and restore_ok


def _page(owner: ModuleType, page: Any, resource: str) -> Any:
    if (
        type(page) is not owner._RootTH01AccountWindowPageV1
        or page.resource != resource
        or page.transport_complete is not True
        or page.truncated is not False
        or type(page.rows) is not tuple
        or type(page.row_count) is not int
        or page.row_count != len(page.rows)
        or type(page.response_body) is not bytes
        or len(page.response_body) >= MAX_PAGE_BYTES
        or type(page.request_ref) is not str
        or type(page.response_ref) is not str
        or not page.request_ref
        or not page.response_ref
        or page.request_ref == page.response_ref
    ):
        _block("sealed_page_invalid")
    return page


def _row_count(page: Any) -> int:
    return page.row_count


def _current_pages(owner: ModuleType, reader: Any) -> tuple[Any, ...]:
    pages: list[Any] = []
    for resource, method_name in CURRENT_METHODS:
        try:
            page = getattr(reader, method_name)()
        except RootAccountWindowCallBlocked:
            raise
        except Exception:
            _block("current_state_read_failed")
        pages.append(_page(owner, page, resource))
    _validate_unique_refs(pages)
    return tuple(pages)


def _validate_unique_refs(pages: list[Any] | tuple[Any, ...]) -> None:
    refs: set[str] = set()
    for page in pages:
        for ref in (page.request_ref, page.response_ref):
            if ref in refs:
                _block("duplicate_request_response_ref")
            refs.add(ref)


def _reader_counters(auth: Any) -> tuple[int, int, int, int | None, float | None]:
    reader = auth._reader
    try:
        requests = reader._request_count[0]
        rows = reader._row_count[0]
        body_bytes = reader._response_bytes[0]
        first_request = reader._first_request_ms[0]
        deadline = reader._capture_deadline_monotonic[0]
    except Exception:
        _block("reader_budget_binding_invalid")
    if (
        type(requests) is not int
        or type(rows) is not int
        or type(body_bytes) is not int
        or requests < 0
        or rows < 0
        or body_bytes < 0
        or requests > MAX_REQUESTS
        or rows > MAX_ROWS
        or body_bytes > MAX_TOTAL_BYTES
        or (first_request is not None and type(first_request) is not int)
        or (deadline is not None and type(deadline) not in (float, int))
    ):
        _block("reader_budget_exceeded")
    return requests, rows, body_bytes, first_request, deadline


def _check_phase_budget(auth: Any) -> None:
    _requests, _rows, _body, first_request_ms, deadline = _reader_counters(auth)
    if deadline is not None and time.monotonic() > float(deadline):
        _block("capture_deadline_exceeded")
    if (
        first_request_ms is not None
        and int(time.time() * 1000) - first_request_ms >= MAX_CAPTURE_MS
    ):
        _block("capture_time_exceeded")


def _next_cutoff_ms(
    *,
    clock_ms: Callable[[], int],
    sleep: Callable[[float], None],
    earliest_ms: int,
    prior_snapshot: Any | None,
    session_started_monotonic: float,
) -> int:
    prior_ms = earliest_ms
    if prior_snapshot is not None:
        try:
            observed = prior_snapshot.observed_at
            parsed = __import__("datetime").datetime.fromisoformat(observed.replace("Z", "+00:00"))
            prior_ms = max(prior_ms, int(parsed.timestamp() * 1000))
        except Exception:
            _block("prior_snapshot_time_invalid")
    while True:
        now = clock_ms()
        cutoff = now - 2_000
        if cutoff > prior_ms:
            if cutoff - earliest_ms > MAX_HISTORY_MS:
                _block("history_window_over_limit")
            return cutoff
        if time.monotonic() - session_started_monotonic >= MAX_CAPTURE_MS / 1000.0:
            _block("capture_deadline_exceeded")
        sleep(0.05)


def _read_all_orders(
    owner: ModuleType,
    reader: Any,
    history_start_ms: int,
    cutoff_ms: int,
    auth: Any,
    ledger: _TransportLedger,
) -> tuple[Any, ...]:
    if history_start_ms - 1 < auth.history_start_ms:
        _block("history_lower_guard_insufficient")
    pages: list[Any] = []
    stack: list[tuple[int, int]] = [(history_start_ms, cutoff_ms - 1)]
    while stack:
        if _reader_counters(auth)[0] >= MAX_REQUESTS:
            _block("request_budget_exhausted")
        lo, hi = stack.pop()
        query_start, query_end = lo - 1, hi + 1
        try:
            page = reader.all_orders(query_start, query_end, None)
        except RootAccountWindowCallBlocked:
            raise
        except Exception:
            _block("all_orders_read_failed")
        page = _page(owner, page, "all_orders_in_window")
        if page.requested_start_ms != query_start or page.requested_end_ms != query_end:
            _block("all_orders_interval_binding_invalid")
        pages.append(page)
        if page.has_more:
            if _row_count(page) != 1000:
                _block("all_orders_pagination_shape_invalid")
            if lo == hi:
                _block("all_orders_one_ms_saturated")
            mid = (lo + hi) // 2
            # Stack order preserves ascending inclusive intervals.
            stack.append((mid + 1, hi))
            stack.append((lo, mid))
        else:
            if _row_count(page) >= 1000:
                _block("all_orders_terminal_proof_invalid")
            if page.terminal_proof != "short_page":
                _block("all_orders_terminal_proof_invalid")
        _check_phase_budget(auth)
    _validate_unique_refs(pages)
    if not pages:
        _block("all_orders_interval_empty")
    return tuple(pages)


def _read_force_orders(
    owner: ModuleType,
    force_reader: Any,
    history_start_ms: int,
    cutoff_ms: int,
    auth: Any,
    attempt_ledger: RootForceOrdersAttemptLedgerV1,
    attempt_snapshot_holder: list[tuple[Any, ...]],
    verify_extension_state: Callable[[], None],
) -> tuple[tuple[Any, RootForceOrdersAttemptTicketV1], ...]:
    if history_start_ms - 1 < auth.history_start_ms:
        _block("history_lower_guard_insufficient")
    if (
        type(attempt_ledger) is not RootForceOrdersAttemptLedgerV1
        or type(attempt_snapshot_holder) is not list
        or len(attempt_snapshot_holder) != 1
        or not attempt_ledger.verify_snapshot(attempt_snapshot_holder[0])
    ):
        _block("force_orders_attempt_ledger_invalid")
    pages: list[Any] = []
    page_ticket_bindings: list[tuple[Any, RootForceOrdersAttemptTicketV1]] = []
    stack: list[tuple[int, int]] = [(history_start_ms, cutoff_ms - 1)]
    while stack:
        if _reader_counters(auth)[0] >= MAX_REQUESTS:
            _block("request_budget_exhausted")
        lo, hi = stack.pop()
        query_start, query_end = lo - 1, hi + 1
        prior_snapshot = attempt_snapshot_holder[0]
        if not attempt_ledger.verify_snapshot(prior_snapshot):
            _block("force_orders_attempt_ledger_invalid")
        ticket = attempt_ledger.reserve(auth, query_start, query_end)
        if not attempt_ledger.verify_transition(prior_snapshot, ticket, "reserved"):
            _block("force_orders_attempt_reservation_invalid")
        reserved_snapshot = attempt_ledger.snapshot()
        call_returned = False
        outcome_code = "interrupted"
        page = None
        try:
            verify_extension_state()
            if not attempt_ledger.verify(
                ticket,
                auth,
                query_start,
                query_end,
                expected_state="reserved",
            ):
                _block("force_orders_attempt_reservation_invalid")
            page = force_reader.force_orders(
                query_start,
                query_end,
                root_attempt=ticket,
            )
            call_returned = True
            outcome_code = "page_received"
        except RootAccountWindowCallBlocked:
            outcome_code = "blocked"
            raise
        except Exception:
            outcome_code = "transport_error"
            _block("force_orders_read_failed")
        finally:
            try:
                extension_state_valid = True
                try:
                    verify_extension_state()
                except Exception:
                    extension_state_valid = False
                dispatch_started = attempt_ledger.verify_transition(
                    reserved_snapshot, ticket, "dispatching"
                )
                still_reserved = attempt_ledger.verify_snapshot(reserved_snapshot)
                transition_valid = dispatch_started or still_reserved
                if call_returned and not dispatch_started:
                    transition_valid = False
                if transition_valid:
                    attempt_ledger.finish(ticket, outcome_code)
                    terminal_valid = attempt_ledger.verify_transition(
                        prior_snapshot,
                        ticket,
                        "terminal",
                        outcome_code,
                    )
                    if terminal_valid:
                        terminal_snapshot = attempt_ledger.snapshot()
                        terminal_valid = attempt_ledger.verify_snapshot(terminal_snapshot)
                    if terminal_valid:
                        attempt_snapshot_holder[0] = terminal_snapshot
                    else:
                        transition_valid = False
                if not transition_valid:
                    _block("force_orders_attempt_ledger_invalid")
                if not extension_state_valid:
                    _block("force_orders_extension_binding_invalid")
            except RootAccountWindowCallBlocked:
                raise
            except Exception:
                _block("force_orders_attempt_ledger_invalid")
        page = _page(owner, page, "force_orders_in_window")
        if page.requested_start_ms != query_start or page.requested_end_ms != query_end:
            _block("force_orders_interval_binding_invalid")
        pages.append(page)
        page_ticket_bindings.append((page, ticket))
        saturated = page.row_count == 100
        if saturated:
            if (
                page.terminal_proof != "interval_saturated"
                or page.has_more is not False
                or page.next_cursor is not None
            ):
                _block("force_orders_saturation_proof_invalid")
            if lo == hi:
                _block("force_orders_one_ms_saturated")
            mid = (lo + hi) // 2
            stack.append((mid + 1, hi))
            stack.append((lo, mid))
        else:
            if (
                page.row_count > 100
                or page.has_more is not False
                or page.terminal_proof != "short_page"
            ):
                _block("force_orders_terminal_proof_invalid")
        _check_phase_budget(auth)
    _validate_unique_refs(pages)
    if not page_ticket_bindings:
        _block("force_orders_interval_empty")
    return tuple(page_ticket_bindings)


def _verify_force_orders_page_ticket_bindings(
    owner: ModuleType,
    auth: Any,
    attempt_ledger: RootForceOrdersAttemptLedgerV1,
    page_ticket_bindings: tuple[tuple[Any, RootForceOrdersAttemptTicketV1], ...],
    verify_extension_state: Callable[[], None],
) -> tuple[Any, ...]:
    verifier = getattr(owner, "verify_force_orders_page", None)
    if (
        not callable(verifier)
        or type(attempt_ledger) is not RootForceOrdersAttemptLedgerV1
        or type(page_ticket_bindings) is not tuple
        or not page_ticket_bindings
    ):
        _block("force_orders_page_ticket_binding_invalid")
    pages: list[Any] = []
    seen_pages: set[int] = set()
    seen_tickets: set[int] = set()
    for binding in page_ticket_bindings:
        if type(binding) is not tuple or len(binding) != 2:
            _block("force_orders_page_ticket_binding_invalid")
        page, ticket = binding
        start_ms = getattr(page, "requested_start_ms", None)
        end_ms = getattr(page, "requested_end_ms", None)
        if (
            type(ticket) is not RootForceOrdersAttemptTicketV1
            or ticket.start_ms != start_ms
            or ticket.end_ms != end_ms
            or id(page) in seen_pages
            or id(ticket) in seen_tickets
            or not attempt_ledger.verify(
                ticket,
                auth,
                start_ms,
                end_ms,
                expected_state="terminal",
            )
        ):
            _block("force_orders_page_ticket_binding_invalid")
        try:
            verify_extension_state()
            verified = verifier(
                auth,
                page,
                start_ms,
                end_ms,
                root_attempt=ticket,
            )
        except Exception:
            _block("force_orders_page_ticket_binding_invalid")
        if verified is not True:
            _block("force_orders_page_ticket_binding_invalid")
        try:
            verify_extension_state()
        except Exception:
            _block("force_orders_extension_binding_invalid")
        seen_pages.add(id(page))
        seen_tickets.add(id(ticket))
        pages.append(page)
    return tuple(pages)


def _force_page_ticket_snapshot_matches(
    bindings: Any,
    holder: Any,
    attempt_ledger: RootForceOrdersAttemptLedgerV1 | None = None,
    auth: Any | None = None,
) -> bool:
    if (
        type(bindings) is not list
        or type(holder) is not list
        or len(holder) != 1
        or type(holder[0]) is not tuple
        or len(bindings) != len(holder[0])
    ):
        return False
    identity_matches = all(
        type(current) is tuple
        and len(current) == 2
        and type(held) is tuple
        and len(held) == 2
        and current[0] is held[0]
        and current[1] is held[1]
        for current, held in zip(bindings, holder[0])
    )
    if not identity_matches or attempt_ledger is None:
        return identity_matches and attempt_ledger is None and auth is None
    return (
        type(attempt_ledger) is RootForceOrdersAttemptLedgerV1
        and auth is attempt_ledger._auth
        and all(
            attempt_ledger.verify(
                ticket,
                auth,
                getattr(page, "requested_start_ms", None),
                getattr(page, "requested_end_ms", None),
                expected_state="terminal",
            )
            for page, ticket in bindings
        )
    )


def _read_income(
    owner: ModuleType, reader: Any, start_ms: int, cutoff_ms: int, auth: Any
) -> tuple[Any, ...]:
    cursor: int | str | None = None
    seen: set[int | str] = set()
    pages: list[Any] = []
    for _ in range(MAX_REQUESTS):
        if _reader_counters(auth)[0] >= MAX_REQUESTS:
            _block("request_budget_exhausted")
        try:
            page = reader.income(start_ms, cutoff_ms - 1, cursor)
        except RootAccountWindowCallBlocked:
            raise
        except Exception:
            _block("income_read_failed")
        page = _page(owner, page, "income_in_window")
        if (
            page.requested_start_ms != start_ms
            or page.requested_end_ms != cutoff_ms - 1
            or page.request_cursor != cursor
        ):
            _block("income_page_binding_invalid")
        pages.append(page)
        if not page.has_more:
            if page.terminal_proof != "short_page" or page.row_count >= 1000:
                _block("income_terminal_proof_invalid")
            break
        next_cursor = page.next_cursor
        if (
            type(next_cursor) is not int
            or next_cursor <= 0
            or next_cursor in seen
            or next_cursor == cursor
            or page.row_count != 1000
        ):
            _block("income_pagination_not_advancing")
        seen.add(next_cursor)
        cursor = next_cursor
        _check_phase_budget(auth)
    else:
        _block("income_page_budget_exhausted")
    _validate_unique_refs(pages)
    return tuple(pages)


def _read_user_trades(
    owner: ModuleType,
    reader: Any,
    symbols: tuple[str, ...],
    start_ms: int,
    cutoff_ms: int,
    auth: Any,
) -> dict[str, tuple[Any, ...]]:
    if type(symbols) is not tuple or tuple(sorted(set(symbols))) != symbols:
        _block("trade_symbol_universe_invalid")
    result: dict[str, tuple[Any, ...]] = {}
    all_pages: list[Any] = []
    for symbol in symbols:
        if type(symbol) is not str or re.fullmatch(r"[A-Z0-9_]{1,32}", symbol) is None:
            _block("trade_symbol_invalid")
        cursor: int | str | None = None
        seen: set[int | str] = set()
        pages: list[Any] = []
        for _ in range(MAX_REQUESTS):
            if _reader_counters(auth)[0] >= MAX_REQUESTS:
                _block("request_budget_exhausted")
            try:
                page = reader.user_trades(symbol, start_ms - 1, cutoff_ms, cursor)
            except RootAccountWindowCallBlocked:
                raise
            except Exception:
                _block("user_trades_read_failed")
            page = _page(owner, page, "user_trades_in_window")
            if page.requested_start_ms != start_ms - 1 or page.requested_end_ms != cutoff_ms:
                _block("user_trades_interval_binding_invalid")
            if page.request_cursor != cursor:
                _block("user_trades_cursor_binding_invalid")
            pages.append(page)
            if not page.has_more:
                if page.terminal_proof != "short_page" or page.row_count >= 1000:
                    _block("user_trades_terminal_proof_invalid")
                break
            next_cursor = page.next_cursor
            if (
                type(next_cursor) is not int
                or next_cursor <= 0
                or next_cursor in seen
                or next_cursor == cursor
                or page.row_count != 1000
            ):
                _block("user_trades_pagination_not_advancing")
            seen.add(next_cursor)
            cursor = next_cursor
            _check_phase_budget(auth)
        else:
            _block("user_trades_page_budget_exhausted")
        result[symbol] = tuple(pages)
        all_pages.extend(pages)
    _validate_unique_refs(all_pages)
    return result


def _verify_auth(owner: ModuleType, auth: Any) -> None:
    if (
        type(auth) is not owner._RootTH01AccountWindowAuthV1
        or auth._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
        or type(auth._reader) is not owner.FixedAccountWindowGetV1
        or auth._reader._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
        or auth._reader.invocation_id != auth.invocation_id
        or auth._reader.evidence_window_id != auth.evidence_window_id
        or auth._reader._account_binding_ref != auth._account_binding_ref
        or auth._reader.history_start_ms != auth.history_start_ms
        or auth.evidence_window_id != "th01-window:" + auth.invocation_id
        or type(auth.history_start_ms) is not int
    ):
        _block("root_auth_binding_invalid")


@dataclass(frozen=True, repr=False)
class RootSnapshotCandidateV1:
    """Private typed snapshots retained behind a safe Root projection."""

    schema: str
    status: str
    phase_count: int
    source_preflight_complete: bool
    source_postflight_complete: bool
    force_orders_bound: bool
    worker_lifecycle_complete: bool
    request_count: int
    row_count: int
    response_bytes: int
    root_host_retention_required: bool
    first_failure: str | None
    snapshots: tuple[Any, ...] = field(repr=False)
    captures: tuple[Any, ...] = field(repr=False)
    session: Any = field(repr=False)

    def __repr__(self) -> str:
        return "RootSnapshotCandidateV1(<private account-window candidate>)"

    def public_document(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "phase_count": self.phase_count,
            "source_preflight_complete": self.source_preflight_complete,
            "source_postflight_complete": self.source_postflight_complete,
            "force_orders_bound": self.force_orders_bound,
            "worker_lifecycle_complete": self.worker_lifecycle_complete,
            "request_count": self.request_count,
            "row_count": self.row_count,
            "response_bytes": self.response_bytes,
            "root_host_retention_required": self.root_host_retention_required,
            "first_failure": self.first_failure,
            "account_full_snapshot_candidate": self.status == "SNAPSHOT_CANDIDATE",
            "generic_runner_invoked": False,
            "trade_logger_attached": False,
            "monitor_ingestion_complete": False,
            "formal_case_pass": False,
            "write_authorized": False,
            "cleanup_authorized": False,
        }


class RootSnapshotBackendHookV1:
    """Sequential per-phase backend hook retaining one R1 auth and reader."""

    def __init__(
        self,
        *,
        owner: ModuleType,
        adapter: ModuleType,
        force_module: ModuleType,
        force_reader: Any,
        auth: Any,
        force_attempt_ledger: RootForceOrdersAttemptLedgerV1,
        force_callback_bindings: tuple[Any, ...],
        force_callback_api_snapshot: tuple[Any, ...],
        action: Any,
        writer: Any,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        sleep: Callable[[float], None] = time.sleep,
        worker_code_fingerprint: tuple[Any, ...] | None = None,
    ):
        _verify_auth(owner, auth)
        self.owner = owner
        self.adapter = adapter
        self.force_module = force_module
        self.force_reader = force_reader
        self.auth = auth
        if type(force_attempt_ledger) is not RootForceOrdersAttemptLedgerV1:
            _block("force_orders_attempt_ledger_invalid")
        self._force_attempt_ledger = force_attempt_ledger
        self._force_attempt_snapshot: list[tuple[Any, ...]] = [force_attempt_ledger.snapshot()]
        self._force_page_ticket_bindings: list[tuple[Any, RootForceOrdersAttemptTicketV1]] = []
        self._force_page_ticket_snapshot: list[tuple[Any, ...]] = [()]
        self._force_callback_bindings = force_callback_bindings
        self._force_callback_api_snapshot = force_callback_api_snapshot
        self.action = action
        self.writer = writer
        self.clock_ms = clock_ms
        self.sleep = sleep
        self._phase_index = 0
        self._baseline = None
        self._captures: list[Any] = []
        self._snapshots: list[Any] = []
        self._cutoffs: list[int] = []
        self._seen_refs: set[str] = set()
        self._ledger = _TransportLedger(
            owner.ROOT,
            owner=owner,
            worker_code_fingerprint=worker_code_fingerprint,
        )
        self._started_monotonic = time.monotonic()
        self._history_start_ms: int | None = None
        self._retention_required = False
        self._sealed = False

    def __repr__(self) -> str:
        return "RootSnapshotBackendHookV1(<Root-protected sequential hook>)"

    def _verify_force_extension_state(self) -> None:
        _verify_force_extension_live_binding(
            self.owner,
            self.auth,
            self.force_reader,
            self._force_callback_bindings,
            self._force_callback_api_snapshot,
        )

    def _check_action(self, action: Any, phase: str) -> None:
        if (
            action is not self.action
            or self._phase_index >= len(PHASES)
            or phase != PHASES[self._phase_index]
        ):
            _block("snapshot_phase_order_invalid")
        validator = getattr(self.adapter, "_validate_action", None)
        if not callable(validator):
            _block("snapshot_action_validator_unavailable")
        try:
            validator(self.auth, action)
        except Exception:
            _block("snapshot_action_binding_invalid")

    def _remember_pages(self, pages: tuple[Any, ...]) -> None:
        for page in pages:
            for ref in (page.request_ref, page.response_ref):
                if ref in self._seen_refs:
                    _block("duplicate_request_response_ref")
                self._seen_refs.add(ref)

    def _collect_one(self, action: Any, phase: str) -> Any:
        self._check_action(action, phase)
        reader = self.auth._reader
        cutoff = None
        if phase != "baseline":
            if self._history_start_ms is None or not self._snapshots:
                _block("baseline_anchor_missing")
            cutoff = _next_cutoff_ms(
                clock_ms=self.clock_ms,
                sleep=self.sleep,
                earliest_ms=self._history_start_ms,
                prior_snapshot=self._snapshots[-1],
                session_started_monotonic=self._started_monotonic,
            )
            self._cutoffs.append(cutoff)
        current_pages = _current_pages(self.owner, reader)
        current_page_map = {
            resource: page for (resource, _method), page in zip(CURRENT_METHODS, current_pages)
        }
        self._remember_pages(current_pages)
        if phase == "baseline":
            try:
                capture = self.adapter.collect_account_snapshot(
                    self.auth,
                    action,
                    phase,
                    current_pages=current_page_map,
                    all_orders_pages=(),
                    income_pages=(),
                    force_order_pages=(),
                    user_trades_by_symbol={},
                    baseline=None,
                    prior_snapshot=None,
                    force_extension=self.owner,
                )
            except Exception as exc:
                _raise_safe_adapter_error(self.owner, exc)
            snapshot = _validate_capture(self.owner, self.adapter, capture, phase)
            baseline_anchor = getattr(capture, "baseline", None)
            start_ms = getattr(baseline_anchor, "history_start_ms", None)
            if (
                type(start_ms) is not int
                or start_ms <= self.auth.history_start_ms
                or start_ms != max(page.response_completed_at_ms for page in current_pages) + 1
            ):
                _block("baseline_boundary_invalid")
            self._history_start_ms = start_ms
            self._baseline = baseline_anchor
        else:
            assert cutoff is not None and self._history_start_ms is not None
            current_started = min(page.request_started_at_ms for page in current_pages)
            current_completed = max(page.response_completed_at_ms for page in current_pages)
            if (
                cutoff + 2_000 > current_started
                or cutoff >= current_completed
                or self.clock_ms() - cutoff < 2_000
                or self.clock_ms() - cutoff >= 120_000
            ):
                _block("phase_cutoff_binding_invalid")
            all_orders = _read_all_orders(
                self.owner, reader, self._history_start_ms, cutoff, self.auth, self._ledger
            )
            if not self._force_attempt_ledger.verify_snapshot(self._force_attempt_snapshot[0]):
                _block("force_orders_attempt_ledger_invalid")
            self._force_attempt_snapshot[0] = self._force_attempt_ledger.set_phase(phase)
            if not self._force_attempt_ledger.verify_snapshot(self._force_attempt_snapshot[0]):
                _block("force_orders_attempt_ledger_invalid")
            page_ticket_bindings = _read_force_orders(
                self.owner,
                self.force_reader,
                self._history_start_ms,
                cutoff,
                self.auth,
                self._force_attempt_ledger,
                self._force_attempt_snapshot,
                self._verify_force_extension_state,
            )
            if not _force_page_ticket_snapshot_matches(
                self._force_page_ticket_bindings,
                self._force_page_ticket_snapshot,
                self._force_attempt_ledger,
                self.auth,
            ):
                _block("force_orders_page_ticket_binding_invalid")
            self._force_page_ticket_bindings.extend(page_ticket_bindings)
            self._force_page_ticket_snapshot[0] = tuple(self._force_page_ticket_bindings)
            if not _force_page_ticket_snapshot_matches(
                self._force_page_ticket_bindings,
                self._force_page_ticket_snapshot,
                self._force_attempt_ledger,
                self.auth,
            ):
                _block("force_orders_page_ticket_binding_invalid")
            force_orders = _verify_force_orders_page_ticket_bindings(
                self.owner,
                self.auth,
                self._force_attempt_ledger,
                page_ticket_bindings,
                self._verify_force_extension_state,
            )
            income = _read_income(self.owner, reader, self._history_start_ms, cutoff, self.auth)
            symbols_fn = getattr(self.adapter, "required_user_trade_symbols", None)
            if not callable(symbols_fn):
                _block("trade_symbol_closure_unavailable")
            try:
                symbols = symbols_fn(
                    self.auth,
                    action,
                    phase,
                    current_pages=current_page_map,
                    all_orders_pages=all_orders,
                    income_pages=income,
                    force_order_pages=force_orders,
                    baseline=self._baseline,
                    prior_snapshot=self._snapshots[-1],
                    force_extension=self.owner,
                    phase_cutoff_ms=cutoff,
                )
            except Exception as exc:
                _raise_safe_adapter_error(self.owner, exc)
            user_trades = _read_user_trades(
                self.owner,
                reader,
                symbols,
                self._history_start_ms,
                cutoff,
                self.auth,
            )
            self._remember_pages(all_orders)
            self._remember_pages(force_orders)
            self._remember_pages(income)
            self._remember_pages(tuple(page for pages in user_trades.values() for page in pages))
            try:
                capture = self.adapter.collect_account_snapshot(
                    self.auth,
                    action,
                    phase,
                    current_pages=current_page_map,
                    all_orders_pages=all_orders,
                    income_pages=income,
                    force_order_pages=force_orders,
                    user_trades_by_symbol=user_trades,
                    baseline=self._baseline,
                    prior_snapshot=self._snapshots[-1],
                    force_extension=self.owner,
                    phase_cutoff_ms=cutoff,
                )
            except Exception as exc:
                _raise_safe_adapter_error(self.owner, exc)
            snapshot = _validate_capture(self.owner, self.adapter, capture, phase)
            if getattr(capture, "baseline", None) is not self._baseline:
                _block("baseline_anchor_identity_changed")
        self._captures.append(capture)
        self._snapshots.append(snapshot)
        self._phase_index += 1
        _check_phase_budget(self.auth)
        return snapshot

    def snapshot(self, action: Any, phase: str) -> Any:
        if self._sealed:
            _block("snapshot_hook_consumed")
        try:
            with _observe_transport(self.owner, self._ledger):
                result = self._collect_one(action, phase)
            return result
        except BaseException:
            self._retention_required = True
            raise

    def collect_three_phases(self) -> RootSnapshotCandidateV1:
        failure = None
        preflight = True
        postflight = False
        try:
            for phase in PHASES:
                self.snapshot(self.action, phase)
            self._sealed = True
            postflight = True
            status = "SNAPSHOT_CANDIDATE"
        except RootAccountWindowCallBlocked as exc:
            failure = exc.code
            status = "BLOCKED_ACCOUNT_SNAPSHOT"
        except Exception:
            failure = "account_window_blocked"
            status = "BLOCKED_ACCOUNT_SNAPSHOT"
        requests, rows, body, _first, _deadline = _reader_counters(self.auth)
        lifecycle_clean = self._ledger.clean() if self._ledger.processes else False
        if not lifecycle_clean or self._phase_index != len(PHASES):
            self._retention_required = True
        return RootSnapshotCandidateV1(
            schema="iteration41.binance.th01.root-account-window-snapshot-candidate.r1",
            status=status,
            phase_count=len(self._snapshots),
            source_preflight_complete=preflight,
            source_postflight_complete=postflight,
            force_orders_bound=True,
            worker_lifecycle_complete=lifecycle_clean,
            request_count=requests,
            row_count=rows,
            response_bytes=body,
            root_host_retention_required=self._retention_required,
            first_failure=failure,
            snapshots=tuple(self._snapshots),
            captures=tuple(self._captures),
            session=self,
        )


def _raise_safe_adapter_error(owner: ModuleType, exc: BaseException) -> None:
    blocked_type = getattr(owner, "RootTH01AccountWindowBlocked", None)
    if type(exc) is blocked_type:
        code = getattr(exc, "code", None)
        if type(code) is str and _SAFE_CODE.fullmatch(code):
            _block(code)
    code = getattr(exc, "code", None)
    if type(code) is str and _SAFE_CODE.fullmatch(code):
        _block(code)
    _block("snapshot_adapter_blocked")


def _validate_capture(owner: ModuleType, adapter: ModuleType, capture: Any, phase: str) -> Any:
    capture_type = getattr(adapter, "SnapshotCaptureV1", None)
    if capture_type is None or type(capture) is not capture_type:
        _block("snapshot_capture_type_invalid")
    snapshot = getattr(capture, "snapshot", None)
    models = sys.modules.get(
        "examples.000_live_certification.binance_penetration._certification.models"
    )
    state_type = getattr(models, "StateSnapshot", None)
    if (
        state_type is None
        or type(snapshot) is not state_type
        or snapshot.phase != phase
        or snapshot.scope != "account_full"
        or snapshot.complete is not True
        or snapshot.pagination_complete is not True
    ):
        _block("account_full_snapshot_candidate_invalid")
    return snapshot


def _load_and_verify_source_dependencies(
    *,
    root: Path,
    held: Mapping[str, bytes],
    owner: ModuleType,
) -> tuple[ModuleType, ModuleType, ModuleType]:
    rootreadonly, adapter, force_module = _install_source_package(root, held)
    _verify_loaded_source_package(root, held)
    if getattr(owner, "__package__", None) not in (
        None,
        "",
        CERTIFICATION_PACKAGE,
    ):
        _block("canonical_package_binding_invalid")
    owner.__package__ = CERTIFICATION_PACKAGE
    if (
        Path(getattr(rootreadonly, "__file__", "")).resolve()
        != (root / ROOT_READONLY_RELATIVE).resolve()
        or getattr(rootreadonly, "__th01_held_source_sha256__", None) != ROOT_READONLY_SHA256
    ):
        _block("root_readonly_binding_invalid")

    return rootreadonly, adapter, force_module


def _install_and_capture_force_extension(
    owner: ModuleType,
    force_module: ModuleType,
    root_wrapper_module: ModuleType,
) -> tuple[Any, Any, tuple[Any, ...]]:
    if not FORCE_EXTENSION_INTEGRATION_ENABLED:
        _block("force_orders_extension_review_pending")
    installer = getattr(force_module, "install_force_orders_extension", None)
    if not callable(installer):
        _block("force_orders_extension_unavailable")
    try:
        installed_owner = installer(owner, root_wrapper_module)
    except Exception:
        _block("force_orders_extension_install_failed")
    if installed_owner is not owner:
        _block("force_orders_owner_binding_invalid")
    owner_verifier = getattr(owner, "verify_force_orders_owner_binding", None)
    verifier = getattr(owner, "verify_force_orders_reader_binding", None)
    capability_type = getattr(owner, "FixedForceOrdersGetV1", None)
    capture_callbacks = getattr(owner, "capture_force_orders_callback_bindings", None)
    verify_callbacks = getattr(owner, "verify_force_orders_callback_bindings", None)
    if (
        not callable(owner_verifier)
        or not callable(verifier)
        or not isinstance(capability_type, type)
        or type(capture_callbacks) is not FunctionType
        or type(verify_callbacks) is not FunctionType
        or capture_callbacks
        is not getattr(force_module, "capture_force_orders_callback_bindings", None)
        or verify_callbacks
        is not getattr(force_module, "verify_force_orders_callback_bindings", None)
    ):
        _block("force_orders_capability_unavailable")
    capture_shape = _function_binding_shape(capture_callbacks)
    verify_shape = _function_binding_shape(verify_callbacks)
    force_module_globals = _module_binding_snapshot(force_module, mutable_globals=frozenset())
    try:
        callback_bindings = capture_callbacks(owner)
    except Exception:
        _block("force_orders_callback_capture_failed")
    if (
        type(callback_bindings) is not tuple
        or type(getattr(owner, "_ROOT_TH01_FORCE_ORDERS_EXTENSION_R2_SHA256", None)) is not str
        or ADDITIVE_SOURCE_PINS[FORCE_EXTENSION_RELATIVE][0]
        != owner._ROOT_TH01_FORCE_ORDERS_EXTENSION_R2_SHA256
    ):
        _block("force_orders_callback_capture_invalid")
    return (
        capability_type,
        callback_bindings,
        (
            force_module,
            force_module_globals,
            capture_callbacks,
            capture_shape,
            verify_callbacks,
            verify_shape,
        ),
    )


def _verify_force_extension_callback_bindings(
    owner: ModuleType,
    held: tuple[Any, ...],
    api_snapshot: tuple[Any, ...],
) -> None:
    if type(api_snapshot) is not tuple or len(api_snapshot) != 6:
        _block("force_orders_callback_binding_invalid")
    (
        force_module,
        globals_snapshot,
        capture_callbacks,
        capture_shape,
        verify_callbacks,
        verify_shape,
    ) = api_snapshot
    if (
        sys.modules.get(force_module.__name__) is not force_module
        or _module_binding_snapshot(force_module, mutable_globals=frozenset()) != globals_snapshot
        or getattr(owner, "capture_force_orders_callback_bindings", None) is not capture_callbacks
        or getattr(owner, "verify_force_orders_callback_bindings", None) is not verify_callbacks
        or getattr(force_module, "capture_force_orders_callback_bindings", None)
        is not capture_callbacks
        or getattr(force_module, "verify_force_orders_callback_bindings", None)
        is not verify_callbacks
        or type(capture_callbacks) is not FunctionType
        or type(verify_callbacks) is not FunctionType
        or _function_binding_shape(capture_callbacks) != capture_shape
        or _function_binding_shape(verify_callbacks) != verify_shape
    ):
        _block("force_orders_callback_binding_invalid")
    try:
        valid = verify_callbacks(owner, held)
    except Exception:
        _block("force_orders_callback_binding_invalid")
    if valid is not True:
        _block("force_orders_callback_binding_invalid")


def _verify_force_extension_live_binding(
    owner: ModuleType,
    auth: Any,
    force_reader: Any,
    callback_bindings: tuple[Any, ...],
    callback_api_snapshot: tuple[Any, ...],
) -> None:
    _verify_force_extension_callback_bindings(owner, callback_bindings, callback_api_snapshot)
    owner_verifier = getattr(owner, "verify_force_orders_owner_binding", None)
    reader_verifier = getattr(owner, "verify_force_orders_reader_binding", None)
    if not callable(owner_verifier) or not callable(reader_verifier):
        _block("force_orders_extension_binding_invalid")
    try:
        owner_valid = owner_verifier(owner)
        reader_valid = reader_verifier(owner, auth, force_reader)
    except Exception:
        _block("force_orders_extension_binding_invalid")
    if owner_valid is not True or reader_valid is not True:
        _block("force_orders_extension_binding_invalid")


def _verify_cuv2_bindings(cuv2_module: ModuleType) -> None:
    function = getattr(cuv2_module, "held_public_sources", None)
    wrapped = getattr(function, "__wrapped__", None)
    if (
        not callable(function)
        or not callable(wrapped)
        or getattr(function, "__module__", None) != cuv2_module.__name__
        or getattr(wrapped, "__module__", None) != cuv2_module.__name__
        or getattr(wrapped, "__globals__", None) is not cuv2_module.__dict__
        or cuv2_module.load.__globals__ is not cuv2_module.__dict__
        or cuv2_module.sha.__globals__ is not cuv2_module.__dict__
        or cuv2_module.check.__globals__ is not cuv2_module.__dict__
    ):
        _block("cuv2_function_binding_invalid")


def _make_actual_session(
    *,
    owner: ModuleType,
    adapter: ModuleType,
    force_module: ModuleType,
    force_capability_type: Any,
    force_callback_bindings: tuple[Any, ...],
    force_callback_api_snapshot: tuple[Any, ...],
    config_snapshot_id: str,
    expected_worker_code: tuple[Any, ...],
    retention: _RootCallRetention,
) -> RootSnapshotBackendHookV1:
    history_start_ms = int(time.time() * 1000) - 24 * 60 * 60 * 1000
    invocation_id = uuid4().hex
    evidence_window_id = "th01-window:" + invocation_id
    credential_context = owner._root_th01_credential_context(owner.ROOT / ".env")
    retention.credential_context = credential_context
    writer = owner.create_root_protected_writer(invocation_id)
    retention.writer = writer
    auth = owner._make_root_account_window_auth(
        credential_context,
        writer,
        invocation_id,
        evidence_window_id,
        history_start_ms,
    )
    retention.auth = auth
    retention.credential_context = None
    del credential_context
    force_attempt_ledger = RootForceOrdersAttemptLedgerV1(auth)
    retention.force_attempt_ledger = force_attempt_ledger
    force_reader = force_capability_type(auth, force_attempt_ledger)
    retention.force_reader = force_reader
    verifier = owner.verify_force_orders_reader_binding
    try:
        verifier(owner, auth, force_reader)
    except Exception:
        _block("force_orders_reader_binding_invalid")
    action_factory = getattr(adapter, "root_th01_read_action", None)
    if not callable(action_factory):
        _block("snapshot_action_factory_unavailable")
    try:
        action = action_factory(
            auth,
            external_ref="root-account-window:" + invocation_id,
            config_snapshot_id=config_snapshot_id,
        )
    except Exception:
        _block("snapshot_action_binding_invalid")
    retention.action = action
    try:
        writer_ref = writer.write_private_record(
            "account_window_snapshot_start",
            {
                "schema": "iteration41.binance.th01.root-account-window-start.private.r1",
                "invocation_ref": invocation_id,
                "evidence_window_ref": evidence_window_id,
                "history_start_ms": history_start_ms,
                "history_window_ms": 24 * 60 * 60 * 1000,
                "source_kind": "ROOT_PROTECTED_ACCOUNT_WINDOW_READ",
            },
        )
        auth._reader._private_record_refs.append(writer_ref)
    except Exception:
        _block("protected_writer_record_failed")
    session = RootSnapshotBackendHookV1(
        owner=owner,
        adapter=adapter,
        force_module=force_module,
        force_reader=force_reader,
        auth=auth,
        force_attempt_ledger=force_attempt_ledger,
        force_callback_bindings=force_callback_bindings,
        force_callback_api_snapshot=force_callback_api_snapshot,
        action=action,
        writer=writer,
        worker_code_fingerprint=expected_worker_code,
    )
    retention.session = session
    return session


def _verified_active_trade_logger_config_snapshot_id(
    active_trade_logger: Any | None,
) -> str:
    """Fail closed until the active source-owned observer receipt is available."""
    if active_trade_logger is None:
        _block("active_trade_logger_config_snapshot_required")
    _block("trade_logger_config_snapshot_source_unreviewed")


def run_root_cold_account_window(
    cuv2_module: ModuleType,
    lease: Any,
    yielded: Any,
    *,
    public_pins: Mapping[str, str],
    software_pins: Mapping[str, str],
    active_trade_logger: Any | None = None,
    root: Path = ROOT,
) -> RootSnapshotCandidateV1:
    """Run one Root-protected, three-phase, read-only account snapshot call.

    Caller enters the exact pinned CUv2 context first, launches the canonical
    R2 script into ``__main__`` with ``--qa-source-only`` and catches its
    ``SystemExit(0)``, then calls this function while the CUv2 generator is
    still suspended at its yield.  The function never exits that scope.
    """
    checked_root = Path(root).resolve()
    session: RootSnapshotBackendHookV1 | None = None
    retention_refs: _RootCallRetention | None = None
    owner: ModuleType | None = None
    force_module: ModuleType | None = None
    held: Mapping[str, bytes] | None = None
    expected: Mapping[str, str] | None = None
    failure: str | None = None
    snapshots: tuple[Any, ...] = ()
    captures: tuple[Any, ...] = ()
    status = "BLOCKED_ACCOUNT_SNAPSHOT"
    preflight_complete = False
    postflight_complete = False
    lifecycle_clean = False
    requests = rows = body_bytes = 0
    retention = False
    scope_verified = False
    force_extension_installed = False
    force_install_attempted = False
    force_callback_bindings: Any = None
    force_callback_api_snapshot: tuple[Any, ...] | None = None
    source_modules: dict[str, ModuleType] | None = None
    source_bindings_before_auth: tuple[
        tuple[ModuleType, frozenset[str], tuple[Any, ...]], ...
    ] | None = None
    source_bindings_after_install: tuple[
        tuple[ModuleType, frozenset[str], tuple[Any, ...]], ...
    ] | None = None
    source_bindings_after_auth: tuple[
        tuple[ModuleType, frozenset[str], tuple[Any, ...]], ...
    ] | None = None
    candidate: ModuleType | None = None
    wrapper_module: ModuleType | None = None
    try:
        if checked_root != ROOT.resolve():
            _block("source_root_mismatch")
        _verify_cuv2_bindings(cuv2_module)
        held = _verify_cuv2_scope(
            cuv2_module, lease, yielded, public_pins, software_pins, checked_root
        )
        scope_verified = True
        wrapper_module = _verify_wrapper_namespace(checked_root, held)
        _verify_runtime(checked_root)
        owner, candidate = _verify_owner_namespace(checked_root, held)
        if not FORCE_EXTENSION_INTEGRATION_ENABLED:
            _block("force_orders_extension_review_pending")
        _rootreadonly, adapter, force_module = _load_and_verify_source_dependencies(
            root=checked_root, held=held, owner=owner
        )
        force_install_attempted = True
        (
            force_capability_type,
            force_callback_bindings,
            force_callback_api_snapshot,
        ) = _install_and_capture_force_extension(owner, force_module, wrapper_module)
        force_extension_installed = True
        # Check the exact R3 source closure before any credential or writer call.
        _r3_source_rows(checked_root, use_held=held)
        expected = _all_expected_pins(checked_root)
        _verify_source_map(checked_root, expected, held)
        wrapper_module = _verify_wrapper_namespace(checked_root, held)
        source_modules = _verify_loaded_source_package(checked_root, held)
        if (
            type(getattr(owner, "_ACTIVE_ROOT_ACCOUNT_AUTH", None)) is not list
            or owner._ACTIVE_ROOT_ACCOUNT_AUTH
            or type(getattr(owner, "_ACTIVE_ROOT_FIXED_WORKERS", None)) is not list
            or owner._ACTIVE_ROOT_FIXED_WORKERS
            or type(getattr(owner, "_ACTIVE_ROOT_PROBE_RECEIPTS", None)) is not list
            or owner._ACTIVE_ROOT_PROBE_RECEIPTS
        ):
            _block("fresh_root_owner_state_required")
        source_bindings_after_install = _capture_source_binding_snapshots(
            wrapper=wrapper_module,
            owner=owner,
            candidate=candidate,
            source_modules={**source_modules, "cuv2": cuv2_module},
        )
        config_snapshot_id = _verified_active_trade_logger_config_snapshot_id(active_trade_logger)
        plan_module = source_modules["runner"]
        plan_module._ROOT_ACTIVE_TRADELOGGER_CONFIG_SNAPSHOT_ID = config_snapshot_id
        source_bindings_before_auth = _capture_source_binding_snapshots(
            wrapper=wrapper_module,
            owner=owner,
            candidate=candidate,
            source_modules={**source_modules, "cuv2": cuv2_module},
            mutable_global_overrides=_pre_action_mutable_globals(adapter),
        )
        preflight_complete = True
        expected_worker_code = _expected_owner_code(held, checked_root).get(
            "_root_fixed_signed_get_worker"
        )
        if expected_worker_code is None:
            _block("spawn_worker_source_binding_invalid")
        retention_refs = _RootCallRetention()
        _ACTIVE_SESSIONS.append(retention_refs)
        session = _make_actual_session(
            owner=owner,
            adapter=adapter,
            force_module=force_module,
            force_capability_type=force_capability_type,
            force_callback_bindings=force_callback_bindings,
            force_callback_api_snapshot=force_callback_api_snapshot,
            config_snapshot_id=config_snapshot_id,
            expected_worker_code=expected_worker_code,
            retention=retention_refs,
        )
        _verify_source_binding_snapshots(source_bindings_before_auth)
        source_bindings_after_auth = _capture_source_binding_snapshots(
            wrapper=wrapper_module,
            owner=owner,
            candidate=candidate,
            source_modules={**source_modules, "cuv2": cuv2_module},
        )
        result = session.collect_three_phases()
        snapshots = result.snapshots
        captures = result.captures
        status = result.status
        failure = result.first_failure
        requests = result.request_count
        rows = result.row_count
        body_bytes = result.response_bytes
        retention = result.root_host_retention_required
        lifecycle_clean = result.worker_lifecycle_complete
    except RootAccountWindowCallBlocked as exc:
        failure = exc.code
        retention = retention_refs is not None or force_install_attempted
        if session is not None:
            requests, rows, body_bytes, _first, _deadline = _reader_counters(session.auth)
            lifecycle_clean = session._ledger.clean() if session._ledger.processes else False
    except Exception:
        failure = "account_window_blocked"
        retention = retention_refs is not None or force_install_attempted
        if session is not None:
            requests, rows, body_bytes, _first, _deadline = _reader_counters(session.auth)
            lifecycle_clean = session._ledger.clean() if session._ledger.processes else False
    finally:
        if scope_verified and held is not None:
            try:
                _verify_cuv2_bindings(cuv2_module)
                _verify_cuv2_scope(
                    cuv2_module, lease, yielded, public_pins, software_pins, checked_root
                )
                _verify_wrapper_namespace(checked_root, held)
                _verify_source_map(
                    checked_root,
                    _all_expected_pins(checked_root),
                    held,
                )
                final_source_modules = (
                    _verify_loaded_source_package(checked_root, held)
                    if source_modules is not None
                    else None
                )
                if source_bindings_after_install is not None:
                    _verify_source_binding_snapshots(source_bindings_after_install)
                if source_bindings_after_auth is not None:
                    _verify_source_binding_snapshots(source_bindings_after_auth)
                if force_install_attempted and not force_extension_installed:
                    _block("force_orders_installation_uncertain")
                if owner is not None:
                    if force_extension_installed:
                        if force_callback_api_snapshot is None:
                            _block("force_orders_callback_binding_missing")
                        _verify_force_extension_callback_bindings(
                            owner,
                            force_callback_bindings,
                            force_callback_api_snapshot,
                        )
                    _verify_owner_namespace(
                        checked_root,
                        held,
                        force_extension_installed=force_extension_installed,
                        package_bound=force_extension_installed,
                    )
                    active_workers = getattr(owner, "_ACTIVE_ROOT_FIXED_WORKERS", None)
                    active_auth = getattr(owner, "_ACTIVE_ROOT_ACCOUNT_AUTH", None)
                    active_probes = getattr(owner, "_ACTIVE_ROOT_PROBE_RECEIPTS", None)
                    if (
                        type(active_workers) is not list
                        or active_workers
                        or type(active_auth) is not list
                        or (retention_refs is None and active_auth)
                        or (
                            retention_refs is not None
                            and (len(active_auth) != 1 or active_auth[0] is not retention_refs.auth)
                        )
                        or type(active_probes) is not list
                        or active_probes
                    ):
                        _block("root_owner_runtime_ledger_invalid")
                    if retention_refs is not None and retention_refs.auth is not None:
                        _verify_auth(owner, retention_refs.auth)
                        reader_verifier = getattr(owner, "verify_force_orders_reader_binding", None)
                        if (
                            not callable(reader_verifier)
                            or reader_verifier(
                                owner, retention_refs.auth, retention_refs.force_reader
                            )
                            is not True
                        ):
                            _block("force_orders_reader_binding_invalid")
                        attempt_ledger = retention_refs.force_attempt_ledger
                        if (
                            type(attempt_ledger) is not RootForceOrdersAttemptLedgerV1
                            or session is None
                            or session._force_attempt_ledger is not attempt_ledger
                            or type(session._force_attempt_snapshot) is not list
                            or len(session._force_attempt_snapshot) != 1
                            or not attempt_ledger.verify_snapshot(
                                session._force_attempt_snapshot[0]
                            )
                            or not _force_page_ticket_snapshot_matches(
                                session._force_page_ticket_bindings,
                                session._force_page_ticket_snapshot,
                                session._force_attempt_ledger,
                                retention_refs.auth,
                            )
                        ):
                            _block("force_orders_attempt_ledger_invalid")
                    if source_modules is not None and final_source_modules != source_modules:
                        _block("source_package_postflight_invalid")
                    if source_modules is None and any(
                        name == CERTIFICATION_PACKAGE
                        or name.startswith(CERTIFICATION_PACKAGE + ".")
                        for name in sys.modules
                    ):
                        _block("source_package_unexpectedly_loaded")
                postflight_complete = True
            except Exception:
                failure = failure or "postflight_source_binding_invalid"
                status = "BLOCKED_ACCOUNT_SNAPSHOT"
                retention = retention_refs is not None or force_install_attempted
    if not postflight_complete:
        status = "BLOCKED_ACCOUNT_SNAPSHOT"
    if status != "SNAPSHOT_CANDIDATE" or not lifecycle_clean or len(snapshots) != 3:
        retention = retention or retention_refs is not None
    return RootSnapshotCandidateV1(
        schema="iteration41.binance.th01.root-account-window-snapshot-candidate.r1",
        status=status,
        phase_count=len(snapshots),
        source_preflight_complete=preflight_complete,
        source_postflight_complete=postflight_complete,
        force_orders_bound=force_extension_installed and postflight_complete,
        worker_lifecycle_complete=lifecycle_clean,
        request_count=requests,
        row_count=rows,
        response_bytes=body_bytes,
        root_host_retention_required=retention,
        first_failure=failure,
        snapshots=snapshots,
        captures=captures,
        session=session,
    )


__all__ = [
    "RootAccountWindowCallBlocked",
    "RootForceOrdersAttemptLedgerV1",
    "RootForceOrdersAttemptTicketV1",
    "RootSnapshotBackendHookV1",
    "RootSnapshotCandidateV1",
    "required_public_source_pins",
    "required_software_source_pins",
    "run_root_cold_account_window",
]
