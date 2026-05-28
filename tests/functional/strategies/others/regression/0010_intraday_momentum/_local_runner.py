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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import backtrader as bt
import yaml


# Auto-added: ensure repo root is on sys.path so tests.test_utils resolves
import sys as _migration_sys
from pathlib import Path as _MigrationPath
_REPO_ROOT_FOR_VENDORED = _MigrationPath(__file__).resolve().parents[6]
if str(_REPO_ROOT_FOR_VENDORED) not in _migration_sys.path:
    _migration_sys.path.insert(0, str(_REPO_ROOT_FOR_VENDORED))

from tests.test_utils.benchmark_metrics import add_benchmark_analyzer, collect_benchmark_metrics
from strategy_intraday_momentum import (
    GoldIntradayMomentumStrategy,
    IntradayMomentumFeed,
    load_mt5_csv,
    prepare_intraday_momentum_features,
)

MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


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
    raw = load_mt5_csv(resolve_data_path(data_cfg["csv_path"]), fromdate=fromdate, todate=todate)
    if raw.empty:
        raise ValueError("Loaded data frame is empty")
    frame = prepare_intraday_momentum_features(raw, config.get("params", {}))
    if frame.empty:
        raise ValueError("Prepared feature frame is empty")
    print(f"Loaded {len(frame)} bars: {frame.index[0]} -> {frame.index[-1]}")
    return frame


def build_cerebro(frame, config):
    params = dict(config.get("params", {}))
    commission_pct = float(params.get("commission_pct", 0.0002))
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(config["backtest"]["initial_cash"]))
    cerebro.broker.setcommission(commission=commission_pct)
    data_feed = IntradayMomentumFeed(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.adddata(data_feed, name=config["data"]["symbol"])
    cerebro.addstrategy(GoldIntradayMomentumStrategy, **params)
    add_benchmark_analyzer(cerebro, name="benchmark")
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
        factor=MINUTES_PER_TRADING_YEAR,
        annualize=True,
        riskfreerate=0,
    )
    cerebro.addanalyzer(
        bt.analyzers.Returns,
        _name="returns",
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
        tann=MINUTES_PER_TRADING_YEAR,
    )
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    run(plot=args.plot)


if __name__ == "__main__":
    main()
