"""Run isolated, real spawn optimization contracts for Cerebro.

Invoke with the repository's Anaconda Python using ``-m scripts.iter28_spawn_probe``.
No live services are used. Optional logging writes only under the supplied directory.
"""

import argparse
import datetime
import faulthandler
import json
import multiprocessing
import os
import sys
from pathlib import Path

import backtrader as bt
from backtrader.utils.log_message import configure_logging, get_logger, reset_logging


class SpawnStrategy(bt.Strategy):
    """Trade fixed local bars so workers return useful, comparable results."""

    params = (("period", 2),)

    def start(self):
        get_logger("backtrader.iter28_spawn").warning(
            "spawn-contract pid=%s period=%s", os.getpid(), self.p.period
        )

    def next(self):
        if len(self) == self.p.period:
            self.buy(size=self.p.period)
        elif len(self) == 15:
            self.close()


class SpawnAnalysis(bt.Analyzer):
    """Capture real bar count, account value and worker identity."""

    def stop(self):
        self.rets = {
            "bars": len(self.strategy),
            "value": round(self.strategy.broker.getvalue(), 8),
            "position": self.strategy.position.size,
            "pid": os.getpid(),
        }


def run_optimization(maxcpus, optreturn, optdatas):
    cerebro = bt.Cerebro(maxcpus=maxcpus, optreturn=optreturn, optdatas=optdatas, stdstats=False)
    cerebro.broker.setcash(100000.0)
    data = Path(__file__).resolve().parents[1] / "tests/datas/2006-day-001.txt"
    cerebro.adddata(
        bt.feeds.BacktraderCSVData(dataname=str(data), todate=datetime.datetime(2006, 2, 15))
    )
    cerebro.optstrategy(SpawnStrategy, period=(2, 4, 6))
    cerebro.addanalyzer(SpawnAnalysis, _name="snapshot")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    callbacks = []
    cerebro.optcallback(callbacks.extend)
    results = cerebro.run()
    rows = []
    pids = []
    for group in results:
        result = group[0]
        assert result.p is result.params
        analysis = dict(result.analyzers.snapshot.get_analysis())
        pids.append(analysis.pop("pid"))
        assert analysis["bars"] > 15
        assert analysis["position"] == 0
        assert result.analyzers.trades.get_analysis()["total"]["closed"] == 1
        if optreturn:
            assert type(result) is bt.OptReturn
            assert result.analyzers.snapshot.strategy is None
        else:
            assert isinstance(result, SpawnStrategy)
        rows.append({"period": result.p.period, "analysis": analysis})
    assert not cerebro._run_active
    assert not cerebro._event_stop
    return {"rows": rows, "callbacks": [r.p.period for r in callbacks], "pids": pids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args()
    multiprocessing.set_start_method("spawn", force=True)
    faulthandler.dump_traceback_later(20, repeat=True)
    reset_logging()
    if args.log_dir is None:
        assert "_logging_config" not in bt.Cerebro().__getstate__()
    if args.log_dir is not None:
        configure_logging(
            level="INFO",
            log_dir=str(args.log_dir),
            script_name="iter28_spawn",
            backend="stdlib",
            console=False,
        )
    checks = []
    try:
        for optreturn in (True, False):
            for optdatas in (True, False):
                print(
                    f"spawn probe: optreturn={optreturn}, optdatas={optdatas}",
                    file=sys.stderr,
                    flush=True,
                )
                serial = run_optimization(1, optreturn, optdatas)
                spawned = run_optimization(2, optreturn, optdatas)
                assert serial["rows"] == spawned["rows"]
                assert serial["callbacks"] == spawned["callbacks"] == [2, 4, 6]
                assert all(pid != os.getpid() for pid in spawned["pids"])
                checks.append({"optreturn": optreturn, "optdatas": optdatas, **spawned})
        for child in multiprocessing.active_children():
            child.join(timeout=10)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
                raise AssertionError("optimization worker did not exit after Pool.close")
            assert child.exitcode == 0
    finally:
        faulthandler.cancel_dump_traceback_later()
        reset_logging()
    print(json.dumps({"start_method": "spawn", "parent_pid": os.getpid(), "checks": checks}))


if __name__ == "__main__":
    main()
