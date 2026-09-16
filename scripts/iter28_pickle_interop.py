"""Write/read local pickle contracts against an explicitly selected source tree.

Run this same script in two isolated interpreters with PYTHONPATH pointing to
the candidate and a frozen pre-split checkout. Output includes the actual
import path. ``--analyzers`` exercises results that contain nonempty analysis.
"""

import argparse
import datetime
import json
import pickle
from pathlib import Path

import backtrader as bt


class InteropStrategy(bt.Strategy):
    params = (("period", 2),)

    def next(self):
        if len(self) == self.p.period:
            self.buy(size=1)
        elif len(self) == 15:
            self.close()


def make_engine():
    engine = bt.Cerebro(stdstats=False, maxcpus=1)
    engine.adddata(
        bt.feeds.BacktraderCSVData(
            dataname=str(Path(__file__).resolve().parents[1] / "tests/datas/2006-day-001.txt"),
            todate=datetime.datetime(2006, 2, 15),
        )
    )
    return engine


def summarize(results):
    return [
        {
            "period": group[0].p.period,
            "type": f"{type(group[0]).__module__}.{type(group[0]).__qualname__}",
            "analyses": [analyzer.get_analysis() for analyzer in group[0].analyzers],
        }
        for group in results
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("write", "read"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--analyzers", action="store_true")
    args = parser.parse_args()
    if args.mode == "write":
        args.directory.mkdir(parents=True, exist_ok=True)
        configured = make_engine()
        configured.addstrategy(InteropStrategy)
        (args.directory / "configured.pkl").write_bytes(pickle.dumps(configured))
        strategy = configured.run()[0]
        optimized = make_engine()
        optimized.optstrategy(InteropStrategy, period=(2, 4))
        if args.analyzers:
            optimized.addanalyzer(bt.analyzers.TradeAnalyzer)
        results = optimized.run()
        (args.directory / "results.pkl").write_bytes(pickle.dumps(results))
        manifest = {
            "bars": len(strategy.data),
            "value": configured.broker.getvalue(),
            "results": summarize(results),
        }
        (args.directory / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    else:
        manifest = json.loads((args.directory / "manifest.json").read_text())
        configured = pickle.loads((args.directory / "configured.pkl").read_bytes())
        assert type(configured) is bt.Cerebro
        assert not configured._run_active and not configured._event_stop
        assert configured._external_channel_token is None
        assert configured.p is configured.params
        strategy = configured.run()[0]
        assert len(strategy.data) == manifest["bars"] > 15
        assert configured.broker.getvalue() == manifest["value"]
        results = pickle.loads((args.directory / "results.pkl").read_bytes())
        assert json.loads(json.dumps(summarize(results))) == manifest["results"]
        assert all(group[0].p is group[0].params for group in results)
    print(json.dumps({"mode": args.mode, "backtrader": bt.__file__, "manifest": manifest}))


if __name__ == "__main__":
    main()
