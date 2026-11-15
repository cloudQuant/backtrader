"""Minimal strategy client for the Execution routing example.

This module is safe to import offline: it imports Backtrader only. It never
imports ``bt_api_execution``, opens a socket, reads credentials or creates a
service runtime. The trusted deployment supplies an already-constructed route
port (see :class:`SdkExecutionRoutePort`) whose router, intent and monitor
handles are built from its own identity, transport factory and grant.

Flow demonstrated per parent order:

1. ``submit_limit_parent()`` -> ``ExecutionOrderRouter.route(intent)``.
   The router durably records the original request identity and digest before
   calling the Execution ``parent.submit`` port exactly once.
2. The Execution service applies the scheduler selected by the matched routing
   rule (``PASS`` / ``SLICE`` / ``TWAP``); the strategy does not split orders.
3. ``poll_monitor()`` drains the explicitly selected Execution -> Monitor relay
   composition on its owner thread.
4. ``cancel_parent()`` -> ``ExecutionOrderRouter.cancel(intent)`` using the
   *same* intent, so the cancel is bound to the original request identity.
"""

from __future__ import annotations

import backtrader as bt


class ExecutionRoutePort:
    """The small surface the trusted deployment binds to the strategy.

    Implementations must never retry an ambiguous submit under a new identity
    and must not construct a second parent for the same order intent.
    """

    def submit_limit_parent(self):
        """Submit the one configured limit parent and return the SDK result."""
        raise NotImplementedError

    def cancel_parent(self):
        """Cancel the original parent by its original identity."""
        raise NotImplementedError

    def poll_monitor(self, limit=None):
        """Drain the selected Monitor relay; the default leaves it unselected."""


class SdkExecutionRoutePort(ExecutionRoutePort):
    """Adapter over the SDK router and monitor composition.

    ``router`` is a prebuilt ``bt_api_py.execution_routing.ExecutionOrderRouter``,
    ``intent`` is the ``GatewayOrderIntent`` that trusted deployment code built
    with its own Gateway binding/route/wire identity, and ``monitor`` is an
    optional ``ServiceExecutionMonitorComposition``. This class deliberately
    accepts live handles instead of constructing them; this example never
    fabricates credentials, wire identity or service endpoints.
    """

    def __init__(self, *, router, intent, monitor=None):
        if router is None or intent is None:
            raise ValueError("router and intent are required")
        self._router = router
        self._intent = intent
        self._monitor = monitor

    def submit_limit_parent(self):
        # One call. The router owns durable pre-submit identity; do not catch
        # EXECUTION_UNKNOWN and resubmit with a new key.
        return self._router.route(self._intent)

    def cancel_parent(self):
        # Same original intent -> same request_key / digest.
        return self._router.cancel(self._intent)

    def poll_monitor(self, limit=None):
        # Must run on the composition's owner thread. ``None`` means the
        # caller selected source ``none`` and no relay was built.
        if self._monitor is None:
            return None
        return self._monitor.poll(limit)


class ExecutionRoutingDemoStrategy(bt.Strategy):
    """Submit one limit parent, poll Monitor, then cancel it by identity.

    This is a client-flow illustration, not a trading strategy: it reads no
    market data and produces no P&L. The route port is bound by the ordinary
    strategy ``start()`` path in a deployment; without a bound port ``next()``
    does nothing.
    """

    params = (
        # Bars to wait after submit before cancelling the parent. The cancel
        # path is explicit, not a stop loss or a timeout.
        ("cancel_after_bars", 2),
    )

    def __init__(self):
        # Direct bt.Strategy subclasses must not call super().__init__().
        self._route_port = None
        self._bars_since_submit = None
        self._submit_result = None
        self._cancel_result = None

    def bind_execution_route(self, port):
        """Bind the trusted route port before the first evaluated bar."""
        if not isinstance(port, ExecutionRoutePort):
            raise TypeError("port must implement ExecutionRoutePort")
        self._route_port = port

    def next(self):
        if self._route_port is None:
            return

        if self._bars_since_submit is None:
            self._submit_result = self._route_port.submit_limit_parent()
            self._bars_since_submit = 0
        else:
            self._bars_since_submit += 1

        # Drain the selected relay once per evaluated bar. A host with its own
        # scheduler may call ``maintain``/``poll`` instead.
        self._route_port.poll_monitor()

        if self._cancel_result is None and self._bars_since_submit >= self.p.cancel_after_bars:
            self._cancel_result = self._route_port.cancel_parent()
