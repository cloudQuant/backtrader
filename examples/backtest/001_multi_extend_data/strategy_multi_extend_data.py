#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convertible bond double-low multi-asset strategy.

This strategy implements a convertible bond trading approach based on
two factors: price level and conversion premium rate. Bonds are ranked
by a weighted combination of these factors, and the top-performing
bonds are selected for monthly rebalancing.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
import pandas as pd


class ExtendPandasFeed(bt.feeds.PandasData):
    """Extended Pandas data feed with convertible bond-specific fields."""

    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", -1),
        ("pure_bond_value", 5),
        ("convert_value", 6),
        ("pure_bond_premium_rate", 7),
        ("convert_premium_rate", 8),
    )

    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class BondConvertTwoFactor(bt.Strategy):
    """Convertible bond double-low strategy using two-factor scoring.

    The strategy rebalances monthly and uses equal weighting across all
    selected bonds.

    Strategy Logic:
        1. Rank bonds by close price (ascending)
        2. Rank bonds by conversion premium rate (ascending)
        3. Calculate weighted composite score
        4. Select top-ranked bonds for equal-weight allocation

    Parameters:
        first_factor_weight (float): Weight for price factor (default: 0.5)
        second_factor_weight (float): Weight for premium rate factor (default: 0.5)
        hold_percent (int): Number or percentage of bonds to hold (default: 20)
    """

    params = (
        ("first_factor_weight", 0.5),
        ("second_factor_weight", 0.5),
        ("hold_percent", 20),
    )

    def log(self, txt, dt=None):
        """Log strategy information with optional timestamp."""
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self, *args, **kwargs):
        """Initialize the BondConvertTwoFactor strategy."""
        super().__init__(*args, **kwargs)
        self.bar_num = 0
        self.position_dict = {}
        self.stock_dict = {}

    def prenext(self):
        """Handle prenext phase by calling next directly."""
        self.next()

    def stop(self):
        """Log the final bar count when strategy execution stops."""
        self.log(f"self.bar_num = {self.bar_num}")

    def next(self):
        """Execute the main strategy logic for each bar."""
        self.bar_num += 1

        pre_date = self.datas[0].datetime.date(-1).strftime("%Y-%m-%d")
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        current_month = current_date[5:7]

        try:
            next_date = self.datas[0].datetime.date(1).strftime("%Y-%m-%d")
            next_month = next_date[5:7]
        except IndexError:
            next_month = current_month
        except Exception:
            next_month = current_month

        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()

        self.stock_dict = {}
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        total_target_stock_num = len(self.stock_dict)
        total_holding_stock_num = len(self.position_dict)

        # Monthly rebalancing
        if current_month != next_month:
            position_name_list = list(self.position_dict.keys())
            for asset_name in position_name_list:
                data = self.getdatabyname(asset_name)
                size = self.getposition(data).size
                if size != 0:
                    self.close(data)
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)

                if data._name in self.position_dict and size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)

            result = self.get_target_symbol()

            if self.p.hold_percent > 1:
                num = self.p.hold_percent
            else:
                num = int(self.p.hold_percent * total_target_stock_num)
            buy_list = result[:num]

            for data_name, _cumsum_rate in buy_list:
                data = self.getdatabyname(data_name)
                now_value = total_value / num
                lots = now_value / data.close[0]
                order = self.buy(data, size=lots)
                self.position_dict[data_name] = order

        self.expire_order_close()

    def expire_order_close(self):
        """Close or cancel orders for bonds with insufficient data."""
        keys_list = list(self.position_dict.keys())
        for name in keys_list:
            order = self.position_dict[name]
            data = self.getdatabyname(name)
            close = data.close
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
            if data_date == current_date:
                try:
                    close[3]
                except IndexError:
                    self.log(f"array index out of range")
                    self.log(f"{data._name} will be cancelled")
                    size = self.getposition(data).size
                    if size != 0:
                        self.close(data)
                    else:
                        if order.alive():
                            self.cancel(order)
                    self.position_dict.pop(name)
                except Exception:
                    pass

    def get_target_symbol(self):
        """Calculate target symbols based on two-factor scoring model."""
        data_name_list = []
        close_list = []
        rate_list = []

        for asset in sorted(self.stock_dict):
            data = self.getdatabyname(asset)
            close = data.close[0]
            rate = data.convert_premium_rate[0]
            data_name_list.append(data._name)
            close_list.append(close)
            rate_list.append(rate)

        df = pd.DataFrame({"data_name": data_name_list, "close": close_list, "rate": rate_list})
        df["close_score"] = df["close"].rank(method="average")
        df["rate_score"] = df["rate"].rank(method="average")
        df["total_score"] = (
            df["close_score"] * self.p.first_factor_weight
            + df["rate_score"] * self.p.second_factor_weight
        )
        df = df.sort_values(by=["total_score", "data_name"], ascending=[False, True])

        result = []
        for _, row in df.iterrows():
            result.append([row["data_name"], row["total_score"]])

        return result

    def notify_order(self, order):
        """Handle order status changes and log execution details."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Rejected:
            self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Margin:
            self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Cancelled:
            self.log(f"order is cancelled : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Partial:
            self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    "buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )
            else:
                self.log(
                    "sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )

    def notify_trade(self, trade):
        """Handle trade lifecycle events and log trade information."""
        if trade.isclosed:
            self.log(
                "closed symbol is : {} , total_profit : {} , net_profit : {}".format(
                    trade.getdataname(), trade.pnl, trade.pnlcomm
                )
            )
        if trade.isopen:
            self.log(f"open symbol is : {trade.getdataname()} , price : {trade.price} ")
