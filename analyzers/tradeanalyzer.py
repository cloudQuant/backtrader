#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys

from backtrader import Analyzer
from backtrader.utils import AutoOrderedDict, AutoDict
from backtrader.utils.py3 import MAXINT

# 分析交易
class TradeAnalyzer(Analyzer):
    '''
    Provides statistics on closed trades (keeps also the count of open ones)

      - Total Open/Closed Trades

      - Streak Won/Lost Current/Longest

      - ProfitAndLoss Total/Average

      - Won/Lost Count/ Total PNL/ Average PNL / Max PNL

      - Long/Short Count/ Total PNL / Average PNL / Max PNL

          - Won/Lost Count/ Total PNL/ Average PNL / Max PNL

      - Length (bars in the market)

        - Total/Average/Max/Min

        - Won/Lost Total/Average/Max/Min

        - Long/Short Total/Average/Max/Min

          - Won/Lost Total/Average/Max/Min

    Note:

      The analyzer uses an "auto"dict for the fields, which means that if no
      trades are executed, no statistics will be generated.

      In that case there will be a single field/subfield in the dictionary
      returned by ``get_analysis``, namely:

        - dictname['total']['total'] which will have a value of 0 (the field is
          also reachable with dot notation dictname.total.total
    '''
    # 创建分析
    def create_analysis(self):
        self.rets = AutoOrderedDict()
        self.rets.total.total = 0
    # 停止
    def stop(self):
        super(TradeAnalyzer, self).stop()
        self.rets._close()

    # trade通知
    def notify_trade(self, trade):
        # 如果trade是刚开
        if trade.justopened:
            # Trade just opened
            self.rets.total.total += 1
            self.rets.total.open += 1
        # 如果trade是关闭
        elif trade.status == trade.Closed:
            trades = self.rets

            res = AutoDict()
            # Trade just closed
            # 盈利
            won = res.won = int(trade.pnlcomm >= 0.0)
            # 亏损
            lost = res.lost = int(not won)
            # 多头
            tlong = res.tlong = trade.long
            # 空头
            tshort = res.tshort = not trade.long
            # 开仓的交易
            trades.total.open -= 1
            # 关闭的交易
            trades.total.closed += 1

            # Streak
            # 计算连续盈利和亏损次数
            for wlname in ['won', 'lost']:
                # 当前盈亏状况
                wl = res[wlname]
                # 当前连续盈利或者亏损次数
                trades.streak[wlname].current *= wl
                trades.streak[wlname].current += wl
                # 获取最大连续盈利或者亏损的次数
                ls = trades.streak[wlname].longest or 0
                # 重新计算
                trades.streak[wlname].longest = \
                    max(ls, trades.streak[wlname].current)
            # 交易的盈亏
            trpnl = trades.pnl
            # 交易总盈亏
            trpnl.gross.total += trade.pnl
            # 平均盈亏
            trpnl.gross.average = trades.pnl.gross.total / trades.total.closed
            # 交易净盈亏
            trpnl.net.total += trade.pnlcomm
            # 平均净盈亏
            trpnl.net.average = trades.pnl.net.total / trades.total.closed

            # Won/Lost statistics
            # 盈亏统计
            for wlname in ['won', 'lost']:
                # 当前盈亏
                wl = res[wlname]
                # 历史盈亏
                trwl = trades[wlname]
                # 盈亏次数
                trwl.total += wl  # won.total / lost.total
                # 总的盈亏和平均盈亏
                trwlpnl = trwl.pnl
                pnlcomm = trade.pnlcomm * wl

                trwlpnl.total += pnlcomm
                trwlpnl.average = trwlpnl.total / (trwl.total or 1.0)
                # 最大盈利或者最小的亏损(亏得最多的一笔)
                wm = trwlpnl.max or 0.0
                func = max if wlname == 'won' else min
                trwlpnl.max = func(wm, pnlcomm)

            # Long/Short statistics
            # 多空的统计
            for tname in ['long', 'short']:
                # 多和空
                trls = trades[tname]
                # 当前交易的多和空
                ls = res['t' + tname]
                # 计算多和空的次数
                trls.total += ls  # long.total / short.total
                # 计算多和空的总的pnl
                trls.pnl.total += trade.pnlcomm * ls
                # 计算多和空的平均盈利
                trls.pnl.average = trls.pnl.total / (trls.total or 1.0)
                # 分析多、空的盈亏状况
                for wlname in ['won', 'lost']:
                    wl = res[wlname]
                    pnlcomm = trade.pnlcomm * wl * ls

                    trls[wlname] += wl * ls  # long.won / short.won

                    trls.pnl[wlname].total += pnlcomm
                    trls.pnl[wlname].average = \
                        trls.pnl[wlname].total / (trls[wlname] or 1.0)

                    wm = trls.pnl[wlname].max or 0.0
                    func = max if wlname == 'won' else min
                    trls.pnl[wlname].max = func(wm, pnlcomm)

            # Length
            # 交易占的bar的个数
            trades.len.total += trade.barlen
            # 平均每个交易占的bar的个数
            trades.len.average = trades.len.total / trades.total.closed
            # 交易最长占的bar的个数
            ml = trades.len.max or 0
            trades.len.max = max(ml, trade.barlen)
            # 交易最短占的bar的个数
            ml = trades.len.min or MAXINT
            trades.len.min = min(ml, trade.barlen)

            # Length Won/Lost
            # 盈亏交易占的bar的个数，和上面类似，只是分了盈利和亏损
            for wlname in ['won', 'lost']:
                trwl = trades.len[wlname]
                wl = res[wlname]

                trwl.total += trade.barlen * wl
                trwl.average = trwl.total / (trades[wlname].total or 1.0)

                m = trwl.max or 0
                trwl.max = max(m, trade.barlen * wl)
                if trade.barlen * wl:
                    m = trwl.min or MAXINT
                    trwl.min = min(m, trade.barlen * wl)

            # Length Long/Short
            # 区分多和空的长度
            for lsname in ['long', 'short']:
                trls = trades.len[lsname]  # trades.len.long
                ls = res['t' + lsname]  # tlong/tshort

                barlen = trade.barlen * ls

                trls.total += barlen  # trades.len.long.total
                total_ls = trades[lsname].total   # trades.long.total
                trls.average = trls.total / (total_ls or 1.0)

                # max/min
                m = trls.max or 0
                trls.max = max(m, barlen)
                m = trls.min or MAXINT
                trls.min = min(m, barlen or m)
                # 区分多和空下盈利和亏损的长度
                for wlname in ['won', 'lost']:
                    wl = res[wlname]  # won/lost

                    barlen2 = trade.barlen * ls * wl

                    trls_wl = trls[wlname]  # trades.len.long.won
                    trls_wl.total += barlen2  # trades.len.long.won.total

                    trls_wl.average = \
                        trls_wl.total / (trades[lsname][wlname] or 1.0)

                    # max/min
                    m = trls_wl.max or 0
                    trls_wl.max = max(m, barlen2)
                    m = trls_wl.min or MAXINT
                    trls_wl.min = min(m, barlen2 or m)
