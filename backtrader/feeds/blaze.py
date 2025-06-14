#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from backtrader import date2num
import backtrader.feed as feed


# 这个类是backtrader对接Blaze数据的类
# blaze介绍可以看这个：https://blaze.readthedocs.io/en/latest/index.html
class BlazeData(feed.DataBase):
    """
    Support for `Blaze <blaze.pydata.org>`_ ``Data`` objects.

    Only numeric indices to columns are supported.

    Note:

      - The ``dataname`` parameter is a blaze ``Data`` object

      - A negative value in any of the parameters for the Data lines
        indicates it's not present in the DataFrame
        it is
    """

    # 参数
    params = (
        # datetime must be present
        ("datetime", 0),
        # pass -1 for any of the following to indicate absence
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
    )

    # 列名称
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]

    # 开始，直接把数据文件使用iter迭代，接下来_load的时候每次读取一行
    def __init__(self):
        self._rows = None

    def start(self):
        super(BlazeData, self).start()

        # reset the iterator on each start
        self._rows = iter(self.p.dataname)

    # load数据
    def _load(self):
        # 尝试获取下一行的数据，如果不存在，那么报错，返回False，代表数据已经load完毕
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        # Set the standard datafields - except for datetime
        # 设置除了时间之外的其他数据，这个跟CSV操作差不多
        for datafield in self.datafields[1:]:
            # get the column index
            colidx = getattr(self.params, datafield)

            if colidx < 0:
                # column not present -- skip
                continue

            # get the line to be set
            line = getattr(self.lines, datafield)
            line[0] = row[colidx]

        # datetime - assumed blaze always serves a native datetime.datetime
        # 处理时间部分，这部分操作相比于CSV部分的操作简单了很多，效率上应该也比较高，理论上会比CSV快一些
        # 获取数据第一列的index
        colidx = getattr(self.params, self.datafields[0])
        # 获取时间数据
        dt = row[colidx]
        # 把时间转化为数字
        dtnum = date2num(dt)

        # get the line to be set
        # 获取该列的line，然后添加数据
        line = getattr(self.lines, self.datafields[0])
        line[0] = dtnum

        # Done ... return
        return True
