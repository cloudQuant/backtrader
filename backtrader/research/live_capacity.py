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
import math
import os
import time
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..feed import AbstractDataBase
from ..linebuffer import LineBuffer
from ..stores.registered_sim import RegisteredSimStore


_UTC = _datetime.timezone.utc
MAX_CAPACITY_SAMPLES = 32
MAX_RUN_CAPACITY_SAMPLES = 16
MAX_RUN_CAPACITY_TARGETS = 256
MAX_RUN_CAPACITY_QUALITY_FLAGS = 16
MAX_GRAPH_NODES = 100_000
MAX_GRAPH_REFERENCES = 200_000
_EMPTY_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_MISSING = object()


def _is_bounded_mapping(value: Any) -> bool:
    return type(value) is dict or type(value) is _EMPTY_MAPPING_PROXY_TYPE


def _live_ready_members_complete(strategy: Any, batch: Any) -> bool:
    target_ids = getattr(strategy, "_target_ids", None)
    members = getattr(batch, "members", None)
    if (
        type(target_ids) is not tuple
        or not target_ids
        or len(target_ids) > MAX_RUN_CAPACITY_TARGETS
        or any(type(target_id) is not str or not target_id for target_id in target_ids)
        or len(set(target_ids)) != len(target_ids)
        or not _is_bounded_mapping(members)
        or len(members) > MAX_RUN_CAPACITY_TARGETS
        or set(members) != set(target_ids)
    ):
        return False
    for receipt in members.values():
        envelope = getattr(receipt, "envelope", None)
        missing_fields = getattr(envelope, "missing_fields", None)
        quality_flags = getattr(envelope, "quality_flags", None)
        if (
            getattr(envelope, "source_role", None) != "live"
            or getattr(envelope, "complete", None) is not True
            or getattr(envelope, "quality", None) != "GOOD"
            or getattr(envelope, "present", None) is not True
            or type(missing_fields) is not tuple
            or missing_fields
            or type(quality_flags) is not tuple
            or len(quality_flags) > MAX_RUN_CAPACITY_QUALITY_FLAGS
            or not set(quality_flags).issubset({"LEGACY_SCHEMA"})
        ):
            return False
    return True


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


def _feed_filter_state_supported(feed: AbstractDataBase) -> bool:
    """Accept only an unfiltered, non-resampled feed with empty filter queues."""
    filters = getattr(feed, "_filters", _MISSING)
    final_filters = getattr(feed, "_ffilters", _MISSING)
    barstack = getattr(feed, "_barstack", _MISSING)
    barstash = getattr(feed, "_barstash", _MISSING)
    return (
        type(filters) is list
        and not filters
        and type(final_filters) is list
        and not final_filters
        and type(barstack) is collections.deque
        and not barstack
        and type(barstash) is collections.deque
        and not barstash
        and type(getattr(feed, "resampling", _MISSING)) is int
        and getattr(feed, "resampling", _MISSING) == 0
        and type(getattr(feed, "replaying", _MISSING)) is int
        and getattr(feed, "replaying", _MISSING) == 0
        and not callable(getattr(feed, "getindicators", None))
    )


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

        if isinstance(owner, AbstractDataBase):
            # Standard feeds are leaves in the indicator graph. Their real
            # LineBuffers are still counted below; filters and resampling can
            # own additional retained state, so only the explicit empty state
            # is observable by this count-only projection.
            if not _feed_filter_state_supported(owner):
                budget.fail("feed_filter_or_resampling_state_unsupported")
            children = ()
        else:
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
    bounded_retained_values = 0
    unbounded_retained_values = 0
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
            bounded_retained_values += retained
            capacity_sum += facts["capacity"]
            max_capacity = max(max_capacity, facts["capacity"])
        else:
            unbounded_count += 1
            unbounded_retained_values += retained

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
        "graph_node_limit": max_graph_nodes,
        "graph_reference_limit": max_graph_references,
        "line_buffer_count": len(lines),
        "bounded_line_buffer_count": bounded_count,
        "unbounded_line_buffer_count": unbounded_count,
        "line_capacity_unavailable_count": len(capacity_unavailable_ids),
        "unobservable_line_reference_count": len(unobservable_line_reference_ids),
        "unobservable_line_collection_count": len(unobservable_line_collection_ids),
        "line_capacity_sum": capacity_sum,
        "max_line_capacity": max_capacity,
        "retained_line_value_count": retained_values,
        "bounded_retained_line_value_count": bounded_retained_values,
        "unbounded_retained_line_value_count": unbounded_retained_values,
        "retained_line_value_count_status": "OBSERVED" if complete else "INCOMPLETE",
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


class LiveCapacityRunCapture:
    """Bind bounded count snapshots to verified Alpha003 live boundaries.

    The first observed complete ``LIVE_READY`` engine callback starts a
    finite, evenly spaced sequence of cohort-calendar slot checkpoints.  The
    callback supplies only identities already checked by the Strategy; this
    class rechecks them against the current run/cohort/batch before sampling.
    Reports are evidence only and never evaluate stability, growth, RSS, or an
    acceptance threshold.
    """

    def __init__(
        self,
        run_id: str,
        *,
        epoch_id: int,
        calendar_id: str,
        calendar_slot_count: int,
        process_id: Optional[int],
        process_create_time: Optional[float],
        max_samples: int = MAX_RUN_CAPACITY_SAMPLES,
        process_identity_issue: Optional[str] = None,
    ) -> None:
        if not isinstance(run_id, str) or not run_id or run_id.strip() != run_id:
            raise ValueError("run_id must be non-empty exact text")
        if type(epoch_id) is not int or epoch_id <= 0:
            raise ValueError("epoch_id must be a positive integer")
        if not isinstance(calendar_id, str) or not calendar_id or calendar_id.strip() != calendar_id:
            raise ValueError("calendar_id must be non-empty exact text")
        if type(calendar_slot_count) is not int or calendar_slot_count <= 0:
            raise ValueError("calendar_slot_count must be a positive integer")
        if type(max_samples) is not int or not 1 <= max_samples <= MAX_RUN_CAPACITY_SAMPLES:
            raise ValueError("max_samples must be between 1 and 16")
        self._run_id = run_id
        self._epoch_id = epoch_id
        self._calendar_id = calendar_id
        self._calendar_slot_count = calendar_slot_count
        self._max_samples = max_samples
        self._process_id = process_id
        self._process_create_time = process_create_time
        self._process_identity_status = "OBSERVED"
        self._issues = []
        if process_identity_issue is not None:
            self._process_identity_status = "INCOMPLETE"
            self._add_issue(process_identity_issue)
        if type(process_id) is not int or process_id <= 0:
            self._process_identity_status = "INCOMPLETE"
            self._add_issue("process_id_unavailable")
        if (
            type(process_create_time) not in (int, float)
            or not math.isfinite(process_create_time)
            or process_create_time <= 0
        ):
            self._process_identity_status = "INCOMPLETE"
            self._add_issue("process_create_time_unavailable")
        self._first_ready_boundary = None
        self._first_ready_phase = None
        self._bound_cohort_identity = None
        self._last_event_identity = None
        self._last_ordinal = None
        self._last_boundary_monotonic_ns = None
        self._last_boundary_utc_ns = None
        self._expected_ordinals = ()
        self._sampler = None
        self._sample_boundaries = []
        self._sampling_stopped = False

    def _add_issue(self, issue: str) -> None:
        if issue not in self._issues:
            self._issues.append(issue)

    def mark_callback_failure(self) -> None:
        """Record a Strategy-side callback failure without affecting trading."""
        self._add_issue("strategy_capacity_callback_failed")

    def _checkpoint_ordinals(self, first: int) -> Tuple[int, ...]:
        last = self._calendar_slot_count - 1
        remaining = last - first + 1
        if remaining <= 0:
            return ()
        count = min(self._max_samples, remaining)
        if count == 1:
            return (first,)
        span = last - first
        points = tuple(first + (index * span // (count - 1)) for index in range(count))
        if len(points) != count or any(a >= b for a, b in zip(points, points[1:])):
            return ()
        return points

    @staticmethod
    def _clock_boundary() -> Mapping[str, int]:
        monotonic_before = time.monotonic_ns()
        system_utc_ns = time.time_ns()
        monotonic_after = time.monotonic_ns()
        return {
            "system_utc_epoch_ns": system_utc_ns,
            "monotonic_before_ns": monotonic_before,
            "monotonic_after_ns": monotonic_after,
        }

    def observe(self, strategy: Any, event: Any, *, store: Any) -> None:
        """Observe one strategy-thread callback; malformed facts fail closed."""
        try:
            if self._process_id is not None and os.getpid() != self._process_id:
                self._add_issue("process_id_changed")
                return
            boundary = self._clock_boundary()
            if (
                self._last_boundary_monotonic_ns is not None
                and boundary["monotonic_before_ns"] < self._last_boundary_monotonic_ns
            ):
                self._add_issue("system_monotonic_clock_regressed")
                return
            if (
                self._last_boundary_utc_ns is not None
                and boundary["system_utc_epoch_ns"] < self._last_boundary_utc_ns
            ):
                self._add_issue("system_utc_clock_regressed")
                return
            self._last_boundary_monotonic_ns = boundary["monotonic_after_ns"]
            self._last_boundary_utc_ns = boundary["system_utc_epoch_ns"]

            if not isinstance(event, Mapping):
                self._add_issue("ready_event_unavailable")
                return
            p = getattr(strategy, "p", None)
            live_factors = getattr(strategy, "live_factors", None)
            cohort = getattr(p, "cohort", None)
            if (
                event.get("readiness") != "LIVE_READY"
                or event.get("replay_mode") is not False
                or event.get("run_id") != self._run_id
                or getattr(p, "logical_run_id", None) != self._run_id
                or getattr(p, "replay_mode", None) is not False
                or cohort is None
                or getattr(live_factors, "cohort", None) is not cohort
            ):
                self._add_issue("ready_event_run_binding_mismatch")
                return

            cohort_id = event.get("cohort_id")
            epoch_id = event.get("epoch_id")
            calendar_id = event.get("calendar_id")
            batch_id = event.get("batch_id")
            slot_index = event.get("slot_index")
            grid_ordinal = event.get("grid_ordinal")
            phase = event.get("engine_phase")
            if (
                not isinstance(cohort_id, str)
                or not cohort_id
                or type(epoch_id) is not int
                or epoch_id != self._epoch_id
                or not isinstance(calendar_id, str)
                or calendar_id != self._calendar_id
                or not isinstance(batch_id, str)
                or not batch_id
                or type(slot_index) is not int
                or slot_index < 0
                or slot_index >= self._calendar_slot_count
                or type(grid_ordinal) is not int
                or grid_ordinal != slot_index
                or phase not in ("prenext_ready", "grid_recorded")
            ):
                self._add_issue("ready_event_identity_or_ordinal_invalid")
                return

            current_batch_method = getattr(cohort, "current_batch", None)
            current_batch = current_batch_method() if callable(current_batch_method) else None
            if not _live_ready_members_complete(strategy, current_batch):
                self._add_issue("ready_event_current_batch_members_incomplete")
                return
            if (
                current_batch is None
                or getattr(current_batch, "status", None) != "COMPLETE"
                or getattr(current_batch, "batch_id", None) != batch_id
                or getattr(current_batch, "cohort_id", None) != cohort_id
                or getattr(current_batch, "epoch_id", None) != epoch_id
                or getattr(current_batch, "calendar_id", None) != calendar_id
                or getattr(current_batch, "slot_index", None) != slot_index
                or getattr(cohort, "cohort_id", None) != cohort_id
                or getattr(cohort, "epoch_id", None) != epoch_id
                or getattr(cohort, "calendar_id", None) != calendar_id
            ):
                self._add_issue("ready_event_current_batch_mismatch")
                return

            cohort_identity = (cohort_id, epoch_id, calendar_id)
            if self._bound_cohort_identity is None:
                self._bound_cohort_identity = cohort_identity
            elif self._bound_cohort_identity != cohort_identity:
                self._add_issue("run_cohort_identity_changed")
                return

            event_identity = (cohort_id, epoch_id, calendar_id, slot_index, batch_id)
            if self._last_event_identity == event_identity:
                return
            if self._last_ordinal is not None and slot_index <= self._last_ordinal:
                self._add_issue("grid_ordinal_regressed_or_conflicted")
                return

            if self._first_ready_boundary is None:
                expected = self._checkpoint_ordinals(slot_index)
                if not expected:
                    self._add_issue("live_calendar_checkpoint_range_invalid")
                    return
                self._first_ready_boundary = dict(boundary)
                self._first_ready_phase = phase
                self._expected_ordinals = expected
                if self._process_identity_status == "OBSERVED":
                    self._sampler = LiveCapacitySampler(
                        self._run_id, expected, max_samples=len(expected)
                    )

            self._last_ordinal = slot_index
            self._last_event_identity = event_identity
            if self._sampler is None:
                return

            next_index = len(self._sample_boundaries)
            if self._sampling_stopped or next_index >= len(self._expected_ordinals):
                return
            expected_ordinal = self._expected_ordinals[next_index]
            if slot_index > expected_ordinal:
                self._add_issue("grid_checkpoint_skipped")
                self._sampling_stopped = True
                return
            if slot_index < expected_ordinal:
                return

            sample = self._sampler.sample(
                slot_index, strategy=strategy, cohort=cohort, store=store
            )
            sample_boundary = {
                **boundary,
                "grid_ordinal": grid_ordinal,
                "ordinal_source": "live_cohort_batch_slot_index_zero_based",
                "batch_id": batch_id,
                "cohort_id": cohort_id,
                "epoch_id": epoch_id,
                "calendar_id": calendar_id,
                "engine_phase": phase,
            }
            if (
                type(sample.get("capture_monotonic_ns")) is not int
                or sample["capture_monotonic_ns"] < boundary["monotonic_before_ns"]
            ):
                self._add_issue("sample_clock_boundary_invalid")
            if sample.get("status") != "OBSERVED":
                self._add_issue("capacity_snapshot_incomplete")
            self._sample_boundaries.append(sample_boundary)
        except Exception:
            self._add_issue("capacity_capture_projection_failed")

    def report(self) -> Mapping[str, Any]:
        """Return finite, explicitly unevaluated run-bound capacity evidence."""
        if self._first_ready_boundary is None:
            self._add_issue("verified_live_ready_not_observed")
        if self._first_ready_boundary is not None and self._sampler is not None:
            sampler_report = self._sampler.report()
        else:
            sampler_report = None
        samples = []
        if sampler_report is not None:
            for index, row in enumerate(sampler_report["samples"]):
                item = copy.deepcopy(row)
                if index < len(self._sample_boundaries):
                    item["run_binding"] = {
                        "run_id": self._run_id,
                        "epoch_id": self._epoch_id,
                        "process_id": self._process_id,
                        "process_create_time": self._process_create_time,
                    }
                    item["ready_boundary"] = dict(self._sample_boundaries[index])
                samples.append(item)
        issues = list(self._issues)
        if sampler_report is not None:
            issues.extend(issue for issue in sampler_report["issues"] if issue not in issues)
        elif self._first_ready_boundary is not None:
            issues.extend(
                issue
                for issue in ("process_identity_unavailable", "capacity_sampler_not_started")
                if issue not in issues
            )
        complete_observation = (
            sampler_report is not None
            and sampler_report["status"] == "RECORDED_NOT_EVALUATED"
            and self._process_identity_status == "OBSERVED"
            and not issues
            and len(self._sample_boundaries) == len(self._expected_ordinals)
        )
        return MappingProxyType(
            {
                "schema": "backtrader.live_capacity_run_report.v1",
                "run_id": self._run_id,
                "status": "RECORDED_NOT_EVALUATED" if complete_observation else "INCOMPLETE",
                "acceptance_evaluated": False,
                "window_evaluation": "NOT_EVALUATED",
                "growth_evaluation": "NOT_EVALUATED",
                "stability_peak_claimed": False,
                "sampling_origin": "first_observed_verified_live_ready_callback",
                "first_ready_engine_phase": self._first_ready_phase,
                "epoch_id": self._epoch_id,
                "calendar_id": self._calendar_id,
                "calendar_slot_count": self._calendar_slot_count,
                "window_start_ordinal": (
                    self._expected_ordinals[0] if self._expected_ordinals else None
                ),
                "window_end_ordinal": (
                    self._expected_ordinals[-1] if self._expected_ordinals else None
                ),
                "expected_ordinals": self._expected_ordinals,
                "max_samples": self._max_samples,
                "sample_count": len(samples),
                "process_identity": {
                    "status": self._process_identity_status,
                    "pid": self._process_id,
                    "create_time": self._process_create_time,
                },
                "first_ready_boundary": (
                    None
                    if self._first_ready_boundary is None
                    else dict(self._first_ready_boundary)
                ),
                "samples": tuple(samples),
                "issues": tuple(issues),
            }
        )
