"""Store / Broker / Feed initialisation helpers and subprocess entry-point (Hongyuan Futures)."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import logging
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SUITE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SUITE_DIR.parents[3]

for _p in (_SUITE_DIR, _REPO_ROOT):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore

from common import config as cfg
from common.evidence import attach_reconciliation, capture_store_snapshot
from common.result import CaseTimer, save_result


_LOGIN_READINESS_ERRORS = ("did not become ready within",)


def start_store_with_retry(store, attempts=3, delay=1.0):
    """Start *store*, retrying bounded transient front-login readiness timeouts.

    ``BtApiStore``'s CTP wrapper allows a fixed 20s window for MD/trader login.
    The simulation fronts intermittently exceed it (observed during trading
    hours as ``CTP market data login did not become ready within 20s``), and a
    fresh connection normally succeeds, so retry a bounded number of times
    before surfacing the original error.  Only readiness timeouts are retried;
    credential/auth failures fail fast.
    """
    attempts = max(int(attempts), 1)
    for attempt in range(1, attempts + 1):
        try:
            store.start()
            return
        except Exception as exc:
            if attempt >= attempts or not any(
                marker in str(exc) for marker in _LOGIN_READINESS_ERRORS
            ):
                raise
            with contextlib.suppress(Exception):
                store.stop()
            time.sleep(max(float(delay), 0.0))


@contextlib.contextmanager
def started_store(env_key=None, stop_on_exit=True, case_id=None, report_dir=None):
    """Create a live BtApiStore in a subprocess-safe context."""
    env_key = env_key or cfg.get_env_key()
    hy_config = cfg.create_config(env_key)
    env_info = cfg.HONGYUAN_ENVIRONMENTS[env_key]
    store = BtApiStore(provider="ctp", **hy_config)
    case_id = case_id or os.getenv("CERTIFICATION_CASE_ID", "")
    report_dir = report_dir or os.getenv("CERTIFICATION_REPORT_DIR", "")

    print(f"\n使用宏源期货环境: {env_info['name']}")
    print(f"  交易前置: {hy_config['td_address']}")
    print(f"  行情前置: {hy_config['md_address']}")
    print(f"  InvestorID: {hy_config['investor_id']}")

    try:
        start_store_with_retry(store)
        if report_dir:
            capture_store_snapshot(
                report_dir=report_dir,
                case_id=case_id,
                label="before_action",
                store=store,
                env_key=env_key,
                config=hy_config,
            )
        yield store, hy_config, env_key
    finally:
        if report_dir:
            capture_store_snapshot(
                report_dir=report_dir,
                case_id=case_id,
                label="after_action_before_stop",
                store=store,
                env_key=env_key,
                config=hy_config,
            )
        if stop_on_exit:
            print("\n断开宏源期货连接...")
            store.stop()


def resolve_ctp_symbol(store, symbol):
    """Return the store-recognized alias for a user-supplied contract symbol.

    CTP instrument naming is case-sensitive per exchange: SHFE/DCE/INE use the
    lowercase native id (``rb2701``) while CZCE quotes the uppercase alias
    (``SA2701``, native ``SA701``).  A lowercase ``sa2701`` is unknown to the
    store, so the feed subscribes to nothing and the execution gate cannot
    canonicalise it.  Resolve through the store's own alias table instead of
    guessing a case convention; unknown symbols pass through unchanged.
    """
    text = str(symbol or "").strip()
    if not text:
        return text
    getter = getattr(store, "get_symbol_info", None)
    if not callable(getter):
        return text
    candidates = [text]
    for variant in (text.upper(), text.lower()):
        if variant not in candidates:
            candidates.append(variant)
    for candidate in candidates:
        try:
            info = getter(candidate) or {}
        except Exception as exc:
            logger.debug("symbol alias lookup failed for %s: %s", candidate, exc)
            info = {}
        if info:
            return candidate
    return text


def create_cerebro(
    store,
    symbol=None,
    bar_seconds=5,
    with_trade_logger=False,
    log_dir=None,
    historical_bars=None,
    position_mode=None,
    **broker_kwargs,
):
    """Create a Cerebro pre-wired with BtApiBroker + BtApiFeed."""
    symbol = resolve_ctp_symbol(store, symbol or cfg.get_order_symbol())
    broker_kwargs.setdefault("position_mode", position_mode or cfg.get_position_mode())
    broker = BtApiBroker(store=store, **broker_kwargs)
    data = BtApiFeed(
        store=store,
        dataname=symbol,
        timeframe=bt.TimeFrame.Seconds,
        compression=bar_seconds,
        backfill_start=False,
        historical_bars=historical_bars,
    )
    store._cerebro_managed_lifecycle = False
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.adddata(data)

    if with_trade_logger and log_dir:
        cerebro.addobserver(
            bt.observers.TradeLogger, log_dir=log_dir, log_format="json"
        )
    return cerebro


def run_with_timeout(cerebro, timeout_seconds=60):
    """Run *cerebro* with a daemon-timer hard timeout."""
    timer = threading.Timer(timeout_seconds, cerebro.runstop)
    timer.daemon = True
    timer.start()
    try:
        return cerebro.run()
    finally:
        timer.cancel()


def make_seed_bar(price=3000.0, when=None):
    """Build one synthetic historical bar for deterministic case startup.

    The Hongyuan simulation front only pushes sparse ticks (~0.2/s), so a case
    that waits for a live 5-second bar is not deterministic: with no tick in
    the window ``next()`` never runs and the case reports BLOCKED
    "未收到行情数据".  Passing ``[make_seed_bar()]`` as ``historical_bars``
    lets the strategy start immediately (live ticks then supplement), which is
    how T01 already works.  ``store.set_history()`` does NOT feed the
    strategy and must not be used for this.
    """
    when = when or datetime.now().replace(microsecond=0)
    return {
        "datetime": when,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 1.0,
        "openinterest": 0.0,
    }


def live_seed_bar(store, symbol, timeout=25.0, fallback=3000.0):
    """Build a seed bar priced from the latest live tick when one arrives.

    Fill-dependent cases (L01/B01/T02 ...) place ±20 offset limit orders
    around the seed price, so the seed must track the real market: a synthetic
    3000 seed against a ~1010 CZCE SA market produces an out-of-limit order
    that the counter rejects.  The simulation MD front delivers the first tick
    late and sparsely, so poll for ``timeout`` seconds, then fall back to the
    last tick the store already cached before using the numeric fallback.
    """
    symbol = resolve_ctp_symbol(store, symbol)
    price = None
    subscribe = getattr(store, "subscribe", None)
    if callable(subscribe):
        subscribe(symbol)
    poll_tick = getattr(store, "poll_tick", None)
    deadline = time.monotonic() + max(float(timeout), 0.0)
    if callable(poll_tick):
        while time.monotonic() < deadline:
            tick = poll_tick(symbol)
            tick_price = float(getattr(tick, "price", 0.0) or 0.0)
            if tick is not None and tick_price > 0:
                price = tick_price
                break
            time.sleep(0.2)
    if price is None:
        latest = getattr(store, "get_latest_tick_snapshot", None)
        if callable(latest):
            cached = latest(symbol)
            cached_price = float(getattr(cached, "price", 0.0) or 0.0)
            if cached_price > 0:
                price = cached_price
    return make_seed_bar(price=float(price if price is not None else fallback))


_CZCE_GENERIC_CLOSE_RE = re.compile(r"[A-Z]+\d{3}$")


def close_offset_for(symbol):
    """Return the correct close offset for *symbol*'s exchange.

    CZCE quotes three-digit contract months (``SA701``) and only accepts the
    generic ``close`` offset; SHFE / DCE / INE use ``close_today`` for legs
    opened the same trading day, which is what the certification cases build.
    A four-digit month code (``rb2701``) therefore means a non-CZCE exchange.
    """
    text = str(symbol or "").strip().upper().split(".")[-1]
    if _CZCE_GENERIC_CLOSE_RE.fullmatch(text):
        return "close"
    return "close_today"


def ensure_ctp_trading_admission(store, symbol, timeout=30.0):
    """Ensure typed CTP startup-query evidence immediately before new exposure.

    ``BtApiBroker`` rejects new CTP exposure (error
    ``ctp_query_evidence_incomplete``) until ``store.get_ctp_preflight_snapshot``
    has produced a complete snapshot bound to the live session, and that
    snapshot goes stale after ``ctp_query_max_age_seconds`` (default 30s).
    Certification cases must therefore run this admission check right before
    each order submission; a fresh snapshot short-circuits the query.

    On gated SDK builds the admission also arms the typed execution gate via
    ``arm_execution_for_registered_sim`` (Hongyuan's simulation fronts are in
    the frozen registered-sim registry), so ``submit_order_insert``/
    ``submit_order_action`` can legally reach the counter.
    """
    health_getter = getattr(store, "get_ctp_query_health", None)
    preflight = getattr(store, "get_ctp_preflight_snapshot", None)
    if not callable(preflight):
        return

    def _health_is_complete() -> bool:
        if not callable(health_getter):
            return True
        health = health_getter()
        return isinstance(health, dict) and health.get("evidence_complete") is True

    def _health_errors() -> list:
        if not callable(health_getter):
            return []
        health = health_getter()
        if not isinstance(health, dict):
            return ["ctp_query_health_unavailable"]
        return list(health.get("evidence_errors") or [])

    snapshot = {}
    # Query evidence occasionally comes back incomplete on the first attempt
    # (account / position / instrument queries still in flight on a freshly
    # established session), so retry within the caller's deadline instead of
    # failing the order on a single transient sample.
    deadline = time.monotonic() + max(float(timeout), 1.0)
    attempt = 0
    while not _health_is_complete():
        attempt += 1
        remaining = deadline - time.monotonic()
        if attempt > 4 or remaining <= 0:
            errors = _health_errors() or ["ctp_query_snapshot_missing"]
            raise RuntimeError(f"CTP admission preflight incomplete: {errors}")
        snapshot = preflight(symbol, timeout=min(remaining, 20.0))
        if not callable(health_getter):
            break

    arm = getattr(store, "arm_registered_sim_execution", None)
    if not callable(arm):
        return
    snapshot_sha = snapshot.get("snapshot_sha256") if isinstance(snapshot, dict) else None
    if not snapshot_sha:
        # Health was already fresh; take a fresh snapshot to bind this arm.
        snapshot = preflight(symbol, timeout=min(max(float(timeout), 1.0), 20.0))
        snapshot_sha = snapshot.get("snapshot_sha256")
    identity = hashlib.sha256(
        f"hongyuan-penetration-certification|{symbol}".encode("utf-8")
    ).hexdigest()
    cycle_id = f"{os.getenv('CERTIFICATION_CASE_ID') or 'case'}-{symbol}"
    # The SDK execution gate canonicalises EXCHANGE.INSTRUMENT, so arm with the
    # concrete pair the preflight resolved.  A bare certification symbol such as
    # ``sa2701`` is not canonicalisable on its own (its CZCE native id is
    # ``SA701``), and the gate rejects it as ``ctp_execution_gate_invalid_proof``.
    resolved = snapshot if isinstance(snapshot, dict) else {}
    arm(
        str(resolved.get("instrument_id") or symbol),
        str(resolved.get("exchange_id") or ""),
        strategy_identity_sha256=identity,
        execution_cycle_id=cycle_id,
        preflight_sha256=str(snapshot_sha or ""),
    )


# ---------------------------------------------------------------------------
# Subprocess entry-point shared by all case files
# ---------------------------------------------------------------------------


def case_main(run_fn, meta: dict):
    """Standard ``if __name__ == '__main__'`` handler for every case file.

    *run_fn(report_dir) -> CaseResult*
    *meta* must contain ``case_id``.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--report-dir", default="")
    args, _ = parser.parse_known_args()

    case_id = meta["case_id"]
    report_dir = (
        Path(args.report_dir)
        if args.report_dir
        else _SUITE_DIR / "reports" / "latest" / case_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    old_report_dir = os.environ.get("CERTIFICATION_REPORT_DIR")
    old_case_id = os.environ.get("CERTIFICATION_CASE_ID")
    os.environ["CERTIFICATION_REPORT_DIR"] = str(report_dir)
    os.environ["CERTIFICATION_CASE_ID"] = case_id

    # Tee stdout / stderr to stdout.log
    stdout_log = report_dir / "stdout.log"
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr

    class _Tee:
        """Tee stream that writes to both console and file with timestamps."""

        def __init__(self, stream, fh, label):
            """Initialize tee stream.

            Args:
                stream: Original stream to write to.
                fh: File handle to write to.
                label: Label for log entries.
            """
            self._stream = stream
            self._fh = fh
            self._label = label
            self._buffer = ""

        @staticmethod
        def _timestamp():
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        def _write_formatted_line(self, line):
            if not line:
                return

            if line.endswith("\n"):
                content = line[:-1]
                newline = "\n"
            else:
                content = line
                newline = ""

            if not content:
                self._fh.write(newline)
                return

            prefix = f"[{self._timestamp()}] [{self._label}] "
            self._fh.write(f"{prefix}{content}{newline}")

        def write(self, data):
            """Write data to both streams.

            Args:
                data: Data to write.
            """
            self._stream.write(data)
            if not data:
                return

            self._buffer += data
            while True:
                newline_index = self._buffer.find("\n")
                if newline_index < 0:
                    break
                line = self._buffer[: newline_index + 1]
                self._buffer = self._buffer[newline_index + 1 :]
                self._write_formatted_line(line)

        def flush(self):
            """Flush both streams."""
            if self._buffer:
                self._write_formatted_line(self._buffer)
                self._buffer = ""
            self._stream.flush()
            self._fh.flush()

    log_fh = open(stdout_log, "w", encoding="utf-8")
    log_fh.write(f"# stdout log for {case_id}\n")
    log_fh.write(f"# case_name: {meta.get('case_name', case_id)}\n")
    log_fh.write(f"# report_dir: {report_dir}\n")
    log_fh.write(f"# started_at: {datetime.now().isoformat(timespec='seconds')}\n\n")
    sys.stdout = _Tee(_orig_stdout, log_fh, "STDOUT")
    sys.stderr = _Tee(_orig_stderr, log_fh, "STDERR")

    try:
        result = run_fn(report_dir)
    except Exception:
        traceback.print_exc()
        env_key = cfg.get_env_key()
        with CaseTimer(case_id, meta.get("case_name", case_id), env_key) as timer:
            result = timer.fail_result(traceback.format_exc())

    result = attach_reconciliation(result, report_dir)
    save_result(result, report_dir)
    if old_report_dir is None:
        os.environ.pop("CERTIFICATION_REPORT_DIR", None)
    else:
        os.environ["CERTIFICATION_REPORT_DIR"] = old_report_dir
    if old_case_id is None:
        os.environ.pop("CERTIFICATION_CASE_ID", None)
    else:
        os.environ["CERTIFICATION_CASE_ID"] = old_case_id

    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    log_fh.close()

    print(f"\n[{case_id}] {result.status}  report -> {report_dir}")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result.exit_code())
