"""Explicit 000 SimNow paired-front TCP diagnostic; never runtime admission.

Consumes a credential-free public JSON projection, never private config/.env.
Only --probe --confirm-transport-only can open sockets. No SDK/provider login,
MD subscription, write API, registration, deployment or G1/G4 authority exists.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path
from statistics import median
import sys
import time
from urllib.parse import urlsplit


SCHEMA = "ctp_000_paired_front_candidates.v1"
STRATEGY = "example.000_live_certification.simnow_penetration"
MAX_PAIRS = 8
ATTEMPTS = 3
TIMEOUT_SECONDS = 1.0
DEADLINE_SECONDS = 30.0
MAX_INPUT_BYTES = 8192


class SelectorError(ValueError):
    """Static redacted reason; caller document/endpoint values never included."""


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SelectorError("duplicate_json_key")
        value[key] = item
    return value


def _endpoint(value):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise SelectorError("numeric_ipv4_front_required")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        address = ipaddress.IPv4Address(host)
    except (ValueError, TypeError):
        raise SelectorError("numeric_ipv4_front_required") from None
    if (
        type(port) is not int
        or not 1 <= port <= 65535
        or value != f"tcp://{address}:{port}"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise SelectorError("numeric_ipv4_front_required")
    return value


def validate_document(value):
    if type(value) is not dict or set(value) != {
        "schema",
        "venue",
        "scope",
        "strategy_id",
        "front_pairs",
    }:
        raise SelectorError("public_pair_document_invalid")
    if (
        value["schema"] != SCHEMA
        or value["venue"] != "simnow"
        or value["scope"] != "transport_only"
        or value["strategy_id"] != STRATEGY
    ):
        raise SelectorError("explicit_000_simnow_transport_scope_required")
    pairs = value["front_pairs"]
    if type(pairs) is not list or not 1 <= len(pairs) <= MAX_PAIRS:
        raise SelectorError("pair_count_invalid")
    result = []
    seen = set()
    for pair in pairs:
        if type(pair) is not dict or set(pair) != {"md_front", "td_front"}:
            raise SelectorError("pair_shape_invalid")
        md, td = _endpoint(pair["md_front"]), _endpoint(pair["td_front"])
        if (md, td) in seen:
            raise SelectorError("duplicate_pair")
        seen.add((md, td))
        result.append({"md_front": md, "td_front": td})
    return tuple(result)


def parse_document(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise SelectorError("public_pair_document_size_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except SelectorError:
        raise
    except (ValueError, UnicodeError):
        raise SelectorError("public_pair_document_invalid") from None
    return validate_document(value)


def _probe_module():
    # Existing transport primitive only; never dispatch through 007/013_3 registry.
    from backtrader_runtime import ctp_front_pair_probe

    return ctp_front_pair_probe


def _endpoint_summary(value, expected_front, probe):
    if (
        type(value) is not probe.CtpFrontEndpointEvidence
        or value.front != expected_front
        or type(value.samples) is not tuple
        or len(value.samples) != ATTEMPTS
    ):
        raise SelectorError("probe_evidence_invalid")
    latencies = []
    for sample in value.samples:
        if type(sample) is not probe.CtpFrontProbeSample or type(sample.connected) is not bool:
            raise SelectorError("probe_evidence_invalid")
        if sample.connected:
            if type(sample.latency_ms) not in (int, float):
                raise SelectorError("probe_evidence_invalid")
            try:
                latency = float(sample.latency_ms)
            except (OverflowError, ValueError):
                raise SelectorError("probe_evidence_invalid") from None
            if not math.isfinite(latency) or latency < 0:
                raise SelectorError("probe_evidence_invalid")
            latencies.append(latency)
        elif sample.latency_ms is not None:
            raise SelectorError("probe_evidence_invalid")
    return {
        "sample_count": ATTEMPTS,
        "successes": len(latencies),
        "median_success_latency_ms": median(latencies) if latencies else None,
        "max_success_latency_ms": max(latencies) if latencies else None,
    }


def rank_evidence(pairs, evidence, probe):
    if type(evidence) is not tuple or len(evidence) != len(pairs):
        raise SelectorError("probe_evidence_invalid")
    rows, candidates = [], []
    for index, (pair, item) in enumerate(zip(pairs, evidence)):
        if (
            type(item) is not probe.CtpFrontPairEvidence
            or type(item.config_index) is not int
            or item.config_index != index
            or type(item.pair) is not probe.CtpConfiguredFrontPair
            or (item.pair.md_front, item.pair.td_front) != (pair["md_front"], pair["td_front"])
        ):
            raise SelectorError("probe_pair_identity_mismatch")
        md = _endpoint_summary(item.md, pair["md_front"], probe)
        td = _endpoint_summary(item.td, pair["td_front"], probe)
        eligible = md["successes"] >= 1 and td["successes"] >= 1
        stable = md["successes"] == td["successes"] == ATTEMPTS
        score = None
        if eligible:
            score = [max(md["median_success_latency_ms"], td["median_success_latency_ms"]), index]
            candidates.append((score, index))
        rows.append(
            {
                "config_index": index,
                "md": md,
                "td": td,
                "stable_both_3_of_3": stable,
                "eligible_both_reachable": eligible,
                "score": score,
            }
        )
    selected = min(candidates)[1] if candidates else None
    return rows, selected


def observe_document(value, *, connector=None, clock=None):
    """Explicit transport observation API. Injected seams are for inert tests."""
    pairs = validate_document(value)  # Validate every pair before probe import/call.
    probe = _probe_module()
    now = clock or time.perf_counter
    start = now()
    deadline = start + DEADLINE_SECONDS
    timed_out = False
    try:
        selection = probe.select_ctp_front_pair(
            pairs,
            timeout_seconds=TIMEOUT_SECONDS,
            max_pairs=MAX_PAIRS,
            repeated_samples=ATTEMPTS,
            connector=connector,
            clock=clock,
            deadline_monotonic=deadline,
        )
        evidence = selection.evidence
    except probe.CtpFrontPairProbeError as error:
        if error.reason not in {
            "no_configured_front_pair_reachable",
            "probe_global_deadline_exceeded",
        }:
            raise SelectorError("transport_probe_rejected") from None
        evidence = error.evidence
        timed_out = error.reason == "probe_global_deadline_exceeded"
    rows, selected = rank_evidence(pairs, evidence, probe)
    elapsed = now() - start
    if not math.isfinite(elapsed) or elapsed < 0:
        raise SelectorError("probe_clock_invalid")
    if timed_out or elapsed >= DEADLINE_SECONDS:
        selected = None
    result = _base_result(len(pairs))
    result.update(
        status="TRANSPORT_CANDIDATE" if selected is not None else "NO_CANDIDATE",
        selected_config_index=selected,
        pairs=rows,
        elapsed_seconds=round(elapsed, 6),
        deadline_observed_exceeded=timed_out or elapsed >= DEADLINE_SECONDS,
        degraded_candidate=selected is not None and not rows[selected]["stable_both_3_of_3"],
        tcp_probe_started=True,
    )
    return result


def _base_result(count):
    return {
        "schema": "ctp_000_paired_front_observation.v1",
        "strategy_id": STRATEGY,
        "venue": "simnow",
        "scope": "transport_only",
        "configured_pair_count": count,
        "planned_attempts_per_endpoint": ATTEMPTS,
        "timeout_seconds": TIMEOUT_SECONDS,
        "deadline_seconds": DEADLINE_SECONDS,
        "hard_whole_command_deadline": False,
        "score_order": [
            "worst_side_median_ms",
            "config_index",
        ],
        "tail_statistic": "maximum_successful_sample_not_percentile",
        "tcp_probe_started": False,
        "provider_login_started": False,
        "md_subscription_started": False,
        "trading_writes": 0,
        "registered_runtime_dispatched": False,
        "execution_authority": "NONE",
        "ctp_gate_status": "NO_WRITE / LIVE_NO_GO",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--probe", action="store_true")
    parser.add_argument("--pairs-json", required=True, metavar="PUBLIC_PROJECTION_JSON")
    parser.add_argument("--confirm-transport-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.probe and not args.confirm_transport_only:
            raise SelectorError("explicit_transport_probe_confirmation_required")
        path = Path(args.pairs_json)
        if path.suffix.lower() != ".json" or not path.is_absolute():
            raise SelectorError("explicit_public_json_path_required")
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        pairs = parse_document(raw)
        if args.check:
            result = _base_result(len(pairs))
            result.update(status="INPUT_VALIDATED_ONLY", selected_config_index=None)
        else:
            result = observe_document(json.loads(raw.decode("utf-8"), object_pairs_hook=_object))
        # Public endpoints-only projection digest, never private/account bytes.
        result["public_projection_sha256"] = hashlib.sha256(raw).hexdigest()
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if args.check or result["selected_config_index"] is not None else 2
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": str(error)
                    if type(error) is SelectorError
                    else "public_projection_or_probe_unavailable",
                    "execution_authority": "NONE",
                    "ctp_gate_status": "NO_WRITE / LIVE_NO_GO",
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
