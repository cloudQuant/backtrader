"""Store / Broker / Feed initialisation helpers and subprocess entry-point."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


def _mask_investor_id(investor_id):
    """Return a stable display value that never includes the full investor ID."""
    value = str(investor_id or "")
    if not value:
        return "<empty>"

    if len(value) <= 4:
        # Fully mask short IDs without revealing their length. The alternate
        # placeholder handles unusual IDs that consist only of mask characters.
        return next(mask for mask in ("****", "••••") if value not in mask)

    masked = f"{value[:2]}***{value[-2:]}"
    # Avoid echoing the complete value when it happens to contain the mask
    # marker (for example, an ID whose middle is already "***").
    return "***" if value in masked else masked


@contextlib.contextmanager
def started_store(env_key=None, stop_on_exit=True, case_id=None, report_dir=None):
    """Create a live BtApiStore in a subprocess-safe context."""
    env_key = env_key or cfg.get_env_key()
    simnow_config = cfg.create_config(env_key)
    env_info = cfg.SIMNOW_ENVIRONMENTS[env_key]
    store = BtApiStore(provider="ctp", **simnow_config)
    case_id = case_id or os.getenv("CERTIFICATION_CASE_ID", "")
    report_dir = report_dir or os.getenv("CERTIFICATION_REPORT_DIR", "")

    print(f"\n使用 SimNow 环境: {env_info['name']}")
    print(f"  交易前置: {simnow_config['td_address']}")
    print(f"  行情前置: {simnow_config['md_address']}")
    print(f"  InvestorID: {_mask_investor_id(simnow_config['investor_id'])}")

    try:
        store.start()
        if report_dir:
            capture_store_snapshot(
                report_dir=report_dir,
                case_id=case_id,
                label="before_action",
                store=store,
                env_key=env_key,
                config=simnow_config,
            )
        yield store, simnow_config, env_key
    finally:
        if report_dir:
            capture_store_snapshot(
                report_dir=report_dir,
                case_id=case_id,
                label="after_action_before_stop",
                store=store,
                env_key=env_key,
                config=simnow_config,
            )
        if stop_on_exit:
            print("\n断开 SimNow 连接...")
            store.stop()


def create_cerebro(
    store,
    symbol=None,
    bar_seconds=5,
    with_trade_logger=False,
    log_dir=None,
    historical_bars=None,
    **broker_kwargs,
):
    """Create a Cerebro pre-wired with BtApiBroker + BtApiFeed."""
    symbol = symbol or cfg.get_order_symbol()
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


def make_seed_bar(price=3000.0, when=None):
    """Build one synthetic historical bar for deterministic case startup.

    SimNow only pushes ticks during exchange trading sessions, and even inside
    a session the flow can be sparse.  A case that waits for a live
    compression bar is therefore not deterministic: with no tick in the
    window ``next()`` never runs and the case reports BLOCKED
    "未收到行情数据" despite a healthy connection.  Passing
    ``[make_seed_bar()]`` as ``historical_bars`` lets the strategy start
    immediately (live ticks then supplement).  ``store.set_history()`` does
    NOT feed the strategy and must not be used for this.
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


def live_seed_bar(store, symbol, timeout=8.0, fallback=3000.0):
    """Build a seed bar priced from the latest live tick when one arrives.

    Waiting briefly for a real tick keeps the seed realistic (local validation
    cases compare against ``close``); ``fallback`` keeps startup deterministic
    when the session is closed or the feed is idle.
    """
    price = float(fallback)
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
    return make_seed_bar(price=price)


def run_with_timeout(cerebro, timeout_seconds=60):
    """Run *cerebro* with a daemon-timer hard timeout."""
    timer = threading.Timer(timeout_seconds, cerebro.runstop)
    timer.daemon = True
    timer.start()
    try:
        return cerebro.run()
    finally:
        timer.cancel()


# ---------------------------------------------------------------------------
# CTP trading admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CtpWriteAdmission:
    """Outcome of a CTP write-admission probe for one certification case."""

    ok: bool
    reason: str = ""
    next_action: str = ""


def refresh_ctp_preflight(store, symbol, timeout=15.0):
    """Refresh the typed CTP startup-query snapshot before a local decision.

    ``BtApiBroker._placement_safety_error`` rejects any new CTP exposure until
    ``store.get_ctp_query_health()["evidence_complete"]`` is ``True`` for the
    live session, and the cached snapshot expires after
    ``ctp_query_max_age_seconds`` (default 30s).  Refreshing here is what lets
    the broker run its own validation at all: without it every local check
    (instrument, price tick, max size) is pre-empted by
    ``ctp_query_evidence_incomplete``.
    """
    preflight = getattr(store, "get_ctp_preflight_snapshot", None)
    if not callable(preflight):
        return None
    health_getter = getattr(store, "get_ctp_query_health", None)
    if callable(health_getter):
        health = health_getter()
        if isinstance(health, dict) and health.get("evidence_complete") is True:
            return health
    snapshot = preflight(symbol, timeout=timeout)
    if callable(health_getter):
        health = health_getter()
        if not isinstance(health, dict) or health.get("evidence_complete") is not True:
            errors = (health or {}).get("evidence_errors") or ["ctp_query_snapshot_missing"]
            raise RuntimeError(f"CTP preflight evidence incomplete: {errors}")
        return health
    return snapshot


def ensure_ctp_trading_admission(store, symbol, timeout=15.0):
    """Report whether this session may legally send a new order to the counter.

    A fresh typed preflight is necessary but not sufficient.  The SDK only
    arms native writes for fronts frozen in its registered-simulation registry
    (``bt_api_ctp.ctp_env_selector``); SimNow's official fronts are not in that
    registry, so arming fails closed with
    ``ctp_execution_gate_environment_unverified`` and the first real order is
    then rejected by the SDK with ``ctp_execution_gate_native_write_blocked``.
    Certification cases must record that as ``BLOCKED`` (an environment
    limitation), not as ``FAIL`` (a code defect).
    """
    preflight = getattr(store, "get_ctp_preflight_snapshot", None)
    if not callable(preflight):
        return CtpWriteAdmission(True)
    try:
        snapshot = preflight(symbol, timeout=timeout)
    except Exception as exc:
        return CtpWriteAdmission(
            False,
            f"CTP preflight 失败: {type(exc).__name__}: {exc}",
            "检查 SimNow 前置连通性与账户凭据",
        )

    health_getter = getattr(store, "get_ctp_query_health", None)
    health = health_getter() if callable(health_getter) else {}
    if not isinstance(health, dict) or health.get("evidence_complete") is not True:
        errors = (health or {}).get("evidence_errors") or ["ctp_query_snapshot_missing"]
        return CtpWriteAdmission(
            False,
            f"CTP preflight 证据不完整: {errors}",
            "检查 SimNow typed 查询覆盖率与账号状态",
        )

    arm = getattr(store, "arm_registered_sim_execution", None)
    if not callable(arm):
        return CtpWriteAdmission(True)

    identity = hashlib.sha256(
        f"simnow-penetration-certification|{symbol}".encode("utf-8")
    ).hexdigest()
    cycle_id = f"{os.getenv('CERTIFICATION_CASE_ID') or 'case'}-{symbol}"
    try:
        arm(
            symbol,
            strategy_identity_sha256=identity,
            execution_cycle_id=cycle_id,
            preflight_sha256=str((snapshot or {}).get("snapshot_sha256") or ""),
        )
    except Exception as exc:
        return CtpWriteAdmission(
            False,
            f"CTP 写单授权不可用: {type(exc).__name__}: {exc}",
            "SimNow 官方前置不在 SDK 注册仿真白名单；真实下单需 provider='btapi' + approval receipt",
        )
    return CtpWriteAdmission(True)


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
        """Tee stream that writes to both console and file."""

        def __init__(self, stream, fh):
            """Initialize tee stream.

            Args:
                stream: Original stream to write to.
                fh: File handle to write to.
            """
            self._stream = stream
            self._fh = fh

        def write(self, data):
            """Write data to both streams.

            Args:
                data: Data to write.
            """
            self._stream.write(data)
            self._fh.write(data)

        def flush(self):
            """Flush both streams."""
            self._stream.flush()
            self._fh.flush()

    log_fh = open(stdout_log, "w", encoding="utf-8")
    sys.stdout = _Tee(_orig_stdout, log_fh)
    sys.stderr = _Tee(_orig_stderr, log_fh)

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
