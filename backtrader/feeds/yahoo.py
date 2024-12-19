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
from datetime import date, datetime
import io
import itertools

from ..utils.py3 import (urlopen, urlquote, ProxyHandler, build_opener,
                         install_opener)

import backtrader as bt
from .. import feed
from ..utils import date2num


class YahooFinanceCSVData(feed.CSVDataBase):
    '''
    Parses pre-downloaded Yahoo CSV Data Feeds (or locally generated if they
    comply to the Yahoo format)
    # 处理预下载的雅虎csv格式的数据或者说本地产生的符合雅虎格式的数据
    Specific parameters:
    # 特殊的参数：
      - ``dataname``: The filename to parse or a file-like object
        # 数据名称，准备处理的数据的地址，或者一个文件对象
      - ``reverse`` (default: ``False``)
        # 数据日期是否是反转的，假设本地存储的文件在下载过程中已经进行过反转
        It is assumed that locally stored files have already been reversed
        during the download process

      - ``adjclose`` (default: ``True``)
        # 是否使用分红或者送股调整后的价格，并且根据这个价格调整所有的数据
        Whether to use the dividend/split adjusted close and adjust all
        values according to it.

      - ``adjvolume`` (default: ``True``)
        # 如果使用了复权价格，并且这个参数设置成True的话，也会相应调整成交量
        Do also adjust ``volume`` if ``adjclose`` is also ``True``

      - ``round`` (default: ``True``)
        # 是否在复权后对复权价进行四舍五入，默认是需要在特定小数进行四舍五入
        Whether to round the values to a specific number of decimals after
        having adjusted the close

      - ``roundvolume`` (default: ``0``)
        # 对成交量进行复权之后四舍五入到的小数点位
        Round the resulting volume to the given number of decimals after having
        adjusted it

      - ``decimals`` (default: ``2``)
        # 四舍五入到的小数点位置
        Number of decimals to round to

      - ``swapcloses`` (default: ``False``)
        # 舍弃不用的参数，暂时保留
        [2018-11-16] It would seem that the order of *close* and *adjusted
        close* is now fixed. The parameter is retained, in case the need to
        swap the columns again arose.

    '''
    # 增加一个line
    lines = ('adjclose',)

    params = (
        ('reverse', False),
        ('adjclose', True),
        ('adjvolume', True),
        ('round', True),
        ('decimals', 2),
        ('roundvolume', False),
        ('swapcloses', False),
    )

    def start(self):
        super(YahooFinanceCSVData, self).start()
        # 如果reverse是False的话，直接return,下面就不在运行
        if not self.params.reverse:
            return

        # Yahoo sends data in reverse order and the file is still unreversed
        # 使用deque双向队列，添加到左边的时候，效率比list高很多，如果文件日期是反转的，那么
        # 传递数据的时候反转了一下，那么新的文件中，日期就是正的
        dq = collections.deque()
        for line in self.f:
            dq.appendleft(line)
        # 建立一个字符串缓存对象，并且把队列中的数据写入文件，把指针移动到第0个字符，关闭文件，把文件赋值给self.f
        f = io.StringIO(newline=None)
        f.writelines(dq)
        f.seek(0)
        self.f.close()
        self.f = f

    def _loadline(self, linetokens):
        # _loadline的代码相对来说比较熟悉，都比较类似
        # 一个while 循环
        while True:
            nullseen = False
            for tok in linetokens[1:]:
                if tok == 'null':
                    nullseen = True
                    linetokens = self._getnextline()  # refetch tokens
                    if not linetokens:
                        return False  # cannot fetch, go away

                    # out of for to carry on wiwth while True logic
                    break

            if not nullseen:
                break  # can proceed
        # 计数器，next(i)的时候值会增加1
        i = itertools.count(0)
        # 获取时间的字符串
        dttxt = linetokens[next(i)]
        # 生成时间
        dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
        # 把时间转化成数字
        dtnum = date2num(datetime.combine(dt, self.p.sessionend))
        # 给datetime的line赋值
        self.lines.datetime[0] = dtnum
        # 获取开高低收持仓量
        o = float(linetokens[next(i)])
        h = float(linetokens[next(i)])
        l = float(linetokens[next(i)])
        c = float(linetokens[next(i)])
        self.lines.openinterest[0] = 0.0

        # 2018-11-16 ... Adjusted Close seems to always be delivered after
        # the close and before the volume columns
        # 获取复权后的价格
        adjustedclose = float(linetokens[next(i)])
        # 尝试获取成交量，如果没有，设置成0
        try:
            v = float(linetokens[next(i)])
        except:  # cover the case in which volume is "null"
            v = 0.0
        # 如果交换收盘价和复权价，进行交换
        if self.p.swapcloses:  # swap closing prices if requested
            c, adjustedclose = adjustedclose, c
        # 计算复权因子，感觉计算复权因子的方式和常规用法有点不同，但是也不能说有问题
        adjfactor = c / adjustedclose

        # in v7 "adjusted prices" seem to be given, scale back for non adj
        # 如果需要调整价格的话，除以复权因子进行调整。
        if self.params.adjclose:
            o /= adjfactor
            h /= adjfactor
            l /= adjfactor
            c = adjustedclose
            # If the price goes down, volume must go up and viceversa
            # 如果调整成交量的话，这里逻辑略有问题，但是应该不影响使用，因为可能存在某些股票合并的情况
            # todo 注意逻辑
            if self.p.adjvolume:
                v *= adjfactor
        # 如果要四舍五入，对价格进行四舍五入
        if self.p.round:
            decimals = self.p.decimals
            o = round(o, decimals)
            h = round(h, decimals)
            l = round(l, decimals)
            c = round(c, decimals)
        # 对成交量进行四舍五入
        v = round(v, self.p.roundvolume)
        # 把计算得到的数据赋值给相应的line
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = l
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.adjclose[0] = adjustedclose

        return True


class YahooLegacyCSV(YahooFinanceCSVData):
    '''
    This is intended to load files which were downloaded before Yahoo
    discontinued the original service in May-2017
    # 用于load 2017年5月之前下载的数据
    '''
    params = (
        ('version', ''),
    )


class YahooFinanceCSV(feed.CSVFeedBase):
    DataCls = YahooFinanceCSVData


# todo 有时间测试一下这个类还能不能使用，如果可以用，尝试进行注释
class YahooFinanceData(YahooFinanceCSVData):
    # 这个是从雅虎上直接爬数据的方法
    '''
    Executes a direct download of data from Yahoo servers for the given time
    range.

    Specific parameters (or specific meaning):

      - ``dataname``

        The ticker to download ('YHOO' for Yahoo own stock quotes)

      - ``proxies``

        A dict indicating which proxy to go through for the download as in
        {'http': 'http://myproxy.com'} or {'http': 'http://127.0.0.1:8080'}

      - ``period``

        The timeframe to download data in. Pass 'w' for weekly and 'm' for
        monthly.

      - ``reverse``

        [2018-11-16] The latest incarnation of Yahoo online downloads returns
        the data in the proper order. The default value of ``reverse`` for the
        online download is therefore set to ``False``

      - ``adjclose``

        Whether to use the dividend/split adjusted close and adjust all values
        according to it.

      - ``urlhist``

        The url of the historical quotes in Yahoo Finance used to gather a
        ``crumb`` authorization cookie for the download

      - ``urldown``

        The url of the actual download server

      - ``retries``

        Number of times (each) to try to get a ``crumb`` cookie and download
        the data

      '''

    params = (
        ('proxies', {}),
        ('period', 'd'),
        ('reverse', False),
        ('urlhist', 'https://finance.yahoo.com/quote/{}/history'),
        ('urldown', 'https://query1.finance.yahoo.com/v7/finance/download'),
        ('retries', 3),
    )

    def start_v7(self):

        try:
            import requests
        except ImportError:
            msg = ('The new Yahoo data feed requires to have the requests '
                   'module installed. Please use pip install requests or '
                   'the method of your choice')
            raise Exception(msg)

        self.error = None
        url = self.p.urlhist.format(self.p.dataname)

        sesskwargs = dict()
        if self.p.proxies:
            sesskwargs['proxies'] = self.p.proxies

        crumb = None
        sess = requests.Session()
        for i in range(self.p.retries + 1):  # at least once
            resp = sess.get(url, **sesskwargs)
            if resp.status_code != requests.codes.ok:
                continue

            txt = resp.text
            i = txt.find('CrumbStore')
            if i == -1:
                continue
            i = txt.find('crumb', i)
            if i == -1:
                continue
            istart = txt.find('"', i + len('crumb') + 1)
            if istart == -1:
                continue
            istart += 1
            iend = txt.find('"', istart)
            if iend == -1:
                continue

            crumb = txt[istart:iend]
            crumb = crumb.encode('ascii').decode('unicode-escape')
            break

        if crumb is None:
            self.error = 'Crumb not found'
            self.f = None
            return

        crumb = urlquote(crumb)

        # urldown/ticker?period1=posix1&period2=posix2&interval=1d&events=history&crumb=crumb

        # Try to download
        urld = '{}/{}'.format(self.p.urldown, self.p.dataname)

        urlargs = []
        posix = date(1970, 1, 1)
        if self.p.todate is not None:
            period2 = (self.p.todate.date() - posix).total_seconds()
            urlargs.append('period2={}'.format(int(period2)))

        if self.p.todate is not None:
            period1 = (self.p.fromdate.date() - posix).total_seconds()
            urlargs.append('period1={}'.format(int(period1)))

        intervals = {
            bt.TimeFrame.Days: '1d',
            bt.TimeFrame.Weeks: '1wk',
            bt.TimeFrame.Months: '1mo',
        }

        urlargs.append('interval={}'.format(intervals[self.p.timeframe]))
        urlargs.append('events=history')
        urlargs.append('crumb={}'.format(crumb))

        urld = '{}?{}'.format(urld, '&'.join(urlargs))
        f = None
        for i in range(self.p.retries + 1):  # at least once
            resp = sess.get(urld, **sesskwargs)
            if resp.status_code != requests.codes.ok:
                continue

            ctype = resp.headers['Content-Type']
            # Cover as many text types as possible for Yahoo changes
            if not ctype.startswith('text/'):
                self.error = 'Wrong content type: %s' % ctype
                continue  # HTML returned? wrong url?

            # buffer everything from the socket into a local buffer
            try:
                # r.encoding = 'UTF-8'
                f = io.StringIO(resp.text, newline=None)
            except Exception:
                continue  # try again if possible

            break

        self.f = f

    def start(self):
        self.start_v7()

        # Prepared a "path" file -  CSV Parser can take over
        super(YahooFinanceData, self).start()



class YahooFinance(feed.CSVFeedBase):
    DataCls = YahooFinanceData
    # 获取具体的参数，形成元组
    params = DataCls.params._gettuple()
