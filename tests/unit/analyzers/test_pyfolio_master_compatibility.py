"""Real trades and independent accounting for the restored master report API."""

import builtins
import math

import pandas as pd
import pytest

import backtrader as bt


def _run_report_strategy(runonce=True, trade=True, with_trade_analyzer=True):
    prices = [10, 10, 11, 12, 12, 14, 14, 10, 9, 9, 8, 8]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), prices),
        index=pd.date_range("2026-01-01", periods=len(prices)),
    )
    frame["volume"] = 100

    class RoundTrips(bt.Strategy):
        def next(self):
            if not trade:
                return
            if len(self) in (1, 9):
                self.buy(size=2)
            elif len(self) == 5:
                self.sell(size=3)
            elif len(self) in (3, 7, 10):
                self.close()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1000)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="asset")
    cerebro.addstrategy(RoundTrips)
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name="pf")
    if with_trade_analyzer:
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="unusual_trade_name")
    results = cerebro.run(runonce=runonce)
    benchmark = pd.DataFrame({"returns": [0.0] * len(prices)}, index=frame.index)
    return results, results[0].analyzers.pf, benchmark


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_report_matches_real_long_short_round_trips_without_empyrical(runonce, monkeypatch, capsys):
    results, analyzer, benchmark = _run_report_strategy(runonce)
    original_benchmark = benchmark.copy(deep=True)
    original_returns, _, original_transactions, _ = analyzer.get_pf_items()
    import_module = builtins.__import__

    def disallow_empyrical(name, *args, **kwargs):
        if name == "empyrical" or name.startswith("empyrical."):
            raise AssertionError("Legacy reporting must not require optional empyrical")
        return import_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", disallow_empyrical)
    performance, records = analyzer.get_format_results(results, benchmark, "equity", "alice")

    # Executions: long 2 @10->12, short 3 @14->10, long 2 @9->8.
    assert results[0].broker.getvalue() == pytest.approx(1014)
    assert records["ENTRUST_NUM"].tolist() == [2, -2, -3, 3, 2, -2]
    assert records["TRADE_PRICE"].tolist() == [10, 12, 14, 10, 9, 8]
    assert records["PROFIT_LOSS"].tolist() == [0, 4, 0, 12, 0, -2]
    assert records["TRADE_TYPE"].tolist() == ["开仓", "平仓"] * 3
    assert records["ORDER_TYPE"].tolist() == ["买入", "卖出", "卖出", "买入", "买入", "卖出"]
    assert records["TRADE_NUM"].tolist() == [1, 1, 2, 2, 3, 3]
    assert records["COMMISSION"].isna().all()  # Transactions does not record paid commissions.
    assert records["CREATE_USER"].tolist() == ["alice"] * 6
    assert records["KIND"].tolist() == ["equity"] * 6
    assert len(records.columns) == 19
    assert performance["PROFIT"] == 1.4
    assert performance["PROFIT_Y"] == round((1.014**21 - 1) * 100, 2)
    assert performance["BASE_PROFIT"] == 0
    assert performance["SUPERIOR_PROFIT"] == 1.4
    assert performance["WIN_NUM"] == 2
    assert performance["LOSS_NUM"] == 1
    assert performance["WIN_RATIO"] == 0.6667
    assert performance["RRR"] == 400
    assert performance["MDD"] == 0.2  # Equity falls from 1016 to 1014.
    assert performance["DATE_REGION"] == (
        pd.Timestamp("2026-01-08"),
        pd.Timestamp("2026-01-11"),
        None,
    )
    assert math.isnan(performance["Beta"])  # The benchmark has zero variance.
    assert performance["CREATE_USER"] == "alice"
    assert performance["UPDATE_USER"] == "alice"
    pd.testing.assert_frame_equal(benchmark, original_benchmark)
    returns_after, _, transactions_after, _ = analyzer.get_pf_items()
    pd.testing.assert_series_equal(returns_after, original_returns)
    pd.testing.assert_frame_equal(transactions_after, original_transactions)
    assert capsys.readouterr().out == ""


def test_trade_table_handles_partial_closes_multiple_symbols_and_reversal():
    _, analyzer, _ = _run_report_strategy(trade=False)
    raw = pd.DataFrame(
        {
            "symbol": ["A", "B", "A", "A", "B", "A"],
            "sid": [0, 1, 0, 0, 1, 0],
            "amount": [10, -4, -3, -9, 4, 2],
            "price": [100, 50, 110, 90, 40, 80],
            "commission": [1.0, 0.4, 0.3, 0.9, 0.4, 0.2],
        },
        index=pd.date_range("2026-01-01", periods=6, tz="UTC"),
    )
    original = raw.copy(deep=True)
    records = analyzer._get_trade_info(raw, "equity", "alice", pair_num=1)

    assert records["ENTRUST_NUM"].tolist() == [10, -4, -3, -7, -2, 4, 2]
    assert records["PROFIT_LOSS"].tolist() == [0, 0, 30, -70, 0, 40, 20]
    assert records["TRADE_NUM"].tolist() == [1, 2, 1, 1, 3, 2, 3]
    assert records["COMMISSION"].tolist() == pytest.approx([1.0, 0.4, 0.3, 0.7, 0.2, 0.4, 0.2])
    assert records["COMMISSION"].sum() == pytest.approx(raw["commission"].sum())
    pd.testing.assert_frame_equal(raw, original)


def test_legacy_profit_loss_helper_respects_symbols_and_partial_quantity():
    _, analyzer, _ = _run_report_strategy(trade=False)
    rows = pd.DataFrame(
        {
            "ORDER_TYPE": ["开多", "开多", "平多", "平多", "平多"],
            "O_CODE": ["A", "B", "A", "B", "A"],
            "ENTRUST_NUM": [10, 2, -3, -2, -7],
            "TRADE_AMT": [1000, 100, -330, -80, -630],
        }
    )
    result = analyzer._compute_profit_loss(rows, "开多", "平多")
    assert result["PROFIT_LOSS"].tolist() == [0, 0, 30, -20, -70]
    assert analyzer._get_order_type({"TRADE_TYPE": "平仓", "amount": 2}) == "买入"
    assert analyzer._get_order_type({"TRADE_TYPE": "平仓", "amount": -2}) == "卖出"


def test_report_handles_no_trades_and_zero_variance_without_fabricated_ratios():
    results, analyzer, benchmark = _run_report_strategy(trade=False, with_trade_analyzer=False)
    performance, records = analyzer.get_format_results(results, benchmark, "equity", "alice")
    assert records.empty
    assert len(records.columns) == 19
    assert performance["PROFIT"] == performance["MDD"] == 0
    assert performance["WIN_NUM"] == performance["LOSS_NUM"] == 0
    assert performance["WIN_RATIO"] == 0
    assert performance["DATE_REGION"] is None
    for key in ("SHARPE_RATIO", "SORTINO_RATIO", "RRR", "Beta", "ALPHA", "INFO_RATIO"):
        assert math.isnan(performance[key])


def test_missing_trade_analyzer_does_not_report_nonempty_trades_as_zero():
    results, analyzer, benchmark = _run_report_strategy(with_trade_analyzer=False)
    performance, records = analyzer.get_format_results(results, benchmark, "equity", "alice")
    assert len(records) == 6
    assert performance["PROFIT"] == 1.4
    for key in ("WIN_NUM", "LOSS_NUM", "WIN_RATIO", "RRR"):
        assert math.isnan(performance[key])


def test_daily_metrics_match_independent_four_day_reference():
    _, analyzer, _ = _run_report_strategy(trade=False)
    dates = pd.date_range("2026-01-01", periods=4)
    returns = pd.Series([0.02, 0.04, -0.02, 0.0], index=dates.tz_localize("UTC"))
    benchmark = pd.Series([0.01, 0.02, -0.01, 0.0], index=dates)
    metrics = analyzer._get_performance_indicators([], returns, benchmark, "alice")

    # Strategy = 2 * benchmark: beta=2 and alpha=0; equity=1.02*1.04*0.98.
    assert metrics["PROFIT"] == 3.96
    assert metrics["BASE_PROFIT"] == 1.99
    assert metrics["SUPERIOR_PROFIT"] == 1.97
    assert metrics["PROFIT_Y"] == round((1.039584**63 - 1) * 100, 2)
    assert metrics["Beta"] == 2
    assert metrics["ALPHA"] == 0
    assert metrics["MDD"] == 2
    assert metrics["MDD_SUPERIOR_PROFIT"] == -1
    assert metrics["DAILY_SUPERIOR_PROFIT"] == 0.5
    assert metrics["SHARPE_RATIO"] == 6.1482
    assert metrics["SP_SHARPE_RATIO"] == 6.1482
    assert metrics["INFO_RATIO"] == 6.1482
    assert metrics["SORTINO_RATIO"] == 15.8745
    assert metrics["VIX"] == 0.4099
    assert metrics["BASE_VIX"] == 0.2049


def test_trade_helper_rejects_unmatched_closes_instead_of_inventing_profit():
    _, analyzer, _ = _run_report_strategy(trade=False)
    rows = pd.DataFrame({"ORDER_TYPE": ["平多"], "TRADE_AMT": [-100]})
    with pytest.raises(ValueError, match="Closing quantity"):
        analyzer._compute_profit_loss(rows, "开多", "平多")
