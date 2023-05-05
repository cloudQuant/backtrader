# backtrader

#### 介绍
基于backtrader打造最好用的量化投研工具


#### 改进升级计划

- [x] 对backtrader源代码进行解读注释
- [ ] 2023年实现对接`vnpy` \ `qmt` \ `wxty` \ `ctp` 等实现实盘交易
- [ ] 基于`numpy` \ `cython` \ `numba` \ `c` \ `c++` \ `codon` 等对`backtrader`源代码进行改进优化，提高回测速度
- [x] 增加向量化回测函数, 进行因子回测，快速验证想法
- [x] 增加向量化回测函数, 进行时间序列回测，快速验证想法
- [ ] 增加向量化回测函数，用于在横截面上选股或者选品种，在时间序列上进行交易
- [ ] 优化backtrader滑点设置，实现可以和comminfo一样对于不同的data收取不同的滑点
- [ ] 优化backtrader涨跌停成交机制，增加一个参数控制是否限制一字涨停不允许成交
- [ ] 使用pyecharts\plotly\dash\bokeh优化backtrader的画图功能
- [ ] 针对期货和期权等有到期日的数据，增加功能在数据退市之后，自动剔除该数据，以提高速度

#### 安装教程
进入到目标路径下面，通常是/xxx/site-packages,然后进行clone
1.  cd  site-packages
2.  git clone https://gitee.com/quant-yunjinqi/backtrader.git

#### 使用说明

1. [参考官方的文档和论坛](https://www.backtrader.com/)
2. [参考我在csdn的付费专栏](https://blog.csdn.net/qq_26948675/category_10220116.html)
3.  网络上也有很多的backtrader的学习资源，大家可以百度

#### 相关改动

记录从2022年之后对backtrader的改动
- [x]    2023-05-05 这几天实现了ts代码，用于编写一些简单的时间序列上的策略，大幅提高了回测效率
- [x]    2023-03-03 修正了cs.py,cal_performance.py等代码上的小bug,提升了运行效率
- [x]    2022-12-18 修改了ts,cs回测框架的部分代码，避免部分bug
- [x]    2022-12-13 调整了sharpe.py的部分代码格式以便更好符合pep8规范，并且去掉了self.ratio的赋值
- [x]    2022-12-05 增加了基于pandas的向量化的单因子回测类，已经可以继承具体的类，编写alpha和signal实现简单回测了
- [x]    2022-12-1  修改plot中`drowdown`的拼写错误，改为drawdown
- [x]    2022-11-21 修改了comminfo.py中的getsize函数，把下单的时候取整数给去掉了，如果要下整数，在策略里面自己取整去控制
- [x]    2022-11-8 给data增加了name属性，使得data.name = data._name,方便写策略的时候规范调用
