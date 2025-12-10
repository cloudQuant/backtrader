#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

import sys

import backtrader as bt

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
        zip(talib.abstract.TA_FUNC_FLAGS.values(), talib.abstract.TA_FUNC_FLAGS.keys())
    )

    FUNC_FLAGS_SAMESCALE = 16777216
    FUNC_FLAGS_UNSTABLE = 134217728
    FUNC_FLAGS_CANDLESTICK = 268435456
    # 把TA_OUTPUT_FLAGS字典进行反转
    R_TA_OUTPUT_FLAGS = dict(
        zip(talib.abstract.TA_OUTPUT_FLAGS.values(), talib.abstract.TA_OUTPUT_FLAGS.keys())
    )

    OUT_FLAGS_LINE = 1
    OUT_FLAGS_DOTTED = 2
    OUT_FLAGS_DASH = 4
    OUT_FLAGS_HISTO = 16
    OUT_FLAGS_UPPER = 2048
    OUT_FLAGS_LOWER = 4096

    # talib指标基类 - 去掉元类，改用普通继承
    class _TALibIndicator(bt.Indicator):
        CANDLEOVER = 1.02  # 2% over
        CANDLEREF = 1  # Open, High, Low, Close (0, 1, 2, 3)

        _KNOWN_UNSTABLE = ["SAR"]

        def __init__(self, *args, **kwargs):
            # 首先调用父类的初始化
            super(_TALibIndicator, self).__init__(*args, **kwargs)

            # 执行原来在 dopostinit 中的逻辑
            self._init_talib_indicator()

        def _init_talib_indicator(self):
            """初始化 TALib 指标的特定设置"""
            # Get the minimum period by using the abstract interface and params
            # 通过抽象的接口和参数，获取需要的最小周期
            if hasattr(self, "_tabstract"):
                self._tabstract.set_function_args(**self.p._getkwargs())
                self._lookback = lookback = self._tabstract.lookback + 1
                self.updateminperiod(lookback)
                if getattr(self, "_unstable", False):
                    self._lookback = 0
                elif self.__class__.__name__ in self._KNOWN_UNSTABLE:
                    self._lookback = 0

                # findowner用于发现_obj的父类，但是是bt.Cerebro的实例
                # cerebro = bt.metabase.findowner(self, bt.Cerebro)
                tafuncinfo = self._tabstract.info
                self._tafunc = getattr(talib, tafuncinfo["name"], None)

        # 类方法
        @classmethod
        def _subclass(cls, name):
            # Module where the class has to end (namely this one)
            # 类模块
            clsmodule = sys.modules[cls.__module__]

            # Create an abstract interface to get lines names
            # 通过抽象接口获取line的名字
            _tabstract = talib.abstract.Function(name)
            # Variables about the info learnt from func_flags
            iscandle = False
            unstable = False

            # Prepare plotinfo
            # 准备画图信息
            plotinfo = dict()
            fflags = _tabstract.function_flags or []
            for fflag in fflags:
                rfflag = R_TA_FUNC_FLAGS[fflag]
                if rfflag == FUNC_FLAGS_SAMESCALE:
                    plotinfo["subplot"] = False
                elif rfflag == FUNC_FLAGS_UNSTABLE:
                    unstable = True
                elif rfflag == FUNC_FLAGS_CANDLESTICK:
                    plotinfo["subplot"] = False
                    plotinfo["plotlinelabels"] = True
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
                            pline["ls"] = "-"
                        else:
                            pline["_plotskip"] = True  # do not plot candles

                    elif orflag & OUT_FLAGS_DASH:
                        pline["ls"] = "--"
                    elif orflag & OUT_FLAGS_DOTTED:
                        pline["ls"] = ":"
                    elif orflag & OUT_FLAGS_HISTO:
                        pline["_method"] = "bar"

                    if samecolor:
                        pline["_samecolor"] = True

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
                pline["_name"] = name  # plotted name
                lname = "_candleplot"  # change name
                lines.append(lname)
                pline["ls"] = ""
                pline["marker"] = "d"
                pline["markersize"] = "7.0"
                pline["fillstyle"] = "full"
                plotlines[lname] = pline

            # Prepare dictionary for subclassing
            # 准备创建子类的字典
            clsdict = {
                "__module__": cls.__module__,
                "__doc__": str(_tabstract),
                "_tabstract": _tabstract,  # keep ref for lookback calcs
                "_iscandle": iscandle,
                "_unstable": unstable,
                "params": _tabstract.get_parameters(),
                "lines": tuple(lines),
                "plotinfo": plotinfo,
                "plotlines": plotlines,
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
            lsize = fsize - getattr(self, "_iscandle", False)
            if lsize == 1:  # only 1 output, no tuple returned
                self.lines[0].array = array.array(str("d"), output)

                if fsize > lsize:  # candle is present
                    candleref = narrays[self.CANDLEREF] * self.CANDLEOVER
                    output2 = candleref * (output / 100.0)
                    self.lines[1].array = array.array(str("d"), output2)

            else:
                for i, o in enumerate(output):
                    self.lines[i].array = array.array(str("d"), o)

        # 每个bar运行
        def next(self):
            # prepare the data arrays - single shot
            size = getattr(self, "_lookback", None) or len(self)
            narrays = [np.array(x.lines[0].get(size=size)) for x in self.datas]

            out = self._tafunc(*narrays, **self.p._getkwargs())

            fsize = self.size()
            lsize = fsize - getattr(self, "_iscandle", False)
            if lsize == 1:  # only 1 output, no tuple returned
                self.lines[0][0] = o = out[-1]

                if fsize > lsize:  # candle is present
                    candleref = narrays[self.CANDLEREF][-1] * self.CANDLEOVER
                    o2 = candleref * (o / 100.0)
                    self.lines[1][0] = o2

            else:
                for i, o in enumerate(out):
                    self.lines[i][0] = o[-1]

    # When importing the module do an automatic declaration of the indicators
    tafunctions = talib.get_functions()
    for tafunc in tafunctions:
        _TALibIndicator._subclass(tafunc)

    __all__ = tafunctions + ["MA_Type", "_TALibIndicator"]
