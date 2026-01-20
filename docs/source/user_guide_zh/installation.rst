====
安装
====

本指南介绍如何安装 Backtrader 并配置环境以获得最佳性能。

系统要求
--------

- **Python**: 3.9+（3.11+ 推荐，可提升约15%性能）
- **操作系统**: Windows / macOS / Linux
- **内存**: 建议 4GB+

核心依赖
~~~~~~~~

- **NumPy** >= 1.20.0
- **python-dateutil**

可选依赖
~~~~~~~~

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - 包名
     - 用途
   * - matplotlib
     - 静态图表绘制
   * - plotly
     - 交互式 HTML 图表（推荐）
   * - bokeh
     - 实时图表更新
   * - pandas
     - DataFrame 数据源
   * - scipy
     - 统计函数
   * - ib_insync
     - 盈透证券集成
   * - ccxt
     - 加密货币交易所集成

安装方法
--------

从 GitHub 安装（推荐）
~~~~~~~~~~~~~~~~~~~~

这是获取最新优化版本的推荐方法：

.. code-block:: bash

   # 从 GitHub 克隆
   git clone https://github.com/cloudQuant/backtrader.git
   cd backtrader
   
   # 安装依赖
   pip install -r requirements.txt
   
   pip install -U .

从 Gitee 安装（国内推荐）
~~~~~~~~~~~~~~~~~~~~~~

国内用户可使用 Gitee 镜像以获得更快的下载速度：

.. code-block:: bash

   git clone https://gitee.com/yunjinqi/backtrader.git
   cd backtrader
   pip install -r requirements.txt
   pip install -U .

安装可视化支持
~~~~~~~~~~~~~~

.. code-block:: bash

   # 安装所有绘图后端
   pip install matplotlib plotly bokeh

安装实盘交易支持
~~~~~~~~~~~~~~

.. code-block:: bash
   
   # 加密货币交易所
   pip install ccxt

虚拟环境（推荐）
~~~~~~~~~~~~

使用虚拟环境可以避免依赖冲突：

.. code-block:: bash

   # 创建虚拟环境
   python -m venv bt_env
   
   # 激活 (Linux/Mac)
   source bt_env/bin/activate
   
   # 激活 (Windows)
   bt_env\Scripts\activate
   
   # 安装 backtrader
   pip install -e .

性能优化
--------

Python 3.11+
~~~~~~~~~~~~

使用 Python 3.11+ 可提供约 15-20% 的速度提升：

.. code-block:: bash

   # 检查 Python 版本
   python --version
   
   # 如果需要，安装 Python 3.11+
   # 然后运行你的策略
   python3.11 your_strategy.py

Cython 加速
~~~~~~~~~~~

为了获得最佳性能，编译 Cython 扩展：

.. code-block:: bash

   # 安装 Cython
   pip install cython
   
   # 编译扩展（如果可用）
   python setup.py build_ext --inplace

验证安装
--------

验证安装是否成功：

.. code-block:: python

   import backtrader as bt
   print(f"Backtrader 版本: {bt.__version__}")

快速测试
~~~~~~~~

.. code-block:: python

   import backtrader as bt
   
   # 创建引擎
   cerebro = bt.Cerebro()
   cerebro.broker.setcash(100000)
   
   print(f'初始资金: {cerebro.broker.getvalue():.2f}')
   cerebro.run()
   print(f'最终资金: {cerebro.broker.getvalue():.2f}')
   print('安装成功！')

运行测试
~~~~~~~~

验证所有功能是否正常：

.. code-block:: bash

   # 运行测试套件
   pytest ./tests -n 4 -v

常见问题
--------

常见问题解决
~~~~~~~~~~~~

**ImportError: No module named 'backtrader'**

.. code-block:: bash

   # 确保在正确的环境中
   pip install -e .

**Matplotlib 后端问题**

.. code-block:: python

   import matplotlib
   matplotlib.use('Agg')  # 用于无头环境

**大数据集内存错误**

.. code-block:: python

   cerebro = bt.Cerebro(
       exactbars=True,   # 最小化内存使用
       stdstats=False    # 禁用观察者
   )

TA-Lib 安装
-----------

安装 TA-Lib 指标支持：

**macOS:**

.. code-block:: bash

   brew install ta-lib
   pip install TA-Lib

**Linux (Ubuntu/Debian):**

.. code-block:: bash

   sudo apt-get install ta-lib
   pip install TA-Lib

**Windows:**

从 https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib 下载预编译的 wheel

.. code-block:: bash

   pip install TA_Lib‑0.4.24‑cp311‑cp311‑win_amd64.whl

下一步
------

- :doc:`quickstart` - 第一个策略
- :doc:`concepts` - 核心概念
- :doc:`data_feeds` - 数据加载

参见
----

- `博客: 安装方法 <https://yunjinqi.blog.csdn.net/article/details/107594251>`_
- `GitHub 仓库 <https://github.com/cloudQuant/backtrader>`_
- `Gitee 镜像 (中国) <https://gitee.com/yunjinqi/backtrader>`_
