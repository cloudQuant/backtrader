=============
经纪商与订单
=============

Backtrader 提供了完整的经纪商模拟系统，可以模拟真实交易环境，
包括手续费、滑点、保证金和各种订单类型。

经纪商基础
----------

经纪商负责管理：

- **现金**：可用交易资金
- **市值**：总投资组合价值（现金 + 持仓）
- **持仓**：当前持有的头寸
- **订单**：订单管理和执行

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # 设置初始资金
   cerebro.broker.setcash(100000)
   
   # 获取当前值
   cash = cerebro.broker.getcash()
   value = cerebro.broker.getvalue()

手续费模型
----------

百分比手续费
^^^^^^^^^^^^

.. code-block:: python

   # 简单百分比手续费 (0.1%)
   cerebro.broker.setcommission(commission=0.001)
   
   # 带百分比的每笔交易手续费
   cerebro.broker.setcommission(
       commission=0.001,     # 每笔交易 0.1%
       margin=None,          # 无保证金要求
       mult=1.0              # 合约乘数
   )

固定手续费
^^^^^^^^^^

.. code-block:: python

   # 每笔交易固定手续费
   class FixedCommission(bt.CommInfoBase):
       params = (
           ('commission', 5.0),      # 每笔 5 元
           ('stocklike', True),
           ('commtype', bt.CommInfoBase.COMM_FIXED),
       )
       
       def _getcommission(self, size, price, pseudoexec):
           return self.p.commission
   
   cerebro.broker.addcommissioninfo(FixedCommission())

期货手续费
^^^^^^^^^^

.. code-block:: python

   # 期货带保证金和乘数
   cerebro.broker.setcommission(
       commission=2.0,       # 每手 2 元
       margin=5000,          # 每手保证金
       mult=10,              # 合约乘数
       commtype=bt.CommInfoBase.COMM_FIXED
   )

滑点
----

滑点模拟预期价格和实际成交价格之间的差异。

.. code-block:: python

   # 固定滑点（价格点数）
   cerebro.broker.set_slippage_fixed(fixed=0.01)
   
   # 百分比滑点
   cerebro.broker.set_slippage_perc(perc=0.001)  # 0.1%
   
   # 基于成交量的滑点
   cerebro.broker.set_slippage_perc(
       perc=0.001,
       slip_open=True,       # 应用于开盘订单
       slip_limit=False,     # 不应用于限价订单
       slip_match=True,      # 应用于匹配订单
       slip_out=False        # 不滑出最高/最低价范围
   )

订单类型
--------

市价订单
^^^^^^^^

以当前市场价格立即成交。

.. code-block:: python

   # 市价买入
   self.buy()
   
   # 市价卖出指定数量
   self.sell(size=100)

限价订单
^^^^^^^^

以指定价格或更优价格成交。

.. code-block:: python

   # 限价买入
   self.buy(exectype=bt.Order.Limit, price=100.0)
   
   # 限价卖出
   self.sell(exectype=bt.Order.Limit, price=110.0, size=50)

止损订单
^^^^^^^^

当价格达到触发价时执行。

.. code-block:: python

   # 止损买入（用于空头回补）
   self.buy(exectype=bt.Order.Stop, price=105.0)
   
   # 止损卖出
   self.sell(exectype=bt.Order.Stop, price=95.0)

止损限价订单
^^^^^^^^^^^^

止损和限价订单的组合。

.. code-block:: python

   # 止损限价订单
   self.buy(
       exectype=bt.Order.StopLimit,
       price=105.0,      # 止损触发价
       plimit=106.0      # 触发后的限价
   )

括号订单
^^^^^^^^

入场订单 + 止盈 + 止损。

.. code-block:: python

   # 括号订单（入场 + 止损 + 止盈）
   orders = self.buy_bracket(
       price=100.0,          # 入场价格（限价）
       stopprice=95.0,       # 止损价格
       limitprice=110.0,     # 止盈价格
       size=100
   )
   
   # 返回元组：(主订单, 止损订单, 限价订单)

目标订单
^^^^^^^^

自动计算订单数量以达到目标。

.. code-block:: python

   # 目标百分比
   self.order_target_percent(target=0.5)  # 投资组合的 50%
   
   # 目标数量
   self.order_target_size(target=100)     # 目标 100 股
   
   # 目标价值
   self.order_target_value(target=10000)  # 目标 10000 元仓位

订单管理
--------

订单状态
^^^^^^^^

.. code-block:: python

   def notify_order(self, order):
       if order.status in [order.Submitted, order.Accepted]:
           return  # 订单待处理
       
       if order.status == order.Completed:
           if order.isbuy():
               print(f'买入成交于 {order.executed.price:.2f}')
           else:
               print(f'卖出成交于 {order.executed.price:.2f}')
       
       elif order.status == order.Canceled:
           print('订单已取消')
       elif order.status == order.Margin:
           print('保证金不足')
       elif order.status == order.Rejected:
           print('订单被拒绝')

取消订单
^^^^^^^^

.. code-block:: python

   # 取消特定订单
   self.cancel(order)
   
   # 取消所有待处理订单
   for order in self.broker.get_orders_open():
       self.cancel(order)

订单有效期
^^^^^^^^^^

.. code-block:: python

   from datetime import datetime, timedelta
   
   # 指定日期前有效
   self.buy(
       exectype=bt.Order.Limit,
       price=100.0,
       valid=datetime.now() + timedelta(days=5)
   )
   
   # 撤销前有效（默认）
   self.buy(exectype=bt.Order.Limit, price=100.0, valid=None)
   
   # 当日有效
   self.buy(exectype=bt.Order.Limit, price=100.0, valid=bt.Order.DAY)

持仓管理
--------

.. code-block:: python

   def next(self):
       # 检查当前持仓
       if self.position:
           print(f'持仓数量: {self.position.size}')
           print(f'持仓均价: {self.position.price}')
           print(f'当前盈亏: {self.position.size * (self.data.close[0] - self.position.price)}')
       
       # 获取特定数据的持仓
       pos = self.getposition(self.datas[0])
       
       # 平仓所有头寸
       if self.position:
           self.close()

保证金与杠杆
------------

.. code-block:: python

   # 设置期货杠杆
   cerebro.broker.setcommission(
       commission=0.0,
       margin=10000,         # 每手保证金
       mult=50,              # 合约乘数
       leverage=10.0         # 最大杠杆
   )
   
   # 检查可用保证金
   def next(self):
       available_margin = self.broker.getcash()

Cheat-On-Open / Cheat-On-Close
------------------------------

回测便利的特殊执行模式：

.. code-block:: python

   # Cheat-On-Open: 订单在K线收盘时下达，在下一根K线开盘时执行
   cerebro.broker.set_coo(True)
   
   # Cheat-On-Close: 订单在当前K线收盘价下达并执行
   # 警告：不真实 - 仅用于特定测试场景
   cerebro.broker.set_coc(True)

.. warning::
   Cheat-On-Close 不真实，只应用于需要模拟以收盘价执行的特定测试场景。

Broker 方法参考
---------------

.. list-table::
   :widths: 35 65
   :header-rows: 1

   * - 方法
     - 描述
   * - ``set_cash(cash)``
     - 设置初始资金
   * - ``get_cash()``
     - 获取可用现金
   * - ``get_value()``
     - 获取投资组合总价值
   * - ``getposition(data)``
     - 获取某个数据源的持仓
   * - ``get_orders_open()``
     - 获取未成交订单列表
   * - ``set_slippage_perc(perc)``
     - 设置百分比滑点
   * - ``set_slippage_fixed(fixed)``
     - 设置固定滑点（点数）
   * - ``setcommission(...)``
     - 设置佣金参数
   * - ``set_coo(coo)``
     - 启用 Cheat-On-Open
   * - ``set_coc(coc)``
     - 启用 Cheat-On-Close
   * - ``add_cash(cash)``
     - 添加或减少资金（负值）

最佳实践
--------

1. **真实模拟**

   .. code-block:: python
   
      # 包含所有交易成本
      cerebro.broker.setcommission(commission=0.001)
      cerebro.broker.set_slippage_perc(perc=0.0005)

2. **订单跟踪**

   .. code-block:: python
   
      def __init__(self):
          self.order = None
      
      def next(self):
          if self.order:  # 检查是否有待处理订单
              return
          # 交易逻辑

3. **风险管理**

   .. code-block:: python
   
      def next(self):
          # 检查是否有足够资金
          if self.broker.getcash() < 1000:
              return
          
          # 仓位管理
          size = int(self.broker.getvalue() * 0.02 / self.data.close[0])
          if size > 0:
              self.buy(size=size)

参见
----

- :doc:`strategies` - 策略开发
- :doc:`analyzers` - 绩效分析
- :doc:`live_trading` - 实盘交易设置
- `博客: Broker使用方法 <https://yunjinqi.blog.csdn.net/article/details/113442367>`_
- `博客: 滑点设置 <https://yunjinqi.blog.csdn.net/article/details/113446335>`_
- `博客: 佣金设置 <https://yunjinqi.blog.csdn.net/article/details/113730323>`_
