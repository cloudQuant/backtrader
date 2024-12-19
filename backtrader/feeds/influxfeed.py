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

import backtrader as bt
import backtrader.feed as feed
from ..utils import date2num
import datetime as dt

# 时间周期的对应
TIMEFRAMES = dict(
    (
        (bt.TimeFrame.Seconds, 's'),
        (bt.TimeFrame.Minutes, 'm'),
        (bt.TimeFrame.Days, 'd'),
        (bt.TimeFrame.Weeks, 'w'),
        (bt.TimeFrame.Months, 'm'),
        (bt.TimeFrame.Years, 'y'),
    )
)


# backtrader从influxDB获取数据
class InfluxDB(feed.DataBase):
    # 导入包
    frompackages = (
        ('influxdb', [('InfluxDBClient', 'idbclient')]),
        ('influxdb.exceptions', 'InfluxDBClientError')
    )
    # 参数
    params = (
        ('host', '127.0.0.1'),
        ('port', '8086'),
        ('username', None),
        ('password', None),
        ('database', None),
        ('timeframe', bt.TimeFrame.Days),
        ('startdate', None),
        ('high', 'high_p'),
        ('low', 'low_p'),
        ('open', 'open_p'),
        ('close', 'close_p'),
        ('volume', 'volume'),
        ('ointerest', 'oi'),
    )

    # 开始
    def start(self):
        super(InfluxDB, self).start()
        # 尝试连接数据库
        try:
            self.ndb = idbclient(self.p.host, self.p.port, self.p.username,
                                 self.p.password, self.p.database)
        except InfluxDBClientError as err:
            print('Failed to establish connection to InfluxDB: %s' % err)
        # 具体的时间周期                                                                                    
        tf = '{multiple}{timeframe}'.format(
            multiple=(self.p.compression if self.p.compression else 1),
            timeframe=TIMEFRAMES.get(self.p.timeframe, 'd'))
        # 开始时间
        if not self.p.startdate:
            st = '<= now()'
        else:
            st = '>= \'%s\'' % self.p.startdate

        # The query could already consider parameters like fromdate and todate
        # to have the database skip them and not the internal code
        # 具体的数据库获取数据需要设置的命令
        qstr = ('SELECT mean("{open_f}") AS "open", mean("{high_f}") AS "high", '
                'mean("{low_f}") AS "low", mean("{close_f}") AS "close", '
                'mean("{vol_f}") AS "volume", mean("{oi_f}") AS "openinterest" '
                'FROM "{dataname}" '
                'WHERE time {begin} '
                'GROUP BY time({timeframe}) fill(none)').format(
                    open_f=self.p.open, high_f=self.p.high,
                    low_f=self.p.low, close_f=self.p.close,
                    vol_f=self.p.volume, oi_f=self.p.ointerest,
                    timeframe=tf, begin=st, dataname=self.p.dataname)
        # 获取数据
        try:
            dbars = list(self.ndb.query(qstr).get_points())
        except InfluxDBClientError as err:
            print('InfluxDB query failed: %s' % err)
        # 迭代数据
        self.biter = iter(dbars)

    def _load(self):
        # 尝试获取下个bar的数据，然后添加到line中
        try:
            bar = next(self.biter)
        except StopIteration:
            return False

        self.l.datetime[0] = date2num(dt.datetime.strptime(bar['time'],
                                                           '%Y-%m-%dT%H:%M:%SZ'))

        self.l.open[0] = bar['open']
        self.l.high[0] = bar['high']
        self.l.low[0] = bar['low']
        self.l.close[0] = bar['close']
        self.l.volume[0] = bar['volume']

        return True
