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

from datetime import datetime
import itertools

from .. import feed, TimeFrame
from ..utils import date2num
from ..utils.py3 import integer_types, string_types


class GenericCSVData(feed.CSVDataBase):
    '''Parses a CSV file according to the order and field presence defined by the
    parameters

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - The lines parameters (datetime, open, high ...) take numeric values

        A value of -1 indicates absence of that field in the CSV source

      - If ``time`` is present (parameter time >=0) the source contains
        separated fields for date and time, which will be combined

      - ``nullvalue``

        Value that will be used if a value which should be there is missing
        (the CSV field is empty)

      - ``dtformat``: Format used to parse the datetime CSV field. See the
        python strptime/strftime documentation for the format.

        If a numeric value is specified, it will be interpreted as follows

          - ``1``: The value is a Unix timestamp of type ``int`` representing
            the number of seconds since Jan 1st, 1970

          - ``2``: The value is a Unix timestamp of type ``float``

        If a **callable** is passed

          - it will accept a string and return a `datetime.datetime` python
            instance

      - ``tmformat``: Format used to parse the time CSV field if "present"
        (the default for the "time" CSV field is not to be present)

    '''

    # csv data的一些常用的参数
    params = (
        ('nullvalue', float('NaN')),
        ('dtformat', '%Y-%m-%d %H:%M:%S'),
        ('tmformat', '%H:%M:%S'),

        ('datetime', 0),
        ('time', -1),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', 6),
    )

    # 开始，根据传入的日期参数确定转换的方法
    def start(self):
        super(GenericCSVData, self).start()
        # 如果是字符串类型，就把self._dtstr设置成True,否则就是默认的False
        self._dtstr = False
        if isinstance(self.p.dtformat, string_types):
            self._dtstr = True
        # 如果是整数，那么就根据整数的不同，设置时间转换方法
        elif isinstance(self.p.dtformat, integer_types):
            idt = int(self.p.dtformat)
            if idt == 1:
                self._dtconvert = lambda x: datetime.utcfromtimestamp(int(x))
            elif idt == 2:
                self._dtconvert = lambda x: datetime.utcfromtimestamp(float(x))
        # 如果dtformat是可以调用的，转换方法就是它本身
        else:  # assume callable
            self._dtconvert = self.p.dtformat

    # 读取csv文件的line之后，把line的每个数据分割开来做成linetokens之后，进一步的处理
    def _loadline(self, linetokens):
        # Datetime needs special treatment
        # 首先根据datetime出现的顺序，取得具体的日期
        dtfield = linetokens[self.p.datetime]
        # 如果时间是字符串格式
        if self._dtstr:
            # 具体的时间格式
            dtformat = self.p.dtformat
            # 如果有time这个列，就把日期和时间结合到一起
            if self.p.time >= 0:
                # add time value and format if it's in a separate field
                dtfield += 'T' + linetokens[self.p.time]
                dtformat += 'T' + self.p.tmformat
            # 然后把字符串时间转化为datetime格式的时间
            dt = datetime.strptime(dtfield, dtformat)
        # 如果不是字符串，就调用start的时候设置好的时间转化函数_dtconvert
        else:
            dt = self._dtconvert(dtfield)
        # 如果交易的时间间隔大于等于日
        if self.p.timeframe >= TimeFrame.Days:
            # check if the expected end of session is larger than parsed
            # 如果_tzinput是真的话，需要把日期做本地化处理，如果不是，日期还是原来的
            if self._tzinput:
                dtin = self._tzinput.localize(dt)  # pytz compatible-ized
            else:
                dtin = dt
            # 使用date2num把日期转化成数字
            dtnum = date2num(dtin)  # utc'ize
            # 把日期和sessionend结合起来，并转化成数字
            dteos = datetime.combine(dt.date(), self.p.sessionend)
            dteosnum = self.date2num(dteos)  # utc'ize
            # 如果结合sessionend的日期转化成的数字大于日期转化后的数字，用前面的数字作为时间
            if dteosnum > dtnum:
                self.lines.datetime[0] = dteosnum
            # 如果不大于的话，如果self._tzinput是真的，那么就直接把dt转化成时间，如果不是真的，就使用原先的dtnum                                   
            else:
                # Avoid reconversion if already converted dtin == dt
                self.l.datetime[0] = date2num(dt) if self._tzinput else dtnum
        # 如果交易周期小于日，那么时间就直接转化
        else:
            self.lines.datetime[0] = date2num(dt)

        # The rest of the fields can be done with the same procedure
        # 剩下的其他的数据可以按照同样的方法去操作，循环不是datetime的列
        for linefield in (x for x in self.getlinealiases() if x != 'datetime'):
            # Get the index created from the passed params
            # 获取这个列名称的index
            csvidx = getattr(self.params, linefield)
            # 如果这个列的index是None或者小于0,代表数据是空的，设置成NAN
            if csvidx is None or csvidx < 0:
                # the field will not be present, assignt the "nullvalue"
                csvfield = self.p.nullvalue
            # 否则直接从linetokens中获取
            else:
                # get it from the token
                csvfield = linetokens[csvidx]
            # 如果获取到的数据是空的字符串，把数据设置成NAN
            if csvfield == '':
                # if empty ... assign the "nullvalue"
                csvfield = self.p.nullvalue
            # 获取这个列对应的line，然后设置value,没有太明白为什么使用两个float转化一个值，暂且认为是低效的，修改下
            # get the corresponding line reference and set the value
            line = getattr(self.lines, linefield)
            # line[0] = float(float(csvfield))  # backtrader自带
            line[0] = float(csvfield)

        return True


class GenericCSV(feed.CSVFeedBase):
    # 类，增加一个属性DataCls，把这个属性值设置成GenericCSVData
    DataCls = GenericCSVData
