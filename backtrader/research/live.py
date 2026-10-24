"""Cohort-bound factor plans and immutable per-batch snapshots.

This module reuses the normal FactorIndicator graph and Cerebro lifecycle. It
does not advance indicators, queue bars, or authorize orders. A snapshot's
``LIVE_READY`` state means only that the calculation inputs and graph windows
meet the declared live calculation contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Optional, Sequence, Tuple

from ..errors import DatasetError, ResearchConfigError
from .specs import FactorSpec, normalize_factor_specs


class LiveFactorReadiness(str, Enum):
    """Calculation readiness derived from cohort receipts and factor windows."""

    INITIALIZING = "INITIALIZING"
    WARMUP = "WARMUP"
    CATCHING_UP = "CATCHING_UP"
    LIVE_READY = "LIVE_READY"
    DEGRADED = "DEGRADED"


class LiveFactorOutputStatus(str, Enum):
    """Whether one current factor output can be consumed as a value."""

    OUTPUT_AVAILABLE = "OUTPUT_AVAILABLE"
    OUTPUT_UNAVAILABLE = "OUTPUT_UNAVAILABLE"


def _executed_graph_span(instance: Any) -> int:
    # Return the largest finite minperiod present in the bound factor graph.
    from .operators import _LogicalOperatorView

    periods = []
    minimum = getattr(instance, "_minperiod", None)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ResearchConfigError("factor graph has no valid root minperiod")
    periods.append(minimum)
    nodes = list(getattr(instance, "_nodes", {}).values())
    nodes.extend(getattr(instance, "_physical_nodes", ()))
    seen_nodes = set()
    for node in nodes:
        if type(node) is _LogicalOperatorView:
            node = getattr(node, "_physical_panel", None)
            if node is None:
                raise ResearchConfigError("factor graph logical view has no physical panel")
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        minimum = getattr(node, "_minperiod", None)
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ResearchConfigError("factor graph node has no finite minperiod")
        periods.append(minimum)
        period = getattr(getattr(node, "p", None), "period", None)
        if period is not None and (
            isinstance(period, bool)
            or not isinstance(period, (int, float))
            or not math.isfinite(float(period))
            or float(period) < 0.0
        ):
            raise ResearchConfigError("factor graph contains an unbounded temporal operator")
    for lines in getattr(instance, "_field_line_cache", {}).values():
        for line in lines:
            owner = getattr(getattr(line, "_owner", None), "_owner_ref", None)
            minimum = getattr(owner, "_minperiod", 1) if owner is not None else 1
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
                raise ResearchConfigError("factor input graph has no finite minperiod")
            periods.append(minimum)
    return max(periods)


def _name(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchConfigError("%s must be a non-empty string" % field_name)
    return value


def _unique_names(values: Sequence[str], field_name: str) -> Tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ResearchConfigError("%s must be a sequence of names" % field_name)
    result = tuple(_name(value, field_name) for value in values)
    if not result or len(set(result)) != len(result):
        raise ResearchConfigError("%s must contain unique names" % field_name)
    return result


def _utc(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchConfigError("%s must be a timezone-aware datetime" % field_name)
    if value.utcoffset() != timedelta(0):
        raise ResearchConfigError("%s must use UTC" % field_name)
    return value.astimezone(timezone.utc)


def _profile_seconds(value: Any, field_name: str, *, positive: bool) -> float:
    if type(value) not in (int, float):
        raise ResearchConfigError("%s must be a finite numeric value" % field_name)
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchConfigError("%s must be a finite numeric value" % field_name) from exc
    if not math.isfinite(seconds):
        raise ResearchConfigError("%s must be finite" % field_name)
    if (positive and seconds <= 0.0) or (not positive and seconds < 0.0):
        relation = "positive" if positive else "non-negative"
        raise ResearchConfigError("%s must be %s" % (field_name, relation))
    return seconds


@dataclass(frozen=True, init=False)
class LiveFactorPlan:
    """Immutable factor inputs, target groups, calendar and bounded-run policy.

    ``groups`` maps each target name to a cross-sectional group, matching the
    existing ``ResearchSpec`` convention. A missing entry uses ``default``.
    ``warmup_min_bars`` is an additional minimum beyond the bound graph's real
    minperiod; a 51 strategy can set its documented 30-bar policy here.
    The freshness profile compares live batch times to the Cerebro-installed
    scheduler clock at each snapshot read. The defaults allow a one-minute
    bar age and no future timestamp skew.
    """

    plan_id: str
    targets: Tuple[str, ...]
    groups: Mapping[str, str]
    factors: Mapping[str, FactorSpec]
    calendar_id: str
    frequency: str
    warmup_min_bars: int
    max_pending_slots: int
    max_window_bars: int
    wait_timeout_ns: int
    max_live_bar_age_seconds: float
    max_future_skew_seconds: float
    allow_history_prewarm: bool
    _group_targets: Mapping[str, Tuple[str, ...]] = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        targets: Sequence[str],
        factors: Any,
        calendar_id: str,
        frequency: str,
        plan_id: str = "live-factor-plan",
        groups: Optional[Mapping[str, str]] = None,
        warmup_min_bars: int = 1,
        max_pending_slots: int = 8,
        max_window_bars: int = 512,
        wait_timeout_ns: int = 5_000_000_000,
        max_live_bar_age_seconds: float = 60.0,
        max_future_skew_seconds: float = 0.0,
        allow_history_prewarm: bool = True,
    ) -> None:
        frozen_targets = _unique_names(targets, "targets")
        declared_factors = normalize_factor_specs(factors)
        _name(plan_id, "plan_id")
        _name(calendar_id, "calendar_id")
        _name(frequency, "frequency")
        if type(warmup_min_bars) is not int or warmup_min_bars < 0:
            raise ResearchConfigError("warmup_min_bars must be a non-negative integer")
        if type(max_pending_slots) is not int or max_pending_slots < 1:
            raise ResearchConfigError("max_pending_slots must be a positive integer")
        if type(max_window_bars) is not int or max_window_bars < 1:
            raise ResearchConfigError("max_window_bars must be a positive integer")
        if warmup_min_bars > max_window_bars:
            raise ResearchConfigError("warmup_min_bars cannot exceed max_window_bars")
        if type(wait_timeout_ns) is not int or wait_timeout_ns < 1:
            raise ResearchConfigError("wait_timeout_ns must be a positive integer")
        max_live_bar_age_seconds = _profile_seconds(
            max_live_bar_age_seconds,
            "max_live_bar_age_seconds",
            positive=True,
        )
        max_future_skew_seconds = _profile_seconds(
            max_future_skew_seconds,
            "max_future_skew_seconds",
            positive=False,
        )
        if type(allow_history_prewarm) is not bool:
            raise ResearchConfigError("allow_history_prewarm must be a bool")

        if groups is not None and not isinstance(groups, Mapping):
            raise ResearchConfigError("groups must map target names to group names")
        supplied_groups = {} if groups is None else dict(groups)
        if any(target not in frozen_targets for target in supplied_groups):
            raise ResearchConfigError("groups may only name declared targets")
        frozen_groups: Dict[str, str] = {}
        grouped: Dict[str, list] = {}
        for target in frozen_targets:
            group = _name(supplied_groups.get(target, "default"), "group name")
            frozen_groups[target] = group
            grouped.setdefault(group, []).append(target)

        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "targets", frozen_targets)
        object.__setattr__(self, "groups", MappingProxyType(frozen_groups))
        object.__setattr__(self, "factors", declared_factors)
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "warmup_min_bars", warmup_min_bars)
        object.__setattr__(self, "max_pending_slots", max_pending_slots)
        object.__setattr__(self, "max_window_bars", max_window_bars)
        object.__setattr__(self, "wait_timeout_ns", wait_timeout_ns)
        object.__setattr__(self, "max_live_bar_age_seconds", max_live_bar_age_seconds)
        object.__setattr__(self, "max_future_skew_seconds", max_future_skew_seconds)
        object.__setattr__(self, "allow_history_prewarm", allow_history_prewarm)
        object.__setattr__(
            self,
            "_group_targets",
            MappingProxyType({key: tuple(value) for key, value in grouped.items()}),
        )

    @property
    def group_targets(self) -> Mapping[str, Tuple[str, ...]]:
        """Return immutable target lists grouped for cross-sectional formulas."""
        return self._group_targets


@dataclass(frozen=True)
class LiveFactorInput:
    """Public, non-secret identity of one declared factor input line."""

    feed_name: str
    member_id: str
    source_ref: Any
    line_name: str


@dataclass(frozen=True)
class LiveFactorOutput:
    """One factor/target value and the exact bar receipt that produced it."""

    value: float
    status: LiveFactorOutputStatus
    reason: Optional[str]
    present: bool
    complete: bool
    quality: Any
    source_role: str
    member_id: str
    source_ref: Any
    sequence: int
    generation: Any


@dataclass(frozen=True)
class LiveFactorResult:
    """One immutable factor's metadata and current target-ordered values."""

    name: str
    mode: str
    panel_line: str
    direction: int
    source_sha256: str
    inputs: Mapping[str, Tuple[LiveFactorInput, ...]]
    values: Mapping[str, LiveFactorOutput]


@dataclass(frozen=True)
class LiveFactorSnapshot:
    """Read-only projection of one complete cohort batch and factor graph.

    ``readiness`` describes calculation only. It is never order, account, or
    permission readiness. Each output separately reports value availability.
    """

    plan_id: str
    cohort_id: str
    calendar_id: str
    calendar_version: Any
    frequency: str
    epoch_id: Optional[int]
    batch_id: Optional[str]
    close_time: Optional[datetime]
    available_at: Optional[datetime]
    batch_complete: bool
    readiness: LiveFactorReadiness
    readiness_reasons: Tuple[str, ...]
    factors: Mapping[str, LiveFactorResult]


def _field_sources(binding: Any, field_bindings: Mapping[str, Any], stack=()) -> Tuple[str, ...]:
    """Resolve existing FactorSpec aliases to their direct feed line sources."""
    if isinstance(binding, Mapping):
        kind = binding.get("derive")
        if kind == "adv":
            alias = binding.get("source")
            if alias in stack:
                raise ResearchConfigError("cyclic factor field binding")
            return _field_sources(field_bindings.get(alias), field_bindings, stack + (alias,))
        if kind == "vwap_volume":
            sources = []
            for alias in (binding.get("vwap"), binding.get("volume")):
                if alias in stack:
                    raise ResearchConfigError("cyclic factor field binding")
                sources.extend(
                    _field_sources(field_bindings.get(alias), field_bindings, stack + (alias,))
                )
            return tuple(sources)
        if binding.get("kind") == "direct":
            binding = binding.get("source")
        else:
            raise ResearchConfigError("unsupported live factor field derivation")
    if not isinstance(binding, str) or not binding.startswith("feed:"):
        raise ResearchConfigError("live factor fields must resolve to feed lines")
    return (binding,)


def _freeze_value(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


class LiveFactorSet:
    """Bind shared FactorSpecs to ordinary feed lines under one live cohort."""

    def __init__(
        self,
        plan,
        cohort,
        feeds,
        instances,
        inputs,
        required_fields,
        bindings,
        scheduler_clock,
        reconstruction,
    ):
        self._plan = plan
        self._cohort = cohort
        self._scheduler_clock = scheduler_clock
        self._feeds = MappingProxyType(dict(feeds))
        self._instances = MappingProxyType(
            {name: MappingProxyType(dict(groups)) for name, groups in instances.items()}
        )
        self._inputs = MappingProxyType(dict(inputs))
        self._required_fields = MappingProxyType(
            {
                feed_id: (feed, tuple(sorted(names)))
                for feed_id, (feed, names) in required_fields.items()
            }
        )
        self._bindings = tuple(
            (binding.feed_ref, binding.line_name, binding) for binding in bindings
        )
        self._reconstruction = MappingProxyType(dict(reconstruction))

    @classmethod
    def bind(cls, plan, datas, *, cohort):
        """Construct the normal FactorIndicator graphs inside a Strategy owner.

        ``datas`` maps exact Cerebro feed names to feed objects. Every declared
        target and auxiliary field source must be an exact member of ``cohort``.
        Strict streaming fields require cohort-issued receipts; no caller flag
        can bypass the source contract.
        """
        from .factor_indicator import FactorIndicator
        from .strict import live_source_binding_scope
        from .specs import thaw
        from .live_cohort import LiveBarCohort

        if type(plan) is not LiveFactorPlan:
            raise ResearchConfigError("plan must be a LiveFactorPlan")
        if type(cohort) is not LiveBarCohort:
            raise ResearchConfigError("cohort must be a LiveBarCohort")
        if not isinstance(datas, Mapping) or not datas:
            raise ResearchConfigError("datas must map feed names to exact feed objects")

        # A schema registration alone is not a per-row source receipt.  The
        # live graph is admitted only on the exact feed implementation that
        # Cerebro has activated for this cohort; its loader stages immutable
        # raw events, lets the cohort validate them before line writes, then
        # publishes the complete batch before strategy callbacks.
        from ..feeds.btapifeed import BtApiFeed

        feeds = dict(datas)
        if any(not isinstance(name, str) or not name for name in feeds):
            raise ResearchConfigError("feed names must be non-empty strings")
        if len({id(feed) for feed in feeds.values()}) != len(feeds):
            raise ResearchConfigError("datas must not map multiple names to one feed")
        for feed_name, feed in feeds.items():
            if type(feed) is not BtApiFeed:
                raise ResearchConfigError(
                    "live factor binding requires exact BtApiFeed instances",
                    code="UNSUPPORTED_SOURCE",
                )
            if getattr(feed, "live_bar_cohort", None) is not cohort:
                raise ResearchConfigError(
                    "BtApiFeed must be activated by Cerebro for this exact live cohort",
                    code="UNSUPPORTED_SOURCE",
                )
            if getattr(feed, "_name", None) != feed_name:
                raise ResearchConfigError("feed mapping name does not match its Cerebro name")
            member = _member_for_feed(cohort, feed)
            if member is None or member.feed_ref is not feed:
                raise ResearchConfigError(
                    "every Strategy feed must be an exact registered cohort member",
                    code="UNSUPPORTED_SOURCE",
                )
        # Cerebro installs this exact clock while activating the cohort.  Keep
        # the shared scheduler object and call its UTC clock at snapshot time;
        # never infer processing time from the provider's bar timestamps.
        scheduler_clock = getattr(next(iter(feeds.values())), "_cohort_clock", None)
        if scheduler_clock is None or not callable(getattr(scheduler_clock, "utc_now", None)):
            raise ResearchConfigError(
                "live cohort feeds must share the Cerebro-installed UTC scheduler clock",
                code="UNSUPPORTED_SOURCE",
            )
        if any(
            getattr(feed, "_cohort_clock", None) is not scheduler_clock for feed in feeds.values()
        ):
            raise ResearchConfigError(
                "live cohort feeds do not share one exact scheduler clock",
                code="UNSUPPORTED_SOURCE",
            )
        if getattr(cohort, "calendar_id", None) != plan.calendar_id:
            raise ResearchConfigError("plan calendar_id does not match the live cohort")
        if getattr(cohort, "frequency", None) != plan.frequency:
            raise ResearchConfigError("plan frequency does not match the live cohort")
        for name in ("max_pending_slots", "max_window_bars", "wait_timeout_ns"):
            if getattr(plan, name) != getattr(cohort, name, None):
                raise ResearchConfigError("plan %s does not match the live cohort" % name)

        missing_targets = tuple(target for target in plan.targets if target not in feeds)
        if missing_targets:
            raise DatasetError(
                "LiveFactorPlan targets have no matching named feed",
                code="MISSING_INPUT",
                report={"missing_targets": missing_targets},
            )

        feed_member_ids = {
            member.member_id
            for member in (_member_for_feed(cohort, feed) for feed in feeds.values())
            if member is not None
        }
        if feed_member_ids != set(cohort.member_ids):
            raise ResearchConfigError(
                "Strategy feeds must cover every exact member registered with the cohort",
                code="UNSUPPORTED_SOURCE",
            )

        required_fields: Dict[int, Tuple[Any, set]] = {}
        for target in plan.targets:
            feed = feeds[target]
            required_fields[id(feed)] = (feed, set())
        input_descriptors: Dict[str, Mapping[str, Tuple[LiveFactorInput, ...]]] = {}
        binding_receipts = {}
        for factor_name, spec in plan.factors.items():
            aliases: Dict[str, Tuple[LiveFactorInput, ...]] = {}
            for alias, binding in spec.field_bindings.items():
                resolved = []
                seen_source = set()
                for source in _field_sources(binding, spec.field_bindings, (alias,)):
                    parts = source.split(":")
                    if len(parts) != 3 or not parts[1] or not parts[2]:
                        raise ResearchConfigError("feed bindings must use feed:<name>:<line>")
                    feed_names = plan.targets if parts[1] == "target" else (parts[1],)
                    for feed_name in feed_names:
                        if feed_name not in feeds:
                            raise DatasetError(
                                "factor field binding references an unknown feed",
                                code="MISSING_INPUT",
                                report={"factor": factor_name, "field": alias, "feed": feed_name},
                            )
                        feed = feeds[feed_name]
                        line_name = parts[2]
                        try:
                            getattr(feed, line_name)
                        except AttributeError as exc:
                            raise DatasetError(
                                "factor field binding references an unknown feed line",
                                code="MISSING_INPUT",
                                report={
                                    "factor": factor_name,
                                    "field": alias,
                                    "feed": feed_name,
                                    "line": line_name,
                                },
                            ) from exc
                        member = _member_for_feed(cohort, feed)
                        if member is None or member.feed_ref is not feed:
                            raise ResearchConfigError(
                                "factor field feed is not an exact cohort member",
                                code="UNSUPPORTED_SOURCE",
                            )
                        key = (id(feed), line_name)
                        receipt = binding_receipts.get(key)
                        if receipt is None:
                            receipt = cohort.require_factor_field(feed, line_name)
                            binding_receipts[key] = receipt
                        if (
                            receipt.feed_ref is not feed
                            or receipt.line_name != line_name
                            or not cohort.owns_factor_binding(receipt)
                        ):
                            raise ResearchConfigError(
                                "cohort returned a mismatched factor input binding",
                                code="UNSUPPORTED_SOURCE",
                            )
                        field_key = (id(feed), line_name)
                        if field_key not in seen_source:
                            resolved.append(
                                LiveFactorInput(
                                    feed_name=feed_name,
                                    member_id=member.member_id,
                                    source_ref=member.source_ref,
                                    line_name=line_name,
                                )
                            )
                            seen_source.add(field_key)
                        entry = required_fields.setdefault(id(feed), (feed, set()))
                        entry[1].add(line_name)
                aliases[alias] = tuple(resolved)
            input_descriptors[factor_name] = MappingProxyType(aliases)

        scoped_receipts = tuple(
            (receipt.feed_ref, receipt.line_name, receipt) for receipt in binding_receipts.values()
        )
        available_datas = tuple(feeds.values())
        instances: Dict[str, Dict[str, FactorIndicator]] = {}
        with live_source_binding_scope(cohort, scoped_receipts):
            for factor_name, spec in plan.factors.items():
                by_group = {}
                for group, targets in plan.group_targets.items():
                    group_datas = tuple(feeds[name] for name in targets)
                    instance = spec.indicator._bind_for_research(
                        *group_datas,
                        output_datas=group_datas,
                        asset_names=targets,
                        factor_name=factor_name,
                        field_bindings=spec.field_bindings,
                        research=None,
                        mode=spec.mode,
                        available_datas=available_datas,
                        strict=True,
                        **thaw(spec.params),
                    )
                    if not isinstance(instance, FactorIndicator):
                        raise RuntimeError("live factor binding did not create a FactorIndicator")
                    if int(getattr(instance, "_minperiod", 1)) > plan.max_window_bars:
                        raise ResearchConfigError("factor graph minperiod exceeds max_window_bars")
                    by_group[group] = instance
                instances[factor_name] = by_group

        from .specs import _source_fingerprint

        from .alpha101 import ALPHA_REGISTRY

        registered_alpha_ids = {id(indicator) for indicator in ALPHA_REGISTRY.values()}
        reconstruction = {}
        for factor_name, spec in plan.factors.items():
            spans = tuple(
                _executed_graph_span(instance) for instance in instances[factor_name].values()
            )
            if not spans or len(set(spans)) != 1:
                raise ResearchConfigError(
                    "factor groups do not share one executed graph span",
                    code="UNSUPPORTED_SOURCE",
                )
            graph_span = spans[0]
            if id(spec.indicator) in registered_alpha_ids:
                current_source, _module_source, _kind = _source_fingerprint(spec.indicator)
                if current_source != spec.source_sha256:
                    raise ResearchConfigError(
                        "registered Alpha101 source changed after FactorSpec construction",
                        code="UNSUPPORTED_SOURCE",
                    )
                if graph_span != spec.lookback_h + 1:
                    raise ResearchConfigError(
                        "registered Alpha101 graph span differs from its verified finite profile",
                        code="UNSUPPORTED_SOURCE",
                    )
                reconstruction[factor_name] = ("finite_window", graph_span)
            elif spec.history_contract is None:
                reconstruction[factor_name] = ("unqualified", graph_span)
            elif spec.history_contract.kind == "finite_window":
                if spec.history_contract.span_bars < graph_span:
                    raise ResearchConfigError(
                        "finite_window history contract is shorter than the executed graph span",
                        code="UNSUPPORTED_SOURCE",
                    )
                reconstruction[factor_name] = (
                    "finite_window",
                    spec.history_contract.span_bars,
                )
            else:
                reconstruction[factor_name] = ("replay_from_source_origin", graph_span)

        return cls(
            plan,
            cohort,
            feeds,
            instances,
            input_descriptors,
            required_fields,
            tuple(binding_receipts.values()),
            scheduler_clock,
            reconstruction,
        )

    @property
    def plan(self) -> LiveFactorPlan:
        return self._plan

    @property
    def cohort(self) -> Any:
        return self._cohort

    @property
    def factor_instances(self) -> Mapping[str, Mapping[str, Any]]:
        return self._instances

    def snapshot(self) -> LiveFactorSnapshot:
        """Read the latest complete batch without advancing or retaining it."""
        batch = self._cohort.current_batch()
        if batch is None:
            if getattr(self._cohort, "frozen", False):
                return self._make_snapshot(
                    batch=None,
                    readiness=LiveFactorReadiness.DEGRADED,
                    reasons=("cohort_frozen_before_first_batch",),
                    factor_values={},
                )
            return self._make_snapshot(
                batch=None,
                readiness=LiveFactorReadiness.INITIALIZING,
                reasons=("no_complete_batch",),
                factor_values={},
            )

        if getattr(self._cohort, "frozen", False):
            return self._make_snapshot(
                batch=batch,
                readiness=LiveFactorReadiness.DEGRADED,
                reasons=("cohort_frozen",),
                factor_values={},
            )

        invalid = []
        if getattr(batch, "status", None) != "COMPLETE":
            invalid.append("batch_not_complete")
        if batch.cohort_id != self._cohort.cohort_id:
            invalid.append("batch_cohort_mismatch")
        if batch.calendar_id != self._plan.calendar_id:
            invalid.append("batch_calendar_mismatch")
        if getattr(batch, "frequency", self._cohort.frequency) != self._plan.frequency:
            invalid.append("batch_frequency_mismatch")
        if batch.epoch_id != self._cohort.epoch_id:
            invalid.append("batch_epoch_mismatch")
        if any(
            feed is not receipt.feed_ref
            or line_name != receipt.line_name
            or not self._cohort.owns_factor_binding(receipt)
            for feed, line_name, receipt in self._bindings
        ):
            invalid.append("input_binding_ownership_changed")
        if any(
            getattr(feed, "_cohort_clock", None) is not self._scheduler_clock
            for feed in self._feeds.values()
        ):
            invalid.append("scheduler_clock_identity_changed")

        current_receipts = {}
        for feed in self._feeds.values():
            member = _member_for_feed(self._cohort, feed)
            receipt = None if member is None else batch.members.get(member.member_id)
            delivered = _current_delivery(self._cohort, feed)
            if receipt is None or receipt.feed_ref is not feed or delivered is not receipt:
                invalid.append("current_delivery_mismatch")
                continue
            current_receipts[id(feed)] = receipt
            if not _feed_clock_matches(feed, receipt.close_time):
                invalid.append("feed_clock_mismatch")
            if not _feed_lines_match_receipt(feed, member.line_fields, receipt):
                invalid.append("feed_line_value_mismatch")

        if invalid:
            return self._make_snapshot(
                batch=batch,
                readiness=LiveFactorReadiness.DEGRADED,
                reasons=tuple(dict.fromkeys(invalid)),
                factor_values={},
            )

        gap_receipts = tuple(
            receipt
            for receipt in current_receipts.values()
            if receipt.present is not True
            or receipt.quality != "GOOD"
            or bool(getattr(receipt, "missing_fields", ()))
        )
        if gap_receipts and not self._has_registered_gap_semantics():
            self._cohort.freeze_unsupported_gap_semantics(batch)
            return self._make_snapshot(
                batch=batch,
                readiness=LiveFactorReadiness.DEGRADED,
                reasons=("unsupported_factor_gap_semantics",),
                factor_values={},
            )

        required_count = max(
            [self._plan.warmup_min_bars]
            + [
                int(getattr(instance, "_minperiod", 1))
                for groups in self._instances.values()
                for instance in groups.values()
            ]
            + [span for kind, span in self._reconstruction.values() if kind == "finite_window"]
        )
        if required_count > self._plan.max_window_bars:
            return self._make_snapshot(
                batch=batch,
                readiness=LiveFactorReadiness.DEGRADED,
                reasons=("factor_window_exceeds_bounded_history",),
                factor_values={},
            )
        windows_complete = True
        window_receipts = {}
        for feed_id, (feed, line_names) in self._required_fields.items():
            if not line_names:
                continue
            window = self._cohort.complete_window_bars(feed, line_names, required_count)
            latest = current_receipts.get(feed_id)
            if not window or latest is None or window[-1] is not latest:
                windows_complete = False
                continue
            window_receipts[feed_id] = tuple(window)

        cutover_flags = []
        for feed_id, (feed, _line_names) in self._required_fields.items():
            member = _member_for_feed(self._cohort, feed)
            cutover = None if member is None else batch.cutovers.get(member.member_id)
            if cutover is None:
                cutover_flags.append(False)
                continue
            latest = current_receipts[feed_id]
            if (
                cutover.cohort_id != self._cohort.cohort_id
                or cutover.epoch_id != batch.epoch_id
                or cutover.member_id != latest.member_id
                or not cutover.crossed_live
                or cutover.first_live_receipt is None
                or cutover.first_live_receipt.cohort_id != self._cohort.cohort_id
                or cutover.first_live_receipt.epoch_id != batch.epoch_id
                or cutover.first_live_receipt.member_id != latest.member_id
                or cutover.first_live_receipt.feed_ref is not feed
                or cutover.first_live_receipt.close_time > latest.close_time
                or cutover.first_live_receipt.source_role != "live"
                or cutover.transition_kind not in ("history_to_live", "live_cold_start")
            ):
                cutover_flags.append(False)
            else:
                cutover_flags.append(True)

        if not cutover_flags:
            cutover_state = LiveFactorReadiness.WARMUP
        elif all(cutover_flags):
            cutover_state = LiveFactorReadiness.LIVE_READY
        elif any(cutover_flags):
            cutover_state = LiveFactorReadiness.CATCHING_UP
        else:
            cutover_state = LiveFactorReadiness.WARMUP

        history_policy_invalid = False
        if not self._plan.allow_history_prewarm:
            history_policy_invalid = any(
                not _is_live_role(receipt.source_role)
                for feed_id in self._required_fields
                for receipt in (current_receipts.get(feed_id),)
                if receipt is not None
            ) or any(
                not _is_live_role(receipt.source_role)
                for rows in window_receipts.values()
                for receipt in rows
            )

        freshness_reasons = []
        if (
            current_receipts
            and len(current_receipts) == len(self._feeds)
            and all(receipt.source_role == "live" for receipt in current_receipts.values())
        ):
            try:
                scheduler_now = _utc(self._scheduler_clock.utc_now(), "scheduler_clock.utc_now")
            except Exception:
                # A broken or malformed injected clock is a closed readiness
                # gate, while the already-computed factor output stays usable
                # for diagnostics.
                freshness_reasons.append("scheduler_clock_unavailable")
            else:
                close_time = _utc(batch.close_time, "batch.close_time")
                available_at = _utc(batch.available_at, "batch.available_at")
                if (scheduler_now - close_time).total_seconds() > (
                    self._plan.max_live_bar_age_seconds
                ):
                    freshness_reasons.append("live_bar_stale")
                if (
                    max(
                        (close_time - scheduler_now).total_seconds(),
                        (available_at - scheduler_now).total_seconds(),
                    )
                    > self._plan.max_future_skew_seconds
                ):
                    freshness_reasons.append("live_bar_future_skew_exceeded")

        reconstruction_reasons = self._history_reconstruction_reasons(batch, current_receipts)
        readiness_reasons = []
        if gap_receipts:
            readiness_reasons.append("cohort_gap_present")
        if not windows_complete:
            readiness_reasons.append("input_window_incomplete_or_warmup_short")
        if cutover_state is not LiveFactorReadiness.LIVE_READY:
            readiness_reasons.append("live_cutover_incomplete")
        if history_policy_invalid:
            readiness_reasons.append("history_prewarm_not_allowed")
        readiness_reasons.extend(freshness_reasons)
        readiness_reasons.extend(reconstruction_reasons)

        if cutover_state is LiveFactorReadiness.CATCHING_UP:
            readiness = LiveFactorReadiness.CATCHING_UP
        elif (
            gap_receipts
            or not windows_complete
            or history_policy_invalid
            or freshness_reasons
            or reconstruction_reasons
        ):
            readiness = LiveFactorReadiness.WARMUP
        else:
            readiness = cutover_state

        factor_values = self._read_factor_values(current_receipts)
        return self._make_snapshot(
            batch=batch,
            readiness=readiness,
            reasons=tuple(readiness_reasons),
            factor_values=factor_values,
        )

    def _history_reconstruction_reasons(self, batch, current_receipts):
        # Qualify history without changing factor values or order permissions.
        reasons = []
        for factor_name, (kind, _span) in self._reconstruction.items():
            if kind == "finite_window":
                continue
            if kind == "unqualified":
                reasons.append("history_reconstruction_unqualified")
                continue
            if kind != "replay_from_source_origin":
                reasons.append("history_reconstruction_unqualified")
                continue
            input_feeds = {
                id(self._feeds[item.feed_name]): self._feeds[item.feed_name]
                for inputs in self._inputs[factor_name].values()
                for item in inputs
            }
            if not input_feeds:
                reasons.append("history_reconstruction_unqualified")
                continue
            for feed in input_feeds.values():
                member = _member_for_feed(self._cohort, feed)
                latest = current_receipts.get(id(feed))
                proof = (
                    None
                    if member is None
                    else getattr(batch, "history_continuity", {}).get(member.member_id)
                )
                if (
                    member is None
                    or latest is None
                    or proof is None
                    or not self._cohort.owns_history_continuity(proof)
                    or proof.cohort_id != self._cohort.cohort_id
                    or proof.member_id != member.member_id
                    or proof.epoch_id != batch.epoch_id
                    or proof.source_ref != member.source_ref
                    or proof.qualified is not True
                    or proof.last_receipt is not latest
                    or proof.origin_receipt is None
                    or proof.origin_receipt.feed_ref is not feed
                    or proof.origin_receipt.member_id != member.member_id
                    or proof.origin_receipt.epoch_id != batch.epoch_id
                ):
                    reasons.append(
                        getattr(proof, "reason", None) or "history_reconstruction_unqualified"
                    )
                    break
                if latest.source_role != "live":
                    continue
                cutover = batch.cutovers.get(member.member_id)
                origin = proof.origin_receipt
                if origin.source_role == "history" and not self._plan.allow_history_prewarm:
                    reasons.append("history_prewarm_not_allowed")
                    break
                handoff_matches = (
                    cutover is not None
                    and cutover.cohort_id == self._cohort.cohort_id
                    and cutover.member_id == member.member_id
                    and cutover.epoch_id == batch.epoch_id
                    and cutover.crossed_live is True
                    and cutover.first_live_receipt is not None
                    and cutover.first_live_receipt.feed_ref is feed
                    and cutover.first_live_receipt.member_id == member.member_id
                    and cutover.first_live_receipt.source_ref == member.source_ref
                    and cutover.first_live_receipt.source_role == "live"
                    and cutover.first_live_close_time == cutover.first_live_receipt.close_time
                )
                if origin.source_role == "history":
                    handoff_matches = (
                        handoff_matches
                        and cutover.transition_kind == "history_to_live"
                        and cutover.history_last_close_time is not None
                        and cutover.history_last_close_time < cutover.first_live_close_time
                    )
                elif origin.source_role == "live":
                    handoff_matches = (
                        handoff_matches
                        and cutover.transition_kind == "live_cold_start"
                        and cutover.first_live_receipt is origin
                    )
                else:
                    handoff_matches = False
                if not handoff_matches:
                    reasons.append("history_role_handoff_unverified")
                    break
        return tuple(dict.fromkeys(reasons))

    def _has_registered_gap_semantics(self) -> bool:
        """Allow NaN-window recovery only for the exact production Alpha101 set."""
        if not self._plan.factors:
            return False
        from .alpha101 import ALPHA_REGISTRY

        accepted = tuple(ALPHA_REGISTRY.values())
        return all(
            any(spec.indicator is indicator for indicator in accepted)
            for spec in self._plan.factors.values()
        )

    def _read_factor_values(self, current_receipts):
        results = {}
        for factor_name, spec in self._plan.factors.items():
            values = {}
            for group, instance in self._instances[factor_name].items():
                for target in self._plan.group_targets[group]:
                    feed = self._feeds[target]
                    receipt = current_receipts.get(id(feed))
                    if receipt is None:
                        continue
                    try:
                        raw_value = float(instance.outputs[feed][spec.panel_line][0])
                    except (
                        AttributeError,
                        IndexError,
                        KeyError,
                        TypeError,
                        ValueError,
                        OverflowError,
                    ):
                        raw_value = float("nan")
                    reason = _output_reason(instance, feed, spec.panel_line)
                    if receipt.present is not True and reason is None:
                        reason = "MISSING_INPUT"
                    available = (
                        receipt.present is True
                        and receipt.complete is True
                        and receipt.quality == "GOOD"
                        and math.isfinite(raw_value)
                        and reason is None
                    )
                    values[target] = LiveFactorOutput(
                        value=raw_value,
                        status=(
                            LiveFactorOutputStatus.OUTPUT_AVAILABLE
                            if available
                            else LiveFactorOutputStatus.OUTPUT_UNAVAILABLE
                        ),
                        reason=reason,
                        present=bool(receipt.present),
                        complete=bool(receipt.complete),
                        quality=_freeze_value(receipt.quality),
                        source_role=_role_name(receipt.source_role),
                        member_id=str(receipt.member_id),
                        source_ref=receipt.source_ref,
                        sequence=int(receipt.feed_sequence),
                        generation=getattr(receipt.envelope, "connection_generation", None),
                    )
            results[factor_name] = MappingProxyType(values)
        return results

    def _make_snapshot(self, *, batch, readiness, reasons, factor_values):
        factor_results = {}
        for name, spec in self._plan.factors.items():
            factor_results[name] = LiveFactorResult(
                name=spec.name,
                mode=spec.mode,
                panel_line=spec.panel_line,
                direction=spec.direction,
                source_sha256=spec.source_sha256,
                inputs=self._inputs[name],
                values=MappingProxyType(dict(factor_values.get(name, {}))),
            )
        if batch is None:
            cohort_id = str(self._cohort.cohort_id)
            calendar_version = None
            epoch_id = batch_id = None
            close_time = available_at = None
        else:
            cohort_id = str(batch.cohort_id)
            calendar_version = batch.calendar_version
            epoch_id = batch.epoch_id
            batch_id = str(batch.batch_id)
            close_time = _utc(batch.close_time, "batch.close_time")
            available_at = _utc(batch.available_at, "batch.available_at")
        return LiveFactorSnapshot(
            plan_id=self._plan.plan_id,
            cohort_id=cohort_id,
            calendar_id=self._plan.calendar_id,
            calendar_version=calendar_version,
            frequency=self._plan.frequency,
            epoch_id=epoch_id,
            batch_id=batch_id,
            close_time=close_time,
            available_at=available_at,
            batch_complete=(batch is not None and getattr(batch, "status", None) == "COMPLETE"),
            readiness=readiness,
            readiness_reasons=tuple(reasons),
            factors=MappingProxyType(factor_results),
        )


def _member_for_feed(cohort, feed):
    try:
        return cohort.member_for_feed(feed)
    except (KeyError, TypeError, ValueError):
        return None


def _current_delivery(cohort, feed):
    try:
        return cohort.current_delivery(feed)
    except (KeyError, TypeError, ValueError):
        return None


def _feed_clock_matches(feed, close_time):
    try:
        from ..utils import num2date

        current = num2date(float(feed.datetime[0]), tz=timezone.utc, naive=False)
        expected = _utc(close_time, "receipt.close_time")
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        return False
    return current == expected


def _feed_lines_match_receipt(feed, line_names, receipt):
    """Fail closed if a delivered feed line no longer matches its receipt."""
    missing = set(getattr(receipt, "missing_fields", ()))
    for line_name in line_names:
        if line_name == "datetime":
            if not _feed_clock_matches(feed, receipt.close_time):
                return False
            continue
        if line_name not in receipt.raw_values:
            return False
        expected = receipt.raw_values[line_name]
        if isinstance(expected, (bool, str, bytes)):
            return False
        try:
            actual = float(getattr(feed, line_name)[0])
            expected = float(expected)
        except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
            return False
        if line_name in missing:
            if not math.isnan(actual) or not math.isnan(expected):
                return False
        elif not math.isfinite(actual) or not math.isfinite(expected) or actual != expected:
            return False
    return True


def _is_live_role(role):
    if isinstance(role, Enum):
        role = role.value
    if not isinstance(role, str):
        return False
    return role.strip().lower() in {"live", "realtime", "direct_live", "live_bar"}


def _role_name(role):
    if isinstance(role, Enum):
        role = role.value
    return str(role)


def _output_reason(instance, feed, output_name):
    """Return a known non-ready reason; malformed reason lines fail closed."""
    result_lines = getattr(instance, "_result_lines", ())
    try:
        index = next(
            index for index, candidate in enumerate(instance.target_datas) if candidate is feed
        )
        result = result_lines[index]
    except (AttributeError, IndexError, StopIteration, TypeError):
        result = None
    if isinstance(result, (tuple, list)):
        result = result[index] if index < len(result) else None
    try:
        reason_line = getattr(result, "_factor_research_reason_line", None)
        if reason_line is None:
            output = instance.outputs[feed][output_name]
            reason_line = getattr(output, "_factor_research_reason_line", None)
    except (AttributeError, IndexError, KeyError, TypeError):
        return "INVALID_REASON"
    if reason_line is None:
        return None
    try:
        raw = float(reason_line[0])
        if not math.isfinite(raw) or not raw.is_integer():
            return "INVALID_REASON"
        from .operators import REASON_NAMES

        reason = REASON_NAMES.get(int(raw))
        if reason is None:
            return "UNKNOWN_REASON"
        return None if reason == "READY" else reason
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        return "INVALID_REASON"


__all__ = (
    "LiveFactorInput",
    "LiveFactorOutput",
    "LiveFactorOutputStatus",
    "LiveFactorPlan",
    "LiveFactorReadiness",
    "LiveFactorResult",
    "LiveFactorSet",
    "LiveFactorSnapshot",
)
