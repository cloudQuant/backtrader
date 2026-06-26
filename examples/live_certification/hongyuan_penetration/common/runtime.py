"""Store / Broker / Feed initialisation helpers and subprocess entry-point (宏源期货)."""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_SUITE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SUITE_DIR.parents[2]

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
        store.start()
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
