"""Fail-closed coordinator for one SDK event batch route.

The SDK batch lease is process-local.  This module coordinates one Store's
dispatch cursor with that exact lease; it does not provide persistence,
producer shutdown proof, or exactly-once business effects.
"""

from __future__ import annotations

from copy import deepcopy
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable


_CONTINUATION_CODES = frozenset(
    {
        "event_batch_scan_budget_exhausted",
        "event_batch_raw_budget_exhausted",
        "event_batch_backlog_pending",
    }
)
_MAX_SDK_EVENT_BATCH_BUDGET = 1024
_SAFE_CODE = re.compile(r"^[a-zA-Z0-9_.-]{1,96}$")


def _require_event_budget(name: str, value: Any) -> int:
    """Reject values which could make the SDK interpret a poll as idle."""

    if type(value) is not int or value < 1 or value > _MAX_SDK_EVENT_BATCH_BUDGET:
        raise ValueError(
            "{} must be an integer from 1 to {}".format(
                name, _MAX_SDK_EVENT_BATCH_BUDGET
            )
        )
    return value


def _require_raw_budget(value: Any) -> int | None:
    """Validate this coordinator's bounded raw-lane budget contract.

    ``None`` follows the SDK's queue-snapshot mode.  The positive scan budget
    still caps work per poll.  Zero is useful for draining already-normalized
    pending inputs, but it cannot make progress on raw queue items.  The
    1024-item ceiling is this Store coordinator's bounded-work contract; the
    SDK itself accepts larger raw budgets.
    """

    if value is None:
        return None
    if (
        type(value) is not int
        or value < 0
        or value > _MAX_SDK_EVENT_BATCH_BUDGET
    ):
        raise ValueError("max_raw_items must be None or an integer from 0 to 1024")
    return value


class StoreEventBatchError(RuntimeError):
    """A finite, safe failure projection for batch coordination."""

    def __init__(
        self,
        code: str,
        *,
        phase: str,
        event_index: int | None = None,
    ) -> None:
        self.code = code
        self.phase = phase
        self.event_index = event_index
        super().__init__(code)


@dataclass(frozen=True)
class StoreEventBatchResult:
    """One bounded drain result; an idle snapshot is not global quiescence."""

    status: str
    venue: str
    dispatched: int = 0
    batch_sequence: int | None = None
    continuation_required: bool = False
    backlog_visible: bool | None = None
    blocked_error_code: str | None = None


class StoreEventBatchCoordinator:
    """Coordinate a single route's opt-in SDK batch consumer.

    Call :meth:`claim` before any legacy poll of this route.  Each successful
    event callback advances a retained in-process cursor.  A callback that
    raises leaves its current event in ``dispatch_unknown`` because some
    Backtrader effects may already have happened.  Such a batch is never
    replayed or acknowledged automatically.

    Likewise, an ACK exception leaves ``ack_unknown``: the ACK may have taken
    effect before the exception.  The coordinator intentionally offers no
    retry or retirement operation.  The Store lifecycle owner must retain the
    coordinator and its API/waker bindings until it has independent producer
    quiescence evidence.  The current SDK close/empty-queue snapshot is not
    such evidence, especially for deferred CTP callbacks.  The scan budget
    bounds input items examined by one call; it does not bound provider
    ``get_data()`` fanout materialized internally by the SDK.
    """

    def __init__(
        self,
        api: Any,
        venue: str,
        *,
        max_raw_items: int | None = 100,
        max_events: int = 100,
        max_scan_items: int = 256,
        coalesce_market_snapshots: Iterable[str] = (),
    ) -> None:
        if type(venue) is not str or not venue:
            raise ValueError("venue must be a non-empty string")
        self.api = api
        self.venue = venue
        self._max_raw_items = _require_raw_budget(max_raw_items)
        self._max_events = _require_event_budget("max_events", max_events)
        self._max_scan_items = _require_event_budget("max_scan_items", max_scan_items)
        self.coalesce_market_snapshots = tuple(coalesce_market_snapshots)
        self._lock = threading.Lock()
        self._state = "new"
        self._token: object | None = None
        self._batch: Any = None
        self._events: tuple[Any, ...] | None = None
        self._next_index = 0
        self._next_expected_batch_sequence = 1
        self._event_epoch: str | None = None
        self._last_error_code: str | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def next_event_index(self) -> int:
        return self._next_index

    @property
    def outstanding_batch(self) -> Any:
        """Return the exact locally retained lease, if one is held."""

        return self._batch

    @property
    def last_error_code(self) -> str | None:
        return self._last_error_code

    @property
    def max_raw_items(self) -> int | None:
        return self._max_raw_items

    @property
    def max_events(self) -> int:
        return self._max_events

    @property
    def max_scan_items(self) -> int:
        return self._max_scan_items

    @staticmethod
    def _error_code(exc: BaseException, fallback: str) -> str:
        code = getattr(exc, "code", None)
        if type(code) is str and _SAFE_CODE.fullmatch(code):
            return code
        return fallback

    def _require_lock(self, phase: str) -> None:
        if not self._lock.acquire(blocking=False):
            raise StoreEventBatchError("store_event_batch_busy", phase=phase)

    def claim(self) -> object:
        """Claim this one route, or retain an unknown claim outcome fail-closed."""

        self._require_lock("claim")
        try:
            if self._state != "new":
                raise StoreEventBatchError("store_event_batch_claim_not_new", phase="claim")
            register = getattr(self.api, "register_event_consumer", None)
            if not callable(register):
                self._state = "claim_blocked"
                self._last_error_code = "batch_consumer_api_unavailable"
                raise StoreEventBatchError(self._last_error_code, phase="claim")
            try:
                token = register(self.venue)
            except BaseException as exc:
                self._state = "claim_unknown"
                self._last_error_code = self._error_code(exc, "batch_consumer_claim_failed")
                self._raise_failure(exc, self._last_error_code, phase="claim")
            if token is None:
                self._state = "claim_unknown"
                self._last_error_code = "batch_consumer_token_missing"
                raise StoreEventBatchError(self._last_error_code, phase="claim")
            self._token = token
            self._state = "claimed"
            return token
        finally:
            self._lock.release()

    def drain_once(
        self,
        dispatch_event: Callable[[str, Any], Any],
        *,
        preflight_events: Callable[[str, tuple[Any, ...]], Any] | None = None,
    ) -> StoreEventBatchResult:
        """Poll at most one batch, dispatch in order, then ACK that exact lease.

        ``dispatch_event`` must return only after the event's Store projection
        has completed.  It should do one event at a time; callers must not hide
        a multi-event partial failure inside one callback.  Continuation
        results are signals for the Store scheduler; this method never loops
        internally.  They do not imply the SDK's total pending memory is
        bounded because provider fanout is materialized before this cursor.
        """

        self._require_lock("drain")
        try:
            if self._state == "new":
                raise StoreEventBatchError("event_consumer_not_registered", phase="poll")
            if self._state != "claimed":
                raise StoreEventBatchError(
                    "store_event_batch_fail_closed", phase=self._state
                )
            if not callable(dispatch_event):
                raise TypeError("dispatch_event must be callable")
            poll = getattr(self.api, "poll_event_batch", None)
            acknowledge = getattr(self.api, "ack_event_batch", None)
            if not callable(poll) or not callable(acknowledge):
                self._state = "poll_blocked"
                self._last_error_code = "batch_poll_api_unavailable"
                raise StoreEventBatchError(self._last_error_code, phase="poll")
            try:
                # Recheck immediately before touching the SDK.  The SDK treats
                # a zero max_events/max_scan_items as an empty result even
                # when backlog remains, so zero must never become Store idle.
                _require_raw_budget(self._max_raw_items)
                _require_event_budget("max_events", self._max_events)
                _require_event_budget("max_scan_items", self._max_scan_items)
            except ValueError:
                self._state = "poll_blocked"
                self._last_error_code = "event_batch_budget_invalid"
                raise StoreEventBatchError(
                    self._last_error_code, phase="poll"
                ) from None
            try:
                batch = poll(
                    self.venue,
                    self._token,
                    max_raw_items=self._max_raw_items,
                    max_events=self._max_events,
                    max_scan_items=self._max_scan_items,
                    coalesce_market_snapshots=self.coalesce_market_snapshots,
                )
            except BaseException as exc:
                code = self._error_code(exc, "batch_poll_failed")
                if code in _CONTINUATION_CODES:
                    if code == "event_batch_raw_budget_exhausted" and self._max_raw_items == 0:
                        # Retrying unchanged would spin without consuming raw
                        # items.  Retain the consumer and report the backlog,
                        # but require an explicit configuration/lifecycle
                        # decision before another poll.
                        self._state = "raw_budget_blocked"
                        self._last_error_code = code
                        return StoreEventBatchResult(
                            status="raw_budget_blocked",
                            venue=self.venue,
                            continuation_required=False,
                            backlog_visible=True,
                            blocked_error_code=code,
                        )
                    return StoreEventBatchResult(
                        status="continuation_required",
                        venue=self.venue,
                        continuation_required=True,
                        backlog_visible=True,
                        blocked_error_code=code,
                    )
                self._state = "poll_blocked"
                self._last_error_code = code
                self._raise_failure(exc, code, phase="poll")
            if batch is None:
                return StoreEventBatchResult(
                    status="idle_snapshot",
                    venue=self.venue,
                    backlog_visible=False,
                )

            self._batch = batch
            try:
                batch_venue = getattr(batch, "exchange_name", None)
                batch_sequence = getattr(batch, "batch_sequence", None)
                batch_epoch = getattr(batch, "event_epoch", None)
                batch_id = getattr(batch, "batch_id", None)
                batch_blocked_error = getattr(batch, "blocked_error_code", None)
                valid_batch = (
                    type(batch_venue) is str
                    and batch_venue == self.venue
                    and type(batch_sequence) is int
                    and batch_sequence == self._next_expected_batch_sequence
                    and type(batch_epoch) is str
                    and bool(batch_epoch)
                    and (self._event_epoch is None or batch_epoch == self._event_epoch)
                    and type(batch_id) is str
                    and bool(batch_id)
                    and (
                        batch_blocked_error is None
                        or (
                            type(batch_blocked_error) is str
                            and _SAFE_CODE.fullmatch(batch_blocked_error)
                        )
                    )
                )
            except BaseException as exc:
                self._state = "batch_binding_blocked"
                self._last_error_code = self._error_code(exc, "batch_binding_invalid")
                self._raise_failure(
                    exc, self._last_error_code, phase="batch_binding"
                )
            if not valid_batch:
                self._state = "batch_binding_blocked"
                self._last_error_code = "event_batch_binding_invalid"
                raise StoreEventBatchError(
                    self._last_error_code, phase="batch_binding"
                )
            if self._event_epoch is None:
                self._event_epoch = batch_epoch
            try:
                # EventBatch.events returns detached copies.  Read it exactly
                # once so retries never change the payload under this cursor.
                events = batch.events
                if type(events) is not tuple:
                    raise TypeError("batch events must be a tuple")
                self._events = events
            except BaseException as exc:
                self._state = "batch_read_unknown"
                self._last_error_code = self._error_code(exc, "batch_copy_failed")
                self._raise_failure(exc, self._last_error_code, phase="batch_copy")

            if preflight_events is not None:
                try:
                    # Contract validation receives an isolated view.  A
                    # validator that annotates or mutates its dictionaries
                    # cannot change the payload subsequently dispatched.
                    preflight_view = tuple(deepcopy(event) for event in self._events)
                    preflight_events(self.venue, preflight_view)
                except BaseException as exc:
                    self._state = "preflight_blocked"
                    self._last_error_code = self._error_code(exc, "batch_preflight_failed")
                    self._raise_failure(exc, self._last_error_code, phase="preflight")

            sequence = batch_sequence
            for index in range(self._next_index, len(self._events)):
                try:
                    dispatch_event(self.venue, self._events[index])
                except BaseException as exc:
                    self._state = "dispatch_unknown"
                    self._last_error_code = self._error_code(exc, "event_dispatch_failed")
                    # Keep next_index on the event whose side effects are
                    # uncertain.  No retry is permitted by this coordinator.
                    self._next_index = index
                    self._raise_failure(
                        exc,
                        self._last_error_code,
                        phase="dispatch_unknown",
                        event_index=index,
                    )
                self._next_index = index + 1

            self._state = "acking"
            try:
                backlog_visible = acknowledge(self.venue, self._token, batch)
                if type(backlog_visible) is not bool:
                    raise TypeError("ACK result must be bool")
            except BaseException as exc:
                self._state = "ack_unknown"
                self._last_error_code = self._error_code(exc, "event_batch_ack_unknown")
                self._raise_failure(
                    exc,
                    self._last_error_code,
                    phase="ack_unknown",
                    event_index=self._next_index,
                )

            blocked_error_code = batch_blocked_error
            dispatched = self._next_index
            self._batch = None
            self._events = None
            self._next_index = 0
            self._next_expected_batch_sequence += 1
            self._state = "claimed"
            return StoreEventBatchResult(
                status=("prefix_acked_blocked" if blocked_error_code else "acked"),
                venue=self.venue,
                dispatched=dispatched,
                batch_sequence=sequence if type(sequence) is int else None,
                # The SDK retained the normalization-failing suffix while
                # leasing this valid prefix.  Schedule its retry on a later
                # bounded turn even if the ACK snapshot was unexpectedly false.
                continuation_required=bool(backlog_visible or blocked_error_code),
                backlog_visible=backlog_visible,
                blocked_error_code=(
                    blocked_error_code if type(blocked_error_code) is str else None
                ),
            )
        finally:
            self._lock.release()

    @staticmethod
    def _raise_failure(
        exc: BaseException,
        code: str,
        *,
        phase: str,
        event_index: int | None = None,
    ) -> None:
        """Preserve process-control exceptions after the fail-closed update."""

        if not isinstance(exc, Exception):
            raise exc
        raise StoreEventBatchError(
            code,
            phase=phase,
            event_index=event_index,
        ) from None


__all__ = (
    "StoreEventBatchCoordinator",
    "StoreEventBatchError",
    "StoreEventBatchResult",
)
