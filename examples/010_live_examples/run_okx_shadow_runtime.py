#!/usr/bin/env python
"""Run a bounded, public-market-only OKX order-book observation."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import importlib
import importlib.util
import io
import math
import os
from pathlib import Path
import queue
import sysconfig
import threading
import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, Callable, Optional, Tuple

HERE = Path(__file__).resolve().parent

from backtrader_runtime import (  # noqa: E402
    CONFIG_SCHEMA_UNSUPPORTED,
    PRESET_POLICY_VIOLATION,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)


DEFAULT_RUNTIME_DIR = HERE / "runtime-okx-shadow"
STRATEGY_ID = "example.010_live_examples.okx_public_shadow"
RUNTIME_ID = STRATEGY_ID
PUBLIC_SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
PUBLIC_ORDERBOOK_LIMIT = 5
REVIEWED_CCXT_VERSION = "4.5.83"
REVIEWED_AIOHTTP_VERSION = "3.14.3"
MIN_DURATION_SECONDS = 1
MAX_DURATION_SECONDS = 30
STARTUP_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 3.0
SHUTDOWN_TIMEOUT_SECONDS = 3.0


def runtime_registry() -> RuntimeRegistry:
    """Return the centrally reviewed registry; config cannot add a route."""

    return iteration41_runtime_registry()


def _profile_error(reason: str, message: str, field_path: str) -> RuntimeConfigError:
    return RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        message,
        field_path=field_path,
        reason=reason,
    )


def _validate_profile(effective: EffectiveRuntimeConfig) -> Tuple[Tuple[str, ...], int]:
    config = effective.config
    if config.strategy_id != STRATEGY_ID or effective.registration.runtime_id != RUNTIME_ID:
        raise _profile_error(
            "strategy_not_bound",
            "this runner is bound only to the registered OKX public shadow runtime",
            "strategy.id",
        )
    if (
        (config.mode, config.preset) != ("simulation", "shadow")
        or effective.order_route != "read_only"
        or effective.account_access != "public_read"
        or not effective.allows_network
        or effective.allows_external_writes
        or effective.allows_production_writes
        or effective.allows_hypothetical_fills
        or effective.required_capabilities
        or effective.requires_approval
        or effective.requires_live_confirmation
        or config.secrets_ref != "none"
    ):
        raise _profile_error(
            "preset_not_bound",
            "the OKX observer accepts only public-read simulation/shadow with no secrets or writes",
            "runtime.preset",
        )

    parameters = config.parameters
    expected_keys = {"symbols", "duration_seconds", "orderbook_limit"}
    if set(parameters) != expected_keys:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "configure only symbols, duration_seconds and orderbook_limit for this observer",
            field_path="parameters",
            reason="invalid_shadow_parameters",
        )

    raw_symbols = parameters.get("symbols")
    if not isinstance(raw_symbols, (tuple, list)) or not raw_symbols:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "symbols must be a non-empty list of the fixed public OKX instruments",
            field_path="parameters.symbols",
            reason="invalid_symbols",
        )
    symbols = tuple(raw_symbols)
    if (
        any(not isinstance(symbol, str) for symbol in symbols)
        or len(set(symbols)) != len(symbols)
        or any(symbol not in PUBLIC_SYMBOLS for symbol in symbols)
    ):
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "symbols may contain only BTC/USDT:USDT and ETH/USDT:USDT, without duplicates",
            field_path="parameters.symbols",
            reason="invalid_symbols",
        )

    duration = parameters.get("duration_seconds")
    if (
        type(duration) is not int
        or duration < MIN_DURATION_SECONDS
        or duration > MAX_DURATION_SECONDS
    ):
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "duration_seconds must be an integer from 1 through 30",
            field_path="parameters.duration_seconds",
            reason="invalid_duration",
        )

    orderbook_limit = parameters.get("orderbook_limit")
    if type(orderbook_limit) is not int or orderbook_limit != PUBLIC_ORDERBOOK_LIMIT:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "orderbook_limit is fixed at five levels",
            field_path="parameters.orderbook_limit",
            reason="invalid_orderbook_limit",
        )
    return symbols, duration


def _build_exchange_config() -> dict:
    """Build fixed public-only options with environment proxy use disabled."""

    return {
        "enableRateLimit": True,
        "timeout": int(READ_TIMEOUT_SECONDS * 1000),
        "aiohttp_trust_env": False,
        "options": {"defaultType": "swap"},
    }


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except (OSError, ValueError):
        return False


def _installed_ccxt_root() -> Path:
    """Resolve CCXT only from this interpreter's installed package roots."""

    spec = importlib.util.find_spec("ccxt")
    if spec is None or not isinstance(spec.origin, str):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the installed CCXT Pro dependency is unavailable",
            field_path="runtime.dependencies.ccxt",
            reason="provider_dependency_unavailable",
        )
    origin = Path(spec.origin).resolve()
    package_root = origin.parent
    paths = sysconfig.get_paths()
    allowed_roots = tuple(
        Path(paths[key]).resolve()
        for key in ("purelib", "platlib")
        if isinstance(paths.get(key), str) and paths[key]
    )
    if not any(_within(origin, root) for root in allowed_roots):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "CCXT must be loaded from the active Python installation",
            field_path="runtime.dependencies.ccxt",
            reason="provider_origin_untrusted",
        )
    return package_root


def _installed_aiohttp_root() -> Path:
    """Resolve aiohttp only from this interpreter's installed package roots."""

    spec = importlib.util.find_spec("aiohttp")
    if spec is None or not isinstance(spec.origin, str):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the installed aiohttp dependency is unavailable",
            field_path="runtime.dependencies.aiohttp",
            reason="provider_dependency_unavailable",
        )
    origin = Path(spec.origin).resolve()
    paths = sysconfig.get_paths()
    allowed_roots = tuple(
        Path(paths[key]).resolve()
        for key in ("purelib", "platlib")
        if isinstance(paths.get(key), str) and paths[key]
    )
    if not any(_within(origin, root) for root in allowed_roots):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "aiohttp must be loaded from the active Python installation",
            field_path="runtime.dependencies.aiohttp",
            reason="provider_origin_untrusted",
        )
    return origin.parent


def _require_reviewed_provider_versions(ccxt: Any, aiohttp: Any) -> None:
    """Reject provider versions that have not passed the public shadow review."""

    if (
        getattr(ccxt, "__version__", None) != REVIEWED_CCXT_VERSION
        or getattr(aiohttp, "__version__", None) != REVIEWED_AIOHTTP_VERSION
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "install the reviewed OKX shadow dependency pair with python -m pip install -e "
            '".[okx-public-shadow]" before running this public market probe',
            field_path="runtime.dependencies",
            reason="provider_dependency_version_unreviewed",
        )


def _new_read_only_client() -> "_ReadOnlyMarketClient":
    """Create a CCXT Pro client after the sealed shadow profile is accepted."""

    expected_package_root = _installed_ccxt_root()
    expected_aiohttp_root = _installed_aiohttp_root()
    try:
        ccxt = importlib.import_module("ccxt")
        package_file = Path(ccxt.__file__).resolve()
        if package_file.parent != expected_package_root:
            raise RuntimeError("CCXT package origin changed during import")
        aiohttp = importlib.import_module("aiohttp")
        aiohttp_file = Path(aiohttp.__file__).resolve()
        if aiohttp_file.parent != expected_aiohttp_root:
            raise RuntimeError("aiohttp package origin changed during import")
        _require_reviewed_provider_versions(ccxt, aiohttp)
        ccxtpro = importlib.import_module("ccxt.pro")
        pro_file = Path(ccxtpro.__file__).resolve()
        if not _within(pro_file, expected_package_root):
            raise RuntimeError("CCXT Pro package origin changed during import")
        exchange = ccxtpro.okx(_build_exchange_config())
    except RuntimeConfigError:
        raise
    except Exception:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the installed CCXT Pro public client could not be initialized",
            field_path="runtime.dependencies.ccxt",
            reason="provider_initialization_failed",
        ) from None
    return _ReadOnlyMarketClient(exchange)


def _valid_orderbook(book: Any, symbol: str, limit: int) -> bool:
    """Accept a symbol-bound book with finite positive levels in the requested depth."""

    if not isinstance(book, Mapping):
        return False
    # Do not relabel an unbound (or different-market) payload as the requested
    # instrument when constructing the callback event below.
    if book.get("symbol") != symbol:
        return False
    for side_name in ("bids", "asks"):
        side = book.get(side_name)
        if not isinstance(side, (tuple, list)) or not side:
            return False
        for level in side[:limit]:
            if not isinstance(level, (tuple, list)) or len(level) < 2:
                return False
            price, amount = level[0], level[1]
            if isinstance(price, bool) or isinstance(amount, bool):
                return False
            try:
                numeric_price = float(price)
                numeric_amount = float(amount)
            except (TypeError, ValueError, OverflowError):
                return False
            if (
                not math.isfinite(numeric_price)
                or not math.isfinite(numeric_amount)
                or numeric_price <= 0
                or numeric_amount <= 0
            ):
                return False
    return True


class _ReadOnlyMarketClient:
    """Expose only public market reads and shutdown from the provider object."""

    __slots__ = ("__exchange",)

    def __init__(self, exchange: Any) -> None:
        self.__exchange = exchange

    async def load_markets(self) -> Any:
        return await self.__exchange.load_markets()

    async def watch_order_book(self, symbol: str, *, limit: int) -> Any:
        return await self.__exchange.watch_order_book(symbol, limit=limit)

    async def close(self) -> Any:
        return await self.__exchange.close()


def _reject_strategy_order_action(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "the public shadow callback adapter has no order route",
        field_path="runtime.runner",
        reason="shadow_order_action_disabled",
    )


_STRATEGY_ORDER_ACTIONS = (
    "buy",
    "sell",
    "close",
    "cancel",
    "buy_bracket",
    "sell_bracket",
    "order_target_size",
    "order_target_value",
    "order_target_percent",
)


def _new_strategy_callback_observer(symbols: Tuple[str, ...]) -> Any:
    """Create the historical strategy's passive callbacks without its broker lifecycle.

    This deliberately does not construct a Cerebro strategy or attach a broker.
    Only ``notify_orderbook`` and ``get_stats`` are used by the shadow runner.
    """

    try:
        module = importlib.import_module("examples.010_live_examples.live_mixbroker_okx_demo")
        strategy_class = module.LiveMultiSymbolStrategy
        observer = object.__new__(strategy_class)
        observer.p = SimpleNamespace(symbols=tuple(symbols))
        for name in _STRATEGY_ORDER_ACTIONS:
            setattr(observer, name, _reject_strategy_order_action)
        strategy_class.__init__(observer)
        if hasattr(observer, "broker") or hasattr(observer, "cerebro"):
            raise TypeError("the callback observer unexpectedly has a broker lifecycle")
        if any(
            getattr(observer, name, None) is not _reject_strategy_order_action
            for name in _STRATEGY_ORDER_ACTIONS
        ):
            raise TypeError("the callback observer's order guards were replaced")
        return observer
    except ModuleNotFoundError:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "install Backtrader core dependencies and the reviewed public-shadow pair with "
            'python -m pip install -e ".[okx-public-shadow]" from the repository root',
            field_path="runtime.dependencies.strategy",
            reason="strategy_callback_dependency_unavailable",
        ) from None
    except RuntimeConfigError:
        raise
    except Exception:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the passive OKX strategy callback could not be initialized",
            field_path="runtime.runner",
            reason="strategy_callback_initialization_failed",
        ) from None


def _bounded_orderbook(book: Mapping[str, Any], symbol: str, limit: int) -> dict:
    """Copy only the validated public levels the shadow profile requested."""

    return {
        "symbol": symbol,
        "bids": [[float(level[0]), float(level[1])] for level in book["bids"][:limit]],
        "asks": [[float(level[0]), float(level[1])] for level in book["asks"][:limit]],
    }


async def _observe_public_markets(
    provider_factory: Callable[[], Any],
    symbols: Tuple[str, ...],
    duration: int,
    *,
    observer_factory: Optional[Callable[[Tuple[str, ...]], Any]] = None,
) -> dict:
    """Run bounded read calls and always shut down the provider client."""

    loop = asyncio.get_running_loop()
    started_at = time.monotonic()
    counts = dict.fromkeys(symbols, 0)
    counters = {
        "public_market_read_calls": 0,
        "public_market_read_timeouts": 0,
        "run_deadline_read_cancellations": 0,
        "run_deadline_watcher_cancellations": 0,
        "provider_startup_timeouts": 0,
        "provider_shutdown_timeouts": 0,
        "public_read_errors": 0,
    }
    tasks = []
    lingering_tasks = set()
    startup_status = "ready"
    shutdown_status = "closed"
    callback_factory = observer_factory or _new_strategy_callback_observer
    strategy_observer = callback_factory(symbols)
    strategy_callback_counts = dict.fromkeys(symbols, 0)
    client = provider_factory()

    async def bounded_call(awaitable: Any, timeout: float) -> Tuple[bool, Any]:
        task = asyncio.create_task(awaitable)
        try:
            done, _pending = await asyncio.wait((task,), timeout=timeout)
            if task not in done:
                task.cancel()
                lingering_tasks.add(task)
                return False, None
            return True, task.result()
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                lingering_tasks.add(task)
            raise

    async def observe_symbol(symbol: str, deadline: float) -> None:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            counters["public_market_read_calls"] += 1
            try:
                completed, _book = await bounded_call(
                    client.watch_order_book(symbol, limit=PUBLIC_ORDERBOOK_LIMIT),
                    timeout=min(READ_TIMEOUT_SECONDS, remaining),
                )
                if not completed:
                    if remaining <= READ_TIMEOUT_SECONDS:
                        counters["run_deadline_read_cancellations"] += 1
                    else:
                        counters["public_market_read_timeouts"] += 1
                    return
                if not _valid_orderbook(_book, symbol, PUBLIC_ORDERBOOK_LIMIT):
                    counters["public_read_errors"] += 1
                    return
                bounded_book = _bounded_orderbook(_book, symbol, PUBLIC_ORDERBOOK_LIMIT)
                event = SimpleNamespace(
                    symbol=symbol,
                    data=bounded_book,
                    channel="orderbook",
                )
                # The legacy callback prints snapshots. Keep those messages out
                # of the config-first CLI's JSON result stream.
                with redirect_stdout(io.StringIO()):
                    strategy_observer.notify_orderbook(event)
                strategy_callback_counts[symbol] += 1
                counts[symbol] += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                counters["public_read_errors"] += 1
                return

    try:
        has_read_interface = all(
            callable(getattr(client, name, None)) for name in ("load_markets", "watch_order_book")
        )
        if not has_read_interface:
            startup_status = "provider_interface_invalid"
        else:
            counters["public_market_read_calls"] += 1
            try:
                completed, _markets = await bounded_call(
                    client.load_markets(), timeout=STARTUP_TIMEOUT_SECONDS
                )
                if not completed:
                    counters["provider_startup_timeouts"] += 1
                    startup_status = "startup_timeout"
            except Exception:
                counters["public_read_errors"] += 1
                startup_status = "startup_failed"

        if startup_status == "ready":
            deadline = loop.time() + duration
            tasks = [asyncio.create_task(observe_symbol(symbol, deadline)) for symbol in symbols]
            await asyncio.sleep(duration)
    finally:
        cleanup_tasks = set(tasks) | lingering_tasks
        for task in tasks:
            if not task.done():
                counters["run_deadline_watcher_cancellations"] += 1
                task.cancel()
        for task in lingering_tasks:
            if not task.done():
                task.cancel()
        if cleanup_tasks:
            done, pending = await asyncio.wait(
                cleanup_tasks, timeout=min(0.25, SHUTDOWN_TIMEOUT_SECONDS)
            )
            for task in done:
                if not task.cancelled():
                    task.exception()
            if pending:
                shutdown_status = "watcher_shutdown_timeout"
        close = getattr(client, "close", None)
        if not callable(close):
            shutdown_status = "provider_close_unavailable"
        else:
            try:
                closed, _result = await bounded_call(close(), timeout=SHUTDOWN_TIMEOUT_SECONDS)
                if not closed:
                    counters["provider_shutdown_timeouts"] += 1
                    shutdown_status = "provider_close_timeout"
            except Exception:
                shutdown_status = "provider_close_failed"

    if startup_status != "ready":
        status = "PUBLIC_SHADOW_STARTUP_FAILED"
    elif counters["public_read_errors"]:
        status = "PUBLIC_SHADOW_PARTIAL"
    elif any(counts.values()):
        status = "PUBLIC_SHADOW_OBSERVED"
    else:
        status = "PUBLIC_SHADOW_NO_UPDATES"

    strategy_evidence_valid = True
    try:
        strategy_stats = strategy_observer.get_stats()
        reported_counts = strategy_stats.get("orderbooks")
        strategy_evidence_valid = (
            isinstance(strategy_stats, Mapping)
            and isinstance(reported_counts, Mapping)
            and all(
                isinstance(key, str)
                and type(value) is int
                and value >= 0
                and key in strategy_callback_counts
                for key, value in reported_counts.items()
            )
            and all(
                reported_counts.get(symbol, 0) == callback_count
                for symbol, callback_count in strategy_callback_counts.items()
            )
            and strategy_callback_counts == counts
        )
    except Exception:
        strategy_stats = {}
        strategy_evidence_valid = False
    if not strategy_evidence_valid:
        counters["public_read_errors"] += 1
        strategy_stats = {}

    return {
        "status": status,
        "duration_seconds": duration,
        "symbols": list(symbols),
        "requested_orderbook_limit": PUBLIC_ORDERBOOK_LIMIT,
        "orderbooks_received": counts,
        "strategy_observation": {
            "status": (
                "CALLBACK_OBSERVED"
                if strategy_evidence_valid and any(strategy_callback_counts.values())
                else "NO_CALLBACK"
                if strategy_evidence_valid
                else "CALLBACK_EVIDENCE_INVALID"
            ),
            "callback": "LiveMultiSymbolStrategy.notify_orderbook",
            "callback_invocations": strategy_callback_counts,
            "callback_stats": strategy_stats,
            "scope": "PASSIVE_PUBLIC_ORDERBOOK_CALLBACK_ONLY_NO_CEREBRO_OR_BROKER",
        },
        "provider_operation_counts": counters,
        "account_read_calls": 0,
        "order_write_calls": 0,
        "cancel_write_calls": 0,
        "hypothetical_fill_count": 0,
        "provider_shutdown": shutdown_status,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "evidence_boundary": "PUBLIC_ORDERBOOK_OBSERVATION_ONLY_NO_ACCOUNT_OR_EXECUTION_EVIDENCE",
    }


def _run_async_bounded(awaitable: Any, timeout_seconds: float) -> Any:
    """Run async work on a daemon loop with a hard join bound.

    ``asyncio.wait_for`` can exceed its timeout when a provider coroutine
    suppresses cancellation. The loop runs on a daemon thread so shutdown can
    stop waiting after cancelling pending tasks instead of hanging the CLI.
    """

    loop = asyncio.new_event_loop()
    completed = threading.Event()
    stop_requested = threading.Event()
    outcome = queue.Queue(maxsize=1)

    def consume_task_exception(task: "asyncio.Task[Any]") -> None:
        if not task.cancelled():
            task.exception()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        try:
            outcome.put((True, loop.run_until_complete(awaitable)))
        except BaseException as error:
            outcome.put((False, error))
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            try:
                if pending and not stop_requested.is_set():
                    done, pending = loop.run_until_complete(
                        asyncio.wait(pending, timeout=min(0.25, SHUTDOWN_TIMEOUT_SECONDS))
                    )
                    for task in done:
                        consume_task_exception(task)
                    for task in pending:
                        task.add_done_callback(consume_task_exception)
            finally:
                loop.close()
                asyncio.set_event_loop(None)
                completed.set()

    worker = threading.Thread(target=run_loop, name="okx-public-shadow", daemon=True)
    worker.start()
    if not completed.wait(timeout_seconds):
        stop_requested.set()
        stop_delivery_failed = False
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            stop_delivery_failed = True
        worker.join(timeout=min(0.25, SHUTDOWN_TIMEOUT_SECONDS))
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the public shadow observer exceeded its hard runtime bound",
            field_path="runtime.runner",
            reason=(
                "provider_hard_timeout_loop_unavailable"
                if stop_delivery_failed
                else "provider_hard_timeout"
            ),
        )
    worker.join(timeout=0.1)
    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value
    raise value


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate sealed v4 policy, then observe fixed public OKX books."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    symbols, duration = _validate_profile(effective)
    try:
        hard_timeout = duration + STARTUP_TIMEOUT_SECONDS + (2 * SHUTDOWN_TIMEOUT_SECONDS) + 1.0
        report = _run_async_bounded(
            _observe_public_markets(_new_read_only_client, symbols, duration), hard_timeout
        )
    except RuntimeConfigError:
        raise
    except Exception:
        raise _profile_error(
            "provider_run_failed",
            "the public shadow observer could not complete safely",
            "runtime.runner",
        ) from None

    config = effective.config
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "effective_digest": effective.effective_digest,
        "scope": "PUBLIC_MARKET_DATA_ONLY",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
        "allows_hypothetical_fills": effective.allows_hypothetical_fills,
    }
    if report["provider_shutdown"] != "closed":
        reason = "provider_shutdown_incomplete"
    elif report["status"] == "PUBLIC_SHADOW_STARTUP_FAILED":
        reason = "public_market_startup_incomplete"
    elif report["provider_operation_counts"]["public_read_errors"]:
        reason = "public_market_read_failed"
    elif not any(report["orderbooks_received"].values()):
        reason = "public_market_observation_empty"
    else:
        reason = None
    if reason is not None:
        raise _profile_error(
            reason,
            "the public shadow observer did not complete a bounded market-data observation",
            "runtime.runner",
        )
    return report
