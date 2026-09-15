"""Iteration 28 AC28-05: pickle cross-version + real spawn verification.

Step 1 (candidate code): load the frozen pre-split payloads and verify
        types/fields/usability (old -> new).
Step 2 (candidate code): produce a fresh OptReturn payload for the frozen
        baseline environment to read back later (new -> old; executed by
        running this script inside the baseline worktree with --read).
"""
import json
import pickle
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
M0 = REPO / "docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/evidence/m0/pickle"
OUT = REPO / "docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/evidence/m4/pickle"
DATAPATH = str(REPO / "tests" / "datas" / "2006-day-001.txt")

import backtrader as bt
import backtrader.cerebro as cerebro_mod


class SmallStrategy(bt.Strategy):
    params = (("period", 10),)

    def __init__(self):
        self.sma = bt.ind.SMA(self.data.close, period=self.p.period)

    def next(self):
        pass


def load_old():
    """Old -> new: read the frozen pre-split payloads."""
    report = {}
    with open(M0 / "cerebro-instance.pkl", "rb") as f:
        cfg = pickle.load(f)
    report["cerebro_instance"] = {
        "type": f"{type(cfg).__module__}.{type(cfg).__qualname__}",
        "is_cerebro": isinstance(cfg, cerebro_mod.Cerebro),
        "params_preload": cfg.params.preload,
        "datas": len(cfg.datas),
        "runstop_inactive": not cfg._event_stop,
        "no_external_channel": cfg._external_channel_token is None,
    }
    # usability: a configured loaded instance can still be run.
    res = cfg.run()
    report["cerebro_instance"]["ran"] = len(res) == 1
    report["cerebro_instance"]["bars"] = len(res[0].data)

    with open(M0 / "optreturn-results.pkl", "rb") as f:
        spawn_results = pickle.load(f)
    with open(M0 / "optreturn-serial.pkl", "rb") as f:
        serial_results = pickle.load(f)
    m0_manifest = json.loads((M0 / "manifest.json").read_text())

    def summarize(results):
        return [
            [
                {"params": dict(r.params), "analyzers": sorted(a.__class__.__name__ for a in r.analyzers)}
                for r in group
            ]
            for group in results
        ]

    report["optreturn"] = {
        "types": [
            f"{type(r).__module__}.{type(r).__qualname__}" for group in spawn_results for r in group
        ],
        "spawn_summary_matches_baseline": summarize(spawn_results) == m0_manifest["spawn_summary"],
        "serial_summary_matches_baseline": summarize(serial_results) == m0_manifest["serial_summary"],
        "count": (len(spawn_results), len(serial_results)),
    }
    return report


def produce_new():
    """New -> old preparation: freeze a new OptReturn payload + summary."""
    OUT.mkdir(parents=True, exist_ok=True)

    def run_opt(maxcpus):
        cerebro = bt.Cerebro(maxcpus=maxcpus)
        cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=DATAPATH))
        cerebro.optstrategy(SmallStrategy, period=(10, 20))
        cerebro.broker.setcash(100000.0)
        return cerebro.run()

    spawn_results = run_opt(2)
    with open(OUT / "optreturn-new.pkl", "wb") as f:
        pickle.dump(spawn_results, f, protocol=pickle.HIGHEST_PROTOCOL)
    summary = [[dict(r.params) for r in group] for group in spawn_results]
    (OUT / "new-manifest.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "types": [
                    f"{type(r).__module__}.{type(r).__qualname__}"
                    for group in spawn_results
                    for r in group
                ],
                "spawn_order": [g[0].params["period"] for g in spawn_results],
            },
            indent=1,
        )
    )
    return {"produced": True, "groups": len(spawn_results)}


def read_new():
    """Old -> (runs on baseline code): read the payload produced by the split."""
    with open(OUT / "optreturn-new.pkl", "rb") as f:
        results = pickle.load(f)
    manifest = json.loads((OUT / "new-manifest.json").read_text())
    summary = [[dict(r.params) for r in group] for group in results]
    return {
        "loaded_groups": len(results),
        "summary_matches": summary == manifest["summary"],
        "types_read": [
            f"{type(r).__module__}.{type(r).__qualname__}" for group in results for r in group
        ],
    }


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = {}
    if mode in ("all", "load-old"):
        out["load_old"] = load_old()
    if mode in ("all", "produce-new"):
        out["produce_new"] = produce_new()
    if mode == "read-new":
        out["read_new"] = read_new()
    print(json.dumps(out, indent=1))
