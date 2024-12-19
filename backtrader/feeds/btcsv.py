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

from datetime import date, datetime, time

from .. import feed
from ..utils import date2num

# 解析一个自定义的csv data，主要用于测试使用。
class BacktraderCSVData(feed.CSVDataBase):
    '''
    Parses a self-defined CSV Data used for testing.

    Specific parameters:

      - ``dataname``: The filename to parse or a file-like object
    '''
    # 对每行数据进行处理
    def _loadline(self, linetokens):
        # 把每行数据进行迭代
        itoken = iter(linetokens)
        # 时间处理
        dttxt = next(itoken)  # Format is YYYY-MM-DD - skip char 4 and 7
        dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
        # 如果列有8个，代表存在时间，第二列是时间，对时间进行处理，如果不是8列，代表没有时间，时间是用sessionend
        if len(linetokens) == 8:
            tmtxt = next(itoken)  # Format if present HH:MM:SS, skip 3 and 6
            tm = time(int(tmtxt[0:2]), int(tmtxt[3:5]), int(tmtxt[6:8]))
        else:
            tm = self.p.sessionend  # end of the session parameter
        # 分别设置各个line
        self.lines.datetime[0] = date2num(datetime.combine(dt, tm))
        self.lines.open[0] = float(next(itoken))
        self.lines.high[0] = float(next(itoken))
        self.lines.low[0] = float(next(itoken))
        self.lines.close[0] = float(next(itoken))
        self.lines.volume[0] = float(next(itoken))
        self.lines.openinterest[0] = float(next(itoken))

        return True


class BacktraderCSV(feed.CSVFeedBase):
    # 类，DataCls设置了值为BacktraderCSVData类
    DataCls = BacktraderCSVData
