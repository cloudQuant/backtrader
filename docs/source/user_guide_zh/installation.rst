====
安装
====

系统要求
--------

- Python 3.7 或更高版本
- NumPy >= 1.20.0

可选依赖
~~~~~~~~

- **matplotlib**: 用于绑制图表
- **pandas**: 用于DataFrame数据源
- **pyfolio**: 用于高级分析
- **scipy**: 用于某些统计函数

安装方法
--------

从PyPI安装（推荐）
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   pip install backtrader

从源码安装
~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader
   pip install -e .

安装全部依赖
~~~~~~~~~~~~

.. code-block:: bash

   pip install backtrader[plotting]

开发环境安装
~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader
   pip install -e ".[dev]"

验证安装
--------

验证安装是否成功：

.. code-block:: python

   import backtrader as bt
   print(bt.__version__)

快速测试
~~~~~~~~

.. code-block:: python

   import backtrader as bt
   
   cerebro = bt.Cerebro()
   print('Cerebro 创建成功!')
