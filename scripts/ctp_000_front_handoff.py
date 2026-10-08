"""Ephemeral zero-authority handoff from a current 000 transport selection.

This module deliberately accepts public endpoints-only projection bytes and
runs the paired selector itself. It never reads credentials, loads the SDK,
serializes a selection, or grants login/provider/trading authority. The fixed
renderer may consume a result once, in the issuing process and thread, while
binding it to the exact same projection bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import threading
import time


_HANDOFF_FACTORY = object()
_SELECTION_FACTORY = object()
_HANDOFF_TTL_NS = 5_000_000_000


class FrontHandoffError(ValueError):
    """Fixed, redacted failure reason for the renderer handoff boundary."""


@dataclass(frozen=True, repr=False, init=False)
class SelectedFrontPair:
    """Endpoint configuration only; this value conveys no execution authority."""

    config_index: int
    md_front: str
    td_front: str
    public_projection_sha256: str
    observation_sha256: str
    degraded_candidate: bool
    execution_authority: str = "NONE"

    def __init__(
        self,
        config_index,
        md_front,
        td_front,
        public_projection_sha256,
        observation_sha256,
        degraded_candidate,
        execution_authority="NONE",
        *,
        _factory=None,
    ):
        if _factory is not _SELECTION_FACTORY:
            _blocked("current_transport_selection_factory_required")
        object.__setattr__(self, "config_index", config_index)
        object.__setattr__(self, "md_front", md_front)
        object.__setattr__(self, "td_front", td_front)
        object.__setattr__(self, "public_projection_sha256", public_projection_sha256)
        object.__setattr__(self, "observation_sha256", observation_sha256)
        object.__setattr__(self, "degraded_candidate", degraded_candidate)
        object.__setattr__(self, "execution_authority", execution_authority)

    def __repr__(self):
        return (
            "SelectedFrontPair(config_index=%d, degraded_candidate=%s, "
            "execution_authority='NONE')" % (self.config_index, self.degraded_candidate)
        )

    def __reduce__(self):
        raise TypeError("selected_front_pair_not_serializable")

    def __reduce_ex__(self, protocol):
        raise TypeError("selected_front_pair_not_serializable")


def _pid():
    return os.getpid()


def _thread_id():
    return threading.get_ident()


def _monotonic_ns():
    return time.monotonic_ns()


def _blocked(reason):
    raise FrontHandoffError(reason) from None


def _selection_from_current_observation(raw, observation):
    from scripts import ctp_000_paired_front_selector as selector

    if type(observation) is not dict:
        _blocked("current_transport_observation_invalid")
    index = observation.get("selected_config_index")
    rows = observation.get("pairs")
    if (
        observation.get("schema") != "ctp_000_paired_front_observation.v1"
        or observation.get("strategy_id") != selector.STRATEGY
        or observation.get("venue") != "simnow"
        or observation.get("scope") != "transport_only"
        or observation.get("status") != "TRANSPORT_CANDIDATE"
        or observation.get("deadline_observed_exceeded") is not False
        or observation.get("tcp_probe_started") is not True
        or observation.get("provider_login_started") is not False
        or observation.get("md_subscription_started") is not False
        or observation.get("registered_runtime_dispatched") is not False
        or type(observation.get("trading_writes")) is not int
        or observation.get("trading_writes") != 0
        or observation.get("execution_authority") != "NONE"
        or type(index) is not int
        or type(rows) is not list
        or type(observation.get("configured_pair_count")) is not int
        or type(observation.get("degraded_candidate")) is not bool
    ):
        _blocked("current_transport_observation_invalid")

    pairs = selector.parse_document(raw)
    if (
        observation["configured_pair_count"] != len(pairs)
        or len(rows) != len(pairs)
        or not 0 <= index < len(pairs)
    ):
        _blocked("current_transport_pair_binding_invalid")
    row = rows[index] if index < len(rows) else None
    if (
        type(row) is not dict
        or type(row.get("config_index")) is not int
        or row.get("config_index") != index
        or row.get("eligible_both_reachable") is not True
        or type(row.get("stable_both_3_of_3")) is not bool
        or observation.get("degraded_candidate") is not (not row["stable_both_3_of_3"])
    ):
        _blocked("current_transport_pair_binding_invalid")
    elapsed = observation.get("elapsed_seconds")
    if (
        type(elapsed) not in (int, float)
        or not math.isfinite(elapsed)
        or elapsed < 0
        or elapsed >= selector.DEADLINE_SECONDS
    ):
        _blocked("current_transport_observation_expired")

    projection_digest = hashlib.sha256(raw).hexdigest()
    observation_bytes = json.dumps(
        observation, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    observation_digest = hashlib.sha256(
        b"ctp_000_current_transport_observation.v1\0"
        + projection_digest.encode("ascii")
        + b"\0"
        + observation_bytes
    ).hexdigest()
    pair = pairs[index]
    return SelectedFrontPair(
        config_index=index,
        md_front=pair["md_front"],
        td_front=pair["td_front"],
        public_projection_sha256=projection_digest,
        observation_sha256=observation_digest,
        degraded_candidate=observation["degraded_candidate"],
        _factory=_SELECTION_FACTORY,
    )


class OneUseTransportHandoff:
    """Unserializable, process/thread-bound handle for a just-run selector.

    This is an internal configuration handoff, not a trusted receipt. Its
    endpoint properties are available only after consume() validates the exact
    original public projection and the short in-process freshness window.
    """

    __slots__ = (
        "_selection",
        "_pid_value",
        "_thread_value",
        "_issued_ns",
        "_used",
        "_lock",
    )

    def __init__(self, token, selection, *, pid, thread_id, issued_ns):
        if token is not _HANDOFF_FACTORY:
            _blocked("transport_handoff_unavailable")
        object.__setattr__(self, "_selection", selection)
        object.__setattr__(self, "_pid_value", pid)
        object.__setattr__(self, "_thread_value", thread_id)
        object.__setattr__(self, "_issued_ns", issued_ns)
        object.__setattr__(self, "_used", False)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, name, value):
        raise AttributeError("transport_handoff_is_immutable")

    def __delattr__(self, name):
        raise AttributeError("transport_handoff_is_immutable")

    def __repr__(self):
        return "OneUseTransportHandoff(status='unconsumed', authority='NONE')"

    def __reduce__(self):
        raise TypeError("transport_handoff_not_serializable")

    def __reduce_ex__(self, protocol):
        raise TypeError("transport_handoff_not_serializable")

    def consume(self, original_public_projection):
        """Return the selected endpoint pair once, for the issuing render call."""

        with self._lock:
            if self._used:
                _blocked("transport_handoff_already_consumed")
            object.__setattr__(self, "_used", True)

        if (
            type(original_public_projection) is not bytes
            or hashlib.sha256(original_public_projection).hexdigest()
            != self._selection.public_projection_sha256
        ):
            _blocked("transport_handoff_projection_mismatch")
        now = _monotonic_ns()
        if type(now) is not int or now < self._issued_ns or now - self._issued_ns > _HANDOFF_TTL_NS:
            _blocked("transport_handoff_expired")
        if _pid() != self._pid_value or _thread_id() != self._thread_value:
            _blocked("transport_handoff_custody_mismatch")
        return self._selection


def create_current_handoff(
    public_projection,
    *,
    confirm_transport_only=False,
    connector=None,
    probe_clock=None,
):
    """Run a fresh paired probe and issue a same-call, zero-authority handoff.

    A stale JSON observation is never accepted as input. The only successful
    path runs the current selector directly over the exact public projection
    bytes. The caller must explicitly confirm that this is transport-only.
    """

    if confirm_transport_only is not True:
        _blocked("explicit_transport_probe_confirmation_required")
    if type(public_projection) is not bytes:
        _blocked("public_pair_document_required")
    from scripts import ctp_000_paired_front_selector as selector

    pairs = selector.parse_document(public_projection)
    observation_started_ns = _monotonic_ns()
    try:
        value = {
            "schema": selector.SCHEMA,
            "venue": "simnow",
            "scope": "transport_only",
            "strategy_id": selector.STRATEGY,
            "front_pairs": [dict(pair) for pair in pairs],
        }
        observation = selector.observe_document(value, connector=connector, clock=probe_clock)
    except FrontHandoffError:
        raise
    except Exception:
        _blocked("current_transport_observation_unavailable")
    if type(observation) is not dict:
        _blocked("current_transport_observation_invalid")
    if observation.get("status") == "NO_CANDIDATE":
        _blocked("no_current_transport_candidate")
    selection = _selection_from_current_observation(public_projection, observation)
    issued_ns = _monotonic_ns()
    if (
        type(observation_started_ns) is not int
        or type(issued_ns) is not int
        or issued_ns < observation_started_ns
    ):
        _blocked("transport_handoff_clock_invalid")
    return OneUseTransportHandoff(
        _HANDOFF_FACTORY,
        selection,
        pid=_pid(),
        thread_id=_thread_id(),
        issued_ns=issued_ns,
    )
