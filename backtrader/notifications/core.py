"""Delivery core: per-channel workers, rate limiting, retries, dedup (D32-06/D32-07).

Concurrency model: **one daemon worker thread plus one bounded queue per channel
instance**. Messages are delivered serially within a channel (ordering, rate
limiting and retries all happen on that thread) while channels never block each
other - a throttled DingTalk robot cannot delay an urgent Telegram alert.

Anything a worker does must stay invisible to the caller: failures are
classified into :data:`ERROR_CATEGORIES` and returned, never raised, and the
enqueue path never blocks the trading loop.
"""

import collections
import queue
import random
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..utils.log_message import get_logger, throttled_warning
from .channels import Attempt
from .security import mask_text

logger = get_logger("notifications")

# The authoritative error-category set (design D32-05). Requirement FR32-09 and
# every acceptance case reference this tuple instead of keeping a second list.
ERROR_CATEGORIES = (
    "network",
    "timeout",
    "tls",
    "server",
    "auth",
    "rate_limit",
    "permission",
    "not_bound",
    "not_configured",
    "bad_request",
    "deduped",
    "dropped",
    "worker_silent",
    "unknown",
)

# Categories worth another attempt (design D32-07). Auth, permission, bad
# request, not_bound and deduped are deliberately excluded: retrying cannot help
# and would burn channel quota.
RETRYABLE_CATEGORIES = frozenset({"network", "timeout", "tls", "server", "rate_limit"})

OVERFLOW_DROP_NEWEST = "drop_newest"
OVERFLOW_DROP_OLDEST = "drop_oldest"

_SENTINEL = object()

# Polling granularity for ``flush``.
_FLUSH_POLL_SECONDS = 0.01


@dataclass(frozen=True)
class ChannelOutcome:
    """Per-channel result of one send call.

    Attributes:
        channel: Channel instance name (``dingtalk`` or ``dingtalk#2``).
        ok: Whether the channel accepted the message (async: enqueued).
        error_category: One of :data:`ERROR_CATEGORIES`, or ``None``.
        error: Masked, readable diagnostic.
        attempts: Number of delivery attempts made.
        elapsed_ms: Wall-clock duration in milliseconds.
    """

    channel: str
    ok: bool
    error_category: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class SendResult:
    """Result of a ``send_message`` call.

    Attributes:
        accepted: At least one target channel accepted the message.
        mode: ``async`` or ``sync``.
        outcomes: Per-channel results (async: enqueue results; sync: delivery
            results).
        dropped: At least one target channel dropped the message.
        reason: ``ok``, ``not_configured``, ``no_channels``, ``queue_full`` ...
    """

    accepted: bool
    mode: str
    outcomes: Tuple[ChannelOutcome, ...] = ()
    dropped: bool = False
    reason: Optional[str] = None


class _RateLimiter:
    """Sliding-window limiter with an optional per-minute and per-second window."""

    def __init__(self, per_minute, per_second, scale, now=time.monotonic):
        """Store the effective thresholds.

        Args:
            per_minute: Official per-minute limit, or ``None``.
            per_second: Official per-second limit, or ``None``.
            scale: Local headroom factor applied to both thresholds.
            now: Clock function (injectable for tests).
        """
        self._now = now
        self._windows = []
        if per_minute:
            self._windows.append((max(1, int(per_minute * scale)), 60.0))
        if per_second:
            self._windows.append((max(1.0, round(per_second * scale, 1)), 1.0))
        self._stamps: List[List[float]] = [[] for _ in self._windows]

    def _prune(self, index, now):
        """Drop stamps that fell out of the window.

        Args:
            index: Window index.
            now: Current clock value.
        """
        stamps = self._stamps[index]
        window = self._windows[index][1]
        cutoff = now - window
        while stamps and stamps[0] <= cutoff:
            stamps.pop(0)

    def wait_time(self):
        """Return how long to wait before the next send is allowed.

        Returns:
            float: ``0.0`` when a send is allowed now, else seconds to wait.
        """
        now = self._now()
        wait = 0.0
        for index, (limit, window) in enumerate(self._windows):
            self._prune(index, now)
            stamps = self._stamps[index]
            if len(stamps) >= limit:
                wait = max(wait, stamps[0] + window - now)
        return max(0.0, wait)

    def record(self):
        """Record that a send just happened."""
        now = self._now()
        for index in range(len(self._windows)):
            self._prune(index, now)
            self._stamps[index].append(now)


class _ChannelRuntime:
    """Per-instance delivery machinery: queue, worker, limiter and stats."""

    def __init__(self, name, spec, driver, options):
        """Create the queue, limiter and stats for one channel instance.

        Args:
            name: Instance name (``dingtalk`` / ``dingtalk#2``).
            spec: The channel spec.
            driver: Object exposing ``deliver(notification, timeout)``.
            options: Resolved core options mapping.
        """
        self.name = name
        self.spec = spec
        self.driver = driver
        self.queue: "queue.Queue" = queue.Queue(maxsize=options["queue_size"])
        self.limiter = _RateLimiter(
            spec.rate_limit[0] if spec.rate_limit else None,
            spec.rate_limit[1] if spec.rate_limit else None,
            options["rate_limit_scale"],
        )
        self._options = options
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = None
        # Message currently being sent; lets the shutdown drain re-send it if the
        # daemon worker froze after dequeueing it.
        self._inflight = None
        self._stats = {
            "sent": 0,
            "failed": 0,
            "retried": 0,
            "dropped": 0,
            "deduped": 0,
            "rate_waited_ms": 0.0,
            "truncated": 0,
        }

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Start the daemon worker thread for this instance."""
        self._worker = threading.Thread(
            target=self._run, name="bt-notify-{0}".format(self.name), daemon=True
        )
        self._worker.start()

    def stop(self, timeout=5.0):
        """Discard pending work and stop the worker.

        Pending messages are dropped *before* the sentinel is enqueued: the
        sentinel must survive in the queue for the worker to observe, otherwise
        a worker parked in ``get()`` would never exit.

        Args:
            timeout: Seconds to wait for the worker to exit.

        Returns:
            int: Number of queued messages discarded.
        """
        discarded = self.drain()
        self._stop.set()
        try:
            self.queue.put_nowait(_SENTINEL)
        except queue.Full:  # pragma: no cover - drain() just emptied the queue
            pass
        if self._worker is not None:
            self._worker.join(timeout)
            self._worker = None
        inflight, self._inflight = self._inflight, None
        if inflight is not None:
            self.count("dropped")
            discarded += 1
        return discarded

    def drain(self):
        """Empty the queue, counting what was discarded.

        Returns:
            int: Number of discarded messages.
        """
        discarded = 0
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            self.queue.task_done()
            if item is _SENTINEL:
                continue
            discarded += 1
        if discarded:
            self.count("dropped", discarded)
        return discarded

    def _run(self):
        """Worker loop: pull, deliver, log; never raise."""
        while True:
            item = self.queue.get()
            try:
                if item is _SENTINEL:
                    return
                if self._stop.is_set():
                    # Handing the message back keeps it reachable for the shutdown
                    # drain (or for stop(), which counts it as dropped); returning
                    # here would lose it silently.
                    if item is not None:
                        self._inflight = item
                    return
                self._log_outcome(self._process(item))
            finally:
                self.queue.task_done()

    def _process(self, notification, timeout=None):
        """Deliver one message, absorbing every failure.

        The notification is published as "in flight" while being sent so the
        interpreter-shutdown drain can re-send it: a daemon worker may already
        have dequeued a message and then be frozen by interpreter finalization,
        which would otherwise lose that one message even though the queue drained.

        Args:
            notification: Message to deliver.

        Returns:
            ChannelOutcome: The outcome.
        """
        self._inflight = notification
        try:
            try:
                return self.deliver(notification, timeout=timeout)
            except Exception as exc:  # a worker must never die on one message
                self.count("failed")
                detail = mask_text("{0}: {1}".format(type(exc).__name__, exc))
                logger.error("notification worker error channel=%s error=%s", self.name, detail)
                return ChannelOutcome(
                    channel=self.name, ok=False, error_category="unknown", error=detail
                )
        finally:
            self._inflight = None

    def _log_outcome(self, outcome):
        """Log one delivery outcome at a level matching its severity.

        Args:
            outcome: The channel outcome.
        """
        if not self._options["log_events"]:
            return
        if outcome.ok:
            logger.debug(
                "notification delivered channel=%s attempts=%d elapsed_ms=%.1f",
                outcome.channel,
                outcome.attempts,
                outcome.elapsed_ms,
            )
        elif outcome.error_category in ("auth", "permission"):
            logger.error(
                "notification rejected channel=%s category=%s error=%s",
                outcome.channel,
                outcome.error_category,
                outcome.error,
            )
        else:
            logger.warning(
                "notification failed channel=%s category=%s error=%s",
                outcome.channel,
                outcome.error_category,
                outcome.error,
            )

    # -- delivery ----------------------------------------------------------

    def deliver(self, notification, timeout=None):
        """Deliver one notification with rate limiting and bounded retries.

        Args:
            notification: Message to deliver.
            timeout: Per-call request timeout override; falls back to the
                configured ``request_timeout``.

        Returns:
            ChannelOutcome: The classified outcome.
        """
        started = time.monotonic()
        attempts = 0
        truncated = False
        attempt = Attempt(False, "unknown", "not attempted")
        request_timeout = self._options["request_timeout"] if timeout is None else float(timeout)
        while True:
            wait = self.limiter.wait_time()
            if wait > 0:
                if wait > self._options["rate_limit_wait_timeout"]:
                    self.count("failed")
                    return ChannelOutcome(
                        channel=self.name,
                        ok=False,
                        error_category="rate_limit",
                        error="local rate limit wait exceeded {0:.1f}s".format(
                            self._options["rate_limit_wait_timeout"]
                        ),
                        attempts=attempts,
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    )
                self._add_wait_stat(wait)
                if self._sleep(wait):
                    break
            attempts += 1
            attempt = self.driver.deliver(notification, request_timeout)
            self.limiter.record()
            truncated = truncated or attempt.truncated
            if attempt.ok:
                break
            if (
                attempt.category in RETRYABLE_CATEGORIES
                and attempts <= self._options["max_retries"]
            ):
                self.count("retried")
                if self._sleep(self._retry_delay(attempt, attempts)):
                    break
                continue
            break
        return self._finalise(attempt, attempts, started, truncated)

    def _sleep(self, seconds):
        """Sleep unless the runtime is shutting down.

        Args:
            seconds: Requested delay.

        Returns:
            bool: ``True`` when the wait was interrupted by shutdown.
        """
        return self._stop.wait(seconds)

    def _add_wait_stat(self, seconds):
        """Accumulate rate-limit wait time.

        Args:
            seconds: Seconds waited.
        """
        with self._lock:
            self._stats["rate_waited_ms"] += seconds * 1000.0

    def _retry_delay(self, attempt, attempts):
        """Compute the delay before the next attempt.

        Args:
            attempt: The failed attempt.
            attempts: Number of attempts already made.

        Returns:
            float: Seconds to wait.
        """
        if attempt.retry_after is not None:
            return max(0.0, float(attempt.retry_after) + 0.2)
        base = self._options["retry_backoff"] * (2 ** (attempts - 1))
        return base + random.uniform(0, base / 2.0)  # nosec B311 - retry jitter only

    def _finalise(self, attempt, attempts, started, truncated):
        """Record stats and build the outcome.

        Args:
            attempt: The last attempt.
            attempts: Number of attempts made.
            started: ``time.monotonic()`` at the start.
            truncated: Whether the body was truncated.

        Returns:
            ChannelOutcome: The outcome.
        """
        if truncated:
            self.count("truncated")
        self.count("sent" if attempt.ok else "failed")
        return ChannelOutcome(
            channel=self.name,
            ok=attempt.ok,
            error_category=None if attempt.ok else (attempt.category or "unknown"),
            error=None if attempt.ok else mask_text(attempt.error or ""),
            attempts=attempts,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    # -- queue and stats ---------------------------------------------------

    def count(self, key, amount=1):
        """Increment one statistic under the instance lock.

        Args:
            key: Statistic name.
            amount: Increment amount.
        """
        with self._lock:
            self._stats[key] += amount

    def note_deduped(self):
        """Record one deduplicated (suppressed) send."""
        self.count("deduped")

    def enqueue(self, notification):
        """Queue a notification without blocking.

        Under ``drop_oldest`` the oldest queued message is evicted to make room;
        the evicted message is counted as dropped while the *new* message is
        reported as accepted, because it is the one that will be delivered.

        Args:
            notification: Message to queue.

        Returns:
            ChannelOutcome: ``ok=True`` when enqueued, ``dropped`` when the
            message itself could not be queued.
        """
        try:
            self.queue.put_nowait(notification)
        except queue.Full:
            if self._options["overflow"] == OVERFLOW_DROP_OLDEST:
                evicted = False
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                    evicted = True
                except queue.Empty:  # pragma: no cover - race guard
                    pass
                if evicted:
                    try:
                        self.queue.put_nowait(notification)
                    except queue.Full:  # pragma: no cover - race guard
                        pass
                    else:
                        # The evicted message is the one that was dropped.
                        self.count("dropped")
                        self.note_dropped()
                        return ChannelOutcome(channel=self.name, ok=True)
            self.count("dropped")
            self.note_dropped()
            return ChannelOutcome(
                channel=self.name, ok=False, error_category="dropped", error="queue full"
            )
        return ChannelOutcome(channel=self.name, ok=True)

    def note_dropped(self):
        """Emit one throttled warning about a queue overflow."""
        throttled_warning(
            logger,
            "notify-queue-full",
            "notification queue full channel=%s; message dropped",
            self.name,
        )

    def flush(self, timeout):
        """Wait until this instance's queue is empty.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            bool: Whether the queue drained in time.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while self.queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(_FLUSH_POLL_SECONDS)
        return True

    def deliver_pending(self, deadline):
        """Send still-queued messages inline, skipping waits (shutdown path).

        Sets the stop flag first so rate-limit and retry waits return
        immediately: at interpreter exit nothing may block, and the daemon
        worker is already unable to run.

        Args:
            deadline: ``time.monotonic()`` value after which sending stops.

        Returns:
            int: Number of messages sent.
        """
        self._stop.set()
        try:
            self.queue.put_nowait(_SENTINEL)
        except queue.Full:  # pragma: no cover - drain below reclaims room
            pass
        worker, self._worker = self._worker, None
        if worker is not None:
            # Retire the worker before sending inline: two senders racing on one
            # queue would otherwise duplicate or strand messages.
            worker.join(max(0.0, min(1.0, deadline - time.monotonic())))
        sent = 0
        inflight = self._inflight
        self._inflight = None
        if inflight is not None:
            self._log_outcome(self._process(inflight))
            sent += 1
        while time.monotonic() < deadline:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            self.queue.task_done()
            if item is _SENTINEL:
                continue
            self._log_outcome(self._process(item))
            sent += 1
        return sent

    def stats_snapshot(self):
        """Return a copy of this instance's statistics.

        Returns:
            dict: Statistic name to value.
        """
        with self._lock:
            return dict(self._stats)

    def clear_stats(self):
        """Reset this instance's statistics to zero."""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0.0 if isinstance(self._stats[key], float) else 0


class Notifier:
    """Owns every channel runtime and dispatches notifications to them."""

    def __init__(self, resolved_channels, options, transport, smtp_sender):
        """Build channel runtimes and start their workers.

        Args:
            resolved_channels: Sequence of mappings with ``name``, ``spec`` and
                ``driver`` (built and validated by ``config.py``).
            options: Resolved core options.
            transport: HTTP transport (stored for session helpers).
            smtp_sender: SMTP sender (stored for the email driver).

        Raises:
            Exception: Re-raises construction failures after stopping any
                runtime already started, so a failed reconfigure leaves no
                orphan threads behind.
        """
        self._options = dict(options)
        self._lock = threading.RLock()
        self._dedup = {}
        self._runtimes = collections.OrderedDict()
        self.transport = transport
        self.smtp_sender = smtp_sender
        started: List[_ChannelRuntime] = []
        try:
            for resolved in resolved_channels:
                runtime = _ChannelRuntime(
                    resolved["name"], resolved["spec"], resolved["driver"], self._options
                )
                self._runtimes[resolved["name"]] = runtime
                started.append(runtime)
        except Exception:
            for runtime in started:
                runtime.stop(self._options["request_timeout"])
            raise
        for runtime in started:
            runtime.start()

    def __repr__(self):
        """Return a credential-free representation."""
        return "Notifier(channels={0})".format(tuple(self._runtimes))

    def instance_names(self):
        """Return the ordered channel instance names.

        Returns:
            tuple: Instance names.
        """
        return tuple(self._runtimes)

    def find_instance(self, channel_id):
        """Return the first runtime matching a channel id.

        Args:
            channel_id: Public channel id (``dingtalk``) or instance name.

        Returns:
            _ChannelRuntime or None: The matching runtime.
        """
        for name, runtime in self._runtimes.items():
            if name == channel_id or name.startswith(channel_id + "#"):
                return runtime
        return None

    def instances_for(self, channel_id):
        """Return every runtime belonging to a channel id.

        Args:
            channel_id: Public channel id.

        Returns:
            tuple: Matching runtimes in configuration order.
        """
        return tuple(
            runtime
            for name, runtime in self._runtimes.items()
            if name == channel_id or name.startswith(channel_id + "#")
        )

    def resolve_targets(self, names):
        """Map requested channel ids onto existing instances.

        Args:
            names: Requested ids, or ``None`` for every instance.

        Returns:
            tuple: ``(matched, missing)``; ``matched`` holds runtimes and
            ``missing`` the valid-but-unconfigured ids.
        """
        if names is None:
            return tuple(self._runtimes.values()), ()
        matched = []
        missing = []
        seen = set()
        for name in names:
            runtime = self.find_instance(name)
            if runtime is None:
                missing.append(name)
            elif runtime.name not in seen:
                seen.add(runtime.name)
                matched.append(runtime)
        return tuple(matched), tuple(missing)

    def _is_deduped(self, runtime, notification):
        """Report whether the dedup window suppresses this notification.

        Args:
            runtime: Target channel runtime.
            notification: Message being sent.

        Returns:
            bool: ``True`` when the message must not be delivered.
        """
        key = notification.dedup_key
        cooldown = self._options["dedup_cooldown"]
        if not key or cooldown <= 0:
            return False
        now = time.monotonic()
        with self._lock:
            stamp = self._dedup.get((runtime.name, key))
            if stamp is not None and (now - stamp) < cooldown:
                runtime.note_deduped()
                return True
            self._dedup[(runtime.name, key)] = now
        return False

    def enqueue(self, notification, names=None):
        """Queue a notification for each target channel.

        Args:
            notification: Message to send.
            names: Optional channel-id subset.

        Returns:
            SendResult: ``mode="async"`` with per-channel enqueue results.
        """
        runtimes, missing = self.resolve_targets(names)
        outcomes: List[ChannelOutcome] = []
        accepted = False
        dropped = False
        for runtime in runtimes:
            if self._is_deduped(runtime, notification):
                outcomes.append(
                    ChannelOutcome(
                        channel=runtime.name, ok=False, error_category="deduped", error="deduped"
                    )
                )
                continue
            outcome = runtime.enqueue(notification)
            outcomes.append(outcome)
            accepted = accepted or outcome.ok
            dropped = dropped or outcome.error_category == "dropped"
        for name in missing:
            outcomes.append(
                ChannelOutcome(
                    channel=name,
                    ok=False,
                    error_category="not_configured",
                    error="channel is not configured",
                )
            )
        reason = "ok" if accepted else ("queue_full" if dropped else "not_configured")
        return SendResult(
            accepted=accepted,
            mode="async",
            outcomes=tuple(outcomes),
            dropped=dropped,
            reason=reason,
        )

    def send_now(self, notification, names=None, timeout=None):
        """Deliver a notification synchronously, channel by channel.

        Args:
            notification: Message to send.
            names: Optional channel-id subset.
            timeout: Per-call request timeout override.

        Returns:
            SendResult: ``mode="sync"`` with per-channel delivery outcomes.
        """
        runtimes, missing = self.resolve_targets(names)
        outcomes: List[ChannelOutcome] = []
        for runtime in runtimes:
            if self._is_deduped(runtime, notification):
                outcomes.append(
                    ChannelOutcome(
                        channel=runtime.name, ok=False, error_category="deduped", error="deduped"
                    )
                )
                continue
            outcomes.append(runtime._process(notification, timeout=timeout))
        for name in missing:
            outcomes.append(
                ChannelOutcome(
                    channel=name,
                    ok=False,
                    error_category="not_configured",
                    error="channel is not configured",
                )
            )
        accepted = any(item.ok for item in outcomes)
        return SendResult(
            accepted=accepted,
            mode="sync",
            outcomes=tuple(outcomes),
            dropped=False,
            reason="ok" if accepted else "failed",
        )

    def flush(self, timeout=5.0):
        """Wait for every channel queue to drain.

        Args:
            timeout: Total seconds to wait across all channels.

        Returns:
            bool: Whether every queue drained.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        drained = True
        for runtime in self._runtimes.values():
            remaining = max(0.0, deadline - time.monotonic())
            if not runtime.flush(remaining):
                drained = False
        return drained

    def drain_and_deliver(self, timeout=5.0):
        """Deliver whatever is still queued, on the calling thread.

        Used by the interpreter-shutdown hook: CPython stops daemon worker
        threads before ``atexit`` callbacks run, so waiting for the workers
        (``flush``) would idle until the timeout and then drop the messages.
        Sending inline is the only thing that can still deliver at shutdown.
        Rate-limit and retry waits are skipped, so a throttled channel cannot
        hang process exit.

        Args:
            timeout: Total seconds available for the inline sends.

        Returns:
            int: Number of messages sent inline.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        sent = 0
        for runtime in self._runtimes.values():
            sent += runtime.deliver_pending(deadline)
        return sent

    def stats(self):
        """Return per-channel statistics snapshots.

        Returns:
            dict: Instance name to statistic mapping.
        """
        return {name: runtime.stats_snapshot() for name, runtime in self._runtimes.items()}

    def clear_stats(self):
        """Reset every channel's statistics."""
        for runtime in self._runtimes.values():
            runtime.clear_stats()

    def stop(self, timeout=5.0):
        """Stop every worker, discarding queued messages.

        Args:
            timeout: Seconds to wait per channel.
        """
        for runtime in list(self._runtimes.values()):
            runtime.stop(timeout)


def silent_outcomes(names, category, error):
    """Build outcomes for a call that cannot be delivered at all.

    Args:
        names: Channel names to report (``None`` reports a single ``"all"``).
        category: Error category to assign.
        error: Masked diagnostic.

    Returns:
        Tuple[ChannelOutcome, ...]: One outcome per reported name.
    """
    targets = names if names else ("all",)
    return tuple(
        ChannelOutcome(channel=str(name), ok=False, error_category=category, error=error)
        for name in targets
    )


def no_channels_result():
    """Return the result for "configured, but with no channels".

    Distinct from ``not_configured`` (nothing was ever configured): an empty
    channel list is a legitimate configuration, so it must be reported without
    the one-shot stderr warning.

    Returns:
        SendResult: ``accepted=False``, ``reason="no_channels"``.
    """
    return SendResult(
        accepted=False, mode="async", outcomes=(), dropped=False, reason="no_channels"
    )
