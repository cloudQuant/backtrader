"""Fixed service-token receipt writer dispatched only by the pinned bootstrap.

The writer is a separate short-lived Job child.  It receives immutable work
facts only after the coordinator Job has independently exited and been
observed empty.  Its receipt never claims that the writer's own Job is empty.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol


RECEIPT_BINDING_SCHEMA = "ctp_i13_i15_readonly_receipt_writer_binding.v1"
RECEIPT_OUTPUT_SCHEMA = "ctp_i13_i15_readonly_receipt_writer_output.v1"
RECEIPT_FRAME_SCHEMA = "ctp_i13_i15_readonly_receipt_writer_frame.v1"
COORDINATOR_OUTPUT_SCHEMA = "ctp_i13_i15_readonly_request_coordinator_output.v1"
SERVICE_RECEIPT_SCHEMA = "ctp_i13_i15_readonly_service_receipt.v2"
_REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
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
_CHANNEL_FIELDS = frozenset({"nonce", "server_pid"})
_JOB_FACT_FIELDS = frozenset(
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
_COORDINATOR_OUTPUT_FIELDS = frozenset(
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
_BINDING_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "deadline_monotonic_ns",
        "deployment",
        "work_result",
        "coordinator_job",
        "receipt_output_channel",
    }
)
_OUTPUT_FIELDS = frozenset(
    {"schema", "request_id", "state", "reason", "receipt_created", "receipt_sha256"}
)
_WORK_REASONS = frozenset(
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
_COORDINATOR_REASONS = frozenset(
    {
        "completed",
        "deadline_expired",
        "coordinator_cleanup_unverified",
        "coordinator_failed",
        "deployment_execution_lease_close_failed",
        "receipt_persist_failed",
        "receipt_output_failed",
    }
)
_OUTPUT_REASONS = _WORK_REASONS | _COORDINATOR_REASONS
_MAX_RECEIPT_BYTES = 64 * 1024


class ReceiptWriterError(ValueError):
    """A fixed, non-sensitive receipt contract rejection."""


@dataclass(frozen=True)
class ReceiptWriterBinding:
    request_id: str
    deadline_monotonic_ns: int
    deployment: Mapping[str, str]
    work_result: Mapping[str, object]
    coordinator_job: Mapping[str, object]
    receipt_output_channel: Mapping[str, object]


class ReceiptWriterApi(Protocol):
    """Fixed APIs supplied by the bootstrap; no wire-selected filesystem path."""

    def monotonic_ns(self) -> int: ...

    def verify_deployment(self, deployment: Mapping[str, str]) -> None: ...

    def close_execution(self) -> None:
        """Attempt child-local trust/input lease cleanup before receipt I/O."""
        ...

    def persist_fixed_receipt(self, request_id: str, raw: bytes) -> None: ...

    def write_supervisor_output(
        self, binding: ReceiptWriterBinding, output: Mapping[str, object]
    ) -> None: ...


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptWriterError("duplicate_json_key")
        result[key] = value
    return result


def _canonical_json(value, *, maximum: int = _MAX_RECEIPT_BYTES) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise ReceiptWriterError("json_value_invalid") from None
    if not raw or len(raw) > maximum:
        raise ReceiptWriterError("json_size_invalid")
    return raw


def _sha(value: object, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None or value == "0" * 64:
        raise ReceiptWriterError(reason)
    return value


def _exact_int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ReceiptWriterError("receipt_facts_invalid")
    return value


def _channel(value: object) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _CHANNEL_FIELDS:
        raise ReceiptWriterError("receipt_output_channel_invalid")
    nonce = value["nonce"]
    pid = value["server_pid"]
    if (
        type(nonce) is not str
        or _REQUEST_ID_RE.fullmatch(nonce) is None
        or type(pid) is not int
        or pid <= 0
    ):
        raise ReceiptWriterError("receipt_output_channel_invalid")
    return MappingProxyType({"nonce": nonce, "server_pid": pid})


def _job_facts(value: object) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _JOB_FACT_FIELDS:
        raise ReceiptWriterError("receipt_facts_invalid")
    for key in (
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "job_termination_requested",
        "job_empty_observed",
        "controls_retained",
    ):
        if type(value[key]) is not bool:
            raise ReceiptWriterError("receipt_facts_invalid")
    for key in ("job_termination_call_succeeded",):
        if value[key] is not None and type(value[key]) is not bool:
            raise ReceiptWriterError("receipt_facts_invalid")
    code = value["launcher_exit_code"]
    if code is not None and type(code) is not int:
        raise ReceiptWriterError("receipt_facts_invalid")
    if value["launcher_exit_observed"] != (code is not None):
        raise ReceiptWriterError("receipt_facts_invalid")
    if type(value["containment"]) is not str or value["containment"] not in {
        "verified",
        "unknown",
        "not_started",
    }:
        raise ReceiptWriterError("receipt_facts_invalid")
    if value["job_assignment_observed"] and not value["process_created"]:
        raise ReceiptWriterError("receipt_facts_invalid")
    if value["launcher_resumed"] and not value["job_assignment_observed"]:
        raise ReceiptWriterError("receipt_facts_invalid")
    if value["job_empty_observed"] and not value["launcher_exit_observed"]:
        raise ReceiptWriterError("receipt_facts_invalid")
    return MappingProxyType(dict(value))


def _worker_summary(value: object) -> dict:
    if type(value) is not dict or set(value) != _WORKER_SUMMARY_FIELDS:
        raise ReceiptWriterError("work_result_invalid")
    if value["schema"] != _WORKER_SUMMARY_SCHEMA:
        raise ReceiptWriterError("work_result_invalid")
    identity = value["identity"]
    if type(identity) is not dict or set(identity) != _WORKER_IDENTITY_FIELDS:
        raise ReceiptWriterError("work_result_invalid")
    if (
        identity["account_scope"] != "redacted"
        or identity["provider"] != "ctp"
        or identity["environment"] != "simnow"
        or type(identity["trading_day"]) is not str
        or re.fullmatch(r"[0-9]{8}", identity["trading_day"]) is None
        or type(identity["connection_generation"]) is not int
        or identity["connection_generation"] <= 0
    ):
        raise ReceiptWriterError("work_result_invalid")
    _sha(value["snapshot_sha256"], "work_result_invalid")
    digests = value["query_digests"]
    if type(digests) is not list or len(digests) != len(_WORKER_QUERY_NAMES):
        raise ReceiptWriterError("work_result_invalid")
    names = []
    for pair in digests:
        if (
            type(pair) is not list
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
        ):
            raise ReceiptWriterError("work_result_invalid")
        _sha(pair[1], "work_result_invalid")
        names.append(pair[0])
    if tuple(names) != _WORKER_QUERY_NAMES:
        raise ReceiptWriterError("work_result_invalid")
    _canonical_json(value)
    return value


def _work_result(value: object, request_id: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _COORDINATOR_OUTPUT_FIELDS:
        raise ReceiptWriterError("work_result_invalid")
    if value["schema"] != COORDINATOR_OUTPUT_SCHEMA or value["request_id"] != request_id:
        raise ReceiptWriterError("work_result_invalid")
    state = value["state"]
    reason = value["reason"]
    if type(state) is not str or state not in {"observed", "unknown"} or type(reason) is not str:
        raise ReceiptWriterError("work_result_invalid")
    if reason not in _WORK_REASONS or (state == "observed") != (reason == "completed"):
        raise ReceiptWriterError("work_result_invalid")
    facts = _job_facts(value["worker_facts"])
    observation = value["worker_observation"]
    if observation is not None:
        observation = _worker_summary(observation)
    if state == "observed" and (
        observation is None
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
        raise ReceiptWriterError("work_result_success_unproven")
    return MappingProxyType(
        {
            "schema": COORDINATOR_OUTPUT_SCHEMA,
            "request_id": request_id,
            "state": state,
            "reason": reason,
            "worker_observation": observation,
            "worker_facts": facts,
        }
    )


def parse_receipt_writer_binding(value: object) -> ReceiptWriterBinding:
    if type(value) is not dict or set(value) != _BINDING_FIELDS:
        raise ReceiptWriterError("receipt_binding_fields_invalid")
    if value["schema"] != RECEIPT_BINDING_SCHEMA:
        raise ReceiptWriterError("receipt_binding_schema_invalid")
    request_id = value["request_id"]
    if type(request_id) is not str or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise ReceiptWriterError("request_id_invalid")
    deadline = _exact_int(value["deadline_monotonic_ns"], minimum=1)
    deployment = value["deployment"]
    if type(deployment) is not dict or set(deployment) != _DEPLOYMENT_FIELDS:
        raise ReceiptWriterError("deployment_binding_invalid")
    deployment_value = {
        key: _sha(deployment[key], "deployment_binding_invalid")
        for key in sorted(_DEPLOYMENT_FIELDS)
    }
    coordinator_job = _job_facts(value["coordinator_job"])
    if not (
        coordinator_job["process_created"] is True
        and coordinator_job["job_assignment_observed"] is True
        and coordinator_job["launcher_exit_observed"] is True
        and coordinator_job["job_empty_observed"] is True
        and coordinator_job["containment"] == "verified"
        and coordinator_job["controls_retained"] is False
    ):
        # The receipt child may only be launched after the supervisor has
        # independently observed the prior request Job as empty.  It may
        # persist UNKNOWN work after cleanup, but cannot manufacture cleanup
        # evidence or run while an earlier process tree may still be active.
        raise ReceiptWriterError("coordinator_cleanup_unverified")
    return ReceiptWriterBinding(
        request_id=request_id,
        deadline_monotonic_ns=deadline,
        deployment=MappingProxyType(deployment_value),
        work_result=_work_result(value["work_result"], request_id),
        coordinator_job=coordinator_job,
        receipt_output_channel=_channel(value["receipt_output_channel"]),
    )


def parse_receipt_writer_output(value: object, *, expected_request_id: str) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != _OUTPUT_FIELDS:
        raise ReceiptWriterError("receipt_output_fields_invalid")
    if (
        value["schema"] != RECEIPT_OUTPUT_SCHEMA
        or type(expected_request_id) is not str
        or _REQUEST_ID_RE.fullmatch(expected_request_id) is None
        or value["request_id"] != expected_request_id
    ):
        raise ReceiptWriterError("receipt_output_binding_invalid")
    state = value["state"]
    reason = value["reason"]
    created = value["receipt_created"]
    digest = value["receipt_sha256"]
    if (
        type(state) is not str
        or state not in {"observed", "unknown"}
        or type(reason) is not str
        or reason not in _OUTPUT_REASONS
        or type(created) is not bool
    ):
        raise ReceiptWriterError("receipt_output_invalid")
    if created:
        _sha(digest, "receipt_output_digest_invalid")
    elif digest is not None:
        raise ReceiptWriterError("receipt_output_digest_invalid")
    if state == "observed" and (reason != "completed" or not created):
        raise ReceiptWriterError("receipt_output_success_unproven")
    if state == "unknown" and reason == "completed":
        raise ReceiptWriterError("receipt_output_invalid")
    return MappingProxyType(dict(value))


def encode_receipt_writer_frame(
    value: Mapping[str, object], *, request_id: str, nonce: str
) -> bytes:
    """Encode the service-only transport envelope for one receipt result."""

    if type(nonce) is not str or _REQUEST_ID_RE.fullmatch(nonce) is None:
        raise ReceiptWriterError("receipt_output_channel_invalid")
    output = parse_receipt_writer_output(dict(value), expected_request_id=request_id)
    return _canonical_json(
        {
            "schema": RECEIPT_FRAME_SCHEMA,
            "request_id": request_id,
            "nonce": nonce,
            "receipt_writer_output": dict(output),
        }
    )


def parse_receipt_writer_frame(
    raw: bytes, *, expected_request_id: str, expected_nonce: str
) -> Mapping[str, object]:
    """Validate one channel-bound receipt-writer frame and nested result."""

    if type(raw) is not bytes or not raw or len(raw) > _MAX_RECEIPT_BYTES:
        raise ReceiptWriterError("receipt_frame_size_invalid")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_pairs)
    except ReceiptWriterError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ReceiptWriterError("receipt_frame_invalid") from None
    if type(value) is not dict or set(value) != {
        "schema",
        "request_id",
        "nonce",
        "receipt_writer_output",
    }:
        raise ReceiptWriterError("receipt_frame_fields_invalid")
    if (
        _canonical_json(value) != raw
        or value["schema"] != RECEIPT_FRAME_SCHEMA
        or type(expected_request_id) is not str
        or _REQUEST_ID_RE.fullmatch(expected_request_id) is None
        or value["request_id"] != expected_request_id
        or type(expected_nonce) is not str
        or _REQUEST_ID_RE.fullmatch(expected_nonce) is None
        or value["nonce"] != expected_nonce
    ):
        raise ReceiptWriterError("receipt_frame_binding_invalid")
    return parse_receipt_writer_output(
        value["receipt_writer_output"], expected_request_id=expected_request_id
    )


def _receipt_state(binding: ReceiptWriterBinding) -> tuple[str, str]:
    if binding.work_result["state"] == "unknown":
        return "unknown", str(binding.work_result["reason"])
    facts = binding.coordinator_job
    if not (
        facts["process_created"] is True
        and facts["job_assignment_observed"] is True
        and facts["launcher_resumed"] is True
        and facts["launcher_exit_observed"] is True
        and facts["launcher_exit_code"] == 0
        and facts["job_termination_requested"] is False
        and facts["job_empty_observed"] is True
        and facts["containment"] == "verified"
        and facts["controls_retained"] is False
    ):
        return "unknown", "coordinator_cleanup_unverified"
    return "observed", "completed"


def _receipt_payload(binding: ReceiptWriterBinding) -> tuple[dict, str, str]:
    state, reason = _receipt_state(binding)
    payload = {
        "schema": SERVICE_RECEIPT_SCHEMA,
        "operation": "ctp_readonly_preflight",
        "request_id": binding.request_id,
        "state": state,
        "reason": reason,
        "worker_observation": binding.work_result["worker_observation"],
        "worker_facts": dict(binding.work_result["worker_facts"]),
        "coordinator_job": dict(binding.coordinator_job),
    }
    return payload, state, reason


def run_receipt_writer(binding_value: object, *, api: ReceiptWriterApi) -> int:
    """Persist one fixed receipt under the same absolute request deadline."""

    binding = parse_receipt_writer_binding(binding_value)
    output = {
        "schema": RECEIPT_OUTPUT_SCHEMA,
        "request_id": binding.request_id,
        "state": "unknown",
        "reason": "receipt_persist_failed",
        "receipt_created": False,
        "receipt_sha256": None,
    }
    now_ns = api.monotonic_ns()
    if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
        return 2
    try:
        api.verify_deployment(binding.deployment)
        payload, state, reason = _receipt_payload(binding)
        close_error = None
        try:
            api.close_execution()
        except Exception:
            close_error = "deployment_execution_lease_close_failed"
        if close_error is not None:
            state = "unknown"
            reason = close_error
            payload = dict(payload)
            payload["state"] = state
            payload["reason"] = reason
        raw = _canonical_json(payload)
        now_ns = api.monotonic_ns()
        if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
            return 2
        api.persist_fixed_receipt(binding.request_id, raw)
        output = {
            "schema": RECEIPT_OUTPUT_SCHEMA,
            "request_id": binding.request_id,
            "state": state,
            "reason": reason,
            "receipt_created": True,
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        }
    except Exception:
        output["state"] = "unknown"
        output["reason"] = "receipt_persist_failed"
        output["receipt_created"] = False
        output["receipt_sha256"] = None
    now_ns = api.monotonic_ns()
    if type(now_ns) is not int or now_ns < 0 or now_ns >= binding.deadline_monotonic_ns:
        return 2
    api.write_supervisor_output(binding, MappingProxyType(dict(output)))
    return 0 if output["state"] == "observed" else 2


def main(binding: object, runtime: ReceiptWriterApi) -> int:
    """Fixed-bootstrap entrypoint; all filesystem authority stays in runtime."""

    return run_receipt_writer(binding, api=runtime)


__all__ = [
    "RECEIPT_BINDING_SCHEMA",
    "RECEIPT_OUTPUT_SCHEMA",
    "RECEIPT_FRAME_SCHEMA",
    "SERVICE_RECEIPT_SCHEMA",
    "ReceiptWriterBinding",
    "ReceiptWriterError",
    "parse_receipt_writer_binding",
    "parse_receipt_writer_output",
    "encode_receipt_writer_frame",
    "parse_receipt_writer_frame",
    "run_receipt_writer",
    "main",
]
