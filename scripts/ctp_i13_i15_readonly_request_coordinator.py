"""Fixed, bootstrap-dispatched coordinator for one inert read-only request.

This file is a data-only I13 source entry.  It is never imported by the
runtime finder and must only be compiled from the retained source lease by
the fixed bootstrap.  The production runtime object is built by that
bootstrap from code-owned APIs; no callback or path is accepted in the wire
binding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol


COORDINATOR_BINDING_SCHEMA = "ctp_i13_i15_readonly_request_coordinator_binding.v1"
COORDINATOR_OUTPUT_SCHEMA = "ctp_i13_i15_readonly_request_coordinator_output.v1"
COORDINATOR_FRAME_SCHEMA = "ctp_i13_i15_readonly_request_coordinator_frame.v1"
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,14}[0-9]+\Z")
_SERVICE_SID_RE = re.compile(r"S-1-5-80-(?:[0-9]+-){4}[0-9]+\Z")
_REASONS = frozenset(
    {
        "completed",
        "deadline_expired",
        "deployment_binding_mismatch",
        "owner_token_invalid",
        "owner_token_session_failed",
        "worker_output_invalid",
        "worker_launch_failed",
        "worker_cleanup_unverified",
        "worker_source_invalid",
        "worker_failed",
        "supervisor_channel_failed",
    }
)
_DEPLOYMENT_FIELDS = frozenset(
    {
        "descriptor_sha256",
        "source_manifest_sha256",
        "runtime_manifest_sha256",
        "dependency_manifest_sha256",
        "python_sha256",
        "i13_pin_sha256",
        "i15_pin_sha256",
        "bootstrap_sha256",
        "worker_sha256",
        "coordinator_sha256",
        "receipt_writer_sha256",
        "token_bootstrap_sha256",
    }
)
_IDENTITY_FIELDS = frozenset({"service_sid", "owner_sid"})
_CHANNEL_FIELDS = frozenset({"nonce", "server_pid"})
_BINDING_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "deadline_monotonic_ns",
        "deployment",
        "identities",
        "supervisor_output_channel",
        "token_control_channel",
    }
)
_WORKER_FACT_FIELDS = frozenset(
    {
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "launcher_exit_code",
        "job_termination_requested",
        "job_termination_call_succeeded",
        "job_empty_observed",
        "containment",
        "controls_retained",
    }
)
_OUTPUT_FIELDS = frozenset(
    {"schema", "request_id", "state", "reason", "worker_observation", "worker_facts"}
)
_WORKER_SUMMARY_SCHEMA = "ctp_i13_i15_readonly_worker_summary.v1"
_WORKER_IDENTITY_FIELDS = frozenset(
    {"account_scope", "provider", "environment", "trading_day", "connection_generation"}
)
_WORKER_QUERY_NAMES = (
    "account",
    "commission_rates",
    "instruments",
    "margin_rates",
    "orders",
    "positions",
    "trades",
)
_WORKER_SUMMARY_FIELDS = frozenset({"schema", "identity", "query_digests", "snapshot_sha256"})
_OUTPUT_LIMIT = 64 * 1024


class CoordinatorError(ValueError):
    """A fixed, non-sensitive coordinator contract rejection."""


@dataclass(frozen=True)
class CoordinatorBinding:
    request_id: str
    deadline_monotonic_ns: int
    deployment: Mapping[str, str]
    service_sid: str
    owner_sid: str
    supervisor_output_channel: Mapping[str, object]
    token_control_channel: Mapping[str, object]


class CoordinatorApi(Protocol):
    """Internal methods supplied only by the fixed bootstrap runtime."""

    def monotonic_ns(self) -> int: ...

    def verify_deployment(self, deployment: Mapping[str, str]) -> None: ...

    def receive_and_set_owner_token_session_zero(self, binding: CoordinatorBinding) -> None: ...

    def run_fixed_worker(self, binding: CoordinatorBinding) -> tuple[object, object]:
        """Return a redacted worker summary and OS-supervised worker facts."""
        ...

    def write_supervisor_output(
        self, binding: CoordinatorBinding, output: Mapping[str, object]
    ) -> None: ...


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoordinatorError("duplicate_json_key")
        result[key] = value
    return result


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _canonical_json(value, *, maximum: int = _OUTPUT_LIMIT) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise CoordinatorError("json_value_invalid") from None
    if not raw or len(raw) > maximum:
        raise CoordinatorError("json_size_invalid")
    return raw


def _parse_canonical_object(raw: bytes, *, maximum: int = _OUTPUT_LIMIT) -> dict:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise CoordinatorError("json_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_pairs)
    except CoordinatorError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise CoordinatorError("json_invalid") from None
    if type(value) is not dict or _canonical_json(value, maximum=maximum) != raw:
        raise CoordinatorError("json_not_canonical")
    return value


def _exact_positive_int(value: object, reason: str) -> int:
    if type(value) is not int or value <= 0:
        raise CoordinatorError(reason)
    return value


def _exact_sha(value: object, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None or value == "0" * 64:
        raise CoordinatorError(reason)
    return value


def _channel(value: object, reason: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _CHANNEL_FIELDS:
        raise CoordinatorError(reason)
    nonce = value["nonce"]
    if type(nonce) is not str or _REQUEST_ID_RE.fullmatch(nonce) is None:
        raise CoordinatorError(reason)
    pid = _exact_positive_int(value["server_pid"], reason)
    return MappingProxyType({"nonce": nonce, "server_pid": pid})


def parse_coordinator_binding(value: object) -> CoordinatorBinding:
    """Validate a bootstrap-created binding; caller data alone grants no trust."""

    if type(value) is not dict or set(value) != _BINDING_FIELDS:
        raise CoordinatorError("coordinator_binding_fields_invalid")
    if value["schema"] != COORDINATOR_BINDING_SCHEMA:
        raise CoordinatorError("coordinator_binding_schema_invalid")
    request_id = value["request_id"]
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise CoordinatorError("request_id_invalid")
    deadline = _exact_positive_int(value["deadline_monotonic_ns"], "deadline_invalid")
    deployment = value["deployment"]
    if type(deployment) is not dict or set(deployment) != _DEPLOYMENT_FIELDS:
        raise CoordinatorError("deployment_binding_invalid")
    validated_deployment = {
        name: _exact_sha(deployment[name], "deployment_binding_invalid")
        for name in sorted(_DEPLOYMENT_FIELDS)
    }
    identities = value["identities"]
    if type(identities) is not dict or set(identities) != _IDENTITY_FIELDS:
        raise CoordinatorError("request_identity_invalid")
    service_sid = identities["service_sid"]
    owner_sid = identities["owner_sid"]
    if (
        type(service_sid) is not str
        or _SERVICE_SID_RE.fullmatch(service_sid) is None
        or type(owner_sid) is not str
        or _SID_RE.fullmatch(owner_sid) is None
        or service_sid == owner_sid
    ):
        raise CoordinatorError("request_identity_invalid")
    return CoordinatorBinding(
        request_id=request_id,
        deadline_monotonic_ns=deadline,
        deployment=MappingProxyType(validated_deployment),
        service_sid=service_sid,
        owner_sid=owner_sid,
        supervisor_output_channel=_channel(
            value["supervisor_output_channel"], "supervisor_channel_invalid"
        ),
        token_control_channel=_channel(value["token_control_channel"], "token_channel_invalid"),
    )


def _worker_facts(value: object) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _WORKER_FACT_FIELDS:
        raise CoordinatorError("worker_facts_invalid")
    for name in (
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "job_termination_requested",
        "job_empty_observed",
        "controls_retained",
    ):
        if type(value[name]) is not bool:
            raise CoordinatorError("worker_facts_invalid")
    for name in ("job_termination_call_succeeded",):
        if value[name] is not None and type(value[name]) is not bool:
            raise CoordinatorError("worker_facts_invalid")
    code = value["launcher_exit_code"]
    if code is not None and type(code) is not int:
        raise CoordinatorError("worker_facts_invalid")
    if value["launcher_exit_observed"] != (code is not None):
        raise CoordinatorError("worker_facts_invalid")
    if type(value["containment"]) is not str or value["containment"] not in {
        "verified",
        "unknown",
        "not_started",
    }:
        raise CoordinatorError("worker_facts_invalid")
    if value["job_assignment_observed"] and not value["process_created"]:
        raise CoordinatorError("worker_facts_invalid")
    if value["launcher_resumed"] and not value["job_assignment_observed"]:
        raise CoordinatorError("worker_facts_invalid")
    if not value["process_created"] and any(
        value[name]
        for name in (
            "job_assignment_observed",
            "launcher_resumed",
            "launcher_exit_observed",
            "job_termination_requested",
            "job_empty_observed",
        )
    ):
        raise CoordinatorError("worker_facts_invalid")
    if value["job_empty_observed"] and not value["launcher_exit_observed"]:
        raise CoordinatorError("worker_facts_invalid")
    return MappingProxyType(dict(value))


def _worker_summary(value: object) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _WORKER_SUMMARY_FIELDS:
        raise CoordinatorError("worker_observation_invalid")
    if value["schema"] != _WORKER_SUMMARY_SCHEMA:
        raise CoordinatorError("worker_observation_invalid")
    identity = value["identity"]
    if type(identity) is not dict or set(identity) != _WORKER_IDENTITY_FIELDS:
        raise CoordinatorError("worker_observation_invalid")
    if (
        identity["account_scope"] != "redacted"
        or identity["provider"] != "ctp"
        or identity["environment"] != "simnow"
        or type(identity["trading_day"]) is not str
        or re.fullmatch(r"[0-9]{8}", identity["trading_day"]) is None
        or type(identity["connection_generation"]) is not int
        or identity["connection_generation"] <= 0
    ):
        raise CoordinatorError("worker_observation_invalid")
    _exact_sha(value["snapshot_sha256"], "worker_observation_invalid")
    digests = value["query_digests"]
    if type(digests) is not list or len(digests) != len(_WORKER_QUERY_NAMES):
        raise CoordinatorError("worker_observation_invalid")
    names = []
    for pair in digests:
        if (
            type(pair) is not list
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            or not _SHA256_RE.fullmatch(pair[1])
            or pair[1] == "0" * 64
        ):
            raise CoordinatorError("worker_observation_invalid")
        names.append(pair[0])
    if tuple(names) != _WORKER_QUERY_NAMES:
        raise CoordinatorError("worker_observation_invalid")
    _canonical_json(value)
    return _freeze(value)


def parse_coordinator_output(value: object, *, expected_request_id: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _OUTPUT_FIELDS:
        raise CoordinatorError("coordinator_output_fields_invalid")
    if value["schema"] != COORDINATOR_OUTPUT_SCHEMA:
        raise CoordinatorError("coordinator_output_schema_invalid")
    if value["request_id"] != expected_request_id:
        raise CoordinatorError("coordinator_output_request_mismatch")
    state = value["state"]
    reason = value["reason"]
    if (
        type(state) is not str
        or state not in {"observed", "unknown"}
        or type(reason) is not str
        or reason not in _REASONS
    ):
        raise CoordinatorError("coordinator_output_state_invalid")
    facts = _worker_facts(value["worker_facts"])
    observation = value["worker_observation"]
    if observation is not None:
        observation = _worker_summary(observation)
    if state == "observed":
        if (
            reason != "completed"
            or observation is None
            or facts["process_created"] is not True
            or facts["job_assignment_observed"] is not True
            or facts["launcher_resumed"] is not True
            or facts["launcher_exit_observed"] is not True
            or facts["launcher_exit_code"] != 0
            or facts["job_termination_requested"] is not False
            or facts["job_empty_observed"] is not True
            or facts["containment"] != "verified"
            or facts["controls_retained"] is not False
        ):
            raise CoordinatorError("coordinator_output_success_unproven")
    elif reason == "completed":
        raise CoordinatorError("coordinator_output_state_invalid")
    return _freeze(
        {
            "schema": COORDINATOR_OUTPUT_SCHEMA,
            "request_id": expected_request_id,
            "state": state,
            "reason": reason,
            "worker_observation": _thaw(observation) if observation is not None else None,
            "worker_facts": dict(facts),
        }
    )


def encode_coordinator_output(value: Mapping[str, object], *, request_id: str) -> bytes:
    parsed = parse_coordinator_output(dict(value), expected_request_id=request_id)
    return _canonical_json(_thaw(parsed))


def encode_coordinator_frame(
    value: Mapping[str, object], *, request_id: str, nonce: str
) -> bytes:
    """Encode the service-only transport envelope for one coordinator result."""

    if type(nonce) is not str or _REQUEST_ID_RE.fullmatch(nonce) is None:
        raise CoordinatorError("supervisor_channel_invalid")
    output = parse_coordinator_output(dict(value), expected_request_id=request_id)
    return _canonical_json(
        {
            "schema": COORDINATOR_FRAME_SCHEMA,
            "request_id": request_id,
            "nonce": nonce,
            "coordinator_output": _thaw(output),
        }
    )


def parse_coordinator_frame(
    raw: bytes, *, expected_request_id: str, expected_nonce: str
) -> Mapping[str, object]:
    """Validate one channel-bound coordinator frame and its nested payload."""

    value = _parse_canonical_object(raw)
    if set(value) != {"schema", "request_id", "nonce", "coordinator_output"}:
        raise CoordinatorError("coordinator_frame_fields_invalid")
    if (
        value["schema"] != COORDINATOR_FRAME_SCHEMA
        or type(expected_request_id) is not str
        or _REQUEST_ID_RE.fullmatch(expected_request_id) is None
        or value["request_id"] != expected_request_id
        or type(expected_nonce) is not str
        or _REQUEST_ID_RE.fullmatch(expected_nonce) is None
        or value["nonce"] != expected_nonce
    ):
        raise CoordinatorError("coordinator_frame_binding_invalid")
    return parse_coordinator_output(
        value["coordinator_output"], expected_request_id=expected_request_id
    )


def _unknown_output(request_id: str, reason: str) -> Mapping[str, object]:
    if reason not in _REASONS or reason == "completed":
        reason = "worker_failed"
    return _freeze(
        {
            "schema": COORDINATOR_OUTPUT_SCHEMA,
            "request_id": request_id,
            "state": "unknown",
            "reason": reason,
            "worker_observation": None,
            "worker_facts": {
                "process_created": False,
                "job_assignment_observed": False,
                "launcher_resumed": False,
                "launcher_exit_observed": False,
                "launcher_exit_code": None,
                "job_termination_requested": False,
                "job_termination_call_succeeded": None,
                "job_empty_observed": False,
                "containment": "not_started",
                "controls_retained": False,
            },
        }
    )


def run_request_coordinator(binding_value: object, *, api: CoordinatorApi) -> int:
    """Run one fixed inert request through bootstrap-owned OS adapters.

    This function does not choose paths, load configuration or construct a
    backend.  Those operations are supplied by the sealed bootstrap runtime.
    An ordinary adapter failure produces an UNKNOWN frame.  Fatal identity
    cleanup exceptions deliberately escape so the containing Job is killed.
    """

    binding = parse_coordinator_binding(binding_value)
    output = _unknown_output(binding.request_id, "worker_failed")
    now_ns = api.monotonic_ns()
    if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
        return 2
    try:
        api.verify_deployment(binding.deployment)
        api.receive_and_set_owner_token_session_zero(binding)
        now_ns = api.monotonic_ns()
        if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
            return 2
        observation, facts = api.run_fixed_worker(binding)
        candidate = {
            "schema": COORDINATOR_OUTPUT_SCHEMA,
            "request_id": binding.request_id,
            "state": "observed",
            "reason": "completed",
            "worker_observation": observation,
            "worker_facts": facts,
        }
        output = parse_coordinator_output(candidate, expected_request_id=binding.request_id)
    except Exception:
        output = _unknown_output(binding.request_id, "worker_failed")
    now_ns = api.monotonic_ns()
    if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
        return 2
    api.write_supervisor_output(binding, output)
    return 0 if output["state"] == "observed" else 2


def main(binding: object, runtime: CoordinatorApi) -> int:
    """Fixed-bootstrap entrypoint; ``runtime`` is never read from the binding."""

    return run_request_coordinator(binding, api=runtime)


__all__ = [
    "COORDINATOR_BINDING_SCHEMA",
    "COORDINATOR_OUTPUT_SCHEMA",
    "COORDINATOR_FRAME_SCHEMA",
    "CoordinatorBinding",
    "CoordinatorError",
    "parse_coordinator_binding",
    "parse_coordinator_output",
    "encode_coordinator_output",
    "encode_coordinator_frame",
    "parse_coordinator_frame",
    "run_request_coordinator",
    "main",
]
