"""R71-165 regression for MyAnnualReturn's first observed equity value."""

import pandas as pd
import pytest

import backtrader as bt


_INITIAL_CASH = 10000.0


def _run_half_year_then_cross_year(*, runonce):
    rows = [
        ("2020-07-01", 100.0),
        ("2020-07-02", 100.0),
        ("2020-12-31", 110.0),
        ("2021-01-01", 110.0),
        ("2021-06-30", 120.0),
    ]
    prices = [price for _, price in rows]
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000.0] * len(rows),
            "openinterest": [0.0] * len(rows),
        },
        index=pd.to_datetime([date for date, _ in rows]),
    )

    class BuyOnce(bt.Strategy):
        def __init__(self):
            self._submitted = False

        def next(self):
            if not self._submitted:
                self.buy(size=100)
                self._submitted = True

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(_INITIAL_CASH)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(BuyOnce)
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="annual")
    cerebro.addanalyzer(bt.analyzers.MyAnnualReturn, _name="pandas_annual")
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    values = strategy.stats.broker.value.get(0, size=len(strategy.data))
    return {
        "annual": strategy.analyzers.annual.get_analysis(),
        "pandas_annual": strategy.analyzers.pandas_annual.get_analysis(),
        "values": [float(value) for value in values],
        "dates": [
            bt.num2date(value).date()
            for value in strategy.data.datetime.get(0, size=len(strategy.data))
        ],
    }


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "runonce"))
def test_myannualreturn_uses_initial_equity_then_prior_year_end(runonce):
    result = _run_half_year_then_cross_year(runonce=runonce)
    values = result["values"]

    assert result["dates"][0].year == 2020
    assert result["dates"][0].month == 7
    assert values[0] == pytest.approx(_INITIAL_CASH)
    assert values == pytest.approx([10000.0, 10000.0, 11000.0, 11000.0, 12000.0])

    # The first available equity is the first year's opening value. For later
    # calendar years, the preceding year's final observation is the opening.
    expected = {
        2020: values[2] / values[0] - 1.0,
        2021: values[4] / values[2] - 1.0,
    }
    assert result["annual"] == pytest.approx(expected)
    assert result["pandas_annual"] == pytest.approx(expected)
