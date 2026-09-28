#!/usr/bin/env python
"""PyFolio Analyzer Module - PyFolio integration.

This module provides the PyFolio analyzer for collecting data compatible
with the pyfolio library for performance analysis.

Classes:
    PyFolio: Analyzer that collects data for pyfolio.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
    >>> results = cerebro.run()
    >>> pyfolio_data = results[0].analyzers.pyfolio.get_analysis()
"""

import datetime
import math

import numpy as np
import pandas as pd

from ..analyzer import Analyzer
from ..dataseries import TimeFrame
from ..metabase import OwnerContext
from ..utils.py3 import iteritems
from .leverage import GrossLeverage
from .positions import PositionsValue
from .timereturn import TimeReturn
from .transactions import Transactions


def _daily_returns(values, name):
    """Copy a daily return series and align timezone-aware and naive date indices."""
    if isinstance(values, pd.DataFrame):
        if name in values:
            values = values[name]
        elif len(values.columns) == 1:
            values = values.iloc[:, 0]
        else:
            raise ValueError(f"Expected one return column or a {name!r} column")
    series = pd.Series(values, dtype=float).copy()
    series.index = pd.to_datetime(series.index, utc=True).tz_localize(None).normalize()
    if series.index.has_duplicates:
        raise ValueError("Formatted PyFolio metrics require one return per day")
    series = series.sort_index().dropna()
    if not np.isfinite(series.to_numpy()).all() or (series < -1).any():
        raise ValueError("Returns must be finite and cannot be less than -100%")
    return series.rename(name)


def _ratio(numerator, denominator):
    """Return NaN for a ratio whose denominator does not define a statistic."""
    return numerator / denominator if denominator > 0 else float("nan")


def _drawdown_details(returns):
    """Return signed maximum drawdown and (peak, trough, recovery) dates."""
    if returns.empty:
        return float("nan"), None
    wealth = (1.0 + returns).cumprod()
    peaks = wealth.cummax().clip(lower=1.0)
    drawdowns = wealth.div(peaks).sub(1.0)
    trough_pos = int(np.argmin(drawdowns.to_numpy()))
    drawdown = float(drawdowns.iloc[trough_pos])
    if drawdown == 0:
        return 0.0, None
    previous = wealth.iloc[:trough_pos]
    peak_pos = int(np.argmax(previous.to_numpy())) if not previous.empty else 0
    # None identifies starting capital before the first recorded return.
    peak = previous.index[peak_pos] if not previous.empty and previous.iloc[peak_pos] >= 1 else None
    recovered = wealth.iloc[trough_pos + 1 :]
    recovered = recovered[recovered >= peaks.iloc[trough_pos]]
    recovery = recovered.index[0] if not recovered.empty else None
    return drawdown, (peak, wealth.index[trough_pos], recovery)


# pyfolio analysis module
class PyFolio(Analyzer):
    """This analyzer uses 4 children analyzers to collect data and transforms it
    in to a data set compatible with ``pyfolio``

    Children Analyzer

      - ``TimeReturn``

        Used to calculate the returns of the global portfolio value

      - ``PositionsValue``

        Used to calculate the value of the positions per data. It sets the
        ``headers`` and ``cash`` parameters to ``True``

      - ``Transactions``

        Used to record each transaction on a data (size, price, value). Sets
        the ``headers`` parameter to ``True``

      - ``GrossLeverage``

        Keeps track of the gross leverage (how much the strategy is invested)

    Params:
      These are passed transparently to the children

      - timeframe (default: ``bt.TimeFrame.Days``)

        If ``None`` then the timeframe of the 1st data of the system will be
        used

      - compression (default: `1``)

        If ``None`` then the compression of the 1st data of the system will be
        used

    Both ``timeframe`` and ``compression`` are set following the default
    behavior of ``pyfolio`` which is working with *daily* data and upsample it
    to obtaine values like yearly returns.

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """

    # Parameters
    params = (("timeframe", TimeFrame.Days), ("compression", 1))

    # Initialize
    def __init__(self, *args, **kwargs):
        """Initialize the PyFolio analyzer.

        Creates child analyzers (TimeReturn, PositionsValue, Transactions,
        GrossLeverage) to collect data for pyfolio integration.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        dtfcomp = {"timeframe": self.p.timeframe, "compression": self.p.compression}

        # Use OwnerContext so child analyzers can find this as their parent
        with OwnerContext.set_owner(self):
            self._returns = TimeReturn(**dtfcomp)
            self._positions = PositionsValue(headers=True, cash=True)
            self._transactions = Transactions(headers=True)
            self._gross_lev = GrossLeverage()

    # When stopping, get several analysis results
    def stop(self):
        """Collect results from child analyzers when backtest ends.

        Gathers returns, positions, transactions, and gross leverage data
        from the child analyzers for pyfolio processing.
        """
        super().stop()
        self.rets["returns"] = self._returns.get_analysis()
        self.rets["positions"] = self._positions.get_analysis()
        self.rets["transactions"] = self._transactions.get_analysis()
        self.rets["gross_lev"] = self._gross_lev.get_analysis()

    # Adjust the results of the above four analyzers to get the input information required by pyfolio
    def get_pf_items(self):
        """Returns a tuple of 4 elements which can be used for further processing with
          ``pyfolio``

          returns, positions, transactions, gross_leverage

        Because the objects are meant to be used as direct input to ``pyfolio``
        this method makes a local import of ``pandas`` to convert the internal
        *backtrader* results to *pandas DataFrames* which is the expected input
        by, for example, ``pyfolio.create_full_tear_sheet``

        The method will break if ``pandas`` is not installed
        """
        # keep import local to avoid disturbing installations with no pandas
        # Returns
        # Process returns
        cols = ["index", "return"]
        returns = pd.DataFrame.from_records(
            iteritems(self.rets["returns"]), index=cols[0], columns=cols
        )
        returns.index = pd.to_datetime(returns.index)
        returns.index = returns.index.tz_localize("UTC")
        rets = returns["return"]
        #
        # Positions
        # Process position
        pss = self.rets["positions"]
        # ps = [[k] + v[-2:] for k, v in iteritems(pss)]
        ps = [[k] + v for k, v in iteritems(pss)]
        if ps:
            cols = ps.pop(0)  # headers are in the first entry
            positions = pd.DataFrame.from_records(ps, columns=cols)
        else:
            positions = pd.DataFrame(columns=["Datetime"])
        positions.index = pd.to_datetime(positions["Datetime"])
        del positions["Datetime"]
        positions.index = positions.index.tz_localize("UTC")

        #
        # Transactions
        # Process transactions
        txss = self.rets["transactions"]
        txs = []
        # The transactions have a common key (date) and can potentially happend
        # for several assets. The dictionary has a single key and a list of
        # lists. Each sublist contains the fields of a transaction
        # Hence the double loop to undo the list indirection
        for k, v in iteritems(txss):
            for v2 in v:
                txs.append([k] + v2)

        if txs:
            cols = txs.pop(0)  # headers are in the first entry
            transactions = pd.DataFrame.from_records(txs, index=cols[0], columns=cols)
        else:
            transactions = pd.DataFrame(
                columns=["date", "amount", "price", "sid", "symbol", "value"]
            ).set_index("date")
        transactions.index = pd.to_datetime(transactions.index)
        transactions.index = transactions.index.tz_localize("UTC")

        # Gross Leverage
        # Process leverage
        cols = ["index", "gross_lev"]
        gross_lev = pd.DataFrame.from_records(
            iteritems(self.rets["gross_lev"]), index=cols[0], columns=cols
        )

        gross_lev.index = pd.to_datetime(gross_lev.index)
        gross_lev.index = gross_lev.index.tz_localize("UTC")
        glev = gross_lev["gross_lev"]

        # Return all together
        # Return all results
        return rets, positions, transactions, glev

    def _get_order_type(self, row):
        """Return the execution side, including buys that close a short position."""
        if row["TRADE_TYPE"] not in {"开仓", "平仓"} or not row["amount"]:
            return np.nan
        return "买入" if row["amount"] > 0 else "卖出"

    def _compute_profit_loss(self, trade_info, open_type, close_type):
        """Fill gross realized PnL for labeled opens/closes, grouped by symbol.

        Quantities come from ENTRUST_NUM when present; legacy tables containing
        only TRADE_AMT represent one full lot per row. Partial closes use the
        position's weighted entry price, as the broker does.
        """
        positions = {}
        direction = -1 if open_type == "开空" else 1
        for index, row in trade_info.iterrows():
            if row["ORDER_TYPE"] not in {open_type, close_type}:
                continue
            symbol = row.get("O_CODE", row.get("symbol", ""))
            quantity = abs(float(row.get("ENTRUST_NUM", 1.0)))
            if not quantity:
                continue
            price = abs(float(row["TRADE_AMT"])) / quantity
            size, average = positions.get(symbol, (0.0, 0.0))
            if row["ORDER_TYPE"] == open_type:
                average = (size * average + quantity * price) / (size + quantity)
                positions[symbol] = (size + quantity, average)
                trade_info.at[index, "PROFIT_LOSS"] = 0.0
            else:
                if quantity > size:
                    raise ValueError("Closing quantity exceeds the preceding opening quantity")
                trade_info.at[index, "PROFIT_LOSS"] = direction * quantity * (price - average)
                positions[symbol] = (size - quantity, average)
        return trade_info

    def _get_trade_info(self, trade_info, symbol_name, current_user_name="", pair_num=None):
        """Format signed transactions into master's 19-column trade table.

        Position transitions determine opens/closes, replacing the old row-modulo
        pairing (which labeled every row as an opening with pair_num=1). A reversal
        is split into its closing and opening parts. pair_num remains accepted for
        source compatibility. PnL is gross, uses unit price and signed quantity,
        and does not infer futures multipliers absent from this transaction schema.
        COMMISSION is NaN unless the input provides an actual commission column.
        """
        if pair_num is not None and (not isinstance(pair_num, int) or pair_num < 1):
            raise ValueError("pair_num must be a positive integer or None")
        columns = [
            "TRADE_DATE",
            "ENTRUST_DATE",
            "O_CODE",
            "KIND",
            "TRADE_TYPE",
            "ORDER_TYPE",
            "TRADE_NUM",
            "TRADE_PRICE",
            "TRADE_AMT",
            "ENTRUST_NUM",
            "ENTRUST_PRICE",
            "STATUS",
            "PROFIT_LOSS",
            "COMMISSION",
            "CREATE_DATE",
            "CREATE_USER",
            "UPDATE_DATE",
            "UPDATE_USER",
            "D_FLAG",
        ]
        records, positions = [], {}
        next_trade = 0
        today = datetime.date.today()
        for timestamp, row in trade_info.sort_index(kind="stable").iterrows():
            amount, price = float(row["amount"]), float(row["price"])
            if not math.isfinite(amount) or not math.isfinite(price):
                raise ValueError("Transaction quantity and price must be finite")
            if not amount:
                continue
            symbol = row["symbol"]
            key = row.get("sid", symbol)
            size, average, trade_num = positions.get(key, (0.0, 0.0, 0))
            date = pd.Timestamp(timestamp).date()
            commission = float(row.get("commission", np.nan))
            parts = []
            if size * amount < 0:
                closed = min(abs(size), abs(amount))
                signed_closed = math.copysign(closed, amount)
                profit = closed * (price - average) * math.copysign(1.0, size)
                parts.append((signed_closed, "平仓", trade_num, profit))
                size += signed_closed
                amount -= signed_closed
            if amount:
                if not size:
                    next_trade += 1
                    trade_num = next_trade
                average = (abs(size) * average + abs(amount) * price) / (abs(size) + abs(amount))
                size += amount
                parts.append((amount, "开仓", trade_num, 0.0))
            positions[key] = (size, average, trade_num)
            for quantity, phase, number, profit in parts:
                records.append(
                    [
                        pd.Timestamp(date),
                        pd.Timestamp(date),
                        symbol,
                        symbol_name,
                        phase,
                        self._get_order_type({"TRADE_TYPE": phase, "amount": quantity}),
                        number,
                        price,
                        quantity * price,
                        quantity,
                        price,
                        "完成",
                        profit,
                        commission * abs(quantity / float(row["amount"])),
                        today,
                        current_user_name,
                        today,
                        current_user_name,
                        0,
                    ]
                )
        return pd.DataFrame.from_records(records, columns=columns)

    def _get_performance_indicators(self, results, returns, benchmark_returns, current_user_name):
        """Return master's performance fields with daily (252-session) statistics.

        This compatibility report uses pandas/numpy rather than optional empyrical
        APIs missing from released empyrical versions. Returns are decimals; PROFIT,
        PROFIT_Y, MDD and the other legacy return fields remain percentage values.
        Undefined ratios are NaN. DATE_REGION is (peak, trough, recovery), with None
        for no drawdown or unavailable endpoints. TradeAnalyzer, under any name,
        supplies net win/loss counts; without it nonempty trade statistics are NaN.
        """
        from .tradeanalyzer import TradeAnalyzer

        strategy_returns = _daily_returns(returns, "return")
        benchmark = _daily_returns(benchmark_returns, "returns")
        paired = pd.concat([strategy_returns, benchmark], axis=1, join="inner").dropna()
        active = paired["return"] - paired["returns"]
        nan = float("nan")
        annualizer = math.sqrt(252)

        def cumulative(series):
            return float((1 + series).prod() - 1) if not series.empty else nan

        def sharpe(series):
            return _ratio(float(series.mean()) * annualizer, float(series.std(ddof=1)))

        profit = cumulative(strategy_returns)
        annual_return = (
            (1 + profit) ** (252.0 / len(strategy_returns)) - 1
            if not strategy_returns.empty
            else nan
        )
        baseline_profit = cumulative(paired["returns"])
        maximum_drawdown, region = _drawdown_details(strategy_returns)
        active_drawdown, _ = _drawdown_details(active)
        variance = paired["returns"].var(ddof=1)
        beta = paired["return"].cov(paired["returns"]) / variance if variance > 0 else nan
        alpha = (1 + (paired["return"] - beta * paired["returns"]).mean()) ** 252 - 1
        downside = (
            float(np.sqrt(np.mean(np.minimum(strategy_returns.to_numpy(), 0.0) ** 2)))
            if not strategy_returns.empty
            else nan
        )

        analysis = None
        if results:
            for analyzer in results[0].analyzers:
                if isinstance(analyzer, TradeAnalyzer):
                    analysis = analyzer.get_analysis()
                    break
        win_num = loss_num = win_average = loss_average = nan
        if analysis is not None:
            won, lost = analysis.get("won", {}), analysis.get("lost", {})
            win_num, loss_num = won.get("total", 0), lost.get("total", 0)
            win_average = won.get("pnl", {}).get("average", nan)
            loss_average = lost.get("pnl", {}).get("average", nan)
        elif not self.get_pf_items()[2].shape[0]:
            win_num = loss_num = 0
        total = win_num + loss_num
        win_ratio = win_num / total if total > 0 else (0.0 if total == 0 else nan)
        today = datetime.date.today()
        return {
            "PROFIT": round(profit * 100, 2),
            "PROFIT_Y": round(annual_return * 100, 2),
            "SUPERIOR_PROFIT": round((profit - baseline_profit) * 100, 2),
            "BASE_PROFIT": round(baseline_profit * 100, 2),
            "ALPHA": round(float(alpha), 4),
            "Beta": round(float(beta), 4),
            "SHARPE_RATIO": round(sharpe(strategy_returns), 4),
            "WIN_RATIO": round(win_ratio, 4),
            "RRR": round(_ratio(win_average * 100, abs(loss_average)), 4),
            "MDD": round(-maximum_drawdown * 100, 2),
            "SORTINO_RATIO": round(
                _ratio(float(strategy_returns.mean()) * annualizer, downside), 4
            ),
            "DAILY_SUPERIOR_PROFIT": round(float(active.mean()) * 100, 2),
            "MDD_SUPERIOR_PROFIT": round(active_drawdown * 100, 2),
            "SP_SHARPE_RATIO": round(sharpe(active), 4),
            "DAILY_WIN_RATIO": round(win_ratio, 4),
            "WIN_NUM": win_num,
            "LOSS_NUM": loss_num,
            "INFO_RATIO": round(sharpe(active), 4),
            "VIX": round(float(strategy_returns.std(ddof=1)) * annualizer, 4),
            "BASE_VIX": round(float(paired["returns"].std(ddof=1)) * annualizer, 4),
            "DATE_REGION": region,
            "CREATE_DATE": today,
            "CREATE_USER": current_user_name,
            "UPDATE_DATE": today,
            "UPDATE_USER": current_user_name,
            "D_FLAG": 0,
        }

    def get_format_results(self, results, benchmark_returns, symbol_name, current_user_name):
        """Return (performance dict, transaction DataFrame) using master's signature.

        See _get_performance_indicators and _get_trade_info for percentage units,
        unavailable metrics/fees and the position-based replacement of row pairing.
        Input return series and the underlying get_pf_items result are not mutated.
        """
        returns, _, transactions, _ = self.get_pf_items()
        performance = self._get_performance_indicators(
            results, returns, benchmark_returns, current_user_name
        )
        trades = self._get_trade_info(transactions, symbol_name, current_user_name, pair_num=1)
        return performance, trades
