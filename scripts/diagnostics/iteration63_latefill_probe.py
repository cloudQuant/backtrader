"""Observe five synthetic late-fill scenarios using the existing direct-mode fakes.

These are known-behavior observations, not product acceptance. Exit 0 means the
observation checks matched, including the recorded correction and restart gaps.
No provider, account, network, credential, or private capture is used.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
import tempfile
import traceback
from pathlib import Path

# Run directly from any working directory using this checkout and its test fakes.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtrader as bt  # noqa: E402
from bt_api_base.direct_write_protocol import (  # noqa: E402
    DirectExecutionEvent,
    DirectExecutionEventKind,
    NativeOrderIdentity,
)
from tests.unit.brokers.direct._fakes import (  # noqa: E402
    EXCHANGE,
    SYMBOL,
    TODAY,
    Env,
    crash,
    position,
    quiet,
)


class Audit(bt.Analyzer):
    def start(self):
        self.events = []

    def notify_order(self, order):
        self.events.append(["order", order.getstatusname(), order.executed.size, order.ref])

    def notify_trade(self, trade):
        self.events.append(
            ["trade", trade.status, trade.size, trade.price, trade.pnl, trade.commission]
        )

    def get_analysis(self):
        return self.events


class Driver(bt.Strategy):
    params = (("env", None), ("qty", 1))

    def __init__(self):
        self.events = []
        self.original = None
        self.call = None

    def notify_order(self, order):
        self.events.append(
            ["order", order.getstatusname(), order.executed.size, order.ref, dict(order.info)]
        )

    def notify_trade(self, trade):
        self.events.append(
            ["trade", trade.status, trade.size, trade.price, trade.pnl, trade.commission]
        )

    def next(self):
        env, broker = self.p.env, self.broker
        if len(self) == 1:
            quiet(broker)
            self.original = broker.buy(
                self, self.data, 2, price=3500.0, exectype=bt.Order.Limit, offset="open"
            )
            self.call = env.api.place_calls[-1]
        elif len(self) == 2:
            env.api.session_generation = 2
            broker.next()
            broker._direct_gap_due = 0
            broker._direct_return_gap_poll()
            broker.next()
            self.events.append(
                [
                    "checkpoint_rejected",
                    self.original.getstatusname(),
                    self.original.ref,
                    broker.direct_writes_blocked(),
                ]
            )
        elif len(self) in (3, 4):
            env.api.push(fill(self.call.identity, self.p.qty))
        elif len(self) == 5:
            self.events.append(
                [
                    "checkpoint_replay",
                    self.original.getstatusname(),
                    self.original.executed.size,
                    broker.getposition(self.data, side="long").size,
                ]
            )

    def stop(self):
        self.final = {
            "status": self.original.getstatusname(),
            "size": self.original.executed.size,
            "position": self.broker.getposition(self.data, side="long").size,
            "trade": [
                {
                    "size": trade.size,
                    "price": trade.price,
                    "status": trade.status,
                    "commission": trade.commission,
                }
                for trades in self._trades[self.data].values()
                for trade in trades
            ],
            "events": self.events,
            "analyzer": self.analyzers.audit.get_analysis(),
            "trade_analyzer": self.analyzers.tradeaudit.get_analysis(),
            "marker": self.p.env.state().pending.get(self.call.marker_id),
        }


def fill(identity, qty):
    fields = dict(identity.fields)
    fields["order_sys_id"] = "7771"
    return DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=SYMBOL,
        identity=NativeOrderIdentity(
            exchange_name=EXCHANGE,
            client_order_id=identity.client_order_id,
            fields=fields,
            session_generation=identity.session_generation,
        ),
        exchange_order_id="7771",
        side="buy",
        offset="open",
        trade_id="T-LATE-1",
        trade_price=3500.0,
        trade_qty=float(qty),
        trading_day=TODAY,
    )


def live_case(qty):
    with tempfile.TemporaryDirectory(prefix="bt63_live_") as tmp:
        env = Env(Path(tmp))
        env.store.get_notifications = list
        env.feed.p.bars = [(dt.datetime(2026, 11, 5, 9, i), 3500.0) for i in range(1, 8)]
        cerebro = bt.Cerebro(stdstats=False, quicknotify=False)
        cerebro.adddata(env.feed)
        broker = env.broker(first_init=True, direct_return_gap_quiet_period=0.0)
        cerebro.setbroker(broker)
        cerebro.addstrategy(Driver, env=env, qty=qty)
        cerebro.addanalyzer(Audit, _name="audit")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeaudit")
        try:
            return cerebro.run(runonce=False, preload=False)[0].final
        finally:
            env.close()


def restart_case(qty, after_fill=False):
    with tempfile.TemporaryDirectory(prefix="bt63_restart_") as tmp:
        env = Env(Path(tmp))
        try:
            broker = env.start(first_init=True, direct_return_gap_quiet_period=0.0)
            quiet(broker)
            order = broker.buy(
                env.strategy, env.feed, 2, price=3500.0, exectype=bt.Order.Limit, offset="open"
            )
            call = env.api.place_calls[-1]
            env.api.session_generation = 2
            broker.next()
            broker._direct_gap_due = 0
            broker._direct_return_gap_poll()
            broker.next()
            before_rejection = order.getstatusname()
            if after_fill:
                env.api.push(fill(call.identity, qty))
                broker.next()
                env.api.positions = [position("long", qty, qty, 0)]
            before = {
                "status": order.getstatusname(),
                "rejection": before_rejection,
                "size": order.executed.size,
                "ref": order.ref,
            }
            crash(broker)
            again = env.start(direct_return_gap_quiet_period=0.0)
            quiet(again)
            event = fill(call.identity, qty)
            before_match = again._direct_order_for_event(event)
            for _ in range(2):
                env.api.push(event)
                again.next()
            notices = []
            while True:
                notice = again.get_notification()
                if notice is None:
                    break
                notices.append([notice.getstatusname(), notice.ref, notice.executed.size])
            return {
                "before": before,
                "restored_count": len(again.get_restored_orders()),
                "match_before": before_match is not None,
                "position": again.getposition(env.feed, side="long").size,
                "notices": notices,
                "applied_trade_keys": sorted(again._direct_applied_set()),
                "report": copy.deepcopy(again.get_direct_reconcile_report()),
                "marker": env.state().pending.get(call.marker_id),
            }
        finally:
            env.close()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_observations(results):
    require(all(case["ok"] for case in results.values()), "A scenario raised; inspect results")
    for name, qty, status in (("memory_partial", 1, "Partial"), ("memory_full", 2, "Completed")):
        result = results[name]["result"]
        require((result["status"], result["size"], result["position"]) == (status, qty, qty), name)
        orders = [(event[1], event[2]) for event in result["events"] if event[0] == "order"]
        require(orders == [("Submitted", 0), ("Rejected", 0), (status, qty)], name + " notices")
        require(
            [event[1] for event in result["analyzer"] if event[0] == "order"]
            == ["Submitted", "Rejected", status],
            name + " analyzer orders",
        )
        require(len(result["trade"]) == 1 and result["trade"][0]["size"] == qty, name + " trade")
        require(result["trade_analyzer"]["total"] == {"total": 1, "open": 1}, name + " analyzer")
        require(
            len([event for event in result["analyzer"] if event[0] == "trade"]) == 1,
            name + " analyzer trades",
        )
        # This deliberately observes an unresolved correction gap, not success.
        require(
            result["marker"]["facts"]["final_status"] == "not_found_at_venue",
            name + " known marker gap changed",
        )
        last_order = [event for event in result["events"] if event[0] == "order"][-1]
        require(
            last_order[4].get("error_code") == "not_found_at_venue",
            name + " known correction notice gap changed",
        )
    for name in ("restart_partial", "restart_full"):
        result = results[name]["result"]
        # This deliberately observes the missing restored binding, not success.
        require(
            result["before"]["status"] == "Rejected"
            and not result["match_before"]
            and result["restored_count"] == 0,
            name + " known restart gap changed",
        )
        require(
            result["position"] == 0
            and not result["notices"]
            and result["report"]["trade_match_buffer"]["pending"] == 1,
            name + " known buffered fill gap changed",
        )
    result = results["restart_after_partial_replay"]["result"]
    require(
        result["before"]["rejection"] == "Rejected"
        and result["before"]["size"] == 1
        and result["position"] == 1
        and len(result["applied_trade_keys"]) == 1
        and not result["notices"],
        "restart after fill replay",
    )


def output_directory(value):
    if value is None:
        return Path(tempfile.mkdtemp(prefix="bt63_latefill_evidence_"))
    path = Path(value).expanduser().absolute()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or any(path.iterdir()):
        raise ValueError("--output-dir must be a new or empty directory")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", help="new or empty directory; default: new temporary directory"
    )
    args = parser.parse_args(argv)
    try:
        output = output_directory(args.output_dir)
        # Exclusive creation prevents overwriting evidence even if the directory races.
        evidence = (output / "results.json").open("x", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    scenarios = (
        ("memory_partial", lambda: live_case(1)),
        ("memory_full", lambda: live_case(2)),
        ("restart_partial", lambda: restart_case(1)),
        ("restart_full", lambda: restart_case(2)),
        ("restart_after_partial_replay", lambda: restart_case(1, after_fill=True)),
    )
    results = {}
    for name, run in scenarios:
        try:
            results[name] = {"ok": True, "result": run()}
        except Exception as exc:
            results[name] = {"ok": False, "error": repr(exc), "traceback": traceback.format_exc()}
    failure = None
    try:
        check_observations(results)
    except Exception as exc:
        failure = {"error": repr(exc), "traceback": traceback.format_exc()}
    payload = {
        "evidence_level": "UNIT/FAKE; synthetic only",
        "acceptance": "NOT_RUN: exit 0 means known observations matched, not product acceptance",
        "known_gaps": [
            "After a matched late fill, the marker and order notice retain not_found_at_venue.",
            "After restart following rejection, the original order is not bound and the fill remains buffered.",
        ],
        "observation_checks_passed": failure is None,
        "failure": failure,
        "scenarios": results,
    }
    with evidence:
        json.dump(payload, evidence, indent=2, default=str, ensure_ascii=False)
        evidence.write("\n")
    print(f"Synthetic evidence: {output / 'results.json'}")
    print("Known correction and restart gaps observed; product acceptance NOT_RUN.")
    if failure:
        print(f"Observation checks failed: {failure['error']}", file=sys.stderr)
        return 1
    print("Observation checks passed for five scenarios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
