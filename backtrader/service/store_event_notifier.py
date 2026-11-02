"""Own Store-to-Cerebro event wakeup state and SDK notifier bindings.

This bridge owns only the condition, waiter registry, event generation, and
the optional SDK wake callback binding. It never polls or closes the SDK API;
the host Store supplies the active API and retains transport lifecycle.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional


class StoreEventNotifier:
    """Single owner for engine waiters and one SDK event-waker binding."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._generation = 0
        self._wakers: Dict[object, Callable[[], Any]] = {}
        self._sdk_lock = threading.RLock()
        self._sdk_api: Any = None
        self._sdk_token: Any = None
        self._setter_api: Any = None

    @property
    def has_wakers(self) -> bool:
        with self._condition:
            return bool(self._wakers)

    @property
    def has_sdk_binding(self) -> bool:
        with self._sdk_lock:
            return self._sdk_api is not None or self._setter_api is not None

    def snapshot(self) -> int:
        """Return the current generation for an engine waiter."""

        with self._condition:
            return self._generation

    def wait(self, generation: int, timeout: Any) -> bool:
        """Wait only while the generation still matches the caller snapshot."""

        with self._condition:
            if self._generation != generation:
                return True
            return self._condition.wait_for(
                lambda: self._generation != generation,
                timeout=max(float(timeout), 0.0),
            )

    def register(
        self,
        callback: Callable[[], Any],
        *,
        api: Any,
        signal_callback: Callable[[], Any],
    ) -> object:
        """Register an engine waiter and bind the active API if available."""

        if not callable(callback):
            raise TypeError("live-bar event waker must be callable")
        token = object()
        with self._condition:
            self._wakers[token] = callback
        if api is not None:
            try:
                self.bind_api_notifier(api, signal_callback)
            except Exception:
                with self._condition:
                    self._wakers.pop(token, None)
                    no_wakers = not self._wakers
                if no_wakers:
                    try:
                        self.unbind_api_notifier()
                    except Exception:
                        pass
                raise
        return token

    def unregister(self, token: object) -> None:
        """Remove one engine waiter and unbind after the last waiter leaves."""

        with self._condition:
            self._wakers.pop(token, None)
            no_wakers = not self._wakers
        if no_wakers:
            self.unbind_api_notifier()

    def signal(self) -> None:
        """Publish a Store transition and notify current engine waiters."""

        with self._condition:
            callbacks = tuple(self._wakers.values())
            if not callbacks:
                return
            self._generation += 1
            self._condition.notify_all()
        for callback in callbacks:
            callback()

    def bind_api_notifier(self, api: Any, callback: Callable[[], Any]) -> None:
        """Bind the engine wake callback to the active public SDK event source."""

        with self._condition:
            if not self._wakers:
                return
        with self._sdk_lock:
            if self._sdk_api is api or self._setter_api is api:
                return
            old_api = self._sdk_api
            old_token = self._sdk_token
            old_setter_api = self._setter_api
            if old_api is not None and old_token is not None:
                unregister = getattr(old_api, "unregister_event_waker", None)
                if callable(unregister):
                    unregister(old_token)
            if old_setter_api is not None:
                setter = getattr(old_setter_api, "set_live_bar_event_notifier", None)
                if callable(setter):
                    setter(None)
            self._sdk_api = None
            self._sdk_token = None
            self._setter_api = None

            register = getattr(api, "register_event_waker", None)
            if callable(register):
                sdk_token = register(callback)
                if sdk_token is None:
                    raise RuntimeError("SDK event-waker registration returned no token")
                self._sdk_api = api
                self._sdk_token = sdk_token
                return

            setter = getattr(api, "set_live_bar_event_notifier", None)
            if callable(setter):
                self._setter_api = api
                try:
                    setter(callback)
                except Exception:
                    self._setter_api = None
                    try:
                        setter(None)
                    except Exception:
                        pass
                    raise

    def unbind_api_notifier(self) -> None:
        """Unbind SDK callbacks after the final engine waiter leaves."""

        with self._sdk_lock:
            api = self._sdk_api
            token = self._sdk_token
            setter_api = self._setter_api
            if api is not None and token is not None:
                unregister = getattr(api, "unregister_event_waker", None)
                if callable(unregister):
                    unregister(token)
            if setter_api is not None:
                setter = getattr(setter_api, "set_live_bar_event_notifier", None)
                if callable(setter):
                    setter(None)
            self._sdk_api = None
            self._sdk_token = None
            self._setter_api = None


__all__ = ("StoreEventNotifier",)
