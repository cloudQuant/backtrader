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

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

import sys

import backtrader as bt
from backtrader.utils.py3 import with_metaclass

# 如果import talib正常，运行else下面的代码，否则，运行except下面的代码
try:
    import talib
except ImportError:
    __all__ = []  # talib is not available
else:
    import numpy as np  # talib dependency
    import talib.abstract

    # MA_Type
    MA_Type = talib.MA_Type

    # Reverse TA_FUNC_FLAGS dict
    # 把TA_FUNC_FLAGS字典进行反转
    R_TA_FUNC_FLAGS = dict(
        zip(talib.abstract.TA_FUNC_FLAGS.values(),
            talib.abstract.TA_FUNC_FLAGS.keys()))

    FUNC_FLAGS_SAMESCALE = 16777216
    FUNC_FLAGS_UNSTABLE = 134217728
    FUNC_FLAGS_CANDLESTICK = 268435456
    # 把TA_OUTPUT_FLAGS字典进行反转
    R_TA_OUTPUT_FLAGS = dict(
        zip(talib.abstract.TA_OUTPUT_FLAGS.values(),
            talib.abstract.TA_OUTPUT_FLAGS.keys()))

    OUT_FLAGS_LINE = 1
    OUT_FLAGS_DOTTED = 2
    OUT_FLAGS_DASH = 4
    OUT_FLAGS_HISTO = 16
    OUT_FLAGS_UPPER = 2048
    OUT_FLAGS_LOWER = 4096

    # Generate all indicators as subclasses
    # talib指标元类
    class _MetaTALibIndicator(bt.Indicator.__class__):
        # 名字
        _refname = '_taindcol'
        # 指标列
        _taindcol = dict()

        _KNOWN_UNSTABLE = ['SAR']
        # postinit
        def dopostinit(cls, _obj, *args, **kwargs):
            # Go to parent
            # todo 省略了res,结果一样，表达更简洁
            _obj, args, kwargs = super(_MetaTALibIndicator, cls).dopostinit(_obj, *args, **kwargs)
            # res = super(_MetaTALibIndicator, cls).dopostinit(_obj,
            #                                                  *args, **kwargs)
            # _obj, args, kwargs = res

            # Get the minimum period by using the abstract interface and params
            # 通过抽象的接口和参数，获取需要的最小周期
            _obj._tabstract.set_function_args(**_obj.p._getkwargs())
            _obj._lookback = lookback = _obj._tabstract.lookback + 1
            _obj.updateminperiod(lookback)
            if _obj._unstable:
                _obj._lookback = 0

            elif cls.__name__ in cls._KNOWN_UNSTABLE:
                _obj._lookback = 0
            # findowner用于发现_obj的父类，但是是bt.Cerebro的实例
            cerebro = bt.metabase.findowner(_obj, bt.Cerebro)
            tafuncinfo = _obj._tabstract.info
            _obj._tafunc = getattr(talib, tafuncinfo['name'], None)
            return _obj, args, kwargs  # return the object and args

    # talib指标类
    class _TALibIndicator(with_metaclass(_MetaTALibIndicator, bt.Indicator)):
        CANDLEOVER = 1.02  # 2% over
        CANDLEREF = 1  # Open, High, Low, Close (0, 1, 2, 3)

        # 类方法
        @classmethod
        def _subclass(cls, name):
            # Module where the class has to end (namely this one)
            # 类模块
            clsmodule = sys.modules[cls.__module__]

            # Create an abstract interface to get lines names
            # 通过抽象接口获取line的名字
            _tabstract = talib.abstract.Function(name)
            # Variables about the  info learnt from func_flags
            iscandle = False
            unstable = False

            # Prepare plotinfo
            # 准备画图信息
            plotinfo = dict()
            fflags = _tabstract.function_flags or []
            for fflag in fflags:
                rfflag = R_TA_FUNC_FLAGS[fflag]
                if rfflag == FUNC_FLAGS_SAMESCALE:
                    plotinfo['subplot'] = False
                elif rfflag == FUNC_FLAGS_UNSTABLE:
                    unstable = True
                elif rfflag == FUNC_FLAGS_CANDLESTICK:
                    plotinfo['subplot'] = False
                    plotinfo['plotlinelabels'] = True
                    iscandle = True

            # Prepare plotlines
            # 准备画图的line
            lines = _tabstract.output_names
            output_flags = _tabstract.output_flags
            plotlines = dict()
            samecolor = False
            for lname in lines:
                oflags = output_flags.get(lname, None)
                pline = dict()
                for oflag in oflags or []:
                    orflag = R_TA_OUTPUT_FLAGS[oflag]
                    if orflag & OUT_FLAGS_LINE:
                        if not iscandle:
                            pline['ls'] = '-'
                        else:
                            pline['_plotskip'] = True  # do not plot candles

                    elif orflag & OUT_FLAGS_DASH:
                        pline['ls'] = '--'
                    elif orflag & OUT_FLAGS_DOTTED:
                        pline['ls'] = ':'
                    elif orflag & OUT_FLAGS_HISTO:
                        pline['_method'] = 'bar'

                    if samecolor:
                        pline['_samecolor'] = True

                    if orflag & OUT_FLAGS_LOWER:
                        samecolor = False

                    elif orflag & OUT_FLAGS_UPPER:
                        samecolor = True  # last: other values in loop are seen

                if pline:  # the dict has something
                    plotlines[lname] = pline
            # 如果是K线
            if iscandle:
                # This is the line that will be plotted when the output of the
                # indicator is a candle. The values of a candle (100) will be
                # used to plot a sign above the maximum of the bar which
                # produces the candle
                pline = dict()
                pline['_name'] = name  # plotted name
                lname = '_candleplot'  # change name
                lines.append(lname)
                pline['ls'] = ''
                pline['marker'] = 'd'
                pline['markersize'] = '7.0'
                pline['fillstyle'] = 'full'
                plotlines[lname] = pline

            # Prepare dictionary for subclassing
            # 准备创建子类的字典
            clsdict = {
                '__module__': cls.__module__,
                '__doc__': str(_tabstract),
                '_tabstract': _tabstract,  # keep ref for lookback calcs
                '_iscandle': iscandle,
                '_unstable': unstable,
                'params': _tabstract.get_parameters(),
                'lines': tuple(lines),
                'plotinfo': plotinfo,
                'plotlines': plotlines,
            }
            newcls = type(str(name), (cls,), clsdict)  # subclass
            setattr(clsmodule, str(name), newcls)  # add to module

        # oncestart
        def oncestart(self, start, end):
            pass  # if not ... a call with a single value to once will happen

        # 运行一次
        def once(self, start, end):
            import array

            # prepare the data arrays - single shot
            narrays = [np.array(x.lines[0].array) for x in self.datas]
            # Execute
            output = self._tafunc(*narrays, **self.p._getkwargs())

            fsize = self.size()
            lsize = fsize - self._iscandle
            if lsize == 1:  # only 1 output, no tuple returned
                self.lines[0].array = array.array(str('d'), output)

                if fsize > lsize:  # candle is present
                    candleref = narrays[self.CANDLEREF] * self.CANDLEOVER
                    output2 = candleref * (output / 100.0)
                    self.lines[1].array = array.array(str('d'), output2)

            else:
                for i, o in enumerate(output):
                    self.lines[i].array = array.array(str('d'), o)
        # 每个bar运行
        def next(self):
            # prepare the data arrays - single shot
            size = self._lookback or len(self)
            narrays = [np.array(x.lines[0].get(size=size)) for x in self.datas]

            out = self._tafunc(*narrays, **self.p._getkwargs())

            fsize = self.size()
            lsize = fsize - self._iscandle
            if lsize == 1:  # only 1 output, no tuple returned
                self.lines[0][0] = o = out[-1]

                if fsize > lsize:  # candle is present
                    candleref = narrays[self.CANDLEREF][-1] * self.CANDLEOVER
                    o2 = candleref * (o / 100.0)
                    self.lines[1][0] = o2

            else:
                for i, o in enumerate(out):
                    self.lines[i][0] = o[-1]

    # When importing the module do an automatic declaration of thed
    tafunctions = talib.get_functions()
    for tafunc in tafunctions:
        _TALibIndicator._subclass(tafunc)

    __all__ = tafunctions + ['MA_Type', '_TALibIndicator']
