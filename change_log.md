#### 相关改动
记录从2022年之后对backtrader的改动
- [x]    2025-03-19 remove with_metaclass, it means that backtrader will not support python2
- [x]    2025-03-08 实现了crypto的实盘模式, 把CryptoStore的单例模式去除, 允许一个进程中定义多个实例
- [x]    2025-02-01 修复了很多的代码格式，文档语法错误，大大减少pycharm警告
- [x]    2025-01-25 去除__future__的引用，后续只支持python3
- [x]    2024-03-15 创建了一个dev的分支，用于开发一些新的功能，后续主要在这个分支上进行更新
- [x]    2024-03-14 修复了cython文件编译不方便的问题
- [x]    2023-05-05 这几天实现了ts代码，用于编写一些简单的时间序列上的策略，大幅提高了回测效率
- [x]    2023-03-03 修正了cs.py,cal_performance.py等代码上的小bug,提升了运行效率
- [x]    2022-12-18 修改了ts,cs回测框架的部分代码，避免部分bug
- [x]    2022-12-13 调整了sharpe.py的部分代码格式以便更好符合pep8规范，并且去掉了self.ratio的赋值
- [x]    2022-12-05 增加了基于pandas的向量化的单因子回测类，已经可以继承具体的类，编写alpha和signal实现简单回测了
- [x]    2022-12-1  修改plot中`drowdown`的拼写错误，改为drawdown
- [x]    2022-11-21 修改了comminfo.py中的getsize函数，把下单的时候取整数给去掉了，如果要下整数，在策略里面自己取整去控制
- [x]    2022-11-8 给data增加了name属性，使得data.name = data._name,方便写策略的时候规范调用