#!/usr/bin/env python
"""Plotting module for Backtrader.

This module provides plotting functionality for backtrader strategies, including
matplotlib-based plotting, plotly integration, and pyecharts support for
creating interactive charts and visualizations of trading results.

Classes:
    PInfo: Internal plotting information container
    Plot_OldSync: Main plotting class for matplotlib-based chart generation

Functions:
    split_data: Split dataframe into chart components
    get_up_scatter: Get upward swing points for chart
    get_dn_scatter: Get downward swing points for chart
    get_valid_point: Get valid swing points
    draw_chart: Draw comprehensive trading chart
    get_rate_sharpe_drawdown: Calculate performance metrics
    run_cerebro_and_plot: Run cerebro backtest and plot results
"""

import bisect
import collections
import copy
import datetime
import math
import operator
import os
import sys
import time
import traceback
from collections import OrderedDict

import matplotlib
import matplotlib.font_manager as mfontmgr
import matplotlib.ticker as mticker
import numpy as np  # guaranteed by matplotlib
import pandas as pd
import plotly.figure_factory as ff
import plotly.graph_objs as go
import plotly.offline as py
from dash import html
from pyecharts import options as opts
from pyecharts.charts import Bar, EffectScatter, Grid, Kline, Line
from pyecharts.commons.utils import JsCode
from pyecharts.globals import SymbolType

from .. import AutoInfoClass, analyzers, date2num
from ..dataseries import TimeFrame
from ..parameters import ParameterDescriptor, ParameterizedBase
from ..utils.py3 import integer_types, range
from . import locator as loc
from .finance import plot_candlestick, plot_lineonclose, plot_ohlc, plot_volume
from .formatters import MyDateFormatter, MyVolFormatter
from .multicursor import MultiCursor
from .scheme import PlotScheme
from .utils import tag_box_style

# from jupyter_plotly_dash import JupyterDash


def cal_macd_system(data, short_=26, long_=12, m=9):
    """
    data is a standard dataframe containing high, open, low, close, volume
    short_, long_, m are the three parameters of macd
    Return value is a dataframe containing original data and diff, dea, macd columns
    """
    data["diff"] = (
        data["close"].ewm(adjust=False, alpha=2 / (short_ + 1), ignore_na=True).mean()
        - data["close"].ewm(adjust=False, alpha=2 / (long_ + 1), ignore_na=True).mean()
    )
    data["dea"] = data["diff"].ewm(adjust=False, alpha=2 / (m + 1), ignore_na=True).mean()
    data["macd"] = 2 * (data["diff"] - data["dea"])
    return data


def split_data(df) -> dict:
    """Split dataframe into components for pyecharts plotting.

    Args:
        df: DataFrame containing OHLCV data and MACD indicators

    Returns:
        Dictionary with keys: datas, times, vols, macds, difs, deas
    """
    datas = list(zip(df["open"], df["close"], df["low"], df["high"], df["volume"], df["up_bar"]))
    times = list(df.index)
    vols = list(df["volume"])
    macds = list(df["macd"])
    difs = list(df["diff"])
    deas = list(df["dea"])

    return {
        "datas": datas,
        "times": times,
        "vols": vols,
        "macds": macds,
        "difs": difs,
        "deas": deas,
    }


def get_up_scatter(df):
    """Get upward swing points from dataframe.

    Identifies low points in the price swing for marking on charts.
    Returns a list of tuples containing (time, lowest price).

    Args:
        df: DataFrame with up_bar and dn_bar columns

    Returns:
        List of [time, low] tuples marking upward swing points
    """
    # Mark up points, format is a list containing tuples of (time, lowest price)
    mark_line_data = []
    first_swing = None
    pre_index = None
    pre_low = None
    for index, row in df.iterrows():
        up_bar = row["up_bar"]
        dn_bar = row["dn_bar"]
        low = row["low"]
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            # mark_line_data.append([index, high])
            first_swing = "dn"
        if first_swing == "dn" and up_bar == 1:
            mark_line_data.append([pre_index, pre_low])
            first_swing = "up"
        pre_index = index
        pre_low = low
        # print(mark_line_data[:10])
    return mark_line_data


def get_dn_scatter(df):
    """Get downward swing points from dataframe.

    Identifies high points in the price swing for marking on charts.
    Returns a list of tuples containing (time, highest price).

    Args:
        df: DataFrame with up_bar and dn_bar columns

    Returns:
        List of [time, high] tuples marking downward swing points
    """
    # Mark down points, format is a list containing tuples of (time, highest price)
    mark_line_data = []
    first_swing = None
    pre_index = None
    pre_high = None
    for index, row in df.iterrows():
        up_bar = row["up_bar"]
        dn_bar = row["dn_bar"]
        high = row["high"]
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            mark_line_data.append([pre_index, pre_high])
            first_swing = "dn"
        if first_swing == "dn" and up_bar == 1:
            # mark_line_data.append([index, low])
            first_swing = "up"
        pre_index = index
        pre_high = high
    # print(mark_line_data[:10])
    return mark_line_data


def get_valid_point(df):
    """Get valid swing points for support/resistance lines.

    Identifies valid swing high and low points that can be used to draw
    support and resistance lines on price charts.

    Args:
        df: DataFrame with up_bar, dn_bar, high, and low columns

    Returns:
        Tuple of two lists:
            - valid_dn_point_list: Valid downward (high) points
            - valid_up_point_list: Valid upward (low) points
    """
    valid_dn_point_list = []
    valid_up_point_list = []
    dn_point_point_list = []
    up_point_point_list = []
    first_swing = None
    pre_index = None
    pre_low = None
    pre_high = None
    for index, row in df.iterrows():
        up_bar = row["up_bar"]
        dn_bar = row["dn_bar"]
        high = row["high"]
        low = row["low"]
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            dn_point_point_list.append([pre_index, pre_high])
            first_swing = "dn"
            if len(dn_point_point_list) > 1 and len(up_point_point_list) > 1:
                pre_pre_high = dn_point_point_list[-2][1]
                # If current highest point is greater than previous highest point, then previous up swing point is at least a test point
                if pre_high > pre_pre_high:
                    # Try to get previous dn_point's highest price and pre-previous dn_point's highest price
                    pre_1_index, pre_1_low = up_point_point_list[-1]
                    pre_2_index, pre_2_low = up_point_point_list[-2]
                    # If previous swing point is up
                    if pre_1_low < pre_2_low:
                        valid_up_point_list.append([pre_1_index, pre_1_low])

        if first_swing == "dn" and up_bar == 1:
            up_point_point_list.append([pre_index, pre_low])
            first_swing = "up"
            # Get previous up_point
            if len(dn_point_point_list) > 1 and len(up_point_point_list) > 1:
                pre_pre_low = up_point_point_list[-2][1]
                # If current lowest point is less than previous lowest point, then previous highest price is a test point
                if pre_low < pre_pre_low:
                    # Try to get previous dn_point's highest price and pre-previous dn_point's highest price
                    pre_1_index, pre_1_high = dn_point_point_list[-1]
                    pre_2_index, pre_2_high = dn_point_point_list[-2]
                    # If previous swing point is up
                    if pre_1_high > pre_2_high:
                        valid_dn_point_list.append([pre_1_index, pre_1_high])

        pre_index = index
        pre_low = low
        pre_high = high
    # print(mark_line_data[:10])
    return valid_dn_point_list, valid_up_point_list


def draw_chart(data, df, bk_list, bp_list, sk_list, sp_list):
    """Draw comprehensive trading chart using pyecharts.

    Creates a detailed K-line chart with volume, MACD indicators,
    trading signals, and support/resistance lines.

    Args:
        data: Dictionary containing times, volumes, MACD data
        df: DataFrame with OHLCV data and swing markers
        bk_list: List of buy signals (open long)
        bp_list: List of sell signals (close long)
        sk_list: List of short signals (open short)
        sp_list: List of cover signals (close short)

    Returns:
        None (renders chart to HTML file)
    """
    kline = (
        Kline()
        .add_xaxis(xaxis_data=data["times"])
        .add_yaxis(
            series_name="",
            y_axis=data["datas"],
            itemstyle_opts=opts.ItemStyleOpts(
                color="#ef232a",
                color0="#14b143",
                border_color="#ef232a",
                border_color0="#14b143",
            ),
            markpoint_opts=opts.MarkPointOpts(
                data=[
                    opts.MarkPointItem(type_="max", name="Maximum"),
                    opts.MarkPointItem(type_="min", name="Minimum"),
                ]
            ),
            # markline_opts = opts.MarkLineOpts(
            #     label_opts=opts.LabelOpts(
            #         position="middle", color="blue", font_size=15
            #     ),
            #     data=split_data_part(),
            #     symbol=["circle", "none"],
            # ),
        )
        .set_series_opts(
            # To avoid affecting mark points, turn off labels here
            label_opts=opts.LabelOpts(is_show=False),
            markpoint_opts=opts.MarkPointOpts(
                data=[
                    opts.MarkPointItem(type_="min", name="y-axis minimum", value_index=1),
                    opts.MarkPointItem(type_="max", name="y-axis maximum", value_index=1),
                ]
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="K-line cycle chart", pos_left="0"),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                is_scale=True,
                boundary_gap=False,
                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                split_number=20,
                min_="dataMin",
                max_="dataMax",
            ),
            yaxis_opts=opts.AxisOpts(
                is_scale=True, splitline_opts=opts.SplitLineOpts(is_show=True)
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="line"),
            datazoom_opts=[
                opts.DataZoomOpts(is_show=False, type_="inside", xaxis_index=[0, 0], range_end=100),
                opts.DataZoomOpts(is_show=True, xaxis_index=[0, 1], pos_top="97%", range_end=100),
                opts.DataZoomOpts(is_show=False, xaxis_index=[0, 2], range_end=100),
            ],
            # Connect axes of three charts together
            # axispointer_opts=opts.AxisPointerOpts(
            #     is_show=True,
            #     link=[{"xAxisIndex": "all"}],
            #     label=opts.LabelOpts(background_color="#777"),
            # ),
        )
    )
    esc = get_up_scatter(df)
    esc_dn = get_dn_scatter(df)

    all_up_dn = esc + esc_dn
    all_up_dn_sorted = sorted(all_up_dn, key=lambda x: x[0])
    line_index = [i[0] for i in all_up_dn_sorted]
    line_value = [i[1] for i in all_up_dn_sorted]

    kline_line = (
        Line()
        .add_xaxis(xaxis_data=line_index)
        .add_yaxis(
            series_name="Wave",
            y_axis=line_value,
            is_smooth=False,
            # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
            linestyle_opts=opts.LineStyleOpts(color="black", width=4, type_="dashed"),
            label_opts=opts.LabelOpts(is_show=False),
            symbol="arrow",
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=1,
                axislabel_opts=opts.LabelOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                grid_index=1,
                split_number=3,
                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                axislabel_opts=opts.LabelOpts(is_show=True),
            ),
        )
    )
    # Overlap Kline + Line
    overlap_kline_line = kline.overlap(kline_line)

    # Try to draw support line
    valid_dn_point_list, valid_up_point_list = get_valid_point(df)
    print(len(valid_dn_point_list), len(valid_up_point_list))
    es = (
        EffectScatter()
        .add_xaxis([i[0] for i in valid_up_point_list])
        .add_yaxis("", [i[1] for i in valid_up_point_list], symbol=SymbolType.TRIANGLE)
    )
    # overlap_kline_line = kline
    overlap_kline_line = overlap_kline_line.overlap(es)

    es_dn = (
        EffectScatter()
        .add_xaxis([i[0] for i in valid_dn_point_list])
        .add_yaxis("", [i[1] for i in valid_dn_point_list], symbol=SymbolType.DIAMOND)
    )
    # overlap_kline_line = kline
    overlap_kline_line = overlap_kline_line.overlap(es_dn)

    # Try to add some support lines to the support
    for d1, d2 in zip(valid_dn_point_list[:-1], valid_dn_point_list[1:]):
        # print(d1,d2)
        dn_line = (
            Line()
            .add_xaxis(xaxis_data=[d1[0], d2[0]])
            .add_yaxis(
                series_name="Support",
                y_axis=[d1[1], d2[1]],
                is_smooth=False,
                # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                linestyle_opts=opts.LineStyleOpts(color="green", width=2, type_="dotted"),
                label_opts=opts.LabelOpts(is_show=False),
                symbol="arrow",
            )
            .set_global_opts(
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    grid_index=1,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                yaxis_opts=opts.AxisOpts(
                    grid_index=1,
                    split_number=3,
                    axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                    axistick_opts=opts.AxisTickOpts(is_show=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                    axislabel_opts=opts.LabelOpts(is_show=True),
                ),
            )
        )
        overlap_kline_line = kline.overlap(dn_line)

    for d1, d2 in zip(valid_up_point_list[:-1], valid_up_point_list[1:]):
        # print(d1,d2)
        dn_line = (
            Line()
            .add_xaxis(xaxis_data=[d1[0], d2[0]])
            .add_yaxis(
                series_name="Support",
                y_axis=[d1[1], d2[1]],
                is_smooth=False,
                # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                linestyle_opts=opts.LineStyleOpts(color="red", width=2, type_="dotted"),
                label_opts=opts.LabelOpts(is_show=False),
                symbol="arrow",
            )
            .set_global_opts(
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    grid_index=1,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                yaxis_opts=opts.AxisOpts(
                    grid_index=1,
                    split_number=3,
                    axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                    axistick_opts=opts.AxisTickOpts(is_show=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                    axislabel_opts=opts.LabelOpts(is_show=True),
                ),
            )
        )
        overlap_kline_line = kline.overlap(dn_line)

    # Add buy/sell points
    # Open long
    bk_df = df[df.index.isin([str(i[0]) for i in bk_list])]
    bk_c = (
        EffectScatter()
        .add_xaxis(bk_df.index)
        .add_yaxis(
            "", bk_df.low, color="red", symbol="image://c:/result/img/open_long.png", symbol_size=10
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="buy"))
    )
    overlap_kline_line = kline.overlap(bk_c)
    # Close long
    bp_df = df[df.index.isin([str(i[0]) for i in bp_list])]
    bp_c = (
        EffectScatter()
        .add_xaxis(bp_df.index)
        .add_yaxis(
            "",
            bp_df.high,
            color="green",
            symbol="image://c:/result/img/close_long.png",
            symbol_size=10,
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="=sell"))
    )
    overlap_kline_line = kline.overlap(bp_c)
    # Long position line segment
    for bk, bp in zip([str(i[0]) for i in bk_list], [str(i[0]) for i in bp_list]):
        # print(bk,bk)
        try:
            bk_df = df[df.index >= bk]
            bk_price = list(bk_df["open"])[1]
            bp_df = df[df.index >= bp]
            bp_price = list(bp_df["open"])[1]
            # print("Long signal", [bk, new_bk, bp, new_bp], [bk_price, bp_price])  # Removed for performance
            # Test
            long_line = (
                Line()
                .add_xaxis(xaxis_data=[bk, bp])
                .add_yaxis(
                    series_name="long_signal",
                    y_axis=[bk_price, bp_price],
                    is_smooth=False,
                    # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                    linestyle_opts=opts.LineStyleOpts(color="red", width=5, type_="dotted"),
                    label_opts=opts.LabelOpts(is_show=False),
                    symbol="arrow",
                )
                .set_global_opts(
                    xaxis_opts=opts.AxisOpts(
                        type_="category",
                        grid_index=1,
                        axislabel_opts=opts.LabelOpts(is_show=False),
                    ),
                    yaxis_opts=opts.AxisOpts(
                        grid_index=1,
                        split_number=3,
                        axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                        axistick_opts=opts.AxisTickOpts(is_show=False),
                        splitline_opts=opts.SplitLineOpts(is_show=False),
                        axislabel_opts=opts.LabelOpts(is_show=True),
                    ),
                )
            )
            overlap_kline_line = kline.overlap(long_line)
        except Exception:
            # print("Some signals are not aligned")  # Removed for performance
            pass

    sk_df = df[df.index.isin([str(i[0]) for i in sk_list])]
    sk_c = (
        EffectScatter()
        .add_xaxis(sk_df.index)
        .add_yaxis(
            "",
            sk_df.high,
            color="green",
            symbol="image://c:/result/img/open_short.png",
            symbol_size=10,
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="sellshort"))
    )
    overlap_kline_line = kline.overlap(sk_c)

    sp_df = df[df.index.isin([str(i[0]) for i in sp_list])]
    sp_c = (
        EffectScatter()
        .add_xaxis(sp_df.index)
        .add_yaxis(
            "",
            sp_df.low,
            color="red",
            symbol="image://c:/result/img/close_short.png",
            symbol_size=10,
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="buytocover"))
    )
    overlap_kline_line = kline.overlap(sp_c)

    # Short position line segment
    for sk, sp in zip([str(i[0]) for i in sk_list], [str(i[0]) for i in sp_list]):
        try:
            sk_df = df[df.index >= sk]
            sk = list(sk_df.index)[1]
            sk_price = list(sk_df["open"])[1]
            sp_df = df[df.index >= sp]
            sp = list(sp_df.index)[1]
            sp_price = list(sp_df["open"])[1]
            # print("Short signal", [sk, sp], [sk_price, sp_price])  # Removed for performance
            # Test
            short_line = (
                Line()
                .add_xaxis(xaxis_data=[sk, sp])
                .add_yaxis(
                    series_name="short_signal",
                    y_axis=[sk_price, sp_price],
                    is_smooth=False,
                    # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                    linestyle_opts=opts.LineStyleOpts(color="green", width=5, type_="dotted"),
                    label_opts=opts.LabelOpts(is_show=False),
                    symbol="arrow",
                )
                .set_global_opts(
                    xaxis_opts=opts.AxisOpts(
                        type_="category",
                        grid_index=1,
                        axislabel_opts=opts.LabelOpts(is_show=False),
                    ),
                    yaxis_opts=opts.AxisOpts(
                        grid_index=1,
                        split_number=3,
                        axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                        axistick_opts=opts.AxisTickOpts(is_show=False),
                        splitline_opts=opts.SplitLineOpts(is_show=False),
                        axislabel_opts=opts.LabelOpts(is_show=True),
                    ),
                )
            )
            overlap_kline_line = kline.overlap(short_line)
        except Exception:
            # print("Short signal error")  # Removed for performance
            pass

    # Bar-1
    bar_1 = (
        Bar()
        .add_xaxis(xaxis_data=data["times"])
        .add_yaxis(
            series_name="Volumn",
            y_axis=data["vols"],
            xaxis_index=1,
            yaxis_index=1,
            label_opts=opts.LabelOpts(is_show=False),
            # According to echarts demo original version, it's written like this
            # itemstyle_opts=opts.ItemStyleOpts(
            #     color=JsCode("""
            #     function(params) {
            #         var colorList;
            #         if (data.datas[params.dataIndex][1]>data.datas[params.dataIndex][0]) {
            #           colorList = '#ef232a';
            #         } else {
            #           colorList = '#14b143';
            #         }
            #         return colorList;
            #     }
            #     """)
            # )
            # After improvement, after add_js_funcs in grid, it becomes as follows
            itemstyle_opts=opts.ItemStyleOpts(color=JsCode("""
                function(params) {
                    var colorList;
                    if (barData[params.dataIndex][1] > barData[params.dataIndex][0]) {
                        colorList = '#ef232a';
                    } else {
                        colorList = '#14b143';
                    }
                    return colorList;
                }
                """)),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=1,
                axislabel_opts=opts.LabelOpts(is_show=False),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    # Bar-2 (Overlap Bar + Line)
    bar_2 = (
        Bar()
        .add_xaxis(xaxis_data=data["times"])
        .add_yaxis(
            series_name="MACD",
            y_axis=data["macds"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(color=JsCode("""
                        function(params) {
                            var colorList;
                            if (params.data >= 0) {
                              colorList = '#ef232a';
                            } else {
                              colorList = '#14b143';
                            }
                            return colorList;
                        }
                        """)),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=2,
                axislabel_opts=opts.LabelOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                grid_index=2,
                split_number=4,
                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                axislabel_opts=opts.LabelOpts(is_show=True),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    line_2 = (
        Line()
        .add_xaxis(xaxis_data=data["times"])
        .add_yaxis(
            series_name="DIF",
            y_axis=data["difs"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
        )
        .add_yaxis(
            series_name="DIF",
            y_axis=data["deas"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
        )
        .set_global_opts(legend_opts=opts.LegendOpts(is_show=False))
    )
    # Bottom bar chart and line chart
    overlap_bar_line = bar_2.overlap(line_2)

    # Final Grid
    grid_chart = Grid(init_opts=opts.InitOpts(width="1400px", height="800px"))

    # This is to write data.datas into html, haven't figured out how to pass values across series
    # Code in demo also uses global variables
    grid_chart.add_js_funcs("var barData = {}".format(data["datas"]))

    # K-line chart and MA5 line chart
    grid_chart.add(
        overlap_kline_line,
        grid_opts=opts.GridOpts(pos_left="3%", pos_right="1%", height="60%"),
    )
    # Volume bar chart
    grid_chart.add(
        bar_1,
        grid_opts=opts.GridOpts(pos_left="3%", pos_right="1%", pos_top="71%", height="10%"),
    )
    # MACD DIFS DEAS
    grid_chart.add(
        overlap_bar_line,
        grid_opts=opts.GridOpts(pos_left="3%", pos_right="1%", pos_top="82%", height="14%"),
    )
    grid_chart.render("c:/result/test_price_action_kline_chart.html")


class PInfo:
    """Container for plotting information and state.

    This class maintains all the state information needed during
    the plotting process, including figure references, axes,
    color schemes, and layout information.

    Attributes:
        sch: PlotScheme instance with plotting configuration
        nrows: Total number of rows in the plot
        row: Current row index
        clock: Strategy or data object providing time reference
        x: X-axis data points
        xlen: Length of x-axis data
        sharex: Shared x-axis reference
        figs: List of figure objects
        cursors: List of MultiCursor objects
        daxis: Ordered dictionary mapping objects to axes
        vaxis: List of vertical (twinx) axes
        zorder: Dictionary mapping axes to z-order values
        coloridx: Dictionary tracking color index per axis
        handles: Dictionary of legend handles per axis
        labels: Dictionary of legend labels per axis
        legpos: Dictionary tracking legend position per axis
        prop: FontProperties for subplot text
    """

    def __init__(self, sch):
        """Initialize PInfo with plotting scheme.

        Args:
            sch: PlotScheme instance with plotting configuration
        """
        self.sch = sch
        self.nrows = 0
        self.row = 0
        self.clock = None
        self.x = None
        self.xlen = 0
        self.sharex = None
        self.figs = list()
        self.cursors = list()
        self.daxis = collections.OrderedDict()
        self.vaxis = list()
        self.zorder = dict()
        self.coloridx = collections.defaultdict(lambda: -1)
        self.handles = collections.defaultdict(list)
        self.labels = collections.defaultdict(list)
        self.legpos = collections.defaultdict(int)

        self.prop = mfontmgr.FontProperties(size=self.sch.subtxtsize)

    def newfig(self, figid, numfig, mpyplot):
        """Create a new matplotlib figure.

        Args:
            figid: Base figure identifier
            numfig: Figure number suffix
            mpyplot: Matplotlib pyplot module

        Returns:
            Figure object
        """
        fig = mpyplot.figure(figid + numfig)
        self.figs.append(fig)
        self.daxis = collections.OrderedDict()
        self.vaxis = list()
        self.row = 0
        self.sharex = None
        return fig

    def nextcolor(self, ax):
        """Increment and get next color index for axis.

        Args:
            ax: Axis object

        Returns:
            Next color index
        """
        self.coloridx[ax] += 1
        return self.coloridx[ax]

    def color(self, ax):
        """Get current color for axis.

        Args:
            ax: Axis object

        Returns:
            Color string for the current color index
        """
        return self.sch.color(self.coloridx[ax])

    def zordernext(self, ax):
        """Get next z-order value for axis.

        Args:
            ax: Axis object

        Returns:
            Next z-order value (slightly higher or lower than current)
        """
        z = self.zorder[ax]
        if self.sch.zdown:
            return z * 0.9999
        return z * 1.0001

    def zordercur(self, ax):
        """Get current z-order value for axis.

        Args:
            ax: Axis object

        Returns:
            Current z-order value
        """
        return self.zorder[ax]


class Plot_OldSync(ParameterizedBase):
    """Matplotlib-based plotting class for backtrader strategies.

    This class provides the main plotting functionality for backtrader,
    creating charts with price data, indicators, volume, and trading signals.

    Attributes:
        scheme: PlotScheme instance with plotting configuration
    """

    scheme = ParameterDescriptor(default=PlotScheme(), doc="Plotting scheme to use")

    def __init__(self, **kwargs):
        """Initialize Plot_OldSync with plotting scheme parameters.

        Args:
            **kwargs: Plotting scheme parameters to override defaults
        """
        # First call parent class initialization, so self.p can be set correctly
        super().__init__()

        # Then set scheme attributes
        for pname, pvalue in kwargs.items():
            setattr(self.p.scheme, pname, pvalue)

    def drawtag(self, ax, x, y, facecolor, edgecolor, alpha=0.9, **kwargs):
        """Draw a text tag on the chart at specified coordinates.

        Args:
            ax: Axis object to draw on
            x: X coordinate
            y: Y coordinate
            facecolor: Background color of the tag
            edgecolor: Border color of the tag
            alpha: Transparency level (default: 0.9)
            **kwargs: Additional keyword arguments for text
        """
        ax.text(
            x,
            y,
            "%.2f" % y,
            va="center",
            ha="left",
            fontsize=self.pinf.sch.subtxtsize,
            bbox=dict(
                boxstyle=tag_box_style, facecolor=facecolor, edgecolor=edgecolor, alpha=alpha
            ),
            # 3.0 is the minimum default for text
            zorder=self.pinf.zorder[ax] + 3.0,
            **kwargs,
        )

    def plot(self, strategy, figid=0, numfigs=1, iplot=True, start=None, end=None, **kwargs):
        """Generate plots for a backtrader strategy.

        Creates matplotlib figures with price data, indicators, volume,
        and other plot elements. Supports multiple figures and date ranges.

        Args:
            strategy: Strategy object with data and indicators
            figid: Base figure identifier (default: 0)
            numfigs: Number of figures to create (default: 1)
            iplot: Whether to use interactive plotting (default: True)
            start: Start date or index (default: None for beginning)
            end: End date or index (default: None for end)
            **kwargs: Additional plotting arguments

        Returns:
            List of matplotlib Figure objects
        """
        # pfillers={}):
        if not strategy.datas:
            return

        if not len(strategy):
            return

        if iplot:
            if "ipykernel" in sys.modules:
                matplotlib.use("nbagg")

        # this import must not happen before matplotlib.use
        import matplotlib.pyplot as mpyplot

        self.mpyplot = mpyplot

        self.pinf = PInfo(self.p.scheme)
        self.sortdataindicators(strategy)
        self.calcrows(strategy)

        st_dtime = strategy.lines.datetime.plot()
        if start is None:
            start = 0
        if end is None:
            end = len(st_dtime)

        if isinstance(start, datetime.date):
            start = bisect.bisect_left(st_dtime, date2num(start))

        if isinstance(end, datetime.date):
            end = bisect.bisect_right(st_dtime, date2num(end))

        if end < 0:
            end = len(st_dtime) + 1 + end  # -1 =  len() -2 = len() - 1

        slen = len(st_dtime[start:end])
        d, m = divmod(slen, numfigs)
        pranges = list()
        for i in range(numfigs):
            a = d * i + start
            if i == (numfigs - 1):
                d += m  # add a remainder to last stint
            b = a + d

            pranges.append([a, b, d])

        figs = []

        for numfig in range(numfigs):
            # prepare a figure
            fig = self.pinf.newfig(figid, numfig, self.mpyplot)
            figs.append(fig)

            self.pinf.pstart, self.pinf.pend, self.pinf.psize = pranges[numfig]
            self.pinf.xstart = self.pinf.pstart
            self.pinf.xend = self.pinf.pend

            self.pinf.clock = strategy
            self.pinf.xreal = self.pinf.clock.datetime.plot(self.pinf.pstart, self.pinf.psize)
            self.pinf.xlen = len(self.pinf.xreal)
            self.pinf.x = list(range(self.pinf.xlen))
            # self.pinf.pfillers = {None: []}
            # for key, val in pfillers.items():
            #     pfstart = bisect.bisect_left(val, self.pinf.pstart)
            #     pfend = bisect.bisect_right(val, self.pinf.pend)
            #     self.pinf.pfillers[key] = val[pfstart:pfend]

            # Do the plotting
            # Things that go always at the top (observers)
            self.pinf.xdata = self.pinf.x
            for ptop in self.dplotstop:
                self.plotind(None, ptop, subinds=self.dplotsover[ptop])

            # Create the rest on a per-data basis
            dt0, dt1 = self.pinf.xreal[0], self.pinf.xreal[-1]
            for data in strategy.datas:
                if not data.plotinfo.plot:
                    continue

                self.pinf.xdata = self.pinf.x
                xd = data.datetime.plotrange(self.pinf.xstart, self.pinf.xend)
                if len(xd) < self.pinf.xlen:
                    self.pinf.xdata = xdata = []
                    xreal = self.pinf.xreal
                    dts = data.datetime.plot()
                    xtemp = list()
                    for dt in (x for x in dts if dt0 <= x <= dt1):
                        dtidx = bisect.bisect_left(xreal, dt)
                        xdata.append(dtidx)
                        xtemp.append(dt)

                    self.pinf.xstart = bisect.bisect_left(dts, xtemp[0])
                    self.pinf.xend = bisect.bisect_right(dts, xtemp[-1])

                for ind in self.dplotsup[data]:
                    self.plotind(
                        data,
                        ind,
                        subinds=self.dplotsover[ind],
                        upinds=self.dplotsup[ind],
                        downinds=self.dplotsdown[ind],
                    )

                self.plotdata(data, self.dplotsover[data])

                for ind in self.dplotsdown[data]:
                    self.plotind(
                        data,
                        ind,
                        subinds=self.dplotsover[ind],
                        upinds=self.dplotsup[ind],
                        downinds=self.dplotsdown[ind],
                    )

            cursor = MultiCursor(
                fig.canvas,
                list(self.pinf.daxis.values()),
                useblit=True,
                horizOn=True,
                vertOn=True,
                horizMulti=False,
                vertMulti=True,
                horizShared=True,
                vertShared=False,
                color="black",
                lw=1,
                ls=":",
            )

            self.pinf.cursors.append(cursor)

            # Put the subplots as indicated by hspace
            fig.subplots_adjust(
                hspace=self.pinf.sch.plotdist, top=0.98, left=0.05, bottom=0.05, right=0.95
            )

            laxis = list(self.pinf.daxis.values())

            # Find the last axis which is not a twinx (date locator fails there)
            i = -1
            while True:
                lastax = laxis[i]
                if lastax not in self.pinf.vaxis:
                    break

                i -= 1

            self.setlocators(lastax)  # place the locators/fmts

            # Applying fig.autofmt_xdate if the data axis is the last one
            # breaks the presentation of the date labels. why?
            # Applying the manual rotation with setp cures the problem
            # but the labels from all axis but the last have to be hidden
            for ax in laxis:
                self.mpyplot.setp(ax.get_xticklabels(), visible=False)

            self.mpyplot.setp(
                lastax.get_xticklabels(), visible=True, rotation=self.pinf.sch.tickrotation
            )

            # Things must be tight along the x-axis (to fill both ends)
            axtight = "x" if not self.pinf.sch.ytight else "both"
            # self.mpyplot.xticks(pd.date_range(start,end),rotation=90)
            self.mpyplot.autoscale(enable=True, axis=axtight, tight=True)

        return figs

    def setlocators(self, ax):
        """Set date locators and formatters for x-axis.

        Configures automatic date formatting based on the timeframe
        of the data being plotted.

        Args:
            ax: Axis object to configure
        """
        tframe = getattr(self.pinf.clock, "_timeframe", TimeFrame.Days)

        if self.pinf.sch.fmt_x_data is None:
            if tframe == TimeFrame.Years:
                fmtdata = "%Y"
            elif tframe == TimeFrame.Months:
                fmtdata = "%Y-%m"
            elif tframe == TimeFrame.Weeks:
                fmtdata = "%Y-%m-%d"
            elif tframe == TimeFrame.Days:
                fmtdata = "%Y-%m-%d"
            elif tframe == TimeFrame.Minutes:
                fmtdata = "%Y-%m-%d %H:%M"
            elif tframe == TimeFrame.Seconds:
                fmtdata = "%Y-%m-%d %H:%M:%S"
            elif tframe == TimeFrame.MicroSeconds:
                fmtdata = "%Y-%m-%d %H:%M:%S.%f"
            elif tframe == TimeFrame.Ticks:
                fmtdata = "%Y-%m-%d %H:%M:%S.%f"
        else:
            fmtdata = self.pinf.sch.fmt_x_data

        fordata = MyDateFormatter(self.pinf.xreal, fmt=fmtdata)
        for dax in self.pinf.daxis.values():
            dax.fmt_xdata = fordata

        # Major locator / formatter
        locmajor = loc.AutoDateLocator(self.pinf.xreal)
        ax.xaxis.set_major_locator(locmajor)
        if self.pinf.sch.fmt_x_ticks is None:
            autofmt = loc.AutoDateFormatter(self.pinf.xreal, locmajor)
        else:
            autofmt = MyDateFormatter(self.pinf.xreal, fmt=self.pinf.sch.fmt_x_ticks)
        ax.xaxis.set_major_formatter(autofmt)

    def calcrows(self, strategy):
        """Calculate the total number of rows needed for plotting.

        Determines how many subplot rows are needed based on data feeds,
        indicators, observers, and volume plots.

        Args:
            strategy: Strategy object with data and indicators
        """
        # Calculate the total number of rows
        rowsmajor = self.pinf.sch.rowsmajor
        rowsminor = self.pinf.sch.rowsminor
        nrows = 0

        datasnoplot = 0
        for data in strategy.datas:
            if not data.plotinfo.plot:
                # neither data nor indicators nor volume add rows
                datasnoplot += 1
                self.dplotsup.pop(data, None)
                self.dplotsdown.pop(data, None)
                self.dplotsover.pop(data, None)

            else:
                pmaster = data.plotinfo.plotmaster
                if pmaster is data:
                    pmaster = None
                if pmaster is not None:
                    # data doesn't add a row, but volume may
                    if self.pinf.sch.volume:
                        nrows += rowsminor
                else:
                    # data adds rows, volume may
                    nrows += rowsmajor
                    if self.pinf.sch.volume and not self.pinf.sch.voloverlay:
                        nrows += rowsminor

        if False:
            # Datas and volumes
            nrows += (len(strategy.datas) - datasnoplot) * rowsmajor
            if self.pinf.sch.volume and not self.pinf.sch.voloverlay:
                nrows += (len(strategy.datas) - datasnoplot) * rowsminor

        # top indicators/observers
        nrows += len(self.dplotstop) * rowsminor

        # indicators above datas
        nrows += sum(len(v) for v in self.dplotsup.values())
        nrows += sum(len(v) for v in self.dplotsdown.values())

        self.pinf.nrows = nrows

    def newaxis(self, obj, rowspan):
        """Create a new axis for plotting.

        Creates a subplot axis with the specified row span and
        configures it with appropriate settings.

        Args:
            obj: Object to associate with this axis
            rowspan: Number of rows this axis should span

        Returns:
            Axis object
        """
        ax = self.mpyplot.subplot2grid(
            (self.pinf.nrows, 1), (self.pinf.row, 0), rowspan=rowspan, sharex=self.pinf.sharex
        )

        # update the sharex information if not available
        if self.pinf.sharex is None:
            self.pinf.sharex = ax

        # update the row index with the taken rows
        self.pinf.row += rowspan

        # save the mapping indicator - axis and return
        self.pinf.daxis[obj] = ax

        # Activate grid in all axes if requested
        ax.yaxis.tick_right()
        ax.grid(self.pinf.sch.grid, which="both")

        return ax

    def plotind(self, iref, ind, subinds=None, upinds=None, downinds=None, masterax=None):
        """Plot an indicator with optional sub-indicators.

        Plots an indicator on an axis, handling line styling, legends,
        fills, and recursively plotting sub-indicators.

        Args:
            iref: Reference object (usually data feed)
            ind: Indicator object to plot
            subinds: List of sub-indicators to plot on same axis (default: None)
            upinds: List of indicators to plot above (default: None)
            downinds: List of indicators to plot below (default: None)
            masterax: Master axis to plot on (default: None to create new)
        """
        # check subind
        subinds = subinds or []
        upinds = upinds or []
        downinds = downinds or []

        # plot subindicators on self with independent axis above
        for upind in upinds:
            self.plotind(iref, upind)

        # Get an axis for this plot
        ax = masterax or self.newaxis(ind, rowspan=self.pinf.sch.rowsminor)

        indlabel = ind.plotlabel()

        # Scan lines quickly to find out if some lines have to be skipped for
        # legend (because matplotlib reorders the legend)
        toskip = 0
        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)
            lineplotinfo = getattr(ind.plotlines, "_%d" % lineidx, None)
            if not lineplotinfo:
                lineplotinfo = getattr(ind.plotlines, linealias, None)
            if not lineplotinfo:
                lineplotinfo = AutoInfoClass()
            pltmethod = lineplotinfo._get("_method", "plot")
            if pltmethod != "plot":
                toskip += 1 - lineplotinfo._get("_plotskip", False)

        if toskip >= ind.size():
            toskip = 0

        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)

            lineplotinfo = getattr(ind.plotlines, "_%d" % lineidx, None)
            if not lineplotinfo:
                lineplotinfo = getattr(ind.plotlines, linealias, None)

            if not lineplotinfo:
                lineplotinfo = AutoInfoClass()

            if lineplotinfo._get("_plotskip", False):
                continue

            # Legend label only when plotting 1st line
            if masterax and not ind.plotinfo.plotlinelabels:
                label = indlabel * (not toskip) or "_nolegend"
            else:
                label = (indlabel + "\n") * (not toskip)
                label += lineplotinfo._get("_name", "") or linealias

            toskip -= 1  # one line less until legend can be added

            # plot data
            lplot = line.plotrange(self.pinf.xstart, self.pinf.xend)

            # Global and generic for indicator
            if self.pinf.sch.linevalues and ind.plotinfo.plotlinevalues:
                plotlinevalue = lineplotinfo._get("_plotvalue", True)
                if len(lplot) > 0:
                    if plotlinevalue and not math.isnan(lplot[-1]):
                        label += " %.2f" % lplot[-1]

            plotkwargs = dict()
            linekwargs = lineplotinfo._getkwargs(skip_=True)

            if linekwargs.get("color", None) is None:
                if not lineplotinfo._get("_samecolor", False):
                    self.pinf.nextcolor(ax)
                plotkwargs["color"] = self.pinf.color(ax)

            plotkwargs.update(dict(aa=True, label=label))
            plotkwargs.update(**linekwargs)

            if ax in self.pinf.zorder:
                plotkwargs["zorder"] = self.pinf.zordernext(ax)

            pltmethod = getattr(ax, lineplotinfo._get("_method", "plot"))

            xdata, lplotarray = self.pinf.xdata, lplot

            # CRITICAL FIX: Check if array is empty to avoid dimension mismatch error
            # Fix dimension mismatch error: ValueError: x and y must have same first dimension
            if not lplotarray or len(lplotarray) == 0:
                # If data is empty, skip plotting
                plottedline = None
                return  # Force exit from this line drawing

            if lineplotinfo._get("_skipnan", False):
                # Get the full array and a mask to skipnan
                lplotarray = np.array(lplot)
                lplotmask = np.isfinite(lplotarray)

                # Get both the axis and the data masked
                lplotarray = lplotarray[lplotmask]
                xdata = np.array(xdata)[lplotmask]

                # Check again if array is empty
                if len(lplotarray) == 0 or len(xdata) == 0 or len(lplotarray) != len(xdata):
                    plottedline = None
                    return  # Skip plotting

            plottedline = pltmethod(xdata, lplotarray, **plotkwargs)
            try:
                plottedline = plottedline[0]
            except (TypeError, IndexError):
                # Possibly a container of artists (when plotting bars)
                pass

            self.pinf.zorder[ax] = plottedline.get_zorder()

            vtags = lineplotinfo._get("plotvaluetags", True)
            if self.pinf.sch.valuetags and vtags:
                linetag = lineplotinfo._get("_plotvaluetag", True)
                if linetag and not math.isnan(lplot[-1]):
                    # line has valid values, plot a tag for the last value
                    self.drawtag(
                        ax,
                        len(self.pinf.xreal),
                        lplot[-1],
                        facecolor="white",
                        edgecolor=self.pinf.color(ax),
                    )

            farts = (
                ("_gt", operator.gt),
                ("_lt", operator.lt),
                ("", None),
            )
            for fcmp, fop in farts:
                fattr = "_fill" + fcmp
                fref, fcol = lineplotinfo._get(fattr, (None, None))
                if fref is not None:
                    y1 = np.array(lplot)
                    if isinstance(fref, integer_types):
                        y2 = np.full_like(y1, fref)
                    else:  # string, naming a line, nothing else is supported
                        l2 = getattr(ind, fref)
                        prl2 = l2.plotrange(self.pinf.xstart, self.pinf.xend)
                        y2 = np.array(prl2)
                    kwargs = dict()
                    if fop is not None:
                        kwargs["where"] = fop(y1, y2)

                    falpha = self.pinf.sch.fillalpha
                    if isinstance(fcol, (list, tuple)):
                        fcol, falpha = fcol

                    ax.fill_between(
                        self.pinf.xdata,
                        y1,
                        y2,
                        facecolor=fcol,
                        alpha=falpha,
                        interpolate=True,
                        **kwargs,
                    )

        # plot subindicators that were created on self
        for subind in subinds:
            self.plotind(iref, subind, subinds=self.dplotsover[subind], masterax=ax)

        if not masterax:
            # adjust margin if requested ... general of particular
            ymargin = ind.plotinfo._get("plotymargin", 0.0)
            ymargin = max(ymargin, self.pinf.sch.yadjust)
            if ymargin:
                ax.margins(y=ymargin)

            # Set specific or generic ticks
            yticks = ind.plotinfo._get("plotyticks", [])
            if not yticks:
                yticks = ind.plotinfo._get("plotyhlines", [])

            if yticks:
                ax.set_yticks(yticks)
            else:
                locator = mticker.MaxNLocator(nbins=4, prune="both")
                ax.yaxis.set_major_locator(locator)

            # Set specific hlines if asked to
            hlines = ind.plotinfo._get("plothlines", [])
            if not hlines:
                hlines = ind.plotinfo._get("plotyhlines", [])
            for hline in hlines:
                ax.axhline(
                    hline,
                    color=self.pinf.sch.hlinescolor,
                    ls=self.pinf.sch.hlinesstyle,
                    lw=self.pinf.sch.hlineswidth,
                )

            if self.pinf.sch.legendind and ind.plotinfo._get("plotlegend", True):
                handles, labels = ax.get_legend_handles_labels()
                # Ensure that we have something to show
                if labels:
                    # location can come from the user
                    loc = ind.plotinfo.legendloc or self.pinf.sch.legendindloc

                    # Legend done here to ensure it includes all plots
                    legend = ax.legend(
                        loc=loc,
                        numpoints=1,
                        frameon=False,
                        shadow=False,
                        fancybox=False,
                        prop=self.pinf.prop,
                    )

                    # legend.set_title(indlabel, prop=self.pinf.prop)
                    # hack: if title is set. legend has a Vbox for the labels
                    # which has a default "center" set
                    legend._legend_box.align = "left"

        # plot subindicators on self with independent axis below
        for downind in downinds:
            self.plotind(iref, downind)

    def plotvolume(self, data, opens, highs, lows, closes, volumes, label):
        """Plot volume for a data feed.

        Creates volume bars with appropriate coloring based on price movement.
        Can be overlaid on price chart or shown in separate subplot.

        Args:
            data: Data feed object
            opens: Array of open prices
            highs: Array of high prices
            lows: Array of low prices
            closes: Array of close prices
            volumes: Array of volume values
            label: Label for the volume plot

        Returns:
            Volume plot artist or None
        """
        pmaster = data.plotinfo.plotmaster
        if pmaster is data:
            pmaster = None
        voloverlay = self.pinf.sch.voloverlay and pmaster is None

        # if sefl.pinf.sch.voloverlay:
        if voloverlay:
            rowspan = self.pinf.sch.rowsmajor
        else:
            rowspan = self.pinf.sch.rowsminor

        ax = self.newaxis(data.volume, rowspan=rowspan)

        # if self.pinf.sch.voloverlay:
        if voloverlay:
            volalpha = self.pinf.sch.voltrans
        else:
            volalpha = 1.0

        maxvol = volylim = max(volumes)
        if maxvol:
            # Plot the volume (no matter if as overlay or standalone)
            vollabel = label
            (volplot,) = plot_volume(
                ax,
                self.pinf.xdata,
                opens,
                closes,
                volumes,
                colorup=self.pinf.sch.volup,
                colordown=self.pinf.sch.voldown,
                alpha=volalpha,
                label=vollabel,
            )

            nbins = 6
            prune = "both"
            # if self.pinf.sch.voloverlay:
            if voloverlay:
                # store for a potential plot over it
                nbins = int(nbins / self.pinf.sch.volscaling)
                prune = None

                volylim /= self.pinf.sch.volscaling
                ax.set_ylim(0, volylim, auto=True)
            else:
                # plot a legend
                handles, labels = ax.get_legend_handles_labels()
                if handles:
                    # location can come from the user
                    loc = data.plotinfo.legendloc or self.pinf.sch.legendindloc

                    # Legend done here to ensure it includes all plots
                    ax.legend(
                        loc=loc,
                        numpoints=1,
                        frameon=False,
                        shadow=False,
                        fancybox=False,
                        prop=self.pinf.prop,
                    )

            locator = mticker.MaxNLocator(nbins=nbins, prune=prune)
            ax.yaxis.set_major_locator(locator)
            ax.yaxis.set_major_formatter(MyVolFormatter(maxvol))

        if not maxvol:
            ax.set_yticks([])
            return None

        return volplot

    def plotdata(self, data, indicators):
        """Plot price data for a data feed.

        Creates candlestick, bar, or line chart for price data along
        with volume and indicators. Handles overlay indicators and
        proper axis configuration.

        Args:
            data: Data feed object with OHLCV data
            indicators: List of indicators to plot with this data
        """
        for ind in indicators:
            upinds = self.dplotsup[ind]
            for upind in upinds:
                self.plotind(
                    data,
                    upind,
                    subinds=self.dplotsover[upind],
                    upinds=self.dplotsup[upind],
                    downinds=self.dplotsdown[upind],
                )

        opens = data.open.plotrange(self.pinf.xstart, self.pinf.xend)
        highs = data.high.plotrange(self.pinf.xstart, self.pinf.xend)
        lows = data.low.plotrange(self.pinf.xstart, self.pinf.xend)
        closes = data.close.plotrange(self.pinf.xstart, self.pinf.xend)
        volumes = data.volume.plotrange(self.pinf.xstart, self.pinf.xend)

        vollabel = "Volume"
        pmaster = data.plotinfo.plotmaster
        if pmaster is data:
            pmaster = None

        datalabel = ""
        if hasattr(data, "_name") and data._name:
            datalabel += data._name

        voloverlay = self.pinf.sch.voloverlay and pmaster is None

        if not voloverlay:
            vollabel += f" ({datalabel})"

        # if self.pinf.sch.volume and self.pinf.sch.voloverlay:
        axdatamaster = None
        if self.pinf.sch.volume and voloverlay:
            volplot = self.plotvolume(data, opens, highs, lows, closes, volumes, vollabel)
            axvol = self.pinf.daxis[data.volume]
            ax = axvol.twinx()
            self.pinf.daxis[data] = ax
            self.pinf.vaxis.append(ax)
        else:
            if pmaster is None:
                ax = self.newaxis(data, rowspan=self.pinf.sch.rowsmajor)
            elif getattr(data.plotinfo, "sameaxis", False):
                axdatamaster = self.pinf.daxis[pmaster]
                ax = axdatamaster
            else:
                axdatamaster = self.pinf.daxis[pmaster]
                ax = axdatamaster.twinx()
                self.pinf.vaxis.append(ax)

        if hasattr(data, "_compression") and hasattr(data, "_timeframe"):
            tfname = TimeFrame.getname(data._timeframe, data._compression)
            datalabel += " (%d %s)" % (data._compression, tfname)

        plinevalues = getattr(data.plotinfo, "plotlinevalues", True)
        if self.pinf.sch.style.startswith("line"):
            if self.pinf.sch.linevalues and plinevalues:
                datalabel += " C:%.2f" % closes[-1]

            if axdatamaster is None:
                color = self.pinf.sch.loc
            else:
                self.pinf.nextcolor(axdatamaster)
                color = self.pinf.color(axdatamaster)

            plotted = plot_lineonclose(ax, self.pinf.xdata, closes, color=color, label=datalabel)
        else:
            if self.pinf.sch.linevalues and plinevalues:
                datalabel += " O:{:.2f} H:{:.2f} L:{:.2f} C:{:.2f}".format(
                    opens[-1],
                    highs[-1],
                    lows[-1],
                    closes[-1],
                )
            if self.pinf.sch.style.startswith("candle"):
                plotted = plot_candlestick(
                    ax,
                    self.pinf.xdata,
                    opens,
                    highs,
                    lows,
                    closes,
                    colorup=self.pinf.sch.barup,
                    colordown=self.pinf.sch.bardown,
                    label=datalabel,
                    alpha=self.pinf.sch.baralpha,
                    fillup=self.pinf.sch.barupfill,
                    filldown=self.pinf.sch.bardownfill,
                )

            elif self.pinf.sch.style.startswith("bar") or True:
                # final default option -- should be "else"
                plotted = plot_ohlc(
                    ax,
                    self.pinf.xdata,
                    opens,
                    highs,
                    lows,
                    closes,
                    colorup=self.pinf.sch.barup,
                    colordown=self.pinf.sch.bardown,
                    label=datalabel,
                )

        self.pinf.zorder[ax] = plotted[0].get_zorder()

        # Code to place a label at the right-hand side with the last value
        vtags = data.plotinfo._get("plotvaluetags", True)
        if self.pinf.sch.valuetags and vtags:
            self.drawtag(
                ax, len(self.pinf.xreal), closes[-1], facecolor="white", edgecolor=self.pinf.sch.loc
            )

        ax.yaxis.set_major_locator(mticker.MaxNLocator(prune="both"))
        # make sure "over" indicators do not change our scale
        if data.plotinfo._get("plotylimited", True):
            if axdatamaster is None:
                ax.set_ylim(ax.get_ylim())

        if self.pinf.sch.volume:
            # if not self.pinf.sch.voloverlay:
            if not voloverlay:
                self.plotvolume(data, opens, highs, lows, closes, volumes, vollabel)
            else:
                # Prepare overlay scaling/pushup or manage own axis
                if self.pinf.sch.volpushup:
                    # push up the overlaid axis by lowering the bottom limit
                    axbot, axtop = ax.get_ylim()
                    axbot *= 1.0 - self.pinf.sch.volpushup
                    ax.set_ylim(axbot, axtop)

        for ind in indicators:
            self.plotind(data, ind, subinds=self.dplotsover[ind], masterax=ax)

        handles, labels = ax.get_legend_handles_labels()
        a = axdatamaster or ax
        if handles:
            # put data and volume legend entries in the 1st positions
            # because they are "collections" they are considered after Line2D
            # for the legend entries, which is not our desire
            # if self.pinf.sch.volume and self.pinf.sch.voloverlay:

            ai = self.pinf.legpos[a]
            if self.pinf.sch.volume and voloverlay:
                if volplot:
                    # even if volume plot was requested, there may be no volume
                    labels.insert(ai, vollabel)
                    handles.insert(ai, volplot)

            didx = labels.index(datalabel)
            labels.insert(ai, labels.pop(didx))
            handles.insert(ai, handles.pop(didx))

            if axdatamaster is None:
                self.pinf.handles[ax] = handles
                self.pinf.labels[ax] = labels
            else:
                self.pinf.handles[axdatamaster] = handles
                self.pinf.labels[axdatamaster] = labels
                # self.pinf.handles[axdatamaster].extend(handles)
                # self.pinf.labels[axdatamaster].extend(labels)

            h = self.pinf.handles[a]
            labels = self.pinf.labels[a]

            axlegend = a
            loc = data.plotinfo.legendloc or self.pinf.sch.legenddataloc
            legend = axlegend.legend(
                h,
                labels,
                loc=loc,
                frameon=False,
                shadow=False,
                fancybox=False,
                prop=self.pinf.prop,
                numpoints=1,
                ncol=1,
            )

            # hack: if title is set. legend has a Vbox for the labels
            # which has a default "center" set
            legend._legend_box.align = "left"

        for ind in indicators:
            downinds = self.dplotsdown[ind]
            for downind in downinds:
                self.plotind(
                    data,
                    downind,
                    subinds=self.dplotsover[downind],
                    upinds=self.dplotsup[downind],
                    downinds=self.dplotsdown[downind],
                )

        self.pinf.legpos[a] = len(self.pinf.handles[a])

        if data.plotinfo._get("plotlog", False):
            a = axdatamaster or ax
            a.set_yscale("log")

    def show(self):
        """Display the plot using matplotlib."""
        self.mpyplot.show()

    def savefig(self, fig, filename, width=16, height=9, dpi=300, tight=True):
        """Save figure to file.

        Args:
            fig: Figure object to save
            filename: Output file path
            width: Figure width in inches (default: 16)
            height: Figure height in inches (default: 9)
            dpi: Resolution in dots per inch (default: 300)
            tight: Whether to use tight bounding box (default: True)
        """
        fig.set_size_inches(width, height)
        bbox_inches = "tight" * tight or None
        fig.savefig(filename, dpi=dpi, bbox_inches=bbox_inches)

    def sortdataindicators(self, strategy):
        """Sort indicators and observers into plotting groups.

        Organizes indicators and observers into groups for plotting:
        - Top: Observers that go above all data
        - Up: Indicators that plot above their data
        - Down: Indicators that plot below their data
        - Over: Indicators that overlay on their data

        Args:
            strategy: Strategy object with indicators and observers
        """
        # These lists/dictionaries hold the subplots that go above each data
        self.dplotstop = list()
        self.dplotsup = collections.defaultdict(list)
        self.dplotsdown = collections.defaultdict(list)
        self.dplotsover = collections.defaultdict(list)

        # Sort observers in the different lists/dictionaries
        for x in strategy.getobservers():
            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            if x.plotinfo.subplot:
                self.dplotstop.append(x)
            else:
                key = getattr(x._clock, "owner", x._clock)
                self.dplotsover[key].append(x)

        # Sort indicators in the different lists/dictionaries
        for x in strategy.getindicators():
            if not hasattr(x, "plotinfo"):
                # no plotting support - so far LineSingle derived classes
                continue

            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            x._plotinit()  # will be plotted ... call its init function

            # support LineSeriesStub, which has "owner" to point to the data
            key = getattr(x._clock, "owner", x._clock)
            if key is strategy:  # a LinesCoupler
                key = strategy.data

            if getattr(x.plotinfo, "plotforce", False):
                if key not in strategy.datas:
                    while True:
                        if key not in strategy.datas:
                            key = key._clock
                        else:
                            break

            xpmaster = x.plotinfo.plotmaster
            if xpmaster is x:
                xpmaster = None
            if xpmaster is not None:
                key = xpmaster

            if x.plotinfo.subplot and xpmaster is None:
                if x.plotinfo.plotabove:
                    self.dplotsup[key].append(x)
                else:
                    self.dplotsdown[key].append(x)
            else:
                self.dplotsover[key].append(x)


def plot_results(results, file_name):
    """write by myself to plot the result, and I will update this function"""
    # Total leverage
    df1 = pd.DataFrame([results[0].analyzers._GrossLeverage.get_analysis()]).T
    df1.columns = ["GrossLeverage"]
    # Rolling log returns
    df2 = pd.DataFrame([results[0].analyzers._LogReturnsRolling.get_analysis()]).T
    df2.columns = ["log_return"]

    # year_rate
    df3 = pd.DataFrame([results[0].analyzers._AnnualReturn.get_analysis()]).T
    df3.columns = ["year_rate"]

    #
    df4 = pd.DataFrame(results[0].analyzers._PositionsValue.get_analysis()).T
    df4["total_position_value"] = df4.sum(axis=1)

    GrossLeverage = go.Scatter(x=df1.index, y=df1.GrossLeverage, name="gross_leverage")
    log_return = go.Scatter(
        x=df2.index, y=df2.log_return, xaxis="x2", yaxis="y2", name="log_return"
    )
    cumsum_return = go.Scatter(
        x=df2.index, y=df2.log_return.cumsum(), xaxis="x2", yaxis="y2", name="cumsum_return"
    )

    year_rate = go.Bar(x=df3.index, y=df3.year_rate, xaxis="x3", yaxis="y3", name="year_rate")
    total_position_value = go.Scatter(
        x=df4.index, y=df4.total_position_value, xaxis="x4", yaxis="y4", name="total_position_value"
    )
    data = [GrossLeverage, log_return, cumsum_return, year_rate, total_position_value]
    layout = go.Layout(
        xaxis=dict(domain=[0, 0.45]),
        yaxis=dict(domain=[0, 0.45]),
        xaxis2=dict(domain=[0.55, 1]),
        xaxis3=dict(domain=[0, 0.45], anchor="y3"),
        xaxis4=dict(domain=[0.55, 1], anchor="y4"),
        yaxis2=dict(domain=[0, 0.45], anchor="x2"),
        yaxis3=dict(domain=[0.55, 1]),
        yaxis4=dict(domain=[0.55, 1], anchor="x4"),
    )
    fig = go.Figure(data=data, layout=layout)
    py.offline.plot(fig, filename=file_name, auto_open=False)


Plot = Plot_OldSync


def create_table(df, max_rows=18):
    """Create HTML table from dataframe for Dash display.

    Args:
        df: DataFrame to convert to table
        max_rows: Maximum number of rows to display (default: 18)

    Returns:
        Dash HTML table object
    """

    table = html.Table(
        # Header
        [html.Tr([html.Th(col) for col in df.columns])]
        +
        # Body
        [
            html.Tr([html.Td(df.iloc[i][col]) for col in df.columns])
            for i in range(min(len(df), max_rows))
        ]
    )
    return table


def get_rate_sharpe_drawdown(data):
    """Calculate Sharpe ratio, annual return, and maximum drawdown.

    For intraday data, extracts the last value of each day as the daily
    closing value. Assumes 252 trading days per year.

    Args:
        data: DataFrame with datetime index and total_value column

    Returns:
        Tuple of (sharpe_ratio, annual_return, max_drawdown)
    """
    # Calculate Sharpe ratio, compound annual return, maximum drawdown
    # For periods less than daily, extract the last value of each day as the final value of a trading day,
    # For futures minute data, it's not calculated based on 15:00 close, which may slightly affect Sharpe ratio and other indicators, but the impact is small.
    data.index = pd.to_datetime(data.index)
    data["date"] = [str(i)[:10] for i in data.index]
    data1 = data.drop_duplicates("date", keep="last")
    data1.index = pd.to_datetime(data1["date"])
    # print(data1)
    if len(data1) == 0:
        return np.nan, np.nan, np.nan
    try:
        # Assume 252 trading days in a year
        data1["rate1"] = np.log(data1["total_value"]) - np.log(data1["total_value"].shift(1))
        # data['rate2']=data['total_value'].pct_change()
        data1 = data1.dropna()
        sharpe_ratio = data1["rate1"].mean() * 252**0.5 / (data1["rate1"].std())
        # Annualized return is:
        value_list = list(data["total_value"])
        begin_value = value_list[0]
        end_value = value_list[-1]
        begin_date = data.index[0]
        end_date = data.index[-1]
        days = (end_date - begin_date).days
        # print(begin_date,begin_value,end_date,end_value,1/(days/365))
        # If the calculated actual return is negative, default to maximum of 0, return cannot be negative
        total_rate = max((end_value - begin_value) / begin_value, -0.9999)
        average_rate = (1 + total_rate) ** (1 / (days / 365)) - 1
        # Calculate maximum drawdown
        data["rate1"] = np.log(data["total_value"]) - np.log(data["total_value"].shift(1))
        df = data["rate1"].cumsum()
        df = df.dropna()
        # index_j = np.argmax(np.maximum.accumulate(df) - df)  # End position
        index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
        # print("Maximum drawdown end time",index_j)
        # index_i = np.argmax(df[:index_j])  # Start position
        index_i = np.argmax(np.array(df[:index_j]))  # Start position
        # print("Maximum drawdown start time",index_i)
        max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]
        """
        begin_max_drawdown_value = data['total_value'][index_i]
        end_max_drawdown_value = data['total_value'][index_j]
        # print("begin_max_drawdown_value",begin_max_drawdown_value)  # Removed for performance
        # print("end_max_drawdown_value",end_max_drawdown_value)  # Removed for performance
        maxdrawdown_rate = (end_max_drawdown_value -begin_max_drawdown_value)/begin_max_drawdown_value  # Maximum drawdown ratio
        maxdrawdown_value = data['total_value'][index_j] -data['total_value'][index_i] #Maximum drawdown value
        # print("Maximum drawdown value is",maxdrawdown_value)  # Removed for performance
        # print("Maximum drawdown ratio is",maxdrawdown_rate)  # Removed for performance
        # Draw chart
        plt.plot(df[1:len(df)])
        plt.plot([index_i], [df[index_i]], 'o', color="r", markersize=10)
        plt.plot([index_j], [df[index_j]], 'o', color="blue", markersize=10)
        plt.show()
        """
        return sharpe_ratio, average_rate, max_drawdown
    except Exception as e:
        traceback.format_exception(type(e), e, e.__traceback__)
        return np.nan, np.nan, np.nan


def get_year_return(data):
    """Calculate annualized annual return"""
    data.index = pd.to_datetime(data.index)
    data["year"] = [i.year for i in data.index]
    last_data = data.iloc[-1:, ::]
    data = data.drop_duplicates("year")
    # data = data.append(last_data)
    data = pd.concat([data, last_data], axis=0)
    data["next_year_value"] = data["total_value"].shift(-1)
    data["return"] = data["next_year_value"] / data["total_value"] - 1
    data = data.dropna()
    data["datetime"] = [str(i) + "-6-30" for i in data.year]
    data.index = pd.to_datetime(data.datetime)
    data = data[["return", "datetime"]]
    return data


def run_cerebro_and_plot(
    cerebro, strategy, params, score=90, port=8050, optimize=True, auto_open=True, result_path=""
):
    """Run cerebro backtest and save/plot results.

    Executes a backtest with the given strategy and parameters,
    calculates performance metrics, and saves results to CSV files.

    Args:
        cerebro: Cerebro instance configured with data
        strategy: Strategy class to run
        params: Dictionary of strategy parameters
        score: Minimum score threshold (default: 90)
        port: Port for dashboard server (default: 8050)
        optimize: Whether to run in optimization mode (default: True)
        auto_open: Whether to auto-open plot (default: True)
        result_path: Path to save result files (default: current directory)

    Returns:
        None (saves results to CSV files)
    """
    strategy_name = strategy.__name__
    params_str = ""
    for key in params:
        if key != "symbol_list" and key != "datas":
            params_str = params_str + "__" + key + "__" + str(params[key])
    file_name = strategy_name + params_str + ".csv"
    if result_path != "":
        file_list = os.listdir(result_path)
    else:
        file_list = os.listdir(os.getcwd())
    if file_name in file_list:
        print(f"backtest {params_str} consume time  :0 because of it has run")
    # print("file name is {}".format(file_name))
    # print("file_list is {}".format(file_list))
    if file_name not in file_list:
        print(
            "begin to run this params:{},now_time is {}".format(
                params_str, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            )
        )
        cerebro.addstrategy(strategy, **params)
        begin_time = time.time()
        if optimize:
            cerebro.addanalyzer(analyzers.TotalValue, _name="_TotalValue")
            results = cerebro.run()
            # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
            end_time = time.time()
            print(
                "backtest {} consume time  :{}, end time is:{}".format(
                    params_str,
                    end_time - begin_time,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
            )
            # Get key account value and calculate three major indicators
            df0 = pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
            df0.columns = ["total_value"]
            df0["datetime"] = df0.index
            df0 = df0.sort_values("datetime")
            del df0["datetime"]
            df0.to_csv(result_path + strategy_name + params_str + "___value.csv")
            # Calculate annual return based on daily net value
            df_return = get_year_return(copy.deepcopy(df0))
            # Calculate Sharpe ratio, average return, maximum drawdown
            sharpe_ratio, average_rate, max_drawdown_rate = get_rate_sharpe_drawdown(
                copy.deepcopy(df0)
            )
            # Analyze trading performance
            performance_dict = OrderedDict()
            # Performance measurement indicators
            performance_dict["sharpe_ratio"] = sharpe_ratio
            performance_dict["average_rate"] = average_rate
            performance_dict["max_drawdown_rate"] = max_drawdown_rate
            performance_dict["calmar_ratio"] = np.nan
            performance_dict["average_drawdown_len"] = np.nan
            performance_dict["average_drawdown_rate"] = np.nan
            performance_dict["average_drawdown_money"] = np.nan
            performance_dict["max_drawdown_len"] = np.nan
            performance_dict["max_drawdown_money"] = np.nan
            performance_dict["stddev_rate"] = np.nan
            performance_dict["positive_year"] = np.nan
            performance_dict["negative_year"] = np.nan
            performance_dict["nochange_year"] = np.nan
            performance_dict["best_year"] = np.nan
            performance_dict["worst_year"] = np.nan
            performance_dict["sqn_ratio"] = np.nan
            performance_dict["vwr_ratio"] = np.nan
            performance_dict["omega"] = np.nan
            trade_dict_1 = OrderedDict()
            trade_dict_2 = OrderedDict()
            trade_dict_1["total_trade_num"] = np.nan
            trade_dict_1["total_trade_opened"] = np.nan
            trade_dict_1["total_trade_closed"] = np.nan
            trade_dict_1["total_trade_len"] = np.nan
            trade_dict_1["long_trade_len"] = np.nan
            trade_dict_1["short_trade_len"] = np.nan
            trade_dict_1["longest_win_num"] = np.nan
            trade_dict_1["longest_lost_num"] = np.nan
            trade_dict_1["net_total_pnl"] = np.nan
            trade_dict_1["net_average_pnl"] = np.nan
            trade_dict_1["win_num"] = np.nan
            trade_dict_1["win_total_pnl"] = np.nan
            trade_dict_1["win_average_pnl"] = np.nan
            trade_dict_1["win_max_pnl"] = np.nan
            trade_dict_1["lost_num"] = np.nan
            trade_dict_1["lost_total_pnl"] = np.nan
            trade_dict_1["lost_average_pnl"] = np.nan
            trade_dict_1["lost_max_pnl"] = np.nan

            trade_dict_2["long_num"] = np.nan
            trade_dict_2["long_win_num"] = np.nan
            trade_dict_2["long_lost_num"] = np.nan
            trade_dict_2["long_total_pnl"] = np.nan
            trade_dict_2["long_average_pnl"] = np.nan
            trade_dict_2["long_win_total_pnl"] = np.nan
            trade_dict_2["long_win_max_pnl"] = np.nan
            trade_dict_2["long_lost_total_pnl"] = np.nan
            trade_dict_2["long_lost_max_pnl"] = np.nan
            trade_dict_2["short_num"] = np.nan
            trade_dict_2["short_win_num"] = np.nan
            trade_dict_2["short_lost_num"] = np.nan
            trade_dict_2["short_total_pnl"] = np.nan
            trade_dict_2["short_average_pnl"] = np.nan
            trade_dict_2["short_win_total_pnl"] = np.nan
            trade_dict_2["short_win_max_pnl"] = np.nan
            trade_dict_2["short_lost_total_pnl"] = np.nan
            trade_dict_2["short_lost_max_pnl"] = np.nan

            assert len(performance_dict) == len(trade_dict_2) == len(trade_dict_1)
            df00 = pd.DataFrame(index=range(18))
            df01 = pd.DataFrame([performance_dict]).T
            df01.columns = ["Performance indicator value"]
            df02 = pd.DataFrame([trade_dict_1]).T
            df02.columns = ["General trading indicator value"]
            df03 = pd.DataFrame([trade_dict_2]).T
            df03.columns = ["Long/short trading indicator value"]
            try:
                df00["Performance indicator"] = df01.index
                df00["Performance indicator value"] = [
                    round(float(i), 4) for i in list(df01["Performance indicator value"])
                ]
                df00["General trading indicator"] = df02.index
                df00["General trading indicator value"] = [
                    round(float(i), 4) for i in list(df02["General trading indicator value"])
                ]
                df00["Long/short trading indicator"] = df03.index
                df00["Long/short trading indicator value"] = [
                    round(float(i), 4) for i in list(df03["Long/short trading indicator value"])
                ]
            except Exception as e:
                traceback.format_exception(type(e), e, e.__traceback__)
                df00["Performance indicator"] = df01.index
                df00["Performance indicator value"] = df01["Performance indicator value"]
                df00["General trading indicator"] = df02.index
                df00["General trading indicator value"] = df02["General trading indicator value"]
                df00["Long/short trading indicator"] = df03.index
                df00["Long/short trading indicator value"] = df03[
                    "Long/short trading indicator value"
                ]
                # print("Performance indicator value", df01["Performance indicator value"])  # Removed for performance
                # print(performance_dict)  # Removed for performance
                # print(strategy.__name__ + params_str)  # Removed for performance
                # print(sharpe_ratio, average_rate, max_drawdown_rate)  # Removed for performance

        if not optimize:
            # Save required trading indicators
            # cerebro.addanalyzer(analyzers.PyFolio, _name='pyfolio')
            # cerebro.addanalyzer(analyzers.AnnualReturn, _name='_AnnualReturn') # Annual return calculation has issues, removed
            cerebro.addanalyzer(analyzers.Calmar, _name="_Calmar")
            cerebro.addanalyzer(analyzers.DrawDown, _name="_DrawDown")
            # cerebro.addanalyzer(analyzers.TimeDrawDown, _name='_TimeDrawDown')
            cerebro.addanalyzer(analyzers.GrossLeverage, _name="_GrossLeverage")
            cerebro.addanalyzer(analyzers.PositionsValue, _name="_PositionsValue")
            # cerebro.addanalyzer(analyzers.LogReturnsRolling, _name='_LogReturnsRolling')
            cerebro.addanalyzer(analyzers.PeriodStats, _name="_PeriodStats")
            cerebro.addanalyzer(analyzers.Returns, _name="_Returns")
            cerebro.addanalyzer(analyzers.SharpeRatio, _name="_SharpeRatio")
            # cerebro.addanalyzer(analyzers.SharpeRatio_A, _name='_SharpeRatio_A')
            cerebro.addanalyzer(analyzers.SQN, _name="_SQN")
            cerebro.addanalyzer(analyzers.TimeReturn, _name="_TimeReturn")
            cerebro.addanalyzer(analyzers.TradeAnalyzer, _name="_TradeAnalyzer")
            cerebro.addanalyzer(analyzers.Transactions, _name="_Transactions")
            cerebro.addanalyzer(analyzers.VWR, _name="_VWR")
            cerebro.addanalyzer(analyzers.TotalValue, _name="_TotalValue")
            cerebro.addanalyzer(analyzers.PyFolio)
            results = cerebro.run()
            # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
            end_time = time.time()
            print(
                "backtest {} consume time  :{}, end time is:{}".format(
                    params_str,
                    end_time - begin_time,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
            )
            # Analyze trading performance
            performance_dict = OrderedDict()
            drawdown_info = results[0].analyzers._DrawDown.get_analysis()
            # Calculate periodic indicators
            PeriodStats_info = results[0].analyzers._PeriodStats.get_analysis()
            # Calculate sqn indicator
            SQN_info = results[0].analyzers._SQN.get_analysis()
            sqn_ratio = SQN_info.get("sqn", np.nan)
            # Calculate vwr indicator
            VWR_info = results[0].analyzers._VWR.get_analysis()
            vwr_ratio = VWR_info.get("vwr", np.nan)
            # Calculate calmar indicator
            # calmar_ratio_list = list(results[0].analyzers._Calmar.get_analysis().values())
            # calmar_ratio = calmar_ratio_list[-1] if len(calmar_ratio_list) > 0 else np.nan
            calmar_ratio = np.nan
            # Calculate Sharpe ratio
            sharpe_info = results[0].analyzers._SharpeRatio.get_analysis()
            sharpe_ratio = sharpe_info.get("sharperatio", np.nan)
            # Get average drawdown indicator
            average_drawdown_len = drawdown_info.get("len", np.nan)
            average_drawdown_rate = drawdown_info.get("drawdown", np.nan)
            average_drawdown_money = drawdown_info.get("moneydown", np.nan)
            # Get maximum drawdown indicator
            max_drawdown_info = drawdown_info.get("max", {})
            max_drawdown_len = max_drawdown_info.get("len", np.nan)
            max_drawdown_rate = max_drawdown_info.get("drawdown", np.nan)
            max_drawdown_money = max_drawdown_info.get("moneydown", np.nan)

            average_rate = PeriodStats_info.get("average", np.nan)
            stddev_rate = PeriodStats_info.get("stddev", np.nan)
            positive_year = PeriodStats_info.get("positive", np.nan)
            negative_year = PeriodStats_info.get("negative", np.nan)
            nochange_year = PeriodStats_info.get("nochange", np.nan)
            best_year = PeriodStats_info.get("best", np.nan)
            worst_year = PeriodStats_info.get("worst", np.nan)

            # Get key account value and calculate three major indicators
            df0 = pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
            df0.columns = ["total_value"]
            df0["datetime"] = df0.index
            df0 = df0.sort_values("datetime")
            del df0["datetime"]
            df0.to_csv(result_path + strategy_name + params_str + "___value.csv")
            # Calculate annual return based on daily net value
            df_return = get_year_return(copy.deepcopy(df0))
            # Calculate Sharpe ratio, average return, maximum drawdown
            sharpe_ratio, average_rate, max_drawdown_rate = get_rate_sharpe_drawdown(
                copy.deepcopy(df0)
            )

            # Performance measurement indicators
            performance_dict["sharpe_ratio"] = sharpe_ratio
            performance_dict["average_rate"] = average_rate
            performance_dict["max_drawdown_rate"] = max_drawdown_rate
            performance_dict["calmar_ratio"] = calmar_ratio
            performance_dict["average_drawdown_len"] = average_drawdown_len
            performance_dict["average_drawdown_rate"] = average_drawdown_rate
            performance_dict["average_drawdown_money"] = average_drawdown_money
            performance_dict["max_drawdown_len"] = max_drawdown_len
            performance_dict["max_drawdown_money"] = max_drawdown_money
            performance_dict["stddev_rate"] = stddev_rate
            performance_dict["positive_year"] = positive_year
            performance_dict["negative_year"] = negative_year
            performance_dict["nochange_year"] = nochange_year
            performance_dict["best_year"] = best_year
            performance_dict["worst_year"] = worst_year
            performance_dict["sqn_ratio"] = sqn_ratio
            performance_dict["vwr_ratio"] = vwr_ratio
            performance_dict["omega"] = np.nan

            trade_dict_1 = OrderedDict()
            trade_dict_2 = OrderedDict()

            try:
                trade_info = results[0].analyzers._TradeAnalyzer.get_analysis()
                total_trade_num = trade_info["total"]["total"]
                total_trade_opened = trade_info["total"]["open"]
                total_trade_closed = trade_info["total"]["closed"]
                total_trade_len = trade_info["len"]["total"]
                long_trade_len = trade_info["len"]["long"]["total"]
                short_trade_len = trade_info["len"]["short"]["total"]
            except Exception as e:
                traceback.format_exception(type(e), e, e.__traceback__)
                total_trade_num = np.nan
                total_trade_opened = np.nan
                total_trade_closed = np.nan
                total_trade_len = np.nan
                long_trade_len = np.nan
                short_trade_len = np.nan

            try:
                longest_win_num = trade_info["streak"]["won"]["longest"]
                longest_lost_num = trade_info["streak"]["lost"]["longest"]
                net_total_pnl = trade_info["pnl"]["net"]["total"]
                net_average_pnl = trade_info["pnl"]["net"]["average"]
                win_num = trade_info["won"]["total"]
                win_total_pnl = trade_info["won"]["pnl"]["total"]
                win_average_pnl = trade_info["won"]["pnl"]["average"]
                win_max_pnl = trade_info["won"]["pnl"]["max"]
                lost_num = trade_info["lost"]["total"]
                lost_total_pnl = trade_info["lost"]["pnl"]["total"]
                lost_average_pnl = trade_info["lost"]["pnl"]["average"]
                lost_max_pnl = trade_info["lost"]["pnl"]["max"]
            except Exception as e:
                traceback.format_exception(type(e), e, e.__traceback__)
                longest_win_num = np.nan
                longest_lost_num = np.nan
                net_total_pnl = np.nan
                net_average_pnl = np.nan
                win_num = np.nan
                win_total_pnl = np.nan
                win_average_pnl = np.nan
                win_max_pnl = np.nan
                lost_num = np.nan
                lost_total_pnl = np.nan
                lost_average_pnl = np.nan
                lost_max_pnl = np.nan

            trade_dict_1["total_trade_num"] = total_trade_num
            trade_dict_1["total_trade_opened"] = total_trade_opened
            trade_dict_1["total_trade_closed"] = total_trade_closed
            trade_dict_1["total_trade_len"] = total_trade_len
            trade_dict_1["long_trade_len"] = long_trade_len
            trade_dict_1["short_trade_len"] = short_trade_len
            trade_dict_1["longest_win_num"] = longest_win_num
            trade_dict_1["longest_lost_num"] = longest_lost_num
            trade_dict_1["net_total_pnl"] = net_total_pnl
            trade_dict_1["net_average_pnl"] = net_average_pnl
            trade_dict_1["win_num"] = win_num
            trade_dict_1["win_total_pnl"] = win_total_pnl
            trade_dict_1["win_average_pnl"] = win_average_pnl
            trade_dict_1["win_max_pnl"] = win_max_pnl
            trade_dict_1["lost_num"] = lost_num
            trade_dict_1["lost_total_pnl"] = lost_total_pnl
            trade_dict_1["lost_average_pnl"] = lost_average_pnl
            trade_dict_1["lost_max_pnl"] = lost_max_pnl

            try:
                long_num = trade_info["long"]["total"]
                long_win_num = trade_info["long"]["won"]
                long_lost_num = trade_info["long"]["lost"]
                long_total_pnl = trade_info["long"]["pnl"]["total"]
                long_average_pnl = trade_info["long"]["pnl"]["average"]
                long_win_total_pnl = trade_info["long"]["pnl"]["won"]["total"]
                long_win_max_pnl = trade_info["long"]["pnl"]["won"]["max"]
                long_lost_total_pnl = trade_info["long"]["pnl"]["lost"]["total"]
                long_lost_max_pnl = trade_info["long"]["pnl"]["lost"]["max"]

                short_num = trade_info["short"]["total"]
                short_win_num = trade_info["short"]["won"]
                short_lost_num = trade_info["short"]["lost"]
                short_total_pnl = trade_info["short"]["pnl"]["total"]
                short_average_pnl = trade_info["short"]["pnl"]["average"]
                short_win_total_pnl = trade_info["short"]["pnl"]["won"]["total"]
                short_win_max_pnl = trade_info["short"]["pnl"]["won"]["max"]
                short_lost_total_pnl = trade_info["short"]["pnl"]["lost"]["total"]
                short_lost_max_pnl = trade_info["short"]["pnl"]["lost"]["max"]
            except Exception as e:
                traceback.format_exception(type(e), e, e.__traceback__)
                long_num = np.nan
                long_win_num = np.nan
                long_lost_num = np.nan
                long_total_pnl = np.nan
                long_average_pnl = np.nan
                long_win_total_pnl = np.nan
                long_win_max_pnl = np.nan
                long_lost_total_pnl = np.nan
                long_lost_max_pnl = np.nan

                short_num = np.nan
                short_win_num = np.nan
                short_lost_num = np.nan
                short_total_pnl = np.nan
                short_average_pnl = np.nan
                short_win_total_pnl = np.nan
                short_win_max_pnl = np.nan
                short_lost_total_pnl = np.nan
                short_lost_max_pnl = np.nan

            trade_dict_2["long_num"] = long_num
            trade_dict_2["long_win_num"] = long_win_num
            trade_dict_2["long_lost_num"] = long_lost_num
            trade_dict_2["long_total_pnl"] = long_total_pnl
            trade_dict_2["long_average_pnl"] = long_average_pnl
            trade_dict_2["long_win_total_pnl"] = long_win_total_pnl
            trade_dict_2["long_win_max_pnl"] = long_win_max_pnl
            trade_dict_2["long_lost_total_pnl"] = long_lost_total_pnl
            trade_dict_2["long_lost_max_pnl"] = long_lost_max_pnl
            trade_dict_2["short_num"] = short_num
            trade_dict_2["short_win_num"] = short_win_num
            trade_dict_2["short_lost_num"] = short_lost_num
            trade_dict_2["short_total_pnl"] = short_total_pnl
            trade_dict_2["short_average_pnl"] = short_average_pnl
            trade_dict_2["short_win_total_pnl"] = short_win_total_pnl
            trade_dict_2["short_win_max_pnl"] = short_win_max_pnl
            trade_dict_2["short_lost_total_pnl"] = short_lost_total_pnl
            trade_dict_2["short_lost_max_pnl"] = short_lost_max_pnl

            assert len(performance_dict) == len(trade_dict_2) == len(trade_dict_1)
            df00 = pd.DataFrame(index=range(18))
            df01 = pd.DataFrame([performance_dict]).T
            df01.columns = ["Performance indicator value"]
            df02 = pd.DataFrame([trade_dict_1]).T
            df02.columns = ["General trading indicator value"]
            df03 = pd.DataFrame([trade_dict_2]).T
            df03.columns = ["Long/short trading indicator value"]
            try:
                df00["Performance indicator"] = df01.index
                df00["Performance indicator value"] = [
                    round(float(i), 4) for i in list(df01["Performance indicator value"])
                ]
                df00["General trading indicator"] = df02.index
                df00["General trading indicator value"] = [
                    round(float(i), 4) for i in list(df02["General trading indicator value"])
                ]
                df00["Long/short trading indicator"] = df03.index
                df00["Long/short trading indicator value"] = [
                    round(float(i), 4) for i in list(df03["Long/short trading indicator value"])
                ]
            except Exception as e:
                traceback.format_exception(type(e), e, e.__traceback__)
                df00["Performance indicator"] = df01.index
                df00["Performance indicator value"] = df01["Performance indicator value"]
                df00["General trading indicator"] = df02.index
                df00["General trading indicator value"] = df02["General trading indicator value"]
                df00["Long/short trading indicator"] = df03.index
                df00["Long/short trading indicator value"] = df03[
                    "Long/short trading indicator value"
                ]
                # print("Performance indicator value", df01["Performance indicator value"])  # Removed for performance
                # print(performance_dict)  # Removed for performance
                # print(strategy.__name__ + params_str)  # Removed for performance
                # print(sharpe_ratio, average_rate, max_drawdown_rate)  # Removed for performance

            # Add table data
            table_data = [
                list(df00["Performance indicator"])[:9],
                list(df00["Performance indicator value"])[:9],
                list(df00["Performance indicator"])[9:],
                list(df00["Performance indicator value"])[9:],
                list(df00["General trading indicator"])[:9],
                list(df00["General trading indicator value"])[:9],
                list(df00["General trading indicator"])[9:],
                list(df00["General trading indicator value"])[9:],
                list(df00["Long/short trading indicator"])[:9],
                list(df00["Long/short trading indicator value"])[:9],
                list(df00["Long/short trading indicator"])[9:],
                list(df00["Long/short trading indicator value"])[9:],
            ]
            fig = ff.create_table(table_data)
            # Add graph data
            # Add graph data
            trace1 = go.Scatter(
                x=list(df0.index),
                y=list(df0.total_value),
                xaxis="x2",
                yaxis="y2",
                name="total_value",
                mode="lines",
            )
            trace2 = go.Bar(
                x=list(df_return.index),
                y=[str(round(i, 3)) + "%" for i in list(df_return["return"])],
                xaxis="x2",
                yaxis="y3",
                name="year_profit",
                opacity=0.3,
                marker={"color": "#ffa631"},
            )
            # Add trace data to figure
            fig.add_traces([trace1, trace2])

            # initialize xaxis2 and yaxis2
            fig["layout"]["xaxis2"] = {}
            fig["layout"]["yaxis2"] = {}
            fig["layout"]["yaxis3"] = {}

            # Edit layout for subplots
            fig.layout.yaxis.update({"domain": [0.5, 1]})
            fig.layout.yaxis2.update({"domain": [0, 0.5]})
            fig.layout.yaxis3.update({"domain": [0, 0.5]})

            # The graph's yaxis2 MUST BE anchored to the graph's xaxis2 and vice versa
            # fig.layout.yaxis3.update({'anchor': 'x2'})
            # # fig.layout.xaxis2.update({'anchor': 'y3'})
            # fig.layout.yaxis3.update({'title': 'year_profit'})
            # fig.layout.yaxis3.update({'overlaying':'y2', 'side':'right'})

            fig.layout.yaxis2.update({"anchor": "x2"})
            fig.layout.xaxis2.update({"anchor": "y2"})
            fig.layout.yaxis2.update({"title": "total_value"})
            fig.layout.yaxis2.update({"type": "log"})

            fig.layout.yaxis3.update({"anchor": "x2"})
            # fig.layout.xaxis2.update({'anchor': 'y3'})
            fig.layout.yaxis3.update({"title": "year_profit"})
            fig.layout.yaxis3.update({"overlaying": "y2", "side": "right"})

            # Update the margins to add a title and see graph x-labels.
            fig.layout.margin.update({"t": 75, "l": 50})
            fig.layout.update(
                {
                    "title": {
                        "text": strategy.__name__ + params_str,
                        "x": 0.5,
                        "xanchor": "center",
                        "yanchor": "middle",
                        "font": {"family": "Arial", "color": "red"},
                    }
                }
            )

            # Update the height because adding a graph vertically will interact with
            # the plot height calculated for the table
            fig.layout.update({"height": 800})

            py.plot(fig, auto_open=auto_open, filename=result_path + strategy.__name__ + params_str)
        df00.to_csv(result_path + strategy.__name__ + params_str + ".csv", encoding="gbk")

        return results

    # def run_cerebro_plot(cerebro,strategy,params,score = 90,port=8050,plot=True,result_path=''):


#     strategy_name = strategy.__name__
#     author = strategy.author
#     params_str=''
#     for key in params:
#         params_str=params_str+'__'+key+'__'+str(params[key])
#     file_name = strategy_name+params_str+'.csv'
#     if result_path!="":
#         file_list = os.listdir(result_path)
#     else:
#         file_list = os.listdir(os.getcwd())
#     if file_name in file_list:
#         print("backtest {} consume time  :0 because of it has run".format(params_str))
#     # print("file name is {}".format(file_name))
#     # print("file_list is {}".format(file_list))
#     if file_name not in file_list:
#         print("begin to run this params:{},now_time is {}".format(params_str,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
#         cerebro.addstrategy(strategy,**params)
#         begin_time=time.time()
#         if plot:
#             cerebro.addanalyzer(analyzers.PyFolio, _name='pyfolio')
#             cerebro.addanalyzer(analyzers.AnnualReturn, _name='_AnnualReturn')
#             cerebro.addanalyzer(analyzers.Calmar, _name='_Calmar')
#             cerebro.addanalyzer(analyzers.DrawDown, _name='_DrawDown')
#             # cerebro.addanalyzer(analyzers.TimeDrawDown, _name='_TimeDrawDown')
#             cerebro.addanalyzer(analyzers.GrossLeverage, _name='_GrossLeverage')
#             cerebro.addanalyzer(analyzers.PositionsValue, _name='_PositionsValue')
#             # cerebro.addanalyzer(analyzers.LogReturnsRolling, _name='_LogReturnsRolling')
#             cerebro.addanalyzer(analyzers.PeriodStats, _name='_PeriodStats')
#             cerebro.addanalyzer(analyzers.Returns, _name='_Returns')
#             cerebro.addanalyzer(analyzers.SharpeRatio, _name='_SharpeRatio')
#             # cerebro.addanalyzer(analyzers.SharpeRatio_A, _name='_SharpeRatio_A')
#             cerebro.addanalyzer(analyzers.SQN, _name='_SQN')
#             cerebro.addanalyzer(analyzers.TimeReturn, _name='_TimeReturn')
#             cerebro.addanalyzer(analyzers.TradeAnalyzer, _name='_TradeAnalyzer')
#             cerebro.addanalyzer(analyzers.Transactions, _name='_Transactions')
#             cerebro.addanalyzer(analyzers.VWR, _name='_VWR')
#             cerebro.addanalyzer(analyzers.TotalValue, _name='_TotalValue')
#         else:
#             cerebro.addanalyzer(analyzers.TotalValue, _name='_TotalValue')
#         results = cerebro.run()
#         # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
#         end_time=time.time()
#         print("backtest {} consume time  :{}, end time is:{}".format(params_str,end_time-begin_time,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
#         # Save trading data
#         try:
#             transactions=results[0].analyzers._Transactions.get_analysis()
#             import pickle
#             file_name_test="C:/{}{}_transactions.pkl".format(strategy_name,params_str)
#             with open(file_name_test) as f:
#                 pickle.dump(transactions,f)
#         except:
#             pass
#             print("Data save failed")
#         try:
#             performance_dict=OrderedDict()
#             drawdown_info=results[0].analyzers._DrawDown.get_analysis()
#             average_drawdown_len=drawdown_info['len']
#             average_drawdown_rate=drawdown_info['drawdown']
#             average_drawdown_money=drawdown_info['moneydown']
#             max_drawdown_len=drawdown_info['max']['len']
#             max_drawdown_rate=drawdown_info['max']['drawdown']
#             max_drawdown_money=drawdown_info['max']['moneydown']
#             PeriodStats_info=results[0].analyzers._PeriodStats.get_analysis()
#             average_rate=PeriodStats_info['average']
#             stddev_rate=PeriodStats_info['stddev']
#             positive_year=PeriodStats_info['positive']
#             negative_year=PeriodStats_info['negative']
#             nochange_year=PeriodStats_info['nochange']
#             best_year=PeriodStats_info['best']
#             worst_year=PeriodStats_info['worst']
#             sharpe_info=results[0].analyzers._SharpeRatio.get_analysis()
#             sharpe_ratio=sharpe_info['sharperatio']

#         except:
#             drawdown_info=np.nan
#             average_drawdown_len=np.nan
#             average_drawdown_rate=np.nan
#             average_drawdown_money=np.nan
#             max_drawdown_len=np.nan
#             max_drawdown_rate=np.nan
#             max_drawdown_money=np.nan
#             PeriodStats_info=np.nan
#             average_rate=np.nan
#             stddev_rate=np.nan
#             positive_year=np.nan
#             negative_year=np.nan
#             nochange_year=np.nan
#             best_year=np.nan
#             worst_year=np.nan
#             sharpe_info=np.nan
#             sharpe_ratio=np.nan
#         try:
#             calmar_ratio=list(results[0].analyzers._Calmar.get_analysis().values())[-1]
#             # print(calmar_ratio)
#             SQN_info=results[0].analyzers._SQN.get_analysis()
#             sqn_ratio=SQN_info['sqn']
#             VWR_info=results[0].analyzers._VWR.get_analysis()
#             vwr_ratio=VWR_info['vwr']
#         except:
#             calmar_ratio=np.nan
#             # print(calmar_ratio)
#             SQN_info=np.nan
#             sqn_ratio=np.nan
#             VWR_info=np.nan
#             vwr_ratio=np.nan
#         # sharpe_info=results[0].analyzers._SharpeRatio_A.get_analysis()
#         # Calculate three key indicators
#         df0=df1=pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
#         df0.columns=['total_value']
#         df0.to_csv("C:/result/"+strategy_name+params_str+"Slope strategy total account value.csv")
#         sharpe_ratio,average_rate,max_drawdown_rate = get_rate_sharpe_drawdown(df0)


#         performance_dict['calmar_ratio']=calmar_ratio
#         performance_dict['average_drawdown_len']=average_drawdown_len
#         performance_dict['average_drawdown_rate']=average_drawdown_rate
#         performance_dict['average_drawdown_money']=average_drawdown_money
#         performance_dict['max_drawdown_len']=max_drawdown_len
#         performance_dict['max_drawdown_rate']=max_drawdown_rate
#         performance_dict['max_drawdown_money']=max_drawdown_money
#         performance_dict['average_rate']=average_rate
#         performance_dict['stddev_rate']=stddev_rate
#         performance_dict['positive_year']=positive_year
#         performance_dict['negative_year']=negative_year
#         performance_dict['nochange_year']=nochange_year
#         performance_dict['best_year']=best_year
#         performance_dict['worst_year']=worst_year
#         performance_dict['sqn_ratio']=sqn_ratio
#         performance_dict['vwr_ratio']=vwr_ratio
#         performance_dict['sharpe_info']=sharpe_ratio
#         performance_dict['omega']=np.nan

#         trade_dict_1=OrderedDict()
#         trade_dict_2=OrderedDict()
#         try:
#             trade_info=results[0].analyzers._TradeAnalyzer.get_analysis()
#             total_trade_num=trade_info['total']['total']
#             total_trade_opened=trade_info['total']['open']
#             total_trade_closed=trade_info['total']['closed']
#             total_trade_len=trade_info['len']['total']
#             long_trade_len=trade_info['len']['long']['total']
#             short_trade_len=trade_info['len']['short']['total']
#         except:
#             total_trade_num=np.nan
#             total_trade_opened=np.nan
#             total_trade_closed=np.nan
#             total_trade_len=np.nan
#             long_trade_len=np.nan
#             short_trade_len=np.nan
#         try:
#             longest_win_num=trade_info['streak']['won']['longest']
#             longest_lost_num=trade_info['streak']['lost']['longest']
#             net_total_pnl=trade_info['pnl']['net']['total']
#             net_average_pnl=trade_info['pnl']['net']['average']
#             win_num=trade_info['won']['total']
#             win_total_pnl=trade_info['won']['pnl']['total']
#             win_average_pnl=trade_info['won']['pnl']['average']
#             win_max_pnl=trade_info['won']['pnl']['max']
#             lost_num=trade_info['lost']['total']
#             lost_total_pnl=trade_info['lost']['pnl']['total']
#             lost_average_pnl=trade_info['lost']['pnl']['average']
#             lost_max_pnl=trade_info['lost']['pnl']['max']
#         except:
#             longest_win_num=np.nan
#             longest_lost_num=np.nan
#             net_total_pnl=np.nan
#             net_average_pnl=np.nan
#             win_num=np.nan
#             win_total_pnl=np.nan
#             win_average_pnl=np.nan
#             win_max_pnl=np.nan
#             lost_num=np.nan
#             lost_total_pnl=np.nan
#             lost_average_pnl=np.nan
#             lost_max_pnl=np.nan

#         trade_dict_1['total_trade_num']=total_trade_num
#         trade_dict_1['total_trade_opened']=total_trade_opened
#         trade_dict_1['total_trade_closed']=total_trade_closed
#         trade_dict_1['total_trade_len']=total_trade_len
#         trade_dict_1['long_trade_len']=long_trade_len
#         trade_dict_1['short_trade_len']=short_trade_len
#         trade_dict_1['longest_win_num']=longest_win_num
#         trade_dict_1['longest_lost_num']=longest_lost_num
#         trade_dict_1['net_total_pnl']=net_total_pnl
#         trade_dict_1['net_average_pnl']=net_average_pnl
#         trade_dict_1['win_num']=win_num
#         trade_dict_1['win_total_pnl']=win_total_pnl
#         trade_dict_1['win_average_pnl']=win_average_pnl
#         trade_dict_1['win_max_pnl']=win_max_pnl
#         trade_dict_1['lost_num']=lost_num
#         trade_dict_1['lost_total_pnl']=lost_total_pnl
#         trade_dict_1['lost_average_pnl']=lost_average_pnl
#         trade_dict_1['lost_max_pnl']=lost_max_pnl

#         try:
#             long_num=trade_info['long']['total']
#             long_win_num=trade_info['long']['won']
#             long_lost_num=trade_info['long']['lost']
#             long_total_pnl=trade_info['long']['pnl']['total']
#             long_average_pnl=trade_info['long']['pnl']['average']
#             long_win_total_pnl=trade_info['long']['pnl']['won']['total']
#             long_win_max_pnl=trade_info['long']['pnl']['won']['max']
#             long_lost_total_pnl=trade_info['long']['pnl']['lost']['total']
#             long_lost_max_pnl=trade_info['long']['pnl']['lost']['max']

#             short_num=trade_info['short']['total']
#             short_win_num=trade_info['short']['won']
#             short_lost_num=trade_info['short']['lost']
#             short_total_pnl=trade_info['short']['pnl']['total']
#             short_average_pnl=trade_info['short']['pnl']['average']
#             short_win_total_pnl=trade_info['short']['pnl']['won']['total']
#             short_win_max_pnl=trade_info['short']['pnl']['won']['max']
#             short_lost_total_pnl=trade_info['short']['pnl']['lost']['total']
#             short_lost_max_pnl=trade_info['short']['pnl']['lost']['max']
#         except:
#             long_num=np.nan
#             long_win_num=np.nan
#             long_lost_num=np.nan
#             long_total_pnl=np.nan
#             long_average_pnl=np.nan
#             long_win_total_pnl=np.nan
#             long_win_max_pnl=np.nan
#             long_lost_total_pnl=np.nan
#             long_lost_max_pnl=np.nan

#             short_num=np.nan
#             short_win_num=np.nan
#             short_lost_num=np.nan
#             short_total_pnl=np.nan
#             short_average_pnl=np.nan
#             short_win_total_pnl=np.nan
#             short_win_max_pnl=np.nan
#             short_lost_total_pnl=np.nan
#             short_lost_max_pnl=np.nan


#         trade_dict_2['long_num']=long_num
#         trade_dict_2['long_win_num']=long_win_num
#         trade_dict_2['long_lost_num']=long_lost_num
#         trade_dict_2['long_total_pnl']=long_total_pnl
#         trade_dict_2['long_average_pnl']=long_average_pnl
#         trade_dict_2['long_win_total_pnl']=long_win_total_pnl
#         trade_dict_2['long_win_max_pnl']=long_win_max_pnl
#         trade_dict_2['long_lost_total_pnl']=long_lost_total_pnl
#         trade_dict_2['long_lost_max_pnl']=long_lost_max_pnl
#         trade_dict_2['short_num']=short_num
#         trade_dict_2['short_win_num']=short_win_num
#         trade_dict_2['short_lost_num']=short_lost_num
#         trade_dict_2['short_total_pnl']=short_total_pnl
#         trade_dict_2['short_average_pnl']=short_average_pnl
#         trade_dict_2['short_win_total_pnl']=short_win_total_pnl
#         trade_dict_2['short_win_max_pnl']=short_win_max_pnl
#         trade_dict_2['short_lost_total_pnl']=short_lost_total_pnl
#         trade_dict_2['short_lost_max_pnl']=short_lost_max_pnl


#         len(performance_dict)==len(trade_dict_2)==len(trade_dict_1)
#         df00=pd.DataFrame(index=range(18))
#         df01=pd.DataFrame([performance_dict]).T
#         df01.columns=['Performance indicator value']
#         df02=pd.DataFrame([trade_dict_1]).T
#         df02.columns=['General trading indicator value']
#         df03=pd.DataFrame([trade_dict_2]).T
#         df03.columns=['Long/short trading indicator value']
#         df00['Performance indicator']=df01.index
#         df00['Performance indicator value']=[round(float(i),4) for i in list(df01['Performance indicator value'])]
#         df00['General trading indicator']=df02.index
#         df00['General trading indicator value']=[round(float(i),4) for i in list(df02['General trading indicator value'])]
#         df00['Long/short trading indicator']=df03.index
#         df00['Long/short trading indicator value']=[round(float(i),4) for i in list(df03['Long/short trading indicator value'])]


#         if plot is True:

#             df00.to_csv(result_path+strategy.__name__+params_str+'.csv',encoding='gbk')

#             test_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#             # Account value
#             df0=df1=pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
#             df0.columns=['total_value']
#             df0.to_csv("C:/result/"+strategy_name+params_str+"Slope strategy total account value.csv")

#             # Total leverage
#             df1=pd.DataFrame([results[0].analyzers._GrossLeverage.get_analysis()]).T
#             df1.columns=['GrossLeverage']


#             # Rolling log returns
#             # df2=pd.DataFrame([results[0].analyzers._LogReturnsRolling.get_analysis()]).T
#             # df2.columns=['log_return']

#             # year_rate
#             df3=pd.DataFrame([results[0].analyzers._AnnualReturn.get_analysis()]).T
#             df3.columns=['year_rate']

#             # Total position value
#             df4=pd.DataFrame(results[0].analyzers._PositionsValue.get_analysis()).T
#             df4['total_position_value']=df4.sum(axis=1)

#             # Define table component


#             app = dash.Dash()
#             # app = JupyterDash('Strategy evaluation result')
#             # server = app.server
#             colors = dict(background = 'white', text = 'black')

#             app.layout = html.Div(
#                 style = dict(backgroundColor = colors['background']),
#                 children = [
#                     html.H1(
#                         children='Strategy evaluation result for {}'.format(strategy_name),
#                         style = dict(textAlign='center', color = colors['text'])),
#                     html.Div(
#                         children=f'Strategy author: {author} ___ Test time: {test_time} ___ Test score is: {score}',
#                         style = dict(textAlign = 'center', color = colors['text'])),

#                     dcc.Graph(
#                         id='Account value',
#                         figure = dict(
#                             data = [{'x': list(df0.index), 'y': list(df0.total_value),
#                                     #'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'scatter', 'name': 'Account value',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='Account value',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text'],
#                             )
#                             )
#                         )
#                     ),

#                     dcc.Graph(
#                         id='Position market value',
#                         figure = dict(
#                             data = [{'x': list(df4.index), 'y': list(df4.total_position_value),
#                                     #'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'scatter', 'name': 'Position market value',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='Position market value',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text']),
#                             )
#                         )
#                     ),
#                     dcc.Graph(
#                         id='Annualized return',
#                         figure = dict(
#                             data = [{'x': list(df3.index), 'y': list(df3.year_rate),
#                                     'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'bar', 'name': 'Annual return rate',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='Annualized return rate',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text']),
#                             )
#                         )
#                     ),
#                     create_table(df00)


#                 ]
#             )
#             app.run_server(port=port)
#             # app.run_server(debug=True, host='0.0.0.0')

#         else:

#             df00.to_csv(result_path+strategy.__name__+params_str+'.csv',encod
