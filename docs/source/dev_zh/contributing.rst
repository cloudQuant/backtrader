========
贡献指南
========

开发环境设置
------------

1. 克隆仓库：

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader

2. 创建虚拟环境：

.. code-block:: bash

   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # 或
   venv\Scripts\activate  # Windows

3. 安装开发依赖：

.. code-block:: bash

   pip install -e ".[dev]"

代码规范
--------

- 遵循 PEP 8 规范
- 使用 Google 风格的文档字符串
- 最大行长度：100 字符
- 尽可能使用类型提示

运行测试
--------

.. code-block:: bash

   # 运行所有测试
   pytest
   
   # 运行特定测试
   pytest tests/test_strategy.py
   
   # 带覆盖率运行
   pytest --cov=backtrader

文档
----

构建文档：

.. code-block:: bash

   cd docs
   make html      # 英文
   make html-zh   # 中文

Pull Request 指南
-----------------

1. Fork 仓库
2. 创建功能分支
3. 为新功能编写测试
4. 更新文档
5. 提交 Pull Request

提交信息规范
~~~~~~~~~~~~

使用约定式提交格式：

- ``feat: 添加新功能``
- ``fix: 修复bug``
- ``docs: 更新文档``
- ``test: 添加测试``
- ``refactor: 代码重构``
