"""Bounded, count-only live memory-capacity observations.

This module records object and cache counts from an already-running live
Strategy.  It does not retain event/order payloads, source rows, line values,
or provider identities, and it does not evaluate an acceptance threshold.
Call :meth:`LiveCapacitySampler.sample` from the same engine callback thread
for every requested ordinal.
"""

from __future__ import annotations

import array
import collections
import copy
import datetime as _datetime
import itertools
import time
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..linebuffer import LineBuffer
from ..stores.registered_sim import RegisteredSimStore


_UTC = _datetime.timezone.utc
MAX_CAPACITY_SAMPLES = 32
MAX_GRAPH_NODES = 100_000
MAX_GRAPH_REFERENCES = 200_000
_EMPTY_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_MISSING = object()


def _is_bounded_mapping(value: Any) -> bool:
    return type(value) is dict or type(value) is _EMPTY_MAPPING_PROXY_TYPE


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


class _GraphBudget:
    def __init__(self, max_nodes: int, max_references: int) -> None:
        self.max_nodes = max_nodes
        self.max_references = max_references
        self.references = 0
        self.complete = True
        self.issues = []

    def reference(self) -> bool:
        self.references += 1
        if self.references > self.max_references:
            self.fail("graph_reference_limit_exceeded")
            return False
        return True

    def fail(self, reason: str) -> None:
        self.complete = False
        if reason not in self.issues:
            self.issues.append(reason)


def _line_facts(line: LineBuffer) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Read one recognized LineBuffer's retained length and real capacity."""
    values = getattr(line, "array", _MISSING)
    maxlen = getattr(line, "maxlen", _MISSING)
    extrasize = getattr(line, "extrasize", _MISSING)
    if not _nonnegative_int(maxlen) or not _nonnegative_int(extrasize):
        return None, "line_capacity_fields_missing"

    if type(values) is array.array:
        if maxlen != 0:
            return None, "line_array_capacity_mismatch"
        return {
            "retained_values": len(values),
            "capacity": None,
            "bounded": False,
        }, None

    if type(values) is collections.deque:
        capacity = values.maxlen
        if type(capacity) is not int or capacity <= 0:
            return None, "line_deque_capacity_unavailable"
        if maxlen <= 0 or capacity != maxlen + extrasize:
            return None, "line_deque_capacity_mismatch"
        return {
            "retained_values": len(values),
            "capacity": capacity,
            "bounded": True,
        }, None

    return None, "line_array_type_unsupported"


def _graph_capacity_facts(
    strategy: Any,
    live_factors: Any,
    *,
    max_graph_nodes: int,
    max_graph_references: int,
) -> Tuple[Dict[str, Any], Tuple[Any, ...]]:
    """Walk only finite public graph edges and count unique LineBuffers."""
    budget = _GraphBudget(max_graph_nodes, max_graph_references)
    stack = []

    def push(value: Any) -> None:
        if value is None:
            budget.fail("graph_reference_missing")
        elif budget.reference():
            stack.append(value)

    datas = getattr(strategy, "datas", _MISSING)
    if type(datas) not in (tuple, list) or len(datas) > max_graph_references:
        budget.fail("strategy_datas_unavailable")
    else:
        for data in datas:
            push(data)
            if not budget.complete:
                break
    push(strategy)

    instances = getattr(live_factors, "factor_instances", _MISSING)
    if not _is_bounded_mapping(instances) or len(instances) > max_graph_references:
        budget.fail("factor_instances_unavailable")
    else:
        for groups in instances.values():
            if not budget.reference():
                break
            if not _is_bounded_mapping(groups) or len(groups) > max_graph_references:
                budget.fail("factor_instance_group_unavailable")
                break
            for instance in groups.values():
                push(instance)
                if not budget.complete:
                    break
            if not budget.complete:
                break

    visited = set()
    lines: Dict[int, LineBuffer] = {}
    factor_nodes = []
    value_lines = set()
    reason_lines = set()
    unobservable_line_reference_ids = set()
    unobservable_line_collection_ids = set()
    line_issues = []
    while stack and budget.complete:
        owner = stack.pop()
        owner_id = id(owner)
        if owner_id in visited:
            continue
        if len(visited) >= max_graph_nodes:
            budget.fail("graph_node_limit_exceeded")
            break
        visited.add(owner_id)
        diagnostic_projection = getattr(type(owner), "lifecycle_capacity_facts", None)
        if isinstance(diagnostic_projection, property) or callable(diagnostic_projection):
            factor_nodes.append(owner)

        getter = getattr(owner, "getindicators", None)
        if not callable(getter):
            budget.fail("indicator_graph_edge_unavailable")
            break
        try:
            children = getter()
        except Exception:
            budget.fail("indicator_graph_edge_failed")
            break
        if type(children) not in (tuple, list) or len(children) > max_graph_references:
            budget.fail("indicator_graph_edge_unavailable")
            break
        for child in children:
            push(child)
            if not budget.complete:
                break

        owner_lines = getattr(owner, "lines", _MISSING)
        if owner_lines is not _MISSING:
            raw_lines = getattr(owner_lines, "lines", _MISSING)
            if type(raw_lines) not in (tuple, list) or len(raw_lines) > max_graph_references:
                budget.fail("owner_lines_unavailable")
                unobservable_line_collection_ids.add(id(owner_lines))
                break
            aliases = ()
            alias_getter = getattr(type(owner_lines), "getlinealiases", None)
            if callable(alias_getter):
                try:
                    aliases = alias_getter()
                except Exception:
                    budget.fail("line_aliases_unavailable")
                    break
                if type(aliases) not in (tuple, list) or len(aliases) > max_graph_references:
                    budget.fail("line_aliases_unavailable")
                    break
            for index, line in enumerate(raw_lines):
                if not budget.reference():
                    break
                if not isinstance(line, LineBuffer):
                    line_issues.append("line_object_unsupported")
                    unobservable_line_reference_ids.add(id(line))
                    continue
                lines[id(line)] = line
                alias = aliases[index] if index < len(aliases) else None
                if alias == "value":
                    value_lines.add(id(line))
                elif alias == "reason":
                    reason_lines.add(id(line))

        outputs = getattr(owner, "outputs", _MISSING)
        if outputs is not _MISSING:
            if not _is_bounded_mapping(outputs) or len(outputs) > max_graph_references:
                budget.fail("factor_outputs_unavailable")
                break
            for output in outputs.values():
                if isinstance(output, LineBuffer):
                    if not budget.reference():
                        break
                    lines[id(output)] = output
                    continue
                keys_getter = getattr(output, "keys", None)
                if not callable(keys_getter):
                    line_issues.append("factor_output_unavailable")
                    unobservable_line_collection_ids.add(id(output))
                    break
                try:
                    keys = keys_getter()
                except Exception:
                    budget.fail("factor_output_keys_unavailable")
                    unobservable_line_collection_ids.add(id(output))
                    break
                is_dict_keys = type(keys) is type({}.keys()) and type(output) is dict
                if (type(keys) not in (tuple, list) and not is_dict_keys) or len(
                    keys
                ) > max_graph_references:
                    budget.fail("factor_output_keys_unavailable")
                    unobservable_line_collection_ids.add(id(output))
                    break
                for key in keys:
                    if not budget.reference():
                        break
                    try:
                        line = output[key]
                    except Exception:
                        budget.fail("factor_output_line_unavailable")
                        unobservable_line_collection_ids.add(id(output))
                        break
                    if isinstance(line, LineBuffer):
                        lines[id(line)] = line
                        if key == "value":
                            value_lines.add(id(line))
                        elif key == "reason":
                            reason_lines.add(id(line))
                    else:
                        line_issues.append("factor_output_line_unsupported")
                        unobservable_line_reference_ids.add(id(line))
                        break
                if line_issues:
                    break
            if not budget.complete:
                break

    retained_values = 0
    capacity_sum = 0
    bounded_count = 0
    unbounded_count = 0
    max_capacity = 0
    max_retained = 0
    capacity_unavailable_ids = set()
    for line in lines.values():
        facts, issue = _line_facts(line)
        if issue is not None:
            line_issues.append(issue)
            capacity_unavailable_ids.add(id(line))
            continue
        retained = facts["retained_values"]
        retained_values += retained
        max_retained = max(max_retained, retained)
        if facts["bounded"]:
            bounded_count += 1
            capacity_sum += facts["capacity"]
            max_capacity = max(max_capacity, facts["capacity"])
        else:
            unbounded_count += 1

    if line_issues:
        budget.fail(line_issues[0])
    complete = budget.complete and bool(lines) and len(lines) == bounded_count + unbounded_count
    if not lines:
        budget.fail("line_buffers_unavailable")
    facts = {
        "schema": "backtrader.live_line_capacity.v1",
        "status": "OBSERVED" if complete else "INCOMPLETE",
        "observation_complete": complete,
        "graph_node_count": len(visited),
        "graph_reference_count": budget.references,
        "line_buffer_count": len(lines),
        "bounded_line_buffer_count": bounded_count,
        "unbounded_line_buffer_count": unbounded_count,
        "line_capacity_unavailable_count": len(capacity_unavailable_ids),
        "unobservable_line_reference_count": len(unobservable_line_reference_ids),
        "unobservable_line_collection_count": len(unobservable_line_collection_ids),
        "line_capacity_sum": capacity_sum,
        "max_line_capacity": max_capacity,
        "retained_line_value_count": retained_values,
        "max_retained_values_per_line": max_retained,
        "value_line_count": len(value_lines),
        "reason_line_count": len(reason_lines),
        "issues": tuple(budget.issues),
    }
    return facts, tuple(factor_nodes)


def _cohort_capacity_facts(cohort: Any) -> Dict[str, Any]:
    method = getattr(cohort, "capacity_facts", None)
    if not callable(method):
        return {"status": "UNAVAILABLE", "reason_code": "cohort_projection_missing"}
    try:
        facts = method()
    except Exception:
        return {"status": "UNAVAILABLE", "reason_code": "cohort_projection_failed"}
    required = (
        "member_count",
        "pending_slot_count",
        "pending_bar_count",
        "max_pending_slots",
        "max_pending_bars",
        "window_receipt_count",
        "window_receipt_limit",
        "window_receipt_member_limit",
        "recent_signature_count",
        "recent_signature_order_count",
        "recent_signature_limit",
        "diagnostic_gap_count",
        "diagnostic_gap_limit",
    )
    if (
        not isinstance(facts, Mapping)
        or facts.get("schema") != "backtrader.live_cohort_capacity.v1"
        or facts.get("status") != "OBSERVED"
        or facts.get("limits_respected") is not True
        or facts.get("window_receipt_member_limits_match") is not True
        or any(not _nonnegative_int(facts.get(name)) for name in required)
    ):
        return {"status": "INCOMPLETE", "reason_code": "invalid_cohort_projection"}
    if (
        facts["pending_slot_count"] > facts["max_pending_slots"]
        or facts["pending_bar_count"] > facts["max_pending_bars"]
        or facts["window_receipt_count"] > facts["window_receipt_limit"]
        or facts["recent_signature_count"] > facts["recent_signature_limit"]
        or facts["recent_signature_order_count"] > facts["recent_signature_limit"]
        or facts["diagnostic_gap_count"] > facts["diagnostic_gap_limit"]
    ):
        return {"status": "INCOMPLETE", "reason_code": "cohort_capacity_exceeded"}
    return {
        key: facts[key]
        for key in (
            "schema",
            "status",
            *required,
            "window_receipt_member_limits_match",
            "limits_respected",
        )
    }


def _factor_diagnostic_facts(nodes: Iterable[Any], *, owners_complete: bool) -> Dict[str, Any]:
    factor_count = 0
    call_count = 0
    once_range_count = 0
    call_sample_count = 0
    once_range_sample_count = 0
    sample_limits = set()
    issues = []
    for node in nodes:
        factor_count += 1
        try:
            facts = node.lifecycle_capacity_facts
            if callable(facts):
                facts = facts()
        except Exception:
            issues.append("factor_diagnostic_projection_failed")
            continue
        if (
            not isinstance(facts, Mapping)
            or facts.get("schema") != "backtrader.factor_lifecycle_capacity.v1"
        ):
            issues.append("factor_diagnostic_projection_invalid")
            continue
        if facts.get("status") != "OBSERVED":
            issues.append("factor_diagnostics_unbounded")
            continue
        required = (
            "call_count",
            "once_range_count",
            "call_sample_count",
            "once_range_sample_count",
            "sample_limit",
        )
        if any(not _nonnegative_int(facts.get(name)) for name in required[:-1]):
            issues.append("factor_diagnostic_counts_invalid")
            continue
        sample_limit = facts.get("sample_limit")
        if (
            type(sample_limit) is not int
            or sample_limit <= 0
            or facts.get("call_samples_bounded") is not True
            or facts.get("once_range_samples_bounded") is not True
            or facts["call_sample_count"] > sample_limit
            or facts["once_range_sample_count"] > sample_limit
        ):
            issues.append("factor_diagnostic_limit_invalid")
            continue
        sample_limits.add(sample_limit)
        call_count += facts["call_count"]
        once_range_count += facts["once_range_count"]
        call_sample_count += facts["call_sample_count"]
        once_range_sample_count += facts["once_range_sample_count"]
    complete = factor_count > 0 and not issues and owners_complete
    return {
        "schema": "backtrader.live_factor_diagnostics_capacity.v1",
        "status": "OBSERVED" if complete else "INCOMPLETE",
        "factor_count": factor_count,
        "call_count": call_count,
        "once_range_count": once_range_count,
        "call_sample_count": call_sample_count,
        "once_range_sample_count": once_range_sample_count,
        "sample_limits": tuple(sorted(sample_limits)),
        "issues": tuple(issues)
        if issues
        else (() if complete else ("factor_diagnostics_unavailable",)),
    }


def _strategy_event_facts(strategy: Any) -> Dict[str, Any]:
    events = {}
    issues = []
    for name in ("order_events", "trade_events"):
        value = getattr(strategy, name, _MISSING)
        if type(value) is not collections.deque:
            issues.append("{}_ring_unavailable".format(name))
            continue
        limit = value.maxlen
        count = len(value)
        if type(limit) is not int or limit <= 0:
            issues.append("{}_ring_unbounded".format(name))
            events[name] = {"count": count, "limit": None, "bounded": False}
            continue
        if count > limit:
            issues.append("{}_ring_over_capacity".format(name))
        events[name] = {"count": count, "limit": limit, "bounded": count <= limit}

    complete = not issues and len(events) == 2
    return {
        "schema": "backtrader.live_strategy_event_capacity.v1",
        "status": "OBSERVED" if complete else "INCOMPLETE",
        "events": events,
        "issues": tuple(issues),
    }


def _order_capacity_facts(store: Any) -> Dict[str, Any]:
    if not isinstance(store, RegisteredSimStore):
        return {"status": "UNAVAILABLE", "reason_code": "registered_sim_store_required"}
    try:
        facts = store.registered_sim_order_capacity_facts()
    except Exception:
        return {"status": "UNAVAILABLE", "reason_code": "order_projection_failed"}
    if isinstance(facts, Mapping) and facts.get("status") == "UNAVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "reason_code": facts.get("reason_code")
            if isinstance(facts.get("reason_code"), str)
            else "order_projection_unavailable",
            "dispatching_order_count": facts.get("dispatching_order_count")
            if _nonnegative_int(facts.get("dispatching_order_count"))
            else None,
        }
    if not isinstance(facts, Mapping):
        return {"status": "INCOMPLETE", "reason_code": "invalid_order_projection"}
    required = (
        "active_order_count",
        "unknown_order_count",
        "terminal_order_count",
        "dispatching_order_count",
        "terminal_order_limit",
    )
    if (
        facts.get("schema") != "backtrader.registered_sim_order_capacity.v1"
        or facts.get("status") not in ("OBSERVED", "UNSTABLE_OR_OVER_CAPACITY")
        or any(not _nonnegative_int(facts.get(name)) for name in required[:-1])
        or type(facts.get("terminal_order_limit")) is not int
        or facts["terminal_order_limit"] <= 0
        or facts.get("active_unknown_limit", _MISSING) is not None
        or facts.get("active_unknown_bounded") is not False
        or facts["dispatching_order_count"] != 0
        or type(facts.get("terminal_limit_respected")) is not bool
        or facts["terminal_limit_respected"]
        != (facts["terminal_order_count"] <= facts["terminal_order_limit"])
        or (facts.get("status") == "OBSERVED") != facts["terminal_limit_respected"]
    ):
        return {"status": "INCOMPLETE", "reason_code": "invalid_order_projection"}
    projection = {
        key: facts[key]
        for key in (
            "schema",
            *required,
            "active_unknown_limit",
            "active_unknown_bounded",
            "terminal_limit_respected",
        )
    }
    if facts["status"] == "UNSTABLE_OR_OVER_CAPACITY":
        projection.update(
            {
                "status": "INCOMPLETE",
                "reason_code": "terminal_order_cap_exceeded",
            }
        )
    else:
        projection["status"] = "OBSERVED"
    return projection


class LiveCapacitySampler:
    """Keep at most 32 same-run, count-only capacity snapshots.

    ``ordinals`` is an explicit, strictly increasing checkpoint sequence.  A
    missing or out-of-order checkpoint marks the report incomplete.  Complete
    reports remain ``RECORDED_NOT_EVALUATED``; this sampler does not issue an
    AC51 result or infer growth from RSS.
    """

    def __init__(
        self,
        run_id: str,
        ordinals: Iterable[int],
        *,
        max_samples: int = 16,
        max_graph_nodes: int = MAX_GRAPH_NODES,
        max_graph_references: int = MAX_GRAPH_REFERENCES,
    ) -> None:
        if not isinstance(run_id, str) or not run_id or run_id.strip() != run_id:
            raise ValueError("run_id must be non-empty exact text")
        if type(max_samples) is not int or not 1 <= max_samples <= MAX_CAPACITY_SAMPLES:
            raise ValueError("max_samples must be between 1 and 32")
        if type(max_graph_nodes) is not int or not 1 <= max_graph_nodes <= MAX_GRAPH_NODES:
            raise ValueError("max_graph_nodes exceeds the fixed graph bound")
        if (
            type(max_graph_references) is not int
            or not 1 <= max_graph_references <= MAX_GRAPH_REFERENCES
        ):
            raise ValueError("max_graph_references exceeds the fixed reference bound")
        try:
            expected = tuple(itertools.islice(iter(ordinals), max_samples + 1))
        except (TypeError, ValueError):
            raise ValueError("ordinals must be a finite iterable of integers") from None
        if (
            not expected
            or len(expected) > max_samples
            or any(type(value) is not int or value < 0 for value in expected)
            or any(left >= right for left, right in zip(expected, expected[1:]))
        ):
            raise ValueError("ordinals must be a non-empty bounded increasing integer sequence")
        self._run_id = run_id
        self._expected_ordinals = expected
        self._max_samples = max_samples
        self._max_graph_nodes = max_graph_nodes
        self._max_graph_references = max_graph_references
        self._samples = []
        self._next_ordinal_index = 0
        self._bound_identities = None
        self._issues = []

    def sample(self, ordinal: int, *, strategy: Any, cohort: Any, store: Any) -> Mapping[str, Any]:
        """Capture one expected checkpoint from the current live run."""
        if len(self._samples) >= self._max_samples:
            self._add_issue("sample_limit_exceeded")
            return MappingProxyType(
                {"status": "INCOMPLETE", "reason_code": "sample_limit_exceeded"}
            )

        mono_before = time.monotonic_ns()
        sampled_at_utc = _datetime.datetime.now(_UTC).isoformat(timespec="microseconds")
        mono_after = time.monotonic_ns()
        valid_ordinal = type(ordinal) is int and ordinal >= 0
        row: Dict[str, Any] = {
            "schema": "backtrader.live_capacity_snapshot.v1",
            "run_id": self._run_id,
            "ordinal": ordinal if valid_ordinal else None,
            "sampled_at_utc": sampled_at_utc,
            "utc_monotonic_before_ns": mono_before,
            "utc_monotonic_after_ns": mono_after,
            "status": "INCOMPLETE",
            "acceptance_evaluated": False,
            "issues": [],
        }

        if not valid_ordinal:
            self._add_issue("invalid_ordinal")
            row["issues"].append("invalid_ordinal")
        elif self._next_ordinal_index >= len(self._expected_ordinals):
            self._add_issue("unexpected_extra_checkpoint")
            row["issues"].append("unexpected_extra_checkpoint")
        elif ordinal != self._expected_ordinals[self._next_ordinal_index]:
            self._add_issue("unexpected_checkpoint_ordinal")
            row["issues"].append("unexpected_checkpoint_ordinal")
        else:
            self._next_ordinal_index += 1

        identities = (id(strategy), id(cohort), id(store))
        if self._bound_identities is None:
            self._bound_identities = identities
        elif identities != self._bound_identities:
            self._add_issue("run_object_identity_changed")
            row["issues"].append("run_object_identity_changed")

        try:
            live_factors = getattr(strategy, "live_factors", _MISSING)
            if live_factors is _MISSING or getattr(live_factors, "cohort", None) is not cohort:
                row["cohort_identity"] = {
                    "status": "INCOMPLETE",
                    "reason_code": "run_cohort_mismatch",
                }
            else:
                cohort_id = getattr(cohort, "cohort_id", None)
                epoch_id = getattr(cohort, "epoch_id", None)
                if not isinstance(cohort_id, str) or type(epoch_id) is not int:
                    row["cohort_identity"] = {
                        "status": "INCOMPLETE",
                        "reason_code": "cohort_identity_unavailable",
                    }
                else:
                    identity = {"status": "OBSERVED", "cohort_id": cohort_id, "epoch_id": epoch_id}
                    previous = getattr(self, "_cohort_identity", None)
                    if previous is None:
                        self._cohort_identity = (cohort_id, epoch_id)
                    elif previous != (cohort_id, epoch_id):
                        identity = {"status": "INCOMPLETE", "reason_code": "cohort_epoch_changed"}
                    row["cohort_identity"] = identity

                line_facts, factor_nodes = _graph_capacity_facts(
                    strategy,
                    live_factors,
                    max_graph_nodes=self._max_graph_nodes,
                    max_graph_references=self._max_graph_references,
                )
                row["lines"] = line_facts
                row["cohort"] = _cohort_capacity_facts(cohort)
                row["diagnostics"] = _factor_diagnostic_facts(
                    factor_nodes,
                    owners_complete=line_facts["observation_complete"],
                )
            row["strategy_events"] = _strategy_event_facts(strategy)
            row["orders"] = _order_capacity_facts(store)
        except Exception:
            row["issues"].append("snapshot_projection_failed")

        if row.get("cohort_identity", {}).get("status") != "OBSERVED":
            row["issues"].append(
                row["cohort_identity"].get("reason_code", "cohort_identity_incomplete")
            )
        for key in ("lines", "cohort", "diagnostics", "strategy_events", "orders"):
            facts = row.get(key)
            if not isinstance(facts, Mapping) or facts.get("status") != "OBSERVED":
                row["issues"].append("{}_incomplete".format(key))
        if row["issues"]:
            row["status"] = "INCOMPLETE"
            self._add_issue("sample_incomplete")
        else:
            row["status"] = "OBSERVED"
        row["issues"] = tuple(dict.fromkeys(row["issues"]))
        row["capture_monotonic_ns"] = time.monotonic_ns()
        self._samples.append(copy.deepcopy(row))
        return MappingProxyType(copy.deepcopy(row))

    def _add_issue(self, issue: str) -> None:
        if issue not in self._issues:
            self._issues.append(issue)

    def report(self) -> Mapping[str, Any]:
        """Return finite observations without passing an acceptance gate."""
        issues = list(self._issues)
        if self._next_ordinal_index < len(self._expected_ordinals):
            if "checkpoint_sequence_incomplete" not in issues:
                issues.append("checkpoint_sequence_incomplete")
        if len(self._samples) != len(self._expected_ordinals):
            if "checkpoint_count_mismatch" not in issues:
                issues.append("checkpoint_count_mismatch")
        all_observed = (
            not issues
            and len(self._samples) == len(self._expected_ordinals)
            and all(sample.get("status") == "OBSERVED" for sample in self._samples)
        )
        return MappingProxyType(
            {
                "schema": "backtrader.live_capacity_report.v1",
                "run_id": self._run_id,
                "status": "RECORDED_NOT_EVALUATED" if all_observed else "INCOMPLETE",
                "acceptance_evaluated": False,
                "expected_ordinals": self._expected_ordinals,
                "sample_count": len(self._samples),
                "max_samples": self._max_samples,
                "issues": tuple(issues),
                "samples": tuple(copy.deepcopy(sample) for sample in self._samples),
            }
        )
