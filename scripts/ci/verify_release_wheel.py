"""Verify a release wheel's source identity and isolated consumer behavior.

Run with the wheel installed in a dedicated --install-root, from outside the
source checkout, with PYTHONPATH pointing only to that installation root.
"""

import argparse
import hashlib
import importlib
import json
import pathlib
import zipfile


def verify(wheel, source_root, install_root, expected_version):
    """Check every packaged source and execute deterministic consumer trades."""
    import backtrader as bt
    import pandas as pd

    install_root = install_root.resolve()
    source_root = source_root.resolve()
    assert bt.__version__ == expected_version
    assert bt.__btversion__ == tuple(int(v) for v in expected_version.split("."))
    pathlib.Path(bt.__file__).resolve().relative_to(install_root)
    checked = {}
    with zipfile.ZipFile(wheel) as package:
        names = package.namelist()
        unexpected = [
            name
            for name in names
            if not name.startswith(("backtrader/", "backtrader-" + expected_version + ".dist-info/"))
        ]
        assert not unexpected, f"Non-library files in wheel: {unexpected[:10]}"
        for name in names:
            if not name.startswith("backtrader/") or not name.endswith(".py"):
                continue
            expected = package.read(name)
            assert (source_root / name).read_bytes() == expected, name
            assert (install_root / name).read_bytes() == expected, name
            checked[name] = hashlib.sha256(expected).hexdigest()
        expected_private = {
            p.relative_to(source_root).as_posix()
            for p in (source_root / "backtrader/_cerebro").glob("*.py")
        }
        assert len(expected_private) == 9
        assert expected_private.issubset(checked)
        expected_sources = {
            p.relative_to(source_root).as_posix()
            for p in (source_root / "backtrader").rglob("*.py")
        }
        assert set(checked) == expected_sources, "Wheel omits or adds package source files"
        assert not any("account_config.yaml" in name for name in names)
        assert not any(pathlib.PurePosixPath(name).name == ".DS_Store" for name in names)

    for source_name in sorted(expected_private | {"backtrader/cerebro.py"}):
        module_name = source_name[:-3].replace("/", ".")
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]
        module = importlib.import_module(module_name)
        pathlib.Path(module.__file__).resolve().relative_to(install_root)
    assert bt.Cerebro.__module__ == "backtrader.cerebro"
    assert bt.OptReturn.__module__ == "backtrader.cerebro"

    class RoundTrip(bt.Strategy):
        def __init__(self):
            self.fills = []

        def next(self):
            if len(self) == 1:
                self.buy(size=1)
            elif len(self) == 4:
                self.close()

        def notify_order(self, order):
            if order.status == order.Completed:
                self.fills.append(order.executed.price)

    prices = list(range(100, 108))
    frame = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "volume": 10},
        index=pd.date_range("2020-01-01", periods=len(prices)),
    )
    runs = []
    for runonce in (True, False):
        engine = bt.Cerebro(stdstats=False, runonce=runonce)
        engine.adddata(bt.feeds.PandasData(dataname=frame.copy()))
        engine.addstrategy(RoundTrip)
        engine.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        strategy = engine.run()[0]
        assert len(strategy) == 8
        assert strategy.fills == [101.0, 104.0], strategy.fills
        assert engine.broker.getvalue() == 10003.0
        assert strategy.analyzers.trades.get_analysis().total.closed == 1
        runs.append({"runonce": runonce, "bars": 8, "fills": strategy.fills, "value": 10003.0})
    return {
        "status": "PASS",
        "version": bt.__version__,
        "module_file": bt.__file__,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "packaged_source_hashes": checked,
        "private_modules": sorted(expected_private),
        "runs": runs,
    }


def main():
    """Write the full verification record, failing on any identity mismatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    parser.add_argument("--install-root", required=True, type=pathlib.Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    result = verify(args.wheel, args.source_root, args.install_root, args.version)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({key: value for key, value in result.items() if key != "packaged_source_hashes"})
    )


if __name__ == "__main__":
    main()
