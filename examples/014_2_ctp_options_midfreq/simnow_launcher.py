"""SimNow Set-2 (7x24) live launcher for the 014_2 engineering smoke.

Local modification entry (user-approved): reads the SimNow Set-2 credentials
and fronts from this directory's ``.env``, builds an authenticated
``bt_api_py.BtApi`` and injects it into the example's existing fail-closed
``run_engineering_smoke(raw_config, api=...)`` assembly path.

- Never modifies run.py / simnow_adapter.py / the strategy itself;
- the injected chain stays ``market_data_only`` read-only with no session
  start and no orders;
- missing credentials or connection failures abort immediately.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import backtrader as bt

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CTP_EXCHANGE = "CTP___FUTURE"


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a local .env file into a plain dict without shell evaluation.

    Comments and blank lines are skipped and values are only quote-stripped;
    a missing file yields an empty dict.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def build_exchange_kwargs(env: dict[str, str]) -> dict[str, Any]:
    """Build the single-exchange ``CTP___FUTURE`` kwargs for ``BtApi(exchange_kwargs=...)``.

    Credentials come from .env (CTP_USER_ID/CTP_PASSWORD required, exit on
    missing); the fronts default to the SimNow Set-2 7x24 4000x port group and
    ``require_ctp_profile`` pins the session to that profile so the SDK cannot
    silently drift to another environment.
    """
    required = ("CTP_USER_ID", "CTP_PASSWORD")
    missing = [key for key in required if not str(env.get(key) or "").strip()]
    if missing:
        raise SystemExit(f"simnow_launcher: missing {missing} in {HERE / '.env'}")
    profile = str(env.get("CTP_ENV_PROFILE") or "set2_7x24_4000x").strip()
    return {
        CTP_EXCHANGE: {
            "broker_id": str(env.get("CTP_BROKER_ID") or "9999").strip(),
            "user_id": str(env["CTP_USER_ID"]).strip(),
            "password": str(env["CTP_PASSWORD"]),
            "app_id": str(env.get("CTP_APP_ID") or "simnow_client_test").strip(),
            "auth_code": str(env.get("CTP_AUTH_CODE") or "0000000000000000").strip(),
            "td_front": str(env.get("CTP_TD_FRONT") or "tcp://182.254.243.31:40001").strip(),
            "md_front": str(env.get("CTP_MD_FRONT") or "tcp://182.254.243.31:40011").strip(),
            "ctp_env_profile": profile,
            "require_ctp_profile": profile,
            "auto_settlement_confirm": False,
        }
    }


# ---------------- live execution-channel probe ----------------


class ExecutionChannelProbe(bt.Strategy):
    """Drive one quote -> order -> cancel -> terminal-state cycle.

    The order uses a far-from-market limit (bid minus N minimum ticks) so
    defensive depth keeps it unfilled; the round trip only verifies the quote,
    order-submission and cancellation channels.
    """

    params = (
        ("symbols", ()),
        ("exchange_id", "CZCE"),
        ("price_offset_ticks", 50),
        ("hold_seconds", 2.0),
        ("run_timeout", 120.0),
    )

    def __init__(self):
        """Bind the probe state machine: phase journal, counters and clock."""
        self._store = getattr(self.datas[0], "store", None)
        self._phase = "waiting_quote"
        self._events: list[dict[str, Any]] = []
        self._probe_ticks = 0
        self._order = None
        self._accepted_at = None
        self._price_tick = 1.0
        self._started = time.monotonic()

    def _record(self, **fields: Any) -> None:
        entry = {
            "phase": self._phase,
            "elapsed_s": round(time.monotonic() - self._started, 3),
            "ticks": self._probe_ticks,
            **fields,
        }
        self._events.append(entry)
        print("[live-probe] " + json.dumps(entry, ensure_ascii=False, default=str), flush=True)

    def _finish(self, status: str, **extra: Any) -> None:
        self._record(event="probe_finished", status=status, **extra)
        self._final_status = status
        self.cerebro.runstop()

    @staticmethod
    def _instrument_price_tick(snapshot: Any) -> float:
        row = snapshot.get("instrument") if isinstance(snapshot, dict) else None
        if isinstance(row, dict):
            for key in ("PriceTick", "price_tick"):
                value = row.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                    return float(value)
        return 1.0

    def notify_tick(self, tick: Any) -> None:
        """Drive the phase machine on every live tick of the primary leg.

        waiting_quote -> preflight (typed startup queries refresh the
        placement-gate evidence) -> wait_data_ready (wait for the first closed
        aggregated bar; order construction reads data.close[0]) ->
        order_submitted -> cancel_wait -> cancel_sent -> terminal state.
        The primary-leg book is refreshed to the latest bid/ask and the order
        price uses the freshest level.
        """
        self._probe_ticks += 1
        symbol = getattr(tick, "symbol", None)
        if symbol == self.p.symbols[0]:
            bid = float(getattr(tick, "bid_price", 0) or 0)
            ask = float(getattr(tick, "ask_price", 0) or 0)
            if bid > 0 and ask > 0 and ask >= bid:
                self._latest_bid, self._latest_ask = bid, ask
        if self._phase == "waiting_quote" and symbol == self.p.symbols[0]:
            if not getattr(self, "_latest_bid", 0):
                return
            self._record(
                event="first_valid_quote", symbol=symbol, bid=self._latest_bid, ask=self._latest_ask
            )
            # Refresh the typed startup preflight so BtApiBroker's placement
            # gate (ctp_query_evidence_incomplete) has complete fresh evidence.
            self._phase = "preflight"
            try:
                snapshot = self._store.get_ctp_preflight_snapshot(
                    instrument_id=symbol,
                    exchange_id=self.p.exchange_id,
                    timeout=15.0,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the operator
                self._finish("PREFLIGHT_FAILED", error=str(exc))
                return
            health = self._store.get_ctp_query_health()
            self._record(
                event="preflight_complete",
                evidence_complete=health.get("evidence_complete"),
                evidence_errors=health.get("evidence_errors"),
            )
            if health.get("evidence_complete") is not True:
                self._finish("PREFLIGHT_EVIDENCE_INCOMPLETE")
                return
            self._price_tick = self._instrument_price_tick(snapshot)
            self._phase = "wait_data_ready"
            return
        if self._phase == "wait_data_ready":
            # Order construction reads data.close[0]; wait for the first
            # closed aggregated bar so the OHLC lines are non-empty.
            data = self.getdatabyname(self.p.symbols[0])
            if len(data) < 1:
                return
            self._record(event="data_ready", bars=len(data))
            price = round(
                self._latest_bid - self.p.price_offset_ticks * self._price_tick, 10
            )
            if price <= 0:
                self._finish("INVALID_LIMIT_PRICE", bid=self._latest_bid, computed=price)
                return
            self._phase = "order_submitted"
            try:
                self._order = self.buy(data=data, size=1, exectype=bt.Order.Limit, price=price)
            except Exception as exc:  # noqa: BLE001 - recorded as a controlled terminal state
                # The request crossed the full broker gate chain and reached
                # the SDK client; the SDK execution gate (no production signer
                # in this iteration) blocks the native write. Same gate covers
                # ReqOrderAction (cancel). Record and stop in a known state.
                self._record(
                    event="order_submit_error",
                    error=type(exc).__name__,
                    message=str(exc)[:300],
                )
                self._finish(
                    "ORDER_WRITE_BLOCKED_BY_SDK_GATE",
                    note=(
                        "Quote + order-request channel verified to the SDK boundary; "
                        "native order writes require the operator approval trust root "
                        "(ctp-execution-entry-approval-v1), which has no production "
                        "signer in this SDK iteration. Cancel shares the same gate."
                    ),
                )
                return
            self._record(event="order_submitted", symbol=self.p.symbols[0], price=price, size=1)
        elif self._phase == "cancel_wait" and self._accepted_at is not None:
            if time.monotonic() - self._accepted_at >= self.p.hold_seconds:
                self._phase = "cancel_sent"
                self.cancel(self._order)
                self._record(event="cancel_sent", ref=getattr(self._order, "ref", None))

    def notify_order(self, order: Any) -> None:
        """Track our own order only: Accepted starts the hold clock, terminal ends the run.

        Only a zero-fill Canceled/Cancelled counts as PASS_EXECUTION_CHANNEL —
        any fill means the far-from-market defense failed and yields TERMINAL_*.
        """
        if self._order is None or getattr(order, "ref", None) != self._order.ref:
            return
        status = order.getstatusname()
        executed = float(getattr(order, "executed", None) and order.executed.size or 0)
        self._record(event="order_status", status=status, executed=executed)
        if status == "Accepted":
            self._accepted_at = time.monotonic()
            self._phase = "cancel_wait"
        elif status in ("Canceled", "Cancelled", "Rejected", "Expired", "Completed"):
            final = (
                "PASS_EXECUTION_CHANNEL"
                if status in ("Canceled", "Cancelled") and executed == 0
                else f"TERMINAL_{status.upper()}"
            )
            self._finish(final, order_status=status, executed=executed)

    def next(self) -> None:
        """Bounded watchdog: abort with TIMEOUT if the cycle stalls past run_timeout."""
        if time.monotonic() - self._started > self.p.run_timeout:
            self._finish("TIMEOUT", phase=self._phase)


def _live_symbols() -> list[str]:
    override = os.environ.get("SIMNOW_LAUNCHER_SYMBOLS", "").strip()
    if override:
        return [token.strip().split(".")[-1] for token in override.split(",") if token.strip()]
    try:
        from run import load_config

        candidate = load_config(HERE / "config.yaml").get("candidate") or {}
    except Exception:  # noqa: BLE001 - fall back to the SA dominant legs
        candidate = {}
    symbols = [
        str(candidate.get(name) or "").split(".")[-1]
        for name in ("future", "call", "put")
    ]
    symbols = [symbol for symbol in symbols if symbol]
    return symbols or ["FG701", "FG701C970", "FG701P970"]


def run_live(env: dict[str, str]) -> int:
    """Quote -> order -> cancel closed loop on the SimNow Set-2 7x24 account."""

    symbols = _live_symbols()
    exchange_id = os.environ.get("SIMNOW_LAUNCHER_EXCHANGE", "CZCE").strip() or "CZCE"

    store = bt.stores.BtApiStore(
        provider="ctp",
        td_address=str(env.get("CTP_TD_FRONT") or "tcp://182.254.243.31:40001").strip(),
        md_address=str(env.get("CTP_MD_FRONT") or "tcp://182.254.243.31:40011").strip(),
        broker_id=str(env.get("CTP_BROKER_ID") or "9999").strip(),
        investor_id=str(env["CTP_USER_ID"]).strip(),
        password=str(env["CTP_PASSWORD"]),
        app_id=str(env.get("CTP_APP_ID") or "simnow_client_test").strip(),
        auth_code=str(env.get("CTP_AUTH_CODE") or "0000000000000000").strip(),
    )
    broker = bt.brokers.BtApiBroker(
        store=store,
        position_mode="net",
        position_sync_policy="startup",
        cash_check_enabled=False,
        force_refresh_queries=False,
        account_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    for symbol in symbols:
        cerebro.adddata(
            store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Ticks,
                backfill_start=False,
                qcheck=0.05,
                dispatch_ticks=True,
            ),
            name=symbol,
        )
    console = os.getenv("TRADE_LOGGER_CONSOLE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    log_dir = HERE / "reports" / "trade-logger" / time.strftime("%Y%m%d_%H%M%S")
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(log_dir),
        log_format="json",
        log_to_console=console,
        log_ticks=console,
        log_bars=False,
        log_positions=False,
        log_indicators=False,
        log_value=False,
        log_position_snapshot=False,
    )
    cerebro.addstrategy(
        ExecutionChannelProbe,
        symbols=tuple(symbols),
        exchange_id=exchange_id,
    )
    print(
        json.dumps(
            {"live_symbols": symbols, "exchange": exchange_id, "td_front": env.get("CTP_TD_FRONT")},
            ensure_ascii=False,
        ),
        flush=True,
    )
    strategy = cerebro.run(preload=False, runonce=False)[0]
    report = {
        "mode": "simnow_live_execution_channel",
        "symbols": symbols,
        "status": getattr(strategy, "_final_status", "UNKNOWN"),
        "ticks_seen": strategy._probe_ticks,
        "events": strategy._events,
        "trade_logger_dir": str(log_dir),
        "note": "Far-from-market limit order by design; no fill is expected or claimed.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if report["status"] == "PASS_EXECUTION_CHANNEL" else 2


def wait_ctp_session_ready(api: Any, timeout: float = 30.0) -> dict[str, Any]:
    """Trigger the lazy CTP connect and wait (bounded) for auth/login."""

    feed = api.exchange_feeds.get(CTP_EXCHANGE)
    if feed is None:
        api.close()
        raise SystemExit("simnow_launcher: CTP feed was not created by BtApi")
    try:
        feed.get_query_session_scope()
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator below
        api.close()
        raise SystemExit(f"simnow_launcher: CTP connect failed: {exc}") from exc
    deadline = time.monotonic() + max(float(timeout), 1.0)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = dict(api.get_ctp_session_state(exchange_name=CTP_EXCHANGE) or {})
        if last.get("account_fingerprint") and last.get("read_only_ready"):
            return last
        time.sleep(0.25)
    return last


def main() -> int:
    """Dispatch on the optional ``live`` subcommand; default builds the smoke chain.

    ``live``: the quote→order→cancel execution-channel round trip
    (run_live). Default: build an authenticated BtApi and inject it into the
    example's engineering_smoke assembly path. Process environment variables
    take precedence over this directory's .env.
    """
    env = {**load_env_file(HERE / ".env"), **dict(os.environ)}
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        missing = [k for k in ("CTP_USER_ID", "CTP_PASSWORD") if not env.get(k)]
        if missing:
            raise SystemExit(f"simnow_launcher: missing {missing} in {HERE / '.env'}")
        return run_live(env)

    from bt_api_py.bt_api import BtApi

    from run import load_config, run_engineering_smoke

    raw_config = load_config(HERE / "config.yaml")

    api = BtApi(
        exchange_kwargs=build_exchange_kwargs(env),
        debug=False,
    )
    session = wait_ctp_session_ready(api)
    if not (session.get("account_fingerprint") and session.get("read_only_ready")):
        api.close()
        raise SystemExit(
            "simnow_launcher: CTP session not ready in 30s: "
            + json.dumps(session, ensure_ascii=False, default=str)
        )
    try:
        report = run_engineering_smoke(raw_config, api=api)
        report["simnow_launcher_session"] = {
            "environment_profile": session.get("environment_profile"),
            "trading_day": session.get("trading_day"),
            "account_fingerprint": session.get("account_fingerprint"),
            "read_only_ready": session.get("read_only_ready"),
        }
    finally:
        try:
            api.close()
        except Exception:
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    status = str(report.get("status") or "")
    return 0 if "PASS" in status or "BUILT" in status else 2


if __name__ == "__main__":
    raise SystemExit(main())
