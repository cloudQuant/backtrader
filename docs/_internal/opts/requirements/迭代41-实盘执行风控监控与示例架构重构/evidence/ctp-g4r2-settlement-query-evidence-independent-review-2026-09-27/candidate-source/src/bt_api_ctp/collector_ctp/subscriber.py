"""CTP market-data subscriber built on the packaged ``MdClient``.

The native callback must never raise back into the CTP thread: a handler or
normalizer failure is counted and swallowed so one bad payload cannot stop
the whole collection run.  Reconnects are observable through
``connection_generation`` so the completeness report can flag the window.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from bt_api_ctp.collector.protocols import TickHandler
from bt_api_ctp.collector_ctp.normalizer import CtpTickNormalizer

_RUN_POLL_SECONDS = 0.1

#: 退出时等待重订阅线程收敛的上限；线程可能正卡在分批提交的批间等待上。
_RESUBSCRIBE_JOIN_TIMEOUT_SEC = 2.0

_logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CtpMdSubscriber:
    """Adapt a ``MdClient`` to the ``MarketDataSubscriber`` contract."""

    def __init__(
        self,
        md_client: Any,
        *,
        normalizer: Any | None = None,
        batch_size: int = 100,
        batch_interval_sec: float = 0.1,
        login_timeout_sec: float = 15.0,
        instrument_exchanges: dict[str, str] | None = None,
    ) -> None:
        self._md_client = md_client
        self.normalizer = normalizer if normalizer is not None else CtpTickNormalizer()
        self._batch_size = int(batch_size)
        self._batch_interval_sec = float(batch_interval_sec)
        self._login_timeout_sec = float(login_timeout_sec)
        self._instrument_exchanges: dict[str, str] = dict(instrument_exchanges or {})
        self._handler: TickHandler | None = None
        self._errors = 0
        self._subscribe_ok = 0
        self._subscribe_failed = 0
        self._last_subscribe_error_id: int | None = None
        self._stop_event = threading.Event()
        self._last_generation: int | None = None
        self._generation_changes: list[dict[str, Any]] = []
        self._subscribed: list[str] = []
        self._resubscribe_event = threading.Event()
        self._resubscribe_thread: threading.Thread | None = None
        self._disconnect_windows: list[dict[str, Any]] = []
        self._pending_disconnect: dict[str, Any] | None = None
        self._failed_instruments: dict[str, int] = {}
        self._resubscribe_events: list[dict[str, Any]] = []

    # -- MarketDataSubscriber -------------------------------------------------

    def set_handler(self, handler: TickHandler) -> None:
        self._handler = handler

    def set_instrument_exchanges(self, mapping: dict[str, str]) -> None:
        """Provide the instrument -> exchange map taken from the contract query.

        CTP depth-market callbacks leave ``ExchangeID`` empty, so the
        authoritative exchange for a tick comes from the reference universe
        rather than from the quote itself.
        """
        self._instrument_exchanges = {
            str(key): str(value) for key, value in (mapping or {}).items()
        }

    def connect(self) -> None:
        """Bind the native callback, start the client and wait for login.

        Waiting matters: ``MdClient.subscribe_batched`` only splits into
        batches once the session is logged in.  Before login it merely records
        the pending set, and the post-login callback would submit everything
        in one native call.
        """
        self._stop_event.clear()
        self._last_generation = self._current_generation()
        self._md_client.on_tick = self._on_raw_tick
        self._md_client.on_subscribe = self._on_subscribe_response
        self._bind_session_callbacks()
        self._take_over_resubscribe()
        self._md_client.start(block=False)
        self._wait_ready()
        _logger.info("CTP market-data session login OK")

    def _bind_session_callbacks(self) -> None:
        """Subscribe to session lifecycle notifications the host can provide.

        Without these, an unattended run cannot tell "no ticks because the
        market is quiet" from "no ticks because the session died".
        """
        if hasattr(self._md_client, "on_login"):
            self._md_client.on_login = self._on_login
        if hasattr(self._md_client, "on_disconnect"):
            self._md_client.on_disconnect = self._on_disconnect

    def _take_over_resubscribe(self) -> None:
        """Move post-reconnect re-subscription off the native callback thread.

        The login callback runs on CTP's callback thread.  Submitting the whole
        universe from there -- even in batches with waits between them -- blocks
        heartbeats and market-data callbacks, which is itself a cause of
        ``OnFrontDisconnected(0x2001)``.  When the host can defer, we disable
        its inline re-subscribe and do it here, in batches, on our own thread.
        """
        if not hasattr(self._md_client, "auto_resubscribe_on_login"):
            return  # 宿主不支持延后：保留其原有内联重订阅行为
        self._md_client.auto_resubscribe_on_login = False
        self._resubscribe_event.clear()
        self._resubscribe_thread = threading.Thread(
            target=self._resubscribe_loop, name="ctp-resubscribe", daemon=True
        )
        self._resubscribe_thread.start()

    def _wait_ready(self) -> None:
        wait_ready = getattr(self._md_client, "wait_ready", None)
        if not callable(wait_ready):
            return  # host cannot report readiness; keep legacy behaviour
        if wait_ready(timeout=self._login_timeout_sec) is not True:
            # Fail fast: a silent login failure would collect nothing for the
            # whole window while looking healthy in the heartbeat log.
            raise RuntimeError("ctp_md_login_timeout")

    def subscribe(self, instruments: list[str]) -> None:
        """Subscribe in batches while keeping the full set for reconnects."""
        self._subscribed = list(instruments)
        self._md_client.subscribe_batched(
            instruments,
            batch_size=self._batch_size,
            interval_sec=self._batch_interval_sec,
            should_stop=self._stop_event.is_set,
        )

    def run(self) -> None:
        """Block until :meth:`close` is called."""
        self._stop_event.wait()

    def close(self) -> None:
        """Stop the native client and release any blocking ``run``."""
        self._stop_event.set()
        self._resubscribe_event.set()  # 唤醒工作线程，让它尽快退出
        worker = self._resubscribe_thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=_RESUBSCRIBE_JOIN_TIMEOUT_SEC)
        self._md_client.stop()
        _logger.info("CTP market-data session closed")

    # -- diagnostics ----------------------------------------------------------

    def error_count(self) -> int:
        """Return how many callback payloads were rejected."""
        return self._errors

    def generation_changes(self) -> list[dict[str, Any]]:
        """Return observed reconnect generations (excluding the first)."""
        return list(self._generation_changes)

    def disconnect_windows(self) -> list[dict[str, Any]]:
        """Return observed disconnect windows.

        A window still open when the run ends keeps ``end``/``generation_after``
        as ``None`` so an unrecovered outage stays visible in the report.
        """
        windows = list(self._disconnect_windows)
        if self._pending_disconnect is not None:
            windows.append(
                {**self._pending_disconnect, "end": None, "generation_after": None}
            )
        return windows

    def failed_instruments(self) -> dict[str, int]:
        """Return instruments whose last subscribe response carried an error."""
        return dict(self._failed_instruments)

    def resubscribe_events(self) -> list[dict[str, Any]]:
        """Return one entry per re-subscribe cycle triggered by a reconnect."""
        return [dict(entry) for entry in self._resubscribe_events]

    def subscription_stats(self) -> dict[str, Any]:
        """Return how many subscribe responses succeeded or failed."""
        return {
            "ok": self._subscribe_ok,
            "failed": self._subscribe_failed,
            "last_error_id": self._last_subscribe_error_id,
        }

    # -- internals ------------------------------------------------------------

    def _current_generation(self) -> int | None:
        generation = getattr(self._md_client, "connection_generation", None)
        return generation if isinstance(generation, int) else None

    def _observe_generation(self) -> None:
        generation = self._current_generation()
        if generation is None:
            return
        if self._last_generation is None:
            self._last_generation = generation
            return
        if generation != self._last_generation:
            self._generation_changes.append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "generation": generation,
                }
            )
            self._last_generation = generation

    def _on_subscribe_response(self, specific_instrument: Any, rsp_info: Any) -> None:
        """Record one SubscribeMarketData response.  Must never raise."""
        try:
            error_id = int(getattr(rsp_info, "ErrorID", 0) or 0) if rsp_info is not None else 0
        except Exception:
            error_id = 0
        if error_id == 0:
            self._subscribe_ok += 1
            # 后续重订阅成功即视为已恢复，失败清单必须同步清理，否则报告会永远
            # 挂着一个早已成功的"失败合约"。
            instrument_id = getattr(specific_instrument, "InstrumentID", None)
            if instrument_id:
                self._failed_instruments.pop(str(instrument_id), None)
            return
        self._subscribe_failed += 1
        self._last_subscribe_error_id = error_id
        # 记住是哪个合约失败：失败清单要能进完整性报告并被后续重订阅重试。
        instrument_id = getattr(specific_instrument, "InstrumentID", None)
        if instrument_id:
            self._failed_instruments[str(instrument_id)] = error_id

    def _on_login(self, _login_field: Any = None) -> None:
        """Native login callback: close the open window, then signal the worker.

        Runs on CTP's callback thread, so it must not block; the re-subscribe
        itself happens in :meth:`_resubscribe_loop` on our own thread.

        Only a login that ended a disconnect asks for a re-subscribe: the first
        login of a session must not duplicate the caller's initial subscribe.
        """
        pending = self._pending_disconnect
        if pending is None:
            return
        self._pending_disconnect = None
        pending["end"] = _iso_now()
        pending["generation_after"] = self._current_generation()
        self._disconnect_windows.append(pending)
        self._resubscribe_event.set()

    def _on_disconnect(self, reason: Any) -> None:
        """Native disconnect callback; runs on CTP's callback thread."""
        if self._pending_disconnect is not None:
            # 上一次断线还没等到登录就再次断开：先作为未恢复窗口归档，避免丢失。
            self._disconnect_windows.append(
                {**self._pending_disconnect, "end": None, "generation_after": None}
            )
        self._pending_disconnect = {
            "start": _iso_now(),
            "reason": reason,
            "generation_before": self._current_generation(),
        }

    def _resubscribe_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._resubscribe_event.wait(_RUN_POLL_SECONDS):
                continue
            self._resubscribe_event.clear()
            if self._stop_event.is_set():
                return
            try:
                self._resubscribe()
            except Exception:
                # 工作线程意外退出会让后续重连永久失去重订阅能力，必须留痕并继续。
                _logger.exception("re-subscribe worker failed; continuing")

    def _resubscribe(self) -> None:
        """Re-submit the full instrument set in batches after a reconnect.

        A reconnect makes the front drop every subscription, so the whole set
        must be re-sent -- there is no cheaper incremental form.  Instruments
        whose earlier response carried an error are retried by this same
        submission, since subscribing is idempotent at the front.
        """
        instruments = list(self._subscribed)
        if not instruments:
            return  # 首次登录时 engine 尚未订阅，无需恢复
        generation = self._current_generation()
        started = time.monotonic()
        try:
            submitted = self._md_client.subscribe_batched(
                instruments,
                batch_size=self._batch_size,
                interval_sec=self._batch_interval_sec,
                should_stop=self._stop_event.is_set,
            )
        except Exception:
            _logger.exception(
                "re-subscribe after reconnect failed (instruments=%d)", len(instruments)
            )
            return
        if not submitted:
            # 一个批次都没提交（已停止 / 提交前又掉线）：不得记成一次重订阅。
            _logger.info("re-subscribe after reconnect skipped: no batch submitted")
            return
        self._resubscribe_events.append(
            {
                "at": _iso_now(),
                "generation": generation,
                "requested": len(instruments),
                "batches": int(submitted),
            }
        )
        stats = self.subscription_stats()
        _logger.info(
            "re-subscribe after reconnect: generation=%s requested=%d submitted_batches=%d "
            "elapsed=%.2fs (cumulative ok=%s failed=%s)",
            generation,
            len(instruments),
            int(submitted),
            time.monotonic() - started,
            stats.get("ok", 0),
            stats.get("failed", 0),
        )

    def _on_raw_tick(self, raw: Any) -> None:
        """Native callback entry point.  Must never raise."""
        try:
            self._observe_generation()
            tick = self.normalizer.normalize(raw)
        except Exception:
            self._errors += 1
            return
        if tick is None:
            return
        if not tick.exchange_id:
            exchange = self._instrument_exchanges.get(tick.instrument_id)
            if exchange:
                tick = replace(tick, exchange_id=exchange)
        handler = self._handler
        if handler is None:
            return
        try:
            handler.on_tick(tick)
        except Exception:
            self._errors += 1


__all__ = ["CtpMdSubscriber"]
