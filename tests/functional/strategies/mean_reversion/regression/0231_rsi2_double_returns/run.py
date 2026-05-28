from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    for parent in BASE_DIR.parents:
        if (parent / "backtrader").is_dir() and (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Cannot find backtrader repo root")


REPO_ROOT = _find_repo_root()
SIBLING_ROOT = REPO_ROOT.parent / "back_trader"
SOURCE_STRATEGY_DIR = SIBLING_ROOT / "strategies" / "mean_reversion" / "0231_rsi2_double_returns"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SOURCE_STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_STRATEGY_DIR))

import backtrader as bt
import yaml


# Auto-added: ensure repo root is on sys.path so tests.test_utils resolves
import sys as _migration_sys
from pathlib import Path as _MigrationPath
_REPO_ROOT_FOR_VENDORED = _MigrationPath(__file__).resolve().parents[6]
if str(_REPO_ROOT_FOR_VENDORED) not in _migration_sys.path:
    _migration_sys.path.insert(0, str(_REPO_ROOT_FOR_VENDORED))

from tests.test_utils.benchmark_metrics import add_benchmark_analyzer, collect_benchmark_metrics

_ORIGINAL_RSI_SMA = bt.indicators.RSI_SMA


def _safe_rsi_sma(*args, **kwargs):
    kwargs.setdefault("safediv", True)
    return _ORIGINAL_RSI_SMA(*args, **kwargs)


bt.indicators.RSI_SMA = _safe_rsi_sma
if hasattr(bt, "ind"):
    bt.ind.RSI_SMA = _safe_rsi_sma

from strategy_rsi2_double_returns import RSI2DoubleReturnsStrategy, load_mt5_csv

TRADING_DAYS_PER_YEAR = 252


def load_config():
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_data_path(path_text: str) -> Path:
    path = (BASE_DIR / path_text).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    return path


def parse_dt(value: str | None):
    if not value:
        return None
    return datetime.datetime.fromisoformat(value)


def load_backtest_frame(config):
    data_cfg = config["data"]
    fromdate = parse_dt(data_cfg.get("fromdate"))
    todate = parse_dt(data_cfg.get("todate"))
    frame = load_mt5_csv(resolve_data_path(data_cfg["csv_path"]), fromdate=fromdate, todate=todate)
    if frame.empty:
        raise ValueError("Loaded data frame is empty")
    print(f"Loaded {len(frame)} bars: {frame.index[0]} -> {frame.index[-1]}")
    return frame


def build_cerebro(frame, config):
    params = dict(config.get("params", {}))
    commission_pct = float(params.pop("commission_pct", 0.0005))
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(config["backtest"]["initial_cash"]))
    cerebro.broker.setcommission(commission=commission_pct)
    data_feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(data_feed, name=config["data"]["symbol"])
    cerebro.addstrategy(RSI2DoubleReturnsStrategy, **params)
    add_benchmark_analyzer(cerebro, name="benchmark")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days, compression=1, factor=TRADING_DAYS_PER_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns", timeframe=bt.TimeFrame.Days, tann=TRADING_DAYS_PER_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    return cerebro


def result_path(config) -> Path:
    outputs = config.get("outputs", {})
    return (BASE_DIR / outputs.get("local_result_json", "backtest_result.json")).resolve()


def print_report(metrics, strategy_name):
    print("\n" + "=" * 60)
    print(f"BACKTEST RESULTS — {strategy_name}")
    print("=" * 60)
    for key in [
        "rows",
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "trade_num",
        "total_trades",
        "final_value",
        "sharpe_ratio",
        "annual_return",
        "max_drawdown",
        "return_rate",
    ]:
        print(f"  {key:16s}: {metrics.get(key)}")
    print("=" * 60)


def run(plot=False):
    config = load_config()
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(frame, config)
    results = cerebro.run()
    metrics = collect_benchmark_metrics(
        results[0],
        cerebro,
        frame=frame,
        config=config,
        result_path=result_path(config),
    )
    print_report(metrics, config["strategy"]["name"])
    if plot:
        cerebro.plot()
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    run(plot=args.plot)


if __name__ == "__main__":
    main()
