# backtrader

#### 介绍
基于backtrader打造最好用的量化投研工具


#### 改进升级计划

- [x] 对backtrader源代码进行解读注释
- [ ] 2023年实现对接`vnpy` \ `qmt` \ `wxty` \ `ctp` 等实现实盘交易
- [ ] 基于`numpy` \ `cython` \ `numba` \ `c` \ `c++` \ `codon` 等对`backtrader`源代码进行改进优化，提高回测速度
- [x] 增加向量化回测函数, 进行因子回测，快速验证想法

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

- [x]    2022-12-13 调整了sharpe.py的部分代码格式以便更好符合pep8规范，并且去掉了self.ratio的赋值
- [x]    2022-12-05 增加了基于pandas的向量化的单因子回测类，已经可以继承具体的类，编写alpha和signal实现简单回测了
- [x]    2022-12-1  修改plot中`drowdown`的拼写错误，改为drawdown
- [x]    2022-11-21 修改了comminfo.py中的getsize函数，把下单的时候取整数给去掉了，如果要下整数，在策略里面自己取整去控制
- [x]    2022-11-8 给data增加了name属性，使得data.name = data._name,方便写策略的时候规范调用
