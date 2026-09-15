"""M0 baseline: freeze legacy pickle payloads (Cerebro + OptReturn).

Produces:
  cerebro-instance.pkl   - a configured (never-run) Cerebro
  optreturn-results.pkl  - OptReturn list from a real 2-param spawn optimization
  optreturn-serial.pkl   - same optimization with maxcpus=1
  manifest.json          - summary for later comparison
"""
import json
import os
import pickle
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

REPO = Path(__file__).resolve().parent.parent
DATAPATH = str(REPO / "tests" / "datas" / "2006-day-001.txt")

import backtrader as bt
import backtrader.cerebro as cerebro_mod


class SmallStrategy(bt.Strategy):
    params = (("period", 10),)

    def __init__(self):
        self.order_log = []
        sma = bt.ind.SMA(self.data.close, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)

    def next(self):
        if not self.position and self.crossover > 0:
            self.order_log.append(("BUY", len(self.data), self.data.close[0]))
            self.buy(size=1)
        elif self.position and self.crossover < 0:
            self.order_log.append(("SELL", len(self.data), self.data.close[0]))
            self.close()


def run_opt(maxcpus):
    cerebro = bt.Cerebro(maxcpus=maxcpus)
    data = bt.feeds.BacktraderCSVData(dataname=DATAPATH)
    cerebro.adddata(data)
    cerebro.optstrategy(SmallStrategy, period=(10, 20))
    cerebro.broker.setcash(100000.0)
    return cerebro.run()


def optreturn_summary(results):
    """Optimization results are a list of per-combination OptReturn lists."""
    out_l = []
    for group in results:
        group_summary = [
            {
                "params": dict(r.params),
                "analyzers": sorted(a.__class__.__name__ for a in r.analyzers),
            }
            for r in group
        ]
        out_l.append(group_summary)
    return out_l


def main():
    # 1) Configured, never-run Cerebro instance payload.
    cfg = bt.Cerebro(runonce=True, stdstats=False, maxcpus=1)
    cfg.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH))
    cfg.addstrategy(SmallStrategy, period=10)
    with open(out / "cerebro-instance.pkl", "wb") as f:
        pickle.dump(cfg, f, protocol=pickle.HIGHEST_PROTOCOL)

    # 2) Real spawn optimization results (OptReturn payloads).
    spawn_results = run_opt(2)
    with open(out / "optreturn-results.pkl", "wb") as f:
        pickle.dump(spawn_results, f, protocol=pickle.HIGHEST_PROTOCOL)

    # 3) Serial (maxcpus=1) results for order/equality comparison.
    serial_results = run_opt(1)
    with open(out / "optreturn-serial.pkl", "wb") as f:
        pickle.dump(serial_results, f, protocol=pickle.HIGHEST_PROTOCOL)

    manifest = {
        "cerebro_module": cerebro_mod.Cerebro.__module__,
        "optreturn_module": cerebro_mod.OptReturn.__module__,
        "spawn_count": len(spawn_results),
        "serial_count": len(serial_results),
        "spawn_summary": optreturn_summary(spawn_results),
        "serial_summary": optreturn_summary(serial_results),
        "spawn_types": [
            [type(r).__module__ + "." + type(r).__qualname__ for r in group]
            for group in spawn_results
        ],
    }
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
