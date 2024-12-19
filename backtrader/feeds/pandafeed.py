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

from backtrader.utils.py3 import filter, string_types, integer_types

from backtrader import date2num
import backtrader.feed as feed

# backtrader通过pandas加载数据
class PandasDirectData(feed.DataBase):
    '''
    Uses a Pandas DataFrame as the feed source, iterating directly over the
    tuples returned by "itertuples".

    This means that all parameters related to lines must have numeric
    values as indices into the tuples

    Note:

      - The ``dataname`` parameter is a Pandas DataFrame

      - A negative value in any of the parameters for the Data lines
        indicates it's not present in the DataFrame
        it is
    '''
    # 参数
    params = (
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', 6),
    )
    # 列名
    datafields = [
        'datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest'
    ]
    # 开始，把dataframe数据转化成可以迭代的元组，每一行一个元组
    def start(self):
        super(PandasDirectData, self).start()

        # reset the iterator on each start
        self._rows = self.p.dataname.itertuples()

    def _load(self):
        # 尝试获取下一个row，如果获取不到报错，就返回False
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        # Set the standard datafields - except for datetime
        # 对于除了datetime之外的列，把数据根据列名添加到line中
        for datafield in self.getlinealiases():
            if datafield == 'datetime':
                continue

            # get the column index
            colidx = getattr(self.params, datafield)

            if colidx < 0:
                # column not present -- skip
                continue

            # get the line to be set
            line = getattr(self.lines, datafield)
            # print(colidx,datafield,row)
            # indexing for pandas: 1st is colum, then row
            line[0] = row[colidx]

        # datetime
        # 对于datetime，获取datetime所在列的index,然后获取时间
        colidx = getattr(self.params, 'datetime')
        tstamp = row[colidx]

        # convert to float via datetime and store it
        # 把时间戳转化成具体的datetime格式，然后转化成数字
        dt = tstamp.to_pydatetime()
        dtnum = date2num(dt)

        # get the line to be set
        # 获取datetime的line，然后保存这个数字
        line = getattr(self.lines, 'datetime')
        line[0] = dtnum

        # Done ... return
        return True


class PandasData(feed.DataBase):
    '''
    Uses a Pandas DataFrame as the feed source, using indices into column
    names (which can be "numeric")

    This means that all parameters related to lines must have numeric
    values as indices into the tuples

    Params:

      - ``nocase`` (default *True*) case insensitive match of column names

    Note:

      - The ``dataname`` parameter is a Pandas DataFrame

      - Values possible for datetime

        - None: the index contains the datetime
        - -1: no index, autodetect column
        - >= 0 or string: specific colum identifier

      - For other lines parameters

        - None: column not present
        - -1: autodetect
        - >= 0 or string: specific colum identifier
    '''
    # 参数及其含义
    params = (
        ('nocase', True),

        # Possible values for datetime (must always be present)
        #  None : datetime is the "index" in the Pandas Dataframe
        #  -1 : autodetect position or case-wise equal name
        #  >= 0 : numeric index to the colum in the pandas dataframe
        #  string : column name (as index) in the pandas dataframe
        ('datetime', None),

        # Possible values below:
        #  None : column not present
        #  -1 : autodetect position or case-wise equal name
        #  >= 0 : numeric index to the colum in the pandas dataframe
        #  string : column name (as index) in the pandas dataframe
        ('open', -1),
        ('high', -1),
        ('low', -1),
        ('close', -1),
        ('volume', -1),
        ('openinterest', -1),
    )
    # 数据的列名
    datafields = [
        'datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest'
    ]

    # 类初始化
    def __init__(self):
        super(PandasData, self).__init__()

        # these "colnames" can be strings or numeric types
        # 列的名字，列表格式
        colnames = list(self.p.dataname.columns.values)
        # 如果datetime在index中
        if self.p.datetime is None:
            # datetime is expected as index col and hence not returned
            pass

        # try to autodetect if all columns are numeric
        # 尝试判断cstrings是不是字符串，把不是字符串的过滤掉
        cstrings = filter(lambda x: isinstance(x, string_types), colnames)
        # 如果有一个是字符串，那么colsnumeric就是False，只有全部是数字的情况下，才会返回True
        colsnumeric = not len(list(cstrings))

        # Where each datafield find its value
        # 定义一个字典
        self._colmapping = dict()

        # Build the column mappings to internal fields in advance
        # 遍历每个列
        for datafield in self.getlinealiases():
            # 列所在的index
            defmapping = getattr(self.params, datafield)
            # 如果列的index是数字并且小于0,需要自动探测
            if isinstance(defmapping, integer_types) and defmapping < 0:
                # autodetection requested
                for colname in colnames:
                    # 如果列名是字符串
                    if isinstance(colname, string_types):
                        # 如果没有大小写的区别，对比小写状态是否相等，如果相等就代表找到了，否则就直接对比是否相等
                        if self.p.nocase:
                            found = datafield.lower() == colname.lower()
                        else:
                            found = datafield == colname
                        # 如果找到了，那么就把datafield和colname进行一一对应，然后退出这个循环，继续datafield
                        if found:
                            self._colmapping[datafield] = colname
                            break
                # 如果找了一遍df的列没有找到，就设置成None
                if datafield not in self._colmapping:
                    # autodetection requested and not found
                    self._colmapping[datafield] = None
                    continue
                
            # 如果datafield用户自己进行了定义，那么就直接使用用户定义的
            else:
                # all other cases -- used given index
                self._colmapping[datafield] = defmapping
    # 开始处理数据
    def start(self):
        super(PandasData, self).start()
        # 开始之前，先重新设置_idx
        # reset the length with each start
        self._idx = -1

        # Transform names (valid for .ix) into indices (good for .iloc)
        # 如果大小写不敏感，就把数据的列名转化成小写，如果敏感，保持原样
        if self.p.nocase:
            colnames = [x.lower() for x in self.p.dataname.columns.values]
        else:
            colnames = [x for x in self.p.dataname.columns.values]

        # 对于datafield和列名进行迭代
        for k, v in self._colmapping.items():
            # 如果列名是None的话，代表这个列很可能是时间
            if v is None:
                continue  # special marker for datetime
            # 如果列名是字符串的话，如果大小写不敏感，就先转化成小写，如果不敏感，忽略，然后根据列名得到列所在的index
            
            if isinstance(v, string_types):
                # 这下面的一些代码似乎有些无效，感觉可以忽略，直接使用self._colmapping[k] = colnames.index(v)替代就好了
                try:
                    if self.p.nocase:
                        v = colnames.index(v.lower())
                    else:
                        v = colnames.index(v)
                except ValueError as e:
                    defmap = getattr(self.params, k)
                    if isinstance(defmap, integer_types) and defmap < 0:
                        v = None
                    else:
                        raise e  # let user now something failed
            # 如果不是字符串，用户自定义了具体的整数，直接使用用户自定义的
            self._colmapping[k] = v

    def _load(self):
        # 每次load一行，_idx每次加1
        self._idx += 1
        # 如果_idx已经大于了数据的长度，返回False
        if self._idx >= len(self.p.dataname):
            # exhausted all rows
            return False

        # Set the standard datafields
        # 循环datafield
        for datafield in self.getlinealiases():
            # 如果是时间，继续上面的循环
            if datafield == 'datetime':
                continue

            colindex = self._colmapping[datafield]
            # 如果列的index是None，继续上面的循环
            if colindex is None:
                # datafield signaled as missing in the stream: skip it
                continue

            # get the line to be set
            line = getattr(self.lines, datafield)

            # indexing for pandas: 1st is colum, then row
            # 使用iloc读取dataframe的数据，感觉效率一般
            line[0] = self.p.dataname.iloc[self._idx, colindex]

        # datetime conversion
        coldtime = self._colmapping['datetime']
        # 如果datetime所在的列是None的话，直接通过index获取时间，如果不是None的话，通过iloc获取时间数据
        if coldtime is None:
            # standard index in the datetime
            tstamp = self.p.dataname.index[self._idx]
        else:
            # it's in a different column ... use standard column index
            tstamp = self.p.dataname.iloc[self._idx, coldtime]

        # convert to float via datetime and store it
        # 转换时间数据并保存
        dt = tstamp.to_pydatetime()
        dtnum = date2num(dt)
        self.lines.datetime[0] = dtnum

        # Done ... return
        return True
