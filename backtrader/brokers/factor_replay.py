"""Conservative local matching for bars labelled by their close time.

The ordinary BackBroker matches prices. This adapter only prevents it from
using a bar whose opening time precedes the decision's data availability.
It neither fabricates bid/ask quotes nor provides an external execution route.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from ..feed import DataBase
from ..order import Order
from ..utils.dateintern import date2num
from .bbroker import BackBroker


def _utc(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be a timezone-aware datetime".format(name))
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ReplayBarTiming:
    """Source times for one immutable, fully closed historical bar."""

    start: datetime
    end: datetime
    available_at: datetime

    def __post_init__(self):
        for name in ("start", "end", "available_at"):
            object.__setattr__(self, name, _utc(getattr(self, name), name))
        if self.start >= self.end or self.available_at < self.end:
            raise ValueError("replay bar requires start < end <= available_at")


class CausalReplayBroker(BackBroker):
    """BackBroker with explicit source-time admission for local replay orders.

    Before Cerebro starts, call ``bind_data_timing(data, timings)`` for each
    traded feed. Feed datetime lines must use the exact timing ``end`` labels.
    Submit ordinary orders with ``decision_available_at=<aware datetime>`` as
    a keyword to Strategy.buy/sell, so the information exists before submit.
    The cutoff must cover every bound feed in the synchronized decision batch
    and the caller's actual decision time, including any later quote inputs.
    Missing or mutated timing is rejected through normal order notifications.

    Only standalone market/limit orders are supported in this first profile;
    neither cheat mode nor Historical orders may bypass the matching gate.
    The immutable schedule is finite and belongs to the local replay run.
    """

    MAX_TIMINGS_PER_FEED = 200_000
    MAX_TOTAL_TIMINGS = 2_000_000
    MAX_FEEDS = 256

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._replay_timings = {}
        self._replay_timing_count = 0
        self._replay_started = False
        self._replay_order_cutoffs = {}

    def bind_data_timing(self, data, timings):
        """Bind an exact feed identity once, before resource-free broker start."""
        if self._replay_started:
            raise ValueError("replay timing cannot change after start")
        if not isinstance(data, DataBase):
            raise TypeError("replay timing requires an actual DataBase feed")
        if id(data) in self._replay_timings:
            raise ValueError("replay feed timing is already bound")
        if len(self._replay_timings) >= self.MAX_FEEDS:
            raise ValueError("too many replay feeds")
        if not isinstance(timings, (tuple, list)) or not timings:
            raise ValueError("timings must be a nonempty finite tuple or list")
        if len(timings) > self.MAX_TIMINGS_PER_FEED:
            raise ValueError("replay timing capacity exceeded")
        if self._replay_timing_count + len(timings) > self.MAX_TOTAL_TIMINGS:
            raise ValueError("total replay timing capacity exceeded")
        indexed = {}
        previous = None
        for timing in timings:
            if type(timing) is not ReplayBarTiming:
                raise TypeError("timings must contain ReplayBarTiming records")
            if previous is not None and timing.start < previous.end:
                raise ValueError("replay timings must be ordered and nonoverlapping")
            label = date2num(timing.end)
            if label in indexed:
                raise ValueError("duplicate replay datetime label")
            indexed[label] = timing
            previous = timing
        self._replay_timings[id(data)] = (data, MappingProxyType(indexed))
        self._replay_timing_count += len(indexed)

    def current_bar_timing(self, data):
        """Return the current feed's exact record; never infer missing metadata."""
        binding = self._replay_timings.get(id(data))
        if binding is None or binding[0] is not data or not len(data):
            raise ValueError("current replay feed has no bound timing")
        timing = binding[1].get(data.datetime[0])
        if timing is None:
            raise ValueError("current replay datetime is outside the bound schedule")
        return timing

    def _require_regular_matching(self):
        if self.get_param("coc") or self.get_param("coo"):
            raise ValueError("causal replay disallows cheat-on-open/close")

    def current_decision_floor(self):
        """Latest source availability of the exact synchronized bound feeds.

        This is a lower bound, not a replacement for a simulation clock or
        later quote availability. The caller must bind every decision input.
        """
        timings = tuple(self.current_bar_timing(data) for data, _ in self._replay_timings.values())
        if not timings or len({timing.end for timing in timings}) != 1:
            raise ValueError("replay decision inputs are not a synchronized batch")
        return max(timing.available_at for timing in timings)

    def start(self):
        if self._replay_started:
            raise ValueError("a replay broker belongs to one run")
        if not self._replay_timings:
            raise ValueError("replay requires a bound timing schedule")
        self._require_regular_matching()
        self._replay_started = True
        super().start()

    def _reject_replay(self, order, reason):
        self._replay_order_cutoffs.pop(order.ref, None)
        order.addinfo(replay_rejection=reason)
        order.reject(self)
        if not any(existing is order for existing in self.orders):
            self.orders.append(order)
        self.notify(order)
        return order

    def submit(self, order, check=True):
        try:
            self._require_regular_matching()
            if not self._replay_started:
                raise ValueError("replay broker has not started")
            self.current_bar_timing(order.data)
            cutoff = _utc(order.info.get("decision_available_at"), "decision_available_at")
            if cutoff < self.current_decision_floor():
                raise ValueError("decision precedes source availability")
            if order.exectype not in (Order.Market, Order.Limit):
                raise ValueError("unsupported replay order type")
            if order.parent is not None or not order.transmit or order.oco is not None:
                raise ValueError("replay requires a standalone order")
            if order.ref in self._replay_order_cutoffs:
                raise ValueError("replay order was already submitted")
        except (TypeError, ValueError):
            return self._reject_replay(order, "REPLAY_SUBMISSION_TIME_INVALID")
        self._replay_order_cutoffs[order.ref] = (order, order.data, cutoff)
        return super().submit(order, check=check)

    def _try_exec(self, order):
        sealed = self._replay_order_cutoffs.get(order.ref)
        try:
            self._require_regular_matching()
            if sealed is None or sealed[0] is not order or sealed[1] is not order.data:
                raise ValueError("replay order has no sealed timing")
            if _utc(order.info.get("decision_available_at"), "decision_available_at") != sealed[2]:
                raise ValueError("replay decision timing changed after submission")
            timing = self.current_bar_timing(order.data)
        except (TypeError, ValueError):
            self._reject_replay(order, "REPLAY_MATCH_TIME_INVALID")
            return
        if timing.start < sealed[2]:
            return
        super()._try_exec(order)

    def next(self):
        super().next()
        # The parent owns historical orders; this extra index retains only
        # active admission records, including orders awaiting margin checks.
        for ref, (order, _data, _cutoff) in tuple(self._replay_order_cutoffs.items()):
            if not order.alive():
                del self._replay_order_cutoffs[ref]

    def cancel(self, order, bracket=False):
        result = super().cancel(order, bracket=bracket)
        if not order.alive():
            self._replay_order_cutoffs.pop(order.ref, None)
        return result


__all__ = ["CausalReplayBroker", "ReplayBarTiming"]
