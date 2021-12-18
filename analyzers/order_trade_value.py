#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 yunmjinqi
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

from collections import OrderedDict
from backtrader.utils.date import num2date
from backtrader import Analyzer
# 这个文件用于创建一个analyzer，来保存order、trade和value的数据
class OrderTradeValue(Analyzer):
    '''
    用于保存每个订单、交易和账户value的信息，这样便于回测后分析，避免了每次回测需要单独写

    Params:

      - (None)

    Member Attributes:


      - ``ret``: dictionary (key: year) of annual returns

    **get_analysis**:

      - Returns a dictionary of annual returns (key: year)
    '''
    params = ()

    def __init__(self):
        '''初始化'''
        super(OrderTradeValue, self).__init__()
        # 保存order、trade和value的数据
        self.ret={}
        self.ret['orders']=[]
        self.ret['trades']=[]
        self.ret['values']={}
        
    
    
    def next(self):
        current_date = num2date(self.datas[0].datetime[0])  #.strftime("%Y-%m-%d")
        total_value = self.strategy.broker.get_value()
        self.ret['values'][current_date] = total_value

    def stop(self):
      	pass
    
    def notify_order(self,order):
        self.ret['orders'].append(order)

        '''

        if order.status in [order.Submitted, order.Accepted]:
            # order被提交和接受
            return
        if order.status == order.Rejected:
            self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Margin:
            self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Cancelled:
            self.log(f"order is concelled : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Partial:
            self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status == order.Completed:
            if order.isbuy():
                self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
                            order.executed.price,order.executed.value,order.executed.comm))
                
            else:  # Sell
                self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
                            order.executed.price,order.executed.value,order.executed.comm)) 
        '''
    def notify_trade(self,trade):
        # 一个trade结束的时候输出信息
        self.ret['trades'].append(trade)
        '''
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}' .format(
                            trade.getdataname(),trade.pnl, trade.pnlcomm))
            self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])
            
        if trade.isopen:
            self.log('open symbol is : {} , price : {} ' .format(
                            trade.getdataname(),trade.price))
        '''
    
    # 上面这些函数，和在strategy里面的用法几乎一致，不需要过多的分析

    def get_analysis(self):
        '''用于获取analyzer运行的结果，self.rets'''
        
        return self.ret 
    
    

    