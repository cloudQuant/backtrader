"""Single-owner runtime for queued SDK commands and Broker completions.

The Store owns command identity, route selection, authorization, risk policy,
SDK request execution, and Backtrader projection.  This module owns only the
bounded scheduling and completion state: queue ordering, worker lifecycle,
generation fencing, in-flight/publication accounting, and the completion
inbox.  All provider work is supplied as a callback and is invoked once.

The runtime deliberately has no dependency on Store, Broker, SDK, or provider
types.  Store callbacks that run while a runtime lock is held are limited to
short state bookkeeping.  They must not perform I/O or re-enter the runtime.
The completion inbox lock is always acquired before the command condition.
"""

from __future__ import annotations

import asyncio
import collections
import heapq
import inspect
import threading
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class SdkCommandRuntimeSnapshot:
    """Immutable, payload-free view of queue and completion ownership."""

    generation: int
    worker_generation: int
    queue_depth: int
    inflight: int
    publications_pending: int
    completion_depth: int
    worker_alive: bool
    stop_requested: bool
    accepting_commands: bool
    accepting_openings: bool
    accepting_completions: bool
    restart_blocked_by_worker: bool
    last_error_code: str
    queue_capacity: int
    reserved_capacity: int
    completion_capacity: int
    completion_ingress: int
    completion_delivered: int
    completion_dropped: int
    counters: Tuple[Tuple[str, int], ...]
    command_drop_records: Tuple[Mapping[str, Any], ...]
    completion_drop_records: Tuple[Mapping[str, Any], ...]

    @property
    def has_active_work(self) -> bool:
        """Whether queued, running, reserved, or unpublished work remains."""

        return bool(
            self.queue_depth
            or self.inflight
            or self.publications_pending
            or self.completion_depth
        )

    @property
    def completion_conserved(self) -> bool:
        """Whether every completion update is queued, delivered, or dropped."""

        return self.completion_ingress == (
            self.completion_delivered + self.completion_dropped + self.completion_depth
        )


class SdkCommandRuntime:
    """Own one bounded command worker and its completion inbox.

    ``execute`` receives the exact queued command mapping and may return either
    a mapping or an awaitable mapping.  It is called once per dequeued command;
    this runtime never retries or interprets provider results.  The Store
    supplies request execution, risk callbacks, sanitization, and completion
    projection.
    """

    def __init__(
        self,
        *,
        queue_capacity: int,
        reserved_capacity: int,
        completion_capacity: int,
        drop_record_limit: int,
        shutdown_timeout: float,
        worker_name: str,
        priorities: Mapping[str, int],
        make_unsent_completion: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
        on_command_drop: Callable[[Mapping[str, Any], str], None],
        on_admission_rejected: Callable[[Mapping[str, Any], str], None],
        prepare_update: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        on_completion_drop: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
        signal_update: Callable[[], None],
        worker_error: Callable[[BaseException], str],
        on_worker_failure: Callable[[BaseException, str], None],
        is_execution_unknown: Callable[[Mapping[str, Any]], bool],
        on_execution_unknown: Callable[[str], None],
    ) -> None:
        self._queue_capacity = self._positive_int(queue_capacity, "queue_capacity")
        self._reserved_capacity = min(
            max(self._nonnegative_int(reserved_capacity, "reserved_capacity"), 0),
            max(self._queue_capacity - 1, 0),
        )
        self._completion_capacity = self._positive_int(
            completion_capacity, "completion_capacity"
        )
        self._drop_record_limit = self._positive_int(drop_record_limit, "drop_record_limit")
        if type(shutdown_timeout) not in (int, float) or shutdown_timeout < 0:
            raise ValueError("shutdown_timeout must be a non-negative number")
        if type(worker_name) is not str or not worker_name or worker_name != worker_name.strip():
            raise ValueError("worker_name must be non-empty trimmed text")
        if not isinstance(priorities, Mapping) or not priorities:
            raise TypeError("priorities must be a non-empty mapping")
        selected_priorities = {}
        for name, value in priorities.items():
            if type(name) is not str or not name or name != name.strip():
                raise ValueError("priority names must be non-empty trimmed text")
            if type(value) is not int:
                raise TypeError("priority values must be exact integers")
            selected_priorities[name] = value

        callbacks = {
            "make_unsent_completion": make_unsent_completion,
            "on_command_drop": on_command_drop,
            "on_admission_rejected": on_admission_rejected,
            "prepare_update": prepare_update,
            "on_completion_drop": on_completion_drop,
            "signal_update": signal_update,
            "worker_error": worker_error,
            "on_worker_failure": on_worker_failure,
            "is_execution_unknown": is_execution_unknown,
            "on_execution_unknown": on_execution_unknown,
        }
        if any(not callable(callback) for callback in callbacks.values()):
            raise TypeError("all Store callbacks must be callable")

        self._priorities = selected_priorities
        self._shutdown_timeout = float(shutdown_timeout)
        self._worker_name = worker_name
        self._make_unsent_completion = make_unsent_completion
        self._on_command_drop = on_command_drop
        self._on_admission_rejected = on_admission_rejected
        self._prepare_update = prepare_update
        self._on_completion_drop = on_completion_drop
        self._signal_update = signal_update
        self._worker_error = worker_error
        self._on_worker_failure = on_worker_failure
        self._is_execution_unknown = is_execution_unknown
        self._on_execution_unknown = on_execution_unknown

        # Lock order is completion inbox -> command condition -> Store risk.
        self._completion_lock = threading.Lock()
        self._condition = threading.Condition(threading.RLock())
        self._heap = []
        self._sequence = 0
        self._worker_thread = None
        self._worker_generation = 0
        self._generation = 0
        self._stop_requested = False
        self._accepting_commands = False
        self._accepting_openings = False
        self._accepting_completions = False
        self._restart_blocked_by_worker = False
        self._inflight = 0
        self._publications_pending = 0
        self._inflight_receipt_id = None
        self._inflight_operation = None
        self._health = collections.Counter()
        self._command_drop_records = collections.deque(maxlen=self._drop_record_limit)
        self._last_error_code = ""
        self._completion_updates = collections.deque(maxlen=self._completion_capacity)
        self._completion_ingress = 0
        self._completion_delivered = 0
        self._completion_dropped = 0
        self._completion_drop_records = collections.deque(maxlen=self._drop_record_limit)

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("{} must be an exact positive integer".format(name))
        return value

    @staticmethod
    def _nonnegative_int(value: Any, name: str) -> int:
        if type(value) is not int or value < 0:
            raise ValueError("{} must be an exact non-negative integer".format(name))
        return value

    @property
    def generation(self) -> int:
        with self._condition:
            return self._generation

    @property
    def accepting_openings(self) -> bool:
        with self._condition:
            return self._accepting_openings

    @property
    def restart_blocked_by_worker(self) -> bool:
        with self._condition:
            return self._restart_blocked_by_worker

    def start(self, execute: Callable[[Mapping[str, Any]], Any]) -> int:
        """Start a worker generation, or return the active generation."""

        if not callable(execute):
            raise TypeError("execute must be callable")
        with self._condition:
            worker = self._worker_thread
            if worker is not None and worker.is_alive():
                if self._restart_blocked_by_worker or self._stop_requested:
                    raise RuntimeError("previous SDK command worker is still running")
                return self._generation
            if self._restart_blocked_by_worker:
                raise RuntimeError("SDK command worker recovery is required before restart")
            self._stop_requested = False
            self._accepting_commands = True
            self._generation += 1
            generation = self._generation
            self._worker_generation = generation
            self._accepting_completions = True
            worker = threading.Thread(
                target=self._worker_main,
                args=(generation, execute),
                name=self._worker_name,
                daemon=True,
            )
            self._worker_thread = worker
            worker.start()
            return generation

    def enqueue(self, command: Dict[str, Any], *, priority_name: str) -> Dict[str, Any]:
        """Queue one already-authorized command and return its local receipt."""

        if type(command) is not dict:
            raise TypeError("command must be an exact dict")
        if type(priority_name) is not str or priority_name not in self._priorities:
            raise ValueError("priority_name is not configured")
        operation = str(command.get("operation") or "").strip().lower()
        receipt_id = uuid.uuid4().hex
        command.update(
            receipt_id=receipt_id,
            priority=priority_name,
            enqueued_monotonic_ns=time.monotonic_ns(),
        )
        priority = self._priorities[priority_name]
        is_opening = priority_name == "open"

        with self._condition:
            command["session_generation"] = self._generation
            depth = len(self._heap)
            opening_limit = self._queue_capacity - self._reserved_capacity
            rejection = ""
            if is_opening and not self._accepting_openings:
                rejection = "openings_frozen"
            elif is_opening and depth >= opening_limit:
                rejection = "command_queue_reserved_capacity"
            elif depth >= self._queue_capacity:
                rejection = "command_queue_full"
            elif (
                not self._accepting_commands
                or self._stop_requested
                or self._restart_blocked_by_worker
            ):
                rejection = "command_worker_stopping"

            if rejection:
                receipt = {
                    "kind": "command_receipt",
                    "command": operation,
                    "receipt_id": receipt_id,
                    "bt_order_ref": command.get("bt_order_ref"),
                    "client_order_id": command.get("client_order_id"),
                    "status": "rejected",
                    "queued": False,
                    "priority": priority_name,
                    "queue_depth": depth,
                    "error_code": rejection,
                    "error_msg": "SDK command queue cannot safely accept this command",
                }
                self._health["rejected"] += 1
                self._health["rejected_{}".format(priority_name)] += 1
                if not is_opening:
                    self._health["risk_command_rejected"] += 1
                    self._on_admission_rejected(command, rejection)
            else:
                self._sequence += 1
                heapq.heappush(self._heap, (priority, self._sequence, command))
                depth = len(self._heap)
                receipt = {
                    "kind": "command_receipt",
                    "command": operation,
                    "receipt_id": receipt_id,
                    "bt_order_ref": command.get("bt_order_ref"),
                    "client_order_id": command.get("client_order_id"),
                    "status": "submitted",
                    "queued": True,
                    "priority": priority_name,
                    "queue_depth": depth,
                }
                self._health["enqueued"] += 1
                self._health["enqueued_{}".format(priority_name)] += 1
                self._health["max_queue_depth"] = max(self._health["max_queue_depth"], depth)
                self._condition.notify()
        return receipt

    def wait_for_commands(
        self,
        timeout: Optional[float] = None,
        *,
        stop_on_timeout: bool = False,
    ) -> bool:
        """Wait boundedly for queued, in-flight, and reserved publications."""

        wait_timeout = self._shutdown_timeout if timeout is None else max(float(timeout), 0.0)
        deadline = time.monotonic() + wait_timeout
        with self._condition:
            while self._heap or self._inflight or self._publications_pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._health["drain_timeouts"] += 1
                    if stop_on_timeout:
                        self._stop_requested = True
                        self._accepting_commands = False
                        self._accepting_openings = False
                        self._accepting_completions = False
                        self._discard_pending_locked("shutdown_deadline")
                        self._condition.notify_all()
                    return False
                self._condition.wait(timeout=remaining)
        return True

    def stop(self, timeout: float, *, discard_pending: bool = False) -> bool:
        """Fence new commands/completions and join the worker within timeout."""

        with self._condition:
            self._stop_requested = True
            self._accepting_commands = False
            self._accepting_openings = False
            self._accepting_completions = False
            if discard_pending:
                self._discard_pending_locked("shutdown_deadline")
            self._condition.notify_all()
            worker = self._worker_thread
        if worker is None:
            with self._condition:
                stopped = not (
                    self._heap or self._inflight or self._publications_pending
                )
                if not stopped:
                    self._restart_blocked_by_worker = True
                return stopped
        worker.join(max(float(timeout), 0.0))
        with self._condition:
            stopped = bool(
                not worker.is_alive()
                and not self._heap
                and not self._inflight
                and not self._publications_pending
            )
            if stopped:
                if self._worker_thread is worker:
                    self._worker_thread = None
            else:
                self._restart_blocked_by_worker = True
                self._health["worker_stop_timeouts"] += 1
            self._condition.notify_all()
        return stopped

    def remove_one(
        self,
        predicate: Callable[[Mapping[str, Any]], bool],
        reason: str,
        *,
        on_remove: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Atomically remove one unique queued command and reserve publication."""

        if not callable(predicate):
            raise TypeError("predicate must be callable")
        with self._condition:
            matches = [
                index
                for index, (_, _, command) in enumerate(self._heap)
                if predicate(command)
            ]
            if len(matches) != 1:
                return None
            index = matches[0]
            _, _, command = self._heap.pop(index)
            heapq.heapify(self._heap)
            self._record_command_drop_locked(command, reason)
            if on_remove is not None:
                on_remove(command)
            self._health["dequeued"] += 1
            self._health["cancelled_opening_before_send"] += 1
            self._publications_pending += 1
            self._condition.notify_all()
            return command

    def reject_matching(
        self,
        predicate: Callable[[Mapping[str, Any]], bool],
        reason: str,
        *,
        reserve_publications: bool = False,
    ) -> Tuple[Dict[str, Any], ...]:
        """Remove all matching unsent commands while preserving queue order."""

        if not callable(predicate):
            raise TypeError("predicate must be callable")
        rejected = []
        with self._condition:
            retained = []
            while self._heap:
                item = heapq.heappop(self._heap)
                command = item[2]
                if predicate(command):
                    self._record_command_drop_locked(command, reason)
                    rejected.append(command)
                else:
                    retained.append(item)
            for item in retained:
                heapq.heappush(self._heap, item)
            if reserve_publications:
                self._publications_pending += len(rejected)
            self._condition.notify_all()
        return tuple(rejected)

    def freeze_openings(
        self,
        reason: str,
        *,
        reject_pending: bool = True,
        reserve_publications: bool = False,
        execution_unknown: bool = False,
    ) -> Tuple[Dict[str, Any], ...]:
        """Close the opening gate and optionally discard all unsent openings.

        If ``execution_unknown`` is true, the injected risk callback runs while
        the command condition is held so its Store-side risk latch is atomic
        with closing this admission gate.  It must only update risk
        bookkeeping; network and user callbacks belong outside the runtime
        lock. Other freezes do not create a new risk incident.
        """

        if type(execution_unknown) is not bool:
            raise TypeError("execution_unknown must be an exact bool")
        reason = self._safe_reason(reason)
        with self._condition:
            self._accepting_openings = False
            if execution_unknown:
                self._on_execution_unknown(reason)
            rejected = []
            if reject_pending:
                retained = []
                while self._heap:
                    item = heapq.heappop(self._heap)
                    command = item[2]
                    if command.get("priority") == "open":
                        self._record_command_drop_locked(
                            command, "openings_frozen_after_unknown"
                        )
                        rejected.append(command)
                    else:
                        retained.append(item)
                for item in retained:
                    heapq.heappush(self._heap, item)
                self._health["dequeued"] += len(rejected)
                if reserve_publications:
                    self._publications_pending += len(rejected)
            self._condition.notify_all()
            return tuple(rejected)

    def publish_update(self, update: Mapping[str, Any]) -> bool:
        """Append one sanitized Broker completion/event to the owned inbox."""

        if not isinstance(update, Mapping):
            raise TypeError("update must be a mapping")
        safe_update = self._prepare_update(dict(update))
        if not isinstance(safe_update, Mapping):
            raise TypeError("prepare_update must return a mapping")
        safe_update = dict(safe_update)
        accepted = True
        with self._completion_lock:
            self._completion_ingress += 1
            self._health["broker_update_ingress"] += 1
            if safe_update.get("kind") == "command_completion":
                with self._condition:
                    generation = safe_update.get("session_generation")
                    if not self._accepting_completions:
                        self._record_completion_drop_locked(
                            safe_update, "session_not_accepting"
                        )
                        accepted = False
                    elif generation != self._generation:
                        self._record_completion_drop_locked(
                            safe_update, "stale_session_generation"
                        )
                        accepted = False
            if accepted:
                self._append_completion_locked(safe_update)
        if accepted:
            self._signal_update()
        return accepted

    def record_drop(self, update: Any, reason: str) -> None:
        """Account for a received update rejected before inbox publication.

        The rejected payload is never queued or signaled to Broker consumers.
        A sanitized projection is prepared first, then ingress and dropped are
        incremented together under the inbox lock and the same Store risk/drop
        callback used by ordinary inbox losses is invoked. If sanitization
        fails, only a fixed marker is passed to the drop callback and the
        reason is replaced with a finite projection failure code.
        """

        safe_reason = self._safe_reason(reason)
        source = dict(update) if isinstance(update, Mapping) else {
            "kind": "unverified_sdk_execution_event"
        }
        try:
            prepared = self._prepare_update(source)
        except Exception:
            prepared = None
        if not isinstance(prepared, Mapping):
            prepared = {"kind": "unverified_sdk_execution_event"}
            safe_reason = "sdk_update_projection_failed"
        safe_update = dict(prepared)
        with self._completion_lock:
            self._completion_ingress += 1
            self._health["broker_update_ingress"] += 1
            self._record_completion_drop_locked(safe_update, safe_reason)

    def pop_update(self) -> Optional[Dict[str, Any]]:
        """Remove and account for the next Broker update, if present."""

        with self._completion_lock:
            if not self._completion_updates:
                return None
            update = self._completion_updates.popleft()
            self._completion_delivered += 1
            self._health["broker_update_delivered"] += 1
            return update

    def clear_updates(self, reason: str) -> int:
        """Drop all queued Broker updates and preserve ingress conservation."""

        with self._completion_lock:
            count = 0
            while self._completion_updates:
                update = self._completion_updates.popleft()
                self._record_completion_drop_locked(update, reason)
                count += 1
            return count

    def reserve_publications(self, count: int = 1) -> None:
        """Reserve a queue-removal-to-inbox publication window."""

        count = self._nonnegative_int(count, "count")
        with self._condition:
            self._publications_pending += count
            self._condition.notify_all()

    def release_publications(self, count: int = 1) -> None:
        """Release a previously reserved publication window."""

        count = self._nonnegative_int(count, "count")
        with self._condition:
            if count > self._publications_pending:
                raise ValueError("publication release exceeds pending reservations")
            self._publications_pending -= count
            self._condition.notify_all()

    def set_accept_openings(self, enabled: bool) -> None:
        """Set the Store-directed opening admission gate."""

        if type(enabled) is not bool:
            raise TypeError("enabled must be an exact bool")
        with self._condition:
            self._accepting_openings = enabled
            self._condition.notify_all()

    def set_accepting_commands(self, enabled: bool) -> None:
        """Set lifecycle admission independently of Store route checks."""

        if type(enabled) is not bool:
            raise TypeError("enabled must be an exact bool")
        with self._condition:
            self._accepting_commands = enabled
            self._condition.notify_all()

    def enable_openings_if(self, safety_check: Callable[[], bool]) -> bool:
        """Enable openings only from an idle, conserved, Store-approved state.

        The fixed lock order is completion inbox, command condition, then the
        Store risk lock taken by ``safety_check``.  The callback must be a
        bounded read-only check and must return the exact boolean ``True``.
        """

        if not callable(safety_check):
            raise TypeError("safety_check must be callable")
        with self._completion_lock:
            with self._condition:
                conserved = self._completion_ingress == (
                    self._completion_delivered
                    + self._completion_dropped
                    + len(self._completion_updates)
                )
                runtime_idle = not (
                    self._heap
                    or self._inflight
                    or self._publications_pending
                    or self._completion_updates
                )
                allowed = runtime_idle and conserved and safety_check() is True
                self._accepting_openings = bool(allowed)
                self._condition.notify_all()
                return bool(allowed)

    def increment_health(self, name: str, amount: int = 1) -> int:
        """Increment one runtime-owned health counter."""

        self._validate_counter_name(name)
        if type(amount) is not int:
            raise TypeError("amount must be an exact integer")
        with self._condition:
            self._health[name] += amount
            if self._health[name] < 0:
                self._health[name] -= amount
                raise ValueError("health counters cannot become negative")
            return self._health[name]

    def set_health(self, name: str, value: int) -> None:
        """Set one runtime-owned health counter."""

        self._validate_counter_name(name)
        if type(value) is not int or value < 0:
            raise ValueError("value must be an exact non-negative integer")
        with self._condition:
            self._health[name] = value

    def set_last_error(self, code: str) -> None:
        """Set the finite worker/command error projection."""

        if type(code) is not str:
            raise TypeError("code must be exact text")
        if code:
            code = self._safe_reason(code)
        with self._condition:
            self._last_error_code = code

    def has_active_work(self) -> bool:
        """Return whether any queue, worker, publication, or inbox work exists."""

        return self.snapshot().has_active_work

    def reset_after_recovery(self) -> None:
        """Clear generation-local state after Store proves API recovery safe."""

        with self._completion_lock:
            with self._condition:
                worker = self._worker_thread
                if worker is not None and worker.is_alive():
                    raise RuntimeError("cannot reset while command worker is alive")
                if self._heap or self._inflight or self._publications_pending:
                    raise RuntimeError("cannot reset while command work remains")
                self._worker_thread = None
                self._worker_generation = 0
                self._stop_requested = False
                self._accepting_commands = False
                self._accepting_openings = False
                self._accepting_completions = False
                self._restart_blocked_by_worker = False
                self._inflight_receipt_id = None
                self._inflight_operation = None
                self._condition.notify_all()
            while self._completion_updates:
                update = self._completion_updates.popleft()
                self._record_completion_drop_locked(update, "session_restart")

    def snapshot(self) -> SdkCommandRuntimeSnapshot:
        """Return a coherent immutable snapshot without command payloads."""

        with self._completion_lock:
            with self._condition:
                worker = self._worker_thread
                return SdkCommandRuntimeSnapshot(
                    generation=self._generation,
                    worker_generation=self._worker_generation,
                    queue_depth=len(self._heap),
                    inflight=self._inflight,
                    publications_pending=self._publications_pending,
                    completion_depth=len(self._completion_updates),
                    worker_alive=bool(worker and worker.is_alive()),
                    stop_requested=self._stop_requested,
                    accepting_commands=self._accepting_commands,
                    accepting_openings=self._accepting_openings,
                    accepting_completions=self._accepting_completions,
                    restart_blocked_by_worker=self._restart_blocked_by_worker,
                    last_error_code=self._last_error_code,
                    queue_capacity=self._queue_capacity,
                    reserved_capacity=self._reserved_capacity,
                    completion_capacity=self._completion_capacity,
                    completion_ingress=self._completion_ingress,
                    completion_delivered=self._completion_delivered,
                    completion_dropped=self._completion_dropped,
                    counters=tuple(
                        sorted((str(key), int(value)) for key, value in self._health.items())
                    ),
                    command_drop_records=tuple(
                        MappingProxyType(dict(row)) for row in self._command_drop_records
                    ),
                    completion_drop_records=tuple(
                        MappingProxyType(dict(row)) for row in self._completion_drop_records
                    ),
                )

    def health(self) -> Dict[str, Any]:
        """Return a finite mapping compatible with existing Store health keys."""

        snapshot = self.snapshot()
        counters = dict(snapshot.counters)
        return {
            **counters,
            "queue_capacity": snapshot.queue_capacity,
            "reserved_capacity": snapshot.reserved_capacity,
            "queue_depth": snapshot.queue_depth,
            "inflight": snapshot.inflight,
            "publications_pending": snapshot.publications_pending,
            "accepting_openings": snapshot.accepting_openings,
            "accepting_commands": snapshot.accepting_commands,
            "worker_alive": snapshot.worker_alive,
            "last_error_code": snapshot.last_error_code,
            "session_generation": snapshot.generation,
            "worker_generation": snapshot.worker_generation,
            "stop_requested": snapshot.stop_requested,
            "accepting_completions": snapshot.accepting_completions,
            "restart_blocked_by_worker": snapshot.restart_blocked_by_worker,
            "completion_queue_capacity": snapshot.completion_capacity,
            "broker_update_queue_depth": snapshot.completion_depth,
            "broker_update_ingress": snapshot.completion_ingress,
            "broker_update_delivered": snapshot.completion_delivered,
            "broker_update_dropped": snapshot.completion_dropped,
            "broker_update_conservation": snapshot.completion_conserved,
            "command_drop_records": [dict(row) for row in snapshot.command_drop_records],
            "broker_update_drop_records": [
                dict(row) for row in snapshot.completion_drop_records
            ],
        }

    def _worker_main(
        self,
        generation: int,
        execute: Callable[[Mapping[str, Any]], Any],
    ) -> None:
        try:
            asyncio.run(self._worker_loop(generation, execute))
        except Exception as error:
            try:
                code = self._worker_error(error)
            except Exception:
                code = "command_worker_failed"
            if not (
                type(code) is str
                and 0 < len(code) <= 128
                and code == code.strip()
                and code.isprintable()
            ):
                code = "command_worker_failed"
            with self._condition:
                self._health["worker_failures"] += 1
                self._last_error_code = code
            try:
                self._on_worker_failure(error, code)
            except Exception:
                # The worker failure projection is diagnostic; it cannot
                # overwrite the original worker failure or start a new call.
                pass
        finally:
            with self._condition:
                self._condition.notify_all()

    async def _worker_loop(
        self,
        generation: int,
        execute: Callable[[Mapping[str, Any]], Any],
    ) -> None:
        while True:
            local_completion = None
            command = None
            with self._condition:
                while not self._heap and not self._stop_requested:
                    self._condition.wait(timeout=0.05)
                if self._stop_requested:
                    return
                _, _, command = heapq.heappop(self._heap)
                if command.get("session_generation") != generation:
                    self._record_command_drop_locked(command, "stale_session_generation")
                    continue
                if command.get("priority") == "open" and not self._accepting_openings:
                    self._record_command_drop_locked(command, "openings_frozen_before_send")
                    self._health["dequeued"] += 1
                    self._publications_pending += 1
                    local_completion = command
                else:
                    self._health["dequeued"] += 1
                    self._inflight += 1
                    self._inflight_receipt_id = command.get("receipt_id")
                    self._inflight_operation = command.get("operation")

            if local_completion is not None:
                try:
                    projected = self._make_unsent_completion(
                        local_completion, "openings_frozen_before_send"
                    )
                    self.publish_update(projected)
                finally:
                    self.release_publications()
                continue

            try:
                result = execute(command)
                completion = await result if inspect.isawaitable(result) else result
                if not isinstance(completion, Mapping):
                    raise TypeError("command executor must return a completion mapping")
                is_unknown = self._is_execution_unknown(completion)
                if type(is_unknown) is not bool:
                    raise TypeError("is_execution_unknown must return an exact bool")
                if is_unknown:
                    reason = self._safe_reason(completion.get("error_code"))
                    rejected = self.freeze_openings(reason, execution_unknown=True)
                else:
                    rejected = ()
                self.publish_update(completion)
                if rejected:
                    for pending in rejected:
                        local = self._make_unsent_completion(
                            pending, "openings_frozen_after_unknown"
                        )
                        self.publish_update(local)
            finally:
                with self._condition:
                    self._inflight -= 1
                    if self._inflight_receipt_id == command.get("receipt_id"):
                        self._inflight_receipt_id = None
                        self._inflight_operation = None
                    self._condition.notify_all()

    def _discard_pending_locked(self, reason: str) -> int:
        count = 0
        while self._heap:
            _, _, command = heapq.heappop(self._heap)
            self._record_command_drop_locked(command, reason)
            count += 1
        return count

    def _record_command_drop_locked(self, command: Mapping[str, Any], reason: str) -> None:
        reason = self._safe_reason(reason)
        self._on_command_drop(command, reason)
        priority = str(command.get("priority") or "unknown")
        self._health["discarded_unsent"] += 1
        self._health["discarded_{}".format(priority)] += 1
        if priority != "open":
            self._health["risk_command_rejected"] += 1
        self._command_drop_records.append(
            self._safe_project(
                {
                    "reason": str(reason),
                    "command": str(command.get("operation") or ""),
                    "bt_order_ref": command.get("bt_order_ref"),
                    "client_order_id": command.get("client_order_id"),
                    "exchange_name": command.get("venue"),
                    "session_generation": command.get("session_generation"),
                }
            )
        )

    def _record_completion_drop_locked(self, update: Mapping[str, Any], reason: str) -> None:
        reason = self._safe_reason(reason)
        record = self._on_completion_drop(update, reason)
        if not isinstance(record, Mapping):
            raise TypeError("on_completion_drop must return a mapping")
        self._completion_dropped += 1
        self._health["broker_update_dropped"] += 1
        if reason in {"session_not_accepting", "stale_session_generation"}:
            self._health["late_completion_dropped"] += 1
        self._completion_drop_records.append(self._safe_project(record))

    def _append_completion_locked(self, update: Dict[str, Any]) -> None:
        if len(self._completion_updates) >= self._completion_capacity:
            evicted = self._completion_updates.popleft()
            self._record_completion_drop_locked(evicted, "broker_update_queue_overflow")
        self._completion_updates.append(update)

    def _safe_project(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        projected = self._prepare_update(dict(value))
        if not isinstance(projected, Mapping):
            raise TypeError("prepare_update must return a mapping")
        return dict(projected)

    @staticmethod
    def _validate_counter_name(name: str) -> None:
        if type(name) is not str or not name or name != name.strip():
            raise ValueError("counter name must be non-empty trimmed text")

    @staticmethod
    def _safe_reason(value: Any) -> str:
        if (
            type(value) is str
            and 0 < len(value) <= 128
            and value == value.strip()
            and value.isprintable()
        ):
            return value
        return "execution_unknown"


__all__ = ("SdkCommandRuntime", "SdkCommandRuntimeSnapshot")
