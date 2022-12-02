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

import collections
import io
import itertools
import sys

import backtrader as bt
from backtrader.utils.py3 import (map, with_metaclass, string_types,
                                  integer_types)


# WriterBase类
class WriterBase(with_metaclass(bt.MetaParams, object)):
    pass


# WriterFile类
class WriterFile(WriterBase):
    """
    The system wide writer class.

    It can be parametrized with:

      - ``out`` (default: ``sys.stdout``): output stream to write to

        If a string is passed a filename with the content of the parameter will
        be used.

        If you wish to run with ``sys.stdout`` while doing multiprocess optimization, leave it as ``None``, which will
        automatically initiate ``sys.stdout`` on the child processes.

        # out 默认是 sys.stdout 如果是在多进程参数优化的过程中，想要把结果输出到标准输出中，把这个参数设置成None,会在每个自进程中自动设置
        # 如果传了一个filename给out,将会输出到这个filename中

      - ``close_out``  (default: ``False``)

        If ``out`` is a stream whether it has to be explicitly closed by the
        writer
        # 在out是一个数据流的情况下，是否需要writer明确的关闭

      - ``csv`` (default: ``False``)

        If a csv stream of the data feeds, strategies, observers and indicators
        has to be written to the stream during execution

        Which objects actually go into the csv stream can be controlled with
        the ``csv`` attribute of each object (defaults to ``True`` for ``data
        feeds`` and ``observers`` / False for ``indicators``)

        # 数据，策略，observers和indicators的csv数据流可以在执行的时候写入到文件里面，如果csv设置的是True的话
        # 是会被写入进去的

      - ``csv_filternan`` (default: ``True``) whether ``nan`` values have to be
        purged out of the csv stream (replaced by an empty field)

        # 在写入csv文件的时候，是否清除nan的值

      - ``csv_counter`` (default: ``True``) if the writer shall keep and print
        out a counter of the lines actually output

        # writer是否保存和打印实际上输出的那些lines,默认是True

      - ``indent`` (default: ``2``) indentation spaces for each level
        # 行首空格，默认是2

      - ``separators`` (default: ``['=', '-', '+', '*', '.', '~', '"', '^',
        '#']``)

        Characters used for line separators across section/sub(sub)sections

        # 分隔符，默认是['=', '-', '+', '*', '.', '~', '"', '^','#']

      - ``seplen`` (default: ``79``)

        total length of a line separator including indentation

        # 包括行首的分隔符的总的长度，默认是79

      - ``rounding`` (default: ``None``)

        Number of decimal places to round floats down to. With ``None`` no
        rounding is performed

        # 保存的小数是否四舍五入到某一位。默认不进行四舍五入。

    """
    params = (
        ('out', None),
        ('close_out', False),

        ('csv', False),
        ('csvsep', ','),
        ('csv_filternan', True),
        ('csv_counter', True),

        ('indent', 2),
        ('separators', ['=', '-', '+', '*', '.', '~', '"', '^', '#']),
        ('seplen', 79),
        ('rounding', None),
    )

    # 初始化
    def __init__(self):
        # _len是一个计数器
        self._len = itertools.count(1)
        # headers
        self.headers = list()
        # values
        self.values = list()

    # 开始输出
    def _start_output(self):
        # open file if needed
        # 如果没有out属性 或者 self.out是None
        if not hasattr(self, 'out') or not self.out:
            # 如果out参数是None,out设置成标准输出，并且close_out设置成False
            if self.p.out is None:
                self.out = sys.stdout
                self.close_out = False
            # 如果self.p.out是一个string_types,以写入方式打开文件，close_out需要设置成True
            elif isinstance(self.p.out, string_types):
                self.out = open(self.p.out, 'w')
                self.close_out = True
            # 如果self.p.out既不是None，也不是字符串格式，那么self.out等于self.p.out,self.close_out等于self.p.close_out
            else:
                self.out = self.p.out
                self.close_out = self.p.close_out

    # 开始
    def start(self):
        # 调用_start_output，准备好开始输出
        self._start_output()
        # 如果csv是True的话，
        if self.p.csv:
            # 写入line的分隔符
            self.writelineseparator()
            # 把列名写入到文件中，第一列默认是Id
            self.writeiterable(self.headers, counter='Id')

    # 结束，如果close_out是True的话，需要关闭self.out
    def stop(self):
        if self.close_out:
            self.out.close()

    # 如果csv是True的话，每次运行一次的时候，就values保存到self.out中，并把self.values设置成空列表
    def next(self):
        if self.p.csv:
            self.writeiterable(self.values, func=str, counter=next(self._len))
            self.values = list()

    # 如果csv是True的话，增加列名
    def addheaders(self, headers):
        if self.p.csv:
            self.headers.extend(headers)
    # 如果csv是True的话，如果需要过滤nan的话，就把nan替换成‘’，并把values添加到self.values
    def addvalues(self, values):
        if self.p.csv:
            if self.p.csv_filternan:
                values = map(lambda x: x if x == x else '', values)
            self.values.extend(values)

    # 把可迭代的对象进行处理，写入标准输出或者csv文件中
    def writeiterable(self, iterable, func=None, counter=''):
        # 如果保存csv的counter，在可迭代对象前加上一个counter
        if self.p.csv_counter:
            iterable = itertools.chain([counter], iterable)
        # 如果func不是None的话，把func应用与可迭代对象
        if func is not None:
            iterable = map(lambda x: func(x), iterable)
        # 把可迭代对象用csv分隔符进行分割，形成line
        line = self.p.csvsep.join(iterable)
        # 把line写入到self.out中
        self.writeline(line)

    # 把line写入到self.out中
    def writeline(self, line):
        self.out.write(line + '\n')

    # 把多条line写入到self.out中
    def writelines(self, lines):
        for l in lines:
            self.out.write(l + '\n')

    # 写入line的分隔符
    def writelineseparator(self, level=0):
        # 决定选用哪种分隔符，默认选择的是第一个分隔符"="
        sepnum = level % len(self.p.separators)
        separator = self.p.separators[sepnum]
        # 行首空格，默认是0
        line = ' ' * (level * self.p.indent)
        # 整个line的内容
        line += separator * (self.p.seplen - (level * self.p.indent))
        self.writeline(line)

    # 写入字典
    def writedict(self, dct, level=0, recurse=False):
        # 如果没有递归的话，写入line分隔符
        if not recurse:
            self.writelineseparator(level)
        # 首行缩进多少
        indent0 = level * self.p.indent
        # 迭代字典
        for key, val in dct.items():
            # 首行空格
            kline = ' ' * indent0
            # 如果递归，加上一个字符'- '
            if recurse:
                kline += '- '
            # 增加一个key :
            kline += str(key) + ':'
            # 判断val是不是一个lineseries的子类
            try:
                sclass = issubclass(val, bt.LineSeries)
            except TypeError:
                sclass = False
            # 如果是子类，加一个空格，增加val的名称
            if sclass:
                kline += ' ' + val.__name__
                self.writeline(kline)
            # 如果是字符串
            elif isinstance(val, string_types):
                # 把val添加到kline中
                kline += ' ' + val
                # 把kline写入到self.out中
                self.writeline(kline)
            # 如果是整数
            elif isinstance(val, integer_types):
                # 把val转化成字符串，添加到kline中
                kline += ' ' + str(val)
                self.writeline(kline)
            # 如果是一个浮点数
            elif isinstance(val, float):
                # 如果四舍五入不是None的话，就把浮点数进行四舍五入
                if self.p.rounding is not None:
                    val = round(val, self.p.rounding)
                # 把val转化成字符串，添加到kline中
                kline += ' ' + str(val)
                self.writeline(kline)
            # 如果val是一个字典
            elif isinstance(val, dict):
                # 如果是递归的话，写入level
                if recurse:
                    self.writelineseparator(level=level)
                self.writeline(kline)
                # 写入字典
                self.writedict(val, level=level + 1, recurse=True)
            # 如果val是一个可迭代对象
            elif isinstance(val, (list, tuple, collections.Iterable)):
                # 形成line,并保存到self.out中
                line = ', '.join(map(str, val))
                self.writeline(kline + ' ' + line)
            # 其他情况下，把val转成字符串，并保存
            else:
                kline += ' ' + str(val)
                self.writeline(kline)

# 写入StringIO
class WriterStringIO(WriterFile):
    # 参数out设置成了stringIO
    params = (('out', io.StringIO),)

    def __init__(self):
        super(WriterStringIO, self).__init__()

    def _start_output(self):
        super(WriterStringIO, self)._start_output()
        self.out = self.out()

    def stop(self):
        super(WriterStringIO, self).stop()
        # Leave the file positioned at the beginning
        self.out.seek(0)
